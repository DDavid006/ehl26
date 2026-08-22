import json

import pytest

from differentiator.cli import main
from differentiator.store import Invention, RunStore

WORKFLOW_TEMPLATE = '''INVENTION = {
    "name": "REPLACE ME",
}
GUI_RUN_ID = ""
GUI_RUNS_DIR = ""
GUI_REPO_ROOT = ""
'''


@pytest.fixture
def run(tmp_path):
    template = tmp_path / "workflow.py"
    template.write_text(WORKFLOW_TEMPLATE)
    store = RunStore(tmp_path / "runs", template)
    created = store.create(
        Invention(name="Heat exchanger", purpose="Stop fouling", description="Piezo.")
    )
    return store, created.run_id


def write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return str(path)


def cli(store, *args):
    return main(["--runs-dir", str(store.runs_dir), *args])


def test_status_and_log(run):
    store, run_id = run
    assert cli(store, "status", run_id, "searching", "--workflow-run-id", "wfr-1") == 0
    assert cli(store, "log", run_id, "opening EP1234567A1") == 0

    state = store.get(run_id)
    assert state.status == "searching"
    assert state.workflow_run_id == "wfr-1"
    assert "opening EP1234567A1" in "\n".join(store.read_log(run_id))


def test_full_progress_sequence(run, tmp_path):
    store, run_id = run
    features = write(tmp_path, "features.json", {
        "features": [{"text": "piezo actuator", "kind": "feature"},
                     {"text": "aluminium fins", "kind": "material"}],
    })
    matrix = write(tmp_path, "matrix.json", {
        "patents": [{"publication": "EP1234567A1", "title": "Shaker"}],
        "cells": [{"feature_id": "f1", "patent": "EP1234567A1", "present": True},
                  {"feature_id": "f2", "patent": "EP1234567A1", "present": False}],
    })
    similarity = write(tmp_path, "similarity.json", {
        "closest_patent": "EP1234567A1", "overlap_ratio": 0.5,
        "shared_features": ["piezo actuator"], "needs_substitution": True,
    })
    substitution = write(tmp_path, "substitution.json", {
        "feature_id": "f1", "replacement": "magnetostrictive actuator",
        "rationale": "not claimed",
    })

    assert cli(store, "features", run_id, "--file", features) == 0
    assert cli(store, "matrix", run_id, "--file", matrix) == 0
    assert cli(store, "similarity", run_id, "--file", similarity) == 0
    assert cli(store, "substitution", run_id, "--file", substitution) == 0

    state = store.get(run_id)
    assert state.cell("f1", "EP1234567A1") is True
    assert [i["kind"] for i in state.iterations] == ["similarity", "substitution"]
    assert [f["text"] for f in state.live_features] == [
        "aluminium fins", "magnetostrictive actuator",
    ]


def test_store_errors_exit_non_zero(run, tmp_path, capsys):
    store, run_id = run
    payload = write(tmp_path, "substitution.json",
                    {"feature_id": "f9", "replacement": "voice coil"})
    assert cli(store, "substitution", run_id, "--file", payload) == 1
    assert "no live feature" in capsys.readouterr().err
