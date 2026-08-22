#!/usr/bin/env python3
"""Score a coverage matcher against the hand-labelled pairs in coverage_eval.json.

Usage:
    ./.venv/bin/python eval_coverage.py            # keyword matcher (no API calls)
    ./.venv/bin/python eval_coverage.py --judge llm  # model-based judge (uses LLM_PROVIDER)

Prints per-cell mismatches and precision / recall / F1 over all labelled cells,
so any change to the matcher can be measured instead of eyeballed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

EVAL_PATH = Path(__file__).resolve().parent / "coverage_eval.json"


def _predict_keyword(elements: list[dict], patents: list[dict]) -> dict:
    from coverage import build_matrix

    return build_matrix(elements, patents)["coverage"]


def _predict_llm(elements: list[dict], patents: list[dict]) -> dict:
    import judge

    if judge.MODE != "llm":
        raise SystemExit("COVERAGE_JUDGE must not be 'keyword' when evaluating the llm judge")
    return judge.build_matrix(elements, patents)["coverage"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge", choices=("keyword", "llm"), default="keyword")
    args = parser.parse_args()
    predict = _predict_llm if args.judge == "llm" else _predict_keyword

    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["cases"]

    tp = fp = fn = tn = 0
    mismatches: list[str] = []

    for case in cases:
        predicted = predict(case["elements"], case["patents"])
        for element_id, per_patent in case["labels"].items():
            for patent_id, expected in per_patent.items():
                got = predicted[element_id][patent_id]["covered"]
                if got and expected:
                    tp += 1
                elif got and not expected:
                    fp += 1
                    mismatches.append(
                        f"  FP {case['name']}: {element_id} x {patent_id} (predicted covered)"
                    )
                elif not got and expected:
                    fn += 1
                    mismatches.append(
                        f"  FN {case['name']}: {element_id} x {patent_id} (missed disclosure)"
                    )
                else:
                    tn += 1

    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    print(f"judge={args.judge}  cells={total}  tp={tp} fp={fp} fn={fn} tn={tn}")
    print(f"precision={precision:.2f}  recall={recall:.2f}  f1={f1:.2f}")
    if mismatches:
        print("mismatches:")
        print("\n".join(mismatches))


if __name__ == "__main__":
    main()
