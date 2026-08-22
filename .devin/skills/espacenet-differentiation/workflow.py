"""Espacenet differentiation workflow.

Extract the features and materials of an invention, search Espacenet for
patents that share at least one of them, build a feature x patent matrix, then
loop two child agents - a similarity checker and a feature substituter - until
no Espacenet patent shares more than half of the invention's features.

Progress is pushed into the differentiator GUI as it happens, so the run page
shows the matrix and a live log of what the agents are doing.

Edit INVENTION below (the GUI does this for you when a run is queued), then run
with the `run_workflow` tool pointing at this file. Everything the workflow
decides is derived from literals and recorded agent output, so a run can be
resumed by `run_id`.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- inputs ----

INVENTION = {
    "name": "REPLACE ME",
    "purpose": "REPLACE ME - what the item is for, in one sentence.",
    "description": "REPLACE ME - how it works and what it is made of.",
}

# Bound to a GUI run by differentiator.store.render_workflow.
GUI_RUN_ID = ""
GUI_RUNS_DIR = ""
GUI_REPO_ROOT = ""

# A patent that shares more than this fraction of the invention's live features
# triggers a substitution round.
OVERLAP_THRESHOLD = 0.5

# Substitution rounds allowed before the workflow gives up.
MAX_ROUNDS = 6

# Patents each per-feature searcher may report.
HITS_PER_FEATURE = 6

# One searcher is dispatched per feature, so a description broken into dozens of
# elements would fan out into dozens of child sessions. Keep only the most
# distinctive ones.
MAX_FEATURES = 10

ESPACENET = (
    "Espacenet (https://worldwide.espacenet.com/patent/search). Use the classic "
    "smart search syntax, e.g. `txt=\"phase change material\" AND txt=heat sink`, "
    "open every hit you report, and read its claims and description. Never invent "
    "a publication number: only report documents you actually opened, and give the "
    "canonical Espacenet URL of each one."
)

# --------------------------------------------------------------- metadata ---

META = {
    "name": "espacenet-differentiation",
    "description": (
        "Extract an invention's features, map them against Espacenet patents, and "
        "substitute duplicated features until no patent shares more than half."
    ),
    "product": "differentiator GUI (github.com/DDavid006/ehl26)",
    "phases": [
        {
            "title": "extract",
            "detail": "identify the features and materials in the description",
            "count": 1,
            "labels": ["extract"],
        },
        {
            "title": "search",
            "detail": "one Espacenet searcher per feature, run in parallel",
        },
        {
            "title": "matrix",
            "detail": "fill the feature x patent grid from the search results",
        },
        {
            "title": "similarity",
            "detail": "first child: find the Espacenet patent closest to the invention",
        },
        {
            "title": "substitute",
            "detail": "second child: swap one duplicated feature for a new one",
        },
    ],
}

# ---------------------------------------------------------------- schemas ---

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "features": {
            "type": "array",
            "description": (
                "Every distinctive feature and every material named or implied by "
                "the description, one per entry, each phrased as a standalone "
                "claim-element-like noun phrase."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "kind": {"type": "string", "enum": ["feature", "material"]},
                },
                "required": ["text", "kind"],
            },
        },
        "field": {"type": "string", "description": "Technical field of the invention."},
    },
    "required": ["features", "field"],
}

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "feature": {"type": "string"},
        "queries_used": {"type": "array", "items": {"type": "string"}},
        "patents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "publication": {"type": "string"},
                    "title": {"type": "string"},
                    "applicant": {"type": "string"},
                    "url": {"type": "string"},
                    "evidence": {
                        "type": "string",
                        "description": "The claim or passage disclosing the feature.",
                    },
                },
                "required": ["publication", "title", "url", "evidence"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["feature", "patents", "notes"],
}

MATRIX_SCHEMA = {
    "type": "object",
    "properties": {
        "cells": {
            "type": "array",
            "description": (
                "One entry per feature/patent pair: present=true when that patent "
                "discloses that feature."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "feature_id": {"type": "string"},
                    "patent": {"type": "string"},
                    "present": {"type": "boolean"},
                },
                "required": ["feature_id", "patent", "present"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["cells", "notes"],
}

SIMILARITY_SCHEMA = {
    "type": "object",
    "properties": {
        "closest_patent": {
            "type": "string",
            "description": "Publication number of the most similar patent, or ''.",
        },
        "closest_patent_url": {"type": "string"},
        "overlap_ratio": {
            "type": "number",
            "description": "Fraction of the invention's features that patent shares.",
        },
        "shared_feature_ids": {"type": "array", "items": {"type": "string"}},
        "shared_features": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": [
        "closest_patent",
        "overlap_ratio",
        "shared_feature_ids",
        "shared_features",
        "reasoning",
    ],
}

SUBSTITUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "feature_id": {
            "type": "string",
            "description": "The shared feature being replaced.",
        },
        "replacement": {
            "type": "string",
            "description": "The new feature that takes its place.",
        },
        "rationale": {"type": "string"},
        "plausible": {
            "type": "boolean",
            "description": "False when no plausible replacement exists.",
        },
    },
    "required": ["feature_id", "replacement", "rationale", "plausible"],
}

# ------------------------------------------------------------- GUI bridge ---


def push(command, payload=None, *args):
    """Send one progress update to the differentiator GUI, best effort."""
    if not GUI_RUN_ID:
        return
    argv = [sys.executable, "-m", "differentiator.cli", "--runs-dir", GUI_RUNS_DIR,
            command, GUI_RUN_ID]
    if payload is not None:
        path = Path(GUI_RUNS_DIR) / GUI_RUN_ID / f"agent-{command}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        argv += ["--file", str(path)]
    argv += list(args)
    try:
        subprocess.run(argv, cwd=GUI_REPO_ROOT, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        log(f"GUI update '{command}' failed: {exc}")


def note(message):
    """Log to both the workflow output and the GUI's live log."""
    log(message)
    push("log", None, message)


