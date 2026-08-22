"""Autonomous PatentLoop state machine."""

from __future__ import annotations

import logging
import math
from pathlib import Path

from .agents.drafting import DraftingAgent
from .agents.extract import extract_idea
from .agents.feasibility import FeasibilityAgent
from .agents.patent_search import PatentSearchAgent
from .agents.pivot import pivot_idea
from .agents.research import ResearchAgent, cosine
from .artifacts import ArtifactWriter
from .config import (
    MAX_ITERATIONS,
    NOVELTY_GATE,
    OVERLAP_GATE,
    SATURATION_COSINE,
    SATURATION_OVERLAP,
    Settings,
    require_live_keys,
)
from .errors import EvidenceFailure
from .llm import Judge
from .sources.arxiv import ArxivSource
from .sources.crossref import CrossrefSource
from .sources.github import GitHubSource
from .sources.openalex import OpenAlexSource
from .sources.semantic_scholar import SemanticScholarSource
from .sources.uspto_odp import USPTOODPSource
from .sources.epo_ops import EPOOPSSource


def saturated(
    pivot_vectors: list[list[float]],
    overlap_scores: list[int],
    iteration: int,
    max_iterations: int = MAX_ITERATIONS,
) -> bool:
    if iteration >= max_iterations and overlap_scores and overlap_scores[-1] > OVERLAP_GATE:
        return True
    if len(pivot_vectors) < 2 or len(overlap_scores) < 2:
        return False
    return (
        cosine(pivot_vectors[-1], pivot_vectors[-2]) > SATURATION_COSINE
        and overlap_scores[-1] >= SATURATION_OVERLAP
        and overlap_scores[-2] >= SATURATION_OVERLAP
    )


