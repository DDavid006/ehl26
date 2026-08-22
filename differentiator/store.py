"""Filesystem-backed store for Espacenet differentiation runs.

Each run lives in its own directory under ``diff-runs/``:

    diff-runs/<run_id>/invention.json  the submitted invention
    diff-runs/<run_id>/state.json      features, patents, matrix, iterations
    diff-runs/<run_id>/workflow.py     the skill workflow with INVENTION substituted
    diff-runs/<run_id>/run.log         append-only progress log

The web process only queues runs; the agents driven by ``run_workflow`` push
their progress back in through :mod:`differentiator.cli`, which writes here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_WORKFLOW = (
    REPO_ROOT / ".devin" / "skills" / "espacenet-differentiation" / "workflow.py"
)
DEFAULT_RUNS_DIR = REPO_ROOT / "diff-runs"

STATUSES = ("queued", "extracting", "searching", "iterating", "complete", "failed")
TERMINAL_STATUSES = ("complete", "failed")

# A feature is either carried over from the submitted description or introduced
# by the substitution agent to design around an overlapping patent.
ORIGINS = ("original", "new")

_INVENTION_BLOCK = re.compile(r"^INVENTION = \{.*?^\}\n", re.DOTALL | re.MULTILINE)
_RUN_ID_LINE = re.compile(r'^GUI_RUN_ID = ".*?"$', re.MULTILINE)
_RUNS_DIR_LINE = re.compile(r'^GUI_RUNS_DIR = ".*?"$', re.MULTILINE)
_REPO_ROOT_LINE = re.compile(r'^GUI_REPO_ROOT = ".*?"$', re.MULTILINE)


class StoreError(Exception):
    """Raised for invalid input or unknown runs."""


@dataclass
class Invention:
    name: str
    purpose: str
    description: str

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "description": self.description,
        }


@dataclass
class Run:
    run_id: str
    invention: Invention
    status: str
    created_at: str
    features: list[dict] = field(default_factory=list)
    patents: list[dict] = field(default_factory=list)
    matrix: dict[str, dict[str, bool]] = field(default_factory=dict)
    iterations: list[dict] = field(default_factory=list)
    workflow_run_id: str | None = None
    error: str | None = None

    @property
    def live_features(self) -> list[dict]:
        """Features that have not been substituted away."""
        return [feature for feature in self.features if not feature.get("replaced_by")]

    @property
    def new_features(self) -> list[dict]:
        return [
            feature for feature in self.live_features if feature["origin"] == "new"
        ]

    def cell(self, feature_id: str, patent_id: str) -> bool | None:
        """True when the patent contains the feature, None when not assessed."""
        return self.matrix.get(feature_id, {}).get(patent_id)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "untitled"


def feature_id(index: int) -> str:
    return f"f{index}"


def patent_id(publication: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", publication).upper()


def render_workflow(invention: Invention, run_id: str, runs_dir: Path,
                    template: str) -> str:
    """Return the skill workflow bound to one invention and one GUI run."""
    literal = (
        "INVENTION = "
        + json.dumps(invention.as_dict(), indent=4, sort_keys=True)
        + "\n"
    )
    rendered, count = _INVENTION_BLOCK.subn(lambda _: literal, template, count=1)
    if count != 1:
        raise StoreError(
            f"could not find the INVENTION literal to substitute in {SKILL_WORKFLOW}"
        )
    substitutions = (
        (_RUN_ID_LINE, f'GUI_RUN_ID = "{run_id}"'),
        (_RUNS_DIR_LINE, f'GUI_RUNS_DIR = "{runs_dir}"'),
        (_REPO_ROOT_LINE, f'GUI_REPO_ROOT = "{REPO_ROOT}"'),
    )
    for pattern, replacement in substitutions:
        rendered, count = pattern.subn(lambda _, r=replacement: r, rendered, count=1)
        if count != 1:
            raise StoreError(
                f"could not bind {pattern.pattern} in {SKILL_WORKFLOW}"
            )
    return rendered


class RunStore:
    def __init__(self, runs_dir: Path | str = DEFAULT_RUNS_DIR,
                 workflow_template: Path | str = SKILL_WORKFLOW):
        self.runs_dir = Path(runs_dir)
        self.workflow_template = Path(workflow_template)

    # ------------------------------------------------------------- writes ---

    def create(self, invention: Invention) -> Run:
        if not invention.name.strip():
            raise StoreError("name is required")
        if not invention.purpose.strip():
            raise StoreError("purpose is required")
        if not invention.description.strip():
            raise StoreError("description is required")

        run_id = self._allocate_id(slugify(invention.name))
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True)

        run = Run(
            run_id=run_id,
            invention=invention,
            status="queued",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        (run_dir / "invention.json").write_text(
            json.dumps(invention.as_dict(), indent=2) + "\n"
        )
        (run_dir / "workflow.py").write_text(
            render_workflow(
                invention, run_id, self.runs_dir, self.workflow_template.read_text()
            )
        )
        self._write_state(run)
        self.log(run_id, f"run created: {invention.name}")
        return run

    def set_status(self, run_id: str, status: str, *,
                   workflow_run_id: str | None = None,
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

    def record_features(self, run_id: str, features: list[dict]) -> Run:
        """Record the feature/material breakdown extracted from the description."""
        if not features:
            raise StoreError("the extractor returned no features")
        run = self.get(run_id)
        run.features = [
            {
                "id": feature_id(index),
                "text": entry["text"],
                "kind": entry.get("kind", "feature"),
                "origin": "original",
                "round": 0,
                "replaced_by": None,
            }
            for index, entry in enumerate(features, start=1)
        ]
        self._write_state(run)
        self.log(run_id, f"extracted {len(run.features)} features and materials")
        return run

    def record_matrix(self, run_id: str, payload: dict) -> Run:
        """Record the patents found on Espacenet and the feature/patent grid."""
        run = self.get(run_id)
        known = {feature["id"] for feature in run.features}
        by_text = {feature["text"]: feature["id"] for feature in run.features}
        for patent in payload.get("patents", []):
            pid = patent_id(patent["publication"])
            existing = next((p for p in run.patents if p["id"] == pid), None)
            record = {
                "id": pid,
                "publication": patent["publication"],
                "title": patent.get("title", ""),
                "applicant": patent.get("applicant", ""),
                "url": patent.get("url", ""),
            }
            if existing:
                run.patents[run.patents.index(existing)] = record
            else:
                run.patents.append(record)

        for cell in payload.get("cells", []):
            fid = cell.get("feature_id") or by_text.get(cell.get("feature", ""))
            if fid not in known:
                raise StoreError(f"unknown feature in matrix cell: {cell}")
            pid = patent_id(cell["patent"])
            run.matrix.setdefault(fid, {})[pid] = bool(cell["present"])

        self._write_state(run)
        self.log(
            run_id,
            f"matrix: {len(run.patents)} patents x {len(run.features)} features",
        )
        return run

    def record_similarity(self, run_id: str, payload: dict) -> Run:
        """Record one similarity check by the first child agent."""
        run = self.get(run_id)
        entry = {
            "round": len(run.iterations) + 1,
            "kind": "similarity",
            "closest_patent": payload.get("closest_patent", ""),
            "overlap_ratio": payload.get("overlap_ratio", 0.0),
            "shared_features": payload.get("shared_features", []),
            "needs_substitution": bool(payload.get("needs_substitution")),
            "reasoning": payload.get("reasoning", ""),
        }
        run.iterations.append(entry)
        self._write_state(run)
        self.log(
            run_id,
            f"round {entry['round']}: closest {entry['closest_patent'] or 'none'} "
            f"shares {entry['overlap_ratio']:.0%} of the features"
            + ("" if entry["needs_substitution"] else " - below the half threshold"),
        )
        return run

    def record_substitution(self, run_id: str, payload: dict) -> Run:
        """Swap one duplicated feature for a new one proposed by the second child."""
        run = self.get(run_id)
        target = next(
            (f for f in run.live_features if f["id"] == payload.get("feature_id")),
            None,
        )
        if target is None:
            raise StoreError(f"no live feature {payload.get('feature_id')!r} to replace")

        round_no = len([i for i in run.iterations if i["kind"] == "similarity"])
        replacement = {
            "id": feature_id(len(run.features) + 1),
            "text": payload["replacement"],
            "kind": target["kind"],
            "origin": "new",
            "round": round_no,
            "replaced_by": None,
            "replaces": target["id"],
        }
        target["replaced_by"] = replacement["id"]
        run.features.append(replacement)
        run.iterations.append(
            {
                "round": round_no,
                "kind": "substitution",
                "removed": target["text"],
                "removed_id": target["id"],
                "added": replacement["text"],
                "added_id": replacement["id"],
                "rationale": payload.get("rationale", ""),
            }
        )
        self._write_state(run)
        self.log(
            run_id,
            f"round {round_no}: replaced '{target['text']}' with "
            f"'{replacement['text']}'",
        )
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
        invention = state["invention"]
        return Run(
            run_id=state["run_id"],
            invention=Invention(
                name=invention["name"],
                purpose=invention["purpose"],
                description=invention["description"],
            ),
            status=state["status"],
            created_at=state["created_at"],
            features=state.get("features", []),
            patents=state.get("patents", []),
            matrix=state.get("matrix", {}),
            iterations=state.get("iterations", []),
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
            "invention": run.invention.as_dict(),
            "status": run.status,
            "created_at": run.created_at,
            "features": run.features,
            "patents": run.patents,
            "matrix": run.matrix,
            "iterations": run.iterations,
            "workflow_run_id": run.workflow_run_id,
            "error": run.error,
        }
        path = self.runs_dir / run.run_id / "state.json"
        path.write_text(json.dumps(state, indent=2) + "\n")
