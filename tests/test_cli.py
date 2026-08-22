import json

from gui.cli import main
from gui.store import Idea, RunStore


def test_cli_status_round_draft_and_log(tmp_path, capsys):
    store = RunStore(tmp_path)
    run = store.create(
        Idea(
            title="CLI idea",
            description="An idea submitted through the CLI tests.",
            features=["a distinctive feature"],
            field_of_art="engineering",
        )
    )
    round_path = tmp_path / "round.json"
    round_path.write_text(json.dumps({"verdict": "blocked", "blocking_references": ["US-1"]}))
    draft_path = tmp_path / "draft.json"
    draft = {
        "branch": "patent/cli-idea",
        "path": "patents/cli-idea.md",
        "independent_claim": "A system...",
        "claim_count": 3,
        "summary": "CLI draft.",
    }
    draft_path.write_text(json.dumps(draft))

    assert main(
        [
            "--runs-dir",
            str(tmp_path),
            "status",
            run.run_id,
            "running",
            "--workflow-run-id",
            "workflow-1",
        ]
    ) == 0
    assert main(["--runs-dir", str(tmp_path), "round", run.run_id, "--file", str(round_path)]) == 0
    assert main(["--runs-dir", str(tmp_path), "draft", run.run_id, "--file", str(draft_path)]) == 0
    assert main(["--runs-dir", str(tmp_path), "log", run.run_id, "workflow complete"]) == 0

    updated = store.get(run.run_id)
    assert updated.status == "drafted"
    assert updated.workflow_run_id == "workflow-1"
    assert updated.rounds == [{"verdict": "blocked", "blocking_references": ["US-1"]}]
    assert updated.draft == draft
    assert any("workflow complete" in line for line in store.read_log(run.run_id))
    assert capsys.readouterr().err == ""


def test_cli_unknown_run_id_returns_nonzero(tmp_path, capsys):
    result = main(["--runs-dir", str(tmp_path), "status", "missing", "running"])

    assert result != 0
    assert "no such run: missing" in capsys.readouterr().err
