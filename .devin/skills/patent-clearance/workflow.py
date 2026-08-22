"""Patent clearance + drafting workflow.

Fan-out prior-art searchers -> freedom-to-operate analyst -> either a patent
drafter (idea is clear) or a plausibility researcher that redesigns around the
blocking claims, then re-checks and drafts.

Edit IDEA below, then run with the `run_workflow` tool pointing at this file.
Everything else is deterministic so a run can be resumed by `run_id`.
"""

import asyncio
import json

# ---------------------------------------------------------------- inputs ----

IDEA = {
    "title": "REPLACE ME",
    "description": "REPLACE ME - one or two paragraphs describing the invention.",
    "features": [
        "REPLACE ME - each distinctive feature / claim element on its own line",
    ],
    "field": "REPLACE ME - technical field, e.g. 'wearable medical devices'",
}

# Repo the final drafts are pushed to.
REPO = "DDavid006/ehl26"

# Where drafts land inside the repo.
DRAFT_DIR = "patents"

# How many redesign rounds are allowed before giving up.
MAX_ROUNDS = 2

# Independent prior-art search angles, run in parallel.
SEARCH_ANGLES = [
    {
        "id": "uspto-fulltext",
        "detail": (
            "USPTO Patent Public Search (https://ppubs.uspto.gov/pubwebapp/ and "
            "https://patft.uspto.gov). Run keyword and phrase queries over granted "
            "US patents and published US applications."
        ),
    },
    {
        "id": "uspto-classification",
        "detail": (
            "CPC/USPC classification sweep: identify the most relevant CPC subclasses "
            "for the idea (use https://www.uspto.gov/web/patents/classification/ and "
            "CPC browsing on Google Patents), then review the busiest patents in those "
            "subclasses from the last 20 years."
        ),
    },
    {
        "id": "google-patents-semantic",
        "detail": (
            "Google Patents (https://patents.google.com) semantic/similar-document "
            "search using the full idea description as the query, including the "
            "'Similar Documents' and 'Cited By' graphs of the closest hits."
        ),
    },
    {
        "id": "assignee-competitors",
        "detail": (
            "Competitor sweep: identify companies active in this field and review their "
            "US portfolios by assignee on Google Patents / USPTO, focusing on live "
            "(in-force, not expired or abandoned) patents."
        ),
    },
    {
        "id": "non-patent-prior-art",
        "detail": (
            "Non-patent prior art: papers, standards, product docs, datasheets and "
            "public demos. This does not create infringement risk but it can destroy "
            "novelty, so report it separately."
        ),
    },
]

# --------------------------------------------------------------- metadata ---

META = {
    "name": "patent-clearance",
    "description": (
        "Parallel prior-art search of US patents, a freedom-to-operate call on the "
        "idea, redesign around any blocking claims, and a drafted provisional "
        "patent application pushed to a branch."
    ),
    "product": f"github.com/{REPO}",
    "phases": [
        {
            "title": "search",
            "detail": "parallel prior-art searchers, one per search angle",
            "count": len(SEARCH_ANGLES),
            "labels": [f"search-{a['id']}" for a in SEARCH_ANGLES],
        },
        {
            "title": "assess",
            "detail": "freedom-to-operate + novelty verdict over all search results",
            "count": 1,
            "labels": ["assess"],
        },
        {
            "title": "redesign",
            "detail": (
                "plausibility researcher: sanity-check feasibility, change the features "
                "that read on blocking claims, add new non-infringing features"
            ),
        },
        {
            "title": "draft",
            "detail": "draft the provisional patent application and push a branch",
            "count": 1,
            "labels": ["draft"],
        },
    ],
}

# ---------------------------------------------------------------- schemas ---

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "angle": {"type": "string"},
        "queries_used": {"type": "array", "items": {"type": "string"}},
        "hits": {
            "type": "array",
            "description": (
                "One entry per relevant reference: publication/patent number, title, "
                "assignee, status (in force / expired / abandoned / application), the "
                "independent claim elements that matter, and which of the idea's "
                "features they read on."
            ),
            "items": {"type": "string"},
        },
        "closest_reference": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["angle", "hits", "closest_reference", "notes"],
}

