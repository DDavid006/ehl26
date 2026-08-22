"""Build an element-by-patent coverage matrix from decomposition and search results."""

from __future__ import annotations

import re
from typing import Any

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
    coverage: dict[str, dict[str, dict[str, Any]]] = {}
    uncovered: list[str] = []

    for element_index, element in enumerate(elements):
        element_id = _element_key(element, element_index)
        per_patent: dict[str, dict[str, Any]] = {}
        for patent_index, patent in enumerate(patents):
            covered, evidence = is_covered(element, patent)
            per_patent[_patent_key(patent, patent_index)] = {
                "covered": covered,
                "evidence": evidence,
            }
        coverage[element_id] = per_patent
        if not any(entry["covered"] for entry in per_patent.values()):
            uncovered.append(element_id)

    return {
        "elements": list(elements),
        "patents": list(patents),
        "coverage": coverage,
        "uncovered": uncovered,
    }
