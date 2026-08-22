"""arXiv Atom API adapter."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import requests

from .common import get_text, raw_response, record


class ArxivSource:
    name = "arxiv"
    url = "https://export.arxiv.org/api/query"

    def __init__(self, session=None):
        self.session = session or requests.Session()

    def search(self, query: str, *, iteration: int, run_dir, limit: int = 10):
        body = get_text(
            self.session, self.url, params={"search_query": f"all:{query}", "max_results": limit}
        )
        path = raw_response(run_dir, iteration, self.name, body)
        root = ET.fromstring(body)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        results = []
        for entry in root.findall("a:entry", ns):
            abstract = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
            if not abstract:
                continue
            results.append(record(self.name, {
                "id": entry.findtext("a:id", default="", namespaces=ns),
                "title": (entry.findtext("a:title", default="", namespaces=ns) or "").strip(),
                "abstract": abstract,
                "year": (entry.findtext("a:published", default="", namespaces=ns) or "")[:4],
                "url": entry.findtext("a:id", default="", namespaces=ns),
            }, path))
        return results
