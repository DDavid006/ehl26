"""Command-line entry point for the autonomous PatentLoop pipeline."""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from patentloop.orchestrator import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run.py")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--idea")
    source.add_argument("--idea-file", type=Path)
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--run-id")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    idea = args.idea if args.idea is not None else args.idea_file.read_text()
    run_id = args.run_id or uuid.uuid4().hex[:12]
    run_dir = args.runs_dir / run_id
    try:
        result = run_pipeline(idea.strip(), run_dir, max_iterations=args.max_iterations)
    except Exception as exc:
        print(f"PatentLoop infrastructure failure: {exc}", file=sys.stderr)
        return 1
    print(f"verdict: {result['verdict']}")
    print(result["run_dir"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
