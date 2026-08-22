# PatentLoop

Fully autonomous multi-agent loop: raw idea in → drafted provisional patent application or a
reasoned kill report out, with zero human intervention after submission. Every run terminates in
exactly one of three states: `DRAFTED`, `KILLED_SATURATED`, or `KILLED_INFEASIBLE`.

## Run it

CLI (prints the run folder path at the end):

```bash
python run.py --idea "your idea text here"
```

Web UI (single form + live agent log, futuristic dark theme):

```bash
./.venv/bin/uvicorn patentloop.server:app --host 0.0.0.0 --port 8100
# open http://localhost:8100
```

One POST also works: `POST /api/run {"idea": "..."}` streams NDJSON progress events and ends with
the result + artifact links.

Requires `OPENAI_API_KEY` in `.env`. Optional: `GITHUB_TOKEN` (raises GitHub search rate
limits), `PATENTLOOP_MODEL` (default `gpt-4o-mini`).

## Architecture

Orchestrator (`patentloop/orchestrator.py`) runs a stateful loop over five distinct agents, each a
separate callable with its own prompt, external data sources, and structured output schema:

1. **Research Agent** (`patentloop/agents/research.py`) — extracts 3–6 core technical elements
   (one LLM call), then live-searches **Semantic Scholar**, **arXiv**, and **GitHub** per element.
   An LLM judge grades the idea against only the retrieved abstracts (never from memory) and must
   cite what it found → `novelty_score` (0–100) + closest prior publications with links.
2. **Patent Search Agent** (`patentloop/agents/patents.py`) — queries **Google Patents**
   (US/EP/WIPO publications) with the same elements, then structurally maps which idea elements
   overlap which retrieved patent disclosures → `overlap_score` (0–100) + matched patents
   (id, title, assignee, link, overlapping text). Source chain: Serper.dev search scoped to
   patents.google.com when `SERPER_API_KEY` is set, else the Google Patents public JSON endpoint,
   else a DuckDuckGo search scoped to patents.google.com (Google rate-limits direct queries).
   (The USPTO PatentsView search API was the first choice but `search.patentsview.org` no longer
   resolves — the service was retired — so Google Patents is the live source.)
3. **Feasibility Gate** (`patentloop/agents/feasibility.py`) — two hard checks with full logged
   reasoning: *doable* (no physical/engineering violation, not a commoditised restatement) and
   *scoped* (concrete mechanism/structure/steps, not a broad aspiration). Failing either kills the
   run immediately.
4. **Expert Pivot Agent** (`patentloop/agents/pivot.py`) — role-prompted as a domain expert in the
   field inferred from the idea; proposes a concrete adjacent-gap variant and must explain, per
   colliding patent, why the variant avoids it. The variant re-enters the loop; lineage is tracked.
5. **Drafting Agent** (`patentloop/agents/drafting.py`) — only after all gates clear; writes the
   provisional-style application (title, field, background referencing the retrieved art, summary,
   detailed description, independent + dependent claims, "why this is novel", disclaimer).

Decision gate: novelty ≥ 60 and overlap ≤ 40 → draft; otherwise pivot; feasibility failure →
`KILLED_INFEASIBLE`. Saturation detector (in the orchestrator): iterations are capped at 4, and if
successive pivot proposals converge (cosine similarity ≥ 0.86 between their OpenAI embeddings)
while overlap stays ≥ 60, the run stops as `KILLED_SATURATED`.

## Verification — how each score is computed, from what real data

- `novelty_score`: the Research Agent's judge sees only documents actually retrieved from the
  Semantic Scholar / arXiv / GitHub APIs during the run (title + abstract + URL). The raw API
  responses for every query are stored in `trace.json` under
  `iterations[i].research.raw_responses`, so the number is traceable to specific documents.
- `overlap_score`: computed the same way over patents actually returned by Google Patents; the
  element-by-element overlap mapping (which idea element collides with which patent text) is in
  `iterations[i].patent_search.matched_patents`, raw API payloads alongside.
- Coverage matrix (`patentloop/coverage.py`): a deterministic, LLM-free element-by-patent matrix
  built per iteration with `build_matrix(elements, patents)` — pure keyword-overlap matching
  (`is_covered`) between each element's search terms and the patent title/abstract, with the
  matching sentence as evidence. `uncovered` lists elements no retrieved patent covers, i.e.
  where the idea's potential novelty lives. Stored in `trace.json` / `prior_art.json` under
  `coverage_matrix` and rendered in `report.md` per iteration.
- Cross-run memory (`patentloop/memory.py`): every run deposits the patents it retrieved into
  `runs/memory.json` (with embeddings); a new run recalls the most similar records by embedding
  cosine before searching live, and they enter the coverage matrix alongside live results. Each
  recalled record carries `source_run_id` + `similarity` (in `trace.json` under `memory_hits`
  and in `report.md` under "Recalled from earlier runs"), so runs provably build on each other —
  delete `runs/memory.json` and re-run to see the difference.
- Feasibility gate: the full chain of reasoning for both checks is logged verbatim in
  `iterations[i].feasibility_gate` and reproduced in `report.md` — never summarized away.
- The final `report.md` contains the complete iteration trace: every idea version, every score,
  every source consulted, every gate decision, so the run is auditable end to end.

## Artifacts per run (`runs/<run_id>/`)

- `report.md` — final verdict with full reasoning and the complete iteration trace.
- `prior_art.json` — structured research + patent results (including raw API responses) across
  all iterations.
- `draft_application.pdf` (+ `.md`) — the drafted provisional application (only if `DRAFTED`).
- `trace.json` — full agent-by-agent, iteration-by-iteration log for audit/demo.

---

# Patentability analyser (earlier prototype)

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
