"""EPO Open Patent Services (EP + WIPO coverage).

Requires a free registered consumer key/secret pair; when they are absent the
source declares itself unavailable and the trace says so, which is why an EP/WO
gap in a report is visible rather than silent.
"""

from __future__ import annotations

import base64
import json
import time

from ..http import HttpError, request
from ..schemas import PatentHit
from .base import Source

AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search/biblio"


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("$", ""))
    if isinstance(value, list):
        return " ".join(_text(v) for v in value)
    return str(value or "")


class EpoOpsSource(Source):
    name = "epo_ops"
    agent = "patent_search"

    def __init__(self, config, tracer):
        super().__init__(config, tracer)
        self._token: str | None = None
        self._token_expiry = 0.0

    @property
    def available(self) -> bool:
        return bool(self.config.epo_ops_key and self.config.epo_ops_secret)

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expiry:
            return self._token
        credentials = base64.b64encode(
            f"{self.config.epo_ops_key}:{self.config.epo_ops_secret}".encode()
        ).decode()
        response = request(
            AUTH_URL,
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
            timeout=self.config.request_timeout,
        )
        payload = json.loads(response.body)
        self._token = payload["access_token"]
        self._token_expiry = time.time() + int(payload.get("expires_in", 1200)) - 60
        return self._token

    def search(self, query: str, limit: int, iteration: int | None = None) -> list[PatentHit]:
        if not self.available:
            self.tracer.api_error(
                self.agent, self.name, query, "EPO_OPS_KEY/EPO_OPS_SECRET not set; source skipped", iteration
            )
            return []
        try:
            token = self._access_token()
            response = request(
                SEARCH_URL,
                params={"q": f'ti%3D"{query}" or ab%3D"{query}"', "Range": f"1-{limit}"},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=self.config.request_timeout,
            )
            payload = response.json()
        except (HttpError, ValueError, KeyError) as exc:
            self._error(query, exc, iteration)
            return []
        result = (
            payload.get("ops:world-patent-data", {})
            .get("ops:biblio-search", {})
            .get("ops:search-result", {})
        )
        hits = []
        for document in _as_list(result.get("exchange-documents"))[:limit]:
            doc = document.get("exchange-document") if isinstance(document, dict) else None
            if not doc:
                continue
            number = f"{doc.get('@country', '')}{doc.get('@doc-number', '')}{doc.get('@kind', '')}"
            biblio = doc.get("bibliographic-data") or {}
            titles = _as_list((biblio.get("invention-title")))
            applicants = (biblio.get("parties") or {}).get("applicants") or {}
            hits.append(
                PatentHit(
                    source=self.name,
                    publication_number=number,
                    title=_text(titles[0]) if titles else "",
                    url=f"https://worldwide.espacenet.com/patent/search?q={number}",
                    assignee=_text(_as_list(applicants.get("applicant"))[:1]),
                    date=_text((biblio.get("publication-reference") or {}).get("document-id")),
                    abstract=_text(doc.get("abstract")),
                    query=query,
                )
            )
        self._trace(query, response, len(hits), iteration)
        return hits
