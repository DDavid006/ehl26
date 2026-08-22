"""Text generation against the configured provider (Gemini or OpenAI).

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
OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"

PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower() or "gemini"
# Free-tier request quota is per model, so a spent model falls through to the next one.
MODEL_NAMES = [name.strip() for name in os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODELS).split(",") if name.strip()]
OPENAI_MODEL_NAMES = [name.strip() for name in os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODELS).split(",") if name.strip()]
REQUEST_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT", "60"))

UNUSABLE_MODEL_MARKERS = ("429", "404", "503", "504", "quota", "deadline", "unavailable")


def _is_model_unusable(exc: Exception) -> bool:
    """True for errors that another model may not have: quota, retirement, overload."""
    message = str(exc).lower()
    return any(marker in message for marker in UNUSABLE_MODEL_MARKERS)


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
        return getattr(response, "text", "") or ""
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


def generate_text(prompt: str, error_cls: type[Exception]) -> str:
    """Generate ``prompt`` with the first configured model that answers."""
    if PROVIDER == "openai":
        return _generate_openai(prompt, error_cls)
    if PROVIDER == "gemini":
        return _generate_gemini(prompt, error_cls)
    raise error_cls(f"unknown LLM_PROVIDER {PROVIDER!r}: use 'gemini' or 'openai'")
