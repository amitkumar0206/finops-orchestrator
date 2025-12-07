"""Service Resolver for mapping user-entered AWS service phrases to CUR product codes.

Layered resolution strategy (phase 1 implementation):
1. Static synonym dictionary (existing SERVICE_NAME_TO_PRODUCT_CODE in athena_executor).
2. Fuzzy match across distinct CUR product codes loaded from Athena.
   - Uses rapidfuzz to score candidates.
3. (Future) Embeddings + constrained LLM selection.

This module intentionally avoids direct boto3 calls for easier unit testing; the
Athena executor injects the product codes via `update_product_codes`.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set, Tuple
from rapidfuzz import fuzz, process
import structlog
import json
from typing import Optional as Opt
from . import service_resolution_metrics as metrics

logger = structlog.get_logger(__name__)

@dataclass
class ResolutionResult:
    product_code: Optional[str]
    method: str  # 'dict' | 'fuzzy' | 'ambiguous' | 'fallback'
    confidence: float
    candidates: List[Tuple[str, float]]
    original: str
    normalized: str
    needs_clarification: bool = False

class ServiceResolver:
    def __init__(self, synonym_dict: dict, llm_service: Opt[any] = None):
        self._synonym_dict = synonym_dict  # keys are pre-normalized
        self._product_codes: Set[str] = set()
        self._min_fuzzy_threshold: float = 80.0  # initial threshold, adjustable
        self._llm_service = llm_service
        self._llm_cache: dict = {}  # phrase -> product_code cache

    @staticmethod
    def _normalize(text: str) -> str:
        return text.lower().strip().replace(" ", "").replace("_", "").replace("-", "")

    def update_product_codes(self, codes: Iterable[str]) -> None:
        # Accept new product codes (distinct CUR line_item_product_code values)
        cleaned = {c for c in codes if c and isinstance(c, str)}
        self._product_codes = cleaned
        logger.info("ServiceResolver product codes updated", count=len(self._product_codes))

    def resolve(self, phrase: str) -> ResolutionResult:
        if not phrase:
            metrics.resolution_counter.labels(method="fallback").inc()
            return ResolutionResult(None, 'fallback', 0.0, [], phrase, '')
        normalized = self._normalize(phrase)

        # 1. Dictionary lookup
        if normalized in self._synonym_dict:
            pc = self._synonym_dict[normalized]
            metrics.resolution_counter.labels(method="dict").inc()
            return ResolutionResult(pc, 'dict', 1.0, [(pc, 100.0)], phrase, normalized)

        # 2. Fuzzy across product codes (only if we have codes)
        candidates: List[Tuple[str, float]] = []
        if self._product_codes:
            # Use rapidfuzz process.extract to get top matches
            extracted = process.extract(phrase, list(self._product_codes), scorer=fuzz.WRatio, limit=5)
            candidates = [(cand, float(score)) for cand, score, _ in extracted]
            best = candidates[0] if candidates else (None, 0.0)
            second = candidates[1] if len(candidates) > 1 else (None, 0.0)
            # Ambiguity detection: if scores close and below high threshold
            if best[0] and best[1] >= self._min_fuzzy_threshold:
                # If second candidate is very close (<3 difference) mark ambiguous
                if second[0] and abs(best[1] - second[1]) < 3:
                    metrics.resolution_counter.labels(method="ambiguous").inc()
                    return ResolutionResult(None, 'ambiguous', best[1] / 100.0, candidates, phrase, normalized, needs_clarification=True)
                metrics.resolution_counter.labels(method="fuzzy").inc()
                return ResolutionResult(best[0], 'fuzzy', best[1] / 100.0, candidates, phrase, normalized)

        # 3. Try LLM resolution if available and we have candidates to choose from
        if self._llm_service and candidates:
            # Check cache first
            if phrase in self._llm_cache:
                cached = self._llm_cache[phrase]
                metrics.resolution_counter.labels(method="llm_cached").inc()
                return ResolutionResult(cached, 'llm', 1.0, candidates, phrase, normalized)
            # LLM resolution with constrained prompt (sync wrapper around async)
            llm_result = self._resolve_with_llm_sync(phrase, candidates[:5])
            if llm_result:
                self._llm_cache[phrase] = llm_result
                metrics.resolution_counter.labels(method="llm").inc()
                return ResolutionResult(llm_result, 'llm', 0.9, candidates, phrase, normalized)
        
        # 4. Fallback - no confident match
        metrics.resolution_counter.labels(method="fallback").inc()
        return ResolutionResult(None, 'fallback', 0.0, candidates, phrase, normalized)

    def _resolve_with_llm_sync(self, phrase: str, candidates: List[Tuple[str, float]]) -> Opt[str]:
        """Synchronous wrapper for LLM resolution (calls async internally)."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If already in event loop, create task and return None (async context will handle)
                logger.warning("Cannot use LLM resolution in running event loop, skipping")
                return None
            return loop.run_until_complete(self._resolve_with_llm(phrase, candidates))
        except RuntimeError:
            # No event loop, create one
            return asyncio.run(self._resolve_with_llm(phrase, candidates))

    async def _resolve_with_llm(self, phrase: str, candidates: List[Tuple[str, float]]) -> Opt[str]:
        """Use LLM to select correct AWS service product code from candidates."""
        if not self._llm_service:
            return None
        try:
            candidate_list = "\n".join([f"- {code} (fuzzy score: {score:.1f})" for code, score in candidates])
            prompt = f"""You are helping map user-entered AWS service names to official AWS CUR product codes.

User phrase: "{phrase}"

Candidate product codes from CUR data (ranked by fuzzy similarity):
{candidate_list}

Select the SINGLE most appropriate product code that matches the user's intent. Respond ONLY with valid JSON in this exact format:
{{"product_code": "<exact-code-from-list>"}}

If none match confidently, respond:
{{"product_code": null}}

Rules:
1. Only return codes from the candidate list above
2. Consider common AWS service naming (e.g., "VPC" → "AmazonVPC", "EC2" → "AmazonEC2")
3. No explanations, just the JSON object"""

            response = await self._llm_service.call_llm(prompt)
            parsed = json.loads(response.strip())
            selected = parsed.get("product_code")
            if selected and any(selected == c[0] for c in candidates):
                logger.info("LLM resolved service name", phrase=phrase, selected=selected)
                return selected
            logger.warning("LLM returned invalid or null product code", phrase=phrase, response=parsed)
            return None
        except Exception as e:
            logger.warning("LLM resolution failed", phrase=phrase, error=str(e))
            return None

__all__ = ["ServiceResolver", "ResolutionResult"]
