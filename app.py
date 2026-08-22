"""FastAPI server exposing the patentability analysis pipeline."""

from __future__ import annotations

import json
import queue
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import agent_log
from coverage import build_matrix
from decompose import decompose_invention
from examine import judge_patentability
from patent_client import search_patents
from suggest import generate_revision, generate_suggestions

FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
PATENTS_PER_ELEMENT = 3
MAX_ITERATIONS = 3
HEARTBEAT_SECONDS = 2.0
MATRIX_KEYS = ("elements", "patents", "coverage", "uncovered")
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:4173",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:4173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
]

app = FastAPI(title="Patentability analyser")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyseRequest(BaseModel):
    description: str = Field(min_length=1)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _upstream_message(exc: Exception) -> str:
    """First line of an upstream error, so quota/auth causes survive to the client."""
    text = str(exc).strip().splitlines()
    return text[0] if text else exc.__class__.__name__


def _collect_patents(elements: list[dict]) -> list[dict]:
    queries = []
    for element in elements:
        query = " ".join(element.get("search_terms") or []) or element.get("text") or ""
        if query.strip():
            queries.append(query)
    if not queries:
        return []

    # The searches run on pool threads but belong to the caller's transcript,
    # which a worker thread does not inherit.
    run = agent_log.current_run()

    def search(query: str) -> list[dict]:
        with agent_log.using(run):
            return search_patents(query, PATENTS_PER_ELEMENT)

    with ThreadPoolExecutor(max_workers=min(len(queries), 8)) as pool:
        per_query = list(pool.map(search, queries))

    patents: list[dict] = []
    seen: set[str] = set()
    for results in per_query:
        for patent in results:
            key = patent.get("patent_id") or patent.get("title")
            if not key or key in seen:
                continue
            seen.add(key)
            patents.append(patent)
    return patents


def _run_pipeline(description: str, progress: "queue.Queue[str] | None" = None) -> dict[str, Any]:
    def note(stage: str) -> None:
        agent_log.note(stage)
        if progress is not None:
            progress.put(stage)

    note("decomposing the invention into functional elements")
    try:
        elements = decompose_invention(description)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"decomposition failed: {_upstream_message(exc)}"
        ) from exc

    note(f"searching prior art for {len(elements)} elements")
    patents = _collect_patents(elements)

    note(f"building the coverage matrix over {len(patents)} references")
    matrix = build_matrix(elements, patents)

    note("generating patentability suggestions")
    try:
        suggestions = generate_suggestions(matrix, description)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"suggestion failed: {_upstream_message(exc)}"
        ) from exc

    note("asking the examiner for a verdict")
    try:
        verdict = judge_patentability(matrix, description)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"examination failed: {_upstream_message(exc)}"
        ) from exc

    return {**matrix, "suggestions": suggestions, "verdict": verdict}


def _run_iterations(description: str, progress: "queue.Queue[str] | None" = None) -> dict[str, Any]:
    """Analyse, then revise and re-analyse until the examiner allows the invention.

    Stops at the first patentable verdict or after :data:`MAX_ITERATIONS` rounds.
    The last iteration's analysis is repeated at the top level, so a caller that
    only wants the outcome can ignore the history.
    """

    def note(stage: str) -> None:
        agent_log.note(stage)
        if progress is not None:
            progress.put(stage)

    iterations: list[dict[str, Any]] = []
    current = description
    changes: str | None = None

    for index in range(MAX_ITERATIONS):
        note(f"iteration {index + 1} of {MAX_ITERATIONS}: analysing the description")
        analysis = _run_pipeline(current, progress)
        iterations.append(
            {"iteration": index + 1, "description": current, "changes": changes, **analysis}
        )
        if analysis["verdict"]["patentable"] or index == MAX_ITERATIONS - 1:
            break

        note(f"iteration {index + 1}: revising the invention around the blocking art")
        try:
            revision = generate_revision(
                {key: analysis[key] for key in MATRIX_KEYS},
                current,
                analysis["verdict"],
                analysis["suggestions"],
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"revision failed: {_upstream_message(exc)}"
            ) from exc
        current = revision["description"]
        changes = revision["changes"]

    final = iterations[-1]
    return {
        **{key: final[key] for key in MATRIX_KEYS},
        "suggestions": final["suggestions"],
        "verdict": final["verdict"],
        "description": final["description"],
        "iterations": iterations,
    }


def _analyse(description: str, progress: "queue.Queue[str] | None" = None) -> dict[str, Any]:
    """Run the analysis inside an Entire transcript and return it with the log."""
    run = agent_log.start_run(description[:200])
    try:
        result = _run_iterations(description, progress)
    finally:
        agent_log.finish_run(run)
    return {**result, "run_id": run.run_id, "log": run.entries}


@app.post("/api/analyse")
def analyse(request: AnalyseRequest) -> dict[str, Any]:
    description = request.description.strip()
    if not description:
        raise HTTPException(status_code=422, detail="description must not be empty")
    return _analyse(description)


@app.get("/api/logs/{run_id}")
def run_log(run_id: str) -> dict[str, Any]:
    """The recorded asks and outputs of an earlier run."""
    entries = agent_log.read_run(run_id)
    if not entries:
        raise HTTPException(status_code=404, detail=f"no transcript for run {run_id}")
    return {"run_id": run_id, "log": entries}


def _stream_events(description: str) -> Iterator[str]:
    """NDJSON progress events, then one result or error event.

    The heartbeat keeps proxies from timing out a run that takes longer than
    their idle read timeout (60s on the preview tunnel).
    """
    progress: queue.Queue[str] = queue.Queue()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_analyse, description, progress)
        stage = "starting"
        while True:
            try:
                stage = progress.get(timeout=HEARTBEAT_SECONDS)
            except queue.Empty:
                pass
            yield json.dumps({"event": "progress", "stage": stage}) + "\n"
            if future.done() and progress.empty():
                break
        try:
            yield json.dumps({"event": "result", "result": future.result()}) + "\n"
        except HTTPException as exc:
            yield json.dumps({"event": "error", "detail": str(exc.detail)}) + "\n"
        except Exception as exc:  # noqa: BLE001 - surfaced to the client as an event
            yield json.dumps({"event": "error", "detail": _upstream_message(exc)}) + "\n"


@app.post("/api/analyse/stream")
def analyse_stream(request: AnalyseRequest) -> StreamingResponse:
    description = request.description.strip()
    if not description:
        raise HTTPException(status_code=422, detail="description must not be empty")
    return StreamingResponse(
        _stream_events(description),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
