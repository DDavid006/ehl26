---
name: espacenet-differentiation
description: Break an invention description into features and materials, map them against Espacenet patents in a feature-by-patent matrix, and substitute duplicated features until no patent shares more than half of them. Use when the user wants an idea differentiated from existing European patents.
---

# Espacenet differentiation

Runs a multi-agent dynamic workflow over one invention description:

1. **extract** — one agent turns the name, purpose and description into a list
   of claim-element-like features, each tagged `feature` or `material`.
2. **search** — one Espacenet searcher per feature, in parallel. Each opens the
   documents it reports and quotes the disclosing claim or passage.
3. **matrix** — one agent fills the feature × patent grid over every feature and
   every patent any searcher found, checking pairs no searcher covered.
4. **similarity** (first child) — finds the patent sharing the most features and
   reports `overlap_ratio`. At or below `OVERLAP_THRESHOLD` (half) the run ends.
5. **substitute** (second child) — replaces exactly one shared feature with a
   plausible non-overlapping alternative, then the new feature is searched and
   the matrix refreshed, and the similarity child runs again.

Steps 4 and 5 alternate for up to `MAX_ROUNDS` rounds. The final feature list
keeps the substituted features marked `new`, so what changed is visible.

## How to run

Normally the GUI does this for you: `python -m flask --app differentiator.app run`,
submit the invention, and the run page writes
`diff-runs/<run_id>/workflow.py` with `INVENTION` and the `GUI_*` constants
already bound. Then call `run_workflow` with
`workflow_name="espacenet-differentiation"` and `script_path` pointing at that
generated file — not at this skill's copy — so progress lands in the GUI.

To run it without the GUI, edit `INVENTION` in this directory's `workflow.py`,
leave `GUI_RUN_ID` empty (GUI pushes become no-ops), and point `run_workflow` at
it.

If a run times out or is interrupted, re-run with the reported `run_id`:
completed agents replay instead of re-searching.

## Limits

- Espacenet only, through its public search UI — no OPS API key, so results are
  what the agents can read in the browser.
- Overlap is judged by agents reading claims, not by claim charting, and this is
  a screening pass rather than a legal opinion.
- Substitution changes one feature per round on purpose; a heavily overlapping
  idea can exhaust `MAX_ROUNDS` and end `failed`.
