"""bp/sheets/rooms.py on a synthetic plan drawn at a known scale (fast: no OCR, no model calls)."""
import cv2
import numpy as np
import pytest

from bp.sheets import rooms as R

PPM = 60.0  # px per metre of the synthetic sheet


def _plan():
    """Two rooms side by side, 4 x 3 m and 3 x 3 m (inside faces), 0.2 m walls, a 0.9 m door with leaf and swing
    between them, a 1.5 m window (two glazing lines) in the outer wall, a scale bar 0-10 m, and grey furniture."""
    m = lambda v: int(round(v * PPM))  # noqa: E731
    W, H = m(12), m(9)
    g = np.full((H, W), 255, np.uint8)
    ox, oy, t = m(1), m(1), m(0.2)

    def wall(x0, y0, x1, y1):
        g[oy + y0:oy + y1, ox + x0:ox + x1] = 0

    iw, ih = m(4) + m(3) + t, m(3)  # inside extents (two rooms + partition)
    wall(0, 0, iw + 2 * t, t)  # top
    wall(0, ih + t, iw + 2 * t, ih + 2 * t)  # bottom
    wall(0, 0, t, ih + 2 * t)  # left
    wall(iw + t, 0, iw + 2 * t, ih + 2 * t)  # right
    px = t + m(4)  # partition x
    d0, d1 = t + m(1.0), t + m(1.9)  # door in the partition, 0.9 m
    wall(px, 0, px + t, d0)
    wall(px, d1, px + t, ih + 2 * t)
    # door leaf (thin, square to the partition, into room 2) and its swing
    cv2.line(g, (ox + px + t, oy + d0), (ox + px + t + m(0.9), oy + d0), 0, 2)
    cv2.ellipse(g, (ox + px + t, oy + d0), (m(0.9), m(0.9)), 0, 0, 90, 0, 2)
    # window in the top wall of room 1: clear the wall, draw two glazing lines
    wx0, wx1 = ox + t + m(1.2), ox + t + m(2.7)
    g[oy:oy + t, wx0:wx1] = 255
    for yy in (oy + 2, oy + t - 3):
        cv2.line(g, (wx0, yy), (wx1, yy), 0, 2)
    # grey furniture in room 1
    cv2.rectangle(g, (ox + m(1), oy + m(1.5)), (ox + m(2.5), oy + m(2.5)), 170, 2)
    # scale bar 0..10 m below the plan
    by = m(7.5)
    cv2.line(g, (m(1), by), (m(11), by), 0, 2)
    cv2.line(g, (m(1), by - 10), (m(1), by), 0, 2)
    cv2.line(g, (m(11), by - 10), (m(11), by), 0, 2)
    words = [{"text": "0", "conf": 95, "bbox": [(m(1) - 6) / W, (by + 8) / H, (m(1) + 6) / W, (by + 30) / H]},
             {"text": "5m", "conf": 95, "bbox": [(m(6) - 12) / W, (by + 8) / H, (m(6) + 12) / W, (by + 30) / H]},
             {"text": "10m", "conf": 95, "bbox": [(m(11) - 18) / W, (by + 8) / H, (m(11) + 18) / W, (by + 30) / H]},
             {"text": "Office", "conf": 95, "bbox": [(ox + m(2)) / W, (oy + m(0.6)) / H, (ox + m(2.8)) / W, (oy + m(0.9)) / H]},
             {"text": "WC", "conf": 95, "bbox": [(ox + m(6)) / W, (oy + m(2.2)) / H, (ox + m(6.4)) / W, (oy + m(2.5)) / H]}]
    return g, words


@pytest.fixture(scope="module")
def plan():
    return _plan()


def test_scale_from_bar(plan):
    g, words = plan
    assert R.scale_from_bar(g, words=words) == pytest.approx(PPM, rel=0.02)


def test_scale_without_zero_label(plan):
    g, words = plan
    ws = [w for w in words if w["text"] != "0"]
    assert R.scale_from_bar(g, words=ws) == pytest.approx(PPM, rel=0.03)


def test_segment_rooms_areas_and_baseboards(plan):
    g, words = plan
    rooms = R.segment_rooms(g, words=words)
    big = sorted((r for r in rooms if r["area_m2"] > 2), key=lambda r: -r["area_m2"])
    assert len(big) == 2
    office, wc = big
    assert office["label"] == "Office" and wc["label"] == "WC"
    assert office["area_m2"] == pytest.approx(12.0, rel=0.04)
    assert wc["area_m2"] == pytest.approx(9.0, rel=0.06)  # minus the swing pocket corner, plus the doorway
    assert office["perimeter_m"] == pytest.approx(14.0, rel=0.04)
    # one door (0.9 m) on each room; the window is not deducted
    assert [round(d["width_m"], 1) for d in office["doors"]] == [pytest.approx(0.9, abs=0.1)]
    assert office["baseboard_m"] == pytest.approx(13.1, rel=0.05)
    assert len(office["polygon"]) >= 4


