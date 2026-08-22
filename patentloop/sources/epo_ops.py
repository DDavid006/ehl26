"""Optional EPO OPS adapter (enabled only when OAuth credentials exist)."""

from __future__ import annotations

import base64
import requests

from .common import get_json, raw_response, record


class EPOOPSSource:
    name = "epo_ops"
    url = "https://ops.epo.org/3.2/rest-services/published-data/search"

    def __init__(self, key: str | None, secret: str | None, session=None):
        self.key, self.secret, self.session = key, secret, session or requests.Session()

    def search(self, keywords: list[str], *, iteration: int, run_dir, limit: int = 25):
        if not self.key or not self.secret:
            return []
        token = base64.b64encode(f"{self.key}:{self.secret}".encode()).decode()
        data, body = get_json(
            self.session,
            self.url,
            params={"q": " OR ".join(keywords), "Range": f"1-{limit}"},
            headers={"Authorization": f"Basic {token}"},
        )
        path = raw_response(run_dir, iteration, self.name, body)
        rows = data.get("results", {}).get("result", []) if isinstance(data, dict) else []
        return [record(self.name, {
            "id": row.get("id"),
            "title": row.get("title", ""),
            "abstract": row.get("abstract", ""),
            "claims": row.get("claims", ""),
            "url": row.get("url"),
        }, path) for row in rows]