def invention_block(features):
    return json.dumps(
        {
            "name": INVENTION["name"],
            "purpose": INVENTION["purpose"],
            "description": INVENTION["description"],
            "features": [
                {"id": f["id"], "text": f["text"], "kind": f["kind"]}
                for f in features
            ],
        },
        indent=2,
        sort_keys=True,
    )


# ----------------------------------------------------------------- stages ---


async def extract():
    return await agent(
        "You are a patent analyst breaking an invention down into claim elements.\n\n"
        f"Invention:\n{json.dumps(INVENTION, indent=2, sort_keys=True)}\n\n"
        "List every distinctive technical feature and every material that the "
        "description names or clearly implies. One idea per entry, phrased so it "
        "could stand alone as a claim element (e.g. 'aluminium fin stack brazed to "
        "the base plate', not 'aluminium'). Mark each entry as 'material' when it is "
        "primarily a material choice, otherwise 'feature'. Do not invent features "
        "that the description does not support, and do not merge two ideas into one "
        f"entry. Return at most {MAX_FEATURES} entries: if the description supports "
        "more, keep the ones that most distinguish the invention from an ordinary "
        "implementation and drop the generic ones.",
        phase="extract",
        schema=EXTRACT_SCHEMA,
        label="extract",
    )


async def search_feature(feature, round_no):
    return await agent(
        "You are a patent searcher. Search real, public patent records with your "
        "browser - never rely on memory.\n\n"
        f"Source to use: {ESPACENET}\n\n"
        f"Invention: {INVENTION['name']} - {INVENTION['purpose']}\n"
        f"Feature to search for: {feature['text']} (kind: {feature['kind']})\n\n"
        f"Find up to {HITS_PER_FEATURE} patent publications whose claims or "
        "description disclose this feature in a technically comparable way, closest "
        "first. Prefer documents in the same technical field as the invention. For "
        "each one, quote the claim or passage that discloses the feature in "
        "'evidence'. If nothing relevant exists, return an empty list and say so in "
        "'notes' rather than padding it with loose matches.",
        phase="search",
        schema=SEARCH_SCHEMA,
        label=f"search-{feature['id']}-r{round_no}",
    )


