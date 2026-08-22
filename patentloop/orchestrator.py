"""The PatentLoop orchestrator: a stateful loop over idea versions.

The orchestrator owns every decision. Agents only produce structured findings;
the gates below turn those findings into one of three terminal states, and no
path asks a human anything:

    RESEARCH -> PATENT SEARCH -> FEASIBILITY GATE -> DECISION GATE
        feasible & scoped & novel & unblocked  -> DRAFTED
        blocked by claims                      -> PIVOT -> next iteration
        infeasible or unscoped                 -> KILLED_INFEASIBLE
        pivot space converged / cap reached    -> KILLED_SATURATED
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from .agents import DraftingAgent, ExpertPivotAgent, FeasibilityGate, PatentSearchAgent, ResearchAgent
from .config import NOVELTY_PASS, OVERLAP_BLOCK, PIVOT_CONVERGENCE, Config
from .llm import LLM
from .reporting import write_artifacts
from .schemas import DRAFTED, KILLED_INFEASIBLE, KILLED_SATURATED, GateDecision, Idea, Iteration, RunResult
from .textsim import cosine
from .trace import Tracer


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


class Orchestrator:
    def __init__(self, config: Config, run_id: str | None = None):
        self.config = config
        self.run_id = run_id or new_run_id()
        self.run_dir = Path(config.runs_dir) / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.tracer = Tracer(self.run_dir, self.run_id)
        self.llm = LLM(config, self.tracer)
        self.research = ResearchAgent(config, self.tracer, self.llm)
        self.patent_search = PatentSearchAgent(config, self.tracer, self.llm)
        self.feasibility = FeasibilityGate(config, self.tracer, self.llm)
        self.pivot = ExpertPivotAgent(config, self.tracer, self.llm)
        self.drafting = DraftingAgent(config, self.tracer, self.llm)

    # -- the loop --------------------------------------------------------
    def run(self, idea_text: str) -> RunResult:
        started = _now()
        idea = Idea(version=1, text=idea_text.strip())
        iterations: list[Iteration] = []
        outcome = reason = ""
        draft = ""
        self.tracer.log(f"run {self.run_id} started; max_iterations={self.config.max_iterations}")

        while True:
            iteration = Iteration(index=idea.version, idea=idea)
            iterations.append(iteration)
            self.tracer.log(f"--- iteration {idea.version}: {idea.text[:120]}", iteration=idea.version)

            self.research.extract_elements(idea)
            self.tracer.log(f"elements: {idea.elements}", "research", idea.version)

            iteration.research = self.research.run(idea)
            iteration.patents = self.patent_search.run(idea)
            iteration.feasibility = self.feasibility.run(idea, iteration.research)

            gate = self._feasibility_gate(iteration)
            iteration.decisions.append(gate)
            if gate.decision == "kill":
                outcome, reason = KILLED_INFEASIBLE, gate.reason
                break

            decision = self._decision_gate(iteration)
            iteration.decisions.append(decision)

            if decision.decision == "draft":
                draft = self.drafting.run(idea, iteration.research, iteration.patents)
                outcome, reason = DRAFTED, decision.reason
                break

            if decision.decision == "kill_saturated":
                outcome, reason = KILLED_SATURATED, decision.reason
                break

            # decision == "pivot"
            iteration.pivot = self.pivot.run(idea, iteration.patents)
            if not iteration.pivot.variant_text:
                outcome = KILLED_SATURATED
                reason = "the pivot agent could not articulate a variant outside the blocked territory"
                self.tracer.gate("pivot_output", "kill_saturated", reason, idea.version, {})
                break

            saturation = self._saturation_gate(iterations, iteration)
            iteration.decisions.append(saturation)
            if saturation.decision == "kill_saturated":
                outcome, reason = KILLED_SATURATED, saturation.reason
                break

            idea = Idea(
                version=idea.version + 1,
                text=iteration.pivot.variant_text,
                title=iteration.pivot.variant_title,
                field_of_art=idea.field_of_art,
                parent_version=idea.version,
                derived_because=iteration.pivot.avoids,
            )

        result = RunResult(
            run_id=self.run_id,
            outcome=outcome,
            reason=reason,
            started_at=started,
            finished_at=_now(),
            iterations=iterations,
            run_dir=str(self.run_dir),
            draft=draft,
        )
        self.tracer.log(f"run {self.run_id} finished: {outcome} — {reason}")
        write_artifacts(result, self.tracer)
        return result

    # -- gates -----------------------------------------------------------
    def _feasibility_gate(self, iteration: Iteration) -> GateDecision:
        feasibility = iteration.feasibility
        assert feasibility is not None
        inputs = {
            "doable": feasibility.doable,
            "scoped": feasibility.scoped,
            "violated_constraints": feasibility.violated_constraints,
        }
        if feasibility.passed:
            decision, reason = "pass", "idea is technically doable and specific enough to claim"
        elif not feasibility.doable:
            decision = "kill"
            reason = "failed the doability check: " + (
                "; ".join(feasibility.violated_constraints) or feasibility.doable_reasoning[:300]
            )
        else:
            decision = "kill"
            reason = "failed the scope check: " + feasibility.scoped_reasoning[:300]
        self.tracer.gate("feasibility", decision, reason, iteration.index, inputs)
        return GateDecision("feasibility", decision, reason, inputs)

    def _decision_gate(self, iteration: Iteration) -> GateDecision:
        research, patents = iteration.research, iteration.patents
        assert research is not None and patents is not None
        blocking = [m for m in patents.matches if m.match_score >= OVERLAP_BLOCK]
        inputs = {
            "novelty_score": research.novelty_score,
            "overlap_score": patents.overlap_score,
            "novelty_threshold": NOVELTY_PASS,
            "overlap_threshold": OVERLAP_BLOCK,
            "blocking_patents": [m.publication_number for m in blocking],
            "iteration": iteration.index,
            "max_iterations": self.config.max_iterations,
        }
        if patents.overlap_score < OVERLAP_BLOCK and research.novelty_score >= NOVELTY_PASS:
            decision = "draft"
            reason = (
                f"novelty {research.novelty_score} >= {NOVELTY_PASS} and no retrieved claim set "
                f"overlaps above {OVERLAP_BLOCK} (highest {patents.overlap_score})"
            )
        elif iteration.index >= self.config.max_iterations:
            decision = "kill_saturated"
            reason = (
                f"iteration cap {self.config.max_iterations} reached with overlap "
                f"{patents.overlap_score} and novelty {research.novelty_score}"
            )
        elif patents.overlap_score >= OVERLAP_BLOCK:
            decision = "pivot"
            reason = (
                f"overlap {patents.overlap_score} >= {OVERLAP_BLOCK}; blocked by "
                + ", ".join(m.publication_number for m in blocking[:3])
            )
        else:
            decision = "pivot"
            reason = (
                f"novelty {research.novelty_score} < {NOVELTY_PASS}: the literature already "
                "discloses the core elements even though no claim blocks them"
            )
        self.tracer.gate("decision", decision, reason, iteration.index, inputs)
        return GateDecision("decision", decision, reason, inputs)

    def _saturation_gate(self, iterations: list[Iteration], iteration: Iteration) -> GateDecision:
        """Stop when pivots stop exploring: same territory, no overlap relief."""

        pivots = [i.pivot for i in iterations if i.pivot]
        overlaps = [i.patents.overlap_score for i in iterations if i.patents]
        similarity = None
        if len(pivots) >= 2:
            similarity = cosine(
                pivots[-1].variant_text,
                pivots[-2].variant_text,
                [p.variant_text for p in pivots],
            )
            iteration.pivot_similarity_to_previous = similarity
        inputs = {
            "overlap_history": overlaps,
            "pivot_similarity_to_previous": similarity,
            "convergence_threshold": PIVOT_CONVERGENCE,
            "pivot_reported_blocked_territory": pivots[-1].blocked_territory if pivots else [],
        }
        blocked_everywhere = len(overlaps) >= 2 and all(o >= OVERLAP_BLOCK for o in overlaps[-2:])
        converged = similarity is not None and similarity >= PIVOT_CONVERGENCE
        if blocked_everywhere and converged:
            decision = "kill_saturated"
            reason = (
                f"overlap stayed >= {OVERLAP_BLOCK} across {len(overlaps)} versions and successive "
                f"pivots converged (tf-idf similarity {similarity} >= {PIVOT_CONVERGENCE}): the "
                "pivot space keeps landing on the same blocked territory"
            )
        else:
            decision = "continue"
            reason = (
                f"pivot explores new territory (similarity to previous pivot: {similarity}); "
                f"continuing to version {iteration.index + 1}"
            )
        self.tracer.gate("saturation", decision, reason, iteration.index, inputs)
        return GateDecision("saturation", decision, reason, inputs)


def run_idea(idea_text: str, config: Config | None = None, run_id: str | None = None) -> RunResult:
    cfg = config or Config.from_env()
    return Orchestrator(cfg, run_id).run(idea_text)
