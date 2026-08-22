"""Tests for patentloop.memory — pure parts only, hand-built fixtures."""

from patentloop.memory import (harvest_run, load_memory, merge_memory,
                               rank_records, save_memory)

TRACE = {
    "run_id": "run-A",
    "iterations": [
        {"iteration": 1, "patent_search": {"records": [
            {"patent_id": "US1", "title": "Anchor", "abstract": "A body.", "url": "u1"},
            {"patent_id": "US2", "title": "Coil", "abstract": "A coil.", "url": "u2"},
        ]}},
        {"iteration": 2, "patent_search": {"records": [
            {"patent_id": "US2", "title": "Coil", "abstract": "A coil.", "url": "u2"},
            {"patent_id": "US3", "title": "Pawl", "abstract": "A pawl.", "url": "u3"},
        ]}},
    ],
}


def test_harvest_run_dedupes_and_tags_source():
    records = harvest_run(TRACE)
    assert [r["patent_id"] for r in records] == ["US1", "US2", "US3"]
    assert all(r["source_run_id"] == "run-A" for r in records)
    assert records[0]["source_iteration"] == 1
    assert records[2]["source_iteration"] == 2


def test_merge_memory_appends_only_new():
    existing = [{"patent_id": "US2", "title": "Coil"}]
    merged = merge_memory(existing, harvest_run(TRACE))
    assert [r["patent_id"] for r in merged] == ["US2", "US1", "US3"]


def test_rank_records_sorts_and_thresholds():
    records = [
        {"patent_id": "US1", "embedding": [1.0, 0.0]},
        {"patent_id": "US2", "embedding": [0.7, 0.7]},
        {"patent_id": "US3", "embedding": [0.0, 1.0]},   # orthogonal -> below threshold
        {"patent_id": "US4"},                            # no embedding -> skipped
    ]
    ranked = rank_records([1.0, 0.0], records, top_k=5)
    assert [r["patent_id"] for r in ranked] == ["US1", "US2"]
    assert ranked[0]["similarity"] == 1.0
    assert all("embedding" not in r for r in ranked)


def test_rank_records_respects_top_k():
    records = [{"patent_id": f"US{i}", "embedding": [1.0, 0.0]} for i in range(5)]
    assert len(rank_records([1.0, 0.0], records, top_k=2)) == 2


def test_load_save_roundtrip(tmp_path):
    assert load_memory(tmp_path) == []
    save_memory(tmp_path, [{"patent_id": "US1"}])
    assert load_memory(tmp_path) == [{"patent_id": "US1"}]


def test_load_memory_tolerates_corrupt_file(tmp_path):
    (tmp_path / "memory.json").write_text("not json", encoding="utf-8")
    assert load_memory(tmp_path) == []
