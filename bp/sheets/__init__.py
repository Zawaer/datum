"""Sheet-type specialists for uploaded drawings (registry + contract).

Final judging uploads unseen, complex sheets (architectural plans, structural slab plans, piping plans).
Each upload is classified once (`classify`), and a question on it is first offered to the module that
claims the sheet type; the existing generic path (text layer + grounded vision) runs when the module
abstains (returns None, or an answer of None).

Contract for a module `bp/sheets/<name>.py`:

    def detect(meta) -> float          # 0..1: how sure this sheet is my type
    def answer(path, question, meta) -> dict | None

`meta` (built once per upload by `build_meta`, cached by the caller):
    {"text":  page text (PDF text layer, or OCR / vision read of the title block; may be ""),
     "title": title-block text if found (sheet title + number, e.g. "FOUNDATION AND SLAB PLAN S-100F"),
     "kind":  sheet kind from the classifier ("arch" | "slab" | "piping" | "other"),
     "words": [{"text", "bbox" (normalised, as displayed), "conf"}] exact vector words when the upload is a PDF
              page with a text layer ("text_source": "pdf"), else [] ("text_source": "ocr"); use sheets.words(meta)
              (or ocr_words, which returns these first) before running OCR yourself; sheets.pdf_paths(meta) gives
              the page's vector linework (walls, pipes, hatches) in the same normalised coordinates,
     "image": path of a PNG/JPG render of the page (full resolution, page 0 unless "page" says otherwise),
     "page":  page index the image is of,
     "low_res": True for a raster under 3000 px on its long side (OCR upscaled; lower confidence on small text),
     "w", "h": image size in px,
     ...}   modules may add their own cached keys under their own name (meta["slab"] = {...}).

`answer` returns the usual solver result (docs/EVIDENCE.md):
    {"answer": number | str | None, "confidence": 0..1, "method": "sheets-<name>-<path>",
     "cost_usd": float, "explanation": "one line, show the arithmetic",
     "evidence": [{"kind": "box" | "polygon" | "text", "page": 0, "bbox": [x0,y0,x1,y1] | "points": [[x,y],..],
                   "label": "...", "value": <contribution or None>}, ...]}   # coords normalised 0..1 to the image
More evidence the UI draws for sheets (app/static/app.js, fixtures in tests/fixtures/sheets_ui/):
    {"kind": "polyline", "points": [[x,y],..], "closed": bool, "label": "16\" suction header", "value": 38.4, "unit": "m"}
        a pipe run / baseboard: a thin line with its length beside it
    {"kind": "cell", "bbox": [...], "label": "West wing dormitory", "value": 6095, "text": "6,095 SF", "table": "Square footage"}
        a value read from a schedule table (outlined, "from the sheet's table")
    polygons with "category": "300 mm w/ D22 @ 300" get one colour per category and a legend with the area per category
        ("untyped" / "unread" categories are grey); boxes labelled "FP-3" / "3: FP-3" (or with "tag": "FP-3", "group": "FP")
        become tag chips grouped by family that zoom to each tag
Result extras the UI reads: "unit" ("m", "m²", "SF", "mm"; it overrides the guessed question type), "low_res": true (or a
one-line string) for a calm "Low resolution" hint, "sheet_how" ("read from tags", "measured at 1:50") to override the chip
text the UI derives from the method and evidence, "scale" ("1:50").
`file` in evidence items is filled in by the caller when missing. Return None (or answer None) to abstain
and let the generic path answer. Never raise for an ordinary "can't do this" (exceptions are caught and
logged as an abstention anyway).
"""
from __future__ import annotations

import importlib
import logging
import os

log = logging.getLogger(__name__)

MODULES = ["arch", "slab", "piping"]  # bp/sheets/<name>.py; a missing/broken module is skipped
ANSWER_TIMEOUT_S = float(os.environ.get("BP_SHEET_TIMEOUT_S", "45"))  # then the generic reader answers
_pool = __import__("concurrent.futures", fromlist=["x"]).ThreadPoolExecutor(8, thread_name_prefix="sheets")
MIN_DETECT = 0.5  # a module answers only when it claims the sheet at least this strongly


def _load(name):
    try:
        return importlib.import_module(f"bp.sheets.{name}")
    except Exception as e:  # noqa: BLE001
        log.warning("sheet module %s unavailable: %s", name, e)
        return None


