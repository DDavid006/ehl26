"""Optional GitHub repository search adapter."""

from __future__ import annotations

from .common import get_json, raw_response, record
import requests


class GitHubSource:
    name = "github"
    url = "https://api.github.com/search/repositories"

    def __init__(self, token: str | None, session=None):
        self.token, self.session = token, session or requests.Session()

    def search(self, query: str, *, iteration: int, run_dir, limit: int = 10):
        if not self.token:
            return []
        data, body = get_json(
            self.session, self.url,
            params={"q": query, "per_page": limit},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        path = raw_response(run_dir, iteration, self.name, body)
        return [record(self.name, {
            "id": row.get("full_name"),
            "title": row.get("name", ""),
            "abstract": row.get("description") or "",
            "url": row.get("html_url"),
        }, path) for row in data.get("items", []) if row.get("description")]