def test_answer_contract(plan, tmp_path):
    g, words = plan
    p = tmp_path / "plan.png"
    cv2.imwrite(str(p), g)
    meta = {"image": str(p), "w": g.shape[1], "h": g.shape[0], "kind": "arch", "words": words}
    r = R.answer(str(p), "What is the area of the office?", meta)
    assert r["answer"] == pytest.approx(12.0, rel=0.04) and r["method"] == "sheets-rooms-area"
    assert r["evidence"][0]["kind"] == "polygon" and all(0 <= v <= 1 for pt in r["evidence"][0]["points"] for v in pt)
    b = R.answer(str(p), "Linear meters for baseboards", meta)
    assert b["unit"] == "m" and b["answer"] > 20
    # baseboard evidence: closed outline polylines (full length) and door openings (negative) add up to the answer
    assert {e["kind"] for e in b["evidence"]} >= {"polyline", "box"}
    parts = sum(e["value"] for e in b["evidence"] if e["kind"] in ("polyline", "box") and e["value"] is not None)
    assert parts == pytest.approx(b["answer"], abs=0.1)
    b2 = R.answer(str(p), "Baseboard length excluding wet rooms", meta)
    assert b2["answer"] < b["answer"]
    one = R.answer(str(p), "Baseboard length in the office?", meta)
    assert one["answer"] == pytest.approx(13.1, rel=0.05)
    # a room the sheet does not have: ask, never total everything
    ask = R.answer(str(p), "Baseboard length in the Hall?", meta)
    assert ask["answer"] is None and ask["method"] == "sheets-rooms-ask" and "Office" in ask["explanation"]
    assert R.answer(str(p), "How many doors are there?", meta) is None
    assert "low_res" not in b


def test_intent_and_match():
    assert R.intent("Linear meters for baseboards") == "baseboard"
    assert R.intent("Floor areas of different areas") == "area"
    rs = [{"label": "Secondary Classroom"}, {"label": "Group Room"}, {"label": "Secondary Classroom (Severe Needs)"}]
    sel, _ = R.match_rooms(rs, "total classroom area")
    assert len(sel) == 2
    halls = [{"label": "Multi-Purpose Hall"}, {"label": "Sports Hal"}, {"label": "Kitchen"}, {"label": "214"},
             {"label": "Dorm 216"}]
    assert [r["label"] for r in R.match_rooms(halls, "Baseboard length in the Hall?")[0]] == \
        ["Multi-Purpose Hall", "Sports Hal"]
    assert [r["label"] for r in R.match_rooms(halls, "area of room 214")[0]] == ["214"]
    assert R.match_rooms(halls, "area of the gym")[0][0]["label"] == "Multi-Purpose Hall"
    assert R._clean("|| 214 ee") == "214"


def test_coarse_sheet_only_totals(plan, tmp_path):
    """At ~20 px/m single rooms are not trusted: named rooms abstain, totals come with a low-res hint."""
    g, words = plan
    small = cv2.resize(g, (g.shape[1] // 3, g.shape[0] // 3), interpolation=cv2.INTER_AREA)
    p = tmp_path / "small.png"
    cv2.imwrite(str(p), small)
    meta = {"image": str(p), "w": small.shape[1], "h": small.shape[0], "kind": "arch", "words": words}
    assert R.answer(str(p), "What is the area of the office?", meta) is None
    assert R.answer(str(p), "Baseboard length excluding wet rooms", meta) is None
    b = R.answer(str(p), "Linear meters for baseboards", meta)
    assert b is not None and b["low_res"] and b["confidence"] < 0.5


def test_side_panel_beside_doorway():
    """A doorway gap whose first 0.5 m is glazed (two lines along the wall) and then 1 m open: a side panel."""
    from bp.sheets import rooms as R

    ppm = 50
    t = np.zeros((8, 75), bool)  # rows across a 0.16 m wall, 1.5 m along it
    t[2, :25] = t[5, :25] = True  # glazing lines over the first 0.5 m
    assert R._side_panel(t, ppm) == (0, 25)
    assert R._side_panel(t[:, ::-1], ppm) == (1, 25)
    t2 = np.zeros((8, 75), bool)  # a plain doorway: nothing
    assert R._side_panel(t2, ppm) is None
    t3 = t.copy()
    t3[2, :] = t3[5, :] = True  # glazed all along: a window, not a side panel
    assert R._side_panel(t3, ppm) is None
