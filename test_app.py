import json

import pytest
from fastapi.testclient import TestClient

import agent_log
import app as app_module
import coverage as coverage_module
from app import app
from decompose import DecompositionError
from examine import ExaminationError
from suggest import SuggestionError

ELEMENTS = [
    {"id": "E1", "text": "a leave-on delivery format", "search_terms": ["leave-on formulation"]},
    {"id": "E2", "text": "a metered dose applicator", "search_terms": ["metered dose"]},
]

PATENT = {
    "patent_id": "US1234567",
    "title": "Leave-on formulation for scalp care",
    "abstract": "A foam comprising an ultraviolet filter.",
    "assignee": "Acme Labs",
    "date": "2020-01-01",
}

SUGGESTIONS = [
    {
        "title": "Claim a 0.5-1.0 mL metered actuation",
        "reasoning": "E2 is uncovered by US1234567.",
        "element_id": "E2",
        "reference": "US1234567",
    },
    {
        "title": "Recast E1 as a method of use",
        "reasoning": "US1234567 anticipates the composition.",
        "element_id": "E1",
        "reference": "US1234567",
    },
]


ALLOWED = {"patentable": True, "reasoning": "E2 is a meaningful structural limitation."}
BLOCKED = {"patentable": False, "reasoning": "E1 is anticipated by US1234567."}

RESULT_KEYS = [
    "coverage",
    "description",
    "elements",
    "iterations",
    "log",
    "patents",
    "run_id",
    "suggestions",
    "uncovered",
    "verdict",
]


@pytest.fixture(autouse=True)
def transcripts(tmp_path, monkeypatch):
    """Keep run transcripts out of the repo and out of the Entire CLI."""
    monkeypatch.setenv("ENTIRE_AGENT_LOG_DIR", str(tmp_path / "agent-logs"))
    monkeypatch.setattr(agent_log, "ATTACH_ENABLED", False)
    return tmp_path / "agent-logs"


def install_pipeline(monkeypatch, verdicts):
    """Stub every upstream call; ``verdicts`` is consumed one per iteration."""
    calls = {"search": [], "examined": [], "revised": []}
    pending = list(verdicts)

    def fake_search(query, limit=10):
        calls["search"].append((query, limit))
        return [PATENT]

    def fake_examine(matrix, description):
        calls["examined"].append(description)
        return pending.pop(0) if pending else ALLOWED

    def fake_revision(matrix, description, verdict, suggestions):
        calls["revised"].append(description)
        index = len(calls["revised"])
        return {"description": f"revision {index}", "changes": f"narrowed round {index}"}

    def keyword_judgement(elements, keys, patent):
        """Stand in for the model's judgement so no test reaches OpenAI."""
        verdicts = {}
        for key, element in zip(keys, elements):
            covered, evidence = coverage_module.is_covered(element, patent)
            verdicts[key] = {"covered": covered, "evidence": evidence}
        return verdicts

    monkeypatch.setattr(coverage_module, "judge_patent", keyword_judgement)
    monkeypatch.setattr(app_module, "decompose_invention", lambda description: ELEMENTS)
    monkeypatch.setattr(app_module, "search_patents", fake_search)
    monkeypatch.setattr(
        app_module, "generate_suggestions", lambda matrix, description: SUGGESTIONS
    )
    monkeypatch.setattr(app_module, "judge_patentability", fake_examine)
    monkeypatch.setattr(app_module, "generate_revision", fake_revision)
    return calls


@pytest.fixture
def client(monkeypatch):
    calls = install_pipeline(monkeypatch, [ALLOWED])
    with TestClient(app) as test_client:
        test_client.search_calls = calls["search"]
        test_client.calls = calls
        yield test_client


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analyse_returns_combined_payload(client):
    response = client.post("/api/analyse", json={"description": "A leave-on scalp foam."})

    assert response.status_code == 200
    body = response.json()
    assert sorted(body) == RESULT_KEYS
    assert body["elements"] == ELEMENTS
    assert body["patents"] == [PATENT]  # deduplicated across both elements
    assert body["uncovered"] == ["E2"]
    assert body["suggestions"] == SUGGESTIONS
    assert body["verdict"] == ALLOWED
    assert sorted(client.search_calls) == [("leave-on formulation", 3), ("metered dose", 3)]
    assert body["run_id"].startswith("run-")
    assert body["log"][0]["type"] == "run_started"
    assert body["log"][-1]["type"] == "run_finished"


def test_analyse_writes_a_transcript_that_the_log_route_serves(client, transcripts):
    body = client.post("/api/analyse", json={"description": "A leave-on scalp foam."}).json()

    assert (transcripts / f"{body['run_id']}.jsonl").is_file()
    served = client.get(f"/api/logs/{body['run_id']}")
    assert served.status_code == 200
    assert served.json() == {"run_id": body["run_id"], "log": body["log"]}
    notes = [entry["message"] for entry in body["log"] if entry["type"] == "note"]
    assert "decomposing the invention into functional elements" in notes


def test_log_route_404s_for_an_unknown_run(client):
    assert client.get("/api/logs/run-nope").status_code == 404


def test_analyse_stops_at_the_first_patentable_verdict(client):
    response = client.post("/api/analyse", json={"description": "A leave-on scalp foam."})

    body = response.json()
    assert body["description"] == "A leave-on scalp foam."
    assert len(body["iterations"]) == 1
    only = body["iterations"][0]
    assert only["iteration"] == 1
    assert only["changes"] is None
    assert only["verdict"] == ALLOWED
    assert only["coverage"] == body["coverage"]
    assert client.calls["revised"] == []


