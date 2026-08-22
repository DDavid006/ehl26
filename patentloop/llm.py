"""Pluggable structured judge facade for Devin and OpenAI backends."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backends.devin_agent import DevinAgentBackend
from .backends.openai_chat import OpenAIChatBackend
from .config import Settings
from .embed import embed as local_embed


class LLMError(RuntimeError):
    """Raised when a judge request cannot be completed."""


class MissingKeyError(LLMError):
    """Raised when a live LLM call has no API key."""


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class Judge:
    """Single structured-output API shared by all agent implementations."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        backend=None,
        session=None,
        run_dir: Path | str | None = None,
    ):
        self.settings = settings or Settings()
        self.run_dir = Path(run_dir) if run_dir else None
        self._sequence = 0
        self._lock = threading.Lock()
        if backend is not None and hasattr(backend, "chat"):
            self.backend = backend
            self.backend_name = type(backend).__name__
            return
        selected = os.environ.get(
            "PATENTLOOP_BACKEND", self.settings.backend
        ).lower()
        if selected == "devin":
            self.backend = DevinAgentBackend(
                self.settings.devin_api_key,
                session=session,
                run_dir=self.run_dir,
                timeout_seconds=self.settings.devin_timeout_seconds,
                poll_interval=self.settings.devin_poll_interval,
                max_concurrent=self.settings.devin_max_concurrent,
                log_callback=self._log,
            )
        elif selected == "openai":
            self.backend = OpenAIChatBackend(
                self.settings.openai_api_key,
                self.settings.openai_base_url,
                self.settings.model,
                session=session,
                log_callback=self._log,
            )
        else:
            raise LLMError(f"unknown PATENTLOOP_BACKEND={selected!r}; use devin or openai")
        self.backend_name = selected

    @property
    def last_log_path(self):
        return getattr(self.backend, "last_log_path", None)

    @property
    def last_session_url(self):
        return getattr(self.backend, "last_session_url", None)

    @property
    def session(self):
        return getattr(self.backend, "session", None)

    def _log(self, agent: str, payload: dict[str, Any]) -> str | None:
        if self.run_dir is None:
            return None
        with self._lock:
            directory = self.run_dir / "llm"
            directory.mkdir(parents=True, exist_ok=True)
            self._sequence += 1
            path = directory / f"{self._sequence:04d}_{agent}.json"
            path.write_text(json.dumps({"logged_at": _stamp(), **payload}, indent=2, default=str) + "\n")
            return str(path)

    def chat(
        self,
        prompt: str,
        json_schema: dict[str, Any],
        *,
        agent: str = "agent",
        title: str | None = None,
    ) -> dict[str, Any]:
        return self.backend.chat(
            prompt, json_schema, title=title or agent, tags=["patentloop", agent]
        )

    def embed(self, texts: list[str], *, agent: str = "embed"):
        vectors = local_embed(
            texts,
            model_name=self.settings.embedding_model,
            cache_dir=self.settings.model_cache,
        )
        record = {
            "backend": "local_sentence_transformer",
            "model_name": self.settings.embedding_model,
            "vector_dimension": len(vectors[0]) if vectors else 0,
            "count": len(texts),
            "text_sha256": [
                hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts
            ],
        }
        return vectors, self._log(agent, record)

    def digest(self, value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, default=str).encode()
        ).hexdigest()
