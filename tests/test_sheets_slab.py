"""bp/sheets/slab.py on the judges' example S-100F (low-res 2000 px JPG), offline: the Tesseract words and the Haiku
note reads are replayed from tests/fixtures/slab/S-100F_lowres_reads.json (recorded once, $0.007), so the test
exercises the geometry (zones, scale from dimension ticks, control joints) and the answer logic without any OCR
or model call."""
import json
import subprocess
from pathlib import Path

import pytest

from bp import sheets
from bp.sheets import slab

FX = Path(__file__).parent / "fixtures" / "slab"
IMG = str(FX / "S-100F_lowres.jpg")


@pytest.fixture(scope="module")
def meta(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(sheets.shutil, "which", lambda name: "/usr/bin/" + name)

    def no_subprocess(*a, **k):
        raise AssertionError("OCR must come from the fixture")

    def no_llm(*a, **k):
        raise AssertionError("no model calls in this test")

    mp.setattr(subprocess, "run", no_subprocess)
    from bp.generic import llm

    mp.setattr(llm, "ask", no_llm)
    m = {"path": IMG, "image": IMG, "w": 2000, "h": 1413, "page": 0, "kind": "slab",
         "title": "FOUNDATION AND SLAB PLAN S-100F", "text": "", "_slab_cache_dir": str(tmp_path_factory.mktemp("s"))}
    m.update(json.loads((FX / "S-100F_lowres_reads.json").read_text()))
    slab.analyse(m)
    yield m
    mp.undo()


def ask(meta, q):
    r = slab.answer(IMG, q, meta)
    assert r is not None, q
    return r


def test_detect(meta):
    assert slab.detect(meta) >= 0.8
    assert slab.detect({"title": "SECOND FLOOR PLAN", "text": "DORM ROOM CORRIDOR", "kind": "arch"}) < 0.5


def test_scale_and_types(meta):
    A = meta["slab"]
    assert A["k"] == pytest.approx(27000 / 1281, rel=0.01)  # mm per px: the 27,000 overall spans ~1281 px
    got = {(t["thickness_mm"], tuple(t["bars"]), t["elevation"]) for t in A["types"]}
    assert got == {(300, ("D16 @ 300",), "9400"), (150, ("D13 @ 300",), "10000"), (300, ("D22 @ 300",), "10000")}
    assert len(A["zones"]) == 3 and all(z["type"] is not None for z in A["zones"])


@pytest.mark.parametrize("q,gold,tol", [
    ("What is the area of the 150 mm slab-on-grade?", 61.69, 0.03),          # 6,200 x 9,950 clear
    ("What is the area of the 300 mm slab-on-grade with D16 bars?", 214.5, 0.03),  # 19,500 x 11,000 clear
    ("What is the area of the D22 slab?", 26.5, 0.05),                      # genset room, 6,200 x 4,272
    ("What is the total slab area?", 302.7, 0.03),
])
def test_areas(meta, q, gold, tol):
    r = ask(meta, q)
    assert r["answer"] == pytest.approx(gold, rel=tol)
    assert "×" in r["explanation"]
    polys = [e for e in r["evidence"] if e["kind"] == "polygon"]
    assert polys and all(0 <= x <= 1 and 0 <= y <= 1 for e in polys for x, y in e["points"])
    assert sum(e["value"] for e in polys) == pytest.approx(r["answer"], rel=1e-3)


def test_area_by_type(meta):
    r = ask(meta, "What is the slab area by type (thickness and bars)?")
    for s in ("D16", "D13", "D22", "300 mm", "150 mm"):
        assert s in r["answer"]


def test_notes(meta):
    assert "D13 @ 300" in ask(meta, "What reinforcement is specified for the 150 slab-on-grade?")["answer"]
    assert "9400" in ask(meta, "What is the top of slab elevation of the D16 slab?")["answer"]
    assert ask(meta, "What is the total length of all trenches given in the notes, in mm?")["answer"] == pytest.approx(7850)
    assert ask(meta, "What is the total trench length?")["answer"] == pytest.approx(7.85)
    assert ask(meta, "How long is the pump control panel trench?")["answer"] == pytest.approx(1.825)
    assert ask(meta, "How many trenches are there?")["answer"] == 3
    assert ask(meta, "How many sumps are there?")["answer"] == 1


def test_control_joint_panels(meta):
    assert ask(meta, "How many control joint panels are in the 300 mm slab with D16 bars?")["answer"] == 6


PDF = Path("/data/attachments/s_YTlo5xSrle/stoa-examples/sources/us_aw_078-24-33/AW_078-24-33.pdf")


@pytest.mark.skipif(not PDF.exists(), reason="source PDF of S-100F not available")
def test_vector_pdf_page(tmp_path):
    """The same sheet as a vector PDF page: exact words, no OCR, no model call."""
    import pymupdf

    src = pymupdf.open(PDF)
    one = pymupdf.open()
    one.insert_pdf(src, from_page=55, to_page=55)
    p = tmp_path / "S-100F.pdf"
    one.save(p)
    m = sheets.build_meta(str(p), do_classify=False)
    assert m.get("text_source") == "pdf" and slab.detect(m) >= 0.8
    A = slab.analyse(m)
    assert A["src"] == "pdf-text" and A["cost_usd"] == 0
    r = slab.answer(str(p), "What is the area of the 150 mm slab-on-grade?", m)
    assert r["answer"] == pytest.approx(61.69, rel=0.02)
    assert "6,200 × 9,950" in r["explanation"]
    assert slab.answer(str(p), "How many control joint panels are in the D16 slab?", m)["answer"] == 6


def test_deterministic_and_ui_fields(meta):
    """Same inputs, same numbers (pinned), and the fields the viewer's legend reads."""
    r = ask(meta, "What is the slab area by type (thickness and bars)?")
    vals = sorted(round(float(e["value"]), 2) for e in r["evidence"] if e["kind"] == "polygon")
    assert vals == PINNED
    meta.pop("slab")
    slab.analyse(meta)  # re-run the geometry from scratch
    r2 = ask(meta, "What is the slab area by type (thickness and bars)?")
    assert r2["answer"] == r["answer"]
    polys = [e for e in r["evidence"] if e["kind"] == "polygon"]
    assert {e["category"] for e in polys} == {"300 mm w/ D16 @ 300", "150 mm w/ D13 @ 300", "300 mm w/ D22 @ 300"}
    assert all(e["unit"] == "m²" for e in polys)
    assert r["unit"] == "m²" and r["low_res"] and r["scale"] == "1:50"


PINNED = [26.49, 61.81, 216.38]  # m², clear areas: D22 genset room, D13 150 slab, D16 main hall


PDF_A = Path("/data/attachments/s_YTlo5xSrle/stoa-examples/sources/us_aw_078-24-28_march_2020/AW_078-24-28_march_2020.pdf")


@pytest.mark.skipif(not PDF_A.exists(), reason="AW 078-24-28 set not available")
@pytest.mark.parametrize("sid", ["S-100A", "S-100B"])
def test_heldout_S100A_imperial(tmp_path, sid):
    """Held-out: S-100A Pumphouse Foundation and Slab Plan (imperial: 6" / 12" slabs, #4 bars, feet-inches),
    found by its sheet id in the title block, never used while tuning the module."""
    import re

    import pymupdf

    src = pymupdf.open(PDF_A)
    idx = None
    for i, pg in enumerate(src):
        W, H = pg.rect.width, pg.rect.height
        R = pg.rotation_matrix
        for w in pg.get_text("words"):
            r = pymupdf.Rect(w[:4]) * R
            if w[4] == sid and r.x0 / W > 0.85 and r.y0 / H > 0.85:  # the sheet id box, bottom right
                idx = i
    assert idx is not None
    one = pymupdf.open()
    one.insert_pdf(src, from_page=idx, to_page=idx)
    p = tmp_path / f"{sid}.pdf"
    one.save(p)
    m = sheets.build_meta(str(p), do_classify=False)
    assert slab.detect(m) >= 0.8
    A = slab.analyse(m)
    assert A["imperial"]
    assert {(t["thickness_in"], t["bars"][0]) for t in A["types"]} == {(6, '#4 @ 18" O.C.'), (12, '#4 @ 12" O.C.E.W.')}
    assert slab.answer(str(p), "What bars are in the 6 inch slab?", m)["answer"] == '#4 @ 18" O.C.'
    assert "#4 @ 12\" O.C.E.W." in slab.answer(str(p), 'What reinforcement does the 12" slab have?', m)["answer"]
    r = slab.answer(str(p), "How long is the power control panel trench?", m)
    assert r["answer"] == pytest.approx(5.5, abs=0.01) and r["unit"] == "ft"
    r = slab.answer(str(p), "What is the slab area by type?", m)
    assert r["unit"] == "SF" and re.search(r"12\" \(305 mm\).*SF", r["answer"])
    assert "dimension strings" in r["explanation"]
    # hand-derived gold from the dimension strings: 6" = 12'-8" x 40'-8" (cable trench room) + 6'-0" x 6'-8"
    # (north-west room) = 555 SF; 12" pump room 58'-4" x 49'-2" = 2,868 SF. The traced outlines alone gave
    # 2,206 / 325 SF; the dimension-driven check rebuilds the ragged / short / missed rooms.
    a12 = slab.answer(str(p), "What is the area of the 12 inch slab?", m)["answer"]
    a6 = slab.answer(str(p), "What is the area of the 6 inch slab?", m)["answer"]
    assert a12 == pytest.approx(2868, rel=0.05)  # S-100B (pump shelter) has the same room dimensions
    assert a6 == pytest.approx(555, rel=0.04)


def test_intent_and_volume(meta):
    """Only the asked quantity: prices and things the sheet does not state abstain; volume = area x thickness."""
    for q in ["What does the concrete cost per m³?", "How heavy is the rebar?", "Who designed this slab?",
              "Tell me about the slab"]:
        assert slab.answer(IMG, q, meta) is None, q
    r = ask(meta, "What is the concrete volume of the 150 mm slab?")
    a150 = ask(meta, "What is the area of the 150 mm slab?")["answer"]
    assert r["unit"] == "m³" and r["answer"] == pytest.approx(a150 * 0.150, abs=0.01)
    assert "× 0.150 m =" in r["explanation"]
    r = ask(meta, "Concrete volume by slab type")
    assert "m³" in r["answer"] and "D13" in r["answer"]
    tot = ask(meta, "How much concrete is in the slabs in total?")["answer"]
    assert tot == pytest.approx(sum(float(e["value"]) for e in r["evidence"] if e["kind"] == "polygon"), rel=1e-3)
