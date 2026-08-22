"""Flask GUI for Espacenet feature-overlap runs."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, url_for

from differentiator.store import (
    DEFAULT_RUNS_DIR,
    TERMINAL_STATUSES,
    Invention,
    RunStore,
    StoreError,
)

STATUS_LABELS = {
    "queued": "Queued - waiting for the agents to start",
    "extracting": "Extracting features and materials",
    "searching": "Searching Espacenet and building the matrix",
    "iterating": "Checking similarity and substituting features",
    "complete": "Done - no patent shares half of the features",
    "failed": "Failed",
}


def matrix_rows(run) -> list[dict]:
    """Rows of the feature x patent grid, newest substitutions last."""
    return [
        {
            "feature": feature,
            "cells": [
                {"patent": patent, "present": run.cell(feature["id"], patent["id"])}
                for patent in run.patents
            ],
        }
        for feature in run.live_features
    ]


def create_app(runs_dir: Path | str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("DIFFERENTIATOR_SECRET",
                                              "differentiator-dev")
    store = RunStore(runs_dir or os.environ.get("DIFFERENTIATOR_RUNS",
                                                DEFAULT_RUNS_DIR))

    @app.context_processor
    def inject_labels():
        return {"status_labels": STATUS_LABELS, "terminal": list(TERMINAL_STATUSES)}

    @app.get("/")
    def index():
        return render_template("index.html", runs=store.list())

    @app.post("/runs")
    def create_run():
        invention = Invention(
            name=request.form.get("name", "").strip(),
            purpose=request.form.get("purpose", "").strip(),
            description=request.form.get("description", "").strip(),
        )
        try:
            run = store.create(invention)
        except StoreError as exc:
            flash(str(exc), "error")
            return render_template("index.html", runs=store.list(), draft=invention), 400
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
            rows=matrix_rows(run),
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
            "revision": run.revision,
            "status": run.status,
            "features": run.live_features,
            "patents": run.patents,
            "matrix": run.matrix,
            "iterations": run.iterations,
            "log": store.read_log(run_id, tail=50),
        }

    return app


app = create_app()
