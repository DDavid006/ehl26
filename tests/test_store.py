import ast
import json
from dataclasses import replace

import pytest

from gui.store import (
    SKILL_WORKFLOW,
    Idea,
    RunStore,
    StoreError,
    parse_features,
    render_workflow,
    slugify,
)


def make_idea(title="Solar thermal battery"):
    return Idea(
        title=title,
        description="Stores heat for later use.",
        features=["phase-change material", "embedded temperature sensor"],
        field_of_art="thermal storage",
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Self-cleaning Heat Exchanger!", "self-cleaning-heat-exchanger"),
        ("  A / B: C  ", "a-b-c"),
        ("!!!", "untitled"),
        ("x" * 70, "x" * 60),
    ],
)
def test_slugify(text, expected):
    assert slugify(text) == expected


def test_parse_features_strips_bullets_and_blank_lines():
    raw = "\n * first feature \n\n- second feature\n  * third feature  \n\t\n"
    assert parse_features(raw) == ["first feature", "second feature", "third feature"]


def test_render_workflow_substitutes_idea_literal_once_and_is_python():
    idea = make_idea("Submitted thermal battery")
    rendered = render_workflow(idea, SKILL_WORKFLOW.read_text())

    assert rendered.count("IDEA = ") == 1
    assert idea.title in rendered
    ast.parse(rendered)


@pytest.mark.parametrize(
    ("idea", "message"),
    [
        (replace(make_idea(), title="   "), "title is required"),
        (replace(make_idea(), description="\n\t"), "description is required"),
        (replace(make_idea(), features=[]), "list at least one distinctive feature"),
    ],
)
def test_create_validation_errors(tmp_path, idea, message):
    with pytest.raises(StoreError, match=message):
        RunStore(tmp_path).create(idea)


def test_create_suffixes_colliding_run_ids(tmp_path):
    store = RunStore(tmp_path)

    first = store.create(make_idea())
    second = store.create(make_idea())

    assert first.run_id == "solar-thermal-battery"
    assert second.run_id == "solar-thermal-battery-2"
    assert (tmp_path / second.run_id / "idea.json").is_file()


def test_record_round_sets_blocked_or_drafted_status(tmp_path):
    store = RunStore(tmp_path)
    blocked = store.create(make_idea("Blocked idea"))
    drafted = store.create(make_idea("Clear idea"))

    blocked_run = store.record_round(
        blocked.run_id,
        {"verdict": "blocked", "blocking_references": ["US-123"]},
    )
    drafted_run = store.record_round(drafted.run_id, {"verdict": "clear"})

    assert blocked_run.status == "blocked"
    assert blocked_run.verdict == "blocked"
    assert drafted_run.status == "drafted"
    assert drafted_run.verdict == "clear"


def test_record_draft_persists_draft_and_status(tmp_path):
    store = RunStore(tmp_path)
    run = store.create(make_idea())
    draft = {
        "branch": "patent/solar-thermal-battery",
        "path": "patents/solar-thermal-battery.md",
        "independent_claim": "A thermal battery comprising...",
        "claim_count": 12,
        "summary": "A draft application.",
    }

    recorded = store.record_draft(run.run_id, draft)

    assert recorded.status == "drafted"
    assert store.get(run.run_id).draft == draft


def test_list_orders_runs_by_created_at_descending(tmp_path):
    store = RunStore(tmp_path)
    older = store.create(make_idea("Older idea"))
    newer = store.create(make_idea("Newer idea"))

    for run_id, timestamp in (
        (older.run_id, "2025-01-01T00:00:00+00:00"),
        (newer.run_id, "2025-01-02T00:00:00+00:00"),
    ):
        state_path = tmp_path / run_id / "state.json"
        state = json.loads(state_path.read_text())
        state["created_at"] = timestamp
        state_path.write_text(json.dumps(state))

    assert [run.run_id for run in store.list()] == [newer.run_id, older.run_id]


def test_get_unknown_run_raises_store_error(tmp_path):
    with pytest.raises(StoreError, match="no such run"):
        RunStore(tmp_path).get("missing-run")
