"""bp/sheets/zones.py on a synthetic sheet: a schedule table, a colour legend, colour-filled zones and a dimension
string (words handed in like a PDF text layer, so no OCR and no model calls)."""
import os

import numpy as np
import pytest

os.environ["BP_ZONES_LLM"] = "0"

from bp.sheets import zones as Z  # noqa: E402

W, H = 2400, 1600
PPF = 10.0  # px per foot on the synthetic sheet
COLS = {"COMMON AREA": (254, 187, 177), "CIRCULATION": (230, 230, 230), "DORMITORY": (211, 224, 209)}


def _line(words, x, y, toks, h=28, gap=14):
    """Lay out tokens left to right; a ('>', x) token jumps to column x."""
    for t in toks:
        if isinstance(t, tuple):
            x = t[1]
            continue
        w = 15 * len(t)
        words.append({"text": t, "conf": 100.0, "bbox": [x / W, y / H, (x + w) / W, (y + h) / H]})
        x += w + gap


def _schedule_words():
    ws = []
    _line(ws, 1500, 960, ["SQUARE", "FOOTAGE"])
    rows = [["WEST", "WING", "DORMITORY", "="], ["WEST", "WING", "CIRCULATION", "="], ["TOTAL", "WEST", "WING", "="],
            ["EAST", "WING", "DORMITORY", "="], ["TOTAL", "SECOND", "FLOOR", "="]]
    vals = ["4,800", "1,200", "6,000", "2,500", "8,500"]
    for i, (lab, v) in enumerate(zip(rows, vals)):
        _line(ws, 1500, 1010 + 40 * i, lab + [(">", 2150 - 15 * len(v)), v, "SF"])
    _line(ws, 1500, 1240, ["ROOM", "COUNT"])
    for i, (lab, v) in enumerate([("FIRST", "24"), ("SECOND", "24")]):
        _line(ws, 1500, 1290 + 40 * i, [lab, "FLOOR", "=", (">", 2100), v, "DORMS"])
    _line(ws, 1500, 1370, ["TOTAL", "=", (">", 2100), "48", "DORMS"])
    return ws


def _sheet(tmp_path):
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    # plan: dormitory 80x60 ft, circulation 20x60 ft, common 100x50 ft (top-left at 200,200; 10 px/ft)
    d.rectangle([200, 200, 999, 799], fill=COLS["DORMITORY"])
    d.rectangle([1000, 200, 1199, 799], fill=COLS["CIRCULATION"])
    d.rectangle([1200, 200, 2199, 699], fill=COLS["COMMON AREA"])
    for x in range(260, 1000, 120):  # furniture outlines on the dormitory fill
        d.rectangle([x, 260, x + 40, 300], outline="black", width=2)
    # a dimension string: 200'-0" between ticks at x=200 and x=2200
    d.line([200, 1450, 2200, 1450], fill="black", width=2)
    for x in (200, 2200):
        d.line([x, 1420, x, 1480], fill="black", width=2)
    # legend swatches
    for i, name in enumerate(COLS):
        d.rectangle([300, 1000 + 60 * i, 380, 1030 + 60 * i], fill=COLS[name])
    p = tmp_path / "sheet.png"
    im.save(p)
    ws = _schedule_words()
    for i, name in enumerate(COLS):
        _line(ws, 400, 1001 + 60 * i, name.split())
    _line(ws, 1140, 1405, ["200'-0\""])
    return {"image": str(p), "w": W, "h": H, "words": ws, "page": 0}


@pytest.fixture()
def meta(tmp_path):
    return _sheet(tmp_path)


def test_numbers_and_dimensions():
    assert Z._num("6,095") == 6095
    assert Z._num("26.562") == 26562
    assert Z._num("12.5") == 12.5
    assert Z._num("SF") is None
    assert Z._dim_ft("323'-4\"") == pytest.approx(323 + 4 / 12)
    assert Z._dim_ft("323-4\"") == pytest.approx(323 + 4 / 12)
    assert Z._dim_ft("40'") == 40


def test_rows_tables_and_totals(meta):
    rs = Z.rows(meta)
    got = {(r["label"], r["value"], r["unit"]) for r in rs}
    assert ("WEST WING DORMITORY", 4800, "SF") in got
    assert ("TOTAL SECOND FLOOR", 8500, "SF") in got
    assert ("TOTAL", 48, "dorms") in got
    tables = {r["table"] for r in rs}
    assert "SQUARE FOOTAGE" in tables and "ROOM COUNT" in tables
    assert [r["total"] for r in rs if r["label"].startswith("TOTAL")] == [True] * 3


