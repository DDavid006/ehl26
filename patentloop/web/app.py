"""Dark mission-control UI for triggering and monitoring PatentLoop runs."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from patentloop.orchestrator import run_pipeline


def create_app(runs_dir: Path | str | None = None, runner=run_pipeline) -> Flask:
    app = Flask(__name__)
    root = Path(runs_dir or Path(__file__).resolve().parents[2] / "runs")
    root.mkdir(parents=True, exist_ok=True)
    app.config["PATENTLOOP_RUNS_DIR"] = root

    def start(run_id: str, idea: str, max_iterations: int) -> None:
        run_dir = root / run_id
        try:
            result = runner(idea, run_dir, max_iterations=max_iterations)
            state_path = run_dir / "web_state.json"
            temporary = run_dir / "web_state.json.tmp"
            temporary.write_text(json.dumps(result, indent=2))
            temporary.replace(state_path)
        except Exception as exc:
            with (run_dir / "run.log").open("a") as log:
                log.write(f"PatentLoop infrastructure failure: {exc}\n")
            state_path = run_dir / "web_state.json"
            temporary = run_dir / "web_state.json.tmp"
            temporary.write_text(json.dumps({"verdict": "FAILED", "error": str(exc)}, indent=2))
            temporary.replace(state_path)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/api/runs")
    def create_run():
        payload = request.get_json(silent=True) or {}
        idea = str(payload.get("idea", "")).strip()
        if not idea:
            return jsonify({"error": "idea is required"}), 400
        run_id = str(payload.get("run_id") or uuid.uuid4().hex[:12])
        run_dir = root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "idea.txt").write_text(idea + "\n")
        max_iterations = int(payload.get("max_iterations", 5))
        (run_dir / "run.log").write_text("queued\n")
        threading.Thread(
            target=start, args=(run_id, idea, max_iterations), daemon=True
        ).start()
        return jsonify({"run_id": run_id, "status": "queued"}), 202

    def run_dir_or_404(run_id: str) -> Path:
        path = root / run_id
        if not path.is_dir():
            abort(404)
        return path

    @app.get("/api/runs/<run_id>")
    def run_summary(run_id: str):
        path = run_dir_or_404(run_id)
        state_path = path / "web_state.json"
        state = {"verdict": "RUNNING"}
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
            except json.JSONDecodeError:
                pass
        return jsonify({"run_id": run_id, **state})

    @app.get("/api/runs/<run_id>/events")
    def run_events(run_id: str):
        path = run_dir_or_404(run_id)
        log = (path / "run.log").read_text().splitlines() if (path / "run.log").exists() else []
        trace = json.loads((path / "trace.json").read_text()) if (path / "trace.json").exists() else []
        return jsonify({"run_id": run_id, "log": log, "events": trace})

    @app.get("/api/runs/<run_id>/staff")
    def run_staff(run_id: str):
        path = run_dir_or_404(run_id) / "company.json"
        if not path.is_file():
            return jsonify({"assignments": []})
        try:
            board = json.loads(path.read_text())
        except json.JSONDecodeError:
            board = {"assignments": []}
        return jsonify(board)

    @app.get("/api/runs/<run_id>/report")
    def run_report(run_id: str):
        report = run_dir_or_404(run_id) / "report.md"
        if not report.is_file():
            abort(404)
        return send_file(report, mimetype="text/markdown")

    @app.get("/api/runs/<run_id>/download")
    def download_pdf(run_id: str):
        pdf = run_dir_or_404(run_id) / "draft_application.pdf"
        if not pdf.is_file():
            abort(404)
        return send_file(pdf, as_attachment=True, download_name="draft_application.pdf")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
