"""Idea decomposition agent."""

from __future__ import annotations

import json

from . import AUTONOMOUS_INSTRUCTION

EXTRACT_SCHEMA = {
    "name": "extract_idea",
    "schema": {
        "type": "object",
        "required": ["elements", "field", "persona_hint"],
        "properties": {
            "elements": {
                "type": "array",
                "minItems": 3,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "required": ["id", "name", "text", "keywords"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "text": {"type": "string"},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "field": {"type": "string"},
            "persona_hint": {"type": "string"},
        },
    },
}


def extract_idea(idea_text: str, llm, *, agent: str = "extract") -> tuple[dict, str | None]:
    output = llm.chat(
        AUTONOMOUS_INSTRUCTION
        + "Decompose an invention into 3 to 6 concrete claim elements.\n\n"
        + json.dumps({"idea": idea_text}, indent=2, sort_keys=True),
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