ASSESS_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["clear", "blocked"],
            "description": (
                "'blocked' if any live US claim plausibly reads on the idea as "
                "described, or if the idea is not novel enough to be patentable."
            ),
        },
        "blocking_references": {"type": "array", "items": {"type": "string"}},
        "infringing_features": {
            "type": "array",
            "description": "Features of the idea that read on a blocking claim.",
            "items": {"type": "string"},
        },
        "novelty_gaps": {"type": "array", "items": {"type": "string"}},
        "design_around_hints": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": [
        "verdict",
        "blocking_references",
        "infringing_features",
        "novelty_gaps",
        "design_around_hints",
        "reasoning",
    ],
}

REDESIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "features": {
            "type": "array",
            "description": "The full revised feature list, replacing the previous one.",
            "items": {"type": "string"},
        },
        "field": {"type": "string"},
        "removed_or_changed": {"type": "array", "items": {"type": "string"}},
        "added": {"type": "array", "items": {"type": "string"}},
        "plausibility": {
            "type": "string",
            "description": "Technical feasibility assessment of the revised idea.",
        },
        "plausible": {"type": "boolean"},
    },
    "required": [
        "title",
        "description",
        "features",
        "field",
        "removed_or_changed",
        "added",
        "plausibility",
        "plausible",
    ],
}

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "branch": {"type": "string"},
        "path": {"type": "string"},
        "independent_claim": {"type": "string"},
        "claim_count": {"type": "integer"},
        "summary": {"type": "string"},
    },
    "required": ["branch", "path", "independent_claim", "claim_count", "summary"],
}


# ----------------------------------------------------------------- stages ---


def idea_block(idea):
    return json.dumps(
        {
            "title": idea["title"],
            "description": idea["description"],
            "features": idea["features"],
            "field": idea["field"],
        },
        indent=2,
        sort_keys=True,
    )


async def search(angle, idea, round_no):
    return await agent(
        "You are a patent prior-art searcher. Use your browser to search real, "
        "public patent databases - do not rely on memory, and never invent a patent "
        "number. Every hit you report must be a document you actually opened.\n\n"
        f"Invention under review (round {round_no}):\n{idea_block(idea)}\n\n"
        f"Your assigned search angle: {angle['detail']}\n\n"
        "For each relevant reference, record: publication or patent number, title, "
        "assignee, current legal status, filing/priority and expiry dates if visible, "
        "the independent claim elements that matter, and which of the invention's "
        "features those elements read on. Report at most the 10 most relevant hits, "
        "closest first. If you find nothing relevant, say so explicitly rather than "
        "padding the list.",
        phase="search",
        schema=SEARCH_SCHEMA,
        label=f"search-{angle['id']}-r{round_no}",
    )


async def search_or_none(angle, idea, round_no):
    try:
        return await search(angle, idea, round_no)
    except WorkflowAgentError as exc:
        log(f"round {round_no}: search angle {angle['id']} failed: {exc}")
        return None


async def assess(idea, findings, round_no):
    return await agent(
        "You are a patent attorney doing a freedom-to-operate and patentability "
        "assessment. You are not filing anything; you are making a call on the "
        "record below.\n\n"
        f"Invention under review (round {round_no}):\n{idea_block(idea)}\n\n"
        "Prior-art search results from parallel searchers:\n"
        + json.dumps(findings, indent=2, sort_keys=True)
        + "\n\nDo a claim-element-by-claim-element comparison against the live US "
        "claims in the record. Verify any reference you rely on by opening it in "
        "your browser. Return verdict 'blocked' if a live US claim plausibly reads "
        "on the invention as described, or if the invention is anticipated/obvious "
        "in light of the record; otherwise 'clear'. When blocked, name the exact "
        "features that read on which claim of which reference, and give concrete "
        "design-around hints. Be conservative: an unverified reference is not a "
        "blocking reference.",
        phase="assess",
        schema=ASSESS_SCHEMA,
        label=f"assess-r{round_no}",
    )


