import json
import subprocess
import sys
from pathlib import Path

import pytest

import agent_log

PLUGIN = Path(__file__).resolve().parent / "tools" / "entire-agent-patentability"


@pytest.fixture(autouse=True)
def log_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ENTIRE_AGENT_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(agent_log, "ATTACH_ENABLED", False)
    agent_log._current.set(None)
    yield tmp_path
    agent_log._current.set(None)


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_records_the_exact_ask_and_output(log_dir):
    run = agent_log.start_run("a leave-on scalp foam")
    agent_log.record("decompose", "PROMPT TEXT", "MODEL OUTPUT", model="gpt-4.1-mini")
    agent_log.finish_run(run)

    exchange = next(entry for entry in lines(run.path) if entry["type"] == "exchange")
    assert exchange["ask"] == "PROMPT TEXT"
    assert exchange["output"] == "MODEL OUTPUT"
    assert exchange["task"] == "decompose"
    assert exchange["model"] == "gpt-4.1-mini"
    assert exchange["error"] is None
    assert lines(run.path)[-1] == {**lines(run.path)[-1], "type": "run_finished", "exchanges": 1}


def test_records_a_failed_ask(log_dir):
    run = agent_log.start_run("failing run")
    agent_log.record("search: foam", "PROMPT", error="401 from OpenAI", model="openai/web_search")
    agent_log.finish_run(run)

    exchange = next(entry for entry in lines(run.path) if entry["type"] == "exchange")
    assert exchange["error"] == "401 from OpenAI"
    assert exchange["output"] == ""


def test_recording_outside_a_run_is_a_no_op(log_dir):
    agent_log.record("decompose", "PROMPT", "OUTPUT")
    agent_log.note("thinking")

    assert list(log_dir.iterdir()) == []


def test_a_run_that_cannot_be_written_still_records_in_memory(log_dir, monkeypatch):
    monkeypatch.setenv("ENTIRE_AGENT_LOG_DIR", str(log_dir / "unwritable"))
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))

    run = agent_log.start_run("no disk")
    agent_log.record("decompose", "PROMPT", "OUTPUT")

    assert [entry["type"] for entry in run.entries] == ["run_started", "exchange"]


def test_read_run_round_trips_a_transcript(log_dir):
    run = agent_log.start_run("round trip")
    agent_log.record("examine", "PROMPT", "OUTPUT")
    agent_log.finish_run(run)

    assert agent_log.read_run(run.run_id) == run.entries


@pytest.mark.parametrize("run_id", ["../etc/passwd", "run id", "", "a/b"])
def test_read_run_refuses_a_run_id_that_is_not_one(run_id):
    assert agent_log.read_run(run_id) == []


def test_finish_run_reports_a_failed_attach(log_dir, monkeypatch):
    monkeypatch.setattr(agent_log, "ATTACH_ENABLED", True)
    monkeypatch.setattr(
        agent_log, "_attach_to_entire", lambda run: (False, "entire: command not found")
    )

    run = agent_log.finish_run(agent_log.start_run("no entire"))

    attach = next(entry for entry in run.entries if entry["type"] == "entire_attach")
    assert attach == {**attach, "attached": False, "output": "entire: command not found"}


def test_attach_puts_the_plugin_on_the_path(log_dir, monkeypatch):
    captured = {}

    class Completed:
        returncode = 0
        stdout = "Attached session"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return Completed()

    monkeypatch.setattr(agent_log.subprocess, "run", fake_run)

    run = agent_log.RunLog("attach", run_id="run-abc")
    assert agent_log._attach_to_entire(run) == (True, "Attached session")
    assert captured["command"] == [
        "entire",
        "session",
        "attach",
        "run-abc",
        "--agent",
        "patentability",
    ]
    assert captured["env"]["PATH"].startswith(str(agent_log.PLUGIN_DIR))
    assert captured["env"]["ENTIRE_AGENT_LOG_DIR"] == str(log_dir)


def plugin(*args, stdin: str = "", log_dir: Path | None = None):
    result = subprocess.run(
        [sys.executable, str(PLUGIN), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "ENTIRE_AGENT_LOG_DIR": str(log_dir or "")},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_plugin_announces_the_protocol_entire_speaks():
    info = json.loads(plugin("info"))

    assert info["protocol_version"] == 1
    assert info["name"] == "patentability"
    assert info["capabilities"]["transcript_analyzer"] is True
    assert info["capabilities"]["hooks"] is False


def test_plugin_resolves_and_reads_a_transcript(log_dir):
    run = agent_log.start_run("scalp foam")
    agent_log.record("decompose", "FIRST ASK", "FIRST OUTPUT")
    agent_log.record("examine", "SECOND ASK", "SECOND OUTPUT")
    agent_log.finish_run(run)

    directory = json.loads(plugin("get-session-dir", log_dir=log_dir))["session_dir"]
    assert directory == str(log_dir)

    resolved = json.loads(
        plugin(
            "resolve-session-file",
            "--session-dir",
            directory,
            "--session-id",
            run.run_id,
            log_dir=log_dir,
        )
    )["session_file"]
    assert resolved == str(run.path)

    raw = plugin("read-transcript", "--session-ref", resolved, log_dir=log_dir)
    assert raw == run.path.read_text(encoding="utf-8")


def test_plugin_hands_entire_the_asks_as_prompts(log_dir):
    run = agent_log.start_run("scalp foam")
    agent_log.record("decompose", "FIRST ASK", "FIRST OUTPUT")
    agent_log.record("examine", "SECOND ASK", "SECOND OUTPUT")
    agent_log.finish_run(run)

    prompts = json.loads(
        plugin("extract-prompts", "--session-ref", str(run.path), log_dir=log_dir)
    )
    assert prompts == {"prompts": ["FIRST ASK", "SECOND ASK"]}

    summary = json.loads(
        plugin("extract-summary", "--session-ref", str(run.path), log_dir=log_dir)
    )
    assert summary["has_summary"] is True
    assert "scalp foam" in summary["summary"]
    assert "2 model exchanges" in summary["summary"]


def test_plugin_chunks_and_reassembles_a_transcript(log_dir):
    run = agent_log.start_run("chunking")
    agent_log.record("decompose", "ASK", "OUTPUT")
    raw = run.path.read_text(encoding="utf-8")

    chunks = json.loads(plugin("chunk-transcript", "--max-size", "16", stdin=raw))["chunks"]
    assert len(chunks) > 1
    assert plugin("reassemble-transcript", stdin=json.dumps({"chunks": chunks})) == raw


def test_plugin_reports_an_empty_summary_for_an_unknown_session(log_dir):
    answer = json.loads(
        plugin("extract-summary", "--session-ref", str(log_dir / "missing.jsonl"))
    )

    assert answer == {"summary": "", "has_summary": False}
