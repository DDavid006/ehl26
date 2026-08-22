"""Company roles and program-manager assignment tracking."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROLE_REGISTRY = {
    "extract": {
        "title": "Intake Analyst",
        "remit": "Turn an invention description into concrete claim elements.",
    },
    "research": {
        "title": "Research Analyst",
        "remit": "Find and score relevant technical literature.",
    },
    "patent_search": {
        "title": "Patent Examiner",
        "remit": "Find patents and validate claim overlap against the idea.",
    },
    "feasibility_doable": {
        "title": "Feasibility Engineer",
        "remit": "Assess whether the proposed mechanism is physically doable.",
    },
    "feasibility_scoped": {
        "title": "Claims Scope Counsel",
        "remit": "Assess whether the claim scope is concrete and defensible.",
    },
    "pivot": {
        "title": "Pivot Strategist",
        "remit": "Design a technically plausible, non-repeating redesign.",
    },
    "drafting": {
        "title": "IP Attorney",
        "remit": "Prepare the provisional application draft.",
    },
}

_ALIASES = {
    "extract_idea": "extract",
    "research_rationale": "research",
    "devin_patent_search": "patent_search",
    "claim_mapping": "patent_search",
    "claim_map": "patent_search",
    "feasibility_physical": "feasibility_doable",
    "feasibility_scope": "feasibility_scoped",
}


def role_for(agent_key: str) -> dict:
    key = _ALIASES.get(agent_key, agent_key)
    return ROLE_REGISTRY.get(
        key,
        {"title": agent_key.replace("_", " ").title(), "remit": ""},
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StaffBoard:
    """Thread-safe assignment board persisted as ``company.json``."""

    def __init__(self, run_dir: Path | str | None = None):
        self.run_dir = Path(run_dir) if run_dir else None
        self._lock = threading.RLock()
        self._assignments: list[dict] = []
        self._sequence = 0
        if self.run_dir:
            self._load()

    def _load(self) -> None:
        try:
            payload = json.loads((self.run_dir / "company.json").read_text())
            self._assignments = list(payload.get("assignments", []))
            self._sequence = len(self._assignments)
        except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
            return

    def _persist(self) -> None:
        if self.run_dir is None:
            return
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            target = self.run_dir / "company.json"
            temporary = self.run_dir / "company.json.tmp"
            temporary.write_text(
                json.dumps(self._payload(), indent=2, ensure_ascii=False) + "\n"
            )
            temporary.replace(target)
        except Exception as exc:
            try:
                with (self.run_dir / "run.log").open("a") as log:
                    log.write(f"StaffBoard persistence failure: {exc}\n")
            except Exception:
                pass

    def _payload(self) -> dict:
        return {"assignments": [dict(item) for item in self._assignments]}

    def snapshot(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._payload()))

    def _change(self, assignment_id: str, **updates) -> None:
        with self._lock:
            for assignment in self._assignments:
                if assignment["assignment_id"] == assignment_id:
                    assignment.update(updates)
                    self._persist()
                    return

    def dispatch(
        self,
        agent_key: str,
        *,
        task: str,
        iteration: int | None = None,
        role: str | None = None,
    ) -> str:
        with self._lock:
            self._sequence += 1
            assignment_id = f"a-{self._sequence:04d}-{uuid.uuid4().hex[:6]}"
            role_data = role_for(agent_key)
            now = _now()
            self._assignments.append(
                {
                    "assignment_id": assignment_id,
                    "role_title": role or role_data["title"],
                    "remit": role_data["remit"],
                    "agent_key": agent_key,
                    "task": task,
                    "iteration": iteration,
                    "status": "dispatched",
                    "started_at": None,
                    "finished_at": None,
                    "duration_seconds": None,
                    "session_id": None,
                    "session_url": None,
                    "acu_usage": None,
                    "acu_raw": None,
                    "error": None,
                    "dispatched_at": now,
                }
            )
            self._persist()
            return assignment_id

    def running(self, assignment_id: str) -> None:
        with self._lock:
            for assignment in self._assignments:
                if assignment["assignment_id"] == assignment_id:
                    updates = {"status": "running"}
                    if not assignment.get("started_at"):
                        updates["started_at"] = _now()
                    assignment.update(updates)
                    self._persist()
                    return

    def blocked(self, assignment_id: str, *, raw_status=None) -> None:
        updates = {"status": "blocked"}
        if raw_status is not None:
            updates["blocked_status"] = raw_status
        self._change(assignment_id, **updates)

    def session(self, assignment_id: str, session_id=None, session_url=None) -> None:
        self._change(
            assignment_id,
            session_id=session_id,
            session_url=session_url,
        )

    def usage(self, assignment_id: str, value, *, raw=None) -> None:
        self._change(assignment_id, acu_usage=value, acu_raw=raw)

    def completed(self, assignment_id: str, *, acu_usage=None, acu_raw=None) -> None:
        self._finish(
            assignment_id,
            status="completed",
            acu_usage=acu_usage,
            acu_raw=acu_raw,
        )

    def failed(self, assignment_id: str, error: str, *, acu_usage=None, acu_raw=None) -> None:
        self._finish(
            assignment_id,
            status="failed",
            error=error,
            acu_usage=acu_usage,
            acu_raw=acu_raw,
        )

    def _finish(self, assignment_id: str, **updates) -> None:
        now = _now()
        with self._lock:
            for assignment in self._assignments:
                if assignment["assignment_id"] == assignment_id:
                    started = assignment.get("started_at") or assignment.get("dispatched_at")
                    try:
                        duration = (
                            datetime.fromisoformat(now).timestamp()
                            - datetime.fromisoformat(started).timestamp()
                        )
                    except (TypeError, ValueError):
                        duration = None
                    assignment.update(
                        {
                            **updates,
                            "finished_at": now,
                            "duration_seconds": duration,
                        }
                    )
                    self._persist()
                    return
