"""Filesystem-backed store for patent clearance runs.

Each run lives in its own directory under ``runs/``:

    runs/<run_id>/idea.json     the submitted invention
    runs/<run_id>/state.json    status, per-round verdicts, draft info
    runs/<run_id>/workflow.py   the skill workflow with IDEA substituted
    runs/<run_id>/run.log       append-only progress log
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_WORKFLOW = REPO_ROOT / ".devin" / "skills" / "patent-clearance" / "workflow.py"
DEFAULT_RUNS_DIR = REPO_ROOT / "runs"

STATUSES = ("queued", "running", "blocked", "drafted", "failed")

_IDEA_BLOCK = re.compile(r"^IDEA = \{.*?^\}\n", re.DOTALL | re.MULTILINE)


class StoreError(Exception):
    """Raised for invalid input or unknown runs."""


@dataclass
class Idea:
    title: str
    description: str
    features: list[str]
    field_of_art: str

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "features": self.features,
            "field": self.field_of_art,
        }


@dataclass
class Run:
    run_id: str
    idea: Idea
    status: str
    created_at: str
    rounds: list[dict] = field(default_factory=list)
    draft: dict | None = None
    workflow_run_id: str | None = None
    error: str | None = None

    @property
    def verdict(self) -> str | None:
        return self.rounds[-1]["verdict"] if self.rounds else None


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "untitled"


def parse_features(raw: str) -> list[str]:
    return [line.strip(" \t-*") for line in raw.splitlines() if line.strip(" \t-*")]


def render_workflow(idea: Idea, template: str) -> str:
    """Return the skill workflow with its IDEA literal replaced by ``idea``."""
    literal = "IDEA = " + json.dumps(idea.as_dict(), indent=4, sort_keys=True) + "\n"
    rendered, count = _IDEA_BLOCK.subn(lambda _: literal, template, count=1)
    if count != 1:
        raise StoreError(
            f"could not find the IDEA literal to substitute in {SKILL_WORKFLOW}"
        )
    return rendered


class RunStore:
    def __init__(self, runs_dir: Path | str = DEFAULT_RUNS_DIR,
                 workflow_template: Path | str = SKILL_WORKFLOW):
        self.runs_dir = Path(runs_dir)
        self.workflow_template = Path(workflow_template)

    # ------------------------------------------------------------- writes ---

    def create(self, idea: Idea) -> Run:
        if not idea.title.strip():
            raise StoreError("title is required")
        if not idea.description.strip():
            raise StoreError("description is required")
        if not idea.features:
            raise StoreError("list at least one distinctive feature")

        run_id = self._allocate_id(slugify(idea.title))
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True)

        run = Run(
            run_id=run_id,
            idea=idea,
            status="queued",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        (run_dir / "idea.json").write_text(json.dumps(idea.as_dict(), indent=2) + "\n")
        (run_dir / "workflow.py").write_text(
            render_workflow(idea, self.workflow_template.read_text())
        )
        self._write_state(run)
        self.log(run_id, f"run created: {idea.title}")
        return run

    def set_status(self, run_id: str, status: str, *, workflow_run_id: str | None = None,
                   error: str | None = None) -> Run:
        if status not in STATUSES:
            raise StoreError(f"unknown status {status!r}, expected one of {STATUSES}")
        run = self.get(run_id)
        run.status = status
        if workflow_run_id:
            run.workflow_run_id = workflow_run_id
        if error is not None:
            run.error = error
        self._write_state(run)
        self.log(run_id, f"status -> {status}")
        return run

    def record_round(self, run_id: str, round_data: dict) -> Run:
        """Record one search/assess (and optional redesign) round."""
        if "verdict" not in round_data:
            raise StoreError("round data must include a 'verdict'")
        run = self.get(run_id)
        run.rounds.append(round_data)
        run.status = "drafted" if round_data["verdict"] == "clear" else "blocked"
        self._write_state(run)
        self.log(
            run_id,
            f"round {len(run.rounds)}: {round_data['verdict']}"
            + (
                f" ({len(round_data.get('blocking_references', []))} blocking refs)"
                if round_data["verdict"] == "blocked"
                else ""
            ),
        )
        return run

    def record_draft(self, run_id: str, draft: dict) -> Run:
        run = self.get(run_id)
        run.draft = draft
        run.status = "drafted"
        self._write_state(run)
        self.log(run_id, f"draft pushed to {draft.get('branch')}")
        return run

    def log(self, run_id: str, message: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with (self.runs_dir / run_id / "run.log").open("a") as handle:
            handle.write(f"[{stamp}] {message}\n")

    # -------------------------------------------------------------- reads ---

    def get(self, run_id: str) -> Run:
        state_path = self.runs_dir / run_id / "state.json"
        if not state_path.is_file():
            raise StoreError(f"no such run: {run_id}")
        state = json.loads(state_path.read_text())
        idea = state["idea"]
        return Run(
            run_id=state["run_id"],
            idea=Idea(
                title=idea["title"],
                description=idea["description"],
                features=idea["features"],
                field_of_art=idea["field"],
            ),
            status=state["status"],
            created_at=state["created_at"],
            rounds=state.get("rounds", []),
            draft=state.get("draft"),
            workflow_run_id=state.get("workflow_run_id"),
            error=state.get("error"),
        )

    def list(self) -> list[Run]:
        if not self.runs_dir.is_dir():
            return []
        runs = [
            self.get(path.name)
            for path in self.runs_dir.iterdir()
            if (path / "state.json").is_file()
        ]
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    def read_log(self, run_id: str, tail: int = 200) -> list[str]:
        log_path = self.runs_dir / run_id / "run.log"
        if not log_path.is_file():
            return []
        return log_path.read_text().splitlines()[-tail:]

    def workflow_path(self, run_id: str) -> Path:
        return self.runs_dir / run_id / "workflow.py"

    # ------------------------------------------------------------ helpers ---

    def _allocate_id(self, slug: str) -> str:
        candidate = slug
        suffix = 2
        while (self.runs_dir / candidate).exists():
            candidate = f"{slug}-{suffix}"
            suffix += 1
        return candidate

    def _write_state(self, run: Run) -> None:
        state = {
            "run_id": run.run_id,
            "idea": run.idea.as_dict(),
            "status": run.status,
            "created_at": run.created_at,
            "rounds": run.rounds,
            "draft": run.draft,
            "workflow_run_id": run.workflow_run_id,
            "error": run.error,
        }
        path = self.runs_dir / run.run_id / "state.json"
        path.write_text(json.dumps(state, indent=2) + "\n")
