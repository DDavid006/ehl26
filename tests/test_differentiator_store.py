import json

import pytest

from differentiator.store import Invention, RunStore, StoreError, render_workflow

WORKFLOW_TEMPLATE = '''INVENTION = {
    "name": "REPLACE ME",
}
GUI_RUN_ID = ""
GUI_RUNS_DIR = ""
GUI_REPO_ROOT = ""
'''


@pytest.fixture
def store(tmp_path):
    template = tmp_path / "workflow.py"
    template.write_text(WORKFLOW_TEMPLATE)
    return RunStore(tmp_path / "runs", template)


@pytest.fixture
def invention():
    return Invention(
        name="Self-cleaning heat exchanger",
        purpose="Stops microfluidic channels fouling",
        description="A piezo actuator shakes an aluminium fin stack.",
    )


def features_of(run):
    return [feature["text"] for feature in run.live_features]


def test_create_writes_run_files_and_binds_the_workflow(store, invention):
    run = store.create(invention)

    assert run.status == "queued"
    run_dir = store.runs_dir / run.run_id
    assert json.loads((run_dir / "invention.json").read_text())["name"] == invention.name
    workflow = (run_dir / "workflow.py").read_text()
    assert f'GUI_RUN_ID = "{run.run_id}"' in workflow
    assert f'GUI_RUNS_DIR = "{store.runs_dir}"' in workflow
    assert invention.name in workflow
    assert store.read_log(run.run_id)


@pytest.mark.parametrize("missing", ["name", "purpose", "description"])
def test_create_requires_every_field(store, invention, missing):
    setattr(invention, missing, "  ")
    with pytest.raises(StoreError, match=missing):
        store.create(invention)


def test_create_allocates_distinct_ids_for_the_same_name(store, invention):
    first = store.create(invention)
    second = store.create(invention)
    assert first.run_id != second.run_id


def test_render_workflow_rejects_a_template_without_the_invention_literal(invention):
    with pytest.raises(StoreError, match="INVENTION literal"):
        render_workflow(invention, "run-1", "/tmp/runs", "GUI_RUN_ID = \"\"\n")


def test_features_are_numbered_in_order(store, invention):
    run = store.create(invention)
    run = store.record_features(
        run.run_id,
        [{"text": "piezo actuator", "kind": "feature"},
         {"text": "aluminium fin stack", "kind": "material"}],
    )
    assert [f["id"] for f in run.features] == ["f1", "f2"]
    assert {f["origin"] for f in run.features} == {"original"}


def test_record_features_rejects_an_empty_list(store, invention):
    run = store.create(invention)
    with pytest.raises(StoreError):
        store.record_features(run.run_id, [])


def test_matrix_normalises_publication_numbers(store, invention):
    run = store.create(invention)
    store.record_features(run.run_id, [{"text": "piezo actuator", "kind": "feature"}])
    run = store.record_matrix(
        run.run_id,
        {
            "patents": [{"publication": "EP 1 234 567 A1", "title": "Shaker"}],
            "cells": [{"feature_id": "f1", "patent": "ep1234567a1", "present": True}],
        },
    )
    assert run.patents[0]["id"] == "EP1234567A1"
    assert run.cell("f1", "EP1234567A1") is True
    assert run.cell("f1", "EP9999999A1") is None


def test_matrix_accepts_cells_addressed_by_feature_text(store, invention):
    run = store.create(invention)
    store.record_features(run.run_id, [{"text": "piezo actuator", "kind": "feature"}])
    run = store.record_matrix(
        run.run_id,
        {
            "patents": [{"publication": "EP1234567A1"}],
            "cells": [{"feature": "piezo actuator", "patent": "EP1234567A1",
                       "present": False}],
        },
    )
    assert run.cell("f1", "EP1234567A1") is False


def test_matrix_rejects_an_unknown_feature(store, invention):
    run = store.create(invention)
    store.record_features(run.run_id, [{"text": "piezo actuator", "kind": "feature"}])
    with pytest.raises(StoreError, match="unknown feature"):
        store.record_matrix(
            run.run_id,
            {"patents": [], "cells": [{"feature": "nope", "patent": "EP1", "present": True}]},
        )


def test_substitution_swaps_one_feature_and_marks_the_replacement_new(store, invention):
    run = store.create(invention)
    store.record_features(
        run.run_id,
        [{"text": "piezo actuator", "kind": "feature"},
         {"text": "aluminium fin stack", "kind": "material"}],
    )
    store.record_similarity(
        run.run_id,
        {"closest_patent": "EP1234567A1", "overlap_ratio": 0.6,
         "shared_features": ["piezo actuator"], "needs_substitution": True},
    )
    run = store.record_substitution(
        run.run_id,
        {"feature_id": "f1", "replacement": "magnetostrictive actuator",
         "rationale": "not claimed by EP1234567A1"},
    )

    assert features_of(run) == ["aluminium fin stack", "magnetostrictive actuator"]
    assert run.new_features[0]["id"] == "f3"
    assert run.new_features[0]["replaces"] == "f1"
    assert run.new_features[0]["round"] == 1
    assert run.features[0]["replaced_by"] == "f3"


def test_a_feature_cannot_be_substituted_twice(store, invention):
    run = store.create(invention)
    store.record_features(run.run_id, [{"text": "piezo actuator", "kind": "feature"}])
    store.record_substitution(
        run.run_id, {"feature_id": "f1", "replacement": "magnetostrictive actuator"}
    )
    with pytest.raises(StoreError, match="no live feature"):
        store.record_substitution(
            run.run_id, {"feature_id": "f1", "replacement": "voice coil"}
        )


def test_similarity_rounds_are_numbered_past_substitutions(store, invention):
    run = store.create(invention)
    store.record_features(
        run.run_id,
        [{"text": "piezo actuator", "kind": "feature"},
         {"text": "aluminium fin stack", "kind": "material"}],
    )
    verdict = {"closest_patent": "EP1234567A1", "overlap_ratio": 0.6,
               "shared_features": ["piezo actuator"],
               "shared_feature_ids": ["f1"], "needs_substitution": True}
    store.record_similarity(run.run_id, verdict)
    store.record_substitution(
        run.run_id, {"feature_id": "f1", "replacement": "magnetostrictive actuator"}
    )
    run = store.record_similarity(run.run_id, {**verdict, "overlap_ratio": 0.25,
                                               "needs_substitution": False})

    assert [(i["kind"], i["round"]) for i in run.iterations] == [
        ("similarity", 1), ("substitution", 1), ("similarity", 2),
    ]
    assert run.iterations[0]["shared_feature_ids"] == ["f1"]


def test_every_write_bumps_the_revision(store, invention):
    run = store.create(invention)
    first = run.revision
    run = store.record_features(run.run_id, [{"text": "piezo actuator"}])
    assert run.revision > first
    assert store.get(run.run_id).revision == run.revision


def test_logging_to_an_unknown_run_is_a_store_error(store):
    with pytest.raises(StoreError, match="no such run"):
        store.log("nope", "hello")


def test_set_status_rejects_unknown_statuses(store, invention):
    run = store.create(invention)
    with pytest.raises(StoreError):
        store.set_status(run.run_id, "wandering")


def test_get_unknown_run(store):
    with pytest.raises(StoreError, match="no such run"):
        store.get("nope")


def test_list_is_newest_first(store, invention):
    first = store.create(invention)
    second = store.create(invention)
    store.set_status(second.run_id, "complete")
    assert {run.run_id for run in store.list()} == {first.run_id, second.run_id}
