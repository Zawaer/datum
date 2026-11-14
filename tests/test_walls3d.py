"""bp/sheets/walls3d.py and /api/walls on synthetic floor plans (no dataset, no OCR, no model calls): a 20 x 15 m
sheet at 100 px/m with four rooms, solid (poché) walls or walls drawn as two thin outlines, a door with its leaf and
swing in an inner wall and a glazed window in the outer wall."""
import json

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from bp.sheets import walls3d  # noqa: E402

PPM = 100  # px per metre of the synthetic sheet


def plan(outline: bool = False) -> np.ndarray:
    g = np.full((15 * PPM, 20 * PPM), 255, np.uint8)
    t = int(0.25 * PPM)

    def wall(x0, y0, x1, y1):  # metres; a horizontal or vertical wall t thick
        a, b, c, d = int(x0 * PPM), int(y0 * PPM), int(x1 * PPM), int(y1 * PPM)
        if b == d:
            b, d = b - t // 2, b + t // 2
        else:
            a, c = a - t // 2, a + t // 2
        if outline:
            cv2.rectangle(g, (a, b), (c, d), 0, 2)
        else:
            g[b:d, a:c] = 0

    # outer walls (a window gap 4.0-6.0 m in the top wall), and two inner walls (a door gap 6.0-6.9 m)
    wall(2, 2, 4, 2), wall(6, 2, 18, 2)
    wall(2, 13, 18, 13), wall(2, 2, 2, 13), wall(18, 2, 18, 13)
    wall(10, 2, 10, 13)
    wall(2, 7, 6, 7), wall(6.9, 7, 18, 7)
    # glazing: two thin lines along the window gap; the door: a leaf square to the wall and its swing
    for dy in (-6, 6):
        cv2.line(g, (4 * PPM, 2 * PPM + dy), (6 * PPM, 2 * PPM + dy), 0, 2)
    cv2.line(g, (int(6.0 * PPM), 7 * PPM + t // 2), (int(6.0 * PPM), int(7.9 * PPM)), 0, 2)
    cv2.ellipse(g, (int(6.0 * PPM), 7 * PPM + t // 2), (90, 90), 0, 0, 90, 0, 2)
    # lettering in a room and a title block line: neither is a wall
    cv2.putText(g, "OFFICE", (int(12 * PPM), int(10 * PPM)), cv2.FONT_HERSHEY_SIMPLEX, 2, 0, 3)
    return g


def test_extract_solid_walls():
    r = walls3d.extract(plan(), PPM)
    assert r["plausible"] and r["wall_style"] == "solid"
    assert r["rooms_n"] == 4
    assert r["page_m"] == [20.0, 15.0]
    assert 100 < r["enclosed_m2"] < 16 * 11  # four rooms inside a 16 x 11 m shell, net of the walls
    # walls hug the drawn shell: bounds ~ 2..18 m x 2..13 m of a 20 x 15 m page
    x0, y0, x1, y1 = r["bounds"]
    assert abs(x0 - 1.875 / 20) < 0.01 and abs(x1 - 18.125 / 20) < 0.01 and abs(y0 - 1.875 / 15) < 0.01
    pts = [p for w in r["walls"] for ring in [w["outer"], *w["holes"]] for p in ring]
    assert all(0 <= u <= 1 and 0 <= v <= 1 for u, v in pts)
    assert len(r["doors"]) >= 1 and len(r["windows"]) == 1
    d = r["doors"][0]
    assert abs(d["width_m"] - 0.9) < 0.15 and d["axis"] == "h"
    w = r["windows"][0]
    assert abs(w["width_m"] - 2.0) < 0.15 and abs(w["bbox"][0] - 4 / 20) < 0.01
    # the lettering is no wall: nothing extruded around (12..15 m, 9.5..10 m)
    for p in r["walls"]:
        us = [q[0] * 20 for q in p["outer"]]
        vs = [q[1] * 15 for q in p["outer"]]
        assert not (min(us) > 11 and max(us) < 16 and min(vs) > 9 and max(vs) < 10.5)


def test_extract_outline_walls():
    r = walls3d.extract(plan(outline=True), PPM)
    assert r["plausible"] and r["wall_style"] == "outline"
    assert r["rooms_n"] >= 4


def test_segment_cap_and_blank_page():
    r = walls3d.extract(plan(), PPM, max_segments=24)
    assert r["segments"] <= 40 and r["simplify_m"] > 0.035
    blank = walls3d.extract(np.full((1500, 2000), 255, np.uint8), PPM)
    assert not blank["plausible"] and blank["walls"] == []


def test_scale_guess_from_wall_thickness():
    est = walls3d.guess_px_per_m(plan())
    assert est and 0.6 * PPM < est < 2 * PPM  # 0.25 m walls taken as 0.2 m: ~125 px/m


# ---------------------------------------------------------------- /api/walls
pytest.importorskip("fastapi")
pytest.importorskip("httpx")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.server as S

    monkeypatch.setattr(S, "UPLOADS", tmp_path / "uploads")
    S._WALLS.clear()
    d = tmp_path / "uploads" / "0123456789ab"
    d.mkdir(parents=True)
    cv2.imwrite(str(d / "plan.png"), plan())
    cv2.imwrite(str(d / "blank.png"), np.full((800, 1000), 255, np.uint8))
    return TestClient(S.app), d


def test_api_walls(client):
    c, d = client
    r = c.get("/api/walls", params={"path": "uploads/0123456789ab/plan.png"})
    assert r.status_code == 200
    j = r.json()
    assert j["plausible"] and j["walls"] and j["segments"] <= 4000
    assert j["scale"]["estimated"] and 60 < j["scale"]["px_per_m"] < 200
    assert j["page_m"][0] == pytest.approx(2000 / j["scale"]["px_per_m"], rel=1e-3)
    cached = json.loads((d / "walls_p0.json").read_text())  # cached beside the image
    assert cached["walls"] == j["walls"]
    assert c.get("/api/walls", params={"path": "uploads/0123456789ab/plan.png"}).json() == j
    assert c.get("/api/walls", params={"path": "uploads/0123456789ab/blank.png"}).json()["plausible"] is False


@pytest.mark.parametrize("path", ["uploads/0123456789ab/../../../etc/passwd", "uploads/../server.py", "/etc/passwd",
                                  "app/server.py", "uploads/0123456789ab/missing.png", "uploads/x\x00.png",
                                  "uploads/0123456789ab/meta.json"])
def test_api_walls_guard(client, path):
    c, _ = client
    assert c.get("/api/walls", params={"path": path}).status_code == 404
