"""CLI used to push workflow progress into the differentiator GUI.

The agent fan-out is driven by the `run_workflow` tool, so the workflow script
reports back through this CLI:

    python -m differentiator.cli status <run_id> searching --workflow-run-id wfr-1
    python -m differentiator.cli features <run_id> --file features.json
    python -m differentiator.cli matrix <run_id> --file matrix.json
    python -m differentiator.cli similarity <run_id> --file similarity.json
    python -m differentiator.cli substitution <run_id> --file substitution.json
    python -m differentiator.cli log <run_id> "checking EP1234567"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from differentiator.store import STATUSES, RunStore, StoreError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="differentiator.cli", description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="set the run status")
    status.add_argument("run_id")
    status.add_argument("status", choices=STATUSES)
    status.add_argument("--workflow-run-id")
    status.add_argument("--error")

    for name, help_text in (
        ("features", "record the extracted features and materials"),
        ("matrix", "record Espacenet patents and feature/patent cells"),
        ("similarity", "record one similarity check"),
        ("substitution", "replace one duplicated feature with a new one"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("run_id")
        cmd.add_argument("--file", type=Path, required=True,
                         help="JSON file holding the agent's structured output")

    log = sub.add_parser("log", help="append a progress line")
    log.add_argument("run_id")
    log.add_argument("message")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = RunStore(args.runs_dir) if args.runs_dir else RunStore()

    try:
        if args.command == "status":
            store.set_status(args.run_id, args.status,
                             workflow_run_id=args.workflow_run_id, error=args.error)
        elif args.command == "features":
            payload = json.loads(args.file.read_text())
            store.record_features(args.run_id, payload["features"])
        elif args.command == "matrix":
            store.record_matrix(args.run_id, json.loads(args.file.read_text()))
        elif args.command == "similarity":
            store.record_similarity(args.run_id, json.loads(args.file.read_text()))
        elif args.command == "substitution":
            store.record_substitution(args.run_id, json.loads(args.file.read_text()))
        elif args.command == "log":
            store.log(args.run_id, args.message)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
