"""bp/sheets/piping.py on cached reads of the USACE piping plan M-101A (no OCR, no model calls).

Fixtures (tests/fixtures/piping/):
  M-101A_pdf_read.json     the PDF text layer of AW 078-24-28 p96 (exact text)
  M-101A_lowres_read.json  tesseract (3 variants) + Haiku tile transcription of the 2000 px screenshot
"""
import copy
import json
from pathlib import Path

import pytest

from bp.sheets import piping as P

FIX = Path(__file__).parent / "fixtures" / "piping"


def _load(name):
    d = json.loads((FIX / name).read_text())
    d["cost_usd_now"] = 0.0
    d["image"] = None
    return d


@pytest.fixture(params=["M-101A_pdf_read.json", "M-101A_lowres_read.json"])
def sheet(request, monkeypatch):
    d = _load(request.param)
    monkeypatch.setattr(P, "read_sheet", lambda path, meta=None, vision=None: copy.deepcopy(d))

    def no_llm(*a, **k):
        raise AssertionError("no model call expected in this test")

    import bp.generic.llm as llm
    monkeypatch.setattr(llm, "ask", no_llm)
    return request.param


def ask(q):
    r = P.answer("M-101A.jpg", q, {})
    assert r is not None, q
    assert r["method"] == "sheets-piping"
    for e in r["evidence"]:
        assert len(e["bbox"]) == 4 and all(0 <= v <= 1 for v in e["bbox"]) and e["label"]
    return r


@pytest.mark.parametrize("q,gold", [
    ("How many fuel pumps?", 5),
    ("How many non-surge check valves (CV) are shown?", 5),
    ("How many filter separators (FSI and FSR) are shown?", 7),
    ("How many different pipe support types (PS tags) are on this plan?", 23),
])
def test_counts(sheet, q, gold):
    r = ask(q)
    assert r["answer"] == gold
    assert sum(1 for e in r["evidence"] if e["value"] == 1) == gold  # one numbered box per distinct tag


def test_control_valves(sheet):
    r = ask("How many control valves?")
    if sheet.startswith("M-101A_pdf"):
        assert r["answer"] == 7 and r["confidence"] >= 0.9
    else:  # without the image the zoomed re-check cannot run: the gap is reported, not filled
        assert r["answer"] in (6, 7)
        if r["answer"] == 6:
            assert "FSCV-6" in r["explanation"]


def test_pipe_support_labels_vs_types(sheet):
    types = ask("How many pipe supports?")
    labels = ask("How many pipe support labels are there?")
    assert types["answer"] == 23 and "PS-2" in types["explanation"]  # the numbering gap is named
    assert labels["answer"] >= 40 and labels["answer"] > types["answer"]
    if sheet.startswith("M-101A_pdf"):
        assert labels["answer"] == 41


def test_sizes(sheet):
    r = ask("What sizes of pipe are on this sheet?")
    assert r["answer"] == '1", 2", 3", 4", 6", 8", 10", 12", 16"'


@pytest.mark.parametrize("q,gold", [("What is the suction header size?", '16"'),
                                    ("What size is the pump discharge header?", '12"'),
                                    ("What size is the return line?", '8"')])
def test_named_size(sheet, q, gold):
    assert ask(q)["answer"] == gold


def test_references(sheet):
    r = ask("Which other sheets does this plan reference?")
    assert r["answer"] == "M-001, M-301A, M-302, M-303, M-504, MS513, S-101"
    assert "E1 on M-504" in r["explanation"]


def test_notes(sheet):
    r = ask("What does note 4 say?")
    assert r["answer"].startswith("MICRONIC FILTER MAY BE NECESSARY")
    assert "DIRECTED BY SME" in r["answer"]
    assert ask("How many notes are there?")["answer"] == 8


def test_where(sheet):
    assert ask("Where is FP-3?")["answer"] == "FP-3 at grid F-5"
    r = ask('Where does the 8" return line go?')
    assert "grid E-2" in r["answer"] and "CROSS CONNECTION" in r["answer"]


# ------------------------------------------------------------------------------------------- parsing units
def _tags(text):
    return [t["tag"] for t in P.tags_in({"text": text, "bbox": [0, 0, 0.1, 0.01]})]


def test_tags_ocr_and_lists():
    assert _tags("DPT-1 & 2") == ["DPT-1", "DPT-2"]
    assert _tags("PIT 3") == ["PIT-3"]
    assert _tags("ESCV-6") == ["FSCV-6"]  # tesseract reads the F of an underlined FSCV as E
    assert _tags("CV-t") == ["CV-1"]
    assert _tags("FP.2") == ["FP-2"]
    assert _tags("SEE SHEET M-303") == []  # sheet ids are not tags
    assert _tags("TANK NO. 1") == []


def test_sizes_exclusions():
    s = lambda t: [x for x, _, _ in P.sizes_in(t)]  # noqa: E731
    assert s('10" X 12" REDUCER') == ['10"', '12"']
    assert s('LABEL ON WALL IN 4" TALL LETTERS') == []
    assert s('SCALE: 1/4" = 1\'-0"') == []
    assert s("16° SUCTION HEADER") == ['16"']  # OCR's degree sign is an inch mark
    assert s("200mm RETURN LINE, 15mm DIA BOLTS") == ["200mm"]


def test_tag_list_and_tiles():
    assert P._tag_list("FP", [1, 2, 3, 4, 5]) == "FP-1 to FP-5"
    assert P._tag_list("PS", [1] + list(range(3, 25))) == "PS-1, PS-3 to PS-24"
    for wh in [(2000, 1294), (10200, 6600)]:
        tiles, f = P._vision_tiles(*wh)
        assert len(tiles) <= P.MAX_TILES
        assert all(round((t[2] - t[0]) * f) <= P.SEND_PX + 1 for t in tiles)


def test_detect():
    assert P.detect({"kind": "piping", "title": "PIPING PLAN M-101A"}) >= 0.9
    assert P.detect({"kind": "arch", "title": "SECOND FLOOR PLAN A-2"}) < 0.5


def test_tag_chips_and_valve_families(sheet):
    r = ask("How many control valves?")
    tagged = [e for e in r["evidence"] if e.get("tag")]
    assert tagged and all(e["group"] == "FSCV" and e["tag"].startswith("FSCV-") for e in tagged)
    assert "CV (check valves, 5)" in r["explanation"]  # says which valve families were not counted
