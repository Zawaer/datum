"""bp/score.py: the official tolerance rules every published number is scored with."""
import pytest

from bp.score import REL_TOL, is_correct, norm_text, text_f1, to_number


# ---------------------------------------------------------------- number parsing
@pytest.mark.parametrize("raw, want", [
    (5, 5.0),
    (15.47, 15.47),
    ("15.47", 15.47),
    ("15.47 m²", 15.47),
    ("15.47 m2", 15.47),
    ("12,5", 12.5),            # decimal comma
    ("1 234,5 m²", 1234.5),    # space-grouped thousands, decimal comma
    ("1 234 567", 1234567.0),
    ("-3", -3.0),
    ("approx. 42 doors", 42.0),
    ("3 m² and 4 m²", 3.0),    # first number wins
])
def test_to_number_parses(raw, want):
    assert to_number(raw) == pytest.approx(want)


@pytest.mark.parametrize("raw", [None, True, False, "", "none", "no windows", "m²"])
def test_to_number_none(raw):
    assert to_number(raw) is None


@pytest.mark.parametrize("raw, want", [("2\u00a0345,5 m²", 2345.5), ("1\u202f234", 1234.0), ("2 345,5", 2345.5)])
def test_to_number_non_ascii_space_grouping(raw, want):
    assert to_number(raw) == pytest.approx(want)


def test_to_number_comma_thousands():
    assert to_number("1,234.5 m²") == pytest.approx(1234.5)


# ---------------------------------------------------------------- counts: exact
@pytest.mark.parametrize("pred, gold, ok", [
    (6, 6, True),
    ("6", 6, True),
    (6.0, "6", True),
    ("6 doors", 6, True),
    (7, 6, False),
    (6.4, 6, False),            # a fractional count is not a count
    (5.99, 6, False),
    (5.9999999, 6, True),       # float noise within 1e-6 is still the count
    ("six", 6, False),          # unparsable -> wrong, not abstain
    (True, 1, False),           # booleans are not numbers
])
def test_count_exact(pred, gold, ok):
    assert is_correct("count", pred, gold) is ok


def test_abstain_is_none():
    for t in ("count", "area", "length", "volume", "text"):
        assert is_correct(t, None, 1) is None


# ---------------------------------------------------------------- measures: within 2 %
def test_rel_tol_is_two_percent():
    assert REL_TOL == 0.02


@pytest.mark.parametrize("qtype", ["area", "length", "volume"])
@pytest.mark.parametrize("pred, gold, ok", [
    (100.0, 100.0, True),
    (102.0, 100.0, True),       # exactly 2 % is inside
    (98.0, 100.0, True),
    (102.1, 100.0, False),
    (97.9, 100.0, False),
    (16.305, 16.31, True),
    ("16,31 m²", 16.31, True),
    ("n/a", 16.31, False),
    (0.0, 0.0, True),
    (0.001, 0.0, False),
    (-100.0, 100.0, False),
])
def test_measure_tolerance(qtype, pred, gold, ok):
    assert is_correct(qtype, pred, gold) is ok


# ---------------------------------------------------------------- text
def test_norm_text():
    assert norm_text("  Küche  (6)! ") == "küche 6"
    assert norm_text("ＡＢＣ") == "abc"  # NFKC folds full-width letters


def test_text_f1():
    assert text_f1("a b c", "a b c") == 1.0
    assert text_f1("x", "y") == 0.0
    assert text_f1("", "") == 1.0
    assert text_f1("a b", "a c") == pytest.approx(0.5)


@pytest.mark.parametrize("pred, gold, ok", [
    ("Erdgeschoss", "erdgeschoss", True),
    ("Living room, kitchen", ["living room", "kitchen"], True),   # list gold is joined
    ("The architect is John Smith", "John Smith", True),          # F1 = 0.57 >= 0.5
    ("Concrete", "Timber", False),
])
def test_text(pred, gold, ok):
    assert is_correct("text", pred, gold) is ok
