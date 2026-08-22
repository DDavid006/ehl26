"""Stateful orchestrator: runs the loop, detects saturation, terminates in one
of exactly three states: DRAFTED, KILLED_SATURATED, KILLED_INFEASIBLE."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .agents import extract_elements, run_drafting, run_feasibility_gate, run_patent_search, run_pivot, run_research
from .artifacts import write_artifacts
from .coverage import build_matrix, elements_from_extraction
from .llm import cosine, embed

MAX_ITERATIONS = 4
NOVELTY_HIGH = 60
OVERLAP_LOW = 40
OVERLAP_HIGH = 60
# Successive pivot proposals this similar are converging on the same blocked territory.
PIVOT_CONVERGENCE = 0.86

ProgressFn = Callable[[str, dict[str, Any]], None]


def _noop(_event: str, _data: dict[str, Any]) -> None:
    pass


def run_loop(idea: str, runs_dir: str | Path = "runs", progress: ProgressFn = _noop) -> dict[str, Any]:
    """Run the full PatentLoop on ``idea``. Returns the final result dict and
    writes all artifacts to ``<runs_dir>/<run_id>/``."""
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    started = time.time()
    trace: dict[str, Any] = {"run_id": run_id, "input_idea": idea, "started_at": started, "iterations": []}
    lineage: list[str] = [idea]
    pivot_embeddings: list[list[float]] = []
    status: str | None = None
    kill_reason = ""
    draft: dict[str, Any] | None = None

    current = idea
    for iteration in range(1, MAX_ITERATIONS + 1):
        entry: dict[str, Any] = {"iteration": iteration, "idea": current}
        trace["iterations"].append(entry)

        progress("extract", {"iteration": iteration, "idea": current})
        extraction = extract_elements(current)
        entry["extraction"] = extraction
        progress("extracted", {"iteration": iteration, **extraction})

        progress("research", {"iteration": iteration})
        research = run_research(current, extraction)
        entry["research"] = research
        progress("research_done", {
            "iteration": iteration,
            "novelty_score": research["novelty_score"],
            "documents_considered": research["documents_considered"],
            "closest_prior_work": research["closest_prior_work"][:3],
        })

        progress("patent_search", {"iteration": iteration})
        patent_search = run_patent_search(current, extraction)
        entry["patent_search"] = patent_search
        matrix = build_matrix(elements_from_extraction(extraction), patent_search["records"])
        entry["coverage_matrix"] = matrix
        progress("coverage", {
            "iteration": iteration,
            "elements": [{"id": e["id"], "text": e["text"]} for e in matrix["elements"]],
            "patents": [{"patent_id": p.get("patent_id"), "title": p.get("title"),
                         "url": p.get("url")} for p in matrix["patents"]],
            "coverage": matrix["coverage"],
            "uncovered": matrix["uncovered"],
        })
        progress("patent_search_done", {
            "iteration": iteration,
            "overlap_score": patent_search["overlap_score"],
            "patents_considered": patent_search["patents_considered"],
            "matched_patents": [
                {k: p.get(k) for k in ("patent_id", "title", "overlapping_elements")}
                for p in patent_search["matched_patents"][:4]
            ],
        })

        progress("feasibility", {"iteration": iteration})
        gate = run_feasibility_gate(current, extraction)
        entry["feasibility_gate"] = gate
        progress("feasibility_done", {"iteration": iteration, "passed": gate["passed"],
                                      "doable": gate["doable"]["pass"], "scoped": gate["scoped"]["pass"]})

        if not gate["passed"]:
            status = "KILLED_INFEASIBLE"
            failed = [name for name in ("doable", "scoped") if not gate[name]["pass"]]
            kill_reason = f"Feasibility gate failed ({', '.join(failed)}) on iteration {iteration}."
            entry["decision"] = {"outcome": "kill_infeasible", "reason": kill_reason}
            break

        novelty = research["novelty_score"]
        overlap = patent_search["overlap_score"]
        if novelty >= NOVELTY_HIGH and overlap <= OVERLAP_LOW:
            entry["decision"] = {"outcome": "draft", "reason":
                                 f"novelty {novelty} >= {NOVELTY_HIGH} and overlap {overlap} <= {OVERLAP_LOW}"}
            progress("drafting", {"iteration": iteration})
            draft = run_drafting(current, extraction, research, patent_search)
            entry["draft"] = {"produced": True}
            status = "DRAFTED"
            break

        if iteration == MAX_ITERATIONS:
            status = "KILLED_SATURATED"
            kill_reason = (f"Iteration cap ({MAX_ITERATIONS}) reached with overlap still "
                           f"{overlap} / novelty {novelty}; the field is saturated.")
            entry["decision"] = {"outcome": "kill_saturated", "reason": kill_reason}
            break

        entry["decision"] = {"outcome": "pivot", "reason":
                             f"overlap {overlap} > {OVERLAP_LOW} or novelty {novelty} < {NOVELTY_HIGH}"}
        progress("pivot", {"iteration": iteration, "field": extraction["field"]})
        pivot = run_pivot(current, extraction["field"], research, patent_search)
        entry["pivot"] = pivot
        progress("pivot_done", {"iteration": iteration, "new_idea": pivot["new_idea"],
                                "pivot_direction": pivot["pivot_direction"]})

        vector = embed([pivot["new_idea"]])[0]
        if pivot_embeddings:
            similarity = max(cosine(vector, prev) for prev in pivot_embeddings)
            entry["pivot_similarity_to_previous"] = round(similarity, 4)
            if similarity >= PIVOT_CONVERGENCE and overlap >= OVERLAP_HIGH:
                status = "KILLED_SATURATED"
                kill_reason = (f"Pivot proposals converged (cosine {similarity:.2f} >= "
                               f"{PIVOT_CONVERGENCE}) while overlap stayed high ({overlap}); "
                               "the pivot space is shrinking into the same blocked territory.")
                entry["decision"] = {"outcome": "kill_saturated", "reason": kill_reason}
                break
        pivot_embeddings.append(vector)
        current = pivot["new_idea"]
        lineage.append(current)

    trace["lineage"] = lineage
    trace["status"] = status
    trace["kill_reason"] = kill_reason
    trace["finished_at"] = time.time()
    trace["duration_seconds"] = round(trace["finished_at"] - started, 1)

    run_dir = Path(runs_dir) / run_id
    write_artifacts(run_dir, trace, draft)
    progress("done", {"status": status, "run_dir": str(run_dir), "kill_reason": kill_reason})
    return {"run_id": run_id, "run_dir": str(run_dir), "status": status,
            "kill_reason": kill_reason, "lineage": lineage,
            "draft_markdown": (draft or {}).get("draft_markdown")}
