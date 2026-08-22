import json

import patentloop.orchestrator as orchestrator_module
from patentloop.agents.feasibility import feasibility_gate
from patentloop.agents.patent_search import (
    overlap_score,
    patent_overlap,
    validate_claim_quote,
)
from patentloop.agents.research import ResearchAgent, element_novelty, novelty_score
from patentloop.artifacts import ArtifactWriter
from patentloop.errors import EvidenceFailure
from patentloop.llm import Judge
from patentloop.orchestrator import saturated
from patentloop.backends.devin_agent import DevinAgentBackend, DevinBackendError
from patentloop.company import StaffBoard
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


class BlockedThenCompleteDevinSession(FakeDevinSession):
    def __init__(self):
        super().__init__({"status": "blocked"})
        self.nudged = False

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if url.endswith("/message"):
            self.nudged = True
            return FakeResponse({"ok": True})
        return FakeResponse(
            {"session_id": "sess-1", "url": "https://app.devin.ai/sessions/sess-1"}
        )

    def get(self, url, **kwargs):
        if self.nudged:
            return FakeResponse(
                {"status": "completed", "structured_output": {"answer": "ok"}}
            )
        return FakeResponse({"status": "blocked"})


def test_novelty_formula_includes_minimum_element():
    assert element_novelty([1, 0], [[1, 0]]) == 0
    assert element_novelty([1, 0], []) == 0
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
    assert saturated(vectors, [60, 60], 2)
    assert not saturated(vectors, [60, 40], 2)


def test_iteration_cap_terminates_above_gate():
    assert saturated([[1, 0]], [46], 5)


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


def test_feasibility_judges_override_non_structural_rule_signals():
    extracted = {
        "elements": [
            {"text": "a platform for sensor data"},
            {"text": "a platform for controller data"},
            {"text": "a platform for processor data"},
        ]
    }
    result = feasibility_gate(
        extracted,
        [
            {"decision": "pass", "reasoning": "physically doable"},
            {"decision": "pass", "reasoning": "narrow enough"},
        ],
    )
    assert result["feasible"] is True
    assert result["rules"]["not_aspiration"] is False


def test_artifacts_write_expected_keys(tmp_path):
    writer = ArtifactWriter(tmp_path)
    writer.event(1, "extract", {"idea": "x"}, {"elements": []})
    writer.write_prior_art([{"iteration": 1, "research": {}, "patents": {}}])
    writer.write_report(
        "KILLED_INFEASIBLE",
        [{"iteration": 1, "novelty_score": 0, "overlap_score": 0}],
        ["reason"],
        [],
        termination_reason="feasibility_failure",
    )
    assert (tmp_path / "trace.json").is_file()
    assert (tmp_path / "prior_art.json").is_file()
    assert (tmp_path / "report.md").is_file()
    assert json.loads((tmp_path / "trace.json").read_text())[0]["agent"] == "extract"


def test_company_board_is_atomic_and_embedded_in_trace_and_report(tmp_path):
    board = StaffBoard(tmp_path)
    assignment_id = board.dispatch(
        "extract", task="Extract the invention.", iteration=1
    )
    board.running(assignment_id)
    board.completed(assignment_id)
    writer = ArtifactWriter(tmp_path, board=board)
    writer.event(1, "extract", {"idea": "x"}, {"elements": []})
    writer.write_report(
        "KILLED_INFEASIBLE",
        [{"iteration": 1, "novelty_score": 0, "overlap_score": 0}],
        [],
        [],
        termination_reason="feasibility_failure",
    )
    payload = json.loads((tmp_path / "company.json").read_text())
    assert payload["assignments"][0]["assignment_id"] == assignment_id
    assert not (tmp_path / "company.json.tmp").exists()
    trace = json.loads((tmp_path / "trace.json").read_text())
    assert trace[0]["company"]["assignments"][0]["status"] == "completed"
    assert "## Team" in (tmp_path / "report.md").read_text()


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
    assert session.posts[0][1]["json"]["unlisted"] is False


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


