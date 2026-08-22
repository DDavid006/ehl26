"""Build an element-by-patent coverage matrix from decomposition and search results."""

from __future__ import annotations

import re
from typing import Any

SENTENCE_SPLIT = re.compile(r"(?<=[.;!?])\s+|\n+")
WORD = re.compile(r"[a-z0-9]+")
SUFFIXES = ("ization", "isation", "ations", "ation", "ings", "ing", "ers", "er", "ors", "or", "ion", "es", "ed", "s")
GENERIC = frozenset(
    {
        "a", "an", "and", "the", "of", "for", "with", "in", "on", "to", "by", "based", "using",
        "system", "systems", "device", "devices", "apparatus", "method", "methods", "assembly",
        "unit", "units", "module", "modules",
    }
)


def _stem(word: str) -> str:
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _stems(text: str) -> list[str]:
    return [_stem(word) for word in WORD.findall(text.lower())]


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

    A patent covers the element when any one of its search terms is present in
    the title or abstract. Matching is case-insensitive, order-independent and
    partial: words count as equal once reduced to their stem, so "temperature
    sensor" matches "temperature sensing" and "load cell" matches "load cells",
    and filler words like "system" or "device" are ignored. The evidence is the
    first matching sentence, or an empty string when there is no match.
    """
    terms = [
        [stem for stem in _stems(term) if stem not in GENERIC]
        for term in element.get("search_terms") or []
        if isinstance(term, str)
    ]
    terms = [term for term in terms if term]

    for sentence in _sentences(patent):
        words = set(_stems(sentence))
        for term in terms:
            if set(term) <= words:
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
