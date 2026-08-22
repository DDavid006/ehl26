import json

import pytest

import decompose
import llm
import suggest
from suggest import SuggestionError, generate_revision, generate_suggestions


DESCRIPTION = "A leave-on foam that delivers sunscreen to the scalp through dense hair."

MATRIX = {
    "elements": [
        {"id": "E1", "text": "a leave-on delivery format", "search_terms": ["leave-on"]},
        {"id": "E2", "text": "an ultraviolet attenuating agent", "search_terms": ["uv filter"]},
        {"id": "E3", "text": "a metered dose applicator", "search_terms": ["metered dose"]},
    ],
    "patents": [
        {
            "patent_id": "US1234567",
            "title": "Leave-on scalp composition",
            "abstract": "A foam comprising an ultraviolet filter.",
            "assignee": "Acme Labs",
            "date": "2020-01-01",
        }
    ],
    "coverage": {
        "E1": {"US1234567": {"covered": True, "evidence": "Leave-on scalp composition"}},
        "E2": {
            "US1234567": {"covered": True, "evidence": "A foam comprising an ultraviolet filter."}
        },
        "E3": {"US1234567": {"covered": False, "evidence": ""}},
    },
    "uncovered": ["E3"],
}

VALID_SUGGESTIONS = [
    {
        "title": "Claim the metered applicator as a system with a 0.5-1.0 mL per actuation dose",
        "reasoning": (
            "E3 is unmatched in US1234567, which discloses a foam but no dosing control. "
            "A system claim reciting a 0.5-1.0 mL metered actuation is a meaningful "
            "structural limitation rather than a labelling difference."
        ),
        "element_id": "E3",
        "reference": "US1234567",
    },
    {
        "title": "Recast E1 as a method of use to avoid the composition overlap",
        "reasoning": (
            "US1234567 anticipates the leave-on composition itself, so a method-of-use "
            "claim reciting application through hair at a stated part spacing shifts the "
            "point of novelty away from the anticipated composition."
        ),
        "element_id": "E1",
        "reference": "US1234567",
    },
]


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []

    def generate_content(self, prompt, request_options=None):
        self.prompts.append(prompt)
        self.request_options = request_options
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm, "PROVIDER", "gemini")
    monkeypatch.setattr(llm.genai, "configure", lambda **kwargs: None)


def install_model(monkeypatch, *responses):
    model = FakeModel(responses)
    monkeypatch.setattr(llm.genai, "GenerativeModel", lambda name: model)
    return model


def test_parses_valid_response_and_prompt_contents(monkeypatch):
    model = install_model(monkeypatch, json.dumps(VALID_SUGGESTIONS))

    suggestions = generate_suggestions(MATRIX, DESCRIPTION)

    assert suggestions == VALID_SUGGESTIONS
    prompt = model.prompts[0]
    assert DESCRIPTION in prompt
    assert '"uncovered"' in prompt
    assert "E3" in prompt and "US1234567" in prompt
    assert "JSON only" in prompt
    for instruction in ("narrower parameter range", "claim category", "trivial"):
        assert instruction in prompt


def test_strips_markdown_fences(monkeypatch):
    install_model(monkeypatch, "```json\n" + json.dumps(VALID_SUGGESTIONS) + "\n```")

    assert generate_suggestions(MATRIX, DESCRIPTION) == VALID_SUGGESTIONS


def test_ignores_surrounding_prose(monkeypatch):
    install_model(monkeypatch, "Here you go:\n" + json.dumps(VALID_SUGGESTIONS) + "\nGood luck!")

    assert generate_suggestions(MATRIX, DESCRIPTION) == VALID_SUGGESTIONS


def test_retries_once_then_succeeds(monkeypatch):
    model = install_model(monkeypatch, "sorry, no JSON", json.dumps(VALID_SUGGESTIONS))

    assert generate_suggestions(MATRIX, DESCRIPTION) == VALID_SUGGESTIONS
    assert len(model.prompts) == 2


def test_raises_after_second_failure(monkeypatch):
    model = install_model(monkeypatch, "not json", "still not json")

    with pytest.raises(SuggestionError):
        generate_suggestions(MATRIX, DESCRIPTION)
    assert len(model.prompts) == 2


def test_rejects_too_few_suggestions(monkeypatch):
    payload = json.dumps(VALID_SUGGESTIONS[:1])
    install_model(monkeypatch, payload, payload)

    with pytest.raises(SuggestionError, match="2-3 suggestions"):
        generate_suggestions(MATRIX, DESCRIPTION)


def test_rejects_too_many_suggestions(monkeypatch):
    payload = json.dumps(VALID_SUGGESTIONS * 2)
    install_model(monkeypatch, payload, payload)

    with pytest.raises(SuggestionError, match="2-3 suggestions"):
        generate_suggestions(MATRIX, DESCRIPTION)


def test_rejects_missing_keys(monkeypatch):
    bad = [dict(item) for item in VALID_SUGGESTIONS]
    del bad[0]["reasoning"]
    payload = json.dumps(bad)
    install_model(monkeypatch, payload, payload)

    with pytest.raises(SuggestionError, match="no reasoning"):
        generate_suggestions(MATRIX, DESCRIPTION)


