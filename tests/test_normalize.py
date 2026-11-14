"""bp/normalize.py without the LLM: the name guard that stops a rewrite inventing rooms, storeys or
apartments, the reply unwrapping, typed feet and two-part counts."""
import pytest

from bp import normalize as N
from bp.templates import slots, template

SWISS = {"names": {"Bad", "Küche", "Wohnen", "Cage d'escalier"}, "tokens": {"5.06", "5.09", "7.01", "A", "B"}}
IFC = {"names": {"Erdgeschoss", "Küche (6)", "E01"}, "tokens": set()}


# ---------------------------------------------------------------- slots (what _valid checks)
def test_slots_and_template():
    q = "Is room 5.06 ('Wohnen') larger than room 5.09 ('Küche')?"
    assert slots(q) == ["Wohnen", "Küche"]
    assert template(q) == "Is room X (X) larger than room X (X)?"
    assert slots("What's the area of 'Cage d'escalier'?") == ["Cage d'escalier"]  # apostrophes don't split names
    assert slots("How many “Bad” rooms?") == ["Bad"]


# ---------------------------------------------------------------- _valid
@pytest.mark.parametrize("rewrite", [
    "How many rooms labelled 'Bad' are there on this floor?",
    "What is the net floor area of room 7.01 ('Bad') in m²?",
    "What is the net floor area of apartment A in m², summing all its rooms except balconies, loggias, terraces "
    "and other outdoor spaces?",
    "Is room 5.06 ('Wohnen') larger than room 5.09 ('Küche')?",
    "Is apartment B larger than apartment A?",
    "How many windows are drawn on this floor plan?",
])
def test_valid_swiss_accepts_names_on_the_drawing(rewrite):
    assert N._valid("swiss", rewrite, SWISS) is None


@pytest.mark.parametrize("rewrite, why", [
    ("How many rooms labelled 'Schlafzimmer' are there on this floor?", "name 'Schlafzimmer'"),
    ("What is the net floor area of room 9.99 ('Bad') in m²?", "room 9.99"),
    ("Is room 5.06 ('Wohnen') larger than room 6.01 ('Küche')?", "room 6.01"),     # second operand checked too
    ("Is apartment B larger than apartment C?", "apartment C"),
    ("What is the net floor area of apartment <LETTER> in m²?", "placeholder"),
    ("How many rooms labelled '<LABEL>' are there on this floor?", "<LABEL>"),     # a bare placeholder is no name
])
def test_valid_swiss_rejects_invented_names(rewrite, why):
    bad = N._valid("swiss", rewrite, SWISS)
    assert bad is not None and why in bad


def test_valid_ifc():
    assert N._valid("ifc", "What is the net floor area of the room 'Küche (6)' on 'Erdgeschoss', in m²?", IFC) is None
    assert N._valid("ifc", "How many doors are shown on the floor plan of 'E01'?", IFC) is None
    assert "Dachgeschoss" in N._valid("ifc", "How many doors are shown on the floor plan of 'Dachgeschoss'?", IFC)
    # no names known (e.g. the model failed to load) -> any quoted name is refused
    assert N._valid("ifc", "How many doors are shown on the floor plan of 'E01'?", {"names": set(), "tokens": set()})


def test_every_template_needs_its_placeholders_filled():
    for route, tpls in N.TEMPLATES.items():
        for t in tpls:
            if "<" in t:
                assert N._valid(route, t, {"names": set(), "tokens": set()}) is not None, t


# ---------------------------------------------------------------- reply parsing
@pytest.mark.parametrize("raw, want", [
    ('"How many sinks are there?"', "How many sinks are there?"),
    ("“How many sinks?”", "How many sinks?"),
    ("'How many rooms labelled 'Bad' are there on this floor?'",
     "How many rooms labelled 'Bad' are there on this floor?"),
    ("How many sinks?", "How many sinks?"),
    ("'Bad'", "'Bad'"),          # a quoted name, not a quoted question: left alone
    ("NONE", "NONE"),
])
def test_unwrap(raw, want):
    assert N._unwrap(raw) == want


def test_normalize_without_templates_makes_no_call():
    r = N.normalize("generic", {"question": "how many doors?", "path": "x.pdf"})
    assert r["question"] is None and r["cost_usd"] == 0.0


# ---------------------------------------------------------------- feet
@pytest.mark.parametrize("q, stripped", [
    ("What is the area of room 3 in square feet?", "What is the area of room 3?"),
    ("What is the total length of all walls on 'E01' in ft?", "What is the total length of all walls on 'E01'?"),
    ("Wie gross ist die Küche in sq ft?", "Wie gross ist die Küche?"),
    ("total volume of the slabs, cubic feet?", "total volume of the slabs?"),
    ("area in ft²", "area"),
])
def test_unit_request_feet(q, stripped):
    assert N.unit_request(q) == (stripped, True)


@pytest.mark.parametrize("q", ["How many footings are there?", "What is the area of room 3 in m²?",
                               "How many doors are shown on this floor plan?"])
def test_unit_request_metric(q):
    assert N.unit_request(q) == (q, False)


def test_unit_request_keeps_a_question_that_is_only_the_unit():
    assert N.unit_request("feet?") == ("feet?", True)


@pytest.mark.parametrize("qtype, metric, feet, unit", [
    ("area", 10.0, 107.6, "ft²"),
    ("area", "15.47", 166.5, "ft²"),
    ("length", 100, 328.1, "ft"),
    ("volume", 2.0, 70.6, "ft³"),
])
def test_to_feet(qtype, metric, feet, unit):
    r = N.to_feet({"answer": metric, "explanation": "why"}, qtype)
    assert r["answer"] == pytest.approx(feet)
    assert r["unit"] == unit and r["answer_metric"] == metric
    assert r["explanation"].endswith("| why")


def test_to_feet_leaves_counts_and_abstains():
    r = N.to_feet({"answer": 4, "explanation": "4 doors"}, "count")
    assert r["answer"] == 4 and "unit" not in r and r["explanation"].startswith("(no unit conversion")
    r = N.to_feet({"answer": None}, "area")
    assert r == {"answer": None}


def test_feet_factors():
    assert N.FT_FACTOR["area"][0] == pytest.approx(3.28084 ** 2, rel=1e-4)
    assert N.FT_FACTOR["volume"][0] == pytest.approx(3.28084 ** 3, rel=1e-4)


# ---------------------------------------------------------------- two-part counts
def test_split_multi():
    assert N.split_multi("How many doors and windows are on this floor?") == [
        ("doors", "How many doors are on this floor?"), ("windows", "How many windows are on this floor?")]
    assert N.split_multi("number of bedrooms, bathrooms") == [("bedrooms", "How many bedrooms?"),
                                                             ("bathrooms", "How many bathrooms?")]


@pytest.mark.parametrize("q", [
    "how many showers and bathtubs?",           # a dataset combined count, not two questions
    "How many sinks and washbasins are drawn?",
    "how many doors and doors?",
    "How many doors and cats?",                 # not a countable object
    "How many sinks and wash basins (kitchen and bathroom combined; a double-bowl sink counts as one) are drawn on "
    "this floor plan?",
    "What is the area of the kitchen and the bathroom?",
])
def test_split_multi_none(q):
    assert N.split_multi(q) is None
