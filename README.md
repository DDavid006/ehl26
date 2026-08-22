# PatentLoop

An autonomous multi-agent loop that takes a raw patent idea as plain text and,
with no human input after the trigger, ends in exactly one of three states:

| state | meaning | artifact |
| --- | --- | --- |
| `DRAFTED` | idea is novel, unblocked, feasible and claimable | `draft_application.md` |
| `KILLED_SATURATED` | every pivot kept landing on existing claims | `report.md` |
| `KILLED_INFEASIBLE` | idea is not doable, or too broad to claim | `report.md` |

There is no fourth state in which a human is asked to decide anything.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/python run.py --idea "A solid-state lithium cell whose garnet electrolyte is laser-textured ..."
# ...
# outcome: DRAFTED
# artifacts: /path/to/runs/20260822-183012-a91f0c
```

Optional single-page trigger with a live agent log (same orchestrator, still
unattended once submitted):

```bash
.venv/bin/python -m patentloop.web     # http://127.0.0.1:5001
```

## The loop

```
[idea text]
   |
   v
ORCHESTRATOR (patentloop/orchestrator.py) — tracks iteration count and idea lineage v1 -> v2 -> ...
   |
   1. RESEARCH AGENT        arXiv + Semantic Scholar + GitHub -> novelty_score, cited documents
   2. PATENT SEARCH AGENT   PatentsView + Google Patents + EPO OPS -> overlap_score, colliding claims
   3. FEASIBILITY GATE      doable? scoped? -> fail = KILLED_INFEASIBLE, immediately, no pivot
   4. DECISION GATE         novel & unblocked -> DRAFTING AGENT -> DRAFTED
                            blocked          -> EXPERT PIVOT AGENT -> new idea version -> back to 1
                            pivots converged -> KILLED_SATURATED
                            iteration cap    -> KILLED_SATURATED