def test_rejects_unknown_element_id(monkeypatch):
    bad = [dict(item) for item in VALID_SUGGESTIONS]
    bad[0]["element_id"] = "E9"
    payload = json.dumps(bad)
    install_model(monkeypatch, payload, payload)

    with pytest.raises(SuggestionError, match="unknown element"):
        generate_suggestions(MATRIX, DESCRIPTION)


def test_rejects_unknown_patent_reference(monkeypatch):
    bad = [dict(item) for item in VALID_SUGGESTIONS]
    bad[1]["reference"] = "US0000000"
    payload = json.dumps(bad)
    install_model(monkeypatch, payload, payload)

    with pytest.raises(SuggestionError, match="unknown patent"):
        generate_suggestions(MATRIX, DESCRIPTION)


def test_drops_extra_keys_and_trims_whitespace(monkeypatch):
    raw = [dict(item) for item in VALID_SUGGESTIONS]
    raw[0] = dict(raw[0], title="  padded title  ", confidence=0.9)
    install_model(monkeypatch, json.dumps(raw))

    suggestions = generate_suggestions(MATRIX, DESCRIPTION)

    assert suggestions[0]["title"] == "padded title"
    assert sorted(suggestions[0]) == sorted(suggest.SUGGESTION_KEYS)


def test_matrix_without_coverage_still_allows_ids_from_lists(monkeypatch):
    matrix = {"elements": MATRIX["elements"], "patents": MATRIX["patents"], "uncovered": ["E3"]}
    install_model(monkeypatch, json.dumps(VALID_SUGGESTIONS))

    assert generate_suggestions(matrix, DESCRIPTION) == VALID_SUGGESTIONS


def test_empty_inputs_raise_without_calling_model(monkeypatch):
    model = install_model(monkeypatch)

    with pytest.raises(SuggestionError):
        generate_suggestions({}, DESCRIPTION)
    with pytest.raises(SuggestionError):
        generate_suggestions(MATRIX, "  ")
    assert model.prompts == []


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    install_model(monkeypatch)

    with pytest.raises(SuggestionError, match="GEMINI_API_KEY"):
        generate_suggestions(MATRIX, DESCRIPTION)


VERDICT = {"patentable": False, "reasoning": "E1 and E2 are anticipated by US1234567."}

VALID_REVISION = {
    "description": (
        "A leave-on scalp foam whose 0.5-1.0 mL metered actuator dispenses through a "
        "comb-tipped nozzle at a 3-5 mm part spacing."
    ),
    "changes": "Added the metered actuation range and comb nozzle to avoid US1234567.",
}


def test_revision_parses_response_and_prompt_contents(monkeypatch):
    model = install_model(monkeypatch, json.dumps(VALID_REVISION))

    revision = generate_revision(MATRIX, DESCRIPTION, VERDICT, VALID_SUGGESTIONS)

    assert revision == VALID_REVISION
    prompt = model.prompts[0]
    assert DESCRIPTION in prompt
    assert "US1234567" in prompt
    assert VERDICT["reasoning"] in prompt
    assert "JSON only" in prompt


def test_revision_strips_fences_and_prose(monkeypatch):
    install_model(monkeypatch, "Sure:\n```json\n" + json.dumps(VALID_REVISION) + "\n```\n")

    assert generate_revision(MATRIX, DESCRIPTION, VERDICT, VALID_SUGGESTIONS) == VALID_REVISION


def test_revision_retries_once_then_succeeds(monkeypatch):
    model = install_model(monkeypatch, "no json here", json.dumps(VALID_REVISION))

    assert generate_revision(MATRIX, DESCRIPTION, VERDICT, VALID_SUGGESTIONS) == VALID_REVISION
    assert len(model.prompts) == 2


def test_revision_raises_after_second_failure(monkeypatch):
    model = install_model(monkeypatch, "not json", "still not json")

    with pytest.raises(SuggestionError):
        generate_revision(MATRIX, DESCRIPTION, VERDICT, VALID_SUGGESTIONS)
    assert len(model.prompts) == 2


def test_revision_rejects_missing_keys(monkeypatch):
    payload = json.dumps({"description": VALID_REVISION["description"]})
    install_model(monkeypatch, payload, payload)

    with pytest.raises(SuggestionError, match="no changes"):
        generate_revision(MATRIX, DESCRIPTION, VERDICT, VALID_SUGGESTIONS)


def test_revision_drops_extra_keys_and_trims(monkeypatch):
    raw = dict(VALID_REVISION, description="  padded  ", confidence=0.4)
    install_model(monkeypatch, json.dumps(raw))

    revision = generate_revision(MATRIX, DESCRIPTION, VERDICT, VALID_SUGGESTIONS)

    assert revision["description"] == "padded"
    assert sorted(revision) == sorted(suggest.REVISION_KEYS)


def test_revision_empty_inputs_raise_without_calling_model(monkeypatch):
    model = install_model(monkeypatch)

    with pytest.raises(SuggestionError):
        generate_revision({}, DESCRIPTION, VERDICT, VALID_SUGGESTIONS)
    with pytest.raises(SuggestionError):
        generate_revision(MATRIX, "  ", VERDICT, VALID_SUGGESTIONS)
    assert model.prompts == []
