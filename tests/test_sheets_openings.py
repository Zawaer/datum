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
    ws = [w for w in res["windows"] if not w.get("side_panel")]
    assert len(ws) == 4
    assert all(w["axis"] == "v" and w["bbox"][2] < 120 for w in ws)  # all on the west facade
    # the glazed side panels beside the two classroom doors on the corridor (the crop's open corridor end makes them
    # read as outside); a pier at one end, the door opening at the other
    sp = [w for w in res["windows"] + res["internal_glazing"] if w.get("side_panel")]
    assert len(sp) == 4 and all(w["axis"] == "v" and 500 < w["bbox"][0] < 820 for w in sp)


def test_find_api_returns_pixel_boxes():
    assert len(O.find_doors(FIX, PPM)) == 21
    assert len(O.find_windows(FIX, PPM)) == 8  # 4 facade windows + 4 side panels


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
    # every glazed panel is a window (Stoa example gold); the split outside walls / internal is given
    assert r["answer"] == "1 doors and 2 windows (1 in outside walls + 1 internal glazed panels)"
    assert [e["label"] for e in r["evidence"]] == ["door 1 (double)", "window 1", "internal glazed panel 1"]
    assert r["counts"]["windows"] == 2 and r["counts"]["exterior_windows"] == 1
    assert all(0 <= v <= 1 for e in r["evidence"] for v in e["bbox"])
    assert O.answer(str(FIX), "What is the hall area?", meta) is None
    meta["openings"]["low_res"] = True
    assert O.answer(str(FIX), "How many doors?", meta) is None


def test_low_res_answer_uses_detector_vision_only_raises_confidence():
    y = {"doors": [{"bbox": [0.1, 0.1, 0.12, 0.12]}] * 10, "windows": [{"bbox": [0, 0, 0.01, 0.01]}] * 4}
    hk_ok = {"doors": [{}] * 9, "windows": [{}] * 4, "tiles": 9, "cost_usd": 0.01}
    hk_bad = {"doors": [{}] * 3, "windows": [{}] * 4, "tiles": 9, "cost_usd": 0.01}
    a = O._answer_yolo("doors", y, hk_ok)
    b = O._answer_yolo("doors", y, hk_bad)
    assert a["answer"] == 10 and b["answer"] == 10
    assert a["confidence"] == 0.6 and b["confidence"] == 0.5
    assert "agrees" in a["explanation"] and "vision" not in b["explanation"]
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


def test_vector_doors_from_tessellated_arcs(tmp_path):
    """A PDF page with door swings drawn as short line pieces (as CAD exports do): one single door, one double door,
    one 45-degree swing with its leaf, and a row of locker arcs that must not count."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    pg = doc.new_page(width=1200, height=800)
    sh = pg.new_shape()

    def arc(cx, cy, r, a0, a1, n=8, leaf=True):
        pts = [pymupdf.Point(cx + r * math.cos(math.radians(a0 + (a1 - a0) * k / n)),
                             cy + r * math.sin(math.radians(a0 + (a1 - a0) * k / n))) for k in range(n + 1)]
        for p, q in zip(pts, pts[1:]):
            sh.draw_line(p, q)
        if leaf:
            sh.draw_line(pymupdf.Point(cx, cy), pts[-1])

    for x in range(0, 600, 60):  # a wall so the page has ordinary linework too
        sh.draw_line(pymupdf.Point(x, 200), pymupdf.Point(x + 50, 200))
    arc(100, 200, 20, 0, -90)                       # single door
    arc(200, 200, 20, 0, -90), arc(240, 200, 20, 180, 270)  # double door: hinges r1 + r2 apart
    arc(350, 200, 20, 0, -45, n=2)                  # 45-degree swing, two pieces, with its leaf
    for k in range(6):                              # locker row: identical arcs 12 apart
        arc(420 + 12 * k, 300, 20, 0, 90, leaf=False)
    sh.finish(color=(0, 0, 0), width=0.5)
    sh.commit()
    f = tmp_path / "doors.pdf"
    doc.save(f)
    r = O.vector_doors(f, 0)
    # the locker row's two end arcs survive the crowding filter (as on the DAF sheet); the others go
    doors = [d for d in r["doors"] if d["bbox"][1] * 800 < 250]
    assert len(r["doors"]) - len(doors) <= 2
    assert len(doors) == 3
    assert sorted(d["leaves"] for d in doors) == [1, 1, 2]


def test_too_coarse_guard():
    y = {"doors": [{"bbox": [0.1, 0.1, 0.105, 0.105]}] * 20, "windows": []}  # 10 px boxes on a 2000 px image
    r = O._answer_yolo("doors", y, None, size=(2000, 1400))
    assert r["answer"] == "at least 20 doors (image too coarse to count reliably)"
    assert r["confidence"] == 0.25 and "upload the PDF" in r["low_res"]
    y["doors"] = [{"bbox": [0.1, 0.1, 0.11, 0.11]}] * 20  # 20 px: countable
    r = O._answer_yolo("doors", y, None, size=(2000, 1400))
    assert r["answer"] == 20 and r["low_res"] is True


def test_room_scope():
    assert O.room_scope("How many doors open into the Multi-Purpose Hall?") == "Multi-Purpose Hall"
    assert O.room_scope("How many doors lead into the kitchen?") == "kitchen"
    for q in ("How many doors are in this dormitory module?", "How many doors does the filter building have?",
              "How many doors are shown on this floor plan?", "How many doors are there in total?"):
        assert O.room_scope(q) is None


def test_vision_closet_rule(monkeypatch, tmp_path):
    """The vision read gives the smaller space's printed name and area; a closet name or < 25 SF (not a WC) is a
    closet door."""
    from PIL import Image

    p = tmp_path / "plan.png"
    Image.new("RGB", (400, 300), "white").save(p)
    reply = '{"1": ["CLOSET", "18 SF"], "2": ["BATH", "51 SF"], "3": ["MECH", "9 SF"], "4": ["WC", "1.5 m2"], ' \
            '"5": ["", ""], "6": ["NOT A DOOR", ""]}'
    import bp.generic.llm as llm
    monkeypatch.setattr(llm, "ask", lambda *a, **k: {"text": reply, "cost_usd": 0.001})
    doors = [{"bbox": [0.1 * i, 0.1, 0.1 * i + 0.05, 0.2]} for i in range(1, 7)]
    out, cost = O.vision_closets({"image": str(p)}, doors)
    assert sorted(out) == [0, 2, 5] and cost == 0.001 and out[5].startswith("not a door")
    assert O._printed_m2("18 SF") == pytest.approx(1.672, abs=0.01) and O._printed_m2("4.5 m2") == 4.5
