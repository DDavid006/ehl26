import coverage
from coverage import build_matrix, is_covered


ELEMENTS = [
    {
        "id": "E1",
        "text": "a delivery format applied without rinsing",
        "search_terms": ["leave-on formulation", "rinse free composition"],
    },
    {
        "id": "E2",
        "text": "an agent that attenuates ultraviolet radiation at the scalp",
        "search_terms": ["ultraviolet filter", "sunscreen active"],
    },
    {
        "id": "E3",
        "text": "a carrier that spreads through dense hair to reach the skin",
        "search_terms": ["scalp delivery vehicle", "hair penetrating carrier"],
    },
    {
        "id": "E4",
        "text": "a dispenser that meters a fixed dose per application",
        "search_terms": ["metered dose dispenser", "dosing pump"],
    },
]

PATENTS = [
    {
        "patent_id": "US1234567",
        "title": "Leave-on formulation for scalp care",
        "abstract": (
            "A composition comprising an ultraviolet filter suspended in a foam. "
            "The foam is a scalp delivery vehicle that spreads between hair fibers."
        ),
        "assignee": "Acme Labs",
        "date": "2020-01-01",
    },
    {
        "patent_id": "US7654321",
        "title": "Sunscreen active for topical use",
        "abstract": "A sunscreen active dispersed in an aqueous carrier.",
        "assignee": None,
        "date": None,
    },
]


def test_matrix_shape_and_keys():
    matrix = build_matrix(ELEMENTS, PATENTS)

    assert sorted(matrix) == ["coverage", "elements", "patents", "uncovered"]
    assert matrix["elements"] == ELEMENTS
    assert matrix["patents"] == PATENTS
    assert sorted(matrix["coverage"]) == ["E1", "E2", "E3", "E4"]
    for per_patent in matrix["coverage"].values():
        assert sorted(per_patent) == ["US1234567", "US7654321"]
        for cell in per_patent.values():
            assert sorted(cell) == ["covered", "evidence"]
            assert isinstance(cell["covered"], bool)
            assert isinstance(cell["evidence"], str)


def test_covered_cells_carry_matching_sentence_as_evidence():
    matrix = build_matrix(ELEMENTS, PATENTS)

    cell = matrix["coverage"]["E1"]["US1234567"]
    assert cell["covered"] is True
    assert cell["evidence"] == "Leave-on formulation for scalp care"

    cell = matrix["coverage"]["E2"]["US1234567"]
    assert cell["covered"] is True
    assert "ultraviolet filter" in cell["evidence"]

    cell = matrix["coverage"]["E3"]["US1234567"]
    assert cell["covered"] is True
    assert cell["evidence"].startswith("The foam is a scalp delivery vehicle")


def test_uncovered_lists_elements_no_patent_covers():
    matrix = build_matrix(ELEMENTS, PATENTS)

    assert matrix["uncovered"] == ["E4"]
    assert all(
        cell["covered"] is False and cell["evidence"] == ""
        for cell in matrix["coverage"]["E4"].values()
    )


def test_all_elements_uncovered_without_patents():
    matrix = build_matrix(ELEMENTS, [])

    assert matrix["uncovered"] == ["E1", "E2", "E3", "E4"]
    assert matrix["coverage"]["E1"] == {}


def test_empty_elements_yield_empty_coverage():
    matrix = build_matrix([], PATENTS)

    assert matrix["coverage"] == {}
    assert matrix["uncovered"] == []


def test_matching_ignores_case_and_word_endings():
    element = {"id": "E1", "search_terms": ["load cell"]}
    patent = {
        "patent_id": "US1",
        "title": "Load Cells for weighing vessels",
        "abstract": None,
    }

    covered, evidence = is_covered(element, patent)

    assert covered is True
    assert evidence == "Load Cells for weighing vessels"


def test_matching_reduces_words_to_their_stem():
    element = {"id": "E1", "search_terms": ["temperature sensor"]}
    patent = {"patent_id": "US1", "title": "Temperature sensing system", "abstract": None}

    assert is_covered(element, patent) == (True, "Temperature sensing system")


def test_matching_ignores_filler_words_in_the_term():
    element = {"id": "E1", "search_terms": ["reminder system"]}
    patent = {"patent_id": "US1", "title": "Smart reminder for drinking liquids", "abstract": None}

    assert is_covered(element, patent) == (True, "Smart reminder for drinking liquids")


def test_a_single_matching_term_is_enough():
    element = {"id": "E1", "search_terms": ["hydration reminder", "load cell", "uv sterilisation"]}
    patent = {"patent_id": "US1", "title": "Vessel", "abstract": "A load cell in the base."}

    covered, evidence = is_covered(element, patent)

    assert covered is True
    assert evidence == "A load cell in the base."


def test_partial_term_overlap_is_not_a_match():
    element = {"id": "E1", "search_terms": ["metered dose dispenser"]}
    patent = {
        "patent_id": "US1",
        "title": "Dispenser for liquids",
        "abstract": "A dispenser that releases a dose of liquid.",
    }

    assert is_covered(element, patent) == (False, "")


def test_missing_fields_are_tolerated():
    assert is_covered({"id": "E1"}, PATENTS[0]) == (False, "")
    assert is_covered(ELEMENTS[0], {"patent_id": "US1"}) == (False, "")
    assert is_covered(
        {"id": "E1", "search_terms": [None, 42, "sunscreen active"]}, PATENTS[1]
    )[0] is True


def test_stopword_only_terms_do_not_match_everything():
    element = {"id": "E1", "search_terms": ["of the", "with"]}

    assert is_covered(element, PATENTS[0]) == (False, "")


def test_patents_without_id_get_stable_placeholder_keys():
    patents = [
        {"patent_id": None, "title": "Sunscreen active composition", "abstract": None},
        {"title": "Unrelated widget", "abstract": None},
    ]

    matrix = build_matrix([ELEMENTS[1]], patents)

    assert sorted(matrix["coverage"]["E2"]) == ["unknown-1", "unknown-2"]
    assert matrix["coverage"]["E2"]["unknown-1"]["covered"] is True
    assert matrix["uncovered"] == []


def test_elements_without_id_get_positional_keys():
    matrix = build_matrix([{"search_terms": ["sunscreen active"]}], PATENTS)

    assert list(matrix["coverage"]) == ["E1"]
    assert matrix["coverage"]["E1"]["US7654321"]["covered"] is True


def test_is_covered_is_swappable(monkeypatch):
    monkeypatch.setattr(coverage, "is_covered", lambda element, patent: (True, "stub"))

    matrix = build_matrix(ELEMENTS, PATENTS)

    assert matrix["uncovered"] == []
    assert matrix["coverage"]["E4"]["US1234567"] == {"covered": True, "evidence": "stub"}


def test_inputs_are_not_mutated():
    elements = [dict(element) for element in ELEMENTS]
    patents = [dict(patent) for patent in PATENTS]

    build_matrix(elements, patents)

    assert elements == ELEMENTS
    assert patents == PATENTS
