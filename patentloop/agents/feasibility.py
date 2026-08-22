"""Feasibility Gate: hard doable + scoped checks. Failing either kills the run."""

from __future__ import annotations

from typing import Any

from ..llm import chat_json

FEASIBILITY_SYSTEM = (
    "You are a sceptical senior engineer and patent examiner performing a hard gate. "
    "Apply two independent checks to the idea.\n"
    "1. DOABLE: does the idea violate a known physical or engineering constraint "
    "(perpetual motion, faster-than-light signalling, thermodynamic impossibility), or is it a "
    "restatement of a commoditised product with no inventive step? Reason explicitly step by step.\n"
    "2. SCOPED: is the idea specific enough to support a real claim - a concrete mechanism, "
    "structure, or method with steps? Reject broad aspirations like 'an app that uses AI to "
    "optimise X' or 'a device that improves efficiency using machine learning'.\n"
    'Return JSON: {"doable": {"pass": bool, "reasoning": "<full chain of reasoning>"}, '
    '"scoped": {"pass": bool, "reasoning": "<full chain of reasoning>"}}'
)


def _check(section: dict[str, Any]) -> dict[str, Any]:
    verdict = section.get("pass", section.get("passed"))
    return {"pass": bool(verdict), "reasoning": section.get("reasoning") or "",
            "malformed": verdict is None}


def run_feasibility_gate(idea: str, extraction: dict[str, Any]) -> dict[str, Any]:
    doable: dict[str, Any] = {}
    scoped: dict[str, Any] = {}
    for _ in range(2):  # retry once if the model returned a malformed section
        verdict = chat_json(
            FEASIBILITY_SYSTEM,
            f"IDEA:\n{idea}\n\nEXTRACTED ELEMENTS: {extraction['elements']}",
            temperature=0.0,
        )
        doable = _check(verdict.get("doable") or {})
        scoped = _check(verdict.get("scoped") or {})
        malformed_doable = doable.pop("malformed")
        malformed_scoped = scoped.pop("malformed")
        if not (malformed_doable or malformed_scoped):
            break
    passed = doable["pass"] and scoped["pass"]
    return {
        "agent": "feasibility_gate",
        "passed": passed,
        "doable": doable,
        "scoped": scoped,
    }
