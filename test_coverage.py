import json

import pytest

import coverage
from coverage import build_matrix, is_covered


@pytest.fixture(autouse=True)
def offline_model(monkeypatch):
    """Keyword matching is the fallback, so most tests run with no model."""

    def unavailable(prompt, error_cls, task="generate"):
        raise error_cls("model offline")

    monkeypatch.setattr(coverage, "generate_text", unavailable)


def install_judge(monkeypatch, answer):
    prompts = []

    def judge(prompt, error_cls, task="generate"):
        prompts.append({"prompt": prompt, "task": task})
        return answer(prompt) if callable(answer) else answer

    monkeypatch.setattr(coverage, "generate_text", judge)
    return prompts


ELEMENTS = [
    {
        "id": "E1",
        "text": "a delivery format applied without rinsing",
        "search_terms": ["leave-on formulation", "rinse free composition"],
    },
    {
        "id": "E2",
        "text": "an agent that attenuates ultraviolet radiation at the scalp",
        "search_terms": ["ultraviolet filter", "sunscreen active"],
    },
    {
        "id": "E3",
        "text": "a carrier that spreads through dense hair to reach the skin",
        "search_terms": ["scalp delivery vehicle", "hair penetrating carrier"],
    },
    {
        "id": "E4",
        "text": "a dispenser that meters a fixed dose per application",
        "search_terms": ["metered dose dispenser", "dosing pump"],
    },
]

PATENTS = [
    {
        "patent_id": "US1234567",
        "title": "Leave-on formulation for scalp care",
        "abstract": (
            "A composition comprising an ultraviolet filter suspended in a foam. "
            "The foam is a scalp delivery vehicle that spreads between hair fibers."
        ),
        "assignee": "Acme Labs",
        "date": "2020-01-01",
    },
    {
        "patent_id": "US7654321",
        "title": "Sunscreen active for topical use",
        "abstract": "A sunscreen active dispersed in an aqueous carrier.",
        "assignee": None,
        "date": None,
    },
]


def test_matrix_shape_and_keys():
    matrix = build_matrix(ELEMENTS, PATENTS)

    assert sorted(matrix) == ["coverage", "elements", "patents", "uncovered"]
    assert matrix["elements"] == ELEMENTS
    assert matrix["patents"] == PATENTS
    assert sorted(matrix["coverage"]) == ["E1", "E2", "E3", "E4"]
    for per_patent in matrix["coverage"].values():
        assert sorted(per_patent) == ["US1234567", "US7654321"]
        for cell in per_patent.values():
            assert sorted(cell) == ["covered", "evidence"]
            assert isinstance(cell["covered"], bool)
            assert isinstance(cell["evidence"], str)


def test_covered_cells_carry_matching_sentence_as_evidence():
    matrix = build_matrix(ELEMENTS, PATENTS)

    cell = matrix["coverage"]["E1"]["US1234567"]
    assert cell["covered"] is True
    assert cell["evidence"] == "Leave-on formulation for scalp care"

    cell = matrix["coverage"]["E2"]["US1234567"]
    assert cell["covered"] is True
    assert "ultraviolet filter" in cell["evidence"]

    cell = matrix["coverage"]["E3"]["US1234567"]
    assert cell["covered"] is True
    assert cell["evidence"].startswith("The foam is a scalp delivery vehicle")


def test_uncovered_lists_elements_no_patent_covers():
    matrix = build_matrix(ELEMENTS, PATENTS)

    assert matrix["uncovered"] == ["E4"]
    assert all(
        cell["covered"] is False and cell["evidence"] == ""
        for cell in matrix["coverage"]["E4"].values()
    )


def test_all_elements_uncovered_without_patents():
    matrix = build_matrix(ELEMENTS, [])

    assert matrix["uncovered"] == ["E1", "E2", "E3", "E4"]
    assert matrix["coverage"]["E1"] == {}


def test_empty_elements_yield_empty_coverage():
    matrix = build_matrix([], PATENTS)

    assert matrix["coverage"] == {}
    assert matrix["uncovered"] == []


def test_matching_ignores_case_punctuation_and_plurals():
    element = {"id": "E1", "search_terms": ["aerated carrier matrix"]}
    patent = {
        "patent_id": "US1",
        "title": "Aerated Carriers: Matrix for topical delivery",
        "abstract": None,
    }

    covered, evidence = is_covered(element, patent)

    assert covered is True
    assert evidence == "Aerated Carriers: Matrix for topical delivery"


