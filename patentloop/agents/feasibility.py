"""Feasibility gate: hard, no-pivot check on doability and claim scope.

Both checks are made in one call but scored separately, and the full reasoning
for each is stored in the trace verbatim — the gate is only defensible if the
reasoning that failed an idea can be read afterwards.
"""

from __future__ import annotations

from ..config import Config
from ..llm import LLM, as_bool
from ..schemas import FeasibilityResult, Idea, ResearchResult
from ..trace import Tracer

SYSTEM = """You are a skeptical patent examiner combined with a physicist reviewing an invention
disclosure. Apply exactly two independent checks and reason explicitly before answering.

CHECK 1 — DOABLE. Does the idea violate a known physical, chemical, information-theoretic or
engineering constraint (conservation laws, thermodynamic limits, Shannon limits, computational
impossibility)? Is it merely a restatement of something already commoditized with no inventive step
(i.e. any competent practitioner would produce it by routine assembly of off-the-shelf parts)?
Fail the check in either case. Name the specific constraint or the specific commodity product.

CHECK 2 — SCOPED. Is the disclosure specific enough to support a real claim: an identified structure,
mechanism, or method with steps? Fail it when the disclosure is an aspiration or a business goal
("an app that uses AI to optimize X", "a platform that improves efficiency"), when no mechanism is
recited, or when the only specificity is the choice of market. State the mechanism you would claim,
or say why none is recited.

Answer strictly with a single JSON object:
{"doable": bool, "doable_reasoning": str, "violated_constraints": [str],
 "scoped": bool, "scoped_reasoning": str, "claimable_mechanism": str}
Both reasoning fields must be at least three sentences and reference the disclosure's own wording."""


class FeasibilityGate:
    name = "feasibility"

    def __init__(self, config: Config, tracer: Tracer, llm: LLM):
        self.config = config
        self.tracer = tracer
        self.llm = llm

    def run(self, idea: Idea, research: ResearchResult | None = None) -> FeasibilityResult:
        context = ""
        if research:
            closest = "\n".join(
                f"- {d.title} ({d.source}, {d.year}) {d.url}" for d in research.documents[:8]
            )
            context = (
                f"\n\nFor the commoditization judgement, these publications/repositories were "
                f"retrieved for this idea:\n{closest}"
            )
        parsed = self.llm.json_call(
            agent=self.name,
            purpose="feasibility_gate",
            system=SYSTEM,
            user=(
                f"Disclosure (v{idea.version}):\n{idea.text}\n\n"
                "Extracted elements:\n" + "\n".join(f"- {e}" for e in idea.elements) + context
            ),
            required_keys=("doable", "scoped"),
            iteration=idea.version,
        )
        result = FeasibilityResult(
            doable=as_bool(parsed.get("doable")),
            doable_reasoning=str(parsed.get("doable_reasoning") or ""),
            scoped=as_bool(parsed.get("scoped")),
            scoped_reasoning=str(parsed.get("scoped_reasoning") or ""),
            claimable_mechanism=str(parsed.get("claimable_mechanism") or ""),
            violated_constraints=[str(c) for c in parsed.get("violated_constraints") or []],
        )
        self.tracer.log(
            f"feasibility: doable={result.doable} scoped={result.scoped}", self.name, idea.version
        )
        return result
