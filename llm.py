"""Text generation against the configured provider (Anthropic, OpenAI or Gemini).

``LLM_PROVIDER`` selects the backend; every module goes through
:func:`generate_text`, so the rest of the app is provider agnostic.
"""

from __future__ import annotations

import os

import google.generativeai as genai
import requests
from dotenv import load_dotenv

load_dotenv()

# Lite models answer this in seconds where the thinking models take tens of seconds.
DEFAULT_GEMINI_MODELS = "gemini-flash-lite-latest,gemini-3.5-flash-lite,gemini-flash-latest,gemini-3.5-flash"
DEFAULT_OPENAI_MODELS = "gpt-4.1-mini,gpt-4o-mini"
DEFAULT_ANTHROPIC_MODELS = "claude-sonnet-5,claude-sonnet-4-6,claude-haiku-4-5-20251001"
OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MAX_TOKENS = 4096

PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower() or "gemini"
# Free-tier request quota is per model, so a spent model falls through to the next one.
MODEL_NAMES = [name.strip() for name in os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODELS).split(",") if name.strip()]
OPENAI_MODEL_NAMES = [name.strip() for name in os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODELS).split(",") if name.strip()]
ANTHROPIC_MODEL_NAMES = [name.strip() for name in os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODELS).split(",") if name.strip()]
REQUEST_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT", "60"))

UNUSABLE_MODEL_MARKERS = ("429", "404", "503", "504", "quota", "deadline", "unavailable")


def _is_model_unusable(exc: Exception) -> bool:
    """True for errors that another model may not have: quota, retirement, overload."""
    message = str(exc).lower()
    return any(marker in message for marker in UNUSABLE_MODEL_MARKERS)


def _gemini_text(response: object) -> str:
    """Text of a Gemini response, tolerating candidates that are not plain text.

    ``response.text`` raises when the model answers with a non-text part (a
    ``function_call``, for instance), so fall back to joining whatever text parts
    there are and let the caller decide what an empty answer means.
    """
    try:
        return getattr(response, "text", "") or ""
    except ValueError:
        pass
    parts = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            parts.append(getattr(part, "text", "") or "")
    return "".join(parts)


def _generate_gemini(prompt: str, error_cls: type[Exception]) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise error_cls("GEMINI_API_KEY is not set")
    genai.configure(api_key=api_key)

    for index, name in enumerate(MODEL_NAMES):
        try:
            response = genai.GenerativeModel(name).generate_content(
                prompt,
                # retry=None: a 429 means the model's daily quota is gone, so waiting
                # out api_core's backoff only burns the timeout budget.
                request_options={"timeout": REQUEST_TIMEOUT, "retry": None},
            )
        except Exception as exc:
            if index == len(MODEL_NAMES) - 1 or not _is_model_unusable(exc):
                raise
            continue
        return _gemini_text(response)
    raise error_cls("no Gemini model configured")


def _openai_completion(name: str, prompt: str, api_key: str) -> str:
    response = requests.post(
        OPENAI_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": name,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(f"{response.status_code} from OpenAI: {response.text[:200]}")
    choices = response.json().get("choices") or []
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content") or ""


def _generate_openai(prompt: str, error_cls: type[Exception]) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise error_cls("OPENAI_API_KEY is not set")

    for index, name in enumerate(OPENAI_MODEL_NAMES):
        try:
            return _openai_completion(name, prompt, api_key)
        except Exception as exc:
            if index == len(OPENAI_MODEL_NAMES) - 1 or not _is_model_unusable(exc):
                raise
    raise error_cls("no OpenAI model configured")


def anthropic_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": "application/json",
    }


def anthropic_text(content: list) -> str:
    """Concatenate the text blocks of an Anthropic ``content`` array."""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
    return "".join(parts)


def _anthropic_completion(name: str, prompt: str, api_key: str) -> str:
    response = requests.post(
        ANTHROPIC_ENDPOINT,
        headers=anthropic_headers(api_key),
        json={
            "model": name,
            "max_tokens": ANTHROPIC_MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(f"{response.status_code} from Anthropic: {response.text[:200]}")
    return anthropic_text(response.json().get("content") or [])


def _generate_anthropic(prompt: str, error_cls: type[Exception]) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise error_cls("ANTHROPIC_API_KEY is not set")

    for index, name in enumerate(ANTHROPIC_MODEL_NAMES):
        try:
            return _anthropic_completion(name, prompt, api_key)
        except Exception as exc:
            if index == len(ANTHROPIC_MODEL_NAMES) - 1 or not _is_model_unusable(exc):
                raise
    raise error_cls("no Anthropic model configured")


def generate_text(prompt: str, error_cls: type[Exception]) -> str:
    """Generate ``prompt`` with the first configured model that answers."""
    if PROVIDER == "anthropic":
        return _generate_anthropic(prompt, error_cls)
    if PROVIDER == "openai":
        return _generate_openai(prompt, error_cls)
    if PROVIDER == "gemini":
        return _generate_gemini(prompt, error_cls)
    raise error_cls(
        f"unknown LLM_PROVIDER {PROVIDER!r}: use 'anthropic', 'openai' or 'gemini'"
    )
