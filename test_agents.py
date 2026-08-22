import json

import pytest

import agents
import llm
from agents import Tool, run_agent


def tool(func=None, name="search_prior_art"):
    return Tool(
        name=name,
        description="search",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        func=func if func is not None else (lambda query: [{"patent_id": "US1", "title": query}]),
    )


class FakeResponse:
    def __init__(self, message=None, status_code=200, text=""):
        self.status_code = status_code
        self._message = message or {}
        self.text = text

    def json(self):
        return {"choices": [{"message": self._message}]}


def answer(content):
    return FakeResponse({"role": "assistant", "content": content})


def wants(name, arguments, call_id="call-1"):
    return FakeResponse(
        {
            "role": "assistant",
            "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}
            ],
        }
    )


@pytest.fixture(autouse=True)
def openai_provider(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "openai")
    monkeypatch.setattr(llm, "OPENAI_MODEL_NAMES", ["model-a"])
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def install_post(monkeypatch, *responses):
    payloads = []

    def post(url, headers=None, json=None, timeout=None):
        payloads.append(json)
        return responses[min(len(payloads) - 1, len(responses) - 1)]

    monkeypatch.setattr(agents.requests, "post", post)
    return payloads


def test_returns_the_answer_without_tool_calls(monkeypatch):
    payloads = install_post(monkeypatch, answer('{"patentable": false}'))

    assert run_agent("judge this", [tool()], ValueError) == '{"patentable": false}'
    assert len(payloads) == 1
    assert [spec["function"]["name"] for spec in payloads[0]["tools"]] == ["search_prior_art"]


