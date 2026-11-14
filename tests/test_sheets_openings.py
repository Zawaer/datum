"""bp/sheets/openings.py: door / window counting by classical CV on a hand-checked crop of the DfE school plan.

Fixture: tests/fixtures/openings/school_nw_half.png = special_school_plan_level_00.png crop (1000,1500)-(3200,3500)
at half resolution (~59 px per metre). Hand count on that crop: 21 doors (4 of them double doors, 3 drawn as a
folding / ajar leaf without a swing) and 4 complete exterior windows on the west wall.
"""
import math
from pathlib import Path

import numpy as np
import pytest

from bp.sheets import openings as O

FIX = Path(__file__).parent / "fixtures/openings/school_nw_half.png"
PPM = 117.85 / 2


@pytest.fixture(scope="module")
def res():
    return O.detect_openings(FIX, PPM)


def test_circle3_and_span():
    c = O._circle3(np.array([[10.0, 0.0], [0.0, 10.0], [-10.0, 0.0]]))
    assert c is not None and abs(c[0]) < 1e-6 and abs(c[1]) < 1e-6 and abs(c[2] - 10) < 1e-6
    ang = np.linspace(0, math.pi / 2, 50)
    span, a0, a1 = O._arc_span(ang)
    assert 85 <= span <= 100


def test_doors_on_school_crop(res):
    doors = res["doors"]
    assert len(doors) == 21
    assert sum(d["leaves"] == 2 for d in doors) == 4
    assert not res["low_res"]
    W, H = res["size"]
    for d in doors:
        x0, y0, x1, y1 = d["bbox"]
        assert 0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H


def test_windows_on_school_crop(res):
    ws = res["windows"]
    assert len(ws) == 4
    assert all(w["axis"] == "v" and w["bbox"][2] < 120 for w in ws)  # all on the west facade


def test_find_api_returns_pixel_boxes():
    assert len(O.find_doors(FIX, PPM)) == 21
    assert len(O.find_windows(FIX, PPM)) == 4


def test_intent():
    assert O.intent("Counts of doors and windows") == "doors_windows"
    assert O.intent("How many doors are there?") == "doors"
    assert O.intent("How many windows on this floor") == "windows"
    assert O.intent("What is the area of the hall?") is None


def test_answer_evidence():
    meta = {"image": str(FIX), "path": str(FIX), "w": 1100, "h": 1000, "page": 0}
    meta["openings"] = {"doors": [{"bbox": [0.1, 0.1, 0.2, 0.2], "leaves": 2, "kind": "swing"}],
                        "windows": [{"bbox": [0.0, 0.3, 0.02, 0.4]}], "internal_glazing": [{"bbox": [0.5, 0.5, 0.52, 0.6]}], "low_res": False}
    r = O.answer(str(FIX), "Counts of doors and windows", meta)
    assert r["answer"] == "1 doors and 1 exterior windows (+1 internal glazed panels)"
    assert [e["label"] for e in r["evidence"]] == ["door 1 (double)", "window 1",
                                                  "internal glazed panel 1 (not in the window count)"]
    assert all(0 <= v <= 1 for e in r["evidence"] for v in e["bbox"])
    assert O.answer(str(FIX), "What is the hall area?", meta) is None
    meta["openings"]["low_res"] = True
    assert O.answer(str(FIX), "How many doors?", meta) is None


def test_low_res_answer_uses_detector_and_flags_disagreement():
    y = {"doors": [{"bbox": [0.1, 0.1, 0.12, 0.12]}] * 10, "windows": [{"bbox": [0, 0, 0.01, 0.01]}] * 4}
    hk_ok = {"doors": [{}] * 9, "windows": [{}] * 4, "tiles": 9, "cost_usd": 0.01}
    hk_bad = {"doors": [{}] * 3, "windows": [{}] * 4, "tiles": 9, "cost_usd": 0.01}
    a = O._answer_yolo("doors", y, hk_ok)
    b = O._answer_yolo("doors", y, hk_bad)
    assert a["answer"] == 10 and b["answer"] == 10
    assert a["confidence"] > b["confidence"] and "DISAGREES" in b["explanation"]
    assert a["low_res"] and len(a["evidence"]) == 10


def test_schedule_marks_parse(monkeypatch):
    class Pg:
        def __init__(self, t):
            self.t = t

        def get_text(self):
            return self.t

    txt = "\n".join(["ROOM FINISH SCHEDULE", "101", "CONTROL ROOM", "CUT AND COVER DOOR SCHEDULE", "DOOR NO.",
                     "101A", "F", "915", "2100", "101A", "F", "915", "2100", "102", "F", "915", "2100",
                     "PUMPHOUSE DOOR SCHEDULE", "106", "3' - 0\"", "7' - 0\""])
    import types
    fake = types.SimpleNamespace(open=lambda p: [Pg("PLAN"), Pg(txt)])
    monkeypatch.setitem(__import__("sys").modules, "pymupdf", fake)
    sch = O.schedule_doors("x.pdf")
    assert sch["page"] == 1
    assert sch["schedules"] == [{"101A": 2, "102": 1}, {"106": 1}]
