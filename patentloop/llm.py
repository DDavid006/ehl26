"""Anthropic Messages API client.

Each agent gets its own system prompt and asks for a JSON object matching a
declared shape; the client parses and validates the keys so a malformed
completion is a retry rather than a silently empty score.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .config import Config
from .http import HttpError, post_json
from .trace import Tracer

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMError(Exception):
    pass


def _extract_json(text: str) -> Any:
    candidates = [text.strip()]
    fenced = _FENCE.search(text)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise LLMError(f"no JSON object in completion: {text[:400]}")


class LLM:
    def __init__(self, config: Config, tracer: Tracer):
        self.config = config
        self.tracer = tracer

    def json_call(
        self,
        *,
        agent: str,
        purpose: str,
        system: str,
        user: str,
        required_keys: tuple[str, ...] = (),
        max_tokens: int | None = None,
        iteration: int | None = None,
        attempts: int = 3,
    ) -> dict:
        """Ask for a JSON object and return it parsed."""

        payload = {
            "model": self.config.anthropic_model,
            "max_tokens": max_tokens or self.config.anthropic_max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self.config.anthropic_api_key,
            "anthropic-version": API_VERSION,
        }
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                body, _ = post_json(
                    API_URL,
                    payload,
                    headers=headers,
                    timeout=max(self.config.request_timeout, 120),
                    retries=3,
                )
            except HttpError as exc:
                last_error = exc
                self.tracer.api_error("llm", "anthropic", purpose, str(exc), iteration)
                if attempt == attempts:
                    raise LLMError(f"Anthropic API call failed for {purpose}: {exc}") from exc
                continue
            text = "".join(
                block.get("text", "") for block in body.get("content", []) if block.get("type") == "text"
            )
            try:
                parsed = _extract_json(text)
                if not isinstance(parsed, dict):
                    raise LLMError("completion JSON is not an object")
                missing = [k for k in required_keys if k not in parsed]
                if missing:
                    raise LLMError(f"completion missing keys {missing}")
            except LLMError as exc:
                last_error = exc
                self.tracer.llm_call(
                    agent, f"{purpose}:invalid", system, user, text, {"error": str(exc)},
                    self.config.anthropic_model, body.get("usage"), iteration,
                )
                if attempt == attempts:
                    raise
                user = (
                    f"{user}\n\nYour previous reply was rejected: {exc}. "
                    "Reply with a single valid JSON object and nothing else."
                )
                payload["messages"] = [{"role": "user", "content": user}]
                continue
            self.tracer.llm_call(
                agent, purpose, system, user, text, parsed,
                self.config.anthropic_model, body.get("usage"), iteration,
            )
            return parsed
        raise LLMError(str(last_error))


def clamp(value: Any, low: float = 0.0, high: float = 100.0, default: float = 0.0) -> float:
    try:
        return round(min(max(float(value), low), high), 2)
    except (TypeError, ValueError):
        return default


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "pass", "1"}
    return bool(value)
