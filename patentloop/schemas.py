"""Structured outputs exchanged between PatentLoop agents.

Each agent returns one of these; the orchestrator and the gates only ever read
these fields, so no agent can decide the run's outcome by prose alone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Terminal states. A run always ends in exactly one of them.
DRAFTED = "DRAFTED"
KILLED_SATURATED = "KILLED_SATURATED"
KILLED_INFEASIBLE = "KILLED_INFEASIBLE"


def _dump(value: Any) -> Any:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if isinstance(value, list):
        return [_dump(v) for v in value]
    if isinstance(value, dict):
        return {k: _dump(v) for k, v in value.items()}
    return value


class Payload:
    """Mixin giving dataclasses a JSON-ready ``as_dict``."""

    def as_dict(self) -> dict:
        return {k: _dump(v) for k, v in asdict(self).items()}


@dataclass
class Idea(Payload):
    """One version of the idea in the lineage."""

    version: int
    text: str
    title: str = ""
    field_of_art: str = ""
    elements: list[str] = field(default_factory=list)
    parent_version: int | None = None
    derived_because: str = ""


@dataclass
class Document(Payload):
    """A literature hit actually retrieved from an external API."""

    source: str
    external_id: str
    title: str
    url: str
    abstract: str = ""
    year: int | None = None
    venue: str = ""
    query: str = ""


@dataclass
class ElementSimilarity(Payload):
    """How close the closest retrieved publication is to one element."""

    element: str
    llm_similarity: float
    lexical_similarity: float
    similarity: float
    closest_document_ids: list[str] = field(default_factory=list)
    rationale: str = ""


@dataclass
class ResearchResult(Payload):
    novelty_score: float
    rationale: str
    element_scores: list[ElementSimilarity] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)


@dataclass
class PatentHit(Payload):
    """A patent actually returned by a patent database, with its claims."""

    source: str
    publication_number: str
    title: str
    url: str
    assignee: str = ""
    date: str = ""
    abstract: str = ""
    claims: list[str] = field(default_factory=list)
    query: str = ""


@dataclass
class ElementCollision(Payload):
    """One idea element read onto one specific claim."""

    element: str
    publication_number: str
    claim_number: str
    claim_text: str
    reads_on: bool
    reasoning: str = ""


@dataclass
class PatentMatch(Payload):
    publication_number: str
    title: str
    assignee: str
    url: str
    source: str
    overlapping_elements: list[str] = field(default_factory=list)
    collisions: list[ElementCollision] = field(default_factory=list)
    llm_overlap: float = 0.0
    lexical_overlap: float = 0.0
    match_score: float = 0.0


@dataclass
class PatentSearchResult(Payload):
    overlap_score: float
    rationale: str
    matches: list[PatentMatch] = field(default_factory=list)
    hits: list[PatentHit] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)


@dataclass
class FeasibilityResult(Payload):
    doable: bool
    doable_reasoning: str
    scoped: bool
    scoped_reasoning: str
    claimable_mechanism: str = ""
    violated_constraints: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.doable and self.scoped


@dataclass
class PivotResult(Payload):
    variant_text: str
    variant_title: str
    avoids: str
    blocked_territory: list[str] = field(default_factory=list)
    persona: str = ""
    still_feasible_reasoning: str = ""


@dataclass
class GateDecision(Payload):
    gate: str
    decision: str
    reason: str
    inputs: dict = field(default_factory=dict)


@dataclass
class Iteration(Payload):
    index: int
    idea: Idea
    research: ResearchResult | None = None
    patents: PatentSearchResult | None = None
    feasibility: FeasibilityResult | None = None
    pivot: PivotResult | None = None
    decisions: list[GateDecision] = field(default_factory=list)
    pivot_similarity_to_previous: float | None = None


@dataclass
class RunResult(Payload):
    run_id: str
    outcome: str
    reason: str
    started_at: str
    finished_at: str
    iterations: list[Iteration] = field(default_factory=list)
    run_dir: str = ""
    draft: str = ""
