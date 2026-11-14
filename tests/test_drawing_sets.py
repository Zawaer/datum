"""Whole drawing sets uploaded as one multi-page PDF (bp/generic/sheetindex.py, app/server.py _prep_pdf /
_upload_question): each page's sheet id and title come from its title block's vector text, the page picker lists them,
and a question that names a sheet is answered on that page. A small synthetic set is generated per test."""
import textwrap
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pymupdf = pytest.importorskip("pymupdf")

from fastapi.testclient import TestClient  # noqa: E402

import app.server as S  # noqa: E402
from bp.generic import sheetindex  # noqa: E402

SHEETS = [("G-001", "COVER SHEET AND INDEX"), ("A-101", "FIRST FLOOR PLAN"), ("M-101A", "PIPING PLAN"),
          ("M-101B", "PIPING PLAN WITH FILTER"), ("S-100A", "FOUNDATION AND SLAB PLAN")]


def _set_pdf(sheets=SHEETS, rotate_from=2) -> bytes:
    """ARCH D-ish pages with a right-hand title strip: the project name (on every page), the sheet title and the
    sheet id under a 'SHEET ID' label. Pages from `rotate_from` on are stored rotated (/Rotate 90), as CAD plots are."""
    doc = pymupdf.open()
    for i, (sid, title) in enumerate(sheets):
        W, H = 2448, 1584
        rot = i >= rotate_from
        pg = doc.new_page(width=H if rot else W, height=W if rot else H)
        if rot:
            pg.set_rotation(90)
        M = pg.derotation_matrix  # draw in displayed coordinates

        def text(x, y, s, size):
            pg.insert_text(pymupdf.Point(x, y) * M, s, fontsize=size, rotate=pg.rotation)

        for k in range(40):  # drawing-area notes, small
            text(100 + (k % 4) * 450, 120 + (k // 4) * 110, f"NOTE {k + 1}: SEE DETAIL {k % 7}/{sid}", 9)
        text(2250, 1150, "ACME ENGINEERS", 12)
        text(2250, 1170, "HARBOUR FUEL DEPOT", 12)
        for k, line in enumerate(textwrap.wrap(title, 13)):
            text(2250, 1250 + 28 * k, line, 22)
        text(2270, 1430, "SHEET ID", 12)
        text(2270, 1490, sid, 40)
    return doc.tobytes()


def test_index_reads_ids_and_titles(tmp_path):
    p = tmp_path / "set.pdf"
    p.write_bytes(_set_pdf())
    idx = sheetindex.index(str(p))
    assert [x["sheet_id"] for x in idx] == [s for s, _ in SHEETS]
    for x, (_, title) in zip(idx, SHEETS):
        assert x["title"].replace(" ", "") == title.replace(" ", ""), x
        assert "HARBOUR" not in x["title"]  # printed on every page: the project, not the sheet


@pytest.mark.parametrize("q,page", [("How many check valves on M-101A?", 2), ("check valves on sheet m101a", 2),
                                    ("Slab area on S-100A?", 4), ("how many doors on M-101B", 3),
                                    ("How many doors?", None), ("pump PS-1 size?", None)])
def test_find_sheet_named_in_question(tmp_path, q, page):
    p = tmp_path / "set.pdf"
    p.write_bytes(_set_pdf())
    assert sheetindex.find(q, sheetindex.index(str(p))) == page


@pytest.fixture()
def up(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(S, "SHEET_CHECK", False)
    monkeypatch.setattr(S, "SHEET_TYPES", False)
    monkeypatch.setattr(S, "_gpu_warm", lambda m: None, raising=False)
    return TestClient(S.app)


def test_upload_lists_sheets_and_question_picks_page(up):
    r = up.post("/api/upload?name=set.pdf", content=_set_pdf())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["pages"] == len(SHEETS)
    assert j["sheet_ids"] == {str(i): s for i, (s, _) in enumerate(SHEETS)}
    assert j["page_titles"]["2"] == "M-101A · PIPING PLAN"
    q = S._upload_question(S.Ask(path=j["path"], question="How many check valves on M-101A?"))
    assert q["page"] == 2 and "M-101A" in q["page_why"]
    # viewing another page: the sheet named in the question still wins; an unnamed question keeps the viewed page
    q = S._upload_question(S.Ask(path=j["path"], question="How many check valves on M-101A?", page=4))
    assert q["page"] == 2
    q = S._upload_question(S.Ask(path=j["path"], question="How many check valves?", page=4))
    assert q["page"] == 4 and q["page_why"] is None


def test_page_sheet_kind_classified_lazily(up, monkeypatch):
    """The first question on page N of a set classifies page N alone (cached in meta.json), not all pages up front."""
    r = up.post("/api/upload?name=set.pdf", content=_set_pdf())
    j = r.json()
    calls = []

    def fake_build_meta(path, page=0, cache_dir=None, do_classify=True):
        calls.append(page)
        return {"kind": "piping", "title": "PIPING PLAN M-101A"}

    from bp import sheets as sheet_types

    monkeypatch.setattr(S, "SHEET_TYPES", True)
    monkeypatch.setattr(sheet_types, "build_meta", fake_build_meta)
    monkeypatch.setattr(sheet_types, "warm_upload", lambda m: None)
    meta = S._upload_meta(j["path"])
    meta["sheet_kind"] = "other"  # page 0 (the cover), as classified at upload
    (S.UPLOADS / j["path"].split("/", 1)[1]).parent.joinpath("meta.json").write_text(S.json.dumps(meta))
    q = S._upload_question(S.Ask(path=j["path"], question="How many check valves on M-101A?"))
    assert q["sheet_kind"] == "piping" and calls == [2]
    q = S._upload_question(S.Ask(path=j["path"], question="Which sheets are referenced on M-101A?"))
    assert q["sheet_kind"] == "piping" and calls == [2]  # cached in meta.json


def test_big_set_prepares_without_rendering_every_page(up, monkeypatch):
    """60 pages: preparation reads text only; a page is rendered when it is asked about, not before."""
    renders = []
    orig = pymupdf.Page.get_pixmap

    def counting(self, *a, **kw):
        renders.append(self.number)
        return orig(self, *a, **kw)

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", counting)
    sheets = [(f"M-{100 + i}", f"PIPING PLAN AREA {i}") for i in range(60)]
    t = time.monotonic()
    r = up.post("/api/upload?name=bigset.pdf", content=_set_pdf(sheets))
    assert r.status_code == 200, r.text
    assert time.monotonic() - t < 10
    assert len(renders) <= 1  # the first page's validity check, at a fifth of its size
    assert r.json()["sheet_ids"]["42"] == "M-142"


def test_set_skips_the_model_page_check(up, monkeypatch):
    """A set whose title blocks name its sheets needs no contact-sheet model call: every page is a titled drawing."""
    from bp.generic import sheets

    def boom(*a, **kw):
        raise AssertionError("the model page check ran on a titled drawing set")

    monkeypatch.setattr(S, "SHEET_CHECK", True)
    monkeypatch.setattr(sheets, "check", boom)
    j = up.post("/api/upload?name=set.pdf", content=_set_pdf()).json()
    assert j["drawing_pages"] == list(range(len(SHEETS))) and not j["not_drawing"]
    assert j["suggested"][:2] == ["How many check valves on M-101A?", "Slab area by type on S-100A?"]