def modules():
    return [(n, m) for n in MODULES if (m := _load(n)) is not None]


def scores(meta) -> dict:
    out = {}
    for n, m in modules():
        try:
            out[n] = float(m.detect(meta) or 0.0)
        except Exception as e:  # noqa: BLE001
            log.warning("detect %s failed: %s", n, e)
            out[n] = 0.0
    return out


def best(meta):
    """(name, module, score) of the module that claims this sheet, or (None, None, 0)."""
    sc = scores(meta)
    if not sc:
        return None, None, 0.0
    n = max(sc, key=sc.get)
    if sc[n] < MIN_DETECT:
        return None, None, sc[n]
    return n, _load(n), sc[n]


def answer(path, question, meta):
    """Ask the best module; None when no module claims the sheet or it abstains."""
    n, m, s = best(meta)
    if m is None:
        return None
    import concurrent.futures as cf

    fut = _pool.submit(m.answer, path, question, meta)
    try:
        res = fut.result(timeout=ANSWER_TIMEOUT_S)
    except cf.TimeoutError:
        # the module keeps running in the background (its OCR / segmentation caches fill for the next question);
        # this question goes on to the generic reader rather than keep a judge waiting
        return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": f"sheets-{n}-timeout",
                "explanation": f"the {n} reader took longer than {ANSWER_TIMEOUT_S:.0f} s on this sheet, so the general "
                               "reader answers this time"}
    except Exception as e:  # noqa: BLE001
        log.exception("sheet module %s failed", n)
        return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0,
                "method": f"sheets-{n}-error", "explanation": f"{n} module failed: {type(e).__name__}: {str(e)[:200]}"}
    if res is not None:
        res.setdefault("method", f"sheets-{n}")
        res["sheet_type"] = n
        res["sheet_score"] = round(s, 3)
    return res


# ------------------------------------------------------------------------------------------- meta (once per upload)
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
from pathlib import Path  # noqa: E402

KINDS = ("arch", "slab", "piping", "other")
CLASSIFY_PROMPT = """This is one sheet of a construction drawing set that a user uploaded. Read its title block and
the big view titles, and say what kind of sheet it is. JSON only:
{"kind": "arch" (architectural floor plan / room layout / general arrangement, incl. dormitories, schools, houses) |
         "slab" (structural foundation / slab / reinforcement plan: slab thicknesses, bar sizes, footings) |
         "piping" (mechanical / plumbing / process piping plan: pipes with sizes, valves, tags) |
         "other" (elevation, section, detail, site plan, schedule-only sheet, not a drawing),
 "title": "<sheet title as printed, e.g. 'SECOND FLOOR PLAN T-SHAPE'>",
 "sheet_number": "<sheet id as printed, e.g. 'A-2', or ''>",
 "scale": "<scale as printed, e.g. '1:200' or '1\\" = 40\\'-0\\"', or ''>",
 "units": "metric" | "imperial" | "unknown",
 "has_tables": true if the sheet carries schedules / tables of numbers (areas, counts, quantities)}"""
_KW = {
    "slab": r"slab|foundation|footing|reinforc|rebar|\bD\d{2}\b|S-\d{3}",
    "piping": r"piping|pipe|valve|\bPS-\d|\bCV-\d|suction|discharge|header|M-\d{3}|plumbing",
    "arch": r"floor plan|plan level|dormitory|classroom|corridor|room|\bA-\d",
}
_meta_lock = threading.Lock()
_meta_mem: dict = {}


