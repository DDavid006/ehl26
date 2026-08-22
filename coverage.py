"""Build an element-by-patent coverage matrix from decomposition and search results.

The comparison is a model judgement: one call per patent asks whether that
patent discloses each element and for the sentence that shows it. Keyword
overlap remains as the offline fallback for when the model cannot be reached.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import agent_log
from llm import generate_text

MAX_PARALLEL_JUDGEMENTS = 8
JUDGE_PROMPT = """You are a patent examiner comparing one prior-art publication \
against the elements of an invention.

Patent:
{patent}

Invention elements:
{elements}

For each element decide whether this patent discloses it. Disclosure means the \
patent's own text describes that function or feature; a shared field or a \
similar-sounding word is not disclosure. Quote the sentence of the patent that \
discloses it as "evidence", verbatim, and use "" when it is not disclosed.

Return JSON only. No prose, no markdown fences:
{{"E1": {{"covered": true, "evidence": "..."}}, "E2": {{"covered": false, "evidence": ""}}}}"""


class JudgementError(ValueError):
    """Raised when the model's coverage judgement cannot be used."""


STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "based",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "the",
        "that",
        "to",
        "with",
        "without",
    }
)

SENTENCE_SPLIT = re.compile(r"(?<=[.;!?])\s+|\n+")
WORD = re.compile(r"[a-z0-9]+")


def _normalize_word(word: str) -> str:
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("es"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def _keywords(text: str) -> list[str]:
    words = [_normalize_word(word) for word in WORD.findall(text.lower())]
    return [word for word in words if word not in STOPWORDS and len(word) > 1]


def _sentences(patent: dict) -> list[str]:
    parts = [patent.get("title") or "", patent.get("abstract") or ""]
    sentences: list[str] = []
    for part in parts:
        for sentence in SENTENCE_SPLIT.split(part):
            sentence = re.sub(r"\s+", " ", sentence).strip()
            if sentence:
                sentences.append(sentence)
    return sentences


def is_covered(element: dict, patent: dict) -> tuple[bool, str]:
    """Return whether ``patent`` covers ``element`` and the sentence evidencing it.

    Matching is keyword overlap: a search term matches a sentence of the patent
    title or abstract when every significant word of the term appears in that
    sentence. The evidence is the first matching sentence, or an empty string
    when there is no match.
    """
    terms = element.get("search_terms") or []
    sentences = _sentences(patent)
    if not sentences:
        return False, ""

    for sentence in sentences:
        sentence_words = set(_keywords(sentence))
        for term in terms:
            if not isinstance(term, str):
                continue
            term_words = _keywords(term)
            if term_words and set(term_words) <= sentence_words:
                return True, sentence
    return False, ""


def _patent_block(patent: dict) -> str:
    return json.dumps(
        {key: patent.get(key) for key in ("patent_id", "title", "abstract", "assignee", "date")},
        indent=2,
        ensure_ascii=False,
    )


def _elements_block(elements: list[dict], keys: list[str]) -> str:
    return json.dumps(
        [{"id": key, "text": element.get("text")} for key, element in zip(keys, elements)],
        indent=2,
        ensure_ascii=False,
    )


def _parse_judgement(answer: str, keys: list[str]) -> dict[str, dict[str, Any]]:
    text = answer.strip()
    fence = re.match(r"^```[A-Za-z0-9_-]*\s*(.*?)\s*```$", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise JudgementError("no JSON object in the coverage judgement")
    try:
        data = json.loads(text[start : end + 1])
    except ValueError as exc:
        raise JudgementError(f"unparsable coverage judgement: {exc}") from exc
    if not isinstance(data, dict):
        raise JudgementError("coverage judgement is not an object")

    verdicts: dict[str, dict[str, Any]] = {}
    for key in keys:
        entry = data.get(key)
        if not isinstance(entry, dict):
            raise JudgementError(f"coverage judgement has no verdict for {key}")
        evidence = entry.get("evidence")
        verdicts[key] = {
            "covered": bool(entry.get("covered")),
            "evidence": evidence.strip() if isinstance(evidence, str) else "",
        }
    return verdicts


def judge_patent(elements: list[dict], keys: list[str], patent: dict) -> dict[str, dict[str, Any]]:
    """Ask the model which of ``elements`` this ``patent`` discloses.

    Falls back to keyword overlap when the model errors or answers unusably, so
    a matrix is always produced.
    """
    prompt = JUDGE_PROMPT.format(
        patent=_patent_block(patent), elements=_elements_block(elements, keys)
    )
    label = f"compare: {patent.get('patent_id') or patent.get('title') or 'patent'}"
    try:
        return _parse_judgement(generate_text(prompt, JudgementError, task=label), keys)
    except Exception as exc:
        agent_log.note(f"{label}: falling back to keyword matching ({exc})")
        verdicts = {}
        for key, element in zip(keys, elements):
            covered, evidence = is_covered(element, patent)
            verdicts[key] = {"covered": covered, "evidence": evidence}
        return verdicts


def _patent_key(patent: dict, index: int) -> str:
    patent_id = patent.get("patent_id")
    if isinstance(patent_id, str) and patent_id.strip():
        return patent_id.strip()
    return f"unknown-{index + 1}"


def _element_key(element: dict, index: int) -> str:
    element_id = element.get("id")
    if isinstance(element_id, str) and element_id.strip():
        return element_id.strip()
    return f"E{index + 1}"


def build_matrix(elements: list[dict], patents: list[dict]) -> dict[str, Any]:
    """Build the coverage matrix for ``elements`` against ``patents``.

    ``uncovered`` lists the ids of elements that no patent covers.
    """
    element_keys = [_element_key(element, index) for index, element in enumerate(elements)]
    patent_keys = [_patent_key(patent, index) for index, patent in enumerate(patents)]

    if elements and patents:
        # The judgements run on pool threads but belong to the caller's
        # transcript, which a worker thread does not inherit.
        run = agent_log.current_run()

        def judge(patent: dict) -> dict[str, dict[str, Any]]:
            with agent_log.using(run):
                return judge_patent(elements, element_keys, patent)

        with ThreadPoolExecutor(max_workers=min(len(patents), MAX_PARALLEL_JUDGEMENTS)) as pool:
            judgements = list(pool.map(judge, patents))
    else:
        judgements = []

    coverage: dict[str, dict[str, dict[str, Any]]] = {}
    uncovered: list[str] = []
    for element_key in element_keys:
        per_patent = {
            patent_key: judgement[element_key]
            for patent_key, judgement in zip(patent_keys, judgements)
        }
        coverage[element_key] = per_patent
        if not any(entry["covered"] for entry in per_patent.values()):
            uncovered.append(element_key)

    return {
        "elements": list(elements),
        "patents": list(patents),
        "coverage": coverage,
        "uncovered": uncovered,
    }
