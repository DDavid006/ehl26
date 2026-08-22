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


@pytest.fixture
def anthropic_provider(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "ANTHROPIC_MODEL_NAMES", ["claude-a", "claude-b"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")


def anthropic_message(*blocks):
    return {"content": list(blocks)}


def test_anthropic_sends_the_prompt_and_joins_the_text_blocks(monkeypatch, anthropic_provider):
    calls = install_post(
        monkeypatch,
        FakeResponse(
            payload=anthropic_message(
                {"type": "text", "text": "["},
                {"type": "tool_use", "name": "ignored", "input": {}},
                {"type": "text", "text": "]"},
            )
        ),
    )

    assert llm.generate_text(PROMPT, ValueError) == "[]"
    assert calls[0]["url"] == llm.ANTHROPIC_ENDPOINT
    assert calls[0]["headers"]["x-api-key"] == "test-anthropic-key"
    assert calls[0]["headers"]["anthropic-version"] == llm.ANTHROPIC_VERSION
    assert calls[0]["json"]["model"] == "claude-a"
    assert calls[0]["json"]["max_tokens"] == llm.ANTHROPIC_MAX_TOKENS
    assert calls[0]["json"]["messages"] == [{"role": "user", "content": PROMPT}]


def test_anthropic_falls_through_to_the_next_model_when_overloaded(monkeypatch, anthropic_provider):
    calls = install_post(
        monkeypatch,
        FakeResponse(status_code=529, text="overloaded, service unavailable"),
        FakeResponse(payload=anthropic_message({"type": "text", "text": "ok"})),
    )

    assert llm.generate_text(PROMPT, ValueError) == "ok"
    assert [call["json"]["model"] for call in calls] == ["claude-a", "claude-b"]


def test_anthropic_does_not_retry_other_errors(monkeypatch, anthropic_provider):
    calls = install_post(monkeypatch, FakeResponse(status_code=401, text="bad key"))

    with pytest.raises(RuntimeError, match="401 from Anthropic"):
        llm.generate_text(PROMPT, ValueError)
    assert len(calls) == 1


def test_anthropic_missing_api_key_raises_the_caller_error(monkeypatch, anthropic_provider):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is not set"):
        llm.generate_text(PROMPT, ValueError)


class Part:
    def __init__(self, text=None):
        if text is not None:
            self.text = text


class Content:
    def __init__(self, parts):
        self.parts = parts


class Candidate:
    def __init__(self, parts):
        self.content = Content(parts)


class GeminiResponse:
    """Mirrors the SDK: ``.text`` raises when a candidate holds a non-text part."""

    def __init__(self, parts, raises=False):
        self._parts = parts
        self._raises = raises
        self.candidates = [Candidate(parts)]

    @property
    def text(self):
        if self._raises:
            raise ValueError("Could not convert `part.function_call` to text.")
        return "".join(part.text for part in self._parts)


def test_gemini_text_reads_the_plain_response():
    assert llm._gemini_text(GeminiResponse([Part("hello")])) == "hello"


def test_gemini_text_survives_a_function_call_part():
    response = GeminiResponse([Part(), Part("tail")], raises=True)

    assert llm._gemini_text(response) == "tail"


def test_gemini_text_of_a_function_call_only_response_is_empty():
    assert llm._gemini_text(GeminiResponse([Part()], raises=True)) == ""


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "llama")

    with pytest.raises(ValueError, match="unknown LLM_PROVIDER"):
        llm.generate_text(PROMPT, ValueError)
