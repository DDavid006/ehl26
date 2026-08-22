import pytest

from differentiator.app import create_app
from differentiator.store import RunStore


@pytest.fixture
def runs_dir(tmp_path):
    """Runs land in tmp_path; the workflow template is the real skill file."""
    return tmp_path / "runs"


@pytest.fixture
def client(runs_dir):
    app = create_app(runs_dir)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def store(runs_dir):
    return RunStore(runs_dir)


def submit(client, **overrides):
    form = {
        "name": "Self-cleaning heat exchanger",
        "purpose": "Stops microfluidic channels fouling",
        "description": "A piezo actuator shakes an aluminium fin stack.",
    }
    form.update(overrides)
    return client.post("/runs", data=form)


def test_index_lists_no_runs_initially(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"No runs yet" in response.data


def test_submitting_creates_a_run_and_redirects_to_it(client, store):
    response = submit(client)
    assert response.status_code == 302

    run = store.list()[0]
    assert run.invention.name == "Self-cleaning heat exchanger"
    assert response.headers["Location"].endswith(f"/runs/{run.run_id}")


def test_submitting_without_a_purpose_reports_the_error(client):
    response = submit(client, purpose="")
    assert response.status_code == 400
    assert b"purpose is required" in response.data


def test_run_page_renders_the_matrix_with_green_and_gray_cells(client, store):
    submit(client)
    run_id = store.list()[0].run_id
    store.record_features(run_id, [{"text": "piezo actuator", "kind": "feature"},
                                   {"text": "aluminium fins", "kind": "material"}])
    store.record_matrix(run_id, {
        "patents": [{"publication": "EP1234567A1", "title": "Shaker",
                     "url": "https://worldwide.espacenet.com/patent/EP1234567A1"}],
        "cells": [{"feature_id": "f1", "patent": "EP1234567A1", "present": True},
                  {"feature_id": "f2", "patent": "EP1234567A1", "present": False}],
    })

    page = client.get(f"/runs/{run_id}").data.decode()
    assert 'class="cell present"' in page
    assert 'class="cell absent"' in page
    assert "EP1234567A1" in page


def test_run_page_marks_substituted_features_as_new(client, store):
    submit(client)
    run_id = store.list()[0].run_id
    store.record_features(run_id, [{"text": "piezo actuator", "kind": "feature"}])
    store.record_substitution(run_id, {"feature_id": "f1",
                                       "replacement": "magnetostrictive actuator",
                                       "rationale": "not claimed"})

    page = client.get(f"/runs/{run_id}").data.decode()
    assert "magnetostrictive actuator" in page
    assert "piezo actuator" in page  # kept in the substitution history
    assert "badge tiny new" in page


def test_state_endpoint_feeds_the_live_log(client, store):
    submit(client)
    run_id = store.list()[0].run_id
    store.set_status(run_id, "searching")
    store.log(run_id, "opening EP1234567A1")

    state = client.get(f"/runs/{run_id}/state").get_json()
    assert state["status"] == "searching"
    assert any("opening EP1234567A1" in line for line in state["log"])


def test_unknown_run_is_404(client):
    assert client.get("/runs/nope").status_code == 404
    assert client.get("/runs/nope/state").status_code == 404
