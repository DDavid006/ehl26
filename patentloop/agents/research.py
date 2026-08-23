"""Research Agent: novelty scan against Semantic Scholar, arXiv and GitHub."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..llm import chat_json
from ..sources import search_arxiv, search_github, search_products, search_semantic_scholar

EXTRACT_SYSTEM = (
    "You are a patent analyst. Extract the 3-6 core technical elements of the idea. "
    "Each element is a short noun phrase naming a concrete mechanism, structure or method step. "
    'Return JSON: {"field": "<technical field>", "elements": ["...", ...], '
    '"search_queries": ["<2-5 word literature search query per element>", ...]}. '
    "search_queries must align 1:1 with elements."
)

SCORE_SYSTEM = (
    "You are a novelty examiner. You are given an idea, its core elements, and REAL retrieved "
    "documents (title + abstract + url): academic publications, code repositories, AND existing "
    "commercial products/solutions found on the web (source 'web_product'). Judge how novel the "
    "idea is relative ONLY to these retrieved documents - never from memory. An existing product "
    "that already does what the idea describes counts against novelty just as much as a paper. "
    'Return JSON: {"novelty_score": <0-100, 100 = nothing retrieved resembles the idea>, '
    '"closest_prior_work": [{"title": "...", "url": "...", "why_similar": "..."}], '
    '"rationale": "<one paragraph citing the retrieved titles>"}'
)


def extract_elements(idea: str) -> dict[str, Any]:
    result = chat_json(EXTRACT_SYSTEM, idea)
    elements = [e for e in result.get("elements") or [] if isinstance(e, str)][:6]
    queries = [q for q in result.get("search_queries") or [] if isinstance(q, str)][: len(elements)]
    while len(queries) < len(elements):
        queries.append(elements[len(queries)])
    return {"field": result.get("field") or "technology", "elements": elements, "search_queries": queries}


def run_research(idea: str, extraction: dict[str, Any]) -> dict[str, Any]:
    """Novelty scan. Returns scores, citations, and every raw API response."""
    queries = extraction["search_queries"] or [idea[:80]]

    def fetch(query: str) -> dict[str, Any]:
        return {
            "query": query,
            "semantic_scholar": search_semantic_scholar(query),
            "arxiv": search_arxiv(query, limit=3),
            "github": search_github(query, limit=3),
            "products": search_products(query, limit=3),
        }

    with ThreadPoolExecutor(max_workers=min(len(queries), 6)) as pool:
        per_query = list(pool.map(fetch, queries))

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bundle in per_query:
        for source in ("semantic_scholar", "arxiv", "github", "products"):
            for record in bundle[source]["records"]:
                key = record.get("url") or record.get("title") or ""
                if key and key not in seen:
                    seen.add(key)
                    records.append(record)

    corpus = [
        {"title": r.get("title"), "abstract": r.get("abstract"), "url": r.get("url"), "source": r.get("source")}
        for r in records[:40]
    ]
    verdict = chat_json(
        SCORE_SYSTEM,
        f"IDEA:\n{idea}\n\nCORE ELEMENTS: {extraction['elements']}\n\nRETRIEVED DOCUMENTS:\n{corpus}",
    )
    score = verdict.get("novelty_score")
    if not isinstance(score, (int, float)):
        score = 50
    return {
        "agent": "research",
        "novelty_score": max(0, min(100, int(score))),
        "closest_prior_work": verdict.get("closest_prior_work") or [],
        "rationale": verdict.get("rationale") or "",
        "documents_considered": len(records),
        "records": records,
        "raw_responses": [
            {
                "query": bundle["query"],
                "semantic_scholar": bundle["semantic_scholar"]["raw"],
                "arxiv": bundle["arxiv"]["raw"],
                "github": bundle["github"]["raw"],
                "products": bundle["products"]["raw"],
            }
            for bundle in per_query
        ],
    }
