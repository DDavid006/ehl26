"""Run-scoped audit log.

The tracer is the reason a PatentLoop verdict is inspectable: every external
HTTP response, every LLM prompt and completion, and every gate decision is
appended here as it happens and flushed to disk, so an auditor can replay the
decision after the fact without the system having asked anyone anything.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .http import Response


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Tracer:
    def __init__(self, run_dir: Path, run_id: str):
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.raw_dir = self.run_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self._raw_seq = 0
        self.log_path = self.run_dir / "run.log"
        self.trace_path = self.run_dir / "trace.json"

    # -- generic ---------------------------------------------------------
    def event(self, kind: str, agent: str, iteration: int | None = None, **payload) -> dict:
        record = {
            "at": _now(),
            "kind": kind,
            "agent": agent,
            "iteration": iteration,
            **payload,
        }
        with self._lock:
            self.events.append(record)
            self._append_log(record)
            self._flush()
        return record

    def log(self, message: str, agent: str = "orchestrator", iteration: int | None = None) -> None:
        self.event("log", agent, iteration, message=message)

    # -- external data ---------------------------------------------------
    def api_call(
        self,
        agent: str,
        source: str,
        query: str,
        response: Response,
        iteration: int | None = None,
        result_count: int | None = None,
    ) -> str:
        """Store a raw external response and reference it from the trace."""

        with self._lock:
            self._raw_seq += 1
            name = f"{self._raw_seq:03d}_{source}.txt"
            (self.raw_dir / name).write_text(response.body, encoding="utf-8")
        self.event(
            "api_call",
            agent,
            iteration,
            source=source,
            query=query,
            url=response.url,
            status=response.status,
            elapsed_ms=response.elapsed_ms,
            attempts=response.attempts,
            result_count=result_count,
            raw_response_file=f"raw/{name}",
        )
        return f"raw/{name}"

    def api_error(self, agent: str, source: str, query: str, error: str, iteration: int | None = None) -> None:
        self.event("api_error", agent, iteration, source=source, query=query, error=error)

    # -- LLM -------------------------------------------------------------
    def llm_call(
        self,
        agent: str,
        purpose: str,
        system: str,
        user: str,
        raw_completion: str,
        parsed: Any,
        model: str,
        usage: dict | None = None,
        iteration: int | None = None,
    ) -> None:
        self.event(
            "llm_call",
            agent,
            iteration,
            purpose=purpose,
            model=model,
            system_prompt=system,
            user_prompt=user,
            raw_completion=raw_completion,
            parsed=parsed,
            usage=usage or {},
        )

    # -- gates -----------------------------------------------------------
    def gate(self, gate: str, decision: str, reason: str, iteration: int, inputs: dict) -> None:
        self.event(
            "gate",
            "orchestrator",
            iteration,
            gate=gate,
            decision=decision,
            reason=reason,
            inputs=inputs,
        )

    # -- persistence -----------------------------------------------------
    def _append_log(self, record: dict) -> None:
        if record["kind"] == "log":
            line = record["message"]
        elif record["kind"] == "api_call":
            line = f"{record['source']}: {record['result_count']} results for {record['query']!r}"
        elif record["kind"] == "api_error":
            line = f"{record['source']} FAILED for {record['query']!r}: {record['error']}"
        elif record["kind"] == "llm_call":
            line = f"llm[{record['purpose']}] -> {record['model']}"
        elif record["kind"] == "gate":
            line = f"gate {record['gate']}: {record['decision']} ({record['reason']})"
        else:
            line = record["kind"]
        prefix = f"[{record['at']}] {record['agent']}"
        if record.get("iteration") is not None:
            prefix += f" i{record['iteration']}"
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{prefix}: {line}\n")

    def _flush(self) -> None:
        payload = {"run_id": self.run_id, "events": self.events}
        tmp = self.trace_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.trace_path)

    def write_trace(self, extra: dict | None = None) -> Path:
        payload = {"run_id": self.run_id, **(extra or {}), "events": self.events}
        self.trace_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return self.trace_path