def test_parse_rows_ignores_underline_junk_and_lone_tags():
    ws = []
    _line(ws, 100, 100, ["UTILITY", "=", (">", 900), "328", "SF"])
    _line(ws, 100, 140, ["TOTAL", "FLOOR", "=", (">", 870), "26,562", "SF"])
    ws.append({"text": "na", "conf": 50, "bbox": [870 / W, 140 / H, 900 / W, 143 / H]})  # underline read as text
    _line(ws, 1500, 600, ["LOUNGE", (">", 1900), "81", "SF"])  # a room tag far from any table, no "="
    rs = Z.parse_rows(ws, W / H)
    assert [(r["label"], r["value"]) for r in rs] == [("UTILITY", 328), ("TOTAL FLOOR", 26562)]


def test_schedule_answers_with_arithmetic_and_cells(meta):
    r = Z.answer(meta["image"], "What is the total dormitory area?", meta)
    assert r["answer"] == 7300 and r["method"] == "sheets-zones-schedule"
    assert "4,800 + 2,500 = 7,300 SF" in r["explanation"]
    cells = [e for e in r["evidence"] if e["kind"] == "cell"]
    assert len(cells) == 2 and cells[0]["table"] == "Square footage" and cells[0]["text"] == "4,800 SF"
    r = Z.answer(meta["image"], "What is the total floor area of the second floor?", meta)
    assert r["answer"] == 8500
    r = Z.answer(meta["image"], "How many dorm rooms are there in total?", meta)
    assert r["answer"] == 48
    r = Z.answer(meta["image"], "How many dorms per floor?", meta)
    assert r["answer"] == 24


def test_unit_conversion(meta):
    r = Z.answer(meta["image"], "What is the west wing circulation area in square metres?", meta)
    assert r["answer"] == pytest.approx(1200 * 0.09290304, abs=0.1)
    assert r["unit"] == "m²" and "m²" in r["explanation"]


def test_scale_from_dimension_string(meta):
    sc = Z.scale(meta)
    assert sc["px_per_ft"] == pytest.approx(PPF, rel=0.01)


def test_legend_and_measured_zones(meta):
    leg = Z.legend(meta)
    assert [x["name"] for x in leg] == list(COLS)
    z = Z.zones(meta)
    a = {c["name"]: c["area_sf"] for c in z["categories"]}
    # fills: dormitory 4,800, circulation 1,200, common 5,000 SF; the footprint is grown by 1 ft of exterior wall
    assert a["DORMITORY"] == pytest.approx(4800, rel=0.08)
    assert a["CIRCULATION"] == pytest.approx(1200, rel=0.12)
    assert a["COMMON AREA"] == pytest.approx(5000, rel=0.08)
    r = Z.answer(meta["image"], "Measure the area of each colour zone", meta)
    assert r["method"] == "sheets-zones-measured"
    polys = [e for e in r["evidence"] if e["kind"] == "polygon"]
    assert {e["category"] for e in polys} == set(COLS) and all(e["unit"] == "m²" and e["value"] > 0 for e in polys)


def test_cross_check_in_explanation(meta):
    r = Z.answer(meta["image"], "What is the west wing dormitory area?", meta)
    assert r["answer"] == 4800
    assert "measured" in r["explanation"] and "on the schedule" in r["explanation"]


def test_detect_and_abstain(meta):
    assert Z.detect(meta) >= 0.8
    assert Z.answer(meta["image"], "How many doors are there?", meta) is None
    assert Z.detect({"text": "", "words": []}) < 0.5


def test_low_res_flag():
    assert Z._low_res({"w": 2000, "h": 1294}) and not Z._low_res({"w": 10200, "h": 6600})
    assert Z._low_res({"w": 2000, "h": 1294, "words": [{"text": "x"}]}) is None


def test_measured_abstains_on_rooms_the_legend_does_not_name(meta):
    # "bedroom" is not a legend colour: the DORMITORY fill is not the bedrooms' area
    assert Z._answer_measured(meta, "What is the total bedroom area in the dormitory module?", None) is None
    assert Z._answer_measured(meta, "What is the dormitory area?", None)["answer"] > 0


def test_overall_length_keeps_feet_and_inches(meta):
    r = Z.answer(meta["image"], "What is the overall length of the building?", meta)
    assert r["answer"] == "200'-0\"" and r["method"] == "sheets-zones-dimension"
    assert r["value_ft"] == pytest.approx(200.0) and r["confidence"] >= 0.85
    assert Z._fmt_ftin(323 + 4 / 12) == "323'-4\""


