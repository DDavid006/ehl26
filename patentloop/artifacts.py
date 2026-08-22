"""Auditable PatentLoop run artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")


class ArtifactWriter:
    def __init__(self, run_dir: Path | str):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.trace: list[dict] = []
        self.seq = 0

    def event(self, iteration: int, agent: str, inputs, output, artifacts=(), llm_calls=(), session_urls=()):
        self.seq += 1
        event = {
            "seq": self.seq, "iteration": iteration, "agent": agent,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "inputs_digest": hashlib.sha256(
                json.dumps(inputs, sort_keys=True, default=str).encode()
            ).hexdigest(),
            "output": output, "artifacts": list(artifacts), "llm_calls": list(llm_calls),
            "session_urls": list(session_urls),
        }
        self.trace.append(event)
        _json(self.run_dir / "trace.json", self.trace)
        return event

    def write_prior_art(self, iterations: list[dict]) -> str:
        path = self.run_dir / "prior_art.json"
        _json(path, {"iterations": iterations})
        return str(path)

    def write_report(
        self,
        verdict: str,
        iterations: list[dict],
        reasoning: list[str],
        citations: list[dict],
        *,
        termination_reason: str,
        pivot_lineage: list[dict] | None = None,
    ) -> str:
        lines = [
            "# PatentLoop Report", "", f"**Verdict:** `{verdict}`", "",
            f"**Termination reason:** `{termination_reason}`", "",
            "| Version | Novelty | Overlap | Feasible | Scoped |",
            "|---|---:|---:|---|---|",
        ]
        for item in iterations:
            lines.append(
                f"| v{item['iteration']} | {item.get('novelty_score', '—')} | "
                f"{item.get('overlap_score', '—')} | {item.get('feasible', '—')} | "
                f"{item.get('scoped', '—')} |"
            )
            lines.append(
                f"  - gate: `{item.get('gate_decision', '—')}`; "
                f"termination: `{item.get('termination_reason', '—')}`"
            )
            if item.get("element_scores"):
                scores = ", ".join(
                    f"{key}={value}" for key, value in item["element_scores"].items()
                )
                lines.append(f"  - element novelty: {scores}")
            if item.get("unverified_elements"):
                lines.append(
                    "  - unverified elements: "
                    + ", ".join(item["unverified_elements"])
                )
            lines.append(
                f"  - patents examined: {item.get('patents_examined', '—')}"
            )
            if item.get("source_errors"):
                lines.append("  - source errors:")
                lines.extend(
                    f"    - {error.get('source', 'unknown')}: "
                    f"{error.get('error', '')}"
                    for error in item["source_errors"]
                )
            blocking = item.get("top_blocking_patent")
            if blocking:
                lines.append(
                    "  - top blocking patent: "
                    f"{blocking.get('id', 'unknown')} — "
                    f"validated claim quote: {blocking.get('claim_quote', 'none')!r}"
                )
        if pivot_lineage:
            lines += ["", "## Pivot lineage"]
            lines.extend(
                f"- v{item['version']}: {item['idea']}" for item in pivot_lineage
            )
        lines += ["", "## Reasoning"]
        lines.extend(f"- {text}" for text in reasoning)
        lines += ["", "## Citations"]
        lines.extend(f"- {item.get('title', item.get('id', 'unknown'))} ({item.get('url', 'no URL')}) — raw: `{item.get('raw_path', 'n/a')}`" for item in citations)
        session_urls = [
            url for event in self.trace for url in event.get("session_urls", []) if url
        ]
        lines += ["", "## Audit trail", "- `trace.json` contains ordered agent events and LLM log paths.", "- `prior_art.json` contains normalized records and raw API paths.", "- Raw API responses are under `raw/<iteration>/`; LLM requests are under `llm/`."]
        if session_urls:
            lines.append("Devin sessions: " + ", ".join(f"[{url}]({url})" for url in session_urls))
        lines.append(
            "Evidence fields: novelty scores exclude unverified elements; patent "
            "overlap uses only examined, claim-validated records."
        )
        path = self.run_dir / "report.md"
        path.write_text("\n".join(lines) + "\n")
        return str(path)
