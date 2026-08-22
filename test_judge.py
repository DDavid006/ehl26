import json

import pytest

import judge
from judge import CoverageJudgeError, build_matrix, judge_patent

ELEMENTS = [
    {"id": "E1", "text": "a delivery format applied without rinsing", "search_terms": ["leave-on formulation", "rinse free"]},
    {"id": "E2", "text": "an agent that attenuates ultraviolet radiation", "search_terms": ["ultraviolet filter", "sunscreen active"]},
]

PATENT = {
    "patent_id": "US1111111",
    "title": "Non-rinse photoprotective mousse",
    "abstract": "An aerated product that remains on the head after use. The mousse carries a UV-absorbing compound.",
}


@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    monkeypatch.setattr(judge, "_CACHE", {})
    monkeypatch.setattr(judge, "MODE", "llm")


def install_model(monkeypatch, responses):
    calls = []

    def fake_generate(prompt, error_cls):
        calls.append(prompt)
        response = responses[min(len(calls), len(responses)) - 1]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(judge, "generate_text", fake_generate)
    return calls


def _response(cells):
    return json.dumps([{"id": key, **value} for key, value in cells.items()])


def test_judge_patent_uses_verbatim_quotes_as_evidence(monkeypatch):
    install_model(
        monkeypatch,
        [
            _response(
                {
                    "E1": {"covered": True, "quote": "remains on the head after use"},
                    "E2": {"covered": False, "quote": ""},
                }
            )
        ],
    )

    cells = judge_patent(ELEMENTS, PATENT)

    assert cells["E1"] == {"covered": True, "evidence": "remains on the head after use"}
    assert cells["E2"] == {"covered": False, "evidence": ""}


def test_quote_matching_ignores_case_and_whitespace(monkeypatch):
    install_model(
        monkeypatch,
        [
            _response(
                {
                    "E1": {"covered": True, "quote": "Remains  on the\nhead after use"},
                    "E2": {"covered": False, "quote": ""},
                }
            )
        ],
    )

    assert judge_patent(ELEMENTS, PATENT)["E1"]["covered"] is True


def test_unverifiable_quote_falls_back_to_keyword_cell(monkeypatch):
    install_model(
        monkeypatch,
        [
            _response(
                {
                    "E1": {"covered": True, "quote": "a sentence that is not in the reference"},
                    "E2": {"covered": True, "quote": "carries a UV-absorbing compound"},
                }
            )
        ],
    )
    monkeypatch.setattr(judge.coverage, "is_covered", lambda element, patent: (False, ""))

    cells = judge_patent(ELEMENTS, PATENT)

    assert cells["E1"] == {"covered": False, "evidence": ""}
    assert cells["E2"] == {"covered": True, "evidence": "carries a UV-absorbing compound"}


def test_results_are_cached_per_elements_patent_pair(monkeypatch):
    calls = install_model(
        monkeypatch,
        [_response({"E1": {"covered": False, "quote": ""}, "E2": {"covered": False, "quote": ""}})],
    )

    first = judge_patent(ELEMENTS, PATENT)
    second = judge_patent(ELEMENTS, PATENT)

    assert first == second
    assert len(calls) == 1


def test_missing_elements_in_response_raise(monkeypatch):
    install_model(monkeypatch, [_response({"E1": {"covered": False, "quote": ""}})])

    with pytest.raises(CoverageJudgeError):
        judge_patent(ELEMENTS, PATENT)


def test_unparseable_response_raises(monkeypatch):
    install_model(monkeypatch, ["not json at all"])

    with pytest.raises(CoverageJudgeError):
        judge_patent(ELEMENTS, PATENT)


def test_build_matrix_matches_keyword_matrix_shape(monkeypatch):
    install_model(
        monkeypatch,
        [
            _response(
                {
                    "E1": {"covered": True, "quote": "remains on the head after use"},
                    "E2": {"covered": False, "quote": ""},
                }
            )
        ],
    )

    matrix = build_matrix(ELEMENTS, [PATENT])

    assert sorted(matrix) == ["coverage", "elements", "patents", "uncovered"]
    assert matrix["coverage"]["E1"]["US1111111"]["covered"] is True
    assert matrix["uncovered"] == ["E2"]


def test_failed_call_falls_back_to_keyword_matching_for_that_patent(monkeypatch):
    install_model(monkeypatch, [RuntimeError("boom")])
    monkeypatch.setattr(judge.coverage, "is_covered", lambda element, patent: (True, "stub"))

    matrix = build_matrix(ELEMENTS, [PATENT])

    assert matrix["coverage"]["E1"]["US1111111"] == {"covered": True, "evidence": "stub"}
    assert matrix["uncovered"] == []


def test_keyword_mode_delegates_to_coverage_module(monkeypatch):
    monkeypatch.setattr(judge, "MODE", "keyword")
    calls = install_model(monkeypatch, ["should not be called"])

    matrix = build_matrix(ELEMENTS, [PATENT])

    assert calls == []
    assert sorted(matrix) == ["coverage", "elements", "patents", "uncovered"]


def test_empty_patents_yield_all_uncovered(monkeypatch):
    calls = install_model(monkeypatch, ["should not be called"])

    matrix = build_matrix(ELEMENTS, [])

    assert calls == []
    assert matrix["uncovered"] == ["E1", "E2"]
    assert matrix["coverage"] == {"E1": {}, "E2": {}}