async def redesign(idea, verdict, round_no):
    return await agent(
        "You are an R&D researcher working with patent counsel. An invention was "
        "found to have a clearance or novelty problem. Your job is to sanity-check "
        "whether the idea is technically plausible at all, then change the features "
        "that create the problem and add new features that strengthen it - without "
        "reading on the blocking claims.\n\n"
        f"Invention (round {round_no}):\n{idea_block(idea)}\n\n"
        "Counsel's assessment:\n"
        + json.dumps(verdict, indent=2, sort_keys=True)
        + "\n\nOpen the blocking references in your browser and read their "
        "independent claims before proposing changes. Then return the FULL revised "
        "invention: keep what is safe, replace every infringing feature with a "
        "concrete non-infringing alternative, and add at least two new features that "
        "are technically plausible and, as far as you can tell, not claimed by the "
        "blocking references. Set 'plausible' to false only if the invention cannot "
        "work as described on physical or economic grounds - explain why in "
        "'plausibility'. Do not water the invention down to something useless; if the "
        "only safe version is useless, say that in 'plausibility'.",
        phase="redesign",
        schema=REDESIGN_SCHEMA,
        label=f"redesign-r{round_no}",
    )


async def draft(idea, verdict, history):
    return await agent(
        "You are a patent agent drafting a US provisional patent application. The "
        "invention below has been cleared for drafting.\n\n"
        f"Invention:\n{idea_block(idea)}\n\n"
        "Clearance assessment:\n"
        + json.dumps(verdict, indent=2, sort_keys=True)
        + "\n\nClearance and redesign history:\n"
        + json.dumps(history, indent=2, sort_keys=True)
        + f"\n\nClone {REPO}, create a new branch, and write the application as a "
        f"single markdown file under `{DRAFT_DIR}/` named after the invention "
        "(lowercase, hyphenated). Structure it as: Title, Technical Field, "
        "Background (citing the prior art found, by number), Summary of the "
        "Invention, Detailed Description with at least one described embodiment and "
        "described figures, Claims (one independent claim plus dependent claims, "
        "numbered, single-sentence each, in standard US claim format), Abstract "
        "(under 150 words), and a Prior Art Considered section listing every "
        "reference with its number and why it does not read on the claims. Draft the "
        "independent claim to avoid the blocking claim elements identified during "
        "clearance. Add a clear note at the top that this is an AI-generated draft "
        "for attorney review and has not been filed.\n\n"
        "Commit and push the branch. Do NOT open a pull request. Report the branch "
        "name, the file path, the independent claim verbatim, and the total claim "
        "count.",
        phase="draft",
        schema=DRAFT_SCHEMA,
        label="draft",
        repos=[REPO],
    )


# ------------------------------------------------------------------- main ---


async def main():
    await register_workflow(META)

    idea = IDEA
    history = []

    for round_no in range(1, MAX_ROUNDS + 1):
        log(f"round {round_no}: searching prior art for '{idea['title']}'")

        findings = []
        results = await parallel(
            [
                (lambda a=angle: search_or_none(a, idea, round_no))
                for angle in SEARCH_ANGLES
            ]
        )
        for result in results:
            if isinstance(result, dict):
                findings.append(result)

        if not findings:
            log(f"round {round_no}: every search angle failed, aborting")
            return

        verdict = await assess(idea, findings, round_no)
        log(f"round {round_no}: verdict = {verdict['verdict']}")
        history.append(
            {
                "round": round_no,
                "idea_title": idea["title"],
                "verdict": verdict["verdict"],
                "blocking_references": verdict["blocking_references"],
                "infringing_features": verdict["infringing_features"],
            }
        )

        if verdict["verdict"] == "clear":
            result = await draft(idea, verdict, history)
            log(
                f"drafted {result['claim_count']} claims -> "
                f"{result['branch']}:{result['path']}"
            )
            return

        if round_no == MAX_ROUNDS:
            log(
                f"still blocked after {MAX_ROUNDS} rounds by "
                f"{verdict['blocking_references']}; no draft produced"
            )
            return

        revised = await redesign(idea, verdict, round_no)
        history[-1]["redesign"] = {
            "removed_or_changed": revised["removed_or_changed"],
            "added": revised["added"],
            "plausible": revised["plausible"],
        }
        if not revised["plausible"]:
            log(f"researcher rejected the idea as implausible: {revised['plausibility']}")
            return

        idea = {
            "title": revised["title"],
            "description": revised["description"],
            "features": revised["features"],
            "field": revised["field"],
        }
        log(f"round {round_no}: redesigned into '{idea['title']}'")


asyncio.run(main())
