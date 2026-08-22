import json

import patentloop.orchestrator as orchestrator_module
from patentloop.agents.feasibility import feasibility_gate
from patentloop.agents.patent_search import (
    overlap_score,
    patent_overlap,
    validate_claim_quote,
)
from patentloop.agents.research import element_novelty, novelty_score
from patentloop.artifacts import ArtifactWriter
from patentloop.orchestrator import saturation_detector
from patentloop.backends.devin_agent import DevinAgentBackend, DevinBackendError
from patentloop.web.app import create_app


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.text = json.dumps(payload)

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeDevinSession:
    def __init__(self, poll_payload):
        self.poll_payload = poll_payload
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse({"session_id": "sess-1", "url": "https://app.devin.ai/sessions/sess-1"})

    def get(self, url, **kwargs):
        return FakeResponse(self.poll_payload)


def test_novelty_formula_includes_minimum_element():
    assert element_novelty([1, 0], [[1, 0]]) == 0
    assert novelty_score([0.2, 0.8]) == 35


def test_overlap_uses_max_patent_and_weights():
    assert patent_overlap(
        [{"verdict": "maps"}, {"verdict": "partial"}, {"verdict": "none"}]
    ) == 0.5
    patents = [
        {"element_verdicts": [{"verdict": "maps"}, {"verdict": "none"}]},
        {"overlap": 0.75, "element_verdicts": []},
    ]
    assert overlap_score(patents) == 75


def test_fabricated_claim_quote_is_downgraded():
    result = validate_claim_quote(
        {"verdict": "maps", "claim_quote": "fabricated language"},
        "A claim with real language.",
    )
    assert result["verdict"] == "partial"
    assert result["claim_quote"] == ""
    assert result["quote_invalid"] is True


def test_saturation_requires_convergence_and_two_high_overlaps():
    vectors = [[1.0, 0.0], [0.999, 0.01]]
    assert saturation_detector(vectors, [60, 60], 2)
    assert not saturation_detector(vectors, [60, 40], 2)


def test_iteration_cap_terminates_above_gate():
    assert saturation_detector([[1, 0]], [46], 5)


def test_feasibility_rules_require_concrete_three_element_idea():
    extracted = {
        "elements": [
            {"text": "a sensor module"},
            {"text": "a controller configured to receive readings"},
            {"text": "a processor generating a control signal"},
        ]
    }
    result = feasibility_gate(
        extracted,
        [
            {"decision": "pass", "reasoning": "doable"},
            {"decision": "pass", "reasoning": "scoped"},
        ],
    )
    assert result["feasible"] is True
    assert result["scoped"] is True


def test_artifacts_write_expected_keys(tmp_path):
    writer = ArtifactWriter(tmp_path)
    writer.event(1, "extract", {"idea": "x"}, {"elements": []})
    writer.write_prior_art([{"iteration": 1, "research": {}, "patents": {}}])
    writer.write_report(
        "KILLED_INFEASIBLE",
        [{"iteration": 1, "novelty_score": 0, "overlap_score": 0}],
        ["reason"],
        [],
    )
    assert (tmp_path / "trace.json").is_file()
    assert (tmp_path / "prior_art.json").is_file()
    assert (tmp_path / "report.md").is_file()
    assert json.loads((tmp_path / "trace.json").read_text())[0]["agent"] == "extract"


def test_devin_backend_polls_and_logs_session_evidence(tmp_path):
    session = FakeDevinSession({"status": "completed", "structured_output": {"answer": "ok"}})
    backend = DevinAgentBackend(
        "devin-test", session=session, run_dir=tmp_path, poll_interval=0
    )
    output = backend.chat(
        "answer",
        {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}},
    )
    assert output == {"answer": "ok"}
    assert backend.last_session_id == "sess-1"
    assert "sess-1" in backend.last_session_url


def test_devin_backend_timeout_is_explicit(tmp_path):
    session = FakeDevinSession({"status": "running"})
    backend = DevinAgentBackend(
        "devin-test", session=session, run_dir=tmp_path, timeout_seconds=-1, poll_interval=0
    )
    try:
        backend.chat("answer", {"type": "object"})
    except DevinBackendError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("expected timeout")


