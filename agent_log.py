"""Transcript of every agent ask and its output, recorded for Entire.

One analysis run is one transcript: ``.entire/agent-logs/<run_id>.jsonl``, a JSON
object per line holding the exact prompt sent to the model and the raw text it
returned. :func:`finish_run` hands the transcript to the ``entire`` CLI, which
reads it through the external agent plugin in ``tools/`` and checkpoints the run
against the repository's history. The attach is best effort: its outcome is
recorded in the transcript rather than raised, because a logging backend must
never fail an analysis.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_LOG_DIR = REPO_ROOT / ".entire" / "agent-logs"
# Where the ``entire-agent-<name>`` plugin that reads these transcripts lives.
PLUGIN_DIR = REPO_ROOT / "tools"
ATTACH_TIMEOUT_SECONDS = 30
# Entire stores a session against the repo's own history, so the transcript is
# only useful to it inside a checkout; skip the attach when asked to.
ATTACH_ENABLED = os.getenv("ENTIRE_ATTACH", "1").strip().lower() not in ("0", "false", "no")
ENTIRE_AGENT = os.getenv("ENTIRE_AGENT", "patentability").strip() or "patentability"

# Run ids reach read_run() from a URL, so they are kept to a shape that cannot
# walk out of the log directory.
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_write_lock = threading.Lock()


def log_dir() -> Path:
    return Path(os.getenv("ENTIRE_AGENT_LOG_DIR") or DEFAULT_LOG_DIR)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunLog:
    """The transcript of a single analysis run."""

    def __init__(self, label: str, run_id: str | None = None) -> None:
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
        self.label = label
        self.started_at = _now()
        self.path = log_dir() / f"{self.run_id}.jsonl"
        self.entries: list[dict[str, Any]] = []
        self._append({"type": "run_started", "label": label})

    def _append(self, entry: dict[str, Any]) -> dict[str, Any]:
        entry = {"run_id": self.run_id, "at": _now(), **entry}
        self.entries.append(entry)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        try:
            with _write_lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
        except OSError:
            pass
        return entry

    def record(
        self,
        task: str,
        ask: str,
        output: str = "",
        *,
        model: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Record one model exchange: what was asked and what came back."""
        return self._append(
            {
                "type": "exchange",
                "task": task,
                "model": model,
                "ask": ask,
                "output": output,
                "error": error,
            }
        )

    def note(self, message: str) -> dict[str, Any]:
        return self._append({"type": "note", "message": message})


_current: ContextVar[RunLog | None] = ContextVar("agent_log_run", default=None)


def start_run(label: str) -> RunLog:
    """Begin a transcript and make it the current one for this context."""
    run = RunLog(label)
    _current.set(run)
    return run


def current_run() -> RunLog | None:
    return _current.get()


@contextmanager
def using(run: RunLog | None) -> Iterator[None]:
    """Record onto ``run`` inside this block, e.g. on a worker thread."""
    token = _current.set(run)
    try:
        yield
    finally:
        _current.reset(token)


def record(
    task: str,
    ask: str,
    output: str = "",
    *,
    model: str | None = None,
    error: str | None = None,
) -> None:
    """Record an exchange on the current transcript, if a run is open."""
    run = _current.get()
    if run is not None:
        run.record(task, ask, output, model=model, error=error)


def note(message: str) -> None:
    run = _current.get()
    if run is not None:
        run.note(message)


def _attach_to_entire(run: RunLog) -> tuple[bool, str]:
    environment = dict(os.environ)
    # Entire finds the plugin by scanning PATH for ``entire-agent-*``.
    environment["PATH"] = os.pathsep.join([str(PLUGIN_DIR), environment.get("PATH", "")])
    environment["ENTIRE_AGENT_LOG_DIR"] = str(log_dir())
    try:
        completed = subprocess.run(
            ["entire", "session", "attach", run.run_id, "--agent", ENTIRE_AGENT],
            capture_output=True,
            text=True,
            timeout=ATTACH_TIMEOUT_SECONDS,
            cwd=str(REPO_ROOT),
            env=environment,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode == 0, output


def finish_run(run: RunLog | None = None) -> RunLog | None:
    """Close the transcript and hand it to Entire (best effort)."""
    run = run or _current.get()
    if run is None:
        return None
    if ATTACH_ENABLED:
        attached, output = _attach_to_entire(run)
        run._append({"type": "entire_attach", "attached": attached, "output": output})
    run._append({"type": "run_finished", "exchanges": sum(
        1 for entry in run.entries if entry.get("type") == "exchange"
    )})
    _current.set(None)
    return run


def read_run(run_id: str) -> list[dict[str, Any]]:
    """Read back a transcript written by an earlier run."""
    if not RUN_ID.match(run_id):
        return []
    path = log_dir() / f"{run_id}.jsonl"
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries
