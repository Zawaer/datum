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


def test_room_phrase():
    assert R.room_phrase("What is the floor area of the Multi-Purpose Hall?") == "Multi-Purpose Hall"
    assert R.room_phrase("How many linear meters of baseboard are needed in the Library?") == "Library"
    assert R.room_phrase("How many linear meters of baseboard does the Multi-Purpose Hall need?") == "Multi-Purpose Hall"


def test_identify_room_takes_only_confident_hall_pick(monkeypatch, tmp_path):
    """A VLM pick of an unreadable room is taken only at high confidence, and a hall must be the largest compact room."""
    from PIL import Image

    import bp.generic.llm as llm

    p = tmp_path / "plan.png"
    Image.new("RGB", (300, 200), "white").save(p)
    lab = np.zeros((200, 300), np.int32)
    lab[10:110, 10:110], lab[10:60, 150:290], lab[120:190, 10:30], lab[130:190, 150:200] = 1, 2, 3, 4
    rooms = [{"id": 1, "bbox": [10, 10, 110, 110], "area_m2": 100.0, "label": ""},
             {"id": 2, "bbox": [150, 10, 290, 60], "area_m2": 70.0, "label": ""},
             {"id": 3, "bbox": [10, 120, 30, 190], "area_m2": 14.0, "label": ""},
             {"id": 4, "bbox": [150, 130, 200, 190], "area_m2": 30.0, "label": ""}]
    seg = {"rooms": rooms, "_lab": {"lab": lab, "f": 1.0}, "px_per_m": 10.0}
    replies = iter(['{"room": 1, "confidence": "high", "why": "seats"}', '{"room": 4, "confidence": "medium"}',
                    '{"room": 4, "confidence": "high", "why": "x"}'])
    monkeypatch.setattr(llm, "ask", lambda *a, **k: {"text": next(replies), "cost_usd": 0.01})
    assert R.identify_room(seg, str(p), "Multi-Purpose Hall")[0] is rooms[0]
    assert R.identify_room(seg, str(p), "Kitchen")[0] is None  # medium: not taken
    assert R.identify_room(seg, str(p), "Sports Hall")[0] is None  # room 4 is not the largest compact room


def test_pen_marks_removed_walls_kept():
    """A red / green pen stroke across a wall is removed; the wall under it stays dark; a pink zone fill stays."""
    rgb = np.full((300, 400, 3), 225, np.uint8)
    rgb[100:115, :] = 20  # a wall
    rgb[268:296, 200:395] = (235, 175, 170)  # a pink zone fill (not a pen)
    cv2.line(rgb, (50, 20), (350, 250), (205, 40, 40), 2)  # red pen
    cv2.line(rgb, (50, 250), (350, 30), (60, 140, 70), 2)  # green pen
    m = R.mark_mask(rgb)
    assert m is not None and m[20:30, 50:65].any()
    assert not m[275:290, 210:380].any()  # the fill is untouched
    g = R.gray_unmarked(__import__("PIL.Image", fromlist=["Image"]).fromarray(rgb))
    assert g[103:111].max() < 110  # the wall under the strokes is still ink (its core: the rims blur)
    assert g[150:190, 150:250].min() > 150  # no stroke left between the wall and the fill


def test_room_words_plural_and_trades():
    assert R.query_words("How many m2 of tiling for all WCs?") == ["toilet"]
    assert R.intent("How many secondary classrooms are on this level?") == "count"
    assert R.intent("How many doors open into the hall?") is None
    assert R.intent("How many m2 of tiling for all WCs?") == "area"


def test_warm_segments_and_reads_names_once(monkeypatch):
    """The upload warm-up segments the rooms and, on a coarse sheet, reads the names once; a big work image is left."""
    calls = []
    seg = {"rooms": [{"area_m2": 10.0, "label": ""}] * 4, "px_per_m": 20.0, "wall_px": 2.0, "scan": True,
           "fill_gray": 255.0, "paper_gray": 250.0}
    monkeypatch.setattr(R, "scale_info", lambda *a, **k: {"px_per_m": 20.0})
    monkeypatch.setattr(R, "segment", lambda *a, **k: dict(seg))
    monkeypatch.setattr(R, "crop_labels", lambda s, img, rooms: calls.append(1) or 0.01)
    meta = {"image": "x.png", "w": 2000, "h": 1400}
    R.warm(meta)
    assert meta["_rooms_seg"]["_crop_read"] and calls == [1]
    R.warm(meta)  # already done: nothing again
    R.ensure_crop_labels(meta, meta["_rooms_seg"])
    assert calls == [1]
    big = {"image": "y.png", "w": 20000, "h": 14000}
    R.warm(big)
    assert "_rooms_seg" not in big