async def search_or_none(feature, round_no):
    try:
        return await search_feature(feature, round_no)
    except WorkflowAgentError as exc:
        note(f"search for feature {feature['id']} failed: {exc}")
        return None


async def build_matrix(features, findings, round_no):
    return await agent(
        "You are building a feature-by-patent table for a patent differentiation "
        "review.\n\n"
        f"Invention:\n{invention_block(features)}\n\n"
        "Per-feature Espacenet search results:\n"
        + json.dumps(findings, indent=2, sort_keys=True)
        + "\n\nFor EVERY feature id and EVERY patent publication that appears "
        "anywhere in those results, decide whether that patent discloses that "
        "feature, and return one cell per pair. A searcher only checked the feature "
        "it was assigned, so open each patent on Espacenet and check it against the "
        "features it was not searched for before marking those cells. Mark "
        "present=true only when the patent's claims or description actually disclose "
        "the feature; a vague topical similarity is not disclosure.",
        phase="matrix",
        schema=MATRIX_SCHEMA,
        label=f"matrix-r{round_no}",
    )


async def similarity(features, patents, round_no):
    return await agent(
        "You are the similarity child of a patent differentiation loop. Decide how "
        "close the invention still is to existing patents.\n\n"
        f"Invention with its current feature list:\n{invention_block(features)}\n\n"
        "Patents found so far:\n"
        + json.dumps(patents, indent=2, sort_keys=True)
        + f"\n\nSource for any further checking: {ESPACENET}\n\n"
        "Search Espacenet for patents similar to the invention as a whole, including "
        "the ones listed above, and open the closest candidates. Report the single "
        "patent that shares the largest number of the invention's current features, "
        "the exact feature ids it shares, and 'overlap_ratio' = shared features "
        "divided by the total number of features listed above. Count a feature as "
        "shared only when the patent's claims or description disclose it. If no "
        "patent shares any feature, return an empty 'closest_patent' and an "
        "overlap_ratio of 0.",
        phase="similarity",
        schema=SIMILARITY_SCHEMA,
        label=f"similarity-r{round_no}",
    )


async def substitute(features, verdict, round_no):
    return await agent(
        "You are the substitution child of a patent differentiation loop. One "
        "existing patent overlaps the invention too heavily, and your job is to "
        "replace exactly ONE duplicated feature with a new, non-overlapping one.\n\n"
        f"Invention with its current feature list:\n{invention_block(features)}\n\n"
        "Similarity finding:\n"
        + json.dumps(verdict, indent=2, sort_keys=True)
        + f"\n\nSource: {ESPACENET}\n\n"
        "Open the overlapping patent and read its independent claims. Pick the ONE "
        "shared feature whose replacement most reduces the overlap, and propose a "
        "concrete technical alternative that keeps the invention working for its "
        "stated purpose, is physically and economically plausible, and is not "
        "disclosed by that patent. Return the feature id you are replacing exactly "
        "as it appears in the feature list. Set 'plausible' to false only when no "
        "workable alternative exists - explain why in 'rationale'.",
        phase="substitute",
        schema=SUBSTITUTE_SCHEMA,
        label=f"substitute-r{round_no}",
    )


# ---------------------------------------------------------------- helpers ---


def collect_patents(findings):
    """Deduplicate the patents reported by the per-feature searchers."""
    patents = {}
    for finding in findings:
        for patent in finding["patents"]:
            patents.setdefault(patent["publication"], patent)
    return [patents[key] for key in sorted(patents)]


