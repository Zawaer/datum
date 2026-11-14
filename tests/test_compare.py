"""bp/compare.py: comparative / superlative question shapes (skipped if the module is not in this checkout)."""
import pytest

C = pytest.importorskip("bp.compare")


@pytest.mark.parametrize("q, op, d, measure", [
    ("Which room is the largest?", "max", 1, "area"),
    ("Which room is the smallest?", "min", -1, "area"),
    ("Welches Zimmer ist das grösste?", "max", 1, "area"),
    ("Quelle est la pièce la plus grande ?", "max", 1, "area"),
    ("Mikä huone on suurin?", "max", 1, "area"),
    ("Which apartment has the most rooms labelled 'Bad'?", "max", 1, "count"),
    ("Which storey has the fewest doors?", "min", -1, "count"),
    ("Is apartment B larger than apartment A?", "cmp", 1, "area"),
    ("Is room 5.06 ('Wohnen') smaller than room 5.09 ('Küche')?", "cmp", -1, "area"),
    ("Does 'E01' have more doors than 'E02'?", "cmp", 1, "count"),
    ("How much larger is room 5.06 ('Wohnen') than room 5.09 ('Küche'), in m²?", "diff", 1, "area"),
    ("What is the difference between the kitchen and the bathroom?", "diff", 0, "area"),
    ("Kumpi on isompi, olohuone vai keittiö?", "which2", 1, "area"),
    ("Which is bigger, the kitchen or the bathroom?", "which2", 1, "area"),
])
def test_parse_shape(q, op, d, measure):
    r = C.parse(q)
    assert r is not None, q
    assert (r["op"], r["dir"], r["measure"]) == (op, d, measure)


def test_parse_operands():
    r = C.parse("Is apartment B larger than apartment A?")
    assert "apartment b" in r["left"] and r["right"] == "apartment a"
    r = C.parse("Kumpi on isompi, olohuone vai keittiö?")
    assert (r["left"], r["right"]) == ("olohuone", "keittiö")
    r = C.parse("Does 'E01' have more doors than 'E02'?")
    assert r["counted"] == "doors" and r["right"] == "'e02'"
    r = C.parse("Which apartment has the most rooms labelled 'Bad'?")
    assert r["counted"] == "rooms labelled 'bad'"


@pytest.mark.parametrize("q", [
    # dataset templates must never parse as comparisons (their answers would change)
    "How many windows are drawn on this floor plan?",
    "What is the net floor area of room 7.01 ('Balkon') in m²?",
    "What is the total net floor area in m² of all numbered indoor rooms on this floor (excluding balconies, loggias, "
    "terraces and other outdoor spaces, shafts and voids)?",
    "How many rooms labelled 'Bad' are there on this floor?",
    "What is the net floor area of the room 'Küche (6)' on 'Erdgeschoss', in m²?",
    "How many doors are shown on the floor plan of 'E01'?",
    "Wie viele Fenster sind auf diesem Grundriss eingezeichnet?",
])
def test_dataset_templates_do_not_parse(q):
    assert C.parse(q) is None


def test_fmt_and_verdict():
    assert C.fmt(18.956, "m²") == "18.96 m²"
    assert C.fmt(1, "windows") == "1 window"
    assert C.fmt(3, "bedrooms") == "3 bedrooms"
    text, d = C.verdict_text("apartment B", 81.55, "apartment A", 62.59, "m²")
    assert d == pytest.approx(18.96) and text.endswith("apartment B is larger by 18.96 m²")
    text, d = C.verdict_text("E01", 3, "E02", 5, "doors")
    assert d == -2 and text.endswith("E02 has 2 doors more")
    assert C.verdict_text("a", 3, "b", 3, "doors")[0].endswith("they are equal")


def test_typed():
    assert C.typed(8.9, "m²", "area") == 8.9
    assert C.typed(8.9, "m²", "text") == "8.90 m²"
    assert C.typed(2, "doors", "count") == 2
    assert C.typed(2, "doors", "text") == "2 doors"


def test_kind_of():
    assert C.kind_of("the kitchen")[0] == "kitchen"
    assert C.kind_of("olohuone")[0] == "living"
    assert C.kind_of("makuuhuone")[0] == "bedroom"