def _image_for(path: str, page: int, cache_dir: Path) -> tuple[str, int, int]:
    """(raster path, w, h) of the page: rasters as they are; a PDF page rendered once at ~200 dpi (<= 9000 px)."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    ext = path.rsplit(".", 1)[-1].lower()
    if ext in ("png", "jpg", "jpeg"):
        with Image.open(path) as im:
            return path, im.width, im.height
    out = cache_dir / f"sheet_p{page}.png"
    if not out.exists():
        import pymupdf

        pg = pymupdf.open(path)[page]
        zoom = min(300 / 72, 9000 / max(pg.rect.width, pg.rect.height))  # small symbols need ~300 dpi
        pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).save(str(out))
    with Image.open(out) as im:
        return str(out), im.width, im.height


def _pdf_text(path: str, page: int) -> str:
    if not path.lower().endswith(".pdf"):
        return ""
    try:
        import pymupdf

        return pymupdf.open(path)[page].get_text()
    except Exception:  # noqa: BLE001
        return ""


def pdf_words(path: str, page: int) -> list[dict]:
    """Vector words of a PDF page as displayed (page rotation applied), boxes normalised to the rendered page:
    [{"text", "bbox": [x0, y0, x1, y1], "conf": 100}]. [] for rasters or pages without a text layer."""
    if not path.lower().endswith(".pdf"):
        return []
    try:
        import pymupdf

        pg = pymupdf.open(path)[page]
        R = pg.rotation_matrix
        W, H = pg.rect.width, pg.rect.height
        out = []
        for x0, y0, x1, y1, t, *_ in pg.get_text("words"):
            r = pymupdf.Rect(x0, y0, x1, y1) * R
            r.normalize()
            out.append({"text": t, "conf": 100.0,
                        "bbox": [max(0.0, r.x0 / W), max(0.0, r.y0 / H), min(1.0, r.x1 / W), min(1.0, r.y1 / H)]})
        return out
    except Exception:  # noqa: BLE001
        return []


def pdf_paths(meta) -> list[dict]:
    """Vector linework of a PDF upload's page (walls, pipes, hatches, dimension lines), as displayed and
    page-normalised: [{"items": [("l", (x0, y0), (x1, y1)) | ("re", (x0, y0, x1, y1)) | ("c", p0, p1, p2, p3) ...],
    "width": stroke width as a fraction of the page width, "stroke": (r, g, b) | None, "fill": (r, g, b) | None,
    "dashes": str | None, "bbox": [x0, y0, x1, y1]}]. [] for rasters. Cached in meta["_pdf_paths"]."""
    if "_pdf_paths" in meta:
        return meta["_pdf_paths"]
    out = []
    path = str(meta.get("path") or "")
    if path.lower().endswith(".pdf"):
        try:
            import pymupdf

            pg = pymupdf.open(path)[meta.get("page") or 0]
            R = pg.rotation_matrix
            W, H = pg.rect.width, pg.rect.height

            def pt(p):
                q = pymupdf.Point(p) * R
                return (q.x / W, q.y / H)

            for d in pg.get_drawings():
                items = []
                for it in d.get("items") or []:
                    if it[0] == "l":
                        items.append(("l", pt(it[1]), pt(it[2])))
                    elif it[0] == "re":
                        r = pymupdf.Rect(it[1]) * R
                        r.normalize()
                        items.append(("re", (r.x0 / W, r.y0 / H, r.x1 / W, r.y1 / H)))
                    elif it[0] == "c":
                        items.append(("c", *[pt(p) for p in it[1:5]]))
                    elif it[0] == "qu":
                        q = it[1]
                        items.append(("qu", pt(q.ul), pt(q.ur), pt(q.lr), pt(q.ll)))
                r = pymupdf.Rect(d["rect"]) * R
                r.normalize()
                out.append({"items": items, "width": (d.get("width") or 0) / W, "stroke": d.get("color"),
                            "fill": d.get("fill"), "dashes": d.get("dashes"),
                            "bbox": [r.x0 / W, r.y0 / H, r.x1 / W, r.y1 / H]})
        except Exception:  # noqa: BLE001
            out = []
    meta["_pdf_paths"] = out
    return out


def words(meta, **ocr_kw) -> list[dict]:
    """The sheet's words: the PDF's exact vector words when it has a text layer, else tesseract OCR."""
    if meta.get("words"):
        return meta["words"]
    return ocr_words(meta, **ocr_kw)


def classify(image_path: str, model: str = "haiku") -> dict:
    """One cheap vision call on a downscaled view of the sheet (~$0.002): kind, title, sheet number, scale."""
    from PIL import Image

    from bp.generic import llm

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        im.thumbnail((1568, 1568))
    r = llm.ask(CLASSIFY_PROMPT, [im], model=model, tag="sheets-classify", timeout=60)
    d = llm.parse_json(r["text"]) or {}
    if not isinstance(d, dict):
        d = {}
    d["cost_usd"] = r.get("cost_usd", 0.0)
    if d.get("kind") not in KINDS:
        d["kind"] = "other" if not d.get("kind") else str(d["kind"]).lower()[:20]
    return d


def kw_score(meta, kind: str) -> float:
    """Helper for detect(): 1.0 when the classifier said `kind`, plus a little for keyword hits in title/text."""
    s = 0.8 if meta.get("kind") == kind else 0.0
    blob = f"{meta.get('title', '')} {meta.get('text', '')[:20000]}"
    hits = len(re.findall(_KW.get(kind, r"^$"), blob, re.I))
    return min(1.0, s + min(0.2, 0.04 * hits))


def build_meta(path: str, page: int = 0, cache_dir: str | Path | None = None, do_classify: bool = True) -> dict:
    """meta for detect()/answer() (see module doc). Cached in memory and in <cache_dir>/sheet_meta_p<page>.json
    (default: the file's own folder, i.e. the upload folder)."""
    path = str(path)
    cache_dir = Path(cache_dir or Path(path).parent)
    key = (path, page)
    with _meta_lock:
        if key in _meta_mem:
            return _meta_mem[key]
    f = cache_dir / f"sheet_meta_p{page}.json"
    meta = None
    if f.exists():
        try:
            meta = json.loads(f.read_text())
        except json.JSONDecodeError:
            meta = None
    if meta is None or (do_classify and "classify" not in meta):
        img, w, h = _image_for(path, page, cache_dir)
        meta = meta or {}
        meta.update({"path": path, "page": page, "image": img, "w": w, "h": h, "text": _pdf_text(path, page)})
        # a small raster (a screenshot, a phone-sized export): tags and small symbols are at the edge of legibility,
        # so specialists should OCR it upscaled and lower their confidence on reads of small text / symbols
        meta["low_res"] = max(w, h) < 3000 and not path.lower().endswith(".pdf")
        pw = pdf_words(path, page)
        if len(pw) >= 20:
            meta["words"], meta["text_source"] = pw, "pdf"
        else:
            meta["words"], meta["text_source"] = [], "ocr"
        if do_classify and os.environ.get("BP_SHEET_CLASSIFY", "1") == "1":
            c = classify(img)
            meta["classify"] = c
            meta["kind"] = c.get("kind")
            meta["title"] = " ".join(str(c.get(k) or "") for k in ("title", "sheet_number")).strip()
            meta["scale"] = c.get("scale") or ""
            meta["units"] = c.get("units") or "unknown"
            meta["cost_usd"] = c.get("cost_usd", 0.0)
        try:
            f.write_text(json.dumps(meta))
        except OSError:
            pass
    meta.setdefault("kind", None)
    meta.setdefault("title", "")
    with _meta_lock:
        _meta_mem[key] = meta
    return meta


# ------------------------------------------------------------------------------------------------- OCR (shared)
def ocr_words(meta, region=None, scale: float = 1.0, psm: int = 11, min_conf: float = 30) -> list[dict]:
    """Tesseract words of the sheet image (or of a region [x0,y0,x1,y1] normalised), cached per call signature.
    Returns [{"text", "bbox": [x0,y0,x1,y1] normalised to the full image, "conf"}]. [] if tesseract is missing.
    Upscale (scale=2) helps on ~2000 px screenshots; large images are processed in tiles of <= 4000 px."""
    if meta.get("words"):  # a PDF text layer: exact, no OCR needed
        x0, y0, x1, y1 = region or (0, 0, 1, 1)
        return [w for w in meta["words"] if x0 <= (w["bbox"][0] + w["bbox"][2]) / 2 <= x1
                and y0 <= (w["bbox"][1] + w["bbox"][3]) / 2 <= y1]
    if not shutil.which("tesseract"):
        return []
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    cache = meta.setdefault("_ocr", {})
    ck = f"{region}|{scale}|{psm}"
    if ck not in cache:
        with _meta_lock:
            lock = meta.setdefault("_ocr_locks", {}).setdefault(ck, threading.Lock())
        with lock:  # one OCR per sheet and signature, however many questions (or the upload warm-up) ask at once
            if ck not in cache:
                cache[ck] = _ocr_run(meta, region, scale, psm)
    return [w for w in cache[ck] if w["conf"] >= min_conf]


def _ocr_run(meta, region, scale, psm):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(meta["image"]).convert("L")
    W, H = im.size
    x0, y0, x1, y1 = region or (0, 0, 1, 1)
    box = (round(x0 * W), round(y0 * H), round(x1 * W), round(y1 * H))
    crop = im.crop(box)
    if scale != 1.0:
        crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.LANCZOS)
    T = 4000
    import concurrent.futures as cf
    import tempfile

    def one(tx, ty):
        tile = crop.crop((tx, ty, min(crop.width, tx + T), min(crop.height, ty + T)))
        with tempfile.NamedTemporaryFile(suffix=".png") as tf:
            tile.save(tf.name)
            try:  # one thread per tesseract: the tiles run side by side instead
                out = subprocess.run(["tesseract", tf.name, "-", "--psm", str(psm), "tsv"], capture_output=True,
                                     text=True, timeout=180, env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout
            except subprocess.TimeoutExpired:
                return []
        res = []
        for line in out.splitlines()[1:]:
            p = line.split("\t")
            if len(p) < 12 or not p[11].strip():
                continue
            left, top, wd, ht, conf = int(p[6]), int(p[7]), int(p[8]), int(p[9]), float(p[10])
            gx0 = box[0] + (tx + left) / scale
            gy0 = box[1] + (ty + top) / scale
            res.append({"text": p[11].strip(), "conf": conf,
                        "bbox": [gx0 / W, gy0 / H, (gx0 + wd / scale) / W, (gy0 + ht / scale) / H]})
        return res

    xs = list(range(0, max(1, crop.width - 200), T - 200)) or [0]
    ys = list(range(0, max(1, crop.height - 200), T - 200)) or [0]
    with cf.ThreadPoolExecutor(min(8, len(xs) * len(ys))) as ex:  # a 10000 px sheet: ~9 tiles at once
        words = [w for part in ex.map(lambda t: one(*t), [(x, y) for y in ys for x in xs]) for w in part]
    # tiles overlap: drop duplicates (same text, nearly the same box)
    seen, uniq = set(), []
    for w in words:
        k = (w["text"], round(w["bbox"][0] * 400), round(w["bbox"][1] * 400))
        if k not in seen:
            seen.add(k)
            uniq.append(w)
    return uniq


def warm_upload(meta):
    """At upload, in the background: the shared OCR, then the claiming module's own warm(meta) if it has one (a
    piping module reading tags with vision, a room segmentation), so the judge's first question finds them ready."""
    def run():
        try:
            n, m, _ = best(meta)
            if m is not None and callable(getattr(m, "warm", None)):
                m.warm(meta)
        except Exception:  # noqa: BLE001
            log.exception("warm-up failed")

    warm(meta)
    threading.Thread(target=run, daemon=True).start()


def warm(meta):
    """Start the default OCR of a raster sheet in the background (called once per upload), so the first question
    does not wait for it; the specialists share the result through ocr_words' cache."""
    if meta.get("words") or not meta.get("image") or not shutil.which("tesseract"):
        return
    sc = 2.0 if max(meta.get("w", 0), meta.get("h", 0)) < 3000 else 1.0
    threading.Thread(target=lambda: ocr_words(meta, scale=sc, min_conf=0), daemon=True).start()


def ocr_lines(words: list[dict], ytol: float = 0.5) -> list[dict]:
    """Group OCR words into text lines: [{"text", "bbox", "words"}], top to bottom, left to right."""
    ws = sorted(words, key=lambda w: (w["bbox"][1], w["bbox"][0]))
    lines: list[dict] = []
    for w in ws:
        h = w["bbox"][3] - w["bbox"][1]
        cy = (w["bbox"][1] + w["bbox"][3]) / 2
        for ln in lines:
            lh = ln["bbox"][3] - ln["bbox"][1]
            lcy = (ln["bbox"][1] + ln["bbox"][3]) / 2
            gap = w["bbox"][0] - ln["bbox"][2]
            if abs(cy - lcy) < ytol * max(h, lh) and -0.002 < gap < 3 * max(h, lh):
                ln["words"].append(w)
                b = ln["bbox"]
                ln["bbox"] = [min(b[0], w["bbox"][0]), min(b[1], w["bbox"][1]), max(b[2], w["bbox"][2]),
                              max(b[3], w["bbox"][3])]
                break
        else:
            lines.append({"words": [w], "bbox": list(w["bbox"])})
    for ln in lines:
        ln["text"] = " ".join(x["text"] for x in sorted(ln["words"], key=lambda x: x["bbox"][0]))
    return sorted(lines, key=lambda ln: (ln["bbox"][1], ln["bbox"][0]))
