"""Patent search agent: prior-art / freedom-to-operate scan.

The overlap score is derived from claim text that was fetched during the run:
for every retrieved patent the agent asks which specific idea element reads on
which specific numbered claim, and the score is computed from the resulting
element/claim collision matrix — not from an LLM's overall impression.
"""

from __future__ import annotations

from ..config import Config
from ..llm import LLM, as_bool
from ..schemas import ElementCollision, Idea, PatentHit, PatentMatch, PatentSearchResult
from ..sources import EpoOpsSource, GooglePatentsSource, PatentsViewSource
from ..textsim import best_cosine
from ..trace import Tracer

COMPARISON_SYSTEM = """You are a patent attorney performing a claim-element comparison for a
freedom-to-operate screen. You are given the elements of a proposed invention and the verbatim claim
text of one patent that was retrieved from a patent database.

For every element, decide whether the patent's claims read on it: does a claim recite that structure,
mechanism or step (literally or in equivalent wording)? Quote the claim you relied on.

Rules:
- Judge ONLY from the supplied claim text.
- claim_number must be the number that starts the claim you used ("1", "7", ...).
- Set reads_on false when the claim merely mentions the same field.

Reply with a single JSON object:
{"collisions": [{"element": str, "claim_number": str, "reads_on": bool, "quote": str, "reasoning": str}],
 "summary": str}"""


class PatentSearchAgent:
    name = "patent_search"

    def __init__(self, config: Config, tracer: Tracer, llm: LLM):
        self.config = config
        self.tracer = tracer
        self.llm = llm
        self.google = GooglePatentsSource(config, tracer)
        self.patentsview = PatentsViewSource(config, tracer)
        self.epo = EpoOpsSource(config, tracer)

    def run(self, idea: Idea, max_claim_fetches: int = 5) -> PatentSearchResult:
        queries = self._queries(idea)
        hits: list[PatentHit] = []
        seen: set[str] = set()
        sources_used: list[str] = []
        for query in queries:
            for source in (self.patentsview, self.google, self.epo):
                for hit in source.search(query, self.config.results_per_query, idea.version):
                    number = hit.publication_number.upper()
                    if number in seen:
                        continue
                    seen.add(number)
                    hits.append(hit)
                    if source.name not in sources_used:
                        sources_used.append(source.name)
        ranked = self._rank(idea, hits)
        for hit in ranked[:max_claim_fetches]:
            if hit.claims:
                continue
            if hit.source == "patentsview" and self.patentsview.available:
                self.patentsview.fetch_claims(hit, iteration=idea.version)
            if not hit.claims:
                self.google.fetch_claims(hit, iteration=idea.version)
        matches = [
            self._compare(idea, hit) for hit in ranked[:max_claim_fetches] if hit.claims
        ]
        matches = [m for m in matches if m]
        matches.sort(key=lambda m: m.match_score, reverse=True)
        overlap = max((m.match_score for m in matches), default=0.0)
        self.tracer.log(
            f"patent_search: {len(hits)} patents retrieved, {len(matches)} claim-compared, "
            f"overlap_score={overlap}",
            self.name,
            idea.version,
        )
        return PatentSearchResult(
            overlap_score=overlap,
            rationale=getattr(self, "_summary", ""),
            matches=matches,
            hits=hits,
            queries=queries,
            sources_used=sources_used,
        )

    def _queries(self, idea: Idea) -> list[str]:
        queries = list(idea.elements[:4])
        if idea.title:
            queries.insert(0, idea.title)
        return queries

    def _rank(self, idea: Idea, hits: list[PatentHit]) -> list[PatentHit]:
        """Order retrieved patents by lexical closeness so claim fetches are spent well."""

        idea_text = " ".join([idea.text, *idea.elements])
        corpus = [f"{h.title}. {h.abstract}" for h in hits] + [idea_text]
        return sorted(
            hits,
            key=lambda h: best_cosine(f"{h.title}. {h.abstract}", [idea_text], corpus),
            reverse=True,
        )

    def _compare(self, idea: Idea, hit: PatentHit) -> PatentMatch | None:
        claims_block = "\n\n".join(hit.claims)
        parsed = self.llm.json_call(
            agent=self.name,
            purpose=f"claim_comparison:{hit.publication_number}",
            system=COMPARISON_SYSTEM,
            user=(
                f"Proposed invention (v{idea.version}): {idea.text}\n\n"
                "Elements:\n" + "\n".join(f"- {e}" for e in idea.elements)
                + f"\n\nPatent {hit.publication_number} — {hit.title} ({hit.assignee})\n"
                f"Claims as retrieved:\n{claims_block}"
            ),
            required_keys=("collisions",),
            iteration=idea.version,
        )
        self._summary = str(parsed.get("summary") or getattr(self, "_summary", ""))
        collisions = []
        for item in parsed.get("collisions") or []:
            element = str(item.get("element") or "").strip()
            if not element:
                continue
            collisions.append(
                ElementCollision(
                    element=element,
                    publication_number=hit.publication_number,
                    claim_number=str(item.get("claim_number") or ""),
                    claim_text=str(item.get("quote") or "")[:1200],
                    reads_on=as_bool(item.get("reads_on")),
                    reasoning=str(item.get("reasoning") or ""),
                )
            )
        overlapping = sorted({c.element for c in collisions if c.reads_on})
        coverage = (len(overlapping) / len(idea.elements) * 100) if idea.elements else 0.0
        lexical = best_cosine(
            " ".join([idea.text, *idea.elements]),
            hit.claims,
            hit.claims + [" ".join([idea.text, *idea.elements])],
        )
        match_score = round(0.7 * coverage + 0.3 * lexical * 100, 2)
        return PatentMatch(
            publication_number=hit.publication_number,
            title=hit.title,
            assignee=hit.assignee,
            url=hit.url,
            source=hit.source,
            overlapping_elements=overlapping,
            collisions=collisions,
            llm_overlap=round(coverage, 2),
            lexical_overlap=round(lexical, 4),
            match_score=match_score,
        )
