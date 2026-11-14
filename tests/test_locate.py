"""Text evidence sits on the text it cites: whole table rows, the sheet's own unit, misplaced boxes moved or dropped
(A-801 of the Sports Complex set: the finish schedule prints areas in SF; row 105 is split in two segments)."""
import json

import pytest

from bp.generic import locate, text as T
from bp.solvers.generic import GenericSolver

from conftest import FULL_DATA

A801 = "data/opening_design/Sports_Complex/Sheets - Current Set/A-801 - Door and Finish Schedules & Wall Types.pdf"


def test_unit_after():
    assert T.unit_after(570, "570 SF | 105 | MEN'S LOCKER") == "SF"
    assert T.unit_after(105, "570 SF | 105 | MEN'S LOCKER") is None
    assert T.unit_after(12.5, "BEDROOM 12.5 m2") == "m²"
    assert T.numbers_with_unit("570 SF | 105 | MEN'S LOCKER", "SF") == [570.0]


def test_needles():
    e = {"kind": "box", "value": 570, "label": "Men 2: '570 SF | 105 | MEN'S LOCKER'"}
    vals, toks = locate.needles(e)
    assert vals == ["570"] and "locker" in toks


@pytest.mark.data
def test_a801_locker_rows():
    g = GenericSolver()
    reply = {"mode": "text", "op": "sum", "answer": 1281, "confidence": "high", "explanation": "",
             "items": [{"ids": [330, 361], "value": 611, "what": "women"}, {"ids": [365], "value": 670, "what": "men"}]}
    g._ask_text = lambda p, t: (json.dumps(reply), 0.0, 0.0)
    r = g({"path": A801, "question": "On sheet A-801, what is the combined area of the locker rooms in m²?",
           "type": "area", "ext": "pdf", "page": 0})
    assert r["answer"] == 1181 and r["unit"] == "SF" and r["read_from"] == "table"
    assert abs(r["answer_m2"] - 1181 * 0.09290304) < 0.01
    a, b = r["evidence"]
    assert b["value"] == 570 and b["misread"] == 670  # the vector text wins over the model's reading
    assert a["bbox"][3] - a["bbox"][1] < 0.01  # one row, not the rows the model cited around it
    assert b["bbox"][2] > 0.32  # row 105 spans the whole table, not just "570 SF | 105 | MEN'S LOCKER"


@pytest.mark.data
def test_check_moves_or_drops():
    p = str(FULL_DATA / A801)
    res = {"evidence": [
        {"kind": "box", "page": 0, "bbox": [0.5, 0.5, 0.6, 0.51], "value": 570, "label": "M 2: '570 SF | 105 | MEN'S LOCKER'"},
        {"kind": "box", "page": 0, "bbox": [0.5, 0.5, 0.6, 0.51], "value": 99999, "label": "X 3: '99999 SF | NOWHERE'"}]}
    locate.check(res, lambda f: p)
    moved, gone = res["evidence"]
    assert moved["relocated"] and 0.44 < moved["bbox"][1] < 0.445
    assert gone["unlocated"] and "bbox" not in gone
    assert res["located"] == {"checked": 2, "moved": 1, "unlocated": 1}
