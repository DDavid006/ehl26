"""`python run.py --idea "..."` — one trigger, one artifact folder, no prompts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Config, ConfigError
from .orchestrator import Orchestrator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Run the PatentLoop autonomous prior-art loop on one idea.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--idea", help="raw idea text")
    source.add_argument("--idea-file", help="path to a file containing the idea text")
    parser.add_argument("--max-iterations", type=int, default=None, help="pivot cap (default 4)")
    parser.add_argument("--model", default=None, help="Anthropic model id")
    parser.add_argument("--runs-dir", default=None, help="where run folders are written")
    parser.add_argument("--run-id", default=None, help="explicit run id")
    parser.add_argument(
        "--results-per-query", type=int, default=None, help="hits requested per source per query"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    idea_text = args.idea if args.idea else Path(args.idea_file).read_text(encoding="utf-8")
    if not idea_text.strip():
        print("error: the idea text is empty", file=sys.stderr)
        return 2
    try:
        config = Config.from_env(
            anthropic_model=args.model,
            max_iterations=args.max_iterations,
            runs_dir=Path(args.runs_dir) if args.runs_dir else None,
            results_per_query=args.results_per_query,
        )
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    orchestrator = Orchestrator(config, args.run_id)
    print(f"run_id: {orchestrator.run_id}")
    print(f"run_dir: {orchestrator.run_dir}")
    result = orchestrator.run(idea_text)
    print("")
    print(f"outcome: {result.outcome}")
    print(f"reason: {result.reason}")
    print(f"iterations: {len(result.iterations)}")
    for iteration in result.iterations:
        novelty = iteration.research.novelty_score if iteration.research else "—"
        overlap = iteration.patents.overlap_score if iteration.patents else "—"
        print(f"  v{iteration.idea.version}: novelty={novelty} overlap={overlap}")
    print("")
    print(f"artifacts: {result.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
