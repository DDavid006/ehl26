"""Patent overlap search, claim validation, and scoring."""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Lock

from . import AUTONOMOUS_INSTRUCTION
from ..errors import EvidenceFailure

WEIGHTS = {"maps": 1.0, "partial": 0.5, "none": 0.0}


def validate_claim_quote(verdict: dict, claim_text: str) -> dict:
    result = dict(verdict)
    quote = result.get("claim_quote", "")
    if quote and quote not in claim_text:
        result["claim_quote"] = ""
        result["verdict"] = "partial" if result.get("verdict") == "maps" else "none"
        result["quote_invalid"] = True
    return result


def patent_overlap(element_verdicts: list[dict], n_elements: int | None = None) -> float:
    n_elements = n_elements or len(element_verdicts)
    return sum(WEIGHTS.get(item.get("verdict"), 0) for item in element_verdicts) / n_elements if n_elements else 0.0


def overlap_score(patents: list[dict]) -> int:
    if not patents:
        return 0
    return round(100 * max(
        item.get("overlap", patent_overlap(item.get("element_verdicts", [])))
        for item in patents
    ))


class PatentSearchAgent:
    def __init__(self, llm, sources, *, allow_devin_search: bool = False):
        self.llm, self.sources = llm, sources
        self.allow_devin_search = allow_devin_search

    def _devin_search(self, idea_text: str, keywords: list[str]) -> list[dict]:
        schema = {
            "name": "patent_search_hits",
            "schema": {
                "type": "object",
                "required": ["hits"],
                "properties": {
                    "hits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "patent_number", "title", "assignee", "status",
                                "claim_number", "claim_text", "url",
                            ],
                            "properties": {
                                key: {"type": "string"}
                                for key in (
                                    "patent_number", "title", "assignee", "status",
                                    "claim_number", "claim_text", "url",
                                )
                            },
                        },
                    }
                },
            },
        }
        prompt = (
            AUTONOMOUS_INSTRUCTION
            + "You are a patent-search specialist. Use your browser to open real "
            "public patent database records. Open every record you report. Never "
            "invent or infer a reference that you did not open. Return verbatim "
            "claim text captured from the opened record.\n"
            + json.dumps(
                {"idea": idea_text, "keywords": keywords},
                indent=2,
                sort_keys=True,
            )
        )
        output = self.llm.chat(prompt, schema, agent="devin_patent_search", title="PatentLoop patent search")
        evidence_path = getattr(self.llm, "last_log_path", None)
        return [
            {
                "id": hit["patent_number"],
                "title": hit["title"],
                "assignee": hit["assignee"],
                "status": hit["status"],
                "claim_number": hit["claim_number"],
                "claims": hit["claim_text"],
                "claim1": hit["claim_text"],
                "url": hit["url"],
                "source": "devin_patent_search",
                "raw_path": evidence_path,
            }
            for hit in output.get("hits", [])
            if hit.get("patent_number") and hit.get("claim_text") and hit.get("url")
        ]

    def run(self, idea_text: str, extracted: dict, *, iteration: int, run_dir) -> dict:
        keywords = [keyword for element in extracted["elements"] for keyword in element.get("keywords", [])]
        source_log_lock = Lock()
        source_errors = []

        def record_source_error(error: dict) -> None:
            source_errors.append(error)
            with source_log_lock:
                directory = Path(run_dir)
                directory.mkdir(parents=True, exist_ok=True)
                with (directory / "run.log").open("a") as log:
                    log.write(
                        "patent source failure: "
                        f"{error['source']}: {error['error']}\n"
                    )

        def search_source(source, query):
            source_name = getattr(source, "name", type(source).__name__)
            try:
                return source.search(
                    query, iteration=iteration, run_dir=run_dir
                ) or []
            except Exception as exc:
                record_source_error(
                    {"source": source_name, "query": query, "error": str(exc)}
                )
                return []

        hits = []
        for source in self.sources:
            hits.extend(search_source(source, keywords))
        if not hits:
            broadened = []
            for element in extracted["elements"]:
                terms = element.get("keywords") or [element.get("text", "")]
                for term in terms[:3]:
                    if term:
                        broadened.append(term)
            for source in self.sources:
                for term in broadened:
                    hits.extend(search_source(source, [term]))
        unique_hits = {}
        for hit in hits:
            identifier = hit.get("id") or hit.get("patent_number") or hit.get("url")
            if identifier:
                unique_hits[identifier] = hit
        hits = list(unique_hits.values())
        if not hits and self.allow_devin_search:
            try:
                hits = self._devin_search(idea_text, keywords)
            except Exception as exc:
                record_source_error(
                    {
                        "source": "devin_patent_search",
                        "query": keywords,
                        "error": str(exc),
                    }
                )
                hits = []
        if not hits:
            error_suffix = ""
            if source_errors:
                error_suffix = "; source errors: " + "; ".join(
                    f"{item['source']}: {item['error']}" for item in source_errors
                )
            raise EvidenceFailure(
                "Patent search returned no records after broadened queries"
                + error_suffix,
                {"patents_examined": 0, "source_errors": source_errors},
            )
        vectors, embed_path = self.llm.embed(
            [idea_text] + [f"{item.get('claims', '')} {item.get('abstract', '')}" for item in hits],
            agent="patent_rank",
        ) if hits else ([[]], None)
        ranked = []
        from .research import cosine
        for hit, vector in zip(hits, vectors[1:]):
            item = dict(hit)
            item["_similarity"] = cosine(vectors[0], vector)
            ranked.append(item)
        ranked.sort(key=lambda item: item["_similarity"], reverse=True)
        kept = ranked[:12]
        llm_paths = [embed_path] if embed_path else []
        def map_claims(patent):
            result = self.llm.chat(
                AUTONOMOUS_INSTRUCTION
                + "Map each idea element to exact claim language. Claim quotes must be substrings.\n"
                + json.dumps(
                    {"elements": extracted["elements"], "patent": patent},
                    indent=2,
                    sort_keys=True,
                ),
                {
                    "name": "claim_mapping",
                    "schema": {
                        "type": "object",
                        "required": ["element_verdicts"],
                        "properties": {
                            "element_verdicts": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": [
                                        "element_id", "verdict", "claim_number",
                                        "claim_quote", "why",
                                    ],
                                    "properties": {
                                        "element_id": {"type": "string"},
                                        "verdict": {
                                            "type": "string",
                                            "enum": ["maps", "partial", "none"],
                                        },
                                        "claim_number": {"type": "string"},
                                        "claim_quote": {"type": "string"},
                                        "why": {"type": "string"},
                                    },
                                },
                            }
                        },
                    },
                },
                agent=f"claim_map_{patent.get('id', 'unknown')}",
            )
            verdicts = [
                validate_claim_quote(item, patent.get("claims") or patent.get("claim1", ""))
                for item in result.get("element_verdicts", [])
            ]
            patent["element_verdicts"] = verdicts
            patent["overlap"] = patent_overlap(verdicts, len(extracted["elements"]))
            patent["similarity"] = patent.pop("_similarity")
            return patent, getattr(self.llm, "last_log_path", None)
        mapped = []
        if kept:
            with ThreadPoolExecutor(max_workers=min(5, len(kept))) as pool:
                mapped = list(pool.map(map_claims, kept))
        kept = [patent for patent, path in mapped]
        llm_paths.extend(path for _, path in mapped if path)
        kept.sort(key=lambda item: item["overlap"], reverse=True)
        return {
            "patents": kept,
            "overlap_score": overlap_score(kept),
            "runner_up": kept[1] if len(kept) > 1 else None,
            "patents_examined": len(kept),
            "source_errors": source_errors,
            "llm_paths": llm_paths,
        }
