import json

import pytest

import decompose
import llm
from examine import ExaminationError, judge_patentability

DESCRIPTION = "A leave-on foam that delivers sunscreen to the scalp through dense hair."

MATRIX = {
    "elements": [
        {"id": "E1", "text": "a leave-on delivery format", "search_terms": ["leave-on"]},
        {"id": "E2", "text": "a metered dose applicator", "search_terms": ["metered dose"]},
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
        "E2": {"US1234567": {"covered": False, "evidence": ""}},
    },
    "uncovered": ["E2"],
}

VERDICT = {
    "patentable": False,
    "reasoning": "E1 is anticipated by US1234567 and E2 is a trivial dosing difference.",
}


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []

    def generate_content(self, prompt, request_options=None):
        self.prompts.append(prompt)
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


def test_parses_verdict_and_prompt_contents(monkeypatch):
    model = install_model(monkeypatch, json.dumps(VERDICT))

    assert judge_patentability(MATRIX, DESCRIPTION) == VERDICT
    prompt = model.prompts[0]
    assert DESCRIPTION in prompt
    assert '"uncovered"' in prompt
    assert "US1234567" in prompt
    assert "JSON only" in prompt


def test_accepts_a_patentable_verdict(monkeypatch):
    install_model(monkeypatch, json.dumps({"patentable": True, "reasoning": "E2 is novel."}))

    verdict = judge_patentability(MATRIX, DESCRIPTION)

    assert verdict["patentable"] is True
    assert verdict["reasoning"] == "E2 is novel."


def test_strips_fences_and_surrounding_prose(monkeypatch):
    install_model(monkeypatch, "```json\n" + json.dumps(VERDICT) + "\n```")

    assert judge_patentability(MATRIX, DESCRIPTION) == VERDICT


def test_retries_once_then_succeeds(monkeypatch):
    model = install_model(monkeypatch, "sorry, no JSON", json.dumps(VERDICT))

    assert judge_patentability(MATRIX, DESCRIPTION) == VERDICT
    assert len(model.prompts) == 2


def test_raises_after_second_failure(monkeypatch):
    model = install_model(monkeypatch, "not json", "still not json")

    with pytest.raises(ExaminationError):
        judge_patentability(MATRIX, DESCRIPTION)
    assert len(model.prompts) == 2


def test_rejects_non_boolean_patentable(monkeypatch):
    payload = json.dumps({"patentable": "maybe", "reasoning": "unsure"})
    install_model(monkeypatch, payload, payload)

    with pytest.raises(ExaminationError, match="boolean"):
        judge_patentability(MATRIX, DESCRIPTION)


def test_rejects_missing_reasoning(monkeypatch):
    payload = json.dumps({"patentable": True, "reasoning": "  "})
    install_model(monkeypatch, payload, payload)

    with pytest.raises(ExaminationError, match="reasoning"):
        judge_patentability(MATRIX, DESCRIPTION)


def test_rejects_empty_inputs():
    with pytest.raises(ExaminationError):
        judge_patentability({}, DESCRIPTION)
    with pytest.raises(ExaminationError):
        judge_patentability(MATRIX, "   ")
