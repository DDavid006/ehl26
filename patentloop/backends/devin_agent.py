"""Devin v1 session backend for structured autonomous agent calls."""

from __future__ import annotations

import json
import threading
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
        unlisted: bool = False,
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
        self.unlisted = unlisted
        self._semaphore = BoundedSemaphore(max_concurrent)
        self.log_callback = log_callback
        self.last_session_id: str | None = None
        self.last_session_url: str | None = None
        self.last_log_path: str | None = None
        self._log_sequence = 0
        self._log_lock = threading.Lock()

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
            "unlisted": self.unlisted,
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
            nudges = []
            interval = self.poll_interval
            terminal = {"completed", "failed", "error", "stopped", "terminated", "cancelled"}
            blocked = {
                "blocked", "idle", "waiting", "awaiting_input",
                "needs_input", "paused", "awaiting_user",
                "waiting_for_user", "input_required",
            }
            nudged = False
            while True:
                if time.monotonic() - started >= self.timeout_seconds:
                    error = DevinBackendError(
                        f"Devin session {session_id} timed out after {self.timeout_seconds:g}s"
                    )
                    self._record(
                        title,
                        {
                            "backend": "devin",
                            "session_id": session_id,
                            "session_url": self.last_session_url,
                            "request": body,
                            "created_response": created,
                            "poll_responses": polls,
                            "nudges": nudges,
                            "error": str(error),
                        },
                    )
                    raise error
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
                if status in blocked:
                    if nudged:
                        error = DevinBackendError(
                            f"Devin session {session_id} remained {status} after an autonomous nudge"
                        )
                        self._record(
                            title,
                            {
                                "backend": "devin",
                                "session_id": session_id,
                                "session_url": self.last_session_url,
                                "request": body,
                                "created_response": created,
                                "poll_responses": polls,
                                "nudges": nudges,
                                "error": str(error),
                            },
                        )
                        raise error
                    nudge = (
                        "Proceed fully autonomously now. Do not ask for user input or "
                        "confirmation; finish the task and emit the requested structured output."
                    )
                    try:
                        nudge_response = self.session.post(
                            f"{self.base_url}/session/{session_id}/message",
                            headers=headers,
                            json={"message": nudge},
                            timeout=60,
                        )
                        nudge_response.raise_for_status()
                        nudge_body = nudge_response.json()
                    except (requests.RequestException, ValueError) as exc:
                        error = DevinBackendError(
                            f"Devin session {session_id} is {status}; autonomous nudge failed: {exc}"
                        )
                        self._record(
                            title,
                            {
                                "backend": "devin",
                                "session_id": session_id,
                                "session_url": self.last_session_url,
                                "request": body,
                                "created_response": created,
                                "poll_responses": polls,
                                "nudges": nudges,
                                "error": str(error),
                            },
                        )
                        raise error from exc
                    nudges.append({"status": status, "request": nudge, "response": nudge_body})
                    nudged = True
                    time.sleep(interval)
                    interval = min(max(interval * 1.5, 0.1), 15.0)
                    continue
                if status in terminal:
                    if status != "completed":
                        error = DevinBackendError(
                            f"Devin session {session_id} ended with status {status}"
                        )
                        self._record(
                            title,
                            {
                                "backend": "devin",
                                "session_id": session_id,
                                "session_url": self.last_session_url,
                                "request": body,
                                "created_response": created,
                                "poll_responses": polls,
                                "nudges": nudges,
                                "error": str(error),
                            },
                        )
                        raise error
                    output = state.get("structured_output")
                    if isinstance(output, str):
                        try:
                            output = json.loads(output)
                        except json.JSONDecodeError as exc:
                            error = DevinBackendError(
                                "Devin structured_output was not JSON"
                            )
                            self._record(
                                title,
                                {
                                    "backend": "devin",
                                    "session_id": session_id,
                                    "session_url": self.last_session_url,
                                    "request": body,
                                    "created_response": created,
                                    "poll_responses": polls,
                                    "nudges": nudges,
                                    "error": str(error),
                                },
                            )
                            raise error from exc
                    if not isinstance(output, dict):
                        error = DevinBackendError(
                            "Devin session completed without structured_output"
                        )
                        self._record(
                            title,
                            {
                                "backend": "devin",
                                "session_id": session_id,
                                "session_url": self.last_session_url,
                                "request": body,
                                "created_response": created,
                                "poll_responses": polls,
                                "nudges": nudges,
                                "error": str(error),
                            },
                        )
                        raise error
                    try:
                        validate(output, schema)
                    except Exception as exc:
                        error = DevinBackendError(
                            f"Devin structured output failed schema validation: {exc}"
                        )
                        self._record(
                            title,
                            {
                                "backend": "devin",
                                "session_id": session_id,
                                "session_url": self.last_session_url,
                                "request": body,
                                "created_response": created,
                                "poll_responses": polls,
                                "nudges": nudges,
                                "structured_output": output,
                                "error": str(error),
                            },
                        )
                        raise error from exc
                    self._record(title, {
                        "backend": "devin",
                        "session_id": session_id,
                        "session_url": self.last_session_url,
                        "request": body,
                        "created_response": created,
                        "poll_responses": polls,
                        "nudges": nudges,
                        "structured_output": output,
                    })
                    return output
                time.sleep(interval)
                interval = min(max(interval * 1.5, 0.1), 15.0)

    def _record(self, title: str, payload: dict) -> None:
        if self.log_callback:
            self.last_log_path = self.log_callback(title.replace(" ", "_"), payload)
            return
        if self.run_dir is None:
            return
        with self._log_lock:
            directory = self.run_dir / "llm"
            directory.mkdir(parents=True, exist_ok=True)
            self._log_sequence += 1
            path = directory / f"{self._log_sequence:04d}_{title.replace(' ', '_')}.json"
            path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
            self.last_log_path = str(path)
