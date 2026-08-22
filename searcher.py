"""Per-element prior-art searcher agent.

One agent per functional element: it phrases its own queries instead of using the
applicant's ``search_terms`` verbatim, and the references it actually opened are
what the coverage matrix is built from.
"""

from __future__ import annotations

from typing import Callable, Optional

from agents import Tool, run_agent
from patent_client import search_patents

SEARCH_LIMIT = 5
SEARCH_BUDGET = 3
MAX_RESULTS = 3

PROMPT_TEMPLATE = """You are a patent searcher looking for the closest prior art to one \
functional element of an invention.

Element {element_id}: {text}
Keywords the applicant suggested: {terms}

Call search_prior_art with your own phrasing — the terms a patent in this field would actually \
use, not the applicant's marketing words. Run up to {budget} searches, starting broad and \
narrowing to the specific mechanism. When you are done, reply with one sentence naming the \
closest reference you found."""


class SearchError(ValueError):
    """Raised when the searcher agent cannot be run."""


SEARCH_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Keywords to search prior art for, as a patent in this field would phrase them.",
        }
    },
    "required": ["query"],
}


def _fallback(element: dict) -> list[dict]:
    query = " ".join(element.get("search_terms") or []) or element.get("text") or ""
    if not query.strip():
        return []
    return search_patents(query, limit=MAX_RESULTS)


def find_prior_art(
    element: dict,
    on_tool_call: Optional[Callable[[str, dict], None]] = None,
) -> list[dict]:
    """Return up to :data:`MAX_RESULTS` references the searcher agent found for ``element``.

    Falls back to a single keyword search on the element's own ``search_terms``
    when the agent runs no searches (for example under a provider without tool
    use), so the pipeline always gets references.
    """
    found: list[dict] = []
    seen: set[str] = set()

    def search(query: str) -> list[dict]:
        results = search_patents(query, limit=SEARCH_LIMIT)
        for patent in results:
            key = patent.get("patent_id") or patent.get("title")
            if key and key not in seen:
                seen.add(key)
                found.append(patent)
        return results

    tool = Tool(
        name="search_prior_art",
        description="Search patent references for a keyword query. Returns id, title and abstract.",
        parameters=SEARCH_TOOL_PARAMETERS,
        func=search,
    )
    prompt = PROMPT_TEMPLATE.format(
        element_id=element.get("id") or "E1",
        text=element.get("text") or "",
        terms=", ".join(element.get("search_terms") or []) or "none",
        budget=SEARCH_BUDGET,
    )
    run_agent(prompt, [tool], SearchError, max_tool_calls=SEARCH_BUDGET, on_tool_call=on_tool_call)

    if not found:
        return _fallback(element)
    return found[:MAX_RESULTS]
