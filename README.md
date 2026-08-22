# Patentability analyser

Modules:

- `patent_client.py` — `search_patents(query, limit)`: Serper web search filtered to
  patents.google.com / worldwide.espacenet.com. Records are built from the search results (id
  from the URL, title and abstract from the result title and snippet); patent pages are never
  fetched because those hosts block server-side requests. `fallback_corpus.json` is used when
  fewer than three results come back.
- `agents.py` — `run_agent(prompt, tools, ...)`: the tool-calling loop. The model chooses which
  tools to call and how often (hard-capped); tool errors are handed back to it rather than
  raised. Tool use needs `LLM_PROVIDER=openai`; under `gemini` an agent degrades to one plain
  call with no tools.
- `searcher.py` — `find_prior_art(element)`: one searcher agent per element, phrasing its own
  queries instead of using the applicant's `search_terms` verbatim; falls back to a plain
  keyword search if it runs none.
- `llm.py` — `generate_text(prompt, error_cls)`: every non-agentic model call goes through here.
  `LLM_PROVIDER=gemini` (default) or `openai` picks the backend; both fall through to the next
  model in the list when one is rate limited, retired or overloaded.
- `decompose.py` — `decompose_invention(description)`: model-based split into 4-8 functional
  elements.
- `coverage.py` — `build_matrix(elements, patents)` and the swappable `is_covered(element,
  patent)`; `uncovered` lists elements no patent covers.
- `suggest.py` — `generate_suggestions(matrix, description)`: 2-3 grounded patentability
  suggestions, and `generate_revision(matrix, description, verdict, suggestions)`: a rewritten
  invention description that designs around the blocking art.
- `examine.py` — `judge_patentability(matrix, description)`: examiner verdict
  `{"patentable": bool, "reasoning": str}`. The examiner is an agent: it can run its own
  `search_prior_art` searches on the uncovered elements before ruling, because the matrix was
  built from the applicant's keywords.
- `app.py` — FastAPI server: `POST /api/analyse`, `POST /api/analyse/stream` (same pipeline,
  emitting NDJSON progress events so proxies do not time out a long run), `GET /health`, static
  frontend from `frontend/dist`.

  Each analysis loops: decompose → search → matrix → suggestions → examiner. A `patentable: false`
  verdict triggers a revised description, which is re-analysed; at most three iterations, stopping
  early on the first `patentable: true`. The response carries the final analysis at the top level
  (`elements`, `patents`, `coverage`, `uncovered`, `suggestions`, `verdict`, `description`) plus
  `iterations`, each with its description, what changed, matrix, suggestions and verdict.
- `frontend/dist/index.html` — single-page UI: live agent activity log, examiner verdict,
  iteration timeline (per-round
  changes, description, reasoning and matrix), coverage matrix (elements as rows, patents as
  columns, evidence on hover, uncovered cells in bright green) plus suggestion cards. No build
  step required.

## Setup

Put your keys in `.env` (gitignored):

```
SERPER_API_KEY=...
GEMINI_API_KEY=...
OPENAI_API_KEY=...
LLM_PROVIDER=openai
```

Only the key for the selected `LLM_PROVIDER` is needed. Optional: `GEMINI_MODEL` /
`OPENAI_MODEL` override the model candidate lists (comma separated, tried in order),
`GEMINI_TIMEOUT` the per-request timeout.

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
