# PatentLoop

PatentLoop is an unattended feasibility, prior-art, overlap, pivot, and
provisional-drafting pipeline. A single idea trigger ends in exactly one of
`DRAFTED`, `KILLED_SATURATED`, or `KILLED_INFEASIBLE`.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export DEVIN_API_KEY=...
# Or use PATENTLOOP_BACKEND=openai with OPENAI_API_KEY.
export USPTO_ODP_API_KEY=...  # optional when Devin patent-search fallback is available
.venv/bin/python run.py --idea "A concrete mechanism with sensors and method steps"
```

`run.py` also accepts `--idea-file`, `--max-iterations`, and `--run-id`. It
prints the verdict and run folder last. Missing required keys fail before live
work begins; no canned or synthetic records are used.

The default judge backend is Devin (`PATENTLOOP_BACKEND=devin`). Each call
creates a Devin v1 session, polls it to completion, validates its JSON Schema
output, and stores session id, URL, request, and raw poll responses under
`llm/`. `PATENTLOOP_BACKEND=openai` selects the OpenAI-compatible alternative.
Patent search uses USPTO ODP when `USPTO_ODP_API_KEY` is set; otherwise five
role-prompted Devin browser sessions run in parallel across full-text,
classification, semantic/citation, assignee-portfolio, and
non-patent-literature search angles. Each browser agent must open and report
the real records it uses. If neither path is configured, the run fails fast.

Embeddings never require an API key: PatentLoop lazily downloads and caches
the CPU `sentence-transformers` `all-MiniLM-L6-v2` model. The first run needs
network access and may be warmed up explicitly:

```bash
.venv/bin/python -c "from patentloop.embed import embed; embed(['warm up'])"
```

The model cache is configurable with `PATENTLOOP_MODEL_CACHE`. Recommendation:
preinstall/cache this model in the environment blueprint for reproducible
hackathon startup, but the blueprint is intentionally unchanged here.

To run the two sequential live proof cases with no arguments:

```bash
scripts/run_proof_runs.sh
```

The script reads the exact ideas from `scripts/ideas/`, invokes `run.py` for
each case through the configured live backend, and prints each resulting run
folder. It does not select or assume a verdict. Set `PATENTLOOP_RUNS_DIR` to
use a different artifact directory.

Devin sessions are visible in the session list by default. Set
`DEVIN_UNLISTED=true` only when unlisted sessions are preferred.

## Web UI

```bash
.venv/bin/python -m flask --app patentloop.web.app run --port 5000
```

`POST /api/runs` with `{"idea": "..."}` is the only trigger. Progress is
available from `/api/runs/<id>/events`; live staff assignments are available
from `/api/runs/<id>/staff`; a drafted PDF is downloaded from
`/api/runs/<id>/download`.

## Scores and gates

For every extracted element, PatentLoop searches Semantic Scholar, arXiv,
OpenAlex, Crossref, and optional GitHub. Documents without abstracts are
discarded. For element embedding `e` and each of its top-ten document
embeddings `d`, `element_novelty(e) = 1 - max(cos(e, d))`.
`novelty_score = round(100 * (0.5 * mean(element_novelty) + 0.5 *
min(element_novelty)))`; the minimum term prevents one fully-covered element
being averaged away.

USPTO ODP full-text/claim search (and optional EPO OPS) ranks hits by embedding
similarity. Claim mappings are weighted `maps=1.0`, `partial=0.5`, `none=0`.
For each patent, `patent_overlap = sum(weights) / n_elements`, and
`overlap_score = round(100 * max(patent_overlap))`; the runner-up is retained.
Claim quotes must be literal substrings of retrieved claims, and citation ids
must belong to retrieved documents.

The feasibility gate records two independent LLM judgments (`doable` and
`scoped`) plus structural rule signals; a failed judgment or element-count
hard-fail yields `KILLED_INFEASIBLE`. Otherwise, `novelty_score >= 55` and
`overlap_score <= 45` yield `DRAFTED`. Other iterations pivot. A pivot is
saturated when cosine similarity to the previous pivot is greater than `0.88`
and overlap is at least `55` in two consecutive iterations, or the fifth
iteration is reached with overlap above the gate.

## Audit artifacts

Each `runs/<run_id>/` contains `report.md`, `prior_art.json`, `trace.json`,
and (only for `DRAFTED`) `draft_application.md` and
`draft_application.pdf`. Untouched source responses are written to
`raw/<iteration>/<source>_<hash>.json`; prompts and raw LLM completions are
written to `llm/<sequence>_<agent>.json`. Every normalized record stores its
source and raw path. `trace.json` records ordered agent events, input digests,
artifact paths, LLM log paths, and Devin session URLs, allowing every report
number to be followed back to retrieved data. `company.json` is an atomic,
continuously updated program-manager board containing each assignment's role,
status, duration, session link, and usage when supplied by the backend; the
same snapshot is included in trace events and the report's Team table.

## Tests

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q patentloop run.py
```

All PatentLoop tests mock HTTP and LLM calls; the live source path is never
replaced by fake data.
