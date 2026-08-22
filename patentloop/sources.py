"""Live external data sources: Semantic Scholar, arXiv, GitHub, USPTO PatentsView.

Every function returns plain dicts plus the raw API payload so runs can store
exactly what was retrieved.
"""

from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from typing import Any

import requests

REQUEST_TIMEOUT = 30
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
ARXIV_URL = "http://export.arxiv.org/api/query"
GITHUB_URL = "https://api.github.com/search/repositories"
GOOGLE_PATENTS_URL = "https://patents.google.com/xhr/query"
ATOM = "{http://www.w3.org/2005/Atom}"


def _get(url: str, *, params: dict | None = None, headers: dict | None = None,
         retries: int = 2, backoff: float = 2.0) -> requests.Response:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            if response.status_code in (429, 503) and attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
            return response
        except requests.RequestException as exc:
            last = exc
            time.sleep(backoff)
    raise RuntimeError(f"request to {url} failed: {last}")


def search_semantic_scholar(query: str, limit: int = 5) -> dict[str, Any]:
    """Papers matching ``query``: {"records": [...], "raw": <api payload>}."""
    response = _get(
        SEMANTIC_SCHOLAR_URL,
        params={"query": query, "limit": limit, "fields": "title,abstract,year,url,citationCount"},
    )
    if response.status_code != 200:
        return {"records": [], "raw": {"error": f"{response.status_code}: {response.text[:200]}"}}
    payload = response.json()
    records = [
        {
            "source": "semantic_scholar",
            "title": item.get("title"),
            "abstract": (item.get("abstract") or "")[:1200],
            "year": item.get("year"),
            "url": item.get("url"),
        }
        for item in payload.get("data") or []
    ]
    return {"records": records, "raw": payload}


def search_arxiv(query: str, limit: int = 5) -> dict[str, Any]:
    response = _get(
        ARXIV_URL,
        params={"search_query": f"all:{query}", "max_results": limit},
    )
    if response.status_code != 200:
        return {"records": [], "raw": {"error": f"{response.status_code}: {response.text[:200]}"}}
    records = []
    try:
        root = ET.fromstring(response.text)
        for entry in root.findall(f"{ATOM}entry"):
            title = (entry.findtext(f"{ATOM}title") or "").strip()
            summary = (entry.findtext(f"{ATOM}summary") or "").strip()
            link = entry.findtext(f"{ATOM}id") or ""
            published = (entry.findtext(f"{ATOM}published") or "")[:10]
            records.append(
                {
                    "source": "arxiv",
                    "title": title,
                    "abstract": summary[:1200],
                    "year": published[:4] or None,
                    "url": link,
                }
            )
    except ET.ParseError:
        pass
    return {"records": records, "raw": {"atom": response.text[:20000]}}


def search_github(query: str, limit: int = 5) -> dict[str, Any]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = _get(
        GITHUB_URL,
        params={"q": query, "per_page": limit, "sort": "stars"},
        headers=headers,
    )
    if response.status_code != 200:
        return {"records": [], "raw": {"error": f"{response.status_code}: {response.text[:200]}"}}
    payload = response.json()
    records = [
        {
            "source": "github",
            "title": item.get("full_name"),
            "abstract": (item.get("description") or "")[:600],
            "year": (item.get("created_at") or "")[:4] or None,
            "url": item.get("html_url"),
        }
        for item in payload.get("items") or []
    ]
    return {"records": records, "raw": {"total_count": payload.get("total_count"), "items": payload.get("items", [])[:limit]}}


def search_patents(keywords: list[str], limit: int = 10) -> dict[str, Any]:
    """Patent full-text search via Google Patents' public JSON endpoint.

    Covers US, EP and WIPO publications. The USPTO PatentsView search API
    (search.patentsview.org) was the first choice but its hostname no longer
    resolves (the service was retired), so Google Patents is the live source.
    """
    query = " ".join(keywords)
    response = _get(
        GOOGLE_PATENTS_URL,
        params={"url": f"q={query}", "exp": ""},
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) PatentLoop/1.0"},
    )
    if response.status_code != 200:
        return {"records": [], "raw": {"error": f"{response.status_code}: {response.text[:300]}"}}
    try:
        payload = response.json()
    except ValueError:
        return {"records": [], "raw": {"error": f"non-JSON response: {response.text[:300]}"}}

    records = []
    clusters = ((payload.get("results") or {}).get("cluster")) or []
    for cluster in clusters:
        for item in cluster.get("result") or []:
            patent = item.get("patent") or {}
            raw_id = item.get("id") or ""  # e.g. "patent/US1234567B2/en"
            parts = raw_id.split("/")
            patent_id = parts[1] if len(parts) > 1 else raw_id
            records.append(
                {
                    "source": "google_patents",
                    "patent_id": patent_id,
                    "title": _strip_html(patent.get("title") or ""),
                    "abstract": _strip_html(patent.get("snippet") or "")[:1500],
                    "date": patent.get("publication_date") or patent.get("grant_date"),
                    "assignee": _strip_html(patent.get("assignee") or "") or None,
                    "url": f"https://patents.google.com/patent/{patent_id}",
                }
            )
            if len(records) >= limit:
                break
        if len(records) >= limit:
            break
    raw = {"total_num_results": (payload.get("results") or {}).get("total_num_results"),
           "cluster": clusters[:1]}
    return {"records": records, "raw": raw}


