"""Idea decomposition agent."""

from __future__ import annotations

EXTRACT_SCHEMA = {
    "name": "extract_idea",
    "schema": {
        "type": "object",
        "required": ["elements", "field", "persona_hint"],
        "properties": {
            "elements": {"type": "array", "minItems": 3, "maxItems": 6},
            "field": {"type": "string"},
            "persona_hint": {"type": "string"},
        },
    },
}


def extract_idea(idea_text: str, llm, *, agent: str = "extract") -> tuple[dict, str | None]:
    output = llm.chat(
        "Decompose an invention into 3 to 6 concrete claim elements.\n\n"
        + idea_text,
        EXTRACT_SCHEMA,
        agent=agent,
    )
    elements = output.get("elements", [])
    if not 3 <= len(elements) <= 6:
        raise ValueError("Extract agent must return between 3 and 6 elements")
    for index, element in enumerate(elements, 1):
        element.setdefault("id", f"e{index}")
        element.setdefault("keywords", [])
        if not element.get("text"):
            raise ValueError("Extracted elements require text")
    return output, getattr(llm, "last_log_path", None)