def test_duplicate_ocr_words_are_merged():
    a = {"text": "SQUA", "conf": 60, "bbox": [0.1, 0.1, 0.13, 0.11]}
    b = {"text": "SQUARE", "conf": 90, "bbox": [0.1, 0.1, 0.15, 0.11]}
    c = {"text": "FOOTAGE", "conf": 90, "bbox": [0.16, 0.1, 0.2, 0.11]}
    assert [w["text"] for w in Z._dedupe_words([a, b, c])] == ["FOOTAGE", "SQUARE"]


def _rows(labels, values, kinds):
    return [{"id": i, "label": l, "value": v, "kind": k, "total": l.startswith(("TOTAL", "SUB")), "table": "T",
             "bbox": [0.1, 0.1 + 0.01 * i, 0.3, 0.108 + 0.01 * i]} for i, (l, v, k) in enumerate(zip(labels, values, kinds))]


def test_guard_prefers_the_named_row_over_totals():
    rs = _rows(["FIRST FLOOR", "SECOND FLOOR", "THIRD FLOOR", "TOTAL", "EAST WING DORMITORY", "TOTAL EAST WING",
                "SUBTOTAL", "EXTERIOR STAIR", "TOTAL FIRST FLOOR"],
               [48, 48, 48, 144, 6092, 7005, 28389, 381, 28770], ["count"] * 4 + ["area"] * 5)

    def picked(q, i):
        g = Z._guard_pick(q, rs, {"groups": [{"name": "x", "ids": [i]}]})["groups"]
        return [rs[j]["label"] for x in g for j in x["ids"]]

    assert picked("How many dorm rooms are on the second floor?", 3) == ["SECOND FLOOR"]
    assert picked("Wie viele Zimmer hat das 2. OG?", 3) == ["SECOND FLOOR"]
    assert picked("How many dorm rooms in total?", 3) == ["TOTAL"]
    assert picked("What's the total first floor area?", 6) == ["TOTAL FIRST FLOOR"]
    assert picked("Total net floor area of the east wing dorm rooms?", 4) == ["EAST WING DORMITORY"]
    assert picked("How many dorms are in the north wing?", 3) == []  # no such row: never the total


def test_total_rows_are_checked_against_their_parts():
    rs = _rows(["COMMON SPACE", "UTILITY", "TOTAL COMMON SPACE", "SUBTOTAL", "EXTERIOR STAIR", "TOTAL FLOOR"],
               [2911, 328, 3239, 26181, 381, 26562], ["area"] * 6)
    assert Z._parts_check(rs, rs[2])[0] == 3239
    assert Z._parts_check(rs, rs[5])[0] == 26562


def test_multilingual_questions_are_ours():
    assert Z.is_mine("Wie groß ist die gesamte Verkehrsfläche (Circulation) im 2. OG?")
    assert Z.is_mine("Montako huonetta toisessa kerroksessa on?")
    assert not Z.is_mine("How many doors are there?")


def test_guard_keeps_a_sum_to_one_category():
    rs = _rows(["WEST WING CIRCULATION", "EAST WING CIRCULATION", "NORTH WING CIRCULATION",
                "COMMON SPACE CIRCULATION", "EXTERIOR STAIR"], [914, 913, 1403, 1240, 381], ["area"] * 5)
    g = Z._guard_pick("total circulation area?", rs, {"groups": [{"name": "c", "ids": [0, 1, 2, 3, 4]}]})["groups"]
    assert g[0]["ids"] == [0, 1, 2, 3]


def test_guard_treats_a_floor_name_without_floor_rows_as_context():
    rs = _rows(["COMMON SPACE", "UTILITY", "TOTAL COMMON SPACE"], [4379, 1368, 6687], ["area"] * 3)
    g = Z._guard_pick("How many square metres of common space are on the first floor?", rs,
                      {"groups": [{"name": "x", "ids": [2]}]})["groups"]
    assert g and g[0]["ids"] == [2]
    rs = _rows(["COMMON SPACE", "UTILITY", "TOTAL COMMON SPACE", "TOTAL FIRST FLOOR", "FIRST FLOOR", "SECOND FLOOR"],
               [4379, 1368, 6687, 28770, 48, 48], ["area"] * 4 + ["count"] * 2)
    g = Z._guard_pick("How many square metres of common space are on the first floor?", rs,
                      {"groups": [{"name": "x", "ids": [2]}]})["groups"]
    assert g and g[0]["ids"] == [2]


def test_vision_answer_with_dotted_thousands_is_an_integer():
    from bp.generic.vision import _thousands

    assert _thousands('{"answer": 4.470, "evidence": []}', 4.47) == 4470
    assert _thousands('{"answer": 1,050}', None) == 1050
    assert _thousands('{"answer": 4.47}', 4.47) == 4.47
    assert _thousands('{"answer": "12 doors"}', "12 doors") == "12 doors"
