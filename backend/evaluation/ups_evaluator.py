"""UPS Evaluation Harness

Runs a deterministic evaluation of the UPS-based intent classification/extraction.
Uses heuristic mode by setting UPS_DISABLE_LLM=1 (avoids external LLM calls).

Metrics:
- Intent accuracy
- Per-intent precision/recall
- Top-N extraction accuracy
- Dimension extraction accuracy
- Time range explicitness correctness (explicit vs inherited vs default)

Usage:
  python backend/evaluation/ups_evaluator.py
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
import os
from typing import List, Dict, Any
from collections import defaultdict, Counter

# Force heuristic mode for reproducibility
os.environ.setdefault("UPS_DISABLE_LLM", "1")

from backend.agents.intent_classifier import intent_classifier  # noqa: E402

SAMPLE_FILE = os.path.join(os.path.dirname(__file__), "sample_queries.json")

@dataclass
class EvalRecord:
    query: str
    expected: Dict[str, Any]
    actual: Dict[str, Any]
    passed: bool
    details: Dict[str, Any] = field(default_factory=dict)


def load_samples(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def classify_time_range_kind(actual_params: Dict[str, Any]) -> str:
    tr = actual_params.get("time_range")
    if not tr:
        return "missing"
    src = tr.get("source")
    if src == "explicit":
        return "explicit"
    if src == "default":
        return "default"
    return src or "unknown"


def evaluate_sample(sample: Dict[str, Any], previous_time_range: Dict[str, Any] | None) -> EvalRecord:
    query = sample["query"]
    expected_intent = sample.get("expected_intent")
    context = {}
    if previous_time_range:
        context["time_range"] = previous_time_range
    result = intent_classifier.classify.__wrapped__(intent_classifier, query, context) if hasattr(intent_classifier.classify, "__wrapped__") else None  # type: ignore
    if result is None:
        # async method fallback - run loop
        import asyncio
        result = asyncio.run(intent_classifier.classify(query, context))

    actual_intent = result.get("intent")
    actual_params = result.get("extracted_params", {})
    previous_time_range_after = actual_params.get("time_range") or previous_time_range

    expected_dimensions = set(sample.get("expected_dimensions", []))
    actual_dimensions = set(actual_params.get("dimensions", [])) if actual_params.get("dimensions") else set()
    dim_ok = expected_dimensions.issubset(actual_dimensions)

    expected_services = set(sample.get("expected_services", []))
    actual_services = set(actual_params.get("services", [])) if actual_params.get("services") else set()
    svc_ok = expected_services.issubset(actual_services)

    expected_top_n = sample.get("expected_top_n")
    actual_top_n = actual_params.get("top_n")
    topn_ok = (expected_top_n is None) or (expected_top_n == actual_top_n)

    expected_tr_kind = sample.get("expected_time_range_kind")
    actual_tr_kind = classify_time_range_kind(actual_params)
    tr_ok = (expected_tr_kind is None) or (expected_tr_kind == actual_tr_kind or (expected_tr_kind == "inherited" and actual_tr_kind in {"explicit", "default"}))

    passed = all([
        actual_intent == expected_intent,
        dim_ok,
        svc_ok,
        topn_ok,
        tr_ok,
    ])

    details = {
        "expected_intent": expected_intent,
        "actual_intent": actual_intent,
        "expected_dimensions": list(expected_dimensions),
        "actual_dimensions": list(actual_dimensions),
        "expected_services": list(expected_services),
        "actual_services": list(actual_services),
        "expected_top_n": expected_top_n,
        "actual_top_n": actual_top_n,
        "expected_time_range_kind": expected_tr_kind,
        "actual_time_range_kind": actual_tr_kind,
        "confidence": result.get("confidence"),
    }

    return EvalRecord(
        query=query,
        expected=sample,
        actual=result,
        passed=passed,
        details=details,
    ), previous_time_range_after


def aggregate(records: List[EvalRecord]) -> Dict[str, Any]:
    intent_counts = Counter()
    intent_correct = Counter()
    confusion = defaultdict(lambda: Counter())  # expected -> actual counts
    for r in records:
        expected_intent = r.details["expected_intent"]
        actual_intent = r.details["actual_intent"]
        intent_counts[expected_intent] += 1
        confusion[expected_intent][actual_intent] += 1
        if actual_intent == expected_intent:
            intent_correct[expected_intent] += 1

    intent_accuracy = {
        intent: intent_correct[intent] / count for intent, count in intent_counts.items()
    }
    overall = sum(1 for r in records if r.passed) / len(records) if records else 0.0

    # Precision/Recall per intent (treat each intent one-vs-all)
    all_intents = set(intent_counts.keys()) | {ai for r in records for ai in [r.details['actual_intent']]}
    pr_table = {}
    for intent in all_intents:
        tp = confusion[intent][intent]
        fp = sum(confusion[other][intent] for other in all_intents if other != intent)
        fn = sum(confusion[intent][other] for other in all_intents if other != intent)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        pr_table[intent] = {"precision": precision, "recall": recall}

    confusion_matrix = {
        exp: dict(act_counts) for exp, act_counts in confusion.items()
    }

    return {
        "overall_pass_rate": overall,
        "intent_accuracy": intent_accuracy,
        "precision_recall": pr_table,
        "confusion_matrix": confusion_matrix,
        "total_samples": len(records),
    }


def main():
    samples = load_samples(SAMPLE_FILE)
    records: List[EvalRecord] = []
    prev_tr = None
    for sample in samples:
        record, prev_tr = evaluate_sample(sample, prev_tr)
        records.append(record)

    metrics = aggregate(records)

    # Structured output
    output = {
        "metrics": metrics,
        "records": [
            {
                "query": r.query,
                "passed": r.passed,
                **r.details,
            } for r in records
        ]
    }

    # Persist results
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"eval_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(json.dumps(output, indent=2))
    print(f"Saved evaluation to {out_path}")

if __name__ == "__main__":
    main()
