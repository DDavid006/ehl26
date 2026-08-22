"""Model-based coverage judging: one LLM call per patent rules on every element.

``build_matrix`` here has the same shape as :func:`coverage.build_matrix` but the
covered/evidence cells come from the model instead of keyword overlap. A cell's
quote must appear verbatim in the reference text, otherwise that cell falls back
to the keyword matcher; a failed call falls back for the whole patent, so the
matrix is always complete. ``COVERAGE_JUDGE=keyword`` disables the model path.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import coverage
from coverage import _element_key, _patent_key
from decompose import extract_json_array, strip_fences
from llm import generate_text

MODE = os.getenv("COVERAGE_JUDGE", "llm").strip().lower() or "llm"

PROMPT_TEMPLATE = """You are a patent analyst filling in one column of an element-by-reference \
coverage matrix.

Reference {patent_id}:
Title: {title}
Abstract: {abstract}

Functional elements of the invention under examination:
{elements}

For each element decide whether this reference discloses it. Disclosure means the reference \
describes the same function or mechanism, even in different words; a shared word without the \
same function is not disclosure.

Rules:
- "quote" must be copied verbatim from the reference title or abstract above — the exact \
substring that discloses the element. Empty string when covered is false.
- Judge only from the text above. If the text is too thin to tell, the element is not covered.

Return JSON only. No prose, no markdown code fences. A JSON array with one object per element, \
in order, with exactly these keys:
[{{"id": "E1", "covered": true, "quote": "..."}}]"""


class CoverageJudgeError(ValueError):
    """Raised when the model response cannot be parsed into coverage cells."""


_CACHE: dict[tuple, dict[str, dict[str, Any]]] = {}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _fingerprint(elements: list[dict], patent: dict) -> tuple:
    return (
        tuple((element.get("id"), element.get("text")) for element in elements),
        patent.get("patent_id"),
        patent.get("title"),
        patent.get("abstract"),
    )


def _keyword_cell(element: dict, patent: dict) -> dict[str, Any]:
    covered, evidence = coverage.is_covered(element, patent)
    return {"covered": covered, "evidence": evidence}


def _format_elements(elements: list[dict]) -> str:
    lines = []
    for index, element in enumerate(elements):
        lines.append(f"- {_element_key(element, index)}: {element.get('text') or ''}")
    return "\n".join(lines)


def _parse_response(text: str, element_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(text, str) or not text.strip():
        raise CoverageJudgeError("empty model response")
    try:
        payload = extract_json_array(strip_fences(text))
    except ValueError as exc:
        raise CoverageJudgeError(str(exc)) from exc
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise CoverageJudgeError(f"invalid JSON in model response: {exc}") from exc
    if not isinstance(data, list):
        raise CoverageJudgeError("model response is not a JSON array")

    by_id: dict[str, dict[str, Any]] = {}
    for raw in data:
        if not isinstance(raw, dict):
            continue
        element_id = raw.get("id")
        if not isinstance(element_id, str) or element_id not in element_ids:
            continue
        quote = raw.get("quote")
        by_id[element_id] = {
            "covered": bool(raw.get("covered")),
            "quote": quote if isinstance(quote, str) else "",
        }
    missing = [element_id for element_id in element_ids if element_id not in by_id]
    if missing:
        raise CoverageJudgeError(f"model response is missing elements: {', '.join(missing)}")
    return by_id


def judge_patent(elements: list[dict], patent: dict) -> dict[str, dict[str, Any]]:
    """Return ``{element_id: {covered, evidence}}`` for ``patent`` over ``elements``.

    The model's quote is only trusted when it appears verbatim (whitespace and
    case insensitive) in the reference text; otherwise the cell falls back to
    the keyword matcher. Results are cached per (elements, patent) pair, so the
    revision loop never re-judges a reference it has already seen.
    """
    key = _fingerprint(elements, patent)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    element_ids = [_element_key(element, index) for index, element in enumerate(elements)]
    reference_text = _normalize(f"{patent.get('title') or ''} {patent.get('abstract') or ''}")

    response = generate_text(
        PROMPT_TEMPLATE.format(
            patent_id=patent.get("patent_id") or "unknown",
            title=patent.get("title") or "(no title)",
            abstract=patent.get("abstract") or "(no abstract)",
            elements=_format_elements(elements),
        ),
        CoverageJudgeError,
    )
    by_id = _parse_response(response, element_ids)

    cells: dict[str, dict[str, Any]] = {}
    for index, element in enumerate(elements):
        element_id = element_ids[index]
        verdict = by_id[element_id]
        if not verdict["covered"]:
            cells[element_id] = {"covered": False, "evidence": ""}
            continue
        quote = verdict["quote"].strip()
        if quote and _normalize(quote) in reference_text:
            cells[element_id] = {"covered": True, "evidence": quote}
        else:
            cells[element_id] = _keyword_cell(element, patent)

    _CACHE[key] = cells
    return cells


def build_matrix(elements: list[dict], patents: list[dict]) -> dict[str, Any]:
    """Model-judged counterpart of :func:`coverage.build_matrix` (same shape).

    Each patent that cannot be judged (call failure, unparseable response) is
    scored with the keyword matcher instead, so a partial outage degrades
    gracefully rather than failing the analysis.
    """
    if MODE != "llm":
        return coverage.build_matrix(elements, patents)

    matrix: dict[str, dict[str, dict[str, Any]]] = {
        _element_key(element, index): {} for index, element in enumerate(elements)
    }
    for patent_index, patent in enumerate(patents):
        patent_id = _patent_key(patent, patent_index)
        try:
            cells = judge_patent(elements, patent)
        except Exception:
            cells = {
                _element_key(element, index): _keyword_cell(element, patent)
                for index, element in enumerate(elements)
            }
        for element_id, cell in cells.items():
            matrix[element_id][patent_id] = cell

    uncovered = [
        element_id
        for element_id, per_patent in matrix.items()
        if not any(cell["covered"] for cell in per_patent.values())
    ]
    return {
        "elements": list(elements),
        "patents": list(patents),
        "coverage": matrix,
        "uncovered": uncovered,
    }
