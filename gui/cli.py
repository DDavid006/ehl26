"""CLI used to push workflow progress into the GUI store.

The agent fan-out is driven by the `run_workflow` tool, not by the web process,
so the orchestrator reports back through this CLI:

    python -m gui.cli status <run_id> running --workflow-run-id wfr-123
    python -m gui.cli round  <run_id> --file round1.json
    python -m gui.cli draft  <run_id> --file draft.json
    python -m gui.cli log    <run_id> "round 1: 5 searchers dispatched"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gui.store import STATUSES, RunStore, StoreError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gui.cli", description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="set the run status")
    status.add_argument("run_id")
    status.add_argument("status", choices=STATUSES)
    status.add_argument("--workflow-run-id")
    status.add_argument("--error")

    for name, help_text in (("round", "record one clearance round"),
                            ("draft", "record the drafted application")):
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
        elif args.command == "round":
            store.record_round(args.run_id, json.loads(args.file.read_text()))
        elif args.command == "draft":
            store.record_draft(args.run_id, json.loads(args.file.read_text()))
        elif args.command == "log":
            store.log(args.run_id, args.message)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
