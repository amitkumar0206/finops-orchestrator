"""
Hybrid query normalization service.

Provides deterministic normalization first, and selectively falls back to the LLM
when confidence is low or phrases are ambiguous. Designed to keep auditability,
avoid hallucinations, and prevent accidental leakage of sensitive tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, List
import re
import time
import structlog

from backend.services.llm_service import llm_service

logger = structlog.get_logger(__name__)


_AWS_KEY_PATTERN = re.compile(r"\b(A3T|AKIA|AROA|ASIA)[0-9A-Z]{16}\b")
_SECRET_KEY_PATTERN = re.compile(r"(?i)(aws)?_?secret(_access)?_key\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{20,})")
_TOKEN_PATTERN = re.compile(r"(?i)(password|token|apikey|api_key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}")


@dataclass
class NormalizationMetadata:
    """Structured metadata to describe normalization behaviour."""
    strategy: str = "deterministic"
    confidence: float = 0.65
    used_llm: bool = False
    cache_hit: bool = False
    transformations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    requires_disambiguation: bool = False
    intent_hint: Optional[str] = None
    time_range_hint: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "confidence": round(self.confidence, 2),
            "used_llm": self.used_llm,
            "cache_hit": self.cache_hit,
            "transformations": self.transformations,
            "warnings": self.warnings,
            "requires_disambiguation": self.requires_disambiguation,
            "intent_hint": self.intent_hint,
            "time_range_hint": self.time_range_hint,
            "notes": self.notes,
        }


class QueryNormalizer:
    """
    Hybrid normalizer that first applies deterministic heuristics and then, if required,
    calls a guarded LLM prompt to clarify intent.
    """

    def __init__(self):
        self._synonym_patterns: List[Tuple[re.Pattern, str]] = [
            (re.compile(r"\bspend(ing)?\b", re.IGNORECASE), "cost"),
            (re.compile(r"\bbill(ing)?\b", re.IGNORECASE), "cost"),
            (re.compile(r"\bcharges?\b", re.IGNORECASE), "cost"),
            (re.compile(r"\bprice\b", re.IGNORECASE), "cost"),
            (re.compile(r"\bhighest\b", re.IGNORECASE), "top"),
            (re.compile(r"\bmost\s+expensive\b", re.IGNORECASE), "top"),
            (re.compile(r"\bservices?\b", re.IGNORECASE), "services"),
            (re.compile(r"\bsku\b", re.IGNORECASE), "service"),
        ]
        self._intent_keywords = [
            "top", "rank", "cost", "trend", "breakdown",
            "optimize", "savings", "compare", "anomaly"
        ]
        # Simple LRU-style cache
        self._cache: Dict[str, Tuple[str, NormalizationMetadata]] = {}
        self._cache_order: List[str] = []
        self._cache_size = 256

    def _sanitize_for_llm(self, text: str) -> Tuple[str, List[str]]:
        """Redact obvious secrets before sending to any external model."""
        redactions: List[str] = []
        sanitized = text

        if _AWS_KEY_PATTERN.search(sanitized):
            sanitized = _AWS_KEY_PATTERN.sub("[REDACTED_AWS_KEY]", sanitized)
            redactions.append("access_key")
        if _SECRET_KEY_PATTERN.search(sanitized):
            sanitized = _SECRET_KEY_PATTERN.sub("secret_key=[REDACTED]", sanitized)
            redactions.append("secret_key")
        if _TOKEN_PATTERN.search(sanitized):
            sanitized = _TOKEN_PATTERN.sub(r"\1=[REDACTED]", sanitized)
            redactions.append("token")

        return sanitized, redactions

    def _apply_deterministic_rules(self, query: str) -> Tuple[str, NormalizationMetadata]:
        """Apply lightweight deterministic clean-up rules."""
        metadata = NormalizationMetadata()
        normalized = query.strip()

        collapsed = re.sub(r"\s+", " ", normalized)
        if collapsed != normalized:
            metadata.transformations.append("collapse_whitespace")
            normalized = collapsed

        # Replace synonyms with canonical words to aid downstream matching
        for pattern, replacement in self._synonym_patterns:
            new_text, count = pattern.subn(replacement, normalized)
            if count > 0:
                metadata.transformations.append(f"synonym:{pattern.pattern}->{replacement}")
                normalized = new_text

        lowered = normalized.lower()
        intent_hits = sum(1 for kw in self._intent_keywords if kw in lowered)

        # Confidence heuristic: base 0.6 plus increments for recognised patterns
        confidence = 0.55 + min(intent_hits, 4) * 0.1
        confidence = min(confidence, 0.9)
        metadata.confidence = confidence

        if "?" in normalized or len(normalized) < 12:
            metadata.requires_disambiguation = True
            metadata.warnings.append("query_may_be_too_short")
            metadata.confidence = min(metadata.confidence, 0.7)

        return normalized, metadata

    def _update_cache(self, key: str, value: Tuple[str, NormalizationMetadata]) -> None:
        if key in self._cache:
            self._cache[key] = value
            # Move to end
            if key in self._cache_order:
                self._cache_order.remove(key)
            self._cache_order.append(key)
            return

        if len(self._cache_order) >= self._cache_size:
            oldest = self._cache_order.pop(0)
            self._cache.pop(oldest, None)

        self._cache[key] = value
        self._cache_order.append(key)

    def _get_cache(self, key: str) -> Optional[Tuple[str, NormalizationMetadata]]:
        cached = self._cache.get(key)
        if cached:
            # refresh order
            if key in self._cache_order:
                self._cache_order.remove(key)
            self._cache_order.append(key)
        return cached

    async def normalize(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Normalize a natural language cost-analysis query.

        Returns normalized text and metadata describing which steps were applied.
        """
        if not query:
            return "", NormalizationMetadata(confidence=0.0, warnings=["empty_query"]).as_dict()

        cache_key = query.strip().lower()
        cached = self._get_cache(cache_key)
        if cached:
            normalized, metadata = cached
            metadata.cache_hit = True
            logger.debug("Query normalizer cache hit", normalized=normalized)
            return normalized, metadata.as_dict()

        start_time = time.perf_counter()
        deterministic_query, metadata = self._apply_deterministic_rules(query)

        # If deterministic phase already strong enough, skip LLM
        if metadata.confidence >= 0.75 or not llm_service.initialized:
            elapsed = time.perf_counter() - start_time
            metadata.notes.append(f"deterministic_elapsed_ms={int(elapsed * 1000)}")
            self._update_cache(cache_key, (deterministic_query, metadata))
            return deterministic_query, metadata.as_dict()

        sanitized, redactions = self._sanitize_for_llm(query)

        if not sanitized.strip():
            metadata.warnings.append("sanitized_query_empty")
            elapsed = time.perf_counter() - start_time
            metadata.notes.append(f"deterministic_elapsed_ms={int(elapsed * 1000)}")
            self._update_cache(cache_key, (deterministic_query, metadata))
            return deterministic_query, metadata.as_dict()

        metadata.notes.append(f"redacted_fields={','.join(redactions) if redactions else 'none'}")

        llm_context = {
            "previous_intent": context.get("last_intent") if context else None,
            "previous_time_range": context.get("last_time_range") if context else None,
            "previous_dimensions": context.get("last_dimensions") if context else None,
        }

        try:
            llm_result = await llm_service.normalize_query_prompt(sanitized, llm_context)
        except Exception as exc:
            logger.warning("LLM normalization failed, continuing with deterministic result", error=str(exc))
            metadata.warnings.append("llm_fallback_error")
            elapsed = time.perf_counter() - start_time
            metadata.notes.append(f"deterministic_elapsed_ms={int(elapsed * 1000)}")
            self._update_cache(cache_key, (deterministic_query, metadata))
            return deterministic_query, metadata.as_dict()

        if not llm_result or "normalized_query" not in llm_result:
            metadata.warnings.append("llm_returned_empty")
            elapsed = time.perf_counter() - start_time
            metadata.notes.append(f"deterministic_elapsed_ms={int(elapsed * 1000)}")
            self._update_cache(cache_key, (deterministic_query, metadata))
            return deterministic_query, metadata.as_dict()

        normalized_query = llm_result.get("normalized_query", "").strip()
        if not normalized_query:
            metadata.warnings.append("llm_returned_blank")
            elapsed = time.perf_counter() - start_time
            metadata.notes.append(f"deterministic_elapsed_ms={int(elapsed * 1000)}")
            self._update_cache(cache_key, (deterministic_query, metadata))
            return deterministic_query, metadata.as_dict()

        metadata.strategy = "llm_fallback"
        metadata.used_llm = True
        metadata.intent_hint = llm_result.get("intent_hint")
        metadata.time_range_hint = llm_result.get("time_range_hint")
        metadata.requires_disambiguation = bool(llm_result.get("requires_disambiguation", False))
        metadata.confidence = max(metadata.confidence, float(llm_result.get("confidence", 0.0)))
        metadata.transformations.append("llm_structured_normalization")

        if llm_result.get("notes"):
            metadata.notes.extend(llm_result["notes"])

        elapsed = time.perf_counter() - start_time
        metadata.notes.append(f"total_elapsed_ms={int(elapsed * 1000)}")

        self._update_cache(cache_key, (normalized_query, metadata))
        return normalized_query, metadata.as_dict()


# Shared instance
query_normalizer = QueryNormalizer()

