"""Generate patentability suggestions from a coverage matrix using Gemini."""

from __future__ import annotations

import json
from typing import Any

from dotenv import load_dotenv

from decompose import extract_json_array, extract_json_object, generate_text, strip_fences

load_dotenv()

MIN_SUGGESTIONS = 2
MAX_SUGGESTIONS = 3
SUGGESTION_KEYS = ("title", "reasoning", "element_id", "reference")
REVISION_KEYS = ("description", "changes")

REVISION_PROMPT_TEMPLATE = """You are a patent attorney rewriting an invention so it can be \
allowed over the prior art found for it.

Current invention description:
{description}

Element decomposition and coverage matrix (JSON). "uncovered" lists element ids that no prior \
art reference covers; each coverage cell holds the sentence of the reference that matched:
{matrix}

The examiner rejected this invention:
{verdict}

Suggestions raised against it:
{suggestions}

Task: write a REVISED invention description that designs around the blocking references.
- Keep the same core purpose and product; this is a revision, not a different invention.
- Fold the suggestions in as concrete technical limitations: numeric parameter ranges with \
units, specific materials, sequences, or claim category shifts. No vague language.
- Do not claim anything a cited reference already discloses.
- Write the description as flowing prose in one paragraph, the same register as the input.
- Summarise in "changes" what you changed and which reference each change avoids, naming the \
reference ids.

Return JSON only. No prose, no explanation, no markdown code fences. A single JSON object with \
exactly these keys:
{{"description": "...", "changes": "..."}}"""

PROMPT_TEMPLATE = """You are a patent attorney assessing patentability over the prior art below.

Invention description:
{description}

Element decomposition and coverage matrix (JSON). "uncovered" lists element ids that no prior \
art reference covers; each coverage cell holds the sentence of the reference that matched:
{matrix}

Task: produce between {min_suggestions} and {max_suggestions} concrete suggestions for making \
this invention more likely to be patentable.

For each suggestion:
- First assess whether the uncovered elements are technically meaningful points of novelty or \
merely trivial (a labelling, packaging, or wording difference). Say which, and why.
- Propose a specific modification: a narrower parameter range (give concrete numbers or units), \
a different claim category (composition vs method vs system vs use), or an attack on a \
limitation that the prior art itself acknowledges (quote or paraphrase the acknowledged \
limitation).
- Ground the suggestion in exactly one element id from the matrix ("element_id") and one \
patent reference id from the matrix ("reference").
- Be specific. Vague advice such as "add more detail" or "consider narrowing the claims" is \
useless; specificity is the entire point.

Allowed element ids: {element_ids}
Allowed patent references: {patent_ids}

Return JSON only. No prose, no explanation, no markdown code fences. A JSON array of objects \
with exactly these keys:
[{{"title": "...", "reasoning": "...", "element_id": "E3", "reference": "US1234567"}}]"""


class SuggestionError(ValueError):
    """Raised when the model response cannot be parsed into suggestions."""


def _matrix_ids(matrix: dict) -> tuple[list[str], list[str]]:
    coverage = matrix.get("coverage") or {}
    element_ids = [key for key in coverage if isinstance(key, str)]
    for element in matrix.get("elements") or []:
        element_id = (element or {}).get("id") if isinstance(element, dict) else None
        if isinstance(element_id, str) and element_id not in element_ids:
            element_ids.append(element_id)

    patent_ids: list[str] = []
    for per_patent in coverage.values():
        if isinstance(per_patent, dict):
            for patent_id in per_patent:
                if isinstance(patent_id, str) and patent_id not in patent_ids:
                    patent_ids.append(patent_id)
    for patent in matrix.get("patents") or []:
        patent_id = (patent or {}).get("patent_id") if isinstance(patent, dict) else None
        if isinstance(patent_id, str) and patent_id not in patent_ids:
            patent_ids.append(patent_id)
    return element_ids, patent_ids


def _coerce_suggestion(
    raw: Any, index: int, element_ids: list[str], patent_ids: list[str]
) -> dict:
    if not isinstance(raw, dict):
        raise SuggestionError(f"suggestion {index} is not an object")
    values: dict[str, str] = {}
    for key in SUGGESTION_KEYS:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SuggestionError(f"suggestion {index} has no {key}")
        values[key] = value.strip()
    if element_ids and values["element_id"] not in element_ids:
        raise SuggestionError(
            f"suggestion {index} references unknown element {values['element_id']!r}"
        )
    if patent_ids and values["reference"] not in patent_ids:
        raise SuggestionError(
            f"suggestion {index} references unknown patent {values['reference']!r}"
        )
    return {key: values[key] for key in SUGGESTION_KEYS}