async def map_features(features, findings_so_far, round_no):
    """Search Espacenet for each given feature and refresh the GUI matrix."""
    results = await parallel(
        [(lambda f=feature: search_or_none(f, round_no)) for feature in features]
    )
    findings = findings_so_far + [r for r in results if isinstance(r, dict)]
    if not findings:
        return findings, []

    patents = collect_patents(findings)
    note(f"round {round_no}: {len(patents)} distinct patents on Espacenet")

    grid = await build_matrix(features, findings, round_no)
    push(
        "matrix",
        {
            "patents": [
                {
                    "publication": patent["publication"],
                    "title": patent.get("title", ""),
                    "applicant": patent.get("applicant", ""),
                    "url": patent.get("url", ""),
                }
                for patent in patents
            ],
            "cells": grid["cells"],
        },
    )
    return findings, patents


# ------------------------------------------------------------------- main ---


async def main():
    await register_workflow(META)

    push("status", None, "extracting")
    note(f"extracting features from '{INVENTION['name']}'")
    extracted = await extract()

    features = [
        {
            "id": f"f{index}",
            "text": entry["text"],
            "kind": entry["kind"],
            "origin": "original",
        }
        for index, entry in enumerate(extracted["features"][:MAX_FEATURES], start=1)
    ]
    # Ids are handed out in creation order and never reused, so they keep
    # matching the GUI's own numbering as features are substituted.
    features_created = len(features)
    push("features", {"features": extracted["features"][:MAX_FEATURES]})
    note(f"{len(features)} features and materials extracted")

    push("status", None, "searching")
    findings, patents = await map_features(features, [], 0)
    if not findings:
        push("status", None, "failed", "--error", "every Espacenet search failed")
        note("every Espacenet search failed, aborting")
        return

    push("status", None, "iterating")

    for round_no in range(1, MAX_ROUNDS + 1):
        verdict = await similarity(features, patents, round_no)
        push(
            "similarity",
            {
                "closest_patent": verdict["closest_patent"],
                "overlap_ratio": verdict["overlap_ratio"],
                "shared_features": verdict["shared_features"],
                "shared_feature_ids": verdict["shared_feature_ids"],
                "needs_substitution": verdict["overlap_ratio"] > OVERLAP_THRESHOLD,
                "reasoning": verdict["reasoning"],
            },
        )
        note(
            f"round {round_no}: closest {verdict['closest_patent'] or 'none'} at "
            f"overlap {verdict['overlap_ratio']}"
        )

        if verdict["overlap_ratio"] <= OVERLAP_THRESHOLD:
            push("status", None, "complete")
            note("no patent shares more than half of the features - done")
            return

        swap = await substitute(features, verdict, round_no)
        if not swap["plausible"]:
            push("status", None, "failed", "--error", swap["rationale"])
            note(f"no plausible substitution left: {swap['rationale']}")
            return

        target = next((f for f in features if f["id"] == swap["feature_id"]), None)
        if target is None:
            push("status", None, "failed", "--error",
                 f"substituter returned unknown feature {swap['feature_id']}")
            note(f"substituter returned unknown feature {swap['feature_id']}, aborting")
            return

        push(
            "substitution",
            {
                "feature_id": target["id"],
                "replacement": swap["replacement"],
                "rationale": swap["rationale"],
            },
        )
        features_created += 1
        replacement = {
            "id": f"f{features_created}",
            "text": swap["replacement"],
            "kind": target["kind"],
            "origin": "new",
        }
        features = [f for f in features if f["id"] != target["id"]] + [replacement]
        note(f"round {round_no}: '{target['text']}' -> '{replacement['text']}'")

        findings, patents = await map_features([replacement], findings, round_no)

    push("status", None, "failed", "--error",
         f"still overlapping after {MAX_ROUNDS} substitution rounds")
    note(f"still overlapping after {MAX_ROUNDS} rounds")


asyncio.run(main())
