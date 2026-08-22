"""Semantic Scholar Graph API.

Keyless access is heavily rate limited, so failures here are recorded in the
trace and the research agent falls back to its other sources rather than
inventing citations.
"""

from __future__ import annotations

from ..http import HttpError, request
from ..schemas import Document
from .base import Source

API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "paperId,title,abstract,year,venue,url,externalIds"


class SemanticScholarSource(Source):
    name = "semantic_scholar"

    def search(self, query: str, limit: int, iteration: int | None = None) -> list[Document]:
        headers = {}
        if self.config.semantic_scholar_api_key:
            headers["x-api-key"] = self.config.semantic_scholar_api_key
        try:
            response = request(
                API_URL,
                params={"query": query, "limit": limit, "fields": FIELDS},
                headers=headers,
                timeout=self.config.request_timeout,
                retries=3,
                backoff=4.0,
            )
            payload = response.json()
        except (HttpError, ValueError) as exc:
            self._error(query, exc, iteration)
            return []
        documents = []
        for paper in payload.get("data") or []:
            documents.append(
                Document(
                    source=self.name,
                    external_id=paper.get("paperId") or "",
                    title=paper.get("title") or "",
                    url=paper.get("url") or f"https://www.semanticscholar.org/paper/{paper.get('paperId')}",
                    abstract=paper.get("abstract") or "",
                    year=paper.get("year"),
                    venue=paper.get("venue") or "",
                    query=query,
                )
            )
        self._trace(query, response, len(documents), iteration)
        return documents
