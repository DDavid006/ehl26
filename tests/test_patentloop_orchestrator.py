"""The loop must terminate in exactly one of three states, without asking anyone."""

from __future__ import annotations

import json

import pytest

from patentloop.config import Config
from patentloop.orchestrator import Orchestrator
from patentloop.schemas import DRAFTED, KILLED_INFEASIBLE, KILLED_SATURATED
from tests import patentloop_fakes as fakes


def build(tmp_path, *, novelty, overlap, feasible=(True, True), converging=True, max_iterations=4):
    config = Config(anthropic_api_key="test", runs_dir=tmp_path, max_iterations=max_iterations)
    orchestrator = Orchestrator(config, run_id="test-run")
    orchestrator.research = fakes.FakeResearch(novelty)
    orchestrator.patent_search = fakes.FakePatents(overlap)
    orchestrator.feasibility = fakes.FakeFeasibility(*feasible)
    orchestrator.pivot = fakes.FakePivot(converging=converging)
    orchestrator.drafting = fakes.FakeDrafting()
    return orchestrator


def test_clear_idea_is_drafted_on_the_first_pass(tmp_path):
    result = build(tmp_path, novelty={1: 82.0}, overlap={1: 5.0}).run("a narrow idea")
    assert result.outcome == DRAFTED
    assert len(result.iterations) == 1
    run_dir = tmp_path / "test-run"
    assert (run_dir / "draft_application.md").exists()
    assert (run_dir / "report.md").read_text().count("DRAFTED") >= 1
    assert json.loads((run_dir / "prior_art.json").read_text())["iterations"][0]["patents"]


def test_infeasible_idea_is_killed_without_pivoting(tmp_path):
    orchestrator = build(tmp_path, novelty={1: 90.0}, overlap={1: 0.0}, feasible=(False, True))
    result = orchestrator.run("a perpetual motion machine")
    assert result.outcome == KILLED_INFEASIBLE
    assert orchestrator.pivot.calls == 0
    assert "doability" in result.reason
    assert not (tmp_path / "test-run" / "draft_application.md").exists()


def test_unscoped_idea_is_killed_by_the_scope_check(tmp_path):
    result = build(tmp_path, novelty={1: 90.0}, overlap={1: 0.0}, feasible=(True, False)).run(
        "an app that uses AI to optimize things"
    )
    assert result.outcome == KILLED_INFEASIBLE
    assert "scope" in result.reason


def test_high_overlap_pivots_then_drafts_when_the_variant_is_clear(tmp_path):
    orchestrator = build(
        tmp_path,
        novelty={1: 70.0, 2: 80.0},
        overlap={1: 90.0, 2: 10.0},
        converging=False,
    )
    result = orchestrator.run("a crowded idea")
    assert result.outcome == DRAFTED
    assert [it.idea.version for it in result.iterations] == [1, 2]
    assert result.iterations[1].idea.parent_version == 1
    assert orchestrator.pivot.calls == 1


def test_converging_pivots_in_a_blocked_field_stop_as_saturated(tmp_path):
    orchestrator = build(tmp_path, novelty={}, overlap={1: 90.0, 2: 88.0, 3: 87.0}, converging=True)
    result = orchestrator.run("a very crowded idea")
    assert result.outcome == KILLED_SATURATED
    assert "converged" in result.reason
    assert len(result.iterations) <= orchestrator.config.max_iterations


def test_iteration_cap_always_terminates_the_run(tmp_path):
    orchestrator = build(
        tmp_path,
        novelty={},
        overlap={v: 95.0 for v in range(1, 9)},
        converging=False,
        max_iterations=3,
    )
    result = orchestrator.run("a permanently blocked idea")
    assert result.outcome == KILLED_SATURATED
    assert len(result.iterations) == 3
    assert "cap" in result.reason


def test_low_novelty_without_blocking_claims_pivots(tmp_path):
    orchestrator = build(
        tmp_path, novelty={1: 20.0, 2: 90.0}, overlap={1: 0.0, 2: 0.0}, converging=False
    )
    result = orchestrator.run("published but unpatented idea")
    assert result.outcome == DRAFTED
    decision_gate = next(d for d in result.iterations[0].decisions if d.gate == "decision")
    assert decision_gate.decision == "pivot"
    assert "literature already discloses" in decision_gate.reason


@pytest.mark.parametrize("outcome_setup,expected", [
    (dict(novelty={1: 82.0}, overlap={1: 5.0}), DRAFTED),
    (dict(novelty={1: 90.0}, overlap={1: 0.0}, feasible=(False, True)), KILLED_INFEASIBLE),
    (dict(novelty={}, overlap={v: 95.0 for v in range(1, 9)}), KILLED_SATURATED),
])
def test_every_run_writes_a_full_audit_trail(tmp_path, outcome_setup, expected):
    result = build(tmp_path, **outcome_setup).run("some idea")
    assert result.outcome == expected
    trace = json.loads((tmp_path / "test-run" / "trace.json").read_text())
    assert trace["outcome"] == expected
    assert trace["lineage"]
    gates = [e for e in trace["events"] if e["kind"] == "gate"]
    assert gates, "gate decisions must be in the trace"
    assert all(g["reason"] for g in gates)
