"""Drafting Agent: writes the provisional-patent-style application."""

from __future__ import annotations

from typing import Any

from ..llm import chat_text

DRAFT_SYSTEM = (
    "You are an experienced patent attorney drafting a PROVISIONAL patent application as a "
    "drafting aid (not legal advice, not USPTO-filable). Write in markdown with exactly these "
    "sections:\n"
    "# <Title>\n"
    "## Field of the Invention\n"
    "## Background\n(reference the retrieved prior art and how this invention differs)\n"
    "## Summary\n"
    "## Detailed Description\n(concrete mechanism/structure/steps, at least 4 paragraphs)\n"
    "## Claims\n(1 independent claim + at least 3 dependent claims, numbered)\n"
    "## Why This Is Novel\n(plain English, citing the specific prior art it does NOT overlap, "
    "by title/patent number)\n"
    "## Disclaimer\n(state this is an AI-generated drafting aid, not legal advice)"
)


def run_drafting(idea: str, extraction: dict[str, Any], research: dict[str, Any],
                 patent_search: dict[str, Any]) -> dict[str, Any]:
    prior_art = {
        "closest_publications": research.get("closest_prior_work") or [],
        "nearest_patents": [
            {"patent_id": p.get("patent_id"), "title": p.get("title")}
            for p in (patent_search.get("records") or [])[:8]
        ],
        "novelty_score": research.get("novelty_score"),
        "overlap_score": patent_search.get("overlap_score"),
    }
    draft = chat_text(
        DRAFT_SYSTEM,
        f"INVENTION:\n{idea}\n\nCORE ELEMENTS: {extraction['elements']}\n\n"
        f"FIELD: {extraction['field']}\n\nRETRIEVED PRIOR ART CONTEXT:\n{prior_art}",
    )
    return {"agent": "drafting", "draft_markdown": draft}
