"""Research agent: novelty scan against live literature.

Pipeline per idea version:

1. an LLM call extracts 3-6 core technical elements plus a search query for
   each (this is the only step where the LLM speaks about the idea unaided);
2. every element is searched on arXiv, Semantic Scholar and GitHub;
3. an LLM call scores each element *against the retrieved abstracts only* and
   must cite the document ids it relied on;
4. the same element is scored again with deterministic tf-idf similarity, and
   the two are blended, so a hallucinated "nothing similar found" cannot lift
   the novelty score on its own.
"""

from __future__ import annotations

from ..config import Config
from ..llm import LLM, clamp
from ..schemas import Document, ElementSimilarity, Idea, ResearchResult
from ..sources import ArxivSource, GitHubSource, SemanticScholarSource
from ..textsim import best_cosine
from ..trace import Tracer

EXTRACTION_SYSTEM = """You are a patent analyst who decomposes invention disclosures into claim elements.
Given raw idea text, identify the 3-6 core technical elements: the specific structures, mechanisms or
method steps that would have to appear in an independent claim. Elements must be concrete and
searchable; do not include marketing language or benefits.
Reply with a single JSON object:
{"title": str, "field_of_art": str, "elements": [str, ...],
 "queries": {"<element>": "<5-10 word literature search query>"}}"""

SCORING_SYSTEM = """You are a novelty examiner. You are given one technical element of a proposed
invention and a list of publications that were actually retrieved from arXiv, Semantic Scholar and
GitHub. Judge how closely the retrieved work already discloses that element.

Rules:
- Judge ONLY from the supplied titles/abstracts. You have no other knowledge of these documents.
- similarity 90-100: a retrieved document discloses essentially this element.
- similarity 50-89: closely related work, differs in a meaningful detail.
- similarity 1-49: same general area only.
- similarity 0: nothing retrieved is relevant.
- cite_ids must be document ids from the supplied list (or [] if similarity is 0).

Reply with a single JSON object:
{"elements": [{"element": str, "similarity": number, "cite_ids": [str], "rationale": str}], "summary": str}"""


class ResearchAgent:
    name = "research"

    def __init__(self, config: Config, tracer: Tracer, llm: LLM):
        self.config = config
        self.tracer = tracer
        self.llm = llm
        self.sources = [
            ArxivSource(config, tracer),
            SemanticScholarSource(config, tracer),
            GitHubSource(config, tracer),
        ]

    # -- step 1 ----------------------------------------------------------
    def extract_elements(self, idea: Idea) -> Idea:
        parsed = self.llm.json_call(
            agent=self.name,
            purpose="element_extraction",
            system=EXTRACTION_SYSTEM,
            user=f"Idea (version {idea.version}):\n{idea.text}",
            required_keys=("elements",),
            iteration=idea.version,
        )
        elements = [str(e).strip() for e in parsed.get("elements") or [] if str(e).strip()][:6]
        idea.elements = elements
        idea.title = str(parsed.get("title") or idea.title or "Untitled invention").strip()
        idea.field_of_art = str(parsed.get("field_of_art") or "").strip()
        queries = parsed.get("queries") or {}
        self._queries = {e: str(queries.get(e) or e) for e in elements}
        return idea

    # -- step 2..4 -------------------------------------------------------
    def run(self, idea: Idea) -> ResearchResult:
        if not idea.elements:
            self.extract_elements(idea)
        queries = getattr(self, "_queries", {}) or {e: e for e in idea.elements}
        documents: list[Document] = []
        seen: set[tuple[str, str]] = set()
        sources_used: list[str] = []
        for element in idea.elements:
            query = queries.get(element, element)
            for source in self.sources:
                for doc in source.search(query, self.config.results_per_query, idea.version):
                    key = (doc.source, doc.external_id or doc.title)
                    if key in seen or not (doc.title or doc.abstract):
                        continue
                    seen.add(key)
                    documents.append(doc)
                    if source.name not in sources_used:
                        sources_used.append(source.name)
        self.tracer.log(
            f"research: {len(documents)} publications retrieved for {len(idea.elements)} elements",
            self.name,
            idea.version,
        )
        element_scores = self._score(idea, documents)
        novelty = self._novelty_score(element_scores)
        rationale = getattr(self, "_summary", "")
        return ResearchResult(
            novelty_score=novelty,
            rationale=rationale,
            element_scores=element_scores,
            documents=documents,
            queries=[queries.get(e, e) for e in idea.elements],
            sources_used=sources_used,
        )

    def _score(self, idea: Idea, documents: list[Document]) -> list[ElementSimilarity]:
        doc_index = {self._doc_id(d): d for d in documents}
        corpus = [f"{d.title}. {d.abstract}" for d in documents] + idea.elements
        if not documents:
            self._summary = "No publications were retrieved from any literature source."
            return [
                ElementSimilarity(element=e, llm_similarity=0.0, lexical_similarity=0.0, similarity=0.0,
                                  rationale="no retrieved documents to compare against")
                for e in idea.elements
            ]
        catalogue = "\n\n".join(
            f"[{self._doc_id(d)}] ({d.source}, {d.year}) {d.title}\n{(d.abstract or '')[:900]}"
            for d in documents
        )
        parsed = self.llm.json_call(
            agent=self.name,
            purpose="novelty_scoring",
            system=SCORING_SYSTEM,
            user=(
                f"Invention idea (v{idea.version}): {idea.text}\n\n"
                f"Elements to score:\n" + "\n".join(f"- {e}" for e in idea.elements)
                + f"\n\nRetrieved publications:\n{catalogue}"
            ),
            required_keys=("elements",),
            iteration=idea.version,
        )
        self._summary = str(parsed.get("summary") or "")
        by_element = {str(item.get("element", "")).strip(): item for item in parsed.get("elements") or []}
        scores = []
        for element in idea.elements:
            item = by_element.get(element) or self._fuzzy_lookup(element, by_element)
            llm_similarity = clamp((item or {}).get("similarity", 0))
            cited = [c for c in ((item or {}).get("cite_ids") or []) if c in doc_index]
            lexical = best_cosine(
                element,
                [f"{d.title}. {d.abstract}" for d in documents],
                corpus,
            )
            blended = round(0.6 * llm_similarity + 0.4 * lexical * 100, 2)
            scores.append(
                ElementSimilarity(
                    element=element,
                    llm_similarity=llm_similarity,
                    lexical_similarity=round(lexical, 4),
                    similarity=blended,
                    closest_document_ids=cited,
                    rationale=str((item or {}).get("rationale") or ""),
                )
            )
        return scores

    @staticmethod
    def _doc_id(document: Document) -> str:
        return f"{document.source}:{document.external_id or document.title[:40]}"

    @staticmethod
    def _fuzzy_lookup(element: str, by_element: dict) -> dict | None:
        target = element.lower()[:40]
        for key, value in by_element.items():
            if key.lower()[:40] == target:
                return value
        return None

    @staticmethod
    def _novelty_score(element_scores: list[ElementSimilarity]) -> float:
        """novelty = 100 - (0.6 * worst element + 0.4 * mean element) similarity."""

        if not element_scores:
            return 0.0
        similarities = [s.similarity for s in element_scores]
        worst = max(similarities)
        mean = sum(similarities) / len(similarities)
        return round(max(0.0, 100.0 - (0.6 * worst + 0.4 * mean)), 2)
