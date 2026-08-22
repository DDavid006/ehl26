"""USPTO PatentsView Search API (https://search.patentsview.org).

PatentsView now gates its API behind a free registered key; without
``PATENTSVIEW_API_KEY`` the source reports itself unavailable so the run falls
back to Google Patents full text instead of pretending it searched USPTO.
Granted claim text comes from the ``g_claim`` endpoint.
"""

from __future__ import annotations

import json

from ..http import HttpError, request
from ..schemas import PatentHit
from .base import Source

PATENT_URL = "https://search.patentsview.org/api/v1/patent/"
CLAIM_URL = "https://search.patentsview.org/api/v1/g_claim/"


class PatentsViewSource(Source):
    name = "patentsview"
    agent = "patent_search"

    @property
    def available(self) -> bool:
        return bool(self.config.patentsview_api_key)

    def _headers(self) -> dict:
        return {"X-Api-Key": self.config.patentsview_api_key or ""}

    def search(self, query: str, limit: int, iteration: int | None = None) -> list[PatentHit]:
        if not self.available:
            self.tracer.api_error(
                self.agent, self.name, query, "PATENTSVIEW_API_KEY not set; source skipped", iteration
            )
            return []
        params = {
            "q": json.dumps({"_text_any": {"patent_title": query, "patent_abstract": query}}),
            "f": json.dumps(
                [
                    "patent_id",
                    "patent_title",
                    "patent_abstract",
                    "patent_date",
                    "assignees.assignee_organization",
                ]
            ),
            "o": json.dumps({"size": limit}),
        }
        try:
            response = request(
                PATENT_URL, params=params, headers=self._headers(), timeout=self.config.request_timeout
            )
            payload = response.json()
        except (HttpError, ValueError) as exc:
            self._error(query, exc, iteration)
            return []
        hits = []
        for patent in payload.get("patents") or []:
            assignees = patent.get("assignees") or []
            number = patent.get("patent_id") or ""
            hits.append(
                PatentHit(
                    source=self.name,
                    publication_number=f"US{number}",
                    title=patent.get("patent_title") or "",
                    url=f"https://patents.google.com/patent/US{number}/en",
                    assignee=(assignees[0].get("assignee_organization") if assignees else "") or "",
                    date=patent.get("patent_date") or "",
                    abstract=patent.get("patent_abstract") or "",
                    query=query,
                )
            )
        self._trace(query, response, len(hits), iteration)
        return hits

    def fetch_claims(self, hit: PatentHit, max_claims: int = 6, iteration: int | None = None) -> PatentHit:
        if not self.available:
            return hit
        patent_id = hit.publication_number.removeprefix("US")
        params = {
            "q": json.dumps({"patent_id": patent_id}),
            "f": json.dumps(["claim_sequence", "claim_text", "claim_dependent"]),
            "o": json.dumps({"size": max_claims}),
        }
        try:
            response = request(
                CLAIM_URL, params=params, headers=self._headers(), timeout=self.config.request_timeout
            )
            payload = response.json()
        except (HttpError, ValueError) as exc:
            self._error(f"claims:{hit.publication_number}", exc, iteration)
            return hit
        claims = [
            " ".join((claim.get("claim_text") or "").split())
            for claim in payload.get("g_claims") or []
        ]
        hit.claims = [c for c in claims if c][:max_claims]
        self.tracer.api_call(
            self.agent, f"{self.name}_claims", hit.publication_number, response, iteration, len(hit.claims)
        )
        return hit
