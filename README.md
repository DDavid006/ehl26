# Patentability analyser

Modules:

- `patent_client.py` — `search_patents(query, limit)`: the model searches the web itself and
  reports publications as JSON, restricted to patents.google.com / worldwide.espacenet.com.
  Records without a well-formed publication number are dropped, so an invented id cannot enter
  the matrix. `fallback_corpus.json` is used when fewer than three records come back.
- `llm.py` — every model call goes through here. `generate_text(prompt, error_cls, task)` for
  reasoning and `search_text(prompt, error_cls, task)` for the OpenAI Responses API with its
  hosted `web_search` tool. `LLM_PROVIDER=openai` (default) or `gemini` picks the backend for
  generation; searching is OpenAI only. Both fall through to the next model in the list when one
  is rate limited, retired or overloaded, and both record the exact ask and the raw output.
- `agent_log.py` — one transcript per analysis in `.entire/agent-logs/<run_id>.jsonl`: a line per
  model exchange with the task, the prompt as sent, the model's raw answer and any error. When
  the run ends the transcript is handed to Entire (`entire session attach <run_id> --agent
  patentability`) so the asks are checkpointed against the repository's history; a failed attach
  is recorded in the transcript rather than raised.
- `tools/entire-agent-patentability` — the external agent plugin Entire uses to read those
  transcripts (`info`, `read-session`, `read-transcript`, `extract-prompts`, …). Entire discovers
  it by name on `$PATH`; the app puts `tools/` there when it attaches.
- `decompose.py` — `decompose_invention(description)`: model-based split into 4-8 functional
  elements.
- `coverage.py` — `build_matrix(elements, patents)` and the swappable `is_covered(element,
  patent)`; `uncovered` lists elements no patent covers.
- `suggest.py` — `generate_suggestions(matrix, description)`: 2-3 grounded patentability
  suggestions, and `generate_revision(matrix, description, verdict, suggestions)`: a rewritten
  invention description that designs around the blocking art.
- `examine.py` — `judge_patentability(matrix, description)`: examiner verdict
  `{"patentable": bool, "reasoning": str}` over the coverage matrix.
- `app.py` — FastAPI server: `POST /api/analyse`, `POST /api/analyse/stream` (same pipeline,
  emitting NDJSON progress events so proxies do not time out a long run), `GET /health`, static
  frontend from `frontend/dist`.

  Each analysis loops: decompose → search → matrix → suggestions → examiner. A `patentable: false`
  verdict triggers a revised description, which is re-analysed; at most three iterations, stopping
  early on the first `patentable: true`. The response carries the final analysis at the top level
  (`elements`, `patents`, `coverage`, `uncovered`, `suggestions`, `verdict`, `description`) plus
  `iterations`, each with its description, what changed, matrix, suggestions and verdict, and the
  run's `run_id` and `log`. `GET /api/logs/{run_id}` replays the transcript of an earlier run.
- `frontend/dist/index.html` — single-page UI: examiner verdict, iteration timeline (per-round
  changes, description, reasoning and matrix), coverage matrix (elements as rows, patents as
  columns, evidence on hover, uncovered cells in bright green) plus suggestion cards. No build
  step required.

## Setup

Put your keys in `.env` (gitignored):

```
OPENAI_API_KEY=...
GEMINI_API_KEY=...
LLM_PROVIDER=openai
```

Only the key for the selected `LLM_PROVIDER` is needed, except that patent search always uses
`OPENAI_API_KEY`. Optional: `GEMINI_MODEL` / `OPENAI_MODEL` override the model candidate lists
(comma separated, tried in order), `GEMINI_TIMEOUT` / `OPENAI_SEARCH_TIMEOUT` the per-request
timeouts, `ENTIRE_AGENT_LOG_DIR` the transcript directory, and `ENTIRE_ATTACH=0` skips the
Entire attach (for runs outside a checkout, or when the CLI is not logged in).

## Transcripts in Entire

Every ask and answer is on disk regardless of Entire; `.entire/settings.json` already enables
the external agent plugin, so a logged-in CLI picks each run up as a session:

```bash
entire login
entire session info <run_id>       # PATH must contain ./tools
PATH=$PWD/tools:$PATH entire session attach <run_id> --agent patentability
```

## Run locally

```bash
./run.sh
```

That creates `.venv`, installs `requirements.txt`, builds `frontend/` if present, and serves
everything on http://localhost:8000 (frontend at `/`, API at `/api/analyse`).

Equivalent manual steps:

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
```

Example request:

```bash
curl -s localhost:8000/api/analyse -H 'Content-Type: application/json' \
  -d '{"description": "A leave-on foam that delivers sunscreen to the scalp through dense hair."}'
```

## Tests

```bash
./.venv/bin/python -m pytest -q
```
