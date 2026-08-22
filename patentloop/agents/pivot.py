"""Expert redesign/pivot agent."""

import json

from . import AUTONOMOUS_INSTRUCTION

PIVOT_SCHEMA = {
    "name": "pivot",
    "schema": {
        "type": "object",
        "required": [
            "new_idea_text", "changed_elements", "avoided_claims", "rationale",
        ],
        "properties": {
            "new_idea_text": {"type": "string"},
            "changed_elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["element_id", "change"],
                    "properties": {
                        "element_id": {"type": "string"},
                        "change": {"type": "string"},
                    },
                },
            },
            "avoided_claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["patent_id", "claim_number", "claim_quote"],
                    "properties": {
                        "patent_id": {"type": "string"},
                        "claim_number": {"type": "string"},
                        "claim_quote": {"type": "string"},
                    },
                },
            },
            "rationale": {"type": "string"},
        },
    },
}


def pivot_idea(llm, current_idea: str, field: str, persona_hint: str, collisions: list[dict], closest: list[dict], previous: list[str]):
    output = llm.chat(
        AUTONOMOUS_INSTRUCTION
        + f"Act as an expert in {field} ({persona_hint}). Produce a technically plausible non-repeating redesign.\n"
        + json.dumps(
            {
                "current_idea": current_idea,
                "collisions": collisions,
                "closest_papers": closest,
                "previous_pivots": previous,
            },
            indent=2,
            sort_keys=True,
        ),
        PIVOT_SCHEMA,
        agent="pivot",
    )
    return output, getattr(llm, "last_log_path", None)
