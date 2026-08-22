"""Devin v1 session backend for structured autonomous agent calls."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import requests
from jsonschema import validate


class DevinBackendError(RuntimeError):
    """Raised when a Devin session fails or returns invalid output."""


class DevinAgentBackend:
    base_url = "https://api.devin.ai/v1"

    def __init__(
        self,
        api_key: str | None,
        *,
        session: Any | None = None,
        run_dir: Path | str | None = None,
        timeout_seconds: float = 1500,
        poll_interval: float = 2.0,
        max_concurrent: int = 5,
        log_callback: Callable[[str, dict], str | None] | None = None,
    ):
        if not api_key:
            raise DevinBackendError(
                "DEVIN_API_KEY is required for PATENTLOOP_BACKEND=devin"
            )
        from threading import BoundedSemaphore

        self.api_key = api_key
        self.session = session or requests.Session()
        self.run_dir = Path(run_dir) if run_dir else None
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self._semaphore = BoundedSemaphore(max_concurrent)
        self.log_callback = log_callback
        self.last_session_id: str | None = None
        self.last_session_url: str | None = None
        self.last_log_path: str | None = None

    @staticmethod
    def _schema(schema: dict) -> dict:
        return schema.get("schema", schema)

    def chat(
        self,
        prompt: str,
        json_schema: dict,
        *,
        title: str = "PatentLoop agent",
        tags: list[str] | None = None,
        max_acu_limit: int = 25,
    ) -> dict[str, Any]:
        schema = self._schema(json_schema)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "prompt": prompt,
            "structured_output_schema": schema,
            "title": title,
            "tags": tags or ["patentloop"],
            "unlisted": True,
            "max_acu_limit": max_acu_limit,
        }
        with self._semaphore:
            try:
                response = self.session.post(
                    f"{self.base_url}/sessions",
                    headers=headers,
                    json=body,
                    timeout=60,
                )
                response.raise_for_status()
                created = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise DevinBackendError(f"could not create Devin session: {exc}") from exc
            session_id = created.get("session_id") or created.get("id")
            if not session_id:
                raise DevinBackendError("Devin session response did not include session_id")
            self.last_session_id = session_id
            self.last_session_url = (
                created.get("url")
                or created.get("session_url")
                or f"https://app.devin.ai/sessions/{session_id}"
            )
            started = time.monotonic()
            polls = []
            interval = self.poll_interval
            terminal = {"completed", "failed", "error", "stopped", "terminated", "cancelled"}
            while True:
                if time.monotonic() - started >= self.timeout_seconds:
                    raise DevinBackendError(
                        f"Devin session {session_id} timed out after {self.timeout_seconds:g}s"
                    )
                try:
                    poll_response = self.session.get(
                        f"{self.base_url}/session/{session_id}",
                        headers=headers,
                        timeout=60,
                    )
                    poll_response.raise_for_status()
                    state = poll_response.json()
                except (requests.RequestException, ValueError) as exc:
                    raise DevinBackendError(f"could not poll Devin session {session_id}: {exc}") from exc
                polls.append(state)
                status = str(state.get("status") or state.get("state") or "").lower()
                if status in terminal:
                    if status != "completed":
                        raise DevinBackendError(
                            f"Devin session {session_id} ended with status {status}"
                        )
                    output = state.get("structured_output")
                    if isinstance(output, str):
                        try:
                            output = json.loads(output)
                        except json.JSONDecodeError as exc:
                            raise DevinBackendError("Devin structured_output was not JSON") from exc
                    if not isinstance(output, dict):
                        raise DevinBackendError("Devin session completed without structured_output")
                    try:
                        validate(output, schema)
                    except Exception as exc:
                        raise DevinBackendError(
                            f"Devin structured output failed schema validation: {exc}"
                        ) from exc
                    log_payload = {
                        "backend": "devin",
                        "session_id": session_id,
                        "session_url": self.last_session_url,
                        "request": body,
                        "created_response": created,
                        "poll_responses": polls,
                        "structured_output": output,
                    }
                    if self.log_callback:
                        self.last_log_path = self.log_callback(title.replace(" ", "_"), log_payload)
                    return output
                time.sleep(interval)
                interval = min(max(interval * 1.5, 0.1), 15.0)