def test_devin_backend_rejects_schema_invalid_output(tmp_path):
    session = FakeDevinSession({"status": "completed", "structured_output": {}})
    backend = DevinAgentBackend("devin-test", session=session, poll_interval=0)
    try:
        backend.chat(
            "answer",
            {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}},
        )
    except DevinBackendError as exc:
        assert "schema validation" in str(exc)
    else:
        raise AssertionError("expected schema validation failure")


class StubLLM:
    last_log_path = None
    last_session_url = None

    def embed(self, texts, **kwargs):
        return [[1.0, 0.0] for _ in texts], None


def _patch_orchestrator(monkeypatch, *, feasible=True, drafted=False):
    extracted = {
        "elements": [
            {"id": "e1", "text": "sensor module", "keywords": ["sensor"]},
            {"id": "e2", "text": "controller configured to receive", "keywords": ["controller"]},
            {"id": "e3", "text": "processor generating signal", "keywords": ["processor"]},
        ],
        "field": "engineering",
        "persona_hint": "engineer",
    }
    monkeypatch.setattr(orchestrator_module, "extract_idea", lambda idea, llm: (extracted, None))
    class Feasibility:
        def __init__(self, llm):
            pass
        def run(self, idea, data):
            return ({"feasible": feasible, "scoped": feasible, "judges": [{"reasoning": "r"}]}, [])
    monkeypatch.setattr(orchestrator_module, "FeasibilityAgent", Feasibility)
    monkeypatch.setattr(orchestrator_module, "ResearchAgent", lambda llm, sources: type(
        "Research", (), {"run": lambda self, *args, **kwargs: {"novelty_score": 90 if drafted else 20, "closest_publications": [], "rationale": "", "llm_paths": []}})())
    monkeypatch.setattr(orchestrator_module, "PatentSearchAgent", lambda llm, sources, **kwargs: type(
        "Patents", (), {"run": lambda self, *args, **kwargs: {"overlap_score": 10 if drafted else 80, "patents": [], "llm_paths": []}})())
    monkeypatch.setattr(orchestrator_module, "DraftingAgent", lambda llm: type(
        "Draft", (), {"run": lambda self, *args, **kwargs: {"markdown_path": "draft.md", "pdf_path": "draft.pdf", "llm_paths": []}})())
    monkeypatch.setattr(orchestrator_module, "pivot_idea", lambda *args: ({"new_idea_text": "a different mechanism"}, None))


def test_orchestrator_reaches_infeasible(monkeypatch, tmp_path):
    _patch_orchestrator(monkeypatch, feasible=False)
    result = orchestrator_module.PatentLoop(
        run_dir=tmp_path, llm=StubLLM(), sources=[], require_keys=False
    ).run("idea")
    assert result["verdict"] == "KILLED_INFEASIBLE"


def test_orchestrator_reaches_drafted(monkeypatch, tmp_path):
    _patch_orchestrator(monkeypatch, drafted=True)
    result = orchestrator_module.PatentLoop(
        run_dir=tmp_path, llm=StubLLM(), sources=[], require_keys=False
    ).run("idea")
    assert result["verdict"] == "DRAFTED"


def test_orchestrator_reaches_saturated_iteration_cap(monkeypatch, tmp_path):
    _patch_orchestrator(monkeypatch)
    result = orchestrator_module.PatentLoop(
        run_dir=tmp_path, llm=StubLLM(), sources=[], require_keys=False
    ).run("idea", max_iterations=2)
    assert result["verdict"] == "KILLED_SATURATED"


def test_web_post_and_events_endpoints(tmp_path):
    def runner(idea, run_dir, **kwargs):
        (run_dir / "run.log").write_text("complete\n")
        return {"verdict": "KILLED_INFEASIBLE", "run_dir": str(run_dir)}

    client = create_app(tmp_path, runner=runner).test_client()
    response = client.post("/api/runs", json={"idea": "a mechanism"})
    assert response.status_code == 202
    run_id = response.get_json()["run_id"]
    import time
    for _ in range(20):
        summary = client.get(f"/api/runs/{run_id}").get_json()
        if summary.get("verdict") != "RUNNING":
            break
        time.sleep(0.01)
    assert client.get(f"/api/runs/{run_id}/events").status_code == 200
    assert summary["verdict"] == "KILLED_INFEASIBLE"
