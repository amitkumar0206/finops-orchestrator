"""Confidence Threshold Calibration

Reads latest evaluation results and proposes per-intent confidence thresholds.
Strategy:
- For each intent collect confidence values for correct vs incorrect classifications.
- Threshold = max( min_correct_confidence - margin , default_min )
- Margin = 0.05; default_min = 0.4
Writes backend/config/intent_thresholds.json
"""
from __future__ import annotations
import json, os
from glob import glob
from statistics import mean

RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'intent_thresholds.json')
DEFAULT_MIN = 0.4
MARGIN = 0.05

def load_latest_results():
    paths = sorted(glob(os.path.join(RESULTS_DIR, 'eval_*.json')))
    if not paths:
        return None
    with open(paths[-1], 'r', encoding='utf-8') as f:
        return json.load(f)


def calibrate(data):
    # Build per-intent confidence sets
    per_intent_correct = {}
    per_intent_incorrect = {}
    for rec in data['records']:
        intent = rec['expected_intent']
        conf = rec.get('confidence') or 0.0
        correct = rec['actual_intent'] == intent
        if correct:
            per_intent_correct.setdefault(intent, []).append(conf)
        else:
            per_intent_incorrect.setdefault(intent, []).append(conf)
    thresholds = {}
    for intent, confs in per_intent_correct.items():
        min_correct = min(confs)
        thresholds[intent] = max(DEFAULT_MIN, round(min_correct - MARGIN, 3))
    # Provide fallback for intents with no correct samples yet
    for intent in set(list(per_intent_correct.keys()) + list(per_intent_incorrect.keys())):
        thresholds.setdefault(intent, DEFAULT_MIN)
    return thresholds


def write_thresholds(thresholds):
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump({'thresholds': thresholds}, f, indent=2)
    print(f'Wrote thresholds to {OUTPUT_PATH}')


def main():
    data = load_latest_results()
    if not data:
        print('No evaluation results found.')
        return
    thresholds = calibrate(data)
    write_thresholds(thresholds)

if __name__ == '__main__':
    main()
