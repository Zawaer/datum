"""Answer card and overlay for uploaded sheets (bp/sheets specialists), in a real browser, without the specialists:
each fixture in tests/fixtures/sheets_ui/ is an /api/ask result with one of the evidence kinds they return (tag boxes,
pipe-run / baseboard polylines, table cells, region polygons per category). The page is pointed at a fake upload
and /api/questions, /api/render and /api/ask are answered from the fixture, so only the UI is under test.

    .venv/bin/python -m pytest tests/test_sheet_ui.py             # needs playwright + chromium
    SHEET_UI_SHOTS=runs/sheet_ui .venv/bin/python -m pytest tests/test_sheet_ui.py   # also save screenshots

The drawing is the Stoa example sheet named in the fixture when STOA_DIR has it, else a blank page (coordinates are
normalised, so the marks land in the same places either way)."""
import io
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests/fixtures/sheets_ui"
STOA = Path(os.environ.get("STOA_DIR", "/data/attachments/s_YTlo5xSrle/stoa-examples"))
SHOTS = os.environ.get("SHEET_UI_SHOTS")
NAMES = sorted(p.stem for p in FIX.glob("*.json"))


def _png(name: str) -> bytes:
    f = STOA / name
    if f.exists():
        return f.read_bytes()
    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (2000, 1400), "white").save(b, "PNG")
    return b.getvalue()


@pytest.fixture(scope="module")
def server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "BP_NORMALIZE": "0", "BP_CROSSCHECK": "0", "BP_SHEETS": "0"}
    if not (REPO / "data/full/junction-dataset/questions.jsonl").exists():
        env.setdefault("BP_DATA", str(REPO / "tests/fixtures/mini_dataset"))
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1", "--port", str(port)],
                         cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.5)
    yield url
    p.terminate()
    p.wait(10)


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(args=["--use-gl=swiftshader"])
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"chromium not available: {e}")
        yield b
        b.close()


def open_fixture(browser, url, name, viewport):
    fx = json.loads((FIX / f"{name}.json").read_text())
    path = f"uploads/fixture{name[:4]}/{fx['image']}"
    sug = {"piping": ["How many fuel pumps?", "What size is the suction header?", "How many check valves?"],
           "slab": ["Slab area by type?", "How many pad footings?", "What is the slab thickness?"]}.get(
        fx["sheet_kind"], ["How many doors?", "Baseboard length in the Library?", "How many rooms?"])
    info = {"path": path, "view": path, "credit": "Stoa example sheet", "has3d": False, "kind": "raster",
            "questions": [{"question": q, "type": None, "answer": None} for q in sug + ["What is the total floor area?"]],
            "notes": [], "pages": 1, "page_titles": {}, "drawing_pages": [0], "not_drawing": None, "original": None,
            "sheet_kind": fx["sheet_kind"], "sheet_label": fx["sheet_kind"], "sheet_title": fx["sheet_title"],
            "sheet_scale": fx["sheet_scale"], "sheet_units": fx.get("sheet_units", "metric"),
            "sheet_low_res": fx.get("sheet_low_res", False), "suggested": sug}
    res = {**fx["res"], "evidence": [{**e, "file": path} for e in fx["res"]["evidence"]]}
    ctx = browser.new_context(viewport=viewport, reduced_motion="reduce", device_scale_factor=1,
                              has_touch=viewport["width"] < 700, is_mobile=viewport["width"] < 700)
    pg = ctx.new_page()
    pg.route("**/api/questions?*", lambda r: r.fulfill(json=info))
    pg.route("**/api/render?*", lambda r: r.fulfill(body=_png(fx["image"]), content_type="image/png"))
    pg.route("**/api/ask", lambda r: r.fulfill(json=res))
    pg.goto(f"{url}/?tab=upload&path={path}")
    pg.wait_for_selector("#chips3 .chip")
    return pg, fx


def ask(pg, fx):
    pg.fill("#q", fx["question"])
    pg.click("#go")
    pg.wait_for_selector("#ahead .sheetchip")
    pg.wait_for_function("document.querySelector('#img').naturalWidth > 0")
    pg.wait_for_timeout(900)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("vp", [{"width": 1440, "height": 900}, {"width": 390, "height": 844}], ids=["desk", "phone"])
def test_sheet_answer(server, browser, name, vp):
    pg, fx = open_fixture(browser, server, name, vp)
    # three examples tailored to the sheet type, in the server's order
    assert pg.locator("#chips3 .chip").count() == 3
    ask(pg, fx)
    chip = pg.inner_text("#ahead .sheetchip")
    assert chip.split(" · ")[0] in ("Piping plan", "Slab plan", "Dormitory plan", "School floor plan", "Floor plan")
    kinds = {e["kind"] for e in fx["res"]["evidence"]}
    if "polyline" in kinds:
        assert pg.locator("#ov path.pl").count() >= 1
        assert pg.locator("#ov text.pglabel").count() >= 1  # its length
    if "cell" in kinds:
        assert pg.locator("#ov rect.cell").count() == sum(e["kind"] == "cell" for e in fx["res"]["evidence"])
        assert "table" in pg.inner_text("#ahead")
    if any(e.get("category") for e in fx["res"]["evidence"]):
        assert pg.locator("#ov path.pg.cat").count() >= 2
        assert pg.locator(".catleg .cl").count() >= 2
    if name == "piping_tags":
        assert pg.locator("#sheetev .tgrp").count() == 2  # FP and CV
        assert pg.locator("#sheetev .tagc").count() == 10
        assert pg.locator("#ov text.badge").count() == 10  # counts keep their numbered badges
        assert "Low resolution" in pg.inner_text("#ahead")
        pg.locator("#sheetev .tagc").nth(2).click()
        pg.wait_for_timeout(300)
    if name == "school_baseboard":
        assert pg.inner_text("#ahead .big").replace("\n", " ").strip().startswith("71.7")  # a length, not a rounded count
    if name == "dorm_imperial":  # "18,472 SF" as a string: the number in its unit; the table reads are evidence rows
        big = pg.inner_text("#ahead .big").replace("\n", " ")
        assert "18,472" in big and "SF" in big
        assert pg.locator("#ov rect.cell").count() == 3
        assert "SF" in pg.text_content("#ev")
        assert "Low resolution" in pg.inner_text("#ahead")  # from the sheet meta, not the result
        assert "SF" in pg.text_content(".catleg") and "m²" not in pg.text_content(".catleg")
    if name == "dorm_length":
        assert pg.inner_text("#ahead .big .bn") == "323'-4\""
    if name == "slab_zones":  # a list answer: the total is the number, the parts a list
        assert "538" in pg.inner_text("#ahead .big")
        assert pg.locator("#ahead .alist > div").count() == 3
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=f"{SHOTS}/{name}-{'phone' if vp['width'] < 700 else 'desk'}.png")
    pg.context.close()
