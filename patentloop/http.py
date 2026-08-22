"""Small stdlib-only HTTP client with retries.

Every external call goes through here so that the raw response of each call can
be handed to the tracer: the scores in a report are only auditable if the bytes
they came from are stored next to them.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

USER_AGENT = "PatentLoop/1.0 (hackathon prior-art agent)"


class HttpError(Exception):
    def __init__(self, url: str, status: int | None, body: str):
        super().__init__(f"{status} for {url}: {body[:300]}")
        self.url = url
        self.status = status
        self.body = body


@dataclass
class Response:
    url: str
    status: int
    body: str
    elapsed_ms: int
    attempts: int = 1
    headers: dict = field(default_factory=dict)

    def json(self) -> Any:
        return json.loads(self.body)


ResponseHook = Callable[[str, Response], None]


def request(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    data: bytes | None = None,
    method: str = "GET",
    timeout: int = 45,
    retries: int = 3,
    backoff: float = 2.0,
    retry_on: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> Response:
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params)}"
    all_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    all_headers.update(headers or {})
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        started = time.time()
        req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode(resp.headers.get_content_charset() or "utf-8", "replace")
                return Response(
                    url=url,
                    status=resp.status,
                    body=body,
                    elapsed_ms=int((time.time() - started) * 1000),
                    attempts=attempt,
                    headers=dict(resp.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            last = HttpError(url, exc.code, body)
            if exc.code not in retry_on or attempt == retries:
                raise last
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = HttpError(url, None, str(exc))
            if attempt == retries:
                raise last
        time.sleep(backoff * attempt)
    raise last if last else HttpError(url, None, "unreachable")


def get_json(url: str, **kwargs) -> tuple[Any, Response]:
    resp = request(url, **kwargs)
    return resp.json(), resp


def post_json(url: str, payload: dict, **kwargs) -> tuple[Any, Response]:
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["Content-Type"] = "application/json"
    resp = request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
        **kwargs,
    )
    return resp.json(), resp
