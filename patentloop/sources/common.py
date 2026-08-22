"""Shared HTTP and raw-response persistence helpers."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import requests


def raw_response(
    run_dir: Path | str,
    iteration: int,
    source: str,
    body: Any,
) -> str:
    directory = Path(run_dir) / "raw" / str(iteration)
    directory.mkdir(parents=True, exist_ok=True)
    encoded = body if isinstance(body, str) else json.dumps(
        body, indent=2, ensure_ascii=False, default=str
    )
    digest = hashlib.sha256(encoded.encode()).hexdigest()[:12]
    path = directory / f"{source}_{digest}.json"
    path.write_text(encoded + "\n")
    return str(path)


def get_json(
    session: requests.Session | Any,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 3,
) -> tuple[Any, str]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json(), response.text
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"source request failed after retries: {last_error}")


def get_text(
    session: requests.Session | Any,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 3,
) -> str:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"source request failed after retries: {last_error}")


def record(
    source: str,
    item: dict[str, Any],
    raw_path: str,
) -> dict[str, Any]:
    item = dict(item)
    item["source"] = source
    item["raw_path"] = raw_path
    return item
