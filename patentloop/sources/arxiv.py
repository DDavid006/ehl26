"""arXiv Atom API (no key required)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ..http import HttpError, request
from ..schemas import Document
from .base import Source

API_URL = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}
_PUNCT = re.compile(r"[^\w\s\-]")


def _clean_query(text: str) -> str:
    return _PUNCT.sub(" ", text).strip()


class ArxivSource(Source):
    name = "arxiv"

    def search(self, query: str, limit: int, iteration: int | None = None) -> list[Document]:
        cleaned = _clean_query(query)
        try:
            response = request(
                API_URL,
                params={
                    "search_query": f'all:"{cleaned}"' if " " in cleaned else f"all:{cleaned}",
                    "start": 0,
                    "max_results": limit,
                    "sortBy": "relevance",
                },
                timeout=self.config.request_timeout,
            )
        except HttpError as exc:
            self._error(query, exc, iteration)
            return []
        try:
            root = ET.fromstring(response.body)
        except ET.ParseError as exc:
            self._error(query, exc, iteration)
            return []
        documents = []
        for entry in root.findall("atom:entry", NS):
            url = (entry.findtext("atom:id", "", NS) or "").strip()
            published = (entry.findtext("atom:published", "", NS) or "")[:4]
            documents.append(
                Document(
                    source=self.name,
                    external_id=url.rsplit("/", 1)[-1],
                    title=" ".join((entry.findtext("atom:title", "", NS) or "").split()),
                    url=url,
                    abstract=" ".join((entry.findtext("atom:summary", "", NS) or "").split()),
                    year=int(published) if published.isdigit() else None,
                    venue="arXiv",
                    query=query,
                )
            )
        self._trace(query, response, len(documents), iteration)
        return documents
