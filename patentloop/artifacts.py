"""Per-run artifacts: report.md, prior_art.json, trace.json, draft_application.pdf."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fpdf import FPDF


def write_artifacts(run_dir: Path, trace: dict[str, Any], draft: dict[str, Any] | None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "trace.json").write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")

    prior_art = [
        {
            "iteration": entry["iteration"],
            "idea": entry["idea"],
            "research": entry.get("research"),
            "patent_search": entry.get("patent_search"),
            "coverage_matrix": entry.get("coverage_matrix"),
        }
        for entry in trace["iterations"]
    ]
    (run_dir / "prior_art.json").write_text(json.dumps(prior_art, indent=2, default=str), encoding="utf-8")

    (run_dir / "report.md").write_text(_render_report(trace, draft), encoding="utf-8")

    if draft and draft.get("draft_markdown"):
        (run_dir / "draft_application.md").write_text(draft["draft_markdown"], encoding="utf-8")
        _write_pdf(run_dir / "draft_application.pdf", draft["draft_markdown"])


def _render_report(trace: dict[str, Any], draft: dict[str, Any] | None) -> str:
    lines = [
        f"# PatentLoop report — run {trace['run_id']}",
        "",
        f"**Verdict: {trace['status']}**",
        "",
        f"Input idea: {trace['input_idea']}",
        "",
    ]
    if trace.get("kill_reason"):
        lines += [f"Kill reason: {trace['kill_reason']}", ""]
    if draft:
        lines += ["A provisional application draft was produced: see `draft_application.pdf` "
                  "(and `draft_application.md`).", ""]

    round_memory = trace.get("round_memory") or []
    if round_memory:
        lines += ["## Round memory (reasoning passed to later rounds)", ""]
        for item in round_memory:
            lines.append(f"- Round {item.get('round')}: rejected because {item.get('why_rejected')} "
                         f"→ pivoted toward: {item.get('pivot_direction_taken') or 'n/a'}")
        lines.append("")

    lines += ["## Idea lineage", ""]
    for index, idea in enumerate(trace.get("lineage") or [], start=1):
        lines.append(f"{index}. {idea}")
    lines.append("")

    lines += ["## Iteration trace", ""]
    for entry in trace["iterations"]:
        research = entry.get("research") or {}
        patents = entry.get("patent_search") or {}
        gate = entry.get("feasibility_gate") or {}
        decision = entry.get("decision") or {}
        lines += [
            f"### Iteration {entry['iteration']}",
            "",
            f"**Idea:** {entry['idea']}",
            "",
            f"**Core elements:** {', '.join((entry.get('extraction') or {}).get('elements') or [])}",
            "",
            f"**Novelty score:** {research.get('novelty_score')} "
            f"({research.get('documents_considered')} documents retrieved)",
            "",
            f"Research rationale: {research.get('rationale')}",
            "",
        ]
        for work in (research.get("closest_prior_work") or [])[:5]:
            lines.append(f"- {work.get('title')} — {work.get('url')} ({work.get('why_similar')})")
        lines += [
            "",
            f"**Overlap score:** {patents.get('overlap_score')} "
            f"({patents.get('patents_considered')} US patents retrieved)",
            "",
            f"Patent rationale: {patents.get('rationale')}",
            "",
        ]
        for patent in (patents.get("matched_patents") or [])[:5]:
            lines.append(
                f"- {patent.get('patent_id')} {patent.get('title')} — overlaps: "
                f"{', '.join(patent.get('overlapping_elements') or [])} — {patent.get('url')}"
            )
        matrix = entry.get("coverage_matrix")
        if matrix:
            lines += ["", "**Element coverage matrix** (keyword overlap vs retrieved patents):", ""]
            for element in matrix.get("elements") or []:
                element_id = element.get("id")
                cells = (matrix.get("coverage") or {}).get(element_id) or {}
                covering = [pid for pid, cell in cells.items() if cell.get("covered")]
                status = f"covered by {', '.join(covering)}" if covering else "UNCOVERED"
                lines.append(f"- {element_id} ({element.get('text')}): {status}")
            uncovered = matrix.get("uncovered") or []
            lines += ["", f"Uncovered elements (potential novelty): "
                          f"{', '.join(uncovered) if uncovered else 'none'}"]
        if gate:
            lines += [
                "",
                f"**Feasibility gate:** {'PASS' if gate.get('passed') else 'FAIL'}",
                "",
                f"- Doable ({'pass' if gate.get('doable', {}).get('pass') else 'fail'}): "
                f"{gate.get('doable', {}).get('reasoning')}",
                f"- Scoped ({'pass' if gate.get('scoped', {}).get('pass') else 'fail'}): "
                f"{gate.get('scoped', {}).get('reasoning')}",
            ]
        if decision:
            lines += ["", f"**Decision:** {decision.get('outcome')} — {decision.get('reason')}"]
        pivot = entry.get("pivot")
        if pivot:
            lines += [
                "",
                f"**Pivot ({pivot.get('pivot_direction')}):** {pivot.get('new_idea')}",
                "",
                f"Why it avoids the prior art: {pivot.get('why_it_avoids_prior_art')}",
            ]
            if "pivot_similarity_to_previous" in entry:
                lines.append(f"Similarity to previous pivots: {entry['pivot_similarity_to_previous']}")
        lines.append("")

    lines += [
        "## Audit notes",
        "",
        "- `trace.json` holds the full agent-by-agent log including raw API responses.",
        "- `prior_art.json` holds every retrieved publication and patent per iteration.",
        "- Scores are computed only from retrieved documents; see README for the method.",
        "",
        f"Run duration: {trace.get('duration_seconds')}s",
        "",
    ]
    return "\n".join(lines)


def _pdf_safe(text: str) -> str:
    text = text.encode("latin-1", "replace").decode("latin-1")
    # Break words too long to fit on one line so fpdf can always wrap.
    words = [
        " ".join(word[i:i + 60] for i in range(0, len(word), 60)) if len(word) > 60 else word
        for word in text.split(" ")
    ]
    return " ".join(words).strip() or " "


def _write_pdf(path: Path, markdown: str) -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    for raw_line in markdown.splitlines():
        pdf.set_x(pdf.l_margin)  # some fpdf versions leave the cursor at the right edge
        line = raw_line.replace("**", "").strip()
        if line.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(0, 8, _pdf_safe(line[2:]))
        elif line.startswith("## "):
            pdf.set_font("Helvetica", "B", 13)
            pdf.multi_cell(0, 7, _pdf_safe(line[3:]))
        elif line.startswith("### "):
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(0, 6, _pdf_safe(line[4:]))
        else:
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, _pdf_safe(line))
    pdf.output(str(path))
