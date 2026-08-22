"""OpenAI-compatible structured chat backend."""

from __future__ import annotations

import json
from typing import Any

import requests
from jsonschema import validate

from ..company import StaffBoard, role_for


class OpenAIBackendError(RuntimeError):
    """Raised when an OpenAI-compatible request fails."""


class OpenAIChatBackend:
    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        model: str,
        *,
        session=None,
        log_callback=None,
        staff_board: StaffBoard | None = None,
    ):
        if not api_key:
            raise OpenAIBackendError(
                "OPENAI_API_KEY is required for PATENTLOOP_BACKEND=openai"
            )
        self.api_key, self.base_url, self.model = api_key, base_url.rstrip("/"), model
        self.session = session or requests.Session()
        self.log_callback = log_callback
        self.staff_board = staff_board
        self.last_log_path = None
        self.last_session_url = None

    def chat(
        self,
        prompt: str,
        json_schema: dict,
        *,
        title="PatentLoop agent",
        agent="agent",
        role=None,
        iteration=None,
        task="Complete the assigned structured-output task.",
        **kwargs,
    ) -> dict[str, Any]:
        assignment_id = None
        if self.staff_board is not None:
            assignment_id = self.staff_board.dispatch(
                agent, task=task, iteration=iteration, role=role
            )
            self.staff_board.running(assignment_id)
        try:
            return self._chat(
                prompt,
                json_schema,
                title=title,
                agent=agent,
                role=role,
                iteration=iteration,
                assignment_id=assignment_id,
            )
        except Exception as exc:
            if assignment_id is not None:
                self.staff_board.failed(assignment_id, str(exc))
            raise

    def _chat(
        self,
        prompt: str,
        json_schema: dict,
        *,
        title,
        agent,
        role,
        iteration,
        assignment_id,
    ) -> dict[str, Any]:
        schema = json_schema.get("schema", json_schema)
        role_title = role or role_for(agent)["title"]
        if iteration is not None:
            title = f"PatentLoop · {role_title} · iteration {iteration}"
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": json_schema.get("name", "response"), "schema": schema},
            },
        }
        try:
            response = self.session.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=90,
            )
            response.raise_for_status()
            data = response.json()
            output = json.loads(data["choices"][0]["message"]["content"])
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            raise OpenAIBackendError(f"OpenAI structured chat failed: {exc}") from exc
        try:
            validate(output, schema)
        except Exception as exc:
            raise OpenAIBackendError(
                f"OpenAI structured output failed schema validation: {exc}"
            ) from exc
        if self.log_callback:
            self.last_log_path = self.log_callback(title.replace(" ", "_"), {
                "backend": "openai", "request": payload, "response": data,
            })
        if assignment_id is not None:
            self.staff_board.completed(assignment_id)
        return output
