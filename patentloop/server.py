"""FastAPI server for PatentLoop: one POST starts a run; NDJSON streams the
live agent log; artifacts are served from the run folder."""

from __future__ import annotations

import json
import queue
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .orchestrator import run_loop

WEB_DIR = Path(__file__).resolve().parent / "web"
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
HEARTBEAT_SECONDS = 3.0

app = FastAPI(title="PatentLoop")


class RunRequest(BaseModel):
    idea: str = Field(min_length=1)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _stream(idea: str) -> Iterator[str]:
    events: "queue.Queue[dict[str, Any]]" = queue.Queue()

    def progress(event: str, data: dict[str, Any]) -> None:
        events.put({"event": event, **data})

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_loop, idea, RUNS_DIR, progress)
        while True:
            try:
                item = events.get(timeout=HEARTBEAT_SECONDS)
                yield json.dumps(item, default=str) + "\n"
            except queue.Empty:
                yield json.dumps({"event": "heartbeat"}) + "\n"
            if future.done() and events.empty():
                break
        try:
            result = future.result()
            yield json.dumps({"event": "result", **result}, default=str) + "\n"
        except Exception as exc:  # noqa: BLE001 - surfaced to the client as an event
            yield json.dumps({"event": "error", "detail": str(exc)[:500]}) + "\n"


@app.post("/api/run")
def run(request: RunRequest) -> StreamingResponse:
    idea = request.idea.strip()
    if not idea:
        raise HTTPException(status_code=422, detail="idea must not be empty")
    return StreamingResponse(
        _stream(idea),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{run_id}/{artifact}")
def artifact(run_id: str, artifact: str) -> FileResponse:
    allowed = {"report.md", "prior_art.json", "trace.json", "draft_application.pdf", "draft_application.md"}
    if artifact not in allowed or "/" in run_id or ".." in run_id:
        raise HTTPException(status_code=404, detail="unknown artifact")
    path = RUNS_DIR / run_id / artifact
    if not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(str(path))


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
