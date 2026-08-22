import pytest

import llm

PROMPT = "Return JSON only."


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def completion(content):
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture(autouse=True)
def openai_provider(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "openai")
    monkeypatch.setattr(llm, "OPENAI_MODEL_NAMES", ["model-a", "model-b"])
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def install_post(monkeypatch, *responses):
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm.requests, "post", post)
    return calls


def test_sends_the_prompt_and_returns_the_message_content(monkeypatch):
    calls = install_post(monkeypatch, FakeResponse(payload=completion('{"ok": true}')))

    assert llm.generate_text(PROMPT, ValueError) == '{"ok": true}'
    assert len(calls) == 1
    assert calls[0]["url"] == llm.OPENAI_ENDPOINT
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[0]["json"]["model"] == "model-a"
    assert calls[0]["json"]["messages"] == [{"role": "user", "content": PROMPT}]


def test_falls_through_to_the_next_model_when_the_first_is_rate_limited(monkeypatch):
    calls = install_post(
        monkeypatch,
        FakeResponse(status_code=429, text="rate limit"),
        FakeResponse(payload=completion("[]")),
    )

    assert llm.generate_text(PROMPT, ValueError) == "[]"
    assert [call["json"]["model"] for call in calls] == ["model-a", "model-b"]


def test_raises_when_every_model_is_rate_limited(monkeypatch):
    install_post(monkeypatch, FakeResponse(status_code=429, text="rate limit"))

    with pytest.raises(RuntimeError, match="429"):
        llm.generate_text(PROMPT, ValueError)


def test_does_not_retry_other_errors(monkeypatch):
    calls = install_post(monkeypatch, FakeResponse(status_code=401, text="bad key"))

    with pytest.raises(RuntimeError, match="401"):
        llm.generate_text(PROMPT, ValueError)
    assert len(calls) == 1


def test_empty_choices_return_an_empty_string(monkeypatch):
    install_post(monkeypatch, FakeResponse(payload={"choices": []}))

    assert llm.generate_text(PROMPT, ValueError) == ""


def test_missing_api_key_raises_the_caller_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY is not set"):
        llm.generate_text(PROMPT, ValueError)


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "llama")

    with pytest.raises(ValueError, match="unknown LLM_PROVIDER"):
        llm.generate_text(PROMPT, ValueError)