```

Each agent is a separate callable unit with its own system prompt, its own data
sources and its own structured output (`patentloop/schemas.py`); the
orchestrator reads only those structured fields, so no single LLM call decides a
run's outcome.

| module | role | external data |
| --- | --- | --- |
| `agents/research.py` | element extraction + novelty scan | arXiv Atom API, Semantic Scholar Graph API, GitHub repo search |
| `agents/patent_search.py` | claim-overlap / FTO scan | PatentsView Search API, Google Patents full text + claim pages, EPO OPS |
| `agents/feasibility.py` | hard gate: doability + claim scope | reuses the retrieved literature for the commoditization judgement |
| `agents/pivot.py` | domain-expert redesign around blocking claims | the specific colliding claim text |
| `agents/drafting.py` | provisional application draft | the run's own dossier only |

## Verification: how every number is produced

The point of the system is that its self-check is external and inspectable. No
score is "the model's opinion of itself"; each one is derived from documents
that were fetched during the run and stored next to the report.

### `novelty_score` (0-100, research agent)

1. An LLM call extracts 3-6 **claim elements** and one literature query per
   element.
2. Each query is run against arXiv, Semantic Scholar and GitHub. Failures
   (e.g. Semantic Scholar rate limiting) are recorded as `api_error` events —
   the agent never substitutes remembered citations for retrieved ones.
3. An LLM call scores every element **only against the retrieved titles and
   abstracts**, and must return the ids of the documents it relied on. Ids that
   were not in the supplied catalogue are discarded.
4. The same element is scored again deterministically:
   `lexical_similarity = max tf-idf cosine(element, retrieved title+abstract)`
   over the run's own corpus (`patentloop/textsim.py`, no embedding service, so
   it is recomputable offline from `prior_art.json`).
5. `similarity = 0.6 * llm_similarity + 0.4 * 100 * lexical_similarity`
6. `novelty_score = 100 - (0.6 * worst element similarity + 0.4 * mean element similarity)`

### `overlap_score` (0-100, patent search agent)

1. The same extracted elements (plus the idea title) become patent queries;
   they are run against PatentsView (if `PATENTSVIEW_API_KEY` is set), Google
   Patents full text, and EPO OPS (if `EPO_OPS_KEY`/`EPO_OPS_SECRET` are set).
2. Hits are deduplicated and ranked by tf-idf closeness to the idea; for the
   top hits the **verbatim claim text is fetched** (PatentsView `g_claim`
   endpoint or the Google Patents page).
3. Per patent, an LLM call performs a claim-element comparison: for every
   element, does a claim read on it, which claim number, and quoting the claim.
   The output is a collision matrix, not a verdict.
4. `element_coverage = 100 * (distinct elements with reads_on = true) / (total elements)`
5. `lexical_overlap = max tf-idf cosine(idea + elements, each claim)`
6. `match_score = 0.7 * element_coverage + 0.3 * 100 * lexical_overlap`
7. `overlap_score = max(match_score)` over all claim-compared patents.

### Feasibility gate

One LLM call, two independent checks (doability against physical/engineering
constraints and commoditization; claim scope against "is a mechanism actually
recited"), each returning a boolean plus reasoning that must cite the
disclosure's own wording. Both reasoning strings are stored verbatim in
`trace.json` and reprinted in `report.md` — nothing is summarized away. Failing
either check ends the run immediately with `KILLED_INFEASIBLE`; there is no
pivot from an infeasible idea.

### Saturation detector (orchestrator, not an agent)

After each pivot the orchestrator compares the new pivot proposal with the
previous one using tf-idf cosine similarity, and looks at the overlap history.
A run stops as `KILLED_SATURATED` when overlap stayed `>= 45` for the last two
versions **and** successive pivot proposals are `>= 0.55` similar (the pivot
space is collapsing onto the same blocked territory), or when the iteration cap
(`--max-iterations`, default 4) is reached while still blocked. A run can
therefore never loop forever.

### Thresholds

`patentloop/config.py`: `NOVELTY_PASS = 55`, `OVERLAP_BLOCK = 45`,
`PIVOT_CONVERGENCE = 0.55`. The decision gate drafts only when
`overlap_score < 45 and novelty_score >= 55`; high overlap pivots; low novelty
with no blocking claim also pivots (published-but-unclaimed prior art).

## Artifacts per run (`runs/<run_id>/`)

| file | contents |
| --- | --- |
| `report.md` | verdict, reason, score trace per iteration, per-element score tables, colliding claim quotes, both feasibility reasonings, every gate decision, the pivot chain |
| `prior_art.json` | every retrieved publication and patent, per-element similarity scores, claim-collision matrices, all queries, per iteration |
| `draft_application.md` | the provisional draft (only when `DRAFTED`) |
| `trace.json` | agent-by-agent event log: every API call (URL, status, timing, pointer to the raw body), every LLM system prompt / user prompt / raw completion / parsed output, every gate decision with its inputs, plus the idea lineage |
| `raw/` | the raw bytes of every external API response, referenced by `trace.json` |
| `run.log` | human-readable live log (this is what the web UI streams) |

An auditor can therefore recompute both scores from `prior_art.json` and
`raw/`, and read exactly why each gate decided what it decided, without the
system ever having asked a human anything.

## Configuration

| env var | required | effect |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | yes | agent reasoning; the run refuses to start without it |
| `PATENTLOOP_MODEL` | no | Anthropic model id (default `claude-sonnet-4-20250514`) |
| `PATENTLOOP_MAX_ITERATIONS` | no | pivot cap (default 4) |
| `SEMANTIC_SCHOLAR_API_KEY` | no | lifts Semantic Scholar rate limits (keyless access often returns 429) |
| `PATENTSVIEW_API_KEY` | no | enables the USPTO PatentsView Search API (free registration); without it USPTO coverage comes from Google Patents full text and the trace says so |
| `EPO_OPS_KEY` / `EPO_OPS_SECRET` | no | enables EP/WO coverage via EPO OPS; without them the trace records the gap |
| `GITHUB_TOKEN` | no | lifts GitHub search rate limits |

Sources that are unavailable are logged as `api_error` events in the trace and
listed in the report as "sources used", so a thin run is visible rather than
silently degraded.

## Tests

```bash
.venv/bin/python -m pytest -q
```

The orchestrator tests drive the loop with stubbed agents to prove the three
terminal states, the no-pivot-on-infeasible rule, the saturation detector and
the iteration cap; the source tests parse recorded API payload shapes. Live
end-to-end behaviour is demonstrated by the two committed demo runs below.

## Demo runs

`demo/` contains the artifacts of two real runs (see `demo/README.md`): one
narrow idea that survives the loop and is drafted, and one crowded/vague idea
that is killed. Same command, opposite verdicts, from live search results.

---

## Also in this repo: the `patent-clearance` Devin workflow

`.devin/skills/patent-clearance/` and `gui/` are a separate, earlier system: a
Devin dynamic workflow that fans out five prior-art agents and a Flask GUI to
submit and review those runs. It is driven by the `run_workflow` tool, not by
PatentLoop.

```bash
.venv/bin/python -m flask --app gui.app run --port 5000
python -m gui.cli status <run_id> running --workflow-run-id wfr-...
python -m gui.cli round  <run_id> --file round1.json
python -m gui.cli draft  <run_id> --file draft.json
python -m gui.cli log    <run_id> "5 searchers dispatched"
```

Nothing in either system is filed with a patent office; both produce drafting
aids for a human attorney, not legal advice.
