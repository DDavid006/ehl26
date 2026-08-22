"""USPTO Open Data Portal patent full-text/claim search adapter."""

from __future__ import annotations

from typing import Any
import requests

from .common import get_json, raw_response, record


class USPTOODPSource:
    name = "uspto_odp"
    url = "https://api.uspto.gov/api/v1/patent/applications/search"

    def __init__(self, api_key: str | None, session=None, url: str | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.url = url or self.url

    def search(self, keywords: list[str], *, iteration: int, run_dir, limit: int = 25):
        if not self.api_key:
            raise RuntimeError("USPTO_ODP_API_KEY is required for patent search")
        query = " OR ".join(f'"{word}"' for word in keywords if word)
        data, body = get_json(
            self.session,
            self.url,
            params={"q": query, "limit": limit},
            headers={"X-API-KEY": self.api_key, "Accept": "application/json"},
        )
        path = raw_response(run_dir, iteration, self.name, body)
        rows = data.get("results") or data.get("data") or []
        results = []
        for item in rows:
            claims = item.get("claims") or item.get("claimText") or item.get("claimsText") or ""
            if isinstance(claims, list):
                claims = " ".join(str(value) for value in claims)
            results.append(record(self.name, {
                "id": item.get("patentId") or item.get("publicationNumber") or item.get("applicationNumber"),
                "title": item.get("title", ""),
                "abstract": item.get("abstract", ""),
                "claims": claims,
                "claim1": claims,
                "url": item.get("url") or item.get("link"),
                "year": item.get("filingDate") or item.get("publicationDate"),
            }, path))
        return results
