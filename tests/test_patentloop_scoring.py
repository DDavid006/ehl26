"""Scoring and similarity maths: the parts a judge can recompute by hand."""

from __future__ import annotations

from patentloop.agents.research import ResearchAgent
from patentloop.schemas import ElementSimilarity
from patentloop.textsim import best_cosine, cosine, tokenize


def test_tokenize_drops_patentese_stopwords():
    tokens = tokenize("A method comprising a plurality of lithium garnet electrolyte layers")
    assert "lithium" in tokens and "garnet" in tokens
    assert "comprising" not in tokens and "plurality" not in tokens


def test_cosine_is_high_for_paraphrase_and_low_for_unrelated():
    a = "laser-textured lithium garnet solid electrolyte interface for dendrite suppression"
    b = "dendrite suppression via laser texturing of a lithium garnet solid electrolyte"
    c = "a mobile application reminding users to drink water"
    assert cosine(a, b) > 0.5
    assert cosine(a, c) < 0.1


def test_best_cosine_picks_closest_candidate():
    assert best_cosine("garnet electrolyte", ["unrelated cooking recipe", "garnet electrolyte film"]) > 0.4


def _score(llm, lexical):
    return ElementSimilarity(
        element="e", llm_similarity=llm, lexical_similarity=lexical,
        similarity=round(0.6 * llm + 0.4 * lexical * 100, 2),
    )


def test_novelty_score_penalises_the_worst_element_most():
    crowded = ResearchAgent._novelty_score([_score(95, 0.8), _score(10, 0.1)])
    fresh = ResearchAgent._novelty_score([_score(10, 0.1), _score(5, 0.05)])
    assert crowded < 40
    assert fresh > 80


def test_novelty_score_is_zero_without_elements():
    assert ResearchAgent._novelty_score([]) == 0.0