def test_analyse_revises_and_reruns_until_patentable(monkeypatch):
    calls = install_pipeline(monkeypatch, [BLOCKED, ALLOWED])

    with TestClient(app) as client:
        body = client.post(
            "/api/analyse", json={"description": "A leave-on scalp foam."}
        ).json()

    assert calls["examined"] == ["A leave-on scalp foam.", "revision 1"]
    assert calls["revised"] == ["A leave-on scalp foam."]
    assert [step["iteration"] for step in body["iterations"]] == [1, 2]
    assert [step["description"] for step in body["iterations"]] == [
        "A leave-on scalp foam.",
        "revision 1",
    ]
    assert [step["changes"] for step in body["iterations"]] == [None, "narrowed round 1"]
    assert [step["verdict"] for step in body["iterations"]] == [BLOCKED, ALLOWED]
    # the top level mirrors the final iteration
    assert body["description"] == "revision 1"
    assert body["verdict"] == ALLOWED
    assert all("coverage" in step and "uncovered" in step for step in body["iterations"])


def test_analyse_stops_after_three_iterations(monkeypatch):
    calls = install_pipeline(monkeypatch, [BLOCKED, BLOCKED, BLOCKED, BLOCKED])

    with TestClient(app) as client:
        body = client.post(
            "/api/analyse", json={"description": "A leave-on scalp foam."}
        ).json()

    assert len(body["iterations"]) == app_module.MAX_ITERATIONS == 3
    assert len(calls["examined"]) == 3
    assert calls["revised"] == ["A leave-on scalp foam.", "revision 1"]  # no revision after the last
    assert body["verdict"] == BLOCKED
    assert body["description"] == "revision 2"


def test_analyse_surfaces_examiner_failures(monkeypatch):
    install_pipeline(monkeypatch, [ALLOWED])

    def boom(matrix, description):
        raise ExaminationError("examiner unavailable")

    monkeypatch.setattr(app_module, "judge_patentability", boom)

    with TestClient(app) as client:
        response = client.post("/api/analyse", json={"description": "A leave-on scalp foam."})

    assert response.status_code == 502
    assert "examiner unavailable" in response.json()["detail"]


def test_analyse_surfaces_revision_failures(monkeypatch):
    install_pipeline(monkeypatch, [BLOCKED])

    def boom(matrix, description, verdict, suggestions):
        raise SuggestionError("revision unavailable")

    monkeypatch.setattr(app_module, "generate_revision", boom)

    with TestClient(app) as client:
        response = client.post("/api/analyse", json={"description": "A leave-on scalp foam."})

    assert response.status_code == 502
    assert "revision unavailable" in response.json()["detail"]


def _stream_events(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_analyse_stream_emits_progress_then_result(client):
    response = client.post(
        "/api/analyse/stream", json={"description": "A leave-on scalp foam."}
    )

    assert response.status_code == 200
    events = _stream_events(response)
    assert events[0]["event"] == "progress"
    assert events[-1]["event"] == "result"
    body = events[-1]["result"]
    assert sorted(body) == RESULT_KEYS
    assert body["uncovered"] == ["E2"]
    assert body["verdict"] == ALLOWED
    # the streamed run keeps its own transcript, reachable after the fact
    assert client.get(f"/api/logs/{body['run_id']}").json()["log"] == body["log"]


def test_analyse_stream_reports_each_iteration(monkeypatch):
    install_pipeline(monkeypatch, [BLOCKED, ALLOWED])

    with TestClient(app) as client:
        response = client.post(
            "/api/analyse/stream", json={"description": "A leave-on scalp foam."}
        )

    events = _stream_events(response)
    stages = [event.get("stage", "") for event in events if event["event"] == "progress"]
    assert any("iteration 1" in stage for stage in stages)
    assert any("iteration 2" in stage for stage in stages)
    assert any("revising" in stage for stage in stages)
    assert len(events[-1]["result"]["iterations"]) == 2


def test_analyse_stream_reports_failures_as_an_event(monkeypatch):
    def boom(description):
        raise DecompositionError("model unavailable")

    monkeypatch.setattr(app_module, "decompose_invention", boom)

    with TestClient(app) as client:
        response = client.post(
            "/api/analyse/stream", json={"description": "A leave-on scalp foam."}
        )

    assert response.status_code == 200
    last = _stream_events(response)[-1]
    assert last["event"] == "error"
    assert "model unavailable" in last["detail"]


def test_analyse_rejects_empty_description(client):
    assert client.post("/api/analyse", json={"description": "   "}).status_code == 422
    assert client.post("/api/analyse", json={"description": ""}).status_code == 422
    assert client.post("/api/analyse", json={}).status_code == 422


def test_analyse_surfaces_pipeline_failures(monkeypatch):
    def boom(description):
        raise DecompositionError("model unavailable")

    monkeypatch.setattr(app_module, "decompose_invention", boom)

    with TestClient(app) as client:
        response = client.post("/api/analyse", json={"description": "A leave-on scalp foam."})

    assert response.status_code == 502
    assert "model unavailable" in response.json()["detail"]


def test_analyse_surfaces_upstream_api_failures(monkeypatch):
    def boom(description):
        raise RuntimeError("429 You exceeded your current quota\nretry_delay: 30s")

    monkeypatch.setattr(app_module, "decompose_invention", boom)

    with TestClient(app) as client:
        response = client.post("/api/analyse", json={"description": "A leave-on scalp foam."})

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "429 You exceeded your current quota" in detail
    assert "retry_delay" not in detail


def test_cors_allows_localhost_origin(client):
    response = client.post(
        "/api/analyse",
        json={"description": "A leave-on scalp foam."},
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