def test_partial_term_overlap_is_not_a_match():
    element = {"id": "E1", "search_terms": ["metered dose dispenser"]}
    patent = {
        "patent_id": "US1",
        "title": "Dispenser for liquids",
        "abstract": "A dispenser that releases a dose of liquid.",
    }

    assert is_covered(element, patent) == (False, "")


def test_missing_fields_are_tolerated():
    assert is_covered({"id": "E1"}, PATENTS[0]) == (False, "")
    assert is_covered(ELEMENTS[0], {"patent_id": "US1"}) == (False, "")
    assert is_covered(
        {"id": "E1", "search_terms": [None, 42, "sunscreen active"]}, PATENTS[1]
    )[0] is True


def test_stopword_only_terms_do_not_match_everything():
    element = {"id": "E1", "search_terms": ["of the", "with"]}

    assert is_covered(element, PATENTS[0]) == (False, "")


def test_patents_without_id_get_stable_placeholder_keys():
    patents = [
        {"patent_id": None, "title": "Sunscreen active composition", "abstract": None},
        {"title": "Unrelated widget", "abstract": None},
    ]

    matrix = build_matrix([ELEMENTS[1]], patents)

    assert sorted(matrix["coverage"]["E2"]) == ["unknown-1", "unknown-2"]
    assert matrix["coverage"]["E2"]["unknown-1"]["covered"] is True
    assert matrix["uncovered"] == []


def test_elements_without_id_get_positional_keys():
    matrix = build_matrix([{"search_terms": ["sunscreen active"]}], PATENTS)

    assert list(matrix["coverage"]) == ["E1"]
    assert matrix["coverage"]["E1"]["US7654321"]["covered"] is True


def test_is_covered_is_swappable(monkeypatch):
    monkeypatch.setattr(coverage, "is_covered", lambda element, patent: (True, "stub"))

    matrix = build_matrix(ELEMENTS, PATENTS)

    assert matrix["uncovered"] == []
    assert matrix["coverage"]["E4"]["US1234567"] == {"covered": True, "evidence": "stub"}


def test_the_model_decides_coverage_when_it_is_reachable(monkeypatch):
    verdicts = {
        "E1": {"covered": True, "evidence": "A composition comprising an ultraviolet filter."},
        "E2": {"covered": False, "evidence": ""},
        "E3": {"covered": False, "evidence": ""},
        "E4": {"covered": False, "evidence": ""},
    }
    prompts = install_judge(monkeypatch, json.dumps(verdicts))

    matrix = build_matrix(ELEMENTS, PATENTS)

    # One judgement per patent, not per cell, and each names the patent it judged.
    assert len(prompts) == len(PATENTS)
    assert {call["task"] for call in prompts} == {"compare: US1234567", "compare: US7654321"}
    assert "a delivery format applied without rinsing" in prompts[0]["prompt"]
    assert matrix["coverage"]["E1"]["US1234567"] == verdicts["E1"]
    # E2 is a keyword match the model rejected, so its judgement is what counts.
    assert matrix["coverage"]["E2"]["US1234567"] == {"covered": False, "evidence": ""}
    assert matrix["uncovered"] == ["E2", "E3", "E4"]


def test_a_fenced_or_chatty_judgement_is_still_read(monkeypatch):
    install_judge(
        monkeypatch,
        '```json\n{"E1": {"covered": true, "evidence": " spaced "}}\n```',
    )

    matrix = build_matrix([ELEMENTS[0]], [PATENTS[0]])

    assert matrix["coverage"]["E1"]["US1234567"] == {"covered": True, "evidence": "spaced"}


@pytest.mark.parametrize(
    "answer",
    ["not json at all", "{}", '{"E1": "covered"}', '{"E9": {"covered": true}}'],
)
def test_an_unusable_judgement_falls_back_to_keyword_matching(monkeypatch, answer):
    install_judge(monkeypatch, answer)

    matrix = build_matrix(ELEMENTS, PATENTS)

    assert matrix["coverage"]["E1"]["US1234567"]["covered"] is True
    assert matrix["uncovered"] == ["E4"]


def test_inputs_are_not_mutated():
    elements = [dict(element) for element in ELEMENTS]
    patents = [dict(patent) for patent in PATENTS]

    build_matrix(elements, patents)

    assert elements == ELEMENTS
    assert patents == PATENTS
