"""Expert pivot agent: invoked only when overlap is high but the idea is alive.

The agent is role-prompted as a practitioner in the field inferred from the
idea, and is given the exact claims that blocked the previous version. Its
variant re-enters the loop at the research agent as a new idea version, and the
lineage records why it was produced.
"""

from __future__ import annotations

from ..config import Config
from ..llm import LLM
from ..schemas import Idea, PatentSearchResult, PivotResult
from ..trace import Tracer

SYSTEM_TEMPLATE = """You are {persona}. You are redirecting an invention that collided with existing
patent claims.

You are given the previous idea, the specific patents it collided with, and the specific claims that
its elements read on. Propose ONE concrete variant that occupies a genuine adjacent technical gap.

Hard requirements:
- The variant must change the mechanism, not the wording: a different physical principle, a
  different structure, a different control strategy, a different material system or a different
  point of intervention.
- It must still be feasible with today's engineering and must recite a mechanism specific enough to
  claim.
- It must be a variant of the same underlying problem, not a new unrelated invention.
- Explain, claim by claim, why the variant no longer reads on the claims that blocked the last
  version.
- If every adjacent direction you can identify is already inside the blocked territory, say so
  honestly in "blocked_territory" and still propose your least-blocked option.

Reply with a single JSON object:
{{"variant_title": str, "variant_text": str, "avoids": str, "still_feasible_reasoning": str,
  "blocked_territory": [str]}}
"variant_text" is the new disclosure in 120-250 words, written as an invention description."""

PERSONA_SYSTEM = """Name the single professional persona best suited to redesign around prior art in
the field of this invention. Reply with a JSON object: {"persona": str} where persona is like
"a senior solid-state battery materials scientist with 20 years of cell-design experience"."""


class ExpertPivotAgent:
    name = "pivot"

    def __init__(self, config: Config, tracer: Tracer, llm: LLM):
        self.config = config
        self.tracer = tracer
        self.llm = llm

    def _persona(self, idea: Idea) -> str:
        parsed = self.llm.json_call(
            agent=self.name,
            purpose="persona_selection",
            system=PERSONA_SYSTEM,
            user=f"Invention: {idea.text}\nField: {idea.field_of_art}",
            required_keys=("persona",),
            max_tokens=300,
            iteration=idea.version,
        )
        return str(parsed.get("persona") or "a senior engineer in the relevant field")

    def run(self, idea: Idea, patents: PatentSearchResult) -> PivotResult:
        persona = self._persona(idea)
        blocking = []
        for match in patents.matches[:3]:
            collisions = "\n".join(
                f"    - element {c.element!r} reads on claim {c.claim_number}: {c.claim_text[:400]}"
                for c in match.collisions
                if c.reads_on
            )
            blocking.append(
                f"{match.publication_number} — {match.title} ({match.assignee})\n"
                f"  overlap {match.match_score}; blocked elements: {', '.join(match.overlapping_elements)}\n"
                f"{collisions}"
            )
        parsed = self.llm.json_call(
            agent=self.name,
            purpose="pivot_proposal",
            system=SYSTEM_TEMPLATE.format(persona=persona),
            user=(
                f"Previous idea (v{idea.version}):\n{idea.text}\n\n"
                "Its elements:\n" + "\n".join(f"- {e}" for e in idea.elements)
                + "\n\nBlocking patents and colliding claims:\n" + "\n\n".join(blocking)
            ),
            required_keys=("variant_text",),
            iteration=idea.version,
        )
        result = PivotResult(
            variant_text=str(parsed.get("variant_text") or "").strip(),
            variant_title=str(parsed.get("variant_title") or "").strip(),
            avoids=str(parsed.get("avoids") or ""),
            blocked_territory=[str(b) for b in parsed.get("blocked_territory") or []],
            persona=persona,
            still_feasible_reasoning=str(parsed.get("still_feasible_reasoning") or ""),
        )
        self.tracer.log(
            f"pivot: proposed {result.variant_title!r} as {persona}", self.name, idea.version
        )
        return result
