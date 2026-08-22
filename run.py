#!/usr/bin/env python3
"""PatentLoop CLI: python run.py --idea "your idea text here"

Runs the whole loop unattended and prints the run folder path at the end.
"""

from __future__ import annotations

import argparse
import sys

from patentloop.orchestrator import run_loop


def main() -> int:
    parser = argparse.ArgumentParser(description="PatentLoop: autonomous patent triage and drafting")
    parser.add_argument("--idea", required=True, help="raw patent idea text")
    parser.add_argument("--runs-dir", default="runs", help="directory for run artifacts")
    args = parser.parse_args()

    def progress(event: str, data: dict) -> None:
        iteration = data.get("iteration")
        prefix = f"[iter {iteration}] " if iteration else ""
        if event == "extracted":
            print(f"{prefix}elements: {', '.join(data.get('elements') or [])}")
        elif event == "research":
            print(f"{prefix}research agent: scanning Semantic Scholar / arXiv / GitHub ...")
        elif event == "research_done":
            print(f"{prefix}novelty_score={data['novelty_score']} "
                  f"({data['documents_considered']} documents)")
        elif event == "patent_search":
            print(f"{prefix}patent search agent: querying Google Patents (US/EP/WIPO) ...")
        elif event == "patent_search_done":
            print(f"{prefix}overlap_score={data['overlap_score']} "
                  f"({data['patents_considered']} patents)")
        elif event == "feasibility_done":
            print(f"{prefix}feasibility gate: {'PASS' if data['passed'] else 'FAIL'}")
        elif event == "pivot_done":
            print(f"{prefix}pivot -> {data['new_idea']}")
        elif event == "drafting":
            print(f"{prefix}drafting agent: writing provisional application ...")
        elif event == "done":
            print(f"\nVERDICT: {data['status']}")
            if data.get("kill_reason"):
                print(f"Reason: {data['kill_reason']}")

    result = run_loop(args.idea, runs_dir=args.runs_dir, progress=progress)
    print(f"\nRun folder: {result['run_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
