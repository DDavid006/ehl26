"""A minimal tool-calling agent loop.

:func:`run_agent` lets the model decide which tools to call, and how often,
before it answers. The Anthropic and OpenAI providers support tool use; under
``LLM_PROVIDER=gemini`` the agent degrades to a single :func:`llm.generate_text`
call with no tools, so the app keeps working either way.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Iterable, Optional

import requests

import llm

MAX_TOOL_CALLS = 6
MAX_TURNS = 8
TOOL_PROVIDERS = ("anthropic", "openai")


class Tool:
    """A function the model may call, plus the JSON schema it is described by."""

    def __init__(self, name: str, description: str, parameters: dict, func: Callable[..., object]) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.func = func

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def anthropic_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def invoke(self, kwargs: dict) -> str:
        try:
            return json.dumps(self.func(**kwargs))
        except Exception as exc:  # a failing tool must not kill the run
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

    def call(self, arguments: str) -> str:
        try:
            kwargs = json.loads(arguments) if arguments.strip() else {}
        except ValueError as exc:
            return json.dumps({"error": f"arguments were not valid JSON: {exc}"})
        if not isinstance(kwargs, dict):
            return json.dumps({"error": "arguments must be a JSON object"})
        return self.invoke(kwargs)


def _post(url: str, headers: dict, payload: dict, provider: str) -> dict:
    response = requests.post(url, headers=headers, json=payload, timeout=llm.REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(f"{response.status_code} from {provider}: {response.text[:200]}")
    return response.json()


def _message(data: dict) -> dict:
    choices = data.get("choices") or []
    if not choices:
        return {}
    return choices[0].get("message") or {}


def run_agent(
    prompt: str,
    tools: Iterable[Tool],
    error_cls: type[Exception],
    max_tool_calls: int = MAX_TOOL_CALLS,
    on_tool_call: Optional[Callable[[str, dict], None]] = None,
) -> str:
    """Run ``prompt`` letting the model call ``tools``; return its final text.

    ``on_tool_call`` is invoked with the tool name and its parsed arguments each
    time the model asks for one, so callers can report progress. The tool budget
    is a hard cap: once it is spent the tools are withdrawn and the model is
    asked to answer with what it has.
    """
    by_name = {tool.name: tool for tool in tools}
    if llm.PROVIDER not in TOOL_PROVIDERS or not by_name:
        return llm.generate_text(prompt, error_cls)
    if llm.PROVIDER == "anthropic":
        return _run_anthropic(prompt, by_name, error_cls, max_tool_calls, on_tool_call)
    return _run_openai(prompt, by_name, error_cls, max_tool_calls, on_tool_call)


def _run_openai(
    prompt: str,
    by_name: dict[str, Tool],
    error_cls: type[Exception],
    max_tool_calls: int,
    on_tool_call: Optional[Callable[[str, dict], None]],
) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise error_cls("OPENAI_API_KEY is not set")

    model = llm.OPENAI_MODEL_NAMES[0] if llm.OPENAI_MODEL_NAMES else "gpt-4.1-mini"
    messages: list[dict] = [{"role": "user", "content": prompt}]
    used = 0

    for _ in range(MAX_TURNS):
        payload: dict = {"model": model, "messages": messages}
        if used < max_tool_calls:
            payload["tools"] = [tool.schema() for tool in by_name.values()]
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        message = _message(_post(llm.OPENAI_ENDPOINT, headers, payload, "OpenAI"))
        calls = message.get("tool_calls") or []
        if not calls:
            answer = message.get("content") or ""
            if answer.strip():
                return answer
            continue  # an empty answer is worth asking for again

        messages.append(message)
        for call in calls:
            function = call.get("function") or {}
            name = function.get("name") or ""
            raw_arguments = function.get("arguments") or "{}"
            tool = by_name.get(name)
            if tool is None:
                result = json.dumps({"error": f"unknown tool {name!r}"})
            else:
                if on_tool_call is not None:
                    try:
                        parsed = json.loads(raw_arguments)
                    except ValueError:
                        parsed = {}
                    on_tool_call(name, parsed if isinstance(parsed, dict) else {})
                result = tool.call(raw_arguments)
                used += 1
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": result})

    raise error_cls(f"agent did not finish within {MAX_TURNS} turns")


def _run_anthropic(
    prompt: str,
    by_name: dict[str, Tool],
    error_cls: type[Exception],
    max_tool_calls: int,
    on_tool_call: Optional[Callable[[str, dict], None]],
) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise error_cls("ANTHROPIC_API_KEY is not set")

    model = llm.ANTHROPIC_MODEL_NAMES[0] if llm.ANTHROPIC_MODEL_NAMES else "claude-sonnet-4-6"
    messages: list[dict] = [{"role": "user", "content": prompt}]
    used = 0

    for _ in range(MAX_TURNS):
        payload: dict = {
            "model": model,
            "max_tokens": llm.ANTHROPIC_MAX_TOKENS,
            "messages": messages,
        }
        if used < max_tool_calls:
            payload["tools"] = [tool.anthropic_schema() for tool in by_name.values()]
        content = _post(
            llm.ANTHROPIC_ENDPOINT, llm.anthropic_headers(api_key), payload, "Anthropic"
        ).get("content") or []
        requested = [block for block in content if block.get("type") == "tool_use"]
        if not requested:
            answer = llm.anthropic_text(content)
            if answer.strip():
                return answer
            continue  # an empty answer is worth asking for again

        messages.append({"role": "assistant", "content": content})
        results = []
        for block in requested:
            name = block.get("name") or ""
            arguments = block.get("input")
            arguments = arguments if isinstance(arguments, dict) else {}
            tool = by_name.get(name)
            if tool is None:
                result = json.dumps({"error": f"unknown tool {name!r}"})
            else:
                if on_tool_call is not None:
                    on_tool_call(name, arguments)
                result = tool.invoke(arguments)
                used += 1
            results.append(
                {"type": "tool_result", "tool_use_id": block.get("id"), "content": result}
            )
        messages.append({"role": "user", "content": results})

    raise error_cls(f"agent did not finish within {MAX_TURNS} turns")
