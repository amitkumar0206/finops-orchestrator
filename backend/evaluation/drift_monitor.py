"""Drift Monitor

Loads recent evaluation result files and computes moving accuracy + intent shifts.
Intended to be run periodically (e.g., cron or scheduled task).
"""
from __future__ import annotations
import json, os
from glob import glob
from collections import Counter, deque

RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')
WINDOW = 5  # number of recent evaluations


def load_recent():
    paths = sorted(glob(os.path.join(RESULTS_DIR, 'eval_*.json')))[-WINDOW:]
    datasets = []
    for p in paths:
        try:
            with open(p, 'r', encoding='utf-8') as f:
                datasets.append(json.load(f))
        except Exception:
            continue
    return datasets


def analyze(datasets):
    if not datasets:
        return {'message': 'No datasets'}
    accuracies = [d['metrics']['overall_pass_rate'] for d in datasets if 'metrics' in d]
    moving_accuracy = sum(accuracies) / len(accuracies) if accuracies else 0.0
    intent_counts = Counter()
    for d in datasets:
        for r in d.get('records', []):
            intent_counts[r.get('actual_intent')] += 1
    return {
        'moving_accuracy': moving_accuracy,
        'total_evaluations': len(datasets),
        'intent_distribution': dict(intent_counts)
    }


def main():
    datasets = load_recent()
    summary = analyze(datasets)
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
