"""Examiner verdict on whether an invention is patentable over the coverage matrix."""

from __future__ import annotations

import json

from dotenv import load_dotenv

from decompose import extract_json_object, generate_text, strip_fences

load_dotenv()

VERDICT_KEYS = ("patentable", "reasoning")

PROMPT_TEMPLATE = """You are a patent examiner deciding whether to allow or reject the \
invention below over the prior art found for it.

Invention description:
{description}

Element decomposition and coverage matrix (JSON). "uncovered" lists element ids that no prior \
art reference covers; each coverage cell holds the sentence of the reference that matched:
{matrix}

Decide whether this invention, as described, is patentable over this prior art:
- The matrix is keyword matching, not a search report. An uncovered element is only a gap if it \
is genuinely unusual in this field; if it is standard subject matter that any practitioner would \
expect to be disclosed somewhere, treat it as covered even though no cell matched.
- An element left uncovered only counts towards novelty if it is a technically meaningful \
difference, not a labelling, packaging, or wording difference, and not the mere presence of an \
ordinary component.
- Also apply obviousness: if the description is a combination of features each shown in the \
references, or lacks any concrete limitation (a parameter range, a material, a structural or \
sequence constraint) beyond what the references disclose, the invention is not patentable.
- If every element is covered, or the uncovered ones are trivial or an obvious combination of \
the references, return false.
- Name the element ids and patent reference ids that drive your decision in the reasoning.
- Be strict, like a first-action rejection. Most descriptions at this stage are not patentable; \
a hopeful verdict is worse than a blocking one.

Return JSON only. No prose, no explanation, no markdown code fences. A single JSON object with \
exactly these keys:
{{"patentable": true, "reasoning": "..."}}"""


class ExaminationError(ValueError):
    """Raised when the model response cannot be parsed into a verdict."""


def _parse_response(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ExaminationError("empty model response")
    try:
        payload = extract_json_object(strip_fences(text))
    except ValueError as exc:
        raise ExaminationError(str(exc)) from exc
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise ExaminationError(f"invalid JSON in model response: {exc}") from exc
    if not isinstance(data, dict):
        raise ExaminationError("model response is not a JSON object")

    patentable = data.get("patentable")
    if not isinstance(patentable, bool):
        raise ExaminationError("verdict has no boolean 'patentable'")
    reasoning = data.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise ExaminationError("verdict has no reasoning")
    return {"patentable": patentable, "reasoning": reasoning.strip()}


def judge_patentability(matrix: dict, description: str) -> dict:
    """Return ``{"patentable": bool, "reasoning": str}`` for ``description`` over ``matrix``.

    Retries once if the model response cannot be parsed, then raises
    :class:`ExaminationError`.
    """
    if not isinstance(matrix, dict) or not matrix:
        raise ExaminationError("matrix must be a non-empty dict")
    if not description or not description.strip():
        raise ExaminationError("description must not be empty")

    prompt = PROMPT_TEMPLATE.format(
        description=description.strip(),
        matrix=json.dumps(matrix, default=str, separators=(",", ":")),
    )
    last_error: ExaminationError | None = None
    for _ in range(2):
        try:
            return _parse_response(generate_text(prompt, ExaminationError, task="examine"))
        except ExaminationError as exc:
            last_error = exc
    raise last_error if last_error else ExaminationError("examination failed")