def test_devin_backend_nudges_blocked_session(tmp_path):
    session = BlockedThenCompleteDevinSession()
    backend = DevinAgentBackend(
        "devin-test", session=session, run_dir=tmp_path, poll_interval=0
    )
    output = backend.chat(
        "answer",
        {
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
    )
    assert output == {"answer": "ok"}
    assert any(url.endswith("/message") for url, _ in session.posts)
    assert backend.last_log_path


def test_company_board_tracks_blocked_nudge_and_role_tags(tmp_path):
    class RecordingBoard(StaffBoard):
        def __init__(self, path):
            super().__init__(path)
            self.transitions = []

        def blocked(self, assignment_id, **kwargs):
            self.transitions.append("blocked")
            super().blocked(assignment_id, **kwargs)

        def completed(self, assignment_id, **kwargs):
            self.transitions.append("completed")
            super().completed(assignment_id, **kwargs)

    session = BlockedThenCompleteDevinSession()
    board = RecordingBoard(tmp_path)
    backend = DevinAgentBackend(
        "devin-test", session=session, staff_board=board, poll_interval=0
    )
    output = backend.chat(
        "answer",
        {
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        agent="patent_search",
        role="Patent Examiner",
        iteration=2,
        task="Find and validate patents.",
    )
    assert output == {"answer": "ok"}
    assert board.transitions == ["blocked", "completed"]
    assignment = json.loads((tmp_path / "company.json").read_text())["assignments"][0]
    assert assignment["role_title"] == "Patent Examiner"
    assert assignment["status"] == "completed"
    assert assignment["session_url"].endswith("sess-1")
    body = session.posts[0][1]["json"]
    assert body["title"] == "PatentLoop · Patent Examiner · iteration 2"
    assert body["tags"] == ["patentloop", "patent-examiner"]


def test_company_board_records_failed_agent(tmp_path):
    session = FakeDevinSession({"status": "completed", "structured_output": {}})
    board = StaffBoard(tmp_path)
    backend = DevinAgentBackend(
        "devin-test", session=session, staff_board=board, poll_interval=0
    )
    try:
        backend.chat(
            "answer",
            {
                "type": "object",
                "required": ["answer"],
                "properties": {"answer": {"type": "string"}},
            },
            agent="extract",
            iteration=1,
            task="Extract elements.",
        )
    except DevinBackendError:
        pass
    else:
        raise AssertionError("expected schema validation failure")
    assignment = json.loads((tmp_path / "company.json").read_text())["assignments"][0]
    assert assignment["status"] == "failed"
    assert "schema validation" in assignment["error"]


class StubLLM:
    last_log_path = None
    last_session_url = None

    def embed(self, texts, **kwargs):
        return [[1.0, 0.0] for _ in texts], None


class EmptySource:
    def __init__(self):
        self.queries = []

    def search(self, query, **kwargs):
        self.queries.append(query)
        return []


class LiteratureSource:
    def search(self, query, **kwargs):
        if query in {"one", "two"}:
            return [{"id": query, "title": query, "abstract": "evidence"}]
        return []


class RaisingSource:
    name = "flaky-literature"

    def search(self, query, **kwargs):
        raise RuntimeError("429 Too Many Requests")


class HealthyLiteratureSource:
    name = "healthy-literature"

    def search(self, query, **kwargs):
        return [{"id": query, "title": query, "abstract": "evidence"}]


class ResearchLLM(StubLLM):
    def chat(self, prompt, schema, **kwargs):
        return {"rationale": "supported", "cited_ids": ["one", "two"]}


def test_research_records_unverified_elements_without_scoring_them(tmp_path):
    extracted = {
        "elements": [
            {"id": "e1", "text": "one", "keywords": ["one"]},
            {"id": "e2", "text": "two", "keywords": ["two"]},
            {"id": "e3", "text": "three", "keywords": ["three"]},
        ]
    }
    result = ResearchAgent(ResearchLLM(), [LiteratureSource()]).run(
        extracted, iteration=1, run_dir=tmp_path
    )
    assert result["unverified_elements"] == ["e3"]
    assert result["verified_elements"] == 2
    assert set(result["element_scores"]) == {"e1", "e2"}


def test_research_isolates_source_failure_and_keeps_healthy_results(tmp_path):
    extracted = {
        "elements": [
            {"id": "e1", "text": "one", "keywords": ["one"]},
            {"id": "e2", "text": "two", "keywords": ["two"]},
            {"id": "e3", "text": "three", "keywords": ["three"]},
        ]
    }
    result = ResearchAgent(
        ResearchLLM(), [RaisingSource(), HealthyLiteratureSource()]
    ).run(extracted, iteration=1, run_dir=tmp_path)
    assert result["verified_elements"] == 3
    assert result["documents_retrieved"] == {"e1": 1, "e2": 1, "e3": 1}
    assert len(result["source_errors"]) == 3
    assert result["source_errors"][0]["source"] == "flaky-literature"
    assert "429 Too Many Requests" in (tmp_path / "run.log").read_text()


def test_research_rejects_insufficient_document_evidence(tmp_path):
    extracted = {
        "elements": [
            {"id": "e1", "text": "one", "keywords": ["one"]},
            {"id": "e2", "text": "two", "keywords": ["two"]},
            {"id": "e3", "text": "three", "keywords": ["three"]},
        ]
    }
    try:
        ResearchAgent(StubLLM(), [EmptySource()]).run(
            extracted, iteration=1, run_dir=tmp_path
        )
    except EvidenceFailure as exc:
        assert exc.details["unverified_elements"] == ["e1", "e2", "e3"]
    else:
        raise AssertionError("expected evidence failure")


def test_judge_embedding_writes_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "patentloop.llm.local_embed",
        lambda texts, **kwargs: [[1.0, 2.0] for _ in texts],
    )
    judge = Judge(
        backend=type("Backend", (), {"chat": lambda self, *args, **kwargs: {}})(),
        run_dir=tmp_path,
    )
    vectors, path = judge.embed(["alpha", "beta"])
    assert vectors == [[1.0, 2.0], [1.0, 2.0]]
    record = json.loads((tmp_path / "llm" / "0001_embed.json").read_text())
    assert path.endswith("0001_embed.json")
    assert record["vector_dimension"] == 2
    assert record["count"] == 2
    assert len(record["text_sha256"]) == 2


def test_patent_search_rejects_zero_hits_after_broadening(tmp_path):
    source = EmptySource()
    extracted = {
        "elements": [
            {"id": "e1", "text": "one", "keywords": ["one"]},
            {"id": "e2", "text": "two", "keywords": ["two"]},
            {"id": "e3", "text": "three", "keywords": ["three"]},
        ]
    }
    from patentloop.agents.patent_search import PatentSearchAgent

    try:
        PatentSearchAgent(
            StubLLM(), [source], allow_devin_search=False
        ).run("idea", extracted, iteration=1, run_dir=tmp_path)
    except EvidenceFailure as exc:
        assert exc.details["patents_examined"] == 0
        assert len(source.queries) > 1
    else:
        raise AssertionError("expected evidence failure")


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
        "Research", (), {"run": lambda self, *args, **kwargs: {"novelty_score": 90 if drafted else 20, "element_scores": {"e1": 0.9, "e2": 0.9, "e3": 0.9}, "verified_elements": 3, "unverified_elements": [], "closest_publications": [], "rationale": "", "llm_paths": []}})())
    monkeypatch.setattr(orchestrator_module, "PatentSearchAgent", lambda llm, sources, **kwargs: type(
        "Patents", (), {"run": lambda self, *args, **kwargs: {"overlap_score": 10 if drafted else 80, "patents_examined": 1 if drafted else 1, "patents": [{"id": "p1", "overlap": 0.1, "element_verdicts": [{"claim_quote": "claim"}]}] if drafted else [{"id": "p1", "overlap": 0.8, "element_verdicts": []}], "llm_paths": []}})())
    monkeypatch.setattr(orchestrator_module, "DraftingAgent", lambda llm: type(
        "Draft", (), {"run": lambda self, *args, **kwargs: {"markdown_path": "draft.md", "pdf_path": "draft.pdf", "llm_paths": []}})())
    monkeypatch.setattr(orchestrator_module, "pivot_idea", lambda *args: ({"new_idea_text": "a different mechanism"}, None))


