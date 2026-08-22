"""Drafting agent: writes the provisional application once every gate passes.

The draft is grounded in the run's own findings: the background section must
reference the publications the research agent retrieved, and the novelty section
must name the patents the search agent found and say why the claims do not read
on the invention.
"""

from __future__ import annotations

from ..config import Config
from ..llm import LLM
from ..schemas import Idea, PatentSearchResult, ResearchResult
from ..trace import Tracer

SYSTEM = """You are a US patent attorney drafting a provisional patent application from an invention
disclosure and a prior-art dossier that was assembled from live database searches.

Write a complete draft with these sections, in markdown, in this order:
1. `# Title`
2. `## Field of the Invention`
3. `## Background` — describe the state of the art using ONLY the supplied publications and patents,
   citing them by identifier/number, and state the unmet need.
4. `## Summary of the Invention`
5. `## Detailed Description` — enabling detail: structure, materials/parameters with ranges,
   operation, at least one worked embodiment, and alternatives.
6. `## Claims` — one independent claim (single sentence, "1. A ... comprising:" with indented
   elements) followed by 4-8 dependent claims that narrow specific elements.
7. `## Why This Is Novel` — plain English, naming the specific prior art from the dossier and the
   specific claim language of each cited patent that the invention does not read on.
8. `## Abstract` — under 150 words.

Never cite a document that is not in the dossier. Reply with a single JSON object:
{"title": str, "document_markdown": str} where document_markdown is the full draft."""

DISCLAIMER = (
    "> **Drafting aid, not legal advice.** This document was generated autonomously by PatentLoop "
    "from live literature and patent-database searches. It has not been reviewed by an attorney and "
    "is not filed with any patent office."
)


class DraftingAgent:
    name = "drafting"

    def __init__(self, config: Config, tracer: Tracer, llm: LLM):
        self.config = config
        self.tracer = tracer
        self.llm = llm

    def run(self, idea: Idea, research: ResearchResult, patents: PatentSearchResult) -> str:
        publications = "\n".join(
            f"- [{d.source}:{d.external_id}] {d.title} ({d.year}) {d.url}\n  {(d.abstract or '')[:400]}"
            for d in research.documents[:12]
        ) or "- (no publications retrieved)"
        patent_lines = []
        for match in patents.matches[:6]:
            claims = "; ".join(
                f"claim {c.claim_number}: {c.claim_text[:300]}" for c in match.collisions[:3]
            )
            patent_lines.append(
                f"- {match.publication_number} — {match.title} ({match.assignee}) overlap "
                f"{match.match_score}/100; {claims}"
            )
        parsed = self.llm.json_call(
            agent=self.name,
            purpose="draft_application",
            system=SYSTEM,
            user=(
                f"Invention disclosure (idea v{idea.version}, title: {idea.title}, field: "
                f"{idea.field_of_art}):\n{idea.text}\n\n"
                "Claim elements:\n" + "\n".join(f"- {e}" for e in idea.elements)
                + f"\n\nNovelty score {research.novelty_score}/100. Research rationale: "
                f"{research.rationale}\n\nRetrieved publications:\n{publications}\n\n"
                f"Closest patents (overlap score {patents.overlap_score}/100):\n"
                + ("\n".join(patent_lines) or "- (no patents with claim overlap)")
            ),
            required_keys=("document_markdown",),
            max_tokens=8000,
            iteration=idea.version,
        )
        document = str(parsed.get("document_markdown") or "").strip()
        self.tracer.log(f"drafting: {len(document)} characters drafted", self.name, idea.version)
        return f"{DISCLAIMER}\n\n{document}\n"
