"""Run artifacts: report.md, prior_art.json, draft_application.md, trace.json."""

from __future__ import annotations

import json
from pathlib import Path

from .config import NOVELTY_PASS, OVERLAP_BLOCK
from .schemas import DRAFTED, RunResult
from .trace import Tracer

VERDICT_BLURB = {
    DRAFTED: "A provisional application draft was produced.",
    "KILLED_SATURATED": "No non-overlapping variant was found; the field is saturated.",
    "KILLED_INFEASIBLE": "The idea failed the feasibility gate and was killed without pivoting.",
}


def prior_art_payload(result: RunResult) -> dict:
    return {
        "run_id": result.run_id,
        "iterations": [
            {
                "iteration": it.index,
                "idea_version": it.idea.version,
                "idea_text": it.idea.text,
                "elements": it.idea.elements,
                "research": {
                    "novelty_score": it.research.novelty_score,
                    "queries": it.research.queries,
                    "sources_used": it.research.sources_used,
                    "element_scores": [e.as_dict() for e in it.research.element_scores],
                    "documents": [d.as_dict() for d in it.research.documents],
                }
                if it.research
                else None,
                "patents": {
                    "overlap_score": it.patents.overlap_score,
                    "queries": it.patents.queries,
                    "sources_used": it.patents.sources_used,
                    "matches": [m.as_dict() for m in it.patents.matches],
                    "all_hits": [h.as_dict() for h in it.patents.hits],
                }
                if it.patents
                else None,
            }
            for it in result.iterations
        ],
    }


