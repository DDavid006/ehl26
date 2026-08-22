# ehl26

Two multi-agent workflows over one invention idea, each with its own web GUI:

- **patent clearance and drafting** (`gui/`, `.devin/skills/patent-clearance/`) —
  US prior-art search, a freedom-to-operate verdict, redesign, and a drafted
  provisional application.
- **Espacenet differentiation** (`differentiator/`,
  `.devin/skills/espacenet-differentiation/`) — feature extraction, a feature ×
  patent overlap matrix built from Espacenet, and a substitution loop that keeps
  swapping duplicated features until no patent shares more than half of them.

## Patent clearance

For one invention idea:

1. **search** — five parallel prior-art agents hit different sources (USPTO
   Patent Public Search full text, CPC classification sweep, Google Patents
   semantic + citation graph, competitor/assignee portfolios, non-patent
   literature). Each reports only references it actually opened.
2. **assess** — one agent does a claim-element comparison and returns `clear`
   or `blocked`, naming the blocking claims and the features that read on them.
3. **redesign** (only if blocked) — a researcher checks whether the idea is
   technically plausible, replaces every infringing feature with a
   non-infringing alternative, adds new features, and the revised idea goes
   back through step 1.
4. **draft** (only if clear) — an agent writes a provisional-application draft
   (spec, embodiments, numbered claims, abstract, prior-art section) and pushes
   it to a branch.

Nothing is filed with the USPTO. The output is a screening pass over public US
sources plus a draft for a human attorney.

## Layout

- `.devin/skills/patent-clearance/` — the workflow (`workflow.py`) and its
  `SKILL.md`. Run it with the `run_workflow` tool.
- `gui/` — Flask app: submit an idea, watch a run, read the verdict, blocking
  references, redesign and drafted claims.
- `differentiator/` — Flask app for the Espacenet differentiation run, plus its
  progress CLI.
- `runs/<run_id>/`, `diff-runs/<run_id>/` — per-run state (git-ignored):
  the submitted idea, `state.json`, `workflow.py` (the skill workflow with the
  submission substituted in), and `run.log`.

## Running the GUI

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m flask --app gui.app run --port 5000
```

Submitting the form creates a queued run and writes that run's `workflow.py`.
The agent fan-out is driven by the `run_workflow` tool rather than by the web
process, so progress is pushed back into the GUI through the CLI:

```bash
python -m gui.cli status <run_id> running --workflow-run-id wfr-...
python -m gui.cli round  <run_id> --file round1.json   # assess output (+ optional "redesign" key)
python -m gui.cli draft  <run_id> --file draft.json    # drafter output
python -m gui.cli log    <run_id> "5 searchers dispatched"
```

The run page polls `/runs/<run_id>/state` every 5s, so a live run updates
without a reload.

## Espacenet differentiation

Submit the item's **name**, **purpose** and **description**; the agents take it
from there:

1. **extract** — one agent turns the description into features and materials.
2. **search** — one Espacenet searcher per feature, in parallel, reporting only
   documents it opened.
3. **matrix** — one agent fills the feature × patent grid. On the run page a
   green cell means that patent does *not* contain the feature, gray means it
   does.
4. **similarity** (first child) — finds the patent sharing the most features. At
   or below half, the run is done.
5. **substitute** (second child) — replaces one shared feature with a plausible
   non-overlapping alternative, the new feature is searched and the matrix
   refreshed, and the similarity child runs again.

The final feature list marks substituted features as `new`, and the run page
keeps a live log of what the agents are doing.

```bash
.venv/bin/python -m flask --app differentiator.app run --port 5001
```

Progress is pushed back from the workflow through its own CLI:

```bash
python -m differentiator.cli status       <run_id> searching --workflow-run-id wfr-...
python -m differentiator.cli features     <run_id> --file features.json
python -m differentiator.cli matrix       <run_id> --file matrix.json
python -m differentiator.cli similarity   <run_id> --file similarity.json
python -m differentiator.cli substitution <run_id> --file substitution.json
python -m differentiator.cli log          <run_id> "opening EP1234567A1"
```

Per-run state lives in `diff-runs/<run_id>/` (git-ignored) and the run page
polls `/runs/<run_id>/state` every 3s.

## Tests

```bash
.venv/bin/python -m pytest -q
```
