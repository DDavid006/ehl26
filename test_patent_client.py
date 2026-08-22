import json

import pytest

import patent_client


def record(patent_id="US10123456B2", **overrides):
    base = {
        "patent_id": patent_id,
        "title": "Distributed sensor data aggregation",
        "abstract": "A method for aggregating measurements.",
        "assignee": "Northfield Instruments, Inc.",
        "date": "2018-11-13",
    }
    base.update(overrides)
    return base


def records(count, start=0):
    return [record(f"US1012345{index}B2") for index in range(start, start + count)]


@pytest.fixture(autouse=True)
def fallback_file(tmp_path, monkeypatch):
    monkeypatch.setattr(patent_client, "FALLBACK_PATH", tmp_path / "fallback_corpus.json")
    return tmp_path / "fallback_corpus.json"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Every search goes through the model; the client itself never fetches."""
    monkeypatch.setattr(
        patent_client,
        "search_text",
        lambda *args, **kwargs: pytest.fail("the search model was not stubbed"),
    )


def install_search(monkeypatch, answer=None, *, error=None):
    calls = []

    def fake_search(prompt, error_cls, task="search"):
        calls.append({"prompt": prompt, "error_cls": error_cls, "task": task})
        if error is not None:
            raise error
        return answer if isinstance(answer, str) else json.dumps(answer)

    monkeypatch.setattr(patent_client, "search_text", fake_search)
    return calls


def test_asks_the_model_to_search_the_patent_hosts(monkeypatch):
    calls = install_search(monkeypatch, records(3))

    results = patent_client.search_patents("sensor fusion", limit=3)

    prompt = calls[0]["prompt"]
    assert "sensor fusion" in prompt
    assert "patents.google.com" in prompt and "worldwide.espacenet.com" in prompt
    assert calls[0]["task"] == "search: sensor fusion"
    assert len(results) == 3
    assert all(sorted(r) == sorted(patent_client.RESULT_KEYS) for r in results)
    assert results[0] == record("US10123450B2")


def test_reads_records_wrapped_in_prose_or_fences(monkeypatch):
    install_search(
        monkeypatch,
        "Here is what I found:\n```json\n" + json.dumps(records(1)) + "\n```\nHope that helps.",
    )

    assert patent_client.search_patents("sensor fusion")[0]["patent_id"] == "US10123450B2"


def test_strips_site_boilerplate_from_titles(monkeypatch):
    install_search(
        monkeypatch,
        [record("US20150101870A1", title="US20150101870A1 - Weight sensing - Google Patents")],
    )

    assert patent_client.search_patents("weight sensing")[0]["title"] == "Weight sensing"


def test_reads_the_publication_number_from_a_url_when_the_field_is_missing(monkeypatch):
    install_search(
        monkeypatch,
        [
            {
                "url": "https://worldwide.espacenet.com/patent/search?CC=EP&NR=3210987A1",
                "title": "Adaptive thermal management",
            }
        ],
    )

    assert patent_client.search_patents("thermal management") == [
        {
            "patent_id": "EP3210987A1",
            "title": "Adaptive thermal management",
            "abstract": None,
            "assignee": None,
            "date": None,
        }
    ]


def test_drops_entries_without_a_well_formed_publication_number(monkeypatch):
    install_search(
        monkeypatch,
        [
            record(patent_id=None),
            record(patent_id="a patent about sensors"),
            record(patent_id="12345"),
            *records(2),
        ],
    )

    results = patent_client.search_patents("sensor fusion")

    assert [r["patent_id"] for r in results] == ["US10123450B2", "US10123451B2"]


def test_normalises_spacing_and_case_in_publication_numbers(monkeypatch):
    install_search(monkeypatch, [record("us 10,123,456 b2")])

    assert patent_client.search_patents("sensor fusion")[0]["patent_id"] == "US10123456B2"


def test_deduplicates_repeated_publications(monkeypatch):
    install_search(monkeypatch, [record(), record(), *records(3)])

    ids = [r["patent_id"] for r in patent_client.search_patents("sensor fusion")]

    assert len(ids) == len(set(ids))


def test_respects_limit(monkeypatch):
    install_search(monkeypatch, records(6))

    assert len(patent_client.search_patents("sensor fusion", limit=3)) == 3
    assert patent_client.search_patents("sensor fusion", limit=0) == []


def test_an_empty_result_falls_back_to_the_local_corpus(monkeypatch):
    install_search(monkeypatch, [])

    results = patent_client.search_patents("sensor fusion")

    assert len(results) == 5
    assert results[0]["patent_id"] == patent_client.FALLBACK_ENTRIES[0]["patent_id"]


def test_an_unparsable_answer_falls_back(monkeypatch):
    install_search(monkeypatch, "I could not find anything relevant.")

    assert len(patent_client.search_patents("sensor fusion")) == 5


def test_a_search_failure_falls_back(monkeypatch, fallback_file):
    install_search(monkeypatch, error=RuntimeError("401 from OpenAI"))

    results = patent_client.search_patents("sensor fusion")

    assert fallback_file.exists()
    assert len(results) == 5
    assert all(sorted(r) == sorted(patent_client.RESULT_KEYS) for r in results)


def test_timeout_falls_back(monkeypatch):
    install_search(monkeypatch, records(5))
    clock = iter([0, 999, 999])
    monkeypatch.setattr(patent_client.time, "monotonic", lambda: next(clock))

    results = patent_client.search_patents("sensor fusion")

    assert results[0]["patent_id"] == patent_client.FALLBACK_ENTRIES[0]["patent_id"]


def test_existing_fallback_file_is_used_and_normalized(monkeypatch, fallback_file):
    fallback_file.write_text(
        json.dumps([{"patent_id": "US1B1", "title": "", "abstract": "a"}]),
        encoding="utf-8",
    )
    install_search(monkeypatch, [])

    assert patent_client.search_patents("sensor fusion") == [
        {
            "patent_id": "US1B1",
            "title": None,
            "abstract": "a",
            "assignee": None,
            "date": None,
        }
    ]


def test_fallback_respects_limit(monkeypatch):
    install_search(monkeypatch, [])

    assert len(patent_client.search_patents("sensor fusion", limit=2)) == 2


def test_corrupt_fallback_file_returns_empty(monkeypatch, fallback_file):
    fallback_file.write_text("not json", encoding="utf-8")
    install_search(monkeypatch, [])

    assert patent_client.search_patents("sensor fusion") == []
