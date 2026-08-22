"""Google Patents full-text search plus claim retrieval.

Two live endpoints are used: the public ``/xhr/query`` search endpoint for
ranked hits, and the patent page itself for the granted claim text (the claims
are what the overlap score is computed against, so they must be fetched, never
paraphrased from memory).
"""

from __future__ import annotations

import html
import re
import urllib.parse

from ..http import HttpError, request
from ..schemas import PatentHit
from .base import Source

SEARCH_URL = "https://patents.google.com/xhr/query"
PATENT_URL = "https://patents.google.com/patent/{number}/en"

_TAGS = re.compile(r"<[^>]+>")
_CLAIM = re.compile(r'<div class="claim-text">(.*?)</div>', re.DOTALL)
_ABSTRACT = re.compile(r'<meta name="description" content="([^"]*)"')
_ASSIGNEE = re.compile(r'<dd itemprop="assigneeSearch"[^>]*>\s*(?:<[^>]+>)*\s*([^<]+)')
_DATE = re.compile(r'<time itemprop="priorityDate">([^<]+)</time>')


def _strip(text: str) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", text)).split())


class GooglePatentsSource(Source):
    name = "google_patents"
    agent = "patent_search"

    def search(self, query: str, limit: int, iteration: int | None = None) -> list[PatentHit]:
        encoded = urllib.parse.urlencode({"q": query})
        try:
            response = request(
                SEARCH_URL,
                params={"url": encoded, "exp": ""},
                timeout=self.config.request_timeout,
            )
            payload = response.json()
        except (HttpError, ValueError) as exc:
            self._error(query, exc, iteration)
            return []
        hits: list[PatentHit] = []
        for cluster in (payload.get("results") or {}).get("cluster") or []:
            for item in cluster.get("result") or []:
                patent = item.get("patent") or {}
                number = (item.get("id") or "").split("/")
                publication_number = number[1] if len(number) > 1 else (patent.get("publication_number") or "")
                if not publication_number:
                    continue
                hits.append(
                    PatentHit(
                        source=self.name,
                        publication_number=publication_number,
                        title=_strip(patent.get("title") or ""),
                        url=f"https://patents.google.com/patent/{publication_number}/en",
                        assignee=_strip(patent.get("assignee") or ""),
                        date=patent.get("priority_date") or patent.get("publication_date") or "",
                        abstract=_strip(patent.get("snippet") or ""),
                        query=query,
                    )
                )
                if len(hits) >= limit:
                    break
            if len(hits) >= limit:
                break
        self._trace(query, response, len(hits), iteration)
        return hits

    def fetch_claims(self, hit: PatentHit, max_claims: int = 6, iteration: int | None = None) -> PatentHit:
        """Populate ``hit.claims`` from the live patent page."""

        url = PATENT_URL.format(number=hit.publication_number)
        try:
            response = request(url, timeout=self.config.request_timeout)
        except HttpError as exc:
            self._error(f"claims:{hit.publication_number}", exc, iteration)
            return hit
        body = response.body
        claims = [_strip(c) for c in _CLAIM.findall(body)]
        claims = [c for c in claims if len(c) > 40][:max_claims]
        hit.claims = claims
        if not hit.abstract:
            abstract = _ABSTRACT.search(body)
            if abstract:
                hit.abstract = _strip(abstract.group(1))
        if not hit.assignee:
            assignee = _ASSIGNEE.search(body)
            if assignee:
                hit.assignee = _strip(assignee.group(1))
        if not hit.date:
            date = _DATE.search(body)
            if date:
                hit.date = date.group(1)
        self.tracer.api_call(
            self.agent,
            f"{self.name}_claims",
            hit.publication_number,
            response,
            iteration,
            len(claims),
        )
        return hit
