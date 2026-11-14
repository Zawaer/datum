"""Number safety: a thousands separator is never read as a decimal point (bp/score.py, bp/numguard.py)."""
import pytest

from bp import numguard
from bp.score import to_number


@pytest.mark.parametrize("s, v", [
    ("4,470 SF", 4470), ("1,050", 1050), ("28,770 SF", 28770), ("1,234.5", 1234.5),
    ("1,5 m", 1.5), ("12,5", 12.5), ("2 345,5", 2345.5), ("300", 300), (189, 189),
])
def test_to_number(s, v):
    assert to_number(s) == pytest.approx(v)


def _ev(*labels):
    return [{"kind": "text", "label": lab} for lab in labels]


def test_sum_read_as_decimal_is_corrected():
    # j04: the model wrote 4.470 for 4,470; its evidence prints the four rows
    res = {"answer": 4.47, "confidence": 0.55, "evidence": _ev(
        "West Wing Circulation 914 SF", "East Wing Circulation 913 SF",
        "North Wing Circulation 1,403 SF", "Common Space Circulation 1,240 SF")}
    numguard.check(res)
    assert res["answer"] == 4470 and res["number_guard"]["action"] == "corrected"


def test_dot_grouped_labels_are_thousands():
    res = {"answer": 4.47, "evidence": _ev("WEST WING = 914 SF", "EAST WING = 913 SF", "NORTH = 1.403 SF",
                                           "COMMON = 1.240 SF")}
    assert numguard.check(res)["answer"] == 4470


def test_single_printed_token():
    res = {"answer": "1.05", "evidence": _ev("TECHNICAL ROOMS 1,050 SF")}
    assert numguard.check(res)["answer"] == 1050


def test_near_factor_1000_is_rejected():
    res = {"answer": 4.46, "confidence": 0.8, "evidence": _ev("TOTAL 4,470 SF")}
    numguard.check(res)
    assert res["answer"] is None and res["tentative_answer"] == 4.46


@pytest.mark.parametrize("res", [
    {"answer": 2.5, "evidence": _ev("SLAB WIDTH 2.500 m")},          # the answer is printed as such
    {"answer": 6.2, "evidence": _ev("6200", "4272")},                 # metric dimension in mm -> m: legitimate
    {"answer": 26.49, "evidence": _ev("6200 x 4272")},
    {"answer": 4470, "evidence": _ev("1,403 SF")},                     # already a whole number
    {"answer": 48, "evidence": _ev("SECOND FLOOR 48 DORMS", "TOTAL 144")},
    {"answer": None, "evidence": _ev("1,050 SF")},
])
def test_leaves_good_answers(res):
    before = res["answer"]
    assert numguard.check(res)["answer"] == before and "number_guard" not in res
