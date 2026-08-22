"""Novelty research agent and exact scoring formulas."""

from __future__ import annotations

import math
import json
from concurrent.futures import ThreadPoolExecutor

from . import AUTONOMOUS_INSTRUCTION
from ..errors import EvidenceFailure


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    denominator = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / denominator if denominator else 0.0


def element_novelty(element_vector: list[float], document_vectors: list[list[float]]) -> float:
    """1 - maximum cosine similarity over an element's top-ten documents."""
    if not document_vectors:
        return 0.0
    return 1.0 - max(cosine(element_vector, vector) for vector in document_vectors[:10])


def novelty_score(element_scores: list[float]) -> int:
    if not element_scores:
        return 0
    return round(100 * (0.5 * sum(element_scores) / len(element_scores) + 0.5 * min(element_scores)))


def validate_citation_ids(cited_ids: list[str], documents: list[dict]) -> list[str]:
    """Keep only citations that identify a document actually retrieved."""
    valid_ids = {document.get("id") for document in documents}
    return [citation_id for citation_id in cited_ids if citation_id in valid_ids]


class ResearchAgent:
    def __init__(self, llm, sources):
        self.llm, self.sources = llm, sources

    def run(self, extracted: dict, *, iteration: int, run_dir) -> dict:
        def search_element(element):
            query = " ".join(element.get("keywords") or [element["text"]])
            documents = []
            for source in self.sources:
                documents.extend(
                    document
                    for document in (
                        source.search(query, iteration=iteration, run_dir=run_dir) or []
                    )
                    if document.get("abstract")
                )
            return element["id"], documents

        documents_by_element = {}
        llm_paths = []
        with ThreadPoolExecutor(max_workers=min(5, len(extracted["elements"]))) as pool:
            for element_id, documents in pool.map(search_element, extracted["elements"]):
                documents_by_element[element_id] = documents
        scores = []
        element_scores = {}
        documents_retrieved = {}
        unverified_elements = []
        closest = []
        for element in extracted["elements"]:
            all_docs = documents_by_element[element["id"]]
            docs = all_docs[:10]
            documents_retrieved[element["id"]] = len(all_docs)
            if not docs:
                unverified_elements.append(element["id"])
                continue
            vectors, path = self.llm.embed(
                [element["text"]] + [f'{doc.get("title", "")} {doc.get("abstract", "")}' for doc in docs],
                agent=f"research_embed_{element['id']}",
            )
            if path:
                llm_paths.append(path)
            score = element_novelty(vectors[0], vectors[1:])
            scores.append(score)
            element_scores[element["id"]] = round(score, 6)
            for doc, vector in zip(docs, vectors[1:]):
                enriched = dict(doc)
                enriched["similarity"] = cosine(vectors[0], vector)
                closest.append(enriched)
        closest.sort(key=lambda item: item.get("similarity", 0), reverse=True)
        required = max(2, math.ceil(len(extracted["elements"]) / 2))
        verified_count = len(extracted["elements"]) - len(unverified_elements)
        if verified_count < required:
            details = {
                "documents_retrieved": documents_retrieved,
                "unverified_elements": unverified_elements,
                "verified_elements": verified_count,
                "required_verified_elements": required,
            }
            raise EvidenceFailure(
                "Insufficient literature evidence to calculate novelty: "
                f"{verified_count} of {len(extracted['elements'])} elements verified",
                details,
            )
        rationale = self.llm.chat(
            AUTONOMOUS_INSTRUCTION
            + "Explain novelty using only the supplied document ids; cite ids verbatim.\n"
            + json.dumps(
                {"elements": extracted["elements"], "documents": closest[:10]},
                indent=2,
                sort_keys=True,
            ),
            {
                "name": "novelty_rationale",
                "schema": {
                    "type": "object",
                    "required": ["rationale", "cited_ids"],
                    "properties": {
                        "rationale": {"type": "string"},
                        "cited_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
            agent="research_rationale",
        )
        path = getattr(self.llm, "last_log_path", None)
        if path:
            llm_paths.append(path)
        cited_ids = validate_citation_ids(rationale.get("cited_ids", []), closest)
        return {
            "novelty_score": novelty_score(scores),
            "element_scores": element_scores,
            "documents_retrieved": documents_retrieved,
            "unverified_elements": unverified_elements,
            "verified_elements": len(element_scores),
            "closest_publications": closest[:10],
            "rationale": rationale.get("rationale", ""),
            "cited_ids": cited_ids,
            "llm_paths": llm_paths,
        }
