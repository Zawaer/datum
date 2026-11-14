"""bp/sheets/pipe_runs.py on synthetic sheets (no data, no model calls)."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from bp.sheets import pipe_runs as pr  # noqa: E402

PPF = 75.0  # 1/4" = 1'-0" at 300 dpi


def _sheet(tmp_path=None):
    """A 12" header (walls 80 px apart, x 500..2500) with an 8" branch (54 px) teed in below at x = 1500."""
    im = np.full((2000, 4000), 255, np.uint8)
    cv2.line(im, (500, 1000), (2500, 1000), 0, 2)
    cv2.line(im, (500, 1080), (1473, 1080), 0, 2)
    cv2.line(im, (1527, 1080), (2500, 1080), 0, 2)
    for x in range(500, 2501, 400):  # joints / end caps, wall to wall
        cv2.line(im, (x, 1000), (x, 1080), 0, 2)
    cv2.line(im, (1473, 1080), (1473, 1800), 0, 2)
    cv2.line(im, (1527, 1080), (1527, 1800), 0, 2)
    for y in (1300, 1550, 1800):
        cv2.line(im, (1473, y), (1527, y), 0, 2)
    # lettering and a single line (2" drawn single-line) are not pipe walls
    cv2.putText(im, '12" HEADER', (600, 900), cv2.FONT_HERSHEY_SIMPLEX, 1.5, 0, 3)
    cv2.line(im, (500, 1400), (1300, 1400), 0, 2)
    if tmp_path is None:
        return im
    p = tmp_path / "sheet.png"
    cv2.imwrite(str(p), im)
    return p


def test_parse_scale():
    assert pr.parse_scale('SCALE: 1/4" = 1\'-0"')["paper_in_per_ft"] == pytest.approx(0.25)
    assert pr.parse_scale('1" = 20\'')["paper_in_per_ft"] == pytest.approx(0.05)
    assert pr.parse_scale("SCALE: 1 : 50")["ratio"] == 50
    assert pr.parse_scale("no scale here") is None
    assert pr.px_per_ft_from(pr.parse_scale('1/4" = 1\'-0"'), 300) == pytest.approx(75)
    assert pr.px_per_ft_from({"ratio": 50}, 300) == pytest.approx(72)


def test_dpi_and_sizes():
    assert pr.dpi_of(10200, 6600) == pytest.approx(300)  # ANSI D, 34 x 22 in
    assert pr.size_for(100, PPF)[0] == 16
    assert pr.size_for(80, PPF)[0] == 12  # 12.75 in OD
    assert pr.size_for(54, PPF)[0] == 8
    assert pr.size_for(46, PPF)[0] is None  # 7.4 in: no standard OD
    labels = ['16" SUCTION HEADER', '8"', '8"', "300mm F/S DISCHARGE", '5"']  # a lone 5" is an OCR slip
    assert pr.sheet_sizes([{"text": t} for t in labels]) == [8, 12, 16]


def test_scale_bar():
    items = [{"text": t, "bbox": [x - 10, 5000, x + 10, 5030]} for t, x in
             (("0", 6886), ("2'", 7036), ("4'", 7186), ("8'", 7486))]
    b = pr.scale_bar(items, 10200, 6600)
    assert b["px_per_ft"] == pytest.approx(75, rel=0.01)
    mm = [{"text": t, "bbox": [x - 10, 5000, x + 10, 5030]} for t, x in
          (("0", 1000), ("500", 1118), ("1000", 1236), ("2000", 1472))]
    assert pr.scale_bar(mm, 9933, 7017)["px_per_ft"] == pytest.approx(0.236 * 304.8, rel=0.01)


def test_trace_runs_synthetic():
    runs = pr.trace_runs(_sheet(), PPF)
    by = {}
    for r in runs:
        by.setdefault(r["size_in"], []).append(r)
    assert set(by) == {12, 8}
    hdr = max(by[12], key=lambda r: r["length_px"])
    assert hdr["axis"] == "h" and hdr["length_ft"] == pytest.approx(2000 / PPF, rel=0.02)
    br = by[8][0]
    # the branch is measured to the header's centreline (y 1040), not to its wall
    assert br["axis"] == "v" and br["length_ft"] == pytest.approx((1800 - 1040) / PPF, rel=0.03)
    assert sum(r["length_ft"] for r in by[12]) == pytest.approx(2000 / PPF, rel=0.03)


def test_is_length_question():
    assert pr.is_length_question("How many metres of 8-inch pipe are on this plan?")
    assert pr.is_length_question('Total length of the 16" suction header')
    assert pr.is_length_question("Linear feet of pipe by size")
    assert not pr.is_length_question("How many fuel pumps are there?")
    assert not pr.is_length_question('What size is the suction header?')


def test_answer_raster(tmp_path, monkeypatch):
    p = _sheet(tmp_path)
    lines = [{"text": 'SCALE: 1/4" = 1\'-0"', "bbox": [100, 1900, 400, 1930]},
             {"text": '12" HEADER', "bbox": [600, 870, 850, 905]},
             {"text": '8" BRANCH LINE', "bbox": [1560, 1500, 1800, 1530]}]
    monkeypatch.setattr(pr, "_raster_lines", lambda path, meta, W, H: (lines, 0.0))
    monkeypatch.setattr(pr, "dpi_of", lambda w, h: 300.0)
    monkeypatch.setattr(pr, "CACHE", tmp_path / "cache")
    r = pr.answer(str(p), "How many metres of 12-inch pipe are on this plan?", {})
    assert r["answer"] == pytest.approx(2000 / PPF * 0.3048, rel=0.03)
    assert r["evidence"] and all(0 <= v <= 1 for e in r["evidence"] for v in e["bbox"])
    assert "75.0 px/ft" in r["explanation"]
    r = pr.answer(str(p), "Linear feet of pipe by size", {})
    assert r["answer"].startswith('12": 26.') and '8": 10.' in r["answer"]
    assert pr.answer(str(p), "How many fuel pumps?", {}) is None