def _parse_response(text: str, element_ids: list[str], patent_ids: list[str]) -> list[dict]:
    if not isinstance(text, str) or not text.strip():
        raise SuggestionError("empty model response")
    try:
        payload = extract_json_array(strip_fences(text))
    except ValueError as exc:
        raise SuggestionError(str(exc)) from exc
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise SuggestionError(f"invalid JSON in model response: {exc}") from exc
    if not isinstance(data, list):
        raise SuggestionError("model response is not a JSON array")
    suggestions = [
        _coerce_suggestion(raw, index, element_ids, patent_ids)
        for index, raw in enumerate(data)
    ]
    if not MIN_SUGGESTIONS <= len(suggestions) <= MAX_SUGGESTIONS:
        raise SuggestionError(
            f"expected {MIN_SUGGESTIONS}-{MAX_SUGGESTIONS} suggestions, got {len(suggestions)}"
        )
    return suggestions


def _generate(matrix: dict, description: str, element_ids: list[str], patent_ids: list[str]) -> str:
    return generate_text(
        PROMPT_TEMPLATE.format(
            description=description.strip(),
            matrix=json.dumps(matrix, default=str, separators=(",", ":")),
            min_suggestions=MIN_SUGGESTIONS,
            max_suggestions=MAX_SUGGESTIONS,
            element_ids=", ".join(element_ids) or "none",
            patent_ids=", ".join(patent_ids) or "none",
        ),
        SuggestionError,
        task="suggest",
    )


def generate_suggestions(matrix: dict, description: str) -> list[dict]:
    """Return 2-3 grounded patentability suggestions for ``matrix``.

    Retries once if the model response cannot be parsed, then raises
    :class:`SuggestionError`.
    """
    if not isinstance(matrix, dict) or not matrix:
        raise SuggestionError("matrix must be a non-empty dict")
    if not description or not description.strip():
        raise SuggestionError("description must not be empty")

    element_ids, patent_ids = _matrix_ids(matrix)
    last_error: SuggestionError | None = None
    for _ in range(2):
        try:
            return _parse_response(
                _generate(matrix, description, element_ids, patent_ids),
                element_ids,
                patent_ids,
            )
        except SuggestionError as exc:
            last_error = exc
    raise last_error if last_error else SuggestionError("suggestion generation failed")


def _parse_revision(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise SuggestionError("empty model response")
    try:
        payload = extract_json_object(strip_fences(text))
    except ValueError as exc:
        raise SuggestionError(str(exc)) from exc
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise SuggestionError(f"invalid JSON in model response: {exc}") from exc
    if not isinstance(data, dict):
        raise SuggestionError("model response is not a JSON object")
    values: dict[str, str] = {}
    for key in REVISION_KEYS:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SuggestionError(f"revision has no {key}")
        values[key] = value.strip()
    return values


def generate_revision(matrix: dict, description: str, verdict: dict, suggestions: list[dict]) -> dict:
    """Rewrite ``description`` to design around the art in ``matrix``.

    Returns ``{"description": str, "changes": str}``. Retries once if the model
    response cannot be parsed, then raises :class:`SuggestionError`.
    """
    if not isinstance(matrix, dict) or not matrix:
        raise SuggestionError("matrix must be a non-empty dict")
    if not description or not description.strip():
        raise SuggestionError("description must not be empty")

    prompt = REVISION_PROMPT_TEMPLATE.format(
        description=description.strip(),
        matrix=json.dumps(matrix, default=str, separators=(",", ":")),
        verdict=json.dumps(verdict, default=str, separators=(",", ":")),
        suggestions=json.dumps(suggestions, default=str, separators=(",", ":")),
    )
    last_error: SuggestionError | None = None
    for _ in range(2):
        try:
            return _parse_revision(generate_text(prompt, SuggestionError, task="revise"))
        except SuggestionError as exc:
            last_error = exc
    raise last_error if last_error else SuggestionError("revision generation failed")
