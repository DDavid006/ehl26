"""Flask GUI for submitting patent ideas and reviewing clearance runs."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, url_for

from gui.store import DEFAULT_RUNS_DIR, Idea, RunStore, StoreError, parse_features

STATUS_LABELS = {
    "queued": "Queued - waiting for the agents to start",
    "running": "Agents running",
    "blocked": "Blocked by prior art",
    "drafted": "Patent drafted",
    "failed": "Failed",
}


def create_app(runs_dir: Path | str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("PATENT_GUI_SECRET", "patent-gui-dev")
    store = RunStore(runs_dir or os.environ.get("PATENT_GUI_RUNS", DEFAULT_RUNS_DIR))

    @app.context_processor
    def inject_labels():
        return {"status_labels": STATUS_LABELS}

    @app.get("/")
    def index():
        return render_template("index.html", runs=store.list())

    @app.post("/runs")
    def create_run():
        idea = Idea(
            title=request.form.get("title", "").strip(),
            description=request.form.get("description", "").strip(),
            features=parse_features(request.form.get("features", "")),
            field_of_art=request.form.get("field", "").strip(),
        )
        try:
            run = store.create(idea)
        except StoreError as exc:
            flash(str(exc), "error")
            return render_template("index.html", runs=store.list(), draft=idea), 400
        return redirect(url_for("show_run", run_id=run.run_id))

    @app.get("/runs/<run_id>")
    def show_run(run_id: str):
        try:
            run = store.get(run_id)
        except StoreError:
            abort(404)
        return render_template(
            "run.html",
            run=run,
            log=store.read_log(run_id),
            workflow_path=store.workflow_path(run_id),
        )

    @app.get("/runs/<run_id>/state")
    def run_state(run_id: str):
        """Polled by the run page so a live run updates without a reload."""
        try:
            run = store.get(run_id)
        except StoreError:
            abort(404)
        return {
            "status": run.status,
            "verdict": run.verdict,
            "rounds": run.rounds,
            "draft": run.draft,
            "log": store.read_log(run_id, tail=50),
        }

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
