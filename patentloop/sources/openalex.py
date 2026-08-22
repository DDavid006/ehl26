"""OpenAlex works API adapter."""

from __future__ import annotations

from .common import get_json, raw_response, record
import requests


class OpenAlexSource:
    name = "openalex"
    url = "https://api.openalex.org/works"

    def __init__(self, session=None):
        self.session = session or requests.Session()

    def search(self, query: str, *, iteration: int, run_dir, limit: int = 10):
        data, body = get_json(
            self.session,
            self.url,
            params={"search": query, "per-page": limit},
        )
        path = raw_response(run_dir, iteration, self.name, body)
        results = []
        for item in data.get("results", []):
            abstract = item.get("abstract")
            if not abstract and item.get("abstract_inverted_index"):
                words = []
                for word, positions in item["abstract_inverted_index"].items():
                    words.extend((position, word) for position in positions)
                abstract = " ".join(word for _, word in sorted(words))
            if not abstract:
                continue
            results.append(record(self.name, {
                "id": item.get("doi") or item.get("id"),
                "title": item.get("title", ""),
                "abstract": abstract,
                "year": item.get("publication_year"),
                "url": item.get("doi") or item.get("id"),
            }, path))
        return results