def _iteration_section(iteration) -> str:
    idea, research, patents = iteration.idea, iteration.research, iteration.patents
    lines = [f"### Iteration {iteration.index} — idea v{idea.version}: {idea.title or 'untitled'}"]
    if idea.parent_version:
        lines.append(f"*Pivoted from v{idea.parent_version} because:* {idea.derived_because}")
    lines += ["", "**Idea text**", "", f"> {idea.text}", ""]
    if idea.elements:
        lines += ["**Extracted claim elements**", ""]
        lines += [f"{n}. {element}" for n, element in enumerate(idea.elements, 1)]
        lines.append("")
    if research:
        lines += [
            f"**Research agent — novelty_score {research.novelty_score}/100** "
            f"(sources: {', '.join(research.sources_used) or 'none reachable'}; "
            f"{len(research.documents)} documents retrieved)",
            "",
            "| element | LLM similarity | tf-idf similarity | blended | closest retrieved |",
            "| --- | --- | --- | --- | --- |",
        ]
        for score in research.element_scores:
            cites = ", ".join(score.closest_document_ids[:3]) or "—"
            lines.append(
                f"| {score.element[:70]} | {score.llm_similarity} | {score.lexical_similarity} | "
                f"{score.similarity} | {cites} |"
            )
        lines += ["", f"*Rationale:* {research.rationale}", ""]
        if research.documents:
            lines += ["<details><summary>Closest publications retrieved</summary>", ""]
            for doc in research.documents[:10]:
                lines.append(f"- [{doc.source}] [{doc.title}]({doc.url}) ({doc.year or 'n/a'})")
            lines += ["", "</details>", ""]
    if patents:
        lines += [
            f"**Patent search agent — overlap_score {patents.overlap_score}/100** "
            f"(sources: {', '.join(patents.sources_used) or 'none reachable'}; "
            f"{len(patents.hits)} patents retrieved, {len(patents.matches)} claim-compared)",
            "",
        ]
        if patents.matches:
            lines += [
                "| patent | assignee | element coverage | tf-idf | match | overlapping elements |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
            for match in patents.matches:
                lines.append(
                    f"| [{match.publication_number}]({match.url}) | {match.assignee or '—'} | "
                    f"{match.llm_overlap} | {match.lexical_overlap} | {match.match_score} | "
                    f"{', '.join(e[:40] for e in match.overlapping_elements) or '—'} |"
                )
            lines.append("")
            for match in patents.matches:
                colliding = [c for c in match.collisions if c.reads_on]
                if not colliding:
                    continue
                lines += [f"<details><summary>{match.publication_number} colliding claims</summary>", ""]
                for collision in colliding:
                    lines.append(
                        f"- element *{collision.element}* reads on claim {collision.claim_number}: "
                        f"\"{collision.claim_text[:400]}\" — {collision.reasoning}"
                    )
                lines += ["", "</details>", ""]
        else:
            lines += ["No retrieved patent had claim text to compare.", ""]
    if iteration.feasibility:
        feas = iteration.feasibility
        lines += [
            f"**Feasibility gate — doable: {feas.doable}, scoped: {feas.scoped}**",
            "",
            f"*Doability reasoning:* {feas.doable_reasoning}",
            "",
            f"*Scope reasoning:* {feas.scoped_reasoning}",
            "",
        ]
        if feas.violated_constraints:
            lines += [f"*Violated constraints:* {'; '.join(feas.violated_constraints)}", ""]
        if feas.claimable_mechanism:
            lines += [f"*Claimable mechanism identified:* {feas.claimable_mechanism}", ""]
    for decision in iteration.decisions:
        lines.append(f"**Gate `{decision.gate}` -> `{decision.decision}`**: {decision.reason}")
        lines.append("")
    if iteration.pivot:
        pivot = iteration.pivot
        lines += [
            f"**Expert pivot agent** (persona: {pivot.persona})",
            "",
            f"Proposed variant — *{pivot.variant_title}*",
            "",
            f"> {pivot.variant_text}",
            "",
            f"*Why it avoids the blocking claims:* {pivot.avoids}",
            "",
            f"*Still feasible because:* {pivot.still_feasible_reasoning}",
            "",
        ]
        if pivot.blocked_territory:
            lines += [f"*Blocked territory reported:* {'; '.join(pivot.blocked_territory)}", ""]
        if iteration.pivot_similarity_to_previous is not None:
            lines += [
                f"*tf-idf similarity to previous pivot:* {iteration.pivot_similarity_to_previous}",
                "",
            ]
    return "\n".join(lines)


def build_report(result: RunResult) -> str:
    first = result.iterations[0] if result.iterations else None
    versions = " -> ".join(f"v{it.idea.version}" for it in result.iterations)
    header = [
        f"# PatentLoop run `{result.run_id}`",
        "",
        f"## Verdict: **{result.outcome}**",
        "",
        f"{VERDICT_BLURB.get(result.outcome, '')}",
        "",
        f"**Reason:** {result.reason}",
        "",
        f"- Started: {result.started_at} · finished: {result.finished_at}",
        f"- Idea lineage: {versions}",
        f"- Iterations: {len(result.iterations)}",
        f"- Thresholds: novelty >= {NOVELTY_PASS}, blocking overlap >= {OVERLAP_BLOCK}",
        "",
        "### Original idea as submitted",
        "",
        f"> {first.idea.text if first else ''}",
        "",
        "### Score trace",
        "",
        "| iteration | idea | novelty_score | overlap_score | feasible | gate outcome |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for it in result.iterations:
        gates = ", ".join(f"{d.gate}:{d.decision}" for d in it.decisions) or "—"
        header.append(
            f"| {it.index} | v{it.idea.version} {it.idea.title[:40]} | "
            f"{it.research.novelty_score if it.research else '—'} | "
            f"{it.patents.overlap_score if it.patents else '—'} | "
            f"{it.feasibility.passed if it.feasibility else '—'} | {gates} |"
        )
    header += [
        "",
        "Every number above is recomputable from `prior_art.json` (retrieved documents, claim text "
        "and per-element scores) and `trace.json` (every API response, prompt, completion and gate "
        "decision, with raw payloads under `raw/`).",
        "",
        "## Iteration detail",
        "",
    ]
    body = "\n\n".join(_iteration_section(it) for it in result.iterations)
    footer = ""
    if result.outcome == DRAFTED:
        footer = "\n\n## Artifact\n\nSee `draft_application.md` for the drafted provisional application.\n"
    return "\n".join(header) + body + footer


def write_artifacts(result: RunResult, tracer: Tracer) -> dict[str, Path]:
    run_dir = Path(result.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    report = run_dir / "report.md"
    report.write_text(build_report(result), encoding="utf-8")
    written["report.md"] = report

    prior_art = run_dir / "prior_art.json"
    prior_art.write_text(json.dumps(prior_art_payload(result), indent=2), encoding="utf-8")
    written["prior_art.json"] = prior_art

    if result.draft:
        draft = run_dir / "draft_application.md"
        draft.write_text(result.draft, encoding="utf-8")
        written["draft_application.md"] = draft

    result_path = run_dir / "result.json"
    result_path.write_text(json.dumps(result.as_dict(), indent=2), encoding="utf-8")
    written["result.json"] = result_path

    written["trace.json"] = tracer.write_trace(
        {
            "outcome": result.outcome,
            "reason": result.reason,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "lineage": [
                {
                    "version": it.idea.version,
                    "parent_version": it.idea.parent_version,
                    "text": it.idea.text,
                    "elements": it.idea.elements,
                    "derived_because": it.idea.derived_because,
                }
                for it in result.iterations
            ],
        }
    )
    return written
