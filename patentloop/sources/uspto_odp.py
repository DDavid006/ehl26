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
        if not isinstance(data, dict):
            return []
        rows = (
            data.get("results")
            or data.get("data")
            or data.get("items")
            or data.get("patentApplications")
            or []
        )
        if isinstance(rows, dict):
            rows = rows.get("results") or rows.get("items") or []
        results = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            claims = (
                item.get("claims")
                or item.get("claimText")
                or item.get("claimsText")
                or item.get("claim")
                or ""
            )
            if isinstance(claims, list):
                claims = " ".join(
                    value.get("text", "") if isinstance(value, dict) else str(value)
                    for value in claims
                )
            if isinstance(claims, dict):
                claims = claims.get("text") or claims.get("claimText") or ""
            normalized = {
                "id": (
                    item.get("patentId")
                    or item.get("publicationNumber")
                    or item.get("patentPublicationNumber")
                    or item.get("applicationNumber")
                    or item.get("patentApplicationNumber")
                ),
                "title": item.get("title") or item.get("inventionTitle") or "",
                "abstract": item.get("abstract") or item.get("abstractText") or "",
                "claims": claims,
                "claim1": claims,
                "url": item.get("url") or item.get("link"),
                "year": (
                    item.get("filingDate")
                    or item.get("publicationDate")
                    or item.get("grantDate")
                ),
            }
            if normalized["id"]:
                results.append(record(self.name, normalized, path))
        return results
