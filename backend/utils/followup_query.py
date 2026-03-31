"""Helpers for follow-up query intent preservation in chat analytics flows."""

import re
from typing import Any, Dict, Optional


_TIME_PATTERN = re.compile(
    r"(last\s+\d+\s+(?:days?|weeks?|months?|years?)|"
    r"past\s+\d+\s+(?:days?|weeks?|months?|years?)|"
    r"for\s+last\s+\d+\s+(?:days?|weeks?|months?|years?)|"
    r"for\s+\d+\s+(?:days?|weeks?|months?|years?)|"
    r"this\s+(?:month|week|quarter|year)|"
    r"last\s+(?:month|week|quarter|year)|"
    r"previous\s+(?:month|week|quarter|year)|"
    r"(?:ytd|mtd|wtd)|"
    r"q[1-4]\s+\d{4})",
    re.IGNORECASE,
)

_PREV_TIME_PATTERN = re.compile(
    r"\b(last\s+\d+\s+(?:days?|weeks?|months?|years?)|"
    r"past\s+\d+\s+(?:days?|weeks?|months?|years?)|"
    r"for\s+last\s+\d+\s+(?:days?|weeks?|months?|years?)|"
    r"for\s+\d+\s+(?:days?|weeks?|months?|years?)|"
    r"this\s+(?:month|week|quarter|year)|"
    r"last\s+(?:month|week|quarter|year)|"
    r"previous\s+(?:month|week|quarter|year)|"
    r"(?:ytd|mtd|wtd)|"
    r"q[1-4]\s+\d{4}|"
    r"\d{4}-\d{2}-\d{2}\s*(?:to|through|-)\s*\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)


def _extract_time_phrase(query: str) -> Optional[str]:
    if not query:
        return None
    match = _TIME_PATTERN.search(query)
    return match.group(1).strip() if match else None


def is_time_only_followup_query(query: str) -> bool:
    """Return True for short follow-ups that only adjust time horizon."""
    if not query:
        return False

    q = query.strip().lower()
    if not q:
        return False

    explicit_scope_reset = ["overall", "total aws", "all services", "entire account"]
    if any(token in q for token in explicit_scope_reset):
        return False

    # If user explicitly asks for a new dimension, this is not time-only.
    explicit_dimension_terms = ["by region", "by service", "by account", "by usage", "by resource", "break down", "breakdown"]
    if any(token in q for token in explicit_dimension_terms):
        return False

    has_time = _extract_time_phrase(q) is not None
    if not has_time:
        return False

    words = re.findall(r"[a-z0-9-]+", q)
    if len(words) <= 7:
        return True

    starter_phrases = ["how about", "what about", "same for", "and for"]
    return any(q.startswith(phrase) for phrase in starter_phrases)


def build_contextual_followup_query(
    query: str,
    previous_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Rewrite time-only follow-ups onto previous analytical query context."""
    if not previous_context:
        return query

    if not is_time_only_followup_query(query):
        return query

    if previous_context.get("is_optimization"):
        return query

    prev_query = str(previous_context.get("last_query") or "").strip()
    if prev_query and prev_query.strip().lower() == query.strip().lower():
        prev_query = ""

    if not prev_query:
        prev_query = str(previous_context.get("previous_user_query") or "").strip()

    if not prev_query:
        history = previous_context.get("conversation_history") or []
        if isinstance(history, list):
            for msg in reversed(history):
                if str(msg.get("role", "")).lower() != "user":
                    continue
                content = str(msg.get("content") or "").strip()
                if content and content.lower() != query.strip().lower():
                    prev_query = content
                    break

    if not prev_query:
        return query

    time_phrase = _extract_time_phrase(query)
    if not time_phrase:
        return query

    if _PREV_TIME_PATTERN.search(prev_query):
        rewritten = _PREV_TIME_PATTERN.sub(time_phrase, prev_query, count=1)
        return rewritten.strip()

    if prev_query.endswith("?"):
        prev_query = prev_query[:-1]
    return f"{prev_query} for {time_phrase}".strip()
