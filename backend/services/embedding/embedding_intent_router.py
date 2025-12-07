"""Embedding-based Intent Router

Computes semantic similarity between the query and canonical intent exemplars.
Used to adjust UPS-extracted intent & confidence or provide a fallback when
UPS confidence is marginal (< threshold).

Design:
- Load sentence-transformers model once (lazy singleton)
- Maintain canonical examples per intent
- Provide route_intent(query) -> {intent, similarity_map}
- Expose adjust(intent, ups_confidence) to raise confidence if embedding strongly supports selection

NOTE: For performance in container environments, consider switching to a smaller model later.
"""
from __future__ import annotations

import threading
from functools import lru_cache
from typing import Dict, List, Tuple
import structlog

try:
    from sentence_transformers import SentenceTransformer, util
except Exception:  # pragma: no cover - model import errors
    SentenceTransformer = None  # type: ignore
    util = None  # type: ignore

logger = structlog.get_logger(__name__)

_INTENT_EXAMPLES: Dict[str, List[str]] = {
    "COST_BREAKDOWN": [
        "Break down AWS cost by service",
        "Show cost distribution by region",
        "List spending grouped by account"
    ],
    "TOP_N_RANKING": [
        "Top 5 most expensive services",
        "Highest cost drivers this month",
        "Rank services by spend"
    ],
    "ANOMALY_ANALYSIS": [
        "Why was there a spike yesterday",
        "Investigate unusual cost surge",
        "Explain cost anomaly"
    ],
    "COST_TREND": [
        "Show cost trend over time",
        "Monthly cost trajectory",
        "Daily spending pattern",
        "Show monthly costs for last year",
        "Cost trend month by month",
        "Week over week cost trend",
        "Month by month cost progression",
        "Monthly cost evolution",
        "Cost over the past 6 months"
    ],
    "UTILIZATION": [
        "Idle instance utilization details",
        "Underutilized resources report",
        "Show usage efficiency"
    ],
    "OPTIMIZATION": [
        "Optimize EC2 spend",
        "Cost saving recommendations",
        "Rightsizing opportunities"
    ],
    "GOVERNANCE": [
        "List untagged resources",
        "Tag compliance issues",
        "Show policy violations"
    ],
    "DATA_METADATA": [
        "CUR record ingestion status",
        "Missing data gaps",
        "Cost data health"
    ],
    "COMPARATIVE": [
        "Compare dev vs prod costs",
        "Cost difference between accounts",
        "Contrast last month vs this month",
        "Compare Q3 vs Q4 spend",
        "Compare this month vs last month",
        "Difference between current and previous month",
        "Compare with previous period",
        "Current period vs previous period",
        "Show growth from last period",
        "Period over period comparison"
    ],
    "OTHER": [
        "General cost question",
        "Miscellaneous inquiry"
    ]
}

_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_lock = threading.Lock()
_model = None

@lru_cache(maxsize=1)
def _load_model():
    global _model
    if _model is None and SentenceTransformer is not None:
        with _lock:
            if _model is None:
                logger.info("Loading embedding model", model=_MODEL_NAME)
                _model = SentenceTransformer(_MODEL_NAME)
    return _model


def route_intent(query: str) -> Dict[str, float]:
    """Return similarity scores per intent for the given query."""
    if SentenceTransformer is None:
        logger.warning("SentenceTransformer not available; returning empty similarity map")
        return {}
    model = _load_model()
    # Build corpus of exemplar sentences with mapping
    corpus_sentences: List[str] = []
    corpus_labels: List[str] = []
    for intent, examples in _INTENT_EXAMPLES.items():
        for ex in examples:
            corpus_sentences.append(ex)
            corpus_labels.append(intent)
    query_emb = model.encode(query, convert_to_tensor=True)
    corpus_emb = model.encode(corpus_sentences, convert_to_tensor=True)
    sims = util.cos_sim(query_emb, corpus_emb)[0]  # shape: (len(corpus))
    # Aggregate max similarity per intent
    intent_scores: Dict[str, float] = {}
    for idx, sim in enumerate(sims):
        intent = corpus_labels[idx]
        score = float(sim)
        if intent not in intent_scores or score > intent_scores[intent]:
            intent_scores[intent] = score
    return intent_scores


def choose_intent(similarity_map: Dict[str, float]) -> Tuple[str, float]:
    if not similarity_map:
        return "OTHER", 0.0
    intent = max(similarity_map, key=similarity_map.get)
    return intent, similarity_map[intent]


def adjust_intent(original_intent: str, ups_confidence: float, similarity_map: Dict[str, float], similarity_threshold: float = 0.68) -> Tuple[str, float, bool]:
    """Adjust intent if embeddings strongly support a different one.

    Returns (final_intent, final_confidence, changed)
    
    NOTE: Threshold raised to 0.68 to prevent false overrides.
    Embedding scores must be significantly higher to override UPS extraction.
    """
    if not similarity_map:
        return original_intent, ups_confidence, False
    best_intent, best_score = choose_intent(similarity_map)
    # Only override if: 1) score above threshold, 2) significantly better than original (0.10 margin)
    if best_intent != original_intent and best_score >= similarity_threshold and best_score - similarity_map.get(original_intent, 0.0) > 0.10:
        # Switch intent
        new_conf = max(ups_confidence, min(0.95, best_score))
        logger.info("Embedding router intent override", from_intent=original_intent, to_intent=best_intent, emb_score=best_score)
        return best_intent, new_conf, True
    # Boost confidence if consistent
    if best_intent == original_intent and best_score >= similarity_threshold:
        boosted = max(ups_confidence, min(0.9, best_score + 0.05))
        return original_intent, boosted, False
    return original_intent, ups_confidence, False


class EmbeddingIntentRouter:
    def route(self, query: str, original_intent: str, ups_confidence: float) -> Dict[str, any]:
        sims = route_intent(query)
        final_intent, final_conf, changed = adjust_intent(original_intent, ups_confidence, sims)
        return {
            "similarities": sims,
            "final_intent": final_intent,
            "final_confidence": final_conf,
            "changed": changed,
        }

embedding_intent_router = EmbeddingIntentRouter()
