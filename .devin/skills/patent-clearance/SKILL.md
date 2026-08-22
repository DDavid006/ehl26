---
name: patent-clearance
description: Check a patent idea against US patents for infringement/novelty problems, redesign around blocking claims, and draft a provisional patent application. Use when the user gives an invention idea and wants it cleared and/or drafted.
---

# Patent clearance and drafting

Runs a multi-agent dynamic workflow over one invention idea:

1. **search** — five parallel prior-art agents hit different sources (USPTO Patent
   Public Search full text, CPC classification sweep, Google Patents semantic +
   citation graph, competitor/assignee portfolios, non-patent literature). Each
   reports verified references only.
2. **assess** — one agent does a claim-element comparison over all findings and
   returns `clear` or `blocked`, naming the blocking claims and which features
   read on them.
3. **redesign** (only if blocked) — a researcher checks whether the idea is
   technically plausible at all, replaces every infringing feature with a
   non-infringing alternative, and adds new features. The revised idea goes back
   through step 1.
4. **draft** (only if clear) — an agent writes a full provisional-application
   markdown draft (spec, embodiments, numbered claims, abstract, prior-art
   section) and pushes it to a branch of the repo named in `REPO`.

Up to `MAX_ROUNDS` search/assess/redesign rounds; if still blocked at the end,
no draft is produced and the reason is logged.

## How to run

1. Edit the `IDEA` dict at the top of `workflow.py`: `title`, `description`,
   `features` (one claim-element-like feature per entry), `field`. Adjust `REPO`
   if the drafts should go elsewhere.
2. Call `run_workflow` with `workflow_name="patent-clearance"` and
   `script_path` pointing at this directory's `workflow.py`.
3. If the run times out or is interrupted, re-run with the reported `run_id` —
   completed agents replay instead of re-searching.

Keep `IDEA` as literal text in the file: the workflow must stay deterministic so
resumes replay correctly. One idea per run.

## Limits

- Agents search public sources; this is a screening pass, not a legal opinion,
  and it does not cover foreign patents unless you add an angle for them.
- Nothing is filed with the USPTO. The output is a draft for a human attorney.
- Only US patents/applications are treated as infringement risk; non-patent
  literature is reported for novelty only.
