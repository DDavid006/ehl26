"""Offline doubles for the orchestrator's collaborators.

These exist so the gate logic can be tested without spending API calls; the
real run path is exercised end-to-end against live APIs by `python run.py`.
"""

from __future__ import annotations

from patentloop.schemas import (
    Document,
    ElementCollision,
    ElementSimilarity,
    FeasibilityResult,
    Idea,
    PatentHit,
    PatentMatch,
    PatentSearchResult,
    PivotResult,
    ResearchResult,
)


def document(name: str = "paper") -> Document:
    return Document(
        source="arxiv",
        external_id=name,
        title=f"{name} title",
        url=f"https://arxiv.org/abs/{name}",
        abstract=f"{name} abstract about laser textured garnet electrolytes",
        year=2024,
    )


def research_result(novelty: float) -> ResearchResult:
    return ResearchResult(
        novelty_score=novelty,
        rationale="stub",
        element_scores=[
            ElementSimilarity(element="e1", llm_similarity=0.0, lexical_similarity=0.0, similarity=0.0)
        ],
        documents=[document()],
        queries=["q"],
        sources_used=["arxiv"],
    )


def patent_result(overlap: float) -> PatentSearchResult:
    match = PatentMatch(
        publication_number="US1234567B2",
        title="Blocking patent",
        assignee="MegaCorp",
        url="https://patents.google.com/patent/US1234567B2/en",
        source="google_patents",
        overlapping_elements=["e1"],
        collisions=[
            ElementCollision(
                element="e1",
                publication_number="US1234567B2",
                claim_number="1",
                claim_text="A method comprising e1",
                reads_on=True,
                reasoning="literal",
            )
        ],
        llm_overlap=overlap,
        lexical_overlap=0.5,
        match_score=overlap,
    )
    return PatentSearchResult(
        overlap_score=overlap,
        rationale="stub",
        matches=[match] if overlap else [],
        hits=[
            PatentHit(
                source="google_patents",
                publication_number="US1234567B2",
                title="Blocking patent",
                url=match.url,
                claims=["A method comprising e1"],
            )
        ],
        queries=["q"],
        sources_used=["google_patents"],
    )


class FakeResearch:
    def __init__(self, novelty_by_version: dict[int, float]):
        self.novelty_by_version = novelty_by_version

    def extract_elements(self, idea: Idea) -> Idea:
        idea.elements = ["e1", "e2"]
        idea.title = f"idea v{idea.version}"
        idea.field_of_art = "electrochemistry"
        return idea

    def run(self, idea: Idea) -> ResearchResult:
        return research_result(self.novelty_by_version.get(idea.version, 80.0))


class FakePatents:
    def __init__(self, overlap_by_version: dict[int, float]):
        self.overlap_by_version = overlap_by_version

    def run(self, idea: Idea) -> PatentSearchResult:
        return patent_result(self.overlap_by_version.get(idea.version, 0.0))


class FakeFeasibility:
    def __init__(self, doable: bool = True, scoped: bool = True):
        self.doable, self.scoped = doable, scoped

    def run(self, idea: Idea, research=None) -> FeasibilityResult:
        return FeasibilityResult(
            doable=self.doable,
            doable_reasoning="stub doability reasoning",
            scoped=self.scoped,
            scoped_reasoning="stub scope reasoning",
            claimable_mechanism="stub mechanism",
            violated_constraints=[] if self.doable else ["conservation of energy"],
        )


class FakePivot:
    """Emits either diverging or converging variants."""

    def __init__(self, converging: bool):
        self.converging = converging
        self.calls = 0

    def run(self, idea: Idea, patents: PatentSearchResult) -> PivotResult:
        self.calls += 1
        if self.converging:
            text = "laser textured garnet electrolyte interlayer with dendrite blocking pillars"
        else:
            text = f"variant {self.calls}: " + " ".join(
                f"unrelated{self.calls}word{n}" for n in range(30)
            )
        return PivotResult(
            variant_text=text,
            variant_title=f"variant {self.calls}",
            avoids="different mechanism",
            blocked_territory=[],
            persona="a senior engineer",
            still_feasible_reasoning="stub",
        )


class FakeDrafting:
    def run(self, idea: Idea, research, patents) -> str:
        return f"# Draft for {idea.title}\n\nClaims: 1. A method...\n"
