# ehl26

Patent clearance and drafting: a multi-agent workflow plus a web GUI for
submitting invention ideas and reviewing what the agents found.

## What it does

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
- `runs/<run_id>/` — per-run state (git-ignored): `idea.json`, `state.json`,
  `workflow.py` (the skill workflow with the submitted idea substituted in),
  and `run.log`.

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

## Tests

```bash
.venv/bin/python -m pytest -q
```
