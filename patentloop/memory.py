"""Cross-run prior-art memory: every run deposits the patents it retrieved into
a shared store; later runs recall the most similar records before searching live,
so runs provably build on each other (each recalled record carries the run_id
that discovered it)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .llm import cosine, embed

MEMORY_FILENAME = "memory.json"


def memory_path(runs_dir: str | Path) -> Path:
    return Path(runs_dir) / MEMORY_FILENAME


def load_memory(runs_dir: str | Path) -> list[dict[str, Any]]:
    path = memory_path(runs_dir)
    if not path.exists():
        return []
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return records if isinstance(records, list) else []


def save_memory(runs_dir: str | Path, records: list[dict[str, Any]]) -> None:
    path = memory_path(runs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")


def harvest_run(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """All unique patent records retrieved during a run, tagged with its run_id."""
    run_id = trace.get("run_id")
    harvested: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in trace.get("iterations") or []:
        records = (entry.get("patent_search") or {}).get("records") or []
        for record in records:
            patent_id = record.get("patent_id")
            if not patent_id or patent_id in seen:
                continue
            seen.add(patent_id)
            harvested.append({
                "patent_id": patent_id,
                "title": record.get("title") or "",
                "abstract": record.get("abstract") or "",
                "url": record.get("url"),
                "source_run_id": run_id,
                "source_iteration": entry.get("iteration"),
            })
    return harvested


def merge_memory(existing: list[dict[str, Any]],
                 harvested: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append harvested records not already in memory (dedup by patent_id)."""
    known = {record.get("patent_id") for record in existing}
    return existing + [r for r in harvested if r.get("patent_id") not in known]


def rank_records(query_vector: list[float], records: list[dict[str, Any]],
                 top_k: int = 8, min_similarity: float = 0.25) -> list[dict[str, Any]]:
    """Pure ranking of memory records (with precomputed ``embedding``) against a
    query vector; returns copies with a ``similarity`` field, best first."""
    scored = []
    for record in records:
        vector = record.get("embedding")
        if not vector:
            continue
        similarity = cosine(query_vector, vector)
        if similarity < min_similarity:
            continue
        ranked = {k: v for k, v in record.items() if k != "embedding"}
        ranked["similarity"] = round(similarity, 4)
        scored.append(ranked)
    scored.sort(key=lambda r: r["similarity"], reverse=True)
    return scored[:top_k]


def update_memory(runs_dir: str | Path, trace: dict[str, Any]) -> int:
    """Deposit this run's retrieved patents into the shared store, embedding new
    records so future runs can recall them. Returns the number of new records."""
    existing = load_memory(runs_dir)
    known = {record.get("patent_id") for record in existing}
    fresh = [r for r in harvest_run(trace) if r.get("patent_id") not in known]
    if not fresh:
        return 0
    vectors = embed([f"{r['title']}. {r['abstract']}"[:2000] for r in fresh])
    for record, vector in zip(fresh, vectors):
        record["embedding"] = vector
    save_memory(runs_dir, existing + fresh)
    return len(fresh)


def recall(idea: str, runs_dir: str | Path, top_k: int = 8) -> list[dict[str, Any]]:
    """Most similar prior-art records that earlier runs discovered, best first."""
    records = load_memory(runs_dir)
    if not records:
        return []
    query_vector = embed([idea[:2000]])[0]
    return rank_records(query_vector, records, top_k=top_k)