class PatentLoop:
    def __init__(
        self,
        *,
        run_dir: Path | str,
        llm=None,
        literature_sources=None,
        patent_sources=None,
        allow_devin_search: bool | None = None,
        require_keys: bool = True,
        logger=None,
    ):
        self.run_dir = Path(run_dir)
        self.writer = ArtifactWriter(self.run_dir)
        self.llm = llm or Judge(run_dir=self.run_dir)
        if literature_sources is None and patent_sources is None and allow_devin_search is None:
            settings = getattr(self.llm, "settings", Settings())
            session = getattr(self.llm, "session", None)
            literature = [
                SemanticScholarSource(session, settings.semantic_scholar_key),
                ArxivSource(session), OpenAlexSource(session), CrossrefSource(session),
                GitHubSource(settings.github_token, session),
            ]
            patent_sources = []
            if settings.uspto_api_key:
                patent_sources.append(USPTOODPSource(settings.uspto_api_key, session))
            if settings.epo_key and settings.epo_secret:
                patent_sources.append(EPOOPSSource(settings.epo_key, settings.epo_secret, session))
            literature_sources = literature
            patent_sources = patent_sources
            allow_devin_search = not bool(settings.uspto_api_key)
        self.literature_sources = literature_sources or []
        self.patent_sources = patent_sources or []
        self.allow_devin_search = bool(allow_devin_search)
        self.require_keys = require_keys
        self.logger = logger or logging.getLogger("patentloop")

    def _log(self, message: str) -> None:
        with (self.run_dir / "run.log").open("a") as handle:
            handle.write(message + "\n")
        if self.logger:
            self.logger.info(message)

    def _session_urls(self) -> list[str]:
        url = getattr(self.llm, "last_session_url", None)
        return [url] if url else []

    def run(self, idea_text: str, *, max_iterations: int = MAX_ITERATIONS) -> dict:
        if self.require_keys:
            require_live_keys(getattr(self.llm, "settings", Settings()))
        self._log("PatentLoop started")
        current = idea_text
        previous_pivots: list[str] = []
        pivot_vectors: list[list[float]] = []
        overlap_scores: list[int] = []
        iteration_rows, prior_art, reasoning, citations = [], [], [], []
        final = "KILLED_SATURATED"
        termination_reason = "iteration_cap"
        pivot_lineage = [{"version": 1, "idea": current}]
        failure = None
        for iteration in range(1, max_iterations + 1):
            self._log(f"iteration {iteration}: extracting claim elements")
            extracted, extract_log = extract_idea(current, self.llm)
            self.writer.event(
                iteration, "extract", current, extracted,
                llm_calls=[extract_log] if extract_log else [],
                session_urls=self._session_urls(),
            )
            feasibility, feasibility_logs = FeasibilityAgent(self.llm).run(current, extracted)
            self.writer.event(
                iteration, "feasibility", extracted, feasibility,
                llm_calls=feasibility_logs, session_urls=self._session_urls(),
            )
            if not feasibility["feasible"]:
                final = "KILLED_INFEASIBLE"
                termination_reason = "feasibility_failure"
                iteration_rows.append(
                    {
                        "iteration": iteration,
                        **feasibility,
                        "gate_decision": "killed_infeasible",
                        "termination_reason": termination_reason,
                    }
                )
                reasoning.extend(
                    f"feasibility judge {index + 1}: {item.get('reasoning', '')}"
                    for index, item in enumerate(feasibility["judges"])
                )
                break
            try:
                research = ResearchAgent(
                    self.llm, self.literature_sources
                ).run(extracted, iteration=iteration, run_dir=self.run_dir)
                patents = PatentSearchAgent(
                    self.llm,
                    self.patent_sources,
                    allow_devin_search=self.allow_devin_search,
                ).run(current, extracted, iteration=iteration, run_dir=self.run_dir)
            except EvidenceFailure as exc:
                failure = exc
                termination_reason = "evidence_failure"
                details = {"error": str(exc), **exc.details}
                self.writer.event(
                    iteration, "evidence_failure", extracted, details,
                    session_urls=self._session_urls(),
                )
                iteration_rows.append(
                    {
                        "iteration": iteration,
                        **details,
                        "gate_decision": "infrastructure_failure",
                        "termination_reason": termination_reason,
                    }
                )
                reasoning.append(f"evidence failure: {exc}")
                break
            self.writer.event(
                iteration, "research", extracted, research,
                llm_calls=research.get("llm_paths", []),
                session_urls=self._session_urls(),
            )
            self.writer.event(
                iteration, "patent_search", extracted, patents,
                llm_calls=patents.get("llm_paths", []),
                session_urls=self._session_urls(),
            )
            blocking = patents.get("patents", [])
            top_blocking = None
            if blocking:
                top_blocking = {
                    "id": blocking[0].get("id"),
                    "title": blocking[0].get("title"),
                    "claim_quote": next(
                        (
                            item.get("claim_quote")
                            for item in blocking[0].get("element_verdicts", [])
                            if item.get("claim_quote")
                        ),
                        "",
                    ),
                }
            row = {
                "iteration": iteration,
                "novelty_score": research["novelty_score"],
                "element_scores": research.get("element_scores", {}),
                "unverified_elements": research.get("unverified_elements", []),
                "overlap_score": patents["overlap_score"],
                "patents_examined": patents.get("patents_examined", 0),
                "top_blocking_patent": top_blocking,
                "gate_decision": "pending",
                **feasibility,
            }
            iteration_rows.append(row)
            prior_art.append({"iteration": iteration, "idea": current, "research": research, "patents": patents})
            reasoning.append(f"novelty rationale: {research.get('rationale', '')}")
            reasoning.extend(
                f"feasibility judge {index + 1}: {item.get('reasoning', '')}"
                for index, item in enumerate(feasibility["judges"])
            )
            citations.extend(research.get("closest_publications", []))
            overlap_scores.append(patents["overlap_score"])
            evidence_ready = (
                research.get("verified_elements", 0)
                >= max(2, math.ceil(len(extracted["elements"]) / 2))
                and patents.get("patents_examined", 0) > 0
            )
            if (
                research["novelty_score"] >= NOVELTY_GATE
                and patents["overlap_score"] <= OVERLAP_GATE
                and evidence_ready
            ):
                row["gate_decision"] = "drafted"
                row["termination_reason"] = "gates_passed"
                termination_reason = "gates_passed"
                draft = DraftingAgent(self.llm).run(current, extracted, research, patents, run_dir=self.run_dir)
                self.writer.event(
                    iteration, "drafting", {"idea": current}, draft,
                    artifacts=[draft["markdown_path"], draft["pdf_path"]],
                    llm_calls=draft["llm_paths"],
                    session_urls=self._session_urls(),
                )
                final = "DRAFTED"
                break
            pivot_saturated = (
                len(pivot_vectors) >= 2
                and len(overlap_scores) >= 2
                and saturated(pivot_vectors, overlap_scores, iteration, max_iterations)
            )
            if iteration >= max_iterations:
                final = "KILLED_SATURATED"
                termination_reason = (
                    "saturated_pivot_space"
                    if pivot_saturated
                    else (
                        "novelty_below_gate"
                        if research["novelty_score"] < NOVELTY_GATE
                        else "iteration_cap"
                    )
                )
                row["gate_decision"] = "killed_saturated"
                row["termination_reason"] = termination_reason
                break
            if pivot_saturated:
                final = "KILLED_SATURATED"
                termination_reason = "saturated_pivot_space"
                row["gate_decision"] = "killed_saturated"
                row["termination_reason"] = termination_reason
                break
            row["gate_decision"] = "pivot"
            row["termination_reason"] = "pivot"
            pivot, pivot_log = pivot_idea(
                self.llm, current, extracted.get("field", ""), extracted.get("persona_hint", ""),
                patents.get("patents", [])[:3], research.get("closest_publications", []), previous_pivots,
            )
            current = pivot["new_idea_text"]
            previous_pivots.append(current)
            pivot_lineage.append({"version": iteration + 1, "idea": current})
            vector, vector_log = self.llm.embed([current], agent="pivot_embedding")
            pivot_vectors.append(vector[0])
            self.writer.event(
                iteration, "pivot", pivot, current,
                llm_calls=[p for p in (pivot_log, vector_log) if p],
                session_urls=self._session_urls(),
            )
            self._log(f"iteration {iteration}: pivot proposed")
        self.writer.event(
            iteration if iteration_rows else 0,
            "termination",
            {"verdict": final},
            {"verdict": final, "termination_reason": termination_reason},
            session_urls=self._session_urls(),
        )
        report_path = self.writer.write_report(
            final,
            iteration_rows,
            reasoning,
            citations,
            termination_reason=termination_reason,
            pivot_lineage=pivot_lineage,
        )
        prior_path = self.writer.write_prior_art(prior_art)
        self._log(f"PatentLoop complete: {final}")
        if failure is not None:
            raise failure
        return {
            "verdict": final,
            "termination_reason": termination_reason,
            "run_dir": str(self.run_dir),
            "report": report_path,
            "prior_art": prior_path,
            "iterations": iteration_rows,
        }


def run_pipeline(
    idea_text: str,
    run_dir: Path | str,
    *,
    max_iterations: int = MAX_ITERATIONS,
    **kwargs,
) -> dict:
    return PatentLoop(run_dir=run_dir, **kwargs).run(
        idea_text, max_iterations=max_iterations
    )
