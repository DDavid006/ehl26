"""Decompose an invention description into functional elements."""

from __future__ import annotations

import json
import re
from typing import Any

from llm import generate_text

MIN_ELEMENTS = 4
MAX_ELEMENTS = 8
MIN_SEARCH_TERMS = 2
MAX_SEARCH_TERMS = 4

PROMPT_TEMPLATE = """You are a patent analyst. Break the invention below into between {min_elements} and {max_elements} distinct functional elements.

Rules:
- Each element must describe what that part of the invention DOES (its function or effect), \
not a restatement of a fragment of the input.
  Bad: "a spray"
  Good: "a delivery format applied without rinsing"
- Give each element between {min_terms} and {max_terms} search terms suitable for a patent \
keyword search: short noun phrases, no boolean operators.
- Ids are "E1", "E2", ... in order.

Return JSON only. No prose, no explanation, no markdown code fences. The response must be a \
JSON array of objects with exactly these keys:
[{{"id": "E1", "text": "...", "search_terms": ["...", "..."]}}]

Invention description:
{description}"""


class DecompositionError(ValueError):
    """Raised when the model response cannot be parsed into functional elements."""


def strip_fences(text: str) -> str:
    """Remove surrounding markdown code fences from a model response."""
    cleaned = text.strip()
    fence = re.match(r"^```[A-Za-z0-9_-]*\s*(.*?)\s*```$", cleaned, flags=re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    else:
        cleaned = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    return cleaned


def extract_json_array(text: str) -> str:
    """Return the outermost JSON array substring of ``text``."""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise DecompositionError("no JSON array found in model response")
    return text[start : end + 1]


def extract_json_object(text: str) -> str:
    """Return the outermost JSON object substring of ``text``."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise DecompositionError("no JSON object found in model response")
    return text[start : end + 1]


def _coerce_element(raw: Any, index: int) -> dict:
    if not isinstance(raw, dict):
        raise DecompositionError(f"element {index} is not an object")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise DecompositionError(f"element {index} has no text")
    terms_raw = raw.get("search_terms")
    if not isinstance(terms_raw, list):
        raise DecompositionError(f"element {index} has no search_terms list")
    terms: list[str] = []
    for term in terms_raw:
        if isinstance(term, str) and term.strip() and term.strip() not in terms:
            terms.append(term.strip())
    if len(terms) < MIN_SEARCH_TERMS:
        raise DecompositionError(f"element {index} needs at least {MIN_SEARCH_TERMS} search terms")
    element_id = raw.get("id")
    if not isinstance(element_id, str) or not element_id.strip():
        element_id = f"E{index + 1}"
    return {
        "id": element_id.strip(),
        "text": text.strip(),
        "search_terms": terms[:MAX_SEARCH_TERMS],
    }


def _parse_response(text: str) -> list[dict]:
    if not isinstance(text, str) or not text.strip():
        raise DecompositionError("empty model response")
    payload = extract_json_array(strip_fences(text))
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise DecompositionError(f"invalid JSON in model response: {exc}") from exc
    if not isinstance(data, list):
        raise DecompositionError("model response is not a JSON array")
    elements = [_coerce_element(raw, index) for index, raw in enumerate(data)]
    if not MIN_ELEMENTS <= len(elements) <= MAX_ELEMENTS:
        raise DecompositionError(
            f"expected {MIN_ELEMENTS}-{MAX_ELEMENTS} elements, got {len(elements)}"
        )
    return elements


def _generate(description: str) -> str:
    return generate_text(
        PROMPT_TEMPLATE.format(
            min_elements=MIN_ELEMENTS,
            max_elements=MAX_ELEMENTS,
            min_terms=MIN_SEARCH_TERMS,
            max_terms=MAX_SEARCH_TERMS,
            description=description.strip(),
        ),
        DecompositionError,
    )


def decompose_invention(description: str) -> list[dict]:
    """Break ``description`` into 4-8 functional elements.

    Retries once if the model response cannot be parsed, then raises
    :class:`DecompositionError`.
    """
    if not description or not description.strip():
        raise DecompositionError("description must not be empty")

    last_error: DecompositionError | None = None
    for _ in range(2):
        try:
            return _parse_response(_generate(description))
        except DecompositionError as exc:
            last_error = exc
    raise last_error if last_error else DecompositionError("decomposition failed")