def test_runs_the_tool_and_feeds_the_result_back(monkeypatch):
    payloads = install_post(
        monkeypatch,
        wants("search_prior_art", '{"query": "uv-c led cap"}'),
        answer("done"),
    )
    seen = []

    result = run_agent("judge this", [tool()], ValueError, on_tool_call=lambda n, a: seen.append((n, a)))

    assert result == "done"
    assert seen == [("search_prior_art", {"query": "uv-c led cap"})]
    tool_message = payloads[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call-1"
    assert json.loads(tool_message["content"]) == [{"patent_id": "US1", "title": "uv-c led cap"}]


def test_withdraws_the_tools_once_the_budget_is_spent(monkeypatch):
    payloads = install_post(
        monkeypatch,
        wants("search_prior_art", '{"query": "one"}'),
        answer("done"),
    )

    run_agent("judge this", [tool()], ValueError, max_tool_calls=1)

    assert "tools" in payloads[0]
    assert "tools" not in payloads[1]  # the model must answer with what it has


def test_a_failing_tool_is_reported_to_the_model_not_raised(monkeypatch):
    def boom(query):
        raise RuntimeError("serper down")

    payloads = install_post(
        monkeypatch, wants("search_prior_art", '{"query": "x"}'), answer("done")
    )

    assert run_agent("judge this", [tool(boom)], ValueError) == "done"
    assert "serper down" in payloads[1]["messages"][-1]["content"]


def test_unknown_tool_and_invalid_arguments_are_reported(monkeypatch):
    payloads = install_post(monkeypatch, wants("nope", "{}"), answer("done"))

    assert run_agent("judge this", [tool()], ValueError) == "done"
    assert "unknown tool" in payloads[1]["messages"][-1]["content"]

    payloads = install_post(
        monkeypatch, wants("search_prior_art", "not json"), answer("done")
    )
    run_agent("judge this", [tool()], ValueError)
    assert "not valid JSON" in payloads[1]["messages"][-1]["content"]


def test_raises_when_the_model_never_stops_calling_tools(monkeypatch):
    install_post(monkeypatch, wants("search_prior_art", '{"query": "x"}'))

    with pytest.raises(ValueError, match="did not finish"):
        run_agent("judge this", [tool()], ValueError, max_tool_calls=99)


def test_falls_back_to_a_plain_call_without_tool_support(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "gemini")
    monkeypatch.setattr(llm, "generate_text", lambda prompt, error_cls: "plain answer")

    assert run_agent("judge this", [tool()], ValueError) == "plain answer"


def test_missing_api_key_raises_the_caller_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY is not set"):
        run_agent("judge this", [tool()], ValueError)


def test_http_errors_propagate(monkeypatch):
    install_post(monkeypatch, FakeResponse(status_code=500, text="boom"))

    with pytest.raises(RuntimeError, match="500 from OpenAI"):
        run_agent("judge this", [tool()], ValueError)


class AnthropicResponse:
    def __init__(self, *blocks, status_code=200, text=""):
        self.status_code = status_code
        self._blocks = list(blocks)
        self.text = text

    def json(self):
        return {"content": self._blocks}


def says(text):
    return {"type": "text", "text": text}


def uses(name, arguments, block_id="tool-1"):
    return {"type": "tool_use", "id": block_id, "name": name, "input": arguments}


@pytest.fixture
def anthropic_provider(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "ANTHROPIC_MODEL_NAMES", ["claude-a"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")


def test_anthropic_runs_the_tool_and_feeds_the_result_back(monkeypatch, anthropic_provider):
    payloads = install_post(
        monkeypatch,
        AnthropicResponse(says("let me look"), uses("search_prior_art", {"query": "uv-c led cap"})),
        AnthropicResponse(says('{"patentable": false}')),
    )
    seen = []

    result = run_agent(
        "judge this", [tool()], ValueError, on_tool_call=lambda n, a: seen.append((n, a))
    )

    assert result == '{"patentable": false}'
    assert seen == [("search_prior_art", {"query": "uv-c led cap"})]
    assert [spec["name"] for spec in payloads[0]["tools"]] == ["search_prior_art"]
    assert "input_schema" in payloads[0]["tools"][0]
    # the tool result goes back as a user turn holding a tool_result block
    assert payloads[1]["messages"][1]["role"] == "assistant"
    block = payloads[1]["messages"][2]["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "tool-1"
    assert json.loads(block["content"]) == [{"patent_id": "US1", "title": "uv-c led cap"}]


def test_anthropic_withdraws_the_tools_once_the_budget_is_spent(monkeypatch, anthropic_provider):
    payloads = install_post(
        monkeypatch,
        AnthropicResponse(uses("search_prior_art", {"query": "one"})),
        AnthropicResponse(says("done")),
    )

    run_agent("judge this", [tool()], ValueError, max_tool_calls=1)

    assert "tools" in payloads[0]
    assert "tools" not in payloads[1]


def test_anthropic_reports_unknown_tools_and_failures(monkeypatch, anthropic_provider):
    def boom(query):
        raise RuntimeError("serper down")

    payloads = install_post(
        monkeypatch,
        AnthropicResponse(uses("nope", {})),
        AnthropicResponse(says("done")),
    )
    assert run_agent("judge this", [tool()], ValueError) == "done"
    assert "unknown tool" in payloads[1]["messages"][2]["content"][0]["content"]

    payloads = install_post(
        monkeypatch,
        AnthropicResponse(uses("search_prior_art", {"query": "x"})),
        AnthropicResponse(says("done")),
    )
    assert run_agent("judge this", [tool(boom)], ValueError) == "done"
    assert "serper down" in payloads[1]["messages"][2]["content"][0]["content"]


def test_anthropic_missing_api_key_raises_the_caller_error(monkeypatch, anthropic_provider):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is not set"):
        run_agent("judge this", [tool()], ValueError)


def test_anthropic_http_errors_propagate(monkeypatch, anthropic_provider):
    install_post(monkeypatch, AnthropicResponse(status_code=500, text="boom"))

    with pytest.raises(RuntimeError, match="500 from Anthropic"):
        run_agent("judge this", [tool()], ValueError)
