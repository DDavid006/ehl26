"""Expert Pivot Agent: proposes an adjacent-gap variant when overlap is high."""

from __future__ import annotations

from typing import Any

from ..llm import chat_json

PIVOT_SYSTEM_TEMPLATE = (
    "You are a world-class domain expert in {field} with deep knowledge of the patent landscape. "
    "The idea below collided with specific prior art. Propose ONE concrete, still-feasible variant "
    "that occupies a genuine adjacent technical gap - a different mechanism, structure, or method - "
    "not a cosmetic rewording. The variant must keep the original goal but avoid the specific "
    "colliding claims and publications listed.\n"
    'Return JSON: {"new_idea": "<2-4 sentence self-contained description of the variant>", '
    '"why_it_avoids_prior_art": "<explain, per colliding patent/publication, why the variant '
    'does not read on it>", "pivot_direction": "<5-10 word label for the direction taken>"}'
)


def run_pivot(idea: str, field: str, research: dict[str, Any], patent_search: dict[str, Any]) -> dict[str, Any]:
    collisions = {
        "overlapping_patents": [
            {
                "patent_id": p.get("patent_id"),
                "title": p.get("title"),
                "overlapping_elements": p.get("overlapping_elements"),
                "overlapping_text": p.get("overlapping_text"),
            }
            for p in patent_search.get("matched_patents") or []
        ],
        "closest_publications": research.get("closest_prior_work") or [],
    }
    verdict = chat_json(
        PIVOT_SYSTEM_TEMPLATE.replace("{field}", field),
        f"ORIGINAL IDEA:\n{idea}\n\nCOLLIDING PRIOR ART:\n{collisions}",
        temperature=0.7,
    )
    return {
        "agent": "expert_pivot",
        "persona_field": field,
        "new_idea": verdict.get("new_idea") or idea,
        "why_it_avoids_prior_art": verdict.get("why_it_avoids_prior_art") or "",
        "pivot_direction": verdict.get("pivot_direction") or "",
    }
