"""OpenAI access for PatentLoop: JSON-mode chat completions and embeddings."""

from __future__ import annotations

import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

CHAT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
EMBED_ENDPOINT = "https://api.openai.com/v1/embeddings"
CHAT_MODEL = os.getenv("PATENTLOOP_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("PATENTLOOP_EMBED_MODEL", "text-embedding-3-small")
REQUEST_TIMEOUT = float(os.getenv("PATENTLOOP_TIMEOUT", "120"))


class LLMError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise LLMError("OPENAI_API_KEY is not set")
    return key


def chat_json(system: str, user: str, temperature: float = 0.2) -> dict:
    """One JSON-mode chat completion; returns the parsed object."""
    response = requests.post(
        CHAT_ENDPOINT,
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
        json={
            "model": CHAT_MODEL,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise LLMError(f"{response.status_code} from OpenAI: {response.text[:300]}")
    content = response.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except ValueError as exc:
        raise LLMError(f"model returned invalid JSON: {content[:300]}") from exc


def chat_text(system: str, user: str, temperature: float = 0.4) -> str:
    """One plain-text chat completion."""
    response = requests.post(
        CHAT_ENDPOINT,
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
        json={
            "model": CHAT_MODEL,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise LLMError(f"{response.status_code} from OpenAI: {response.text[:300]}")
    return response.json()["choices"][0]["message"]["content"] or ""


def embed(texts: list[str]) -> list[list[float]]:
    """Embedding vectors for ``texts``, in order."""
    if not texts:
        return []
    response = requests.post(
        EMBED_ENDPOINT,
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
        json={"model": EMBED_MODEL, "input": texts},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise LLMError(f"{response.status_code} from OpenAI embeddings: {response.text[:300]}")
    data = sorted(response.json()["data"], key=lambda item: item["index"])
    return [item["embedding"] for item in data]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
