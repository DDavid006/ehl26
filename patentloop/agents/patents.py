"""Patent Search Agent: prior-art / FTO scan against Google Patents (US/EP/WIPO)."""

from __future__ import annotations

import time
from typing import Any

from ..llm import chat_json
from ..sources import search_patents_any

OVERLAP_SYSTEM = (
    "You are a freedom-to-operate analyst. You are given an idea, its core elements, and REAL "
    "patent publications retrieved live from Google Patents (id, title, abstract snippet). For each patent decide "
    "which specific idea elements its disclosure overlaps. Judge ONLY from the retrieved text. "
    'Return JSON: {"overlap_score": <0-100, 100 = the idea is fully anticipated>, '
    '"matched_patents": [{"patent_id": "...", "title": "...", "assignee": "...", "url": "...", '
    '"overlapping_elements": ["..."], "overlapping_text": "<the abstract fragment that overlaps>"}], '
    '"rationale": "<one paragraph mapping elements to patents>"}. '
    "Include only patents with a real overlap in matched_patents."
)


def run_patent_search(idea: str, extraction: dict[str, Any]) -> dict[str, Any]:
    """Overlap scan. Returns overlap_score, matched patents, raw API responses."""
    # Google Patents rate-limits parallel hits, so queries run sequentially, spaced out.
    element_queries = [extraction["elements"]] + [[q] for q in extraction["search_queries"][:4]]
    per_query = []
    for index, keywords in enumerate(element_queries):
        if index:
            time.sleep(1.5)
        per_query.append({"keywords": keywords, "result": search_patents_any(keywords, limit=8)})

    patents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bundle in per_query:
        for record in bundle["result"]["records"]:
            pid = record.get("patent_id")
            if pid and pid not in seen:
                seen.add(pid)
                patents.append(record)

    corpus = [
        {"patent_id": p.get("patent_id"), "title": p.get("title"), "abstract": p.get("abstract"),
         "assignee": p.get("assignee"), "date": p.get("date"), "url": p.get("url")}
        for p in patents[:30]
    ]
    if corpus:
        verdict = chat_json(
            OVERLAP_SYSTEM,
            f"IDEA:\n{idea}\n\nCORE ELEMENTS: {extraction['elements']}\n\nRETRIEVED PATENTS:\n{corpus}",
        )
    else:
        verdict = {
            "overlap_score": 0,
            "matched_patents": [],
            "rationale": "No patents were retrieved for any element query, so no overlap is evidenced.",
        }
    score = verdict.get("overlap_score")
    if not isinstance(score, (int, float)):
        score = 50
    return {
        "agent": "patent_search",
        "overlap_score": max(0, min(100, int(score))),
        "matched_patents": verdict.get("matched_patents") or [],
        "rationale": verdict.get("rationale") or "",
        "patents_considered": len(patents),
        "records": patents,
        "raw_responses": [
            {"keywords": bundle["keywords"], "google_patents": bundle["result"]["raw"]}
            for bundle in per_query
        ],
    }
