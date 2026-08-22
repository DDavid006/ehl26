from gui.app import create_app
from gui.store import Idea, RunStore


def valid_form():
    return {
        "title": "Adaptive sensor array",
        "field": "sensor systems",
        "description": "A sensor array that adapts its sampling strategy.",
        "features": "* distributed sensors\n- adaptive sampling controller",
    }


def test_get_index_returns_200(tmp_path):
    response = create_app(tmp_path).test_client().get("/")

    assert response.status_code == 200
    assert b"Submit an invention" in response.data


def test_post_valid_run_redirects_and_creates_run(tmp_path):
    client = create_app(tmp_path).test_client()

    response = client.post("/runs", data=valid_form())

    assert response.status_code == 302
    run_id = response.headers["Location"].rstrip("/").split("/")[-1]
    run = RunStore(tmp_path).get(run_id)
    assert run.idea.title == valid_form()["title"]


def test_post_missing_field_returns_400_and_rerenders(tmp_path):
    form = valid_form()
    del form["description"]

    response = create_app(tmp_path).test_client().post("/runs", data=form)

    assert response.status_code == 400
    assert b"description is required" in response.data
    assert b"Adaptive sensor array" in response.data


def test_get_run_returns_200(tmp_path):
    run = RunStore(tmp_path).create(
        Idea(
            title="Existing idea",
            description="An existing description.",
            features=["a feature"],
            field_of_art="engineering",
        )
    )

    response = create_app(tmp_path).test_client().get(f"/runs/{run.run_id}")

    assert response.status_code == 200
    assert b"Existing idea" in response.data


def test_get_unknown_run_returns_404(tmp_path):
    response = create_app(tmp_path).test_client().get("/runs/unknown")

    assert response.status_code == 404


def test_get_run_state_returns_expected_json_keys(tmp_path):
    run = RunStore(tmp_path).create(
        Idea(
            title="Stateful idea",
            description="A stateful description.",
            features=["a feature"],
            field_of_art="engineering",
        )
    )

    response = create_app(tmp_path).test_client().get(f"/runs/{run.run_id}/state")

    assert response.status_code == 200
    assert set(response.get_json()) == {"status", "verdict", "rounds", "draft", "log"}
    assert response.get_json()["status"] == "queued"
