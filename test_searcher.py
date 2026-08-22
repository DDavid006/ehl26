import pytest

import searcher
from searcher import find_prior_art

ELEMENT = {
    "id": "E2",
    "text": "sterilises the contents with ultraviolet light",
    "search_terms": ["uv-c led", "water sterilisation"],
}


def patent(number):
    return {
        "patent_id": number,
        "title": f"Reference {number}",
        "abstract": "...",
        "assignee": None,
        "date": None,
    }


def install_agent(monkeypatch, queries, results_by_query=None):
    """Fake the agent loop: it issues ``queries`` through the tool it is given."""
    seen = []

    def fake_run_agent(prompt, tools, error_cls, max_tool_calls=6, on_tool_call=None):
        seen.append({"prompt": prompt, "budget": max_tool_calls})
        tool = list(tools)[0]
        for query in queries:
            if on_tool_call is not None:
                on_tool_call(tool.name, {"query": query})
            tool.func(query=query)
        return "closest reference found"

    monkeypatch.setattr(searcher, "run_agent", fake_run_agent)

    def fake_search(query, limit=10):
        return (results_by_query or {}).get(query, [])

    monkeypatch.setattr(searcher, "search_patents", fake_search)
    return seen


def test_returns_what_the_agent_searched_for(monkeypatch):
    calls = install_agent(
        monkeypatch,
        ["ultraviolet water treatment vessel", "uv led sterilisation cap"],
        {
            "ultraviolet water treatment vessel": [patent("US1"), patent("US2")],
            "uv led sterilisation cap": [patent("US3")],
        },
    )
    reported = []

    found = find_prior_art(ELEMENT, on_tool_call=lambda name, args: reported.append(args["query"]))

    assert [p["patent_id"] for p in found] == ["US1", "US2", "US3"]
    assert reported == ["ultraviolet water treatment vessel", "uv led sterilisation cap"]
    assert calls[0]["budget"] == searcher.SEARCH_BUDGET


def test_prompt_carries_the_element_and_its_terms(monkeypatch):
    calls = install_agent(monkeypatch, [])

    find_prior_art(ELEMENT)

    prompt = calls[0]["prompt"]
    assert "E2" in prompt
    assert ELEMENT["text"] in prompt
    assert "uv-c led, water sterilisation" in prompt


def test_deduplicates_and_caps_the_results(monkeypatch):
    install_agent(
        monkeypatch,
        ["a", "b"],
        {
            "a": [patent("US1"), patent("US2"), patent("US1")],
            "b": [patent("US2"), patent("US3"), patent("US4")],
        },
    )

    found = find_prior_art(ELEMENT)

    assert [p["patent_id"] for p in found] == ["US1", "US2", "US3"]
    assert len(found) == searcher.MAX_RESULTS


def test_falls_back_to_the_applicants_terms_when_the_agent_searches_nothing(monkeypatch):
    install_agent(monkeypatch, [], {"uv-c led water sterilisation": [patent("US9")]})

    assert [p["patent_id"] for p in find_prior_art(ELEMENT)] == ["US9"]


def test_element_without_terms_or_text_yields_nothing(monkeypatch):
    install_agent(monkeypatch, [])

    assert find_prior_art({"id": "E1"}) == []
