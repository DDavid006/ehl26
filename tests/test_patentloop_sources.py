"""Source parsers, checked against payload shapes the live APIs return."""

from __future__ import annotations

import json

import pytest

from patentloop import http as http_mod
from patentloop.config import Config
from patentloop.llm import _extract_json, LLMError
from patentloop.schemas import PatentHit
from patentloop.sources import ArxivSource, GooglePatentsSource, PatentsViewSource
from patentloop.trace import Tracer

ARXIV_XML = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <id>http://arxiv.org/abs/2401.00001v1</id>
  <published>2024-01-01T00:00:00Z</published>
  <title>Laser textured garnet
   electrolytes</title>
  <summary>We texture LLZO surfaces to suppress dendrites.</summary>
 </entry>
</feed>"""

GOOGLE_SEARCH = {
    "results": {
        "cluster": [
            {
                "result": [
                    {
                        "id": "patent/US11942620B2/en",
                        "patent": {
                            "title": "<b>Solid state battery</b> with electrolyte",
                            "assignee": "GM Global Technology",
                            "priority_date": "2021-01-01",
                            "snippet": "A solid-state cell &hellip; electrolyte",
                        },
                    }
                ]
            }
        ]
    }
}

PATENT_HTML = """
<html><meta name="description" content="A solid-state cell.">
<div class="claim-text">1. A method of making a solid-state electrochemical cell comprising punching apertures.</div>
<div class="claim-text">short</div>
<div class="claim-text">2. The method of claim 1, wherein the apertures are laser drilled to a depth of 20 micrometres.</div>
</html>"""


@pytest.fixture()
def context(tmp_path):
    config = Config(anthropic_api_key="test", runs_dir=tmp_path)
    return config, Tracer(tmp_path / "run", "run")


def _stub(monkeypatch, body: str, status: int = 200):
    def fake_request(url, **kwargs):
        return http_mod.Response(url=url, status=status, body=body, elapsed_ms=1)

    monkeypatch.setattr(http_mod, "request", fake_request)
    for module in ("arxiv", "google_patents", "patentsview"):
        monkeypatch.setattr(f"patentloop.sources.{module}.request", fake_request)


def test_arxiv_parses_entries_and_traces_raw_response(monkeypatch, context):
    config, tracer = context
    _stub(monkeypatch, ARXIV_XML)
    documents = ArxivSource(config, tracer).search("garnet electrolyte", 5)
    assert len(documents) == 1
    assert documents[0].title == "Laser textured garnet electrolytes"
    assert documents[0].year == 2024
    api_calls = [e for e in tracer.events if e["kind"] == "api_call"]
    assert api_calls and (tracer.run_dir / api_calls[0]["raw_response_file"]).exists()


def test_arxiv_records_failures_instead_of_inventing_results(monkeypatch, context):
    config, tracer = context

    def fail(url, **kwargs):
        raise http_mod.HttpError(url, 503, "unavailable")

    monkeypatch.setattr("patentloop.sources.arxiv.request", fail)
    assert ArxivSource(config, tracer).search("x", 3) == []
    assert [e for e in tracer.events if e["kind"] == "api_error"]


def test_google_patents_search_and_claim_extraction(monkeypatch, context):
    config, tracer = context
    _stub(monkeypatch, json.dumps(GOOGLE_SEARCH))
    source = GooglePatentsSource(config, tracer)
    hits = source.search("solid state battery", 5)
    assert hits[0].publication_number == "US11942620B2"
    assert hits[0].title == "Solid state battery with electrolyte"

    _stub(monkeypatch, PATENT_HTML)
    hit = source.fetch_claims(PatentHit(source="google_patents", publication_number="US11942620B2",
                                        title="t", url="u"))
    assert len(hit.claims) == 2, "short fragments are dropped"
    assert hit.claims[0].startswith("1. A method")
    assert hit.abstract == "A solid-state cell."


def test_patentsview_is_unavailable_without_a_key(context):
    config, tracer = context
    source = PatentsViewSource(config, tracer)
    assert not source.available
    assert source.search("battery", 3) == []
    assert tracer.events[-1]["error"].startswith("PATENTSVIEW_API_KEY not set")


@pytest.mark.parametrize("text", [
    '{"a": 1}',
    'here you go:\n```json\n{"a": 1}\n```',
    'prose {"a": 1} trailing prose',
])
def test_extract_json_tolerates_wrapping(text):
    assert _extract_json(text) == {"a": 1}


def test_extract_json_raises_when_there_is_no_object():
    with pytest.raises(LLMError):
        _extract_json("no json at all")
