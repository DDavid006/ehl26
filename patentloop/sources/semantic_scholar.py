"""Semantic Scholar Graph API adapter."""

from __future__ import annotations

from typing import Any
import requests

from .common import get_json, raw_response, record


class SemanticScholarSource:
    name = "semantic_scholar"
    url = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self, session=None, api_key: str | None = None):
        self.session = session or requests.Session()
        self.api_key = api_key

    def search(self, query: str, *, iteration: int, run_dir, limit: int = 10) -> list[dict[str, Any]]:
        data, body = get_json(
            self.session,
            self.url,
            params={"query": query, "limit": limit, "fields": "title,abstract,year,url,externalIds"},
            headers={"x-api-key": self.api_key} if self.api_key else None,
        )
        path = raw_response(run_dir, iteration, self.name, body)
        results = []
        for item in data.get("data", []):
            if not item.get("abstract"):
                continue
            results.append(
                record(
                    self.name,
                    {
                        "id": (item.get("externalIds") or {}).get("DOI") or item.get("paperId"),
                        "title": item.get("title", ""),
                        "abstract": item["abstract"],
                        "year": item.get("year"),
                        "url": item.get("url"),
                    },
                    path,
                )
            )
        return results
