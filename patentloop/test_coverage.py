"""Tests for patentloop.coverage — pure functions, hand-built fixtures."""

from patentloop.coverage import build_matrix, elements_from_extraction, is_covered

ELEMENT_COIL = {
    "id": "E1",
    "text": "shape-memory nitinol coil",
    "search_terms": ["nitinol coil", "shape memory alloy"],
}
ELEMENT_PAWL = {
    "id": "E2",
    "text": "ratcheting pawl",
    "search_terms": ["ratcheting pawl"],
}

PATENT_COIL = {
    "patent_id": "US1234567",
    "title": "Suture anchor with nitinol coil",
    "abstract": "An anchor body houses a nitinol coil. The coil re-tensions the suture.",
}
PATENT_UNRELATED = {
    "patent_id": "US7654321",
    "title": "Water dispenser",
    "abstract": "A dispenser for dispensing water into a cup.",
}


def test_is_covered_returns_matching_sentence():
    covered, evidence = is_covered(ELEMENT_COIL, PATENT_COIL)
    assert covered is True
    assert evidence == "Suture anchor with nitinol coil"


def test_is_covered_no_match():
    covered, evidence = is_covered(ELEMENT_PAWL, PATENT_UNRELATED)
    assert covered is False
    assert evidence == ""


def test_is_covered_requires_all_term_words_in_one_sentence():
    patent = {
        "patent_id": "US1",
        "title": "Ratcheting mechanism",
        "abstract": "A pawl engages a gear.",
    }
    covered, _ = is_covered(ELEMENT_PAWL, patent)
    assert covered is False  # "ratcheting" and "pawl" never share a sentence


def test_is_covered_handles_empty_patent():
    covered, evidence = is_covered(ELEMENT_COIL, {"patent_id": "US0"})
    assert (covered, evidence) == (False, "")


def test_build_matrix_shape_and_uncovered():
    result = build_matrix([ELEMENT_COIL, ELEMENT_PAWL], [PATENT_COIL, PATENT_UNRELATED])
    assert set(result) == {"elements", "patents", "coverage", "uncovered"}
    assert result["elements"] == [ELEMENT_COIL, ELEMENT_PAWL]
    assert result["patents"] == [PATENT_COIL, PATENT_UNRELATED]
    assert result["coverage"]["E1"]["US1234567"]["covered"] is True
    assert result["coverage"]["E1"]["US1234567"]["evidence"]
    assert result["coverage"]["E1"]["US7654321"]["covered"] is False
    assert result["coverage"]["E2"]["US1234567"]["covered"] is False
    assert result["uncovered"] == ["E2"]


def test_build_matrix_no_patents_marks_all_uncovered():
    result = build_matrix([ELEMENT_COIL, ELEMENT_PAWL], [])
    assert result["uncovered"] == ["E1", "E2"]
    assert result["coverage"] == {"E1": {}, "E2": {}}


def test_build_matrix_generates_missing_ids():
    element = {"text": "unlabelled", "search_terms": ["nitinol coil"]}
    patent = {"title": "A nitinol coil device", "abstract": ""}
    result = build_matrix([element], [patent])
    assert result["coverage"]["E1"]["unknown-1"]["covered"] is True
    assert result["uncovered"] == []


def test_elements_from_extraction_adapts_shape():
    extraction = {
        "elements": ["nitinol coil", "ratcheting pawl"],
        "search_queries": ["shape memory coil", "ratcheting pawl"],
    }
    adapted = elements_from_extraction(extraction)
    assert adapted == [
        {"id": "E1", "text": "nitinol coil",
         "search_terms": ["nitinol coil", "shape memory coil"]},
        {"id": "E2", "text": "ratcheting pawl", "search_terms": ["ratcheting pawl"]},
    ]
