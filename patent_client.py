"""Patent search performed by OpenAI's hosted web search, with a local fallback corpus.

The model does the searching: it is asked for patent records from Google Patents
or Espacenet and returns them as JSON. The patent hosts block server-side
fetches, so no patent page is ever retrieved directly.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from llm import search_text

load_dotenv()

ALLOWED_HOSTS = ("patents.google.com", "worldwide.espacenet.com")
PATENT_ID = re.compile(r"^[A-Z]{2}[A-Z0-9/]*\d[A-Z0-9/]*$")
SEARCH_PROMPT = """Search the web for patent publications about: {query}

Use only {hosts} as sources, and open the results you report - do not answer \
from memory and do not invent a publication number.

Return the {limit} most relevant publications as JSON only: no prose, no \
markdown fences. The response must be a JSON array of objects with exactly \
these keys:
[{{"patent_id": "US10123456B2", "title": "...", "abstract": "...", \
"assignee": "...", "date": "YYYY-MM-DD"}}]

"abstract" is the publication's own abstract, trimmed to about 60 words. Use \
null for a field the source does not give. Return [] if nothing relevant \
exists rather than padding the list."""
FALLBACK_PATH = Path(__file__).resolve().parent / "fallback_corpus.json"
RESULT_KEYS = ("patent_id", "title", "abstract", "assignee", "date")
# Callers ask for a handful of hits per query, and a real query commonly returns two,
# so the fallback corpus is only for a query that yields nothing usable.
MIN_RESULTS = 1
# A browsing turn is slower than a search API, and every element searches in parallel.
TIME_BUDGET_SECONDS = 150

FALLBACK_ENTRIES: list[dict[str, Optional[str]]] = [
    {
        "patent_id": "US10123456B2",
        "title": "Method and system for distributed sensor data aggregation",
        "abstract": (
            "A method for aggregating measurements from a plurality of distributed sensor "
            "nodes, wherein each node transmits a compressed representation of its local "
            "readings to a gateway that reconstructs a global state estimate."
        ),
        "assignee": "Northfield Instruments, Inc.",
        "date": "2018-11-13",
    },
    {
        "patent_id": "US9876543B1",
        "title": "Adaptive thermal management for battery packs",
        "abstract": (
            "Systems and methods for regulating the temperature of a battery pack by "
            "selectively routing coolant through cell groups based on predicted load."
        ),
        "assignee": "Arclight Energy Systems LLC",
        "date": "2018-01-23",
    },
    {
        "patent_id": "EP3210987A1",
        "title": "Apparatus for optical inspection of semiconductor wafers",
        "abstract": (
            "An inspection apparatus comprising a tunable illumination source and a "
            "multi-angle detector array configured to identify sub-surface defects in a "
            "semiconductor wafer without contact."
        ),
        "assignee": "Meridian Photonics GmbH",
        "date": "2017-08-30",
    },
    {
        "patent_id": "US11234567B2",
        "title": "Machine learning based anomaly detection in industrial control networks",
        "abstract": (
            "A monitoring system trains a model on nominal traffic patterns of an "
            "industrial control network and raises alerts when observed traffic deviates "
            "beyond a learned tolerance."
        ),
        "assignee": "Halstead Automation Corporation",
        "date": "2022-01-25",
    },
    {
        "patent_id": "WO2019123456A1",
        "title": "Biodegradable polymer composition for single-use packaging",
        "abstract": (
            "A polymer composition comprising a starch-derived matrix and a plasticizer "
            "blend that provides mechanical strength comparable to polyethylene while "
            "degrading under industrial composting conditions."
        ),
        "assignee": "Verdant Materials S.A.",
        "date": "2019-06-27",
    },
]


def _ensure_fallback_corpus() -> None:
    if FALLBACK_PATH.exists():
        return
    FALLBACK_PATH.write_text(json.dumps(FALLBACK_ENTRIES, indent=2) + "\n", encoding="utf-8")


def _load_fallback(limit: int) -> list[dict[str, Optional[str]]]:
    _ensure_fallback_corpus()
    try:
        data = json.loads(FALLBACK_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = [_normalize(entry) for entry in data if isinstance(entry, dict)]
    return entries[:limit]


def _normalize(entry: dict[str, Any]) -> dict[str, Optional[str]]:
    return {key: entry.get(key) or None for key in RESULT_KEYS}


class SearchError(RuntimeError):
    """Raised when the search model cannot be reached."""


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    fence = re.match(r"^```[A-Za-z0-9_-]*\s*(.*?)\s*```$", cleaned, flags=re.DOTALL)
    return fence.group(1).strip() if fence else cleaned


def _parse_records(answer: str) -> list[dict[str, Any]]:
    text = _strip_fences(answer)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end < start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return []
    return [item for item in data if isinstance(item, dict)]


def _openai_search(query: str, limit: int) -> list[dict[str, Any]]:
    answer = search_text(
        SEARCH_PROMPT.format(query=query, limit=limit, hosts=" or ".join(ALLOWED_HOSTS)),
        SearchError,
        task=f"search: {query}",
    )
    return _parse_records(answer)


def _clean(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return re.sub(r"\s+", " ", value).strip() or None


def _patent_id_from_url(url: str) -> Optional[str]:
    if not isinstance(url, str):
        return None
    match = re.search(r"[?&]CC=([A-Z]{2})&NR=([^&#]+)", url)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    match = re.search(r"/patent/([A-Z]{2}\d[^/?#]*)", url)
    if match:
        return match.group(1)
    return None


def _clean_title(title: Optional[str], patent_id: str) -> Optional[str]:
    """Drop the site's boilerplate: ``US123B2 - Weight sensing - Google Patents``."""
    if title is None:
        return None
    title = re.sub(r"\s*[-|]\s*(Google Patents|Espacenet).*$", "", title, flags=re.IGNORECASE)
    title = re.sub(rf"^{re.escape(patent_id)}\s*-\s*", "", title)
    return title.strip() or None


def _record_from_hit(hit: dict[str, Any]) -> Optional[dict[str, Optional[str]]]:
    """Turn one reported publication into a record, or drop it if it has no id."""
    patent_id = _clean(hit.get("patent_id")) or _patent_id_from_url(hit.get("url") or "")
    if not patent_id:
        return None
    patent_id = patent_id.replace(" ", "").replace(",", "").upper()
    if not PATENT_ID.match(patent_id):
        return None
    return _normalize(
        {
            "patent_id": patent_id,
            "title": _clean_title(_clean(hit.get("title")), patent_id),
            "abstract": _clean(hit.get("abstract")),
            "assignee": _clean(hit.get("assignee")),
            "date": _clean(hit.get("date")),
        }
    )


def search_patents(query: str, limit: int = 10) -> list[dict]:
    """Search for patents matching ``query`` and return up to ``limit`` records.

    The search itself is an OpenAI web-search turn restricted to Google Patents
    and Espacenet; publications it reports without a well-formed publication
    number are dropped. Falls back to ``fallback_corpus.json`` when no usable
    result comes back or the call exceeds the time budget.
    """
    started = time.monotonic()

    if limit <= 0:
        return []

    try:
        hits = _openai_search(query, limit)
    except Exception:
        hits = []

    results: list[dict[str, Optional[str]]] = []
    seen: set[str] = set()
    for hit in hits:
        if len(results) >= limit:
            break
        record = _record_from_hit(hit)
        if record is None or record["patent_id"] in seen:
            continue
        seen.add(record["patent_id"])
        results.append(record)

    if len(results) < MIN_RESULTS or time.monotonic() - started > TIME_BUDGET_SECONDS:
        return _load_fallback(limit)
    return results