SERPER_URL = "https://google.serper.dev/search"


def _search_patents_serper(query: str, limit: int) -> dict[str, Any]:
    """Serper web search restricted to patents.google.com (needs SERPER_API_KEY)."""
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return {"records": [], "raw": {"provider": "serper", "error": "no SERPER_API_KEY"}}
    try:
        response = requests.post(
            SERPER_URL,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            # Free-tier Serper rejects "site:" operators, so search "<query> patent"
            # and keep only patents.google.com results.
            json={"q": f"{query} patent", "num": min(max(limit * 5, 20), 100)},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return {"records": [], "raw": {"provider": "serper", "error": str(exc)}}
    if response.status_code != 200:
        return {"records": [], "raw": {"provider": "serper",
                                       "error": f"{response.status_code}: {response.text[:200]}"}}
    payload = response.json()
    records = []
    seen: set[str] = set()
    for item in payload.get("organic") or []:
        url = item.get("link") or ""
        match = re.search(r"patents\.google\.com/patent/([A-Z]{2}[A-Z0-9]+)", url)
        if not match or match.group(1) in seen:
            continue
        patent_id = match.group(1)
        seen.add(patent_id)
        title = item.get("title") or ""
        title = re.sub(rf"^{re.escape(patent_id)}\s*-\s*", "", title)
        title = re.sub(r"\s*-\s*Google Patents.*$", "", title)
        records.append(
            {
                "source": "serper_google_patents",
                "patent_id": patent_id,
                "title": title.strip(),
                "abstract": (item.get("snippet") or "")[:1500],
                "date": None,
                "assignee": None,
                "url": f"https://patents.google.com/patent/{patent_id}",
            }
        )
        if len(records) >= limit:
            break
    return {"records": records, "raw": {"provider": "serper", "organic": payload.get("organic")}}


def search_patents_any(keywords: list[str], limit: int = 10) -> dict[str, Any]:
    """Serper (if keyed) first, then Google Patents direct, then DuckDuckGo-scoped search."""
    query = " ".join(keywords)
    if os.getenv("SERPER_API_KEY"):
        serper = _search_patents_serper(query, limit)
        if serper["records"]:
            return serper
    result = search_patents(keywords, limit)
    if result["records"]:
        return result
    fallback = _search_patents_ddg(query, limit)
    if not fallback["records"]:
        words = query.split()
        if len(words) > 3:
            fallback = _search_patents_ddg(" ".join(words[:3]), limit)
    fallback["raw"] = {"google_patents_direct": result["raw"], **fallback["raw"]}
    return fallback


DDG_URL = "https://html.duckduckgo.com/html/"
BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _search_patents_ddg(query: str, limit: int) -> dict[str, Any]:
    """Fallback: DuckDuckGo web search restricted to patents.google.com.

    Records are built from the result titles and snippets; ids are parsed out
    of the result URLs. Used when Google Patents rate-limits direct queries.
    """
    try:
        response = requests.post(
            DDG_URL,
            data={"q": f"site:patents.google.com {query}"},
            headers={"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"},
            timeout=25,
        )
    except requests.RequestException as exc:
        return {"records": [], "raw": {"provider": "duckduckgo", "error": str(exc)}}
    if response.status_code != 200:
        return {"records": [], "raw": {"provider": "duckduckgo",
                                       "error": f"{response.status_code}: {response.text[:200]}"}}
    html = response.text
    records = []
    seen: set[str] = set()
    raw_hits = []
    for match in re.finditer(
        r'class="result__a" href="(https://patents\.google\.com/patent/([A-Z]{2}[A-Z0-9]+)[^"]*)"[^>]*>(.*?)</a>(.*?)(?=class="result__a"|$)',
        html, re.DOTALL,
    ):
        url, patent_id, title, block = match.groups()
        if patent_id in seen:
            continue
        seen.add(patent_id)
        snippet_match = re.search(
            r'class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)
        snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
        title = _strip_html(title)
        title = re.sub(rf"^{re.escape(patent_id)}\s*-\s*", "", title)
        title = re.sub(r"\s*-\s*Google Patents.*$", "", title)
        raw_hits.append({"url": url, "title": title, "snippet": snippet})
        records.append(
            {
                "source": "duckduckgo_google_patents",
                "patent_id": patent_id,
                "title": title,
                "abstract": snippet[:1500],
                "date": None,
                "assignee": None,
                "url": f"https://patents.google.com/patent/{patent_id}",
            }
        )
        if len(records) >= limit:
            break
    return {"records": records, "raw": {"provider": "duckduckgo", "hits": raw_hits}}


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&hellip;", "…").replace("&amp;", "&").replace("&quot;", '"')
    return re.sub(r"\s+", " ", text).strip()