def test_orchestrator_reaches_infeasible(monkeypatch, tmp_path):
    _patch_orchestrator(monkeypatch, feasible=False)
    result = orchestrator_module.PatentLoop(
        run_dir=tmp_path, llm=StubLLM(), literature_sources=[],
        patent_sources=[], allow_devin_search=False, require_keys=False
    ).run("idea")
    assert result["verdict"] == "KILLED_INFEASIBLE"


def test_orchestrator_reaches_drafted(monkeypatch, tmp_path):
    _patch_orchestrator(monkeypatch, drafted=True)
    result = orchestrator_module.PatentLoop(
        run_dir=tmp_path, llm=StubLLM(), literature_sources=[],
        patent_sources=[], allow_devin_search=False, require_keys=False
    ).run("idea")
    assert result["verdict"] == "DRAFTED"


def test_orchestrator_reaches_saturated_iteration_cap(monkeypatch, tmp_path):
    _patch_orchestrator(monkeypatch)
    result = orchestrator_module.PatentLoop(
        run_dir=tmp_path, llm=StubLLM(), literature_sources=[],
        patent_sources=[], allow_devin_search=False, require_keys=False
    ).run("idea", max_iterations=2)
    assert result["verdict"] == "KILLED_SATURATED"
    assert result["iterations"][-1]["termination_reason"] == "novelty_below_gate"
    assert "novelty_below_gate" in (tmp_path / "report.md").read_text()


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


def test_web_staff_endpoint_returns_empty_or_assignments(tmp_path):
    app = create_app(tmp_path, runner=lambda *args, **kwargs: {})
    client = app.test_client()
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    empty = client.get("/api/runs/run-1/staff")
    assert empty.status_code == 200
    assert empty.get_json() == {"assignments": []}
    (run_dir / "company.json").write_text(
        json.dumps({"assignments": [{"assignment_id": "a-1", "status": "running"}]})
    )
    populated = client.get("/api/runs/run-1/staff")
    assert populated.status_code == 200
    assert populated.get_json() == {
        "assignments": [{"assignment_id": "a-1", "status": "running"}]
    }
