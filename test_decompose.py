import json

import pytest

import decompose
import llm
from decompose import DecompositionError, decompose_invention


DESCRIPTION = "A leave-on foam that delivers sunscreen to the scalp through dense hair."

VALID_ELEMENTS = [
    {
        "id": "E1",
        "text": "a delivery format applied without rinsing",
        "search_terms": ["leave-on formulation", "no-rinse topical", "topical foam", "cosmetic composition"],
    },
    {
        "id": "E2",
        "text": "a carrier that spreads through dense hair to reach the skin surface",
        "search_terms": ["scalp delivery vehicle", "hair penetrating carrier", "topical carrier", "skin penetration"],
    },
    {
        "id": "E3",
        "text": "an agent that attenuates ultraviolet radiation at the scalp",
        "search_terms": ["ultraviolet filter", "sunscreen active", "uv absorber", "photoprotection"],
    },
    {
        "id": "E4",
        "text": "a texture that avoids leaving visible residue on hair",
        "search_terms": ["non-greasy composition", "residue free cosmetic", "hair feel", "cosmetic texture"],
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


def test_parses_plain_json(monkeypatch):
    model = install_model(monkeypatch, json.dumps(VALID_ELEMENTS))

    elements = decompose_invention(DESCRIPTION)

    assert elements == VALID_ELEMENTS
    assert len(model.prompts) == 1
    assert DESCRIPTION in model.prompts[0]
    assert "JSON only" in model.prompts[0]


def test_prompt_forbids_inventing_specifics(monkeypatch):
    model = install_model(monkeypatch, json.dumps(VALID_ELEMENTS))

    decompose_invention(DESCRIPTION)

    prompt = model.prompts[0]
    assert "Do not add specificity that is not present in the source text." in prompt
    assert "Never invent numerical values" in prompt
    assert "mutually consistent" in prompt


def test_prompt_asks_for_concise_text_and_patent_vocabulary_terms(monkeypatch):
    model = install_model(monkeypatch, json.dumps(VALID_ELEMENTS))

    decompose_invention(DESCRIPTION)

    prompt = model.prompts[0]
    assert 'Keep "text" to one short clause' in prompt
    assert "between 4 and 6 search terms" in prompt
    assert "load cell" in prompt


def test_falls_through_to_the_next_model_when_quota_is_spent(monkeypatch):
    used = []

    class QuotaExhausted(FakeModel):
        def generate_content(self, prompt, request_options=None):
            raise RuntimeError("429 You exceeded your current quota")

    working = FakeModel([json.dumps(VALID_ELEMENTS)])

    def pick(name):
        used.append(name)
        return QuotaExhausted([]) if len(used) == 1 else working

    monkeypatch.setattr(llm, "MODEL_NAMES", ["spent-model", "working-model"])
    monkeypatch.setattr(llm.genai, "GenerativeModel", pick)

    assert decompose_invention(DESCRIPTION) == VALID_ELEMENTS
    assert used == ["spent-model", "working-model"]


def test_raises_when_the_last_model_is_also_out_of_quota(monkeypatch):
    def boom(name):
        class Model:
            def generate_content(self, prompt, request_options=None):
                raise RuntimeError("429 You exceeded your current quota")

        return Model()

    monkeypatch.setattr(llm, "MODEL_NAMES", ["a", "b"])
    monkeypatch.setattr(llm.genai, "GenerativeModel", boom)

    with pytest.raises(RuntimeError, match="429"):
        decompose_invention(DESCRIPTION)


def test_strips_markdown_fences(monkeypatch):
    install_model(monkeypatch, "```json\n" + json.dumps(VALID_ELEMENTS) + "\n```")

    assert decompose_invention(DESCRIPTION) == VALID_ELEMENTS


def test_ignores_surrounding_prose(monkeypatch):
    install_model(
        monkeypatch,
        "Sure! Here are the elements:\n" + json.dumps(VALID_ELEMENTS) + "\nHope that helps.",
    )

    assert decompose_invention(DESCRIPTION) == VALID_ELEMENTS


def test_retries_once_then_succeeds(monkeypatch):
    model = install_model(monkeypatch, "I cannot do that.", json.dumps(VALID_ELEMENTS))

    assert decompose_invention(DESCRIPTION) == VALID_ELEMENTS
    assert len(model.prompts) == 2


def test_raises_after_second_failure(monkeypatch):
    model = install_model(monkeypatch, "not json", "still not json")

    with pytest.raises(DecompositionError):
        decompose_invention(DESCRIPTION)
    assert len(model.prompts) == 2


def test_rejects_too_few_elements(monkeypatch):
    payload = json.dumps(VALID_ELEMENTS[:2])
    install_model(monkeypatch, payload, payload)

    with pytest.raises(DecompositionError, match="4-8 elements"):
        decompose_invention(DESCRIPTION)


def test_rejects_too_many_elements(monkeypatch):
    payload = json.dumps(
        [dict(element, id=f"E{i}") for i, element in enumerate(VALID_ELEMENTS * 3, start=1)]
    )
    install_model(monkeypatch, payload, payload)

    with pytest.raises(DecompositionError, match="4-8 elements"):
        decompose_invention(DESCRIPTION)


def test_rejects_element_with_too_few_search_terms(monkeypatch):
    bad = [dict(element) for element in VALID_ELEMENTS]
    bad[1]["search_terms"] = ["only one"]
    payload = json.dumps(bad)
    install_model(monkeypatch, payload, payload)

    with pytest.raises(DecompositionError, match="search terms"):
        decompose_invention(DESCRIPTION)


def test_truncates_extra_search_terms_and_fills_missing_id(monkeypatch):
    raw = [dict(element) for element in VALID_ELEMENTS]
    raw[0] = {
        "text": "a delivery format applied without rinsing",
        "search_terms": ["a", "b", "c", "d", "e", "f", "g", "b"],
    }
    install_model(monkeypatch, json.dumps(raw))

    elements = decompose_invention(DESCRIPTION)

    assert elements[0]["id"] == "E1"
    assert elements[0]["search_terms"] == ["a", "b", "c", "d", "e", "f"]


def test_rejects_payload_without_array(monkeypatch):
    payload = json.dumps({"error": "cannot comply"})
    install_model(monkeypatch, payload, payload)

    with pytest.raises(DecompositionError, match="no JSON array"):
        decompose_invention(DESCRIPTION)


def test_accepts_array_wrapped_in_object(monkeypatch):
    install_model(monkeypatch, json.dumps({"elements": VALID_ELEMENTS}))

    assert decompose_invention(DESCRIPTION) == VALID_ELEMENTS


def test_empty_description_raises_without_calling_model(monkeypatch):
    model = install_model(monkeypatch)

    with pytest.raises(DecompositionError):
        decompose_invention("   ")
    assert model.prompts == []


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    install_model(monkeypatch)

    with pytest.raises(DecompositionError, match="GEMINI_API_KEY"):
        decompose_invention(DESCRIPTION)
