"""Crossref works API adapter used as an additional literature source."""

from __future__ import annotations

from .common import get_json, raw_response, record
import requests


class CrossrefSource:
    name = "crossref"
    url = "https://api.crossref.org/works"

    def __init__(self, session=None):
        self.session = session or requests.Session()

    def search(self, query: str, *, iteration: int, run_dir, limit: int = 10):
        data, body = get_json(
            self.session, self.url, params={"query": query, "rows": limit}
        )
        path = raw_response(run_dir, iteration, self.name, body)
        results = []
        for item in data.get("message", {}).get("items", []):
            abstract = item.get("abstract", "").replace("<jats:p>", "").replace("</jats:p>", "")
            if not abstract:
                continue
            results.append(record(self.name, {
                "id": item.get("DOI"),
                "title": (item.get("title") or [""])[0],
                "abstract": abstract,
                "year": (item.get("published-print") or item.get("published-online") or {})
                .get("date-parts", [[None]])[0][0],
                "url": item.get("URL"),
            }, path))
        return results
