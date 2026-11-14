"""Huge and odd raster / PDF uploads (app/server.py _prepare, /api/render, /api/pageinfo, /api/crop): size and memory
guards, pixel-format normalisation, the display / full-size / OCR copies, and the crop endpoint's path guard.
Big images are generated on the fly (mostly white, so a few MB on disk at most) and removed with tmp_path."""
import io
import resource
import struct
import zlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import app.server as S  # noqa: E402

TRAVERSAL = ["../../etc/passwd", "/etc/passwd", "data/../../../../etc/passwd", "uploads/../../etc/passwd",
             "uploads/../server.py", "uploads//etc/passwd", "uploads/abc/../../../../etc/passwd"]


@pytest.fixture()
def up(tmp_path, monkeypatch):
    """Uploads go to a temp folder; no model calls (sheet check / sheet type off)."""
    monkeypatch.setattr(S, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(S, "SHEET_CHECK", False)
    monkeypatch.setattr(S, "SHEET_TYPES", False)
    monkeypatch.setattr(S, "_gpu_warm", lambda m: None, raising=False)
    S._crop.cache_clear()
    S._render.cache_clear()
    S._crop_src.clear()
    return TestClient(S.app)


def _png(im, **kw) -> bytes:
    b = io.BytesIO()
    im.save(b, "PNG", **kw)
    return b.getvalue()


def _post(client, name, data):
    return client.post(f"/api/upload?name={name}", content=data)


def _sheet(w, h, mode="L", colour=False):
    im = Image.new(mode, (w, h), "white")
    d = ImageDraw.Draw(im)
    for x in range(0, w, max(1, w // 40)):
        d.line([x, 0, x, h], fill="black", width=3)
    if colour:
        d.rectangle([w // 4, h // 4, w // 2, h // 2], fill=(240, 120, 120))
    return im


def _bomb_png(w, h) -> bytes:
    """A valid 1x1 PNG whose header claims w x h: nothing behind it, so it must be refused from the header alone."""
    raw = bytearray(_png(Image.new("L", (1, 1), 255)))
    ihdr = raw[12:29]  # b"IHDR" + 13 bytes
    ihdr[4:12] = struct.pack(">II", w, h)
    raw[12:29] = ihdr
    raw[29:33] = struct.pack(">I", zlib.crc32(bytes(ihdr)) & 0xFFFFFFFF)
    return bytes(raw)


def _rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


# ---------------------------------------------------------------- size and memory guards
@pytest.mark.parametrize("ext", ["png", "tif"])
def test_bomb_refused_from_header(up, ext):
    data = _bomb_png(30000, 30000)  # 900 MP, ~2.7 GB if decoded
    if ext == "tif":
        b = io.BytesIO()
        Image.new("L", (1, 1)).save(b, "TIFF")
        raw = bytearray(b.getvalue())  # patch ImageWidth / ImageLength (tags 256 / 257, SHORT) in the IFD
        ifd = struct.unpack("<I", raw[4:8])[0]
        for i in range(struct.unpack("<H", raw[ifd:ifd + 2])[0]):
            e = ifd + 2 + 12 * i
            tag, typ = struct.unpack("<HH", raw[e:e + 4])
            if tag in (256, 257):
                raw[e + 2:e + 4] = struct.pack("<H", 4)
                raw[e + 8:e + 12] = struct.pack("<I", 30000)
        data = bytes(raw)
    before = _rss_mb()
    r = _post(up, f"bomb.{ext}", data)
    assert r.status_code == 413, r.text
    assert "megapixels" in r.json()["detail"]
    assert _rss_mb() - before < 300  # nothing was decoded


def test_byte_limit(up, monkeypatch):
    monkeypatch.setattr(S, "MAX_UPLOAD", 1000)
    r = _post(up, "plan.png", b"\0" * 2000)
    assert r.status_code == 413


def test_huge_gray_sheet_keeps_full_resolution(up):
    im = _sheet(12000, 9000)  # 108 MP: over the old 40 MP cap, under REFUSE_PIXELS
    r = _post(up, "school.png", _png(im, compress_level=1))
    assert r.status_code == 200, r.text
    d = r.json()
    p = S.resolve(d["path"])
    with Image.open(p) as w:
        assert w.size == (12000, 9000) and w.mode == "L"
    view = p.with_name(p.name + ".view.png")
    with Image.open(view) as v:
        assert max(v.size) == S.VIEW_SIDE
    # the browser gets the display copy, not 108 MP
    rr = up.get("/api/render", params={"path": d["path"]})
    assert rr.status_code == 200 and Image.open(io.BytesIO(rr.content)).size == (6000, 4500)
    assert up.get("/api/pageinfo", params={"path": d["path"]}).json() == {"w": 12000, "h": 9000}
    # a crop past the display copy's resolution comes from the full-size raster
    c = up.get("/api/crop", params={"path": d["path"], "x0": 0.5, "y0": 0.5, "x1": 0.6, "y1": 0.6, "w": 4000})
    assert c.status_code == 200 and c.headers["content-type"] == "image/png"
    cw, ch = Image.open(io.BytesIO(c.content)).size
    assert abs(cw - 1200) <= 2 and abs(ch - 900) <= 2  # never upscaled past the source (1200 x 900 px)


def test_colour_sheet_capped_with_full_gray_copy(up, monkeypatch):
    monkeypatch.setattr(S, "WORK_RGB_PIXELS", 2_000_000)
    r = _post(up, "zones.png", _png(_sheet(3000, 2000, "RGB", colour=True)))
    assert r.status_code == 200, r.text
    p = S.resolve(r.json()["path"])
    with Image.open(p) as w:
        assert w.mode == "RGB" and abs(w.width * w.height - 2_000_000) < 10_000
    full = p.with_name(p.name + ".full.png")
    with Image.open(full) as f:
        assert f.size == (3000, 2000) and f.mode == "L"
    assert up.get("/api/pageinfo", params={"path": r.json()["path"]}).json() == {"w": 3000, "h": 2000}


def test_colourless_rgb_becomes_gray(up, monkeypatch):
    monkeypatch.setattr(S, "GRAY_ABOVE_PIXELS", 1_000_000)
    r = _post(up, "scan.png", _png(_sheet(2000, 1000, "RGB")))
    assert r.status_code == 200
    with Image.open(S.resolve(r.json()["path"])) as w:
        assert w.mode == "L" and w.size == (2000, 1000)


def test_small_raster_gets_ocr_copy(up):
    r = _post(up, "screenshot.png", _png(_sheet(1600, 1000)))
    assert r.status_code == 200
    p = S.resolve(r.json()["path"])
    with Image.open(p.with_name(p.name + ".ocr.png")) as o:
        assert o.size == (3200, 2000)
    assert not p.with_name(p.name + ".view.png").exists()
    rr = up.get("/api/render", params={"path": r.json()["path"]})
    assert Image.open(io.BytesIO(rr.content)).size == (1600, 1000)  # the original is what is shown


# ---------------------------------------------------------------- pixel formats and file types
def test_transparent_png_on_white(up):
    im = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    ImageDraw.Draw(im).line([0, 150, 400, 150], fill=(0, 0, 0, 255), width=4)
    r = _post(up, "t.png", _png(im))
    assert r.status_code == 200
    with Image.open(S.resolve(r.json()["path"])) as w:
        assert w.mode in ("RGB", "L") and w.convert("L").getpixel((5, 5)) == 255  # not black


def test_16bit_png(up):
    im = Image.new("I;16", (300, 200), 60000)
    r = _post(up, "deep.png", _png(im))
    assert r.status_code == 200
    with Image.open(S.resolve(r.json()["path"])) as w:
        assert w.mode == "L" and w.getpixel((1, 1)) == 255


@pytest.mark.parametrize("fmt,ext,mode", [("WEBP", "webp", "RGBA"), ("TIFF", "tif", "L"), ("BMP", "bmp", "RGB"),
                                           ("GIF", "gif", "P")])
def test_converted_formats(up, fmt, ext, mode):
    im = _sheet(800, 600, "RGB").convert(mode)
    b = io.BytesIO()
    im.save(b, fmt)
    r = _post(up, f"plan.{ext}", b.getvalue())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["path"].endswith(".png") and d["kind"] == "raster"
    assert up.get("/api/render", params={"path": d["path"]}).status_code == 200


def test_big_single_page_tiff(up):
    b = io.BytesIO()
    _sheet(11000, 10000).save(b, "TIFF", compression="tiff_deflate")  # 110 MP: over FRAME_PIXEL_BUDGET, one frame
    r = _post(up, "scan.tif", b.getvalue())
    assert r.status_code == 200, r.text
    with Image.open(S.resolve(r.json()["path"])) as w:
        assert w.size == (11000, 10000) and w.mode == "L"


def test_multipage_tiff_becomes_pdf(up):
    b = io.BytesIO()
    pages = [_sheet(600, 400) for _ in range(3)]
    pages[0].save(b, "TIFF", save_all=True, append_images=pages[1:])
    r = _post(up, "set.tif", b.getvalue())
    assert r.status_code == 200, r.text
    assert r.json()["path"].endswith(".pdf") and r.json()["pages"] == 3


def test_heic_converted_like_a_jpg(up):
    """An iPhone photo (HEIC) is read like a JPG: converted, with the orientation libheif applies on decode."""
    pillow_heif = pytest.importorskip("pillow_heif")
    if not pillow_heif.libheif_info().get("encoders"):
        pytest.skip("this libheif build cannot write HEIC")
    b = io.BytesIO()
    pillow_heif.from_pillow(_sheet(640, 480, "RGB")).save(b, quality=90)
    r = _post(up, "IMG_0001.HEIC", b.getvalue())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["path"].endswith(".jpg") and j["kind"] == "raster"
    assert any("HEIC" in n for n in j["notes"])
    p = S.UPLOADS / j["path"].split("/", 1)[1]
    with Image.open(p) as im:
        assert im.format == "JPEG" and im.size == (640, 480)


def test_damaged_heic_gets_a_reason(up):
    pytest.importorskip("pillow_heif")
    r = _post(up, "photo.heic", b"\0\0\0\x18ftypheic" + b"\0" * 64)
    assert r.status_code == 422 and "HEIC" in r.json()["detail"]


# ---------------------------------------------------------------- PDFs: rotation in display and crops
def test_rotated_pdf_crop_matches_render(up):
    pymupdf = pytest.importorskip("pymupdf")
    import numpy as np

    doc = pymupdf.open()
    pg = doc.new_page(width=600, height=400)
    pg.insert_text((40, 60), "NORTH WING", fontsize=30)
    pg.draw_rect(pymupdf.Rect(300, 200, 560, 380), color=(0, 0, 0), fill=(0, 0, 0))
    pg.set_rotation(90)
    r = _post(up, "rot.pdf", doc.tobytes())
    assert r.status_code == 200, r.text
    path = r.json()["path"]
    full = Image.open(io.BytesIO(up.get("/api/render", params={"path": path, "dpi": 72}).content)).convert("L")
    assert full.size == (400, 600)  # shown upright as rotated
    for box in [(0, 0, 0.5, 0.5), (0.5, 0.5, 1, 1), (0.1, 0.6, 0.4, 0.9)]:
        c = up.get("/api/crop", params={"path": path, "x0": box[0], "y0": box[1], "x1": box[2], "y1": box[3],
                                        "w": 800})
        assert c.status_code == 200
        ci = Image.open(io.BytesIO(c.content)).convert("L")
        ref = full.crop((round(box[0] * 400), round(box[1] * 600), round(box[2] * 400), round(box[3] * 600)))
        a = np.asarray(ci.resize(ref.size), float)
        assert abs(a.mean() - np.asarray(ref, float).mean()) < 12, box
    assert up.get("/api/pageinfo", params={"path": path}).json() == {"w": 3333, "h": 5000}


# ---------------------------------------------------------------- crop endpoint guards
@pytest.mark.parametrize("path", TRAVERSAL + ["uploads/abc/../../app/server.py", "app/server.py", "README.md",
                                             "uploads/x\x00.png"])
def test_crop_path_guard(up, path):
    r = up.get("/api/crop", params={"path": path, "x0": 0, "y0": 0, "x1": 1, "y1": 1, "w": 256})
    assert r.status_code == 404
    assert up.get("/api/pageinfo", params={"path": path}).status_code == 404


@pytest.mark.parametrize("box", [(0.5, 0, 0.4, 1), (0, 0, 1.5, 1), (-0.2, 0, 1, 1), (0, 0, 0, 0),
                                 (float("nan"), 0, 1, 1), (0.5, 0.5, 0.50001, 0.50001)])
def test_crop_bad_box(up, box):
    r = _post(up, "s.png", _png(_sheet(400, 300)))
    params = {"path": r.json()["path"], "x0": box[0], "y0": box[1], "x1": box[2], "y1": box[3], "w": 256}
    assert up.get("/api/crop", params=params).status_code == 400


def test_crop_size_capped(up):
    r = _post(up, "s.png", _png(_sheet(9000, 300)))
    c = up.get("/api/crop", params={"path": r.json()["path"], "x0": 0, "y0": 0, "x1": 1, "y1": 1, "w": 100000})
    assert c.status_code == 200
    assert max(Image.open(io.BytesIO(c.content)).size) <= S.CROP_MAX_SIDE
