import json

import pytest

import patent_client


class FakeResponse:
    def __init__(self, *, json_data=None, status=200):
        self._json = json_data
        self.status_code = status

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def hit(link, title="Distributed sensor data aggregation", snippet="A method for aggregating measurements."):
    return {"link": link, "title": title, "snippet": snippet}


def serper_payload(*hits):
    return {"organic": list(hits)}


def google_hits(count, start=0):
    return [hit(f"https://patents.google.com/patent/US1012345{i}B2/en") for i in range(start, start + count)]


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "test-key")


@pytest.fixture(autouse=True)
def fallback_file(tmp_path, monkeypatch):
    monkeypatch.setattr(patent_client, "FALLBACK_PATH", tmp_path / "fallback_corpus.json")
    return tmp_path / "fallback_corpus.json"


@pytest.fixture(autouse=True)
def no_page_fetches(monkeypatch):
    """Patent pages are never fetched; any GET is a bug."""

    def forbidden(*args, **kwargs):
        raise AssertionError("search_patents must not fetch patent pages")

    monkeypatch.setattr(patent_client.requests, "get", forbidden)


def install_transport(monkeypatch, *, search=None, search_error=None):
    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == patent_client.SERPER_ENDPOINT
        assert headers["X-API-KEY"] == "test-key"
        assert json["q"].endswith(" patent")
        if search_error is not None:
            raise search_error
        return FakeResponse(json_data=search)

    monkeypatch.setattr(patent_client.requests, "post", fake_post)


def test_builds_records_from_search_results(monkeypatch):
    install_transport(monkeypatch, search=serper_payload(*google_hits(3)))

    results = patent_client.search_patents("sensor fusion")

    assert len(results) == 3
    assert all(sorted(r) == sorted(patent_client.RESULT_KEYS) for r in results)
    assert results[0] == {
        "patent_id": "US10123450B2",
        "title": "Distributed sensor data aggregation",
        "abstract": "A method for aggregating measurements.",
        "assignee": None,
        "date": None,
    }


def test_strips_site_boilerplate_from_titles(monkeypatch):
    install_transport(
        monkeypatch,
        search=serper_payload(
            hit(
                "https://patents.google.com/patent/US20150101870A1/en",
                title="US20150101870A1 - Weight sensing - Google Patents",
            )
        ),
    )

    assert patent_client.search_patents("weight sensing")[0]["title"] == "Weight sensing"


def test_reads_patent_id_from_espacenet_url(monkeypatch):
    espacenet = hit(
        "https://worldwide.espacenet.com/patent/search?CC=EP&NR=3210987A1",
        title="Adaptive thermal management",
        snippet=None,
    )
    install_transport(monkeypatch, search=serper_payload(*google_hits(2), espacenet))

    result = patent_client.search_patents("thermal management")[-1]

    assert result["patent_id"] == "EP3210987A1"
    assert result["title"] == "Adaptive thermal management"
    assert result["abstract"] is None
    assert result["assignee"] is None
    assert result["date"] is None


def test_filters_non_patent_hosts(monkeypatch):
    install_transport(
        monkeypatch,
        search=serper_payload(
            hit("https://example.com/blog/patent-news"),
            hit("https://en.wikipedia.org/wiki/Patent"),
            *google_hits(1),
        ),
    )

    results = patent_client.search_patents("sensor fusion")

    assert [r["patent_id"] for r in results] == ["US10123450B2"]


def test_no_usable_result_falls_back(monkeypatch):
    install_transport(
        monkeypatch,
        search=serper_payload(hit("https://example.com/blog/patent-news")),
    )

    results = patent_client.search_patents("sensor fusion")

    assert len(results) == 5
    assert results[0]["patent_id"] == patent_client.FALLBACK_ENTRIES[0]["patent_id"]


def test_skips_results_without_a_patent_id(monkeypatch):
    install_transport(
        monkeypatch,
        search=serper_payload(
            hit("https://patents.google.com/?q=sensor+fusion"),
            *google_hits(3),
        ),
    )

    results = patent_client.search_patents("sensor fusion")

    assert [r["patent_id"] for r in results] == ["US10123450B2", "US10123451B2", "US10123452B2"]


def test_deduplicates_repeated_patent_ids(monkeypatch):
    duplicate = "https://patents.google.com/patent/US10123456B2/en"
    install_transport(
        monkeypatch,
        search=serper_payload(hit(duplicate), hit(duplicate + "?oq=x"), *google_hits(3)),
    )

    results = patent_client.search_patents("sensor fusion")

    ids = [r["patent_id"] for r in results]
    assert len(ids) == len(set(ids))


def test_respects_limit(monkeypatch):
    install_transport(monkeypatch, search=serper_payload(*google_hits(6)))

    assert len(patent_client.search_patents("sensor fusion", limit=3)) == 3
    assert patent_client.search_patents("sensor fusion", limit=0) == []


def test_search_error_falls_back(monkeypatch, fallback_file):
    install_transport(monkeypatch, search_error=RuntimeError("serper is down"))

    results = patent_client.search_patents("sensor fusion")

    assert fallback_file.exists()
    assert len(results) == 5
    assert all(sorted(r) == sorted(patent_client.RESULT_KEYS) for r in results)


def test_missing_api_key_falls_back(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    install_transport(monkeypatch, search=serper_payload())

    assert len(patent_client.search_patents("sensor fusion")) == 5


def test_timeout_falls_back(monkeypatch):
    install_transport(monkeypatch, search=serper_payload(*google_hits(5)))
    clock = iter([0, 99, 99])
    monkeypatch.setattr(patent_client.time, "monotonic", lambda: next(clock))

    results = patent_client.search_patents("sensor fusion")

    assert len(results) == 5
    assert results[0]["patent_id"] == patent_client.FALLBACK_ENTRIES[0]["patent_id"]


def test_existing_fallback_file_is_used_and_normalized(monkeypatch, fallback_file):
    fallback_file.write_text(
        json.dumps([{"patent_id": "US1B1", "title": "", "abstract": "a"}]),
        encoding="utf-8",
    )
    install_transport(monkeypatch, search=serper_payload())

    results = patent_client.search_patents("sensor fusion")

    assert results == [
        {
            "patent_id": "US1B1",
            "title": None,
            "abstract": "a",
            "assignee": None,
            "date": None,
        }
    ]


def test_fallback_respects_limit(monkeypatch):
    install_transport(monkeypatch, search=serper_payload())

    assert len(patent_client.search_patents("sensor fusion", limit=2)) == 2


def test_corrupt_fallback_file_returns_empty(monkeypatch, fallback_file):
    fallback_file.write_text("not json", encoding="utf-8")
    install_transport(monkeypatch, search=serper_payload())

    assert patent_client.search_patents("sensor fusion") == []
