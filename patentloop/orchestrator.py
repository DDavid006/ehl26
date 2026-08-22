"""Autonomous PatentLoop state machine."""

from __future__ import annotations

import json
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
from .llm import LLMClient
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


saturation_detector = saturated


class PatentLoop:
    def __init__(self, *, run_dir: Path | str, llm=None, sources=None, require_keys: bool = True, logger=None):
        self.run_dir = Path(run_dir)
        self.writer = ArtifactWriter(self.run_dir)
        self.llm = llm or LLMClient(run_dir=self.run_dir)
        if sources is None:
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
            sources = (
                literature,
                patent_sources,
                not bool(settings.uspto_api_key),
            )
        self.sources = sources
        self.require_keys = require_keys
        self.logger = logger or logging.getLogger("patentloop")

    def _log(self, message: str) -> None:
        with (self.run_dir / "run.log").open("a") as handle:
            handle.write(message + "\n")
        if self.logger:
            self.logger.info(message)

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
        for iteration in range(1, max_iterations + 1):
            self._log(f"iteration {iteration}: extracting claim elements")
            extracted, extract_log = extract_idea(current, self.llm)
            self.writer.event(iteration, "extract", current, extracted, llm_calls=[extract_log] if extract_log else [], session_urls=[self.llm.last_session_url] if getattr(self.llm, "last_session_url", None) else [])
            feasibility, feasibility_logs = FeasibilityAgent(self.llm).run(current, extracted)
            self.writer.event(iteration, "feasibility", extracted, feasibility, llm_calls=feasibility_logs, session_urls=[self.llm.last_session_url] if getattr(self.llm, "last_session_url", None) else [])
            if not feasibility["feasible"]:
                final = "KILLED_INFEASIBLE"
                iteration_rows.append({"iteration": iteration, **feasibility})
                reasoning.extend(item.get("reasoning", "") for item in feasibility["judges"])
                break
            if (
                isinstance(self.sources, tuple)
                and len(self.sources) == 3
            ):
                literature_sources, patent_sources, allow_devin_search = self.sources
            else:
                literature_sources = self.sources[:-1]
                patent_sources = self.sources[-1:]
                allow_devin_search = False
            research = ResearchAgent(self.llm, literature_sources).run(extracted, iteration=iteration, run_dir=self.run_dir)
            patents = PatentSearchAgent(
                self.llm, patent_sources, allow_devin_search=allow_devin_search
            ).run(current, extracted, iteration=iteration, run_dir=self.run_dir)
            self.writer.event(iteration, "research", extracted, research, llm_calls=research.get("llm_paths", []), session_urls=[self.llm.last_session_url] if getattr(self.llm, "last_session_url", None) else [])
            self.writer.event(iteration, "patent_search", extracted, patents, llm_calls=patents.get("llm_paths", []), session_urls=[self.llm.last_session_url] if getattr(self.llm, "last_session_url", None) else [])
            row = {"iteration": iteration, "novelty_score": research["novelty_score"], "overlap_score": patents["overlap_score"], **feasibility}
            iteration_rows.append(row)
            prior_art.append({"iteration": iteration, "idea": current, "research": research, "patents": patents})
            reasoning.extend([research.get("rationale", ""), feasibility["judges"][0].get("reasoning", "")])
            citations.extend(research.get("closest_publications", []))
            overlap_scores.append(patents["overlap_score"])
            if research["novelty_score"] >= NOVELTY_GATE and patents["overlap_score"] <= OVERLAP_GATE:
                draft = DraftingAgent(self.llm).run(current, extracted, research, patents, run_dir=self.run_dir)
                self.writer.event(iteration, "drafting", {"idea": current}, draft, artifacts=[draft["markdown_path"], draft["pdf_path"]], llm_calls=draft["llm_paths"], session_urls=[self.llm.last_session_url] if getattr(self.llm, "last_session_url", None) else [])
                final = "DRAFTED"
                break
            if iteration >= max_iterations or saturated(
                pivot_vectors, overlap_scores, iteration, max_iterations
            ):
                final = "KILLED_SATURATED"
                break
            pivot, pivot_log = pivot_idea(
                self.llm, current, extracted.get("field", ""), extracted.get("persona_hint", ""),
                patents.get("patents", [])[:3], research.get("closest_publications", []), previous_pivots,
            )
            current = pivot["new_idea_text"]
            previous_pivots.append(current)
            vector, vector_log = self.llm.embed([current], agent="pivot_embedding")
            pivot_vectors.append(vector[0])
            self.writer.event(iteration, "pivot", pivot, current, llm_calls=[p for p in (pivot_log, vector_log) if p], session_urls=[self.llm.last_session_url] if getattr(self.llm, "last_session_url", None) else [])
            self._log(f"iteration {iteration}: pivot proposed")
        report_path = self.writer.write_report(final, iteration_rows, reasoning, citations)
        prior_path = self.writer.write_prior_art(prior_art)
        self._log(f"PatentLoop complete: {final}")
        return {"verdict": final, "run_dir": str(self.run_dir), "report": report_path, "prior_art": prior_path, "iterations": iteration_rows}


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
