"""Piping-plan specialist (mechanical / fuel / process piping sheets, e.g. USACE "PIPING PLAN" M-101A).

Reads the sheet into positioned text once (vector PDF: the text layer; raster: tesseract on a few preprocessed
variants, plus a tiled Claude Haiku vision transcription, merged), caches it per file, and then answers with
plain code:

  * counts by tag family ("How many fuel pumps?" -> FP-1..FP-5 = 5 distinct tags), distinct tags vs label
    instances (PS-12 is printed 7 times: one support type, seven labels), numbering gaps reported, never filled
  * pipe sizes on the sheet ('What sizes of pipe ...' -> 1" 2" 3" 4" 6" 8" 10" 12" 16" with counts)
  * the size of a named run ('suction header' -> 16"), where a label / tag / run is (with the sheet grid square)
  * referenced sheets and detail callouts (M-303, S-101, MS513 ...), notes lookup ('What does note 4 say?')
  * anything else on the sheet's text: one Haiku call over the read text, citing the lines it used

Every counted / read item comes back as a numbered evidence box, so a human checks the answer in seconds.
Readers, cost and misses are stated in the explanation; OCR can miss labels, so counts say "found N".
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

METHOD = "sheets-piping"
CACHE = Path(os.environ.get("BP_PIPING_CACHE", "cache/sheets/piping"))
VOTES = max(1, int(os.environ.get("BP_PIPING_VOTES", "1") or 1))  # readings of each tile (see _vision_items)
VOTE_MIN = max(1, int(os.environ.get("BP_PIPING_VOTE_MIN", "2") or 2))
VISION = os.environ.get("BP_PIPING_VISION", "1") != "0"  # the Haiku tile transcription (~$0.03-0.1 per sheet)
MAX_TILES = 40
FAMSCAN_TILES = 24
_lock = threading.Lock()
_mem: dict = {}

# ------------------------------------------------------------------------------------------------- glossary
# family code -> (singular, plural); what the abbreviations mean on fuel / process piping plans
FAMILIES = {
    "FP": ("fuel pump", "fuel pumps"),
    "P": ("pump", "pumps"),
    "CV": ("check valve", "check valves"),
    "NSCV": ("non-surge check valve", "non-surge check valves"),
    "FTP": ("fuel transfer pump", "fuel transfer pumps"),
    "PCV": ("pressure control valve", "pressure control valves"),
    "HLV": ("high level valve", "high level valves"),
    "FSCV": ("filter separator control valve", "filter separator control valves"),
    "BPCV": ("back-pressure control valve", "back-pressure control valves"),
    "FSI": ("issue filter separator", "issue filter separators"),
    "FSR": ("receipt filter separator", "receipt filter separators"),
    "FS": ("filter separator / flow switch", "filter separators / flow switches"),
    "PS": ("pipe support", "pipe supports"),
    "PIT": ("pressure indicating transmitter", "pressure indicating transmitters"),
    "DPT": ("differential pressure transmitter", "differential pressure transmitters"),
    "PT": ("pressure transmitter", "pressure transmitters"),
    "PG": ("pressure gauge", "pressure gauges"),
    "MAV": ("manual air vent", "manual air vents"),
    "IF": ("insulating flange", "insulating flanges"),
    "TK": ("tank", "tanks"),
    "V": ("valve", "valves"),
    "HV": ("hand valve", "hand valves"),
    "BV": ("ball valve", "ball valves"),
    "GV": ("gate valve", "gate valves"),
    "FE": ("flow element", "flow elements"),
    "FIT": ("flow indicating transmitter", "flow indicating transmitters"),
    "FM": ("flow meter", "flow meters"),
    "TE": ("temperature element", "temperature elements"),
    "TI": ("temperature indicator", "temperature indicators"),
    "LS": ("level switch", "level switches"),
    "LT": ("level transmitter", "level transmitters"),
    "STR": ("strainer", "strainers"),
}
# families printed without a number: counted as label instances
UNNUMBERED = {"PG", "MAV", "IF", "BPCV"}
# question wording -> families (first match wins; longest phrases first)
GLOSSARY = [
    (r"filter[- ]?separator control valve|fscv", ["FSCV"]),
    (r"back[- ]?pressure control valve|bpcv", ["BPCV"]),
    (r"pressure control valve|pcv\b", ["PCV"]),
    (r"control valve", ["FSCV", "PCV"]),
    (r"check valve|non[- ]?surge", ["CV", "NSCV"]),
    (r"issue filter|fsi\b", ["FSI"]),
    (r"receipt filter|fsr\b", ["FSR"]),
    (r"filter[- ]?separator|filter vessel|filters?\b", ["FSI", "FSR"]),
    (r"fuel transfer pump", ["FTP"]),
    (r"fuel pump|pump", ["FP", "FTP", "P"]),
    (r"pipe support|support|hanger", ["PS"]),
    (r"differential pressure|dpt\b", ["DPT"]),
    (r"pressure (?:indicating )?transmitter|pit\b|transmitter", ["PIT"]),
    (r"pressure gauge|gauge|gage", ["PG"]),
    (r"air vent|vent\b|mav\b", ["MAV"]),
    (r"insulating flange|isolating flange|dielectric", ["IF"]),
    (r"flow meter", ["FM"]),
    (r"strainer", ["STR"]),
    (r"tank", ["TK"]),
]
NPS = {"1/2", "3/4", "1", "1-1/4", "1-1/2", "2", "2-1/2", "3", "3-1/2", "4", "5", "6", "8", "10", "12", "14", "16",
       "18", "20", "24", "30", "36", "42", "48"}
DN = {15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300, 350, 400, 450, 500, 600, 700, 750, 800, 900}
_SIZE_MM = re.compile(r"(?<![\d.])(\d{2,3})\s?mm\b", re.I)
DISCIPLINES = r"MS|ME|FP|FA|M|S|A|E|P|C|G|L|T|I"

# ============================================================================================ reading the sheet


def _sha(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def _pdf_items(path: str, page: int) -> list[dict]:
    """Text-layer lines of a vector PDF page (normalised to the rendered page), [] when there is no text layer."""
    try:
        import pymupdf
    except ImportError:
        return []
    try:
        pg = pymupdf.open(path)[page]
    except Exception:  # noqa: BLE001
        return []
    m = pg.rotation_matrix
    W, H = pg.rect.width, pg.rect.height
    out = []
    for blk in pg.get_text("dict").get("blocks", []):
        for ln in blk.get("lines", []):
            spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            txt = " ".join(s["text"].strip() for s in spans)
            r = pymupdf.Rect(ln["bbox"]) * m
            r.normalize()
            out.append({"text": re.sub(r"\s+", " ", txt), "bbox": [r.x0 / W, r.y0 / H, r.x1 / W, r.y1 / H],
                        "src": "pdf", "conf": 100.0})
    return out


def _tess_run(img, scale: float, psm: int = 11) -> list[dict]:
    """Tesseract words of a PIL greyscale image (already preprocessed), boxes normalised to the unscaled image."""
    W, H = img.width / scale, img.height / scale
    T = 4000
    words = []
    for ty in range(0, img.height, T - 300):
        for tx in range(0, img.width, T - 300):
            tile = img.crop((tx, ty, min(img.width, tx + T), min(img.height, ty + T)))
            with tempfile.NamedTemporaryFile(suffix=".png") as tf:
                tile.save(tf.name)
                try:
                    out = subprocess.run(["tesseract", tf.name, "-", "--psm", str(psm), "tsv"], capture_output=True,
                                         text=True, timeout=300).stdout
                except subprocess.TimeoutExpired:
                    out = ""
            for line in out.splitlines()[1:]:
                p = line.split("\t")
                if len(p) < 12 or not p[11].strip():
                    continue
                left, top, wd, ht, conf = int(p[6]), int(p[7]), int(p[8]), int(p[9]), float(p[10])
                x0, y0 = (tx + left) / scale, (ty + top) / scale
                words.append({"text": p[11].strip(), "conf": conf, "line": (tx, ty, p[2], p[3], p[4]),
                              "bbox": [x0 / W, y0 / H, (x0 + wd / scale) / W, (y0 + ht / scale) / H]})
            if tx + T >= img.width:
                break
        if ty + T >= img.height:
            break
    return words


def _variants(image_path: str):
    """(name, preprocessed greyscale PIL image, scale): raw upscale, and with long straight lines removed
    (underlined tags like CV-1 / FSCV-3 and leader lines touching text defeat tesseract otherwise)."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    g = Image.open(image_path).convert("L")
    s = max(1.0, min(3.0, 6000 / max(g.size)))
    out = [("raw", g.resize((round(g.width * s), round(g.height * s)), Image.LANCZOS), s)]
    try:
        import cv2
        import numpy as np

        for sv in sorted({s, min(4.0, s * 4 / 3)}):
            u = np.asarray(g.resize((round(g.width * sv), round(g.height * sv)), Image.LANCZOS))
            ink = (u < 170).astype(np.uint8) * 255
            # longer than ~2 letter heights: ~0.6 % of the sheet (a fixed pixel length ate the letters of hi-res scans)
            L = max(15, round(0.006 * max(g.size) * sv))
            hl = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1)))
            vl = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, L)))
            clean = cv2.subtract(ink, cv2.bitwise_or(hl, vl))
            out.append((f"nolines@{sv:g}", Image.fromarray(255 - clean), sv))
    except ImportError:
        pass
    return out


def _group_lines(words: list[dict]) -> list[dict]:
    """Tesseract words -> text lines (same tesseract line, or same baseline and a small gap)."""
    by = defaultdict(list)
    for w in words:
        by[w["line"]].append(w)
    lines = []
    for ws in by.values():
        ws.sort(key=lambda w: w["bbox"][0])
        cur = [ws[0]]
        for w in ws[1:]:
            h = max(cur[-1]["bbox"][3] - cur[-1]["bbox"][1], w["bbox"][3] - w["bbox"][1])
            if w["bbox"][0] - cur[-1]["bbox"][2] > 2.5 * h:
                lines.append(cur)
                cur = [w]
            else:
                cur.append(w)
        lines.append(cur)
    out = []
    for ws in lines:
        text, spans, pos = "", [], 0
        for w in ws:
            if text:
                text += " "
            spans.append((len(text), len(text) + len(w["text"]), w["bbox"]))
            text += w["text"]
        out.append({"text": text, "bbox": _union([w["bbox"] for w in ws]), "conf": min(w["conf"] for w in ws),
                    "spans": spans})
    return out


def _tess_items(image_path: str) -> list[dict]:
    if not shutil.which("tesseract"):
        return []
    vs = _variants(image_path)
    with ThreadPoolExecutor(min(4, len(vs))) as ex:
        res = list(ex.map(lambda v: (v[0], _tess_run(v[1], v[2])), vs))
    items = []
    for name, words in res:
        for ln in _group_lines([w for w in words if w["conf"] >= 0]):
            ln["src"] = f"tesseract:{name}"
            items.append(ln)
    return items


VISION_PROMPT = """This is one tile of a piping plan (construction drawing), {w}x{h} pixels.
Transcribe EVERY piece of printed text in it: tags (e.g. CV-1, PS-12, FSCV-3, FP-2, PIT 1, DPT-1 & 2), pipe sizes
(e.g. 8", 16" SUCTION HEADER, 10" X 12" REDUCER), abbreviations (PG, MAV, IF), callout bubbles (e.g. E1 above M-303),
notes, titles. One line per text line: the text line's box as four integer pixel coordinates in this tile image
(left,top,right,bottom), a bar, then the text, e.g.
412,88,470,104|CV-1
120,300,388,318|16" SUCTION HEADER
Write the numbers themselves, never the letters x0,y0,x1,y1. Text exactly as printed (keep inch marks "). Skip text
cut off at the tile edge. No other output."""


SEND_PX = 1072  # tile side sent to the model: <= ~1.15 MP, so the API never resizes it (boxes stay in our frame)


def _vision_tiles(W: int, H: int):
    """Tile grid in source pixels and the resize factor to SEND_PX: ~536 px tiles upscaled x2 on small (~2000 px)
    screenshots; on large renders bigger tiles scaled down so the sheet fits in MAX_TILES calls."""
    t = SEND_PX // 2
    while True:
        nx, ny = max(1, math.ceil((W - t * 0.12) / (t * 0.88))), max(1, math.ceil((H - t * 0.12) / (t * 0.88)))
        if nx * ny <= MAX_TILES:
            break
        t = int(t * 1.15)
    t = min(t, max(W, H))
    out = []
    for j in range(ny):
        for i in range(nx):
            x0 = 0 if nx == 1 else round(i * (W - t) / (nx - 1))
            y0 = 0 if ny == 1 else round(j * (H - t) / (ny - 1))
            out.append((max(0, x0), max(0, y0), min(W, x0 + t), min(H, y0 + t)))
    return out, SEND_PX / t


def _vision_items(image_path: str) -> tuple[list[dict], float]:
    from PIL import Image

    from bp.generic import llm

    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(image_path).convert("RGB")
    W, H = im.size
    tiles, up = _vision_tiles(W, H)

    def one(job):
        tb, _pass = job
        crop = im.crop(tb)
        if up != 1.0:
            crop = crop.resize((round(crop.width * up), round(crop.height * up)), Image.LANCZOS)
        got, spent = [], 0.0
        for attempt in range(3):  # an empty / unparseable reply (it happens on dense tiles) is retried
            r = llm.ask(VISION_PROMPT.format(w=crop.width, h=crop.height), [crop], model="haiku", think="low",
                        system="You transcribe drawings exactly. Output only the requested lines.", timeout=180,
                        tag="sheets-piping-ocr")
            spent += float(r.get("cost_usd") or 0.0)
            for line in (r.get("text") or "").splitlines():
                m = re.match(r"\s*[\[(]?\s*(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)[\s,]+"
                             r"(-?\d+(?:\.\d+)?)\s*[\])]?\s*[|:\t]\s*(.+?)\s*$", line)
                if not m:
                    continue
                a, b, c, d = (float(m.group(k)) / up for k in range(1, 5))
                txt = m.group(5).strip().strip("`").strip()
                if not txt:
                    continue
                bb = [(tb[0] + min(a, c)) / W, (tb[1] + min(b, d)) / H, (tb[0] + max(a, c)) / W,
                      (tb[1] + max(b, d)) / H]
                bb = [min(max(v, 0.0), 1.0) for v in bb]
                got.append({"text": txt, "bbox": bb, "src": "vision", "conf": 80.0,
                            "tile": [tb[0] / W, tb[1] / H, tb[2] / W, tb[3] / H]})
            if got:
                break
        return got, spent

    # the model can't be run at temperature 0 (Haiku 5.5 rejects sampling parameters): on a scan one reading of a
    # tile misses a tag another one gets (FSCV 6 / 6 / 7, PG 18 / 20 over three cold runs of the same file). Each
    # tile is read VOTES times at once and a tag kept when at least VOTE_MIN of the readings agree on it.
    jobs = [(tb, k) for k in range(VOTES) for tb in tiles]
    with ThreadPoolExecutor(min(24, len(jobs))) as ex:  # one wave: each call is ~7 s of waiting on the API
        res = list(ex.map(one, jobs))
    cost = sum(c for _, c in res)
    if VOTES == 1:
        return [it for g, _ in res for it in g], cost
    by_tile: dict = {}
    for (tb, k), (g, _) in zip(jobs, res):
        by_tile.setdefault(tb, []).append(g)
    out = []
    for tb, reads in by_tile.items():
        out += _vote(reads, W, H)
    return out, cost


def _vote(reads: list[list[dict]], W: int, H: int) -> list[dict]:
    """Items read in at least VOTE_MIN of one tile's readings (same text, folded, at about the same place); the
    first reading's box. A reading that came back empty (a failed call) doesn't vote."""
    reads = [r for r in reads if r]
    if not reads:
        return []
    need = min(VOTE_MIN, len(reads))
    tol = 0.006  # share of the sheet: two boxes of one tag land within a few characters of each other
    clusters: list[dict] = []
    for ri, r in enumerate(reads):
        for it in r:
            key = _norm_txt(it["text"])
            cx, cy = (it["bbox"][0] + it["bbox"][2]) / 2, (it["bbox"][1] + it["bbox"][3]) / 2
            c = next((c for c in clusters if c["key"] == key and ri not in c["reads"]
                      and abs(c["cx"] - cx) < tol + (it["bbox"][2] - it["bbox"][0]) / 2 and abs(c["cy"] - cy) < tol * W / H + (it["bbox"][3] - it["bbox"][1]) / 2),
                     None)
            if c is None:
                clusters.append({"key": key, "cx": cx, "cy": cy, "item": it, "reads": {ri}})
            else:
                c["reads"].add(ri)
    out = []
    for c in clusters:
        if len(c["reads"]) >= need:
            it = dict(c["item"])
            it["votes"] = f"{len(c['reads'])}/{len(reads)}"
            out.append(it)
    return out


def _norm_txt(t: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _canon(t).upper().replace("O", "0"))


def _calibrate(vis: list[dict], tess: list[dict]) -> list[dict]:
    """Vision boxes sometimes come back in the wrong frame for a whole tile (e.g. in the un-upscaled size). Per tile,
    pair vision lines with the unique tesseract line of the same text inside that tile and fit a scale about the
    tile origin per axis; apply it when >= 3 pairs agree on a clearly wrong scale."""
    if not tess:
        return vis
    tidx = defaultdict(list)
    for t in tess:
        k = _norm_txt(t["text"])
        if len(k) >= 2:
            tidx[k].append(t)
    by_tile = defaultdict(list)
    for v in vis:
        by_tile[tuple(v.get("tile") or ())].append(v)
    for tile, vs in by_tile.items():
        if not tile:
            continue
        tx0, ty0, tx1, ty1 = tile
        rx, ry = [], []
        for v in vs:
            k = _norm_txt(v["text"])
            if len(k) < 2:
                continue
            cand = {(round(c["bbox"][0], 3), round(c["bbox"][1], 3)): c for c in tidx.get(k, [])
                    if tx0 <= _center(c["bbox"])[0] <= tx1 and ty0 <= _center(c["bbox"])[1] <= ty1}
            if len(cand) != 1:
                continue
            c = next(iter(cand.values()))
            (vx, vy), (cx, cy) = _center(v["bbox"]), _center(c["bbox"])
            if vx - tx0 > 0.02 * (tx1 - tx0):
                rx.append((cx - tx0) / (vx - tx0))
            if vy - ty0 > 0.02 * (ty1 - ty0):
                ry.append((cy - ty0) / (vy - ty0))

        def fit(r):
            if len(r) < 3:
                return 1.0
            r = sorted(r)
            m = r[len(r) // 2]
            agree = sum(abs(x - m) < 0.08 * m for x in r)
            return m if abs(m - 1) > 0.12 and agree >= max(3, 0.6 * len(r)) else 1.0

        ax, ay = fit(rx), fit(ry)
        if ax != 1.0 or ay != 1.0:
            for v in vs:
                b = v["bbox"]
                v["bbox"] = [tx0 + (b[0] - tx0) * ax, ty0 + (b[1] - ty0) * ay, tx0 + (b[2] - tx0) * ax,
                             ty0 + (b[3] - ty0) * ay]
                v["calibrated"] = [round(ax, 3), round(ay, 3)]
    return vis


def _scan_image(path: str, page: int) -> str | None:
    """A scanned PDF page (one full-page raster, no rotation): the embedded image at its own resolution. Re-rendering
    it resamples the scan (blurrier letters for OCR); its normalised coordinates are the page's."""
    try:
        import pymupdf

        pg = pymupdf.open(path)[page]
        if pg.rotation:
            return None
        imgs = pg.get_images(full=True)
        if len(imgs) != 1:
            return None
        rects = pg.get_image_rects(imgs[0][0])
        if len(rects) != 1:
            return None
        r, pr = rects[0], pg.rect
        if abs(r.x0 - pr.x0) > 0.01 * pr.width or abs(r.x1 - pr.x1) > 0.01 * pr.width or \
                abs(r.y0 - pr.y0) > 0.01 * pr.height or abs(r.y1 - pr.y1) > 0.01 * pr.height:
            return None
        CACHE.mkdir(parents=True, exist_ok=True)
        out = CACHE / f"{_sha(path)}_p{page}_scan.png"
        if not out.exists():
            pix = pymupdf.Pixmap(pg.parent, imgs[0][0])
            if pix.n - pix.alpha >= 4:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            if max(pix.width, pix.height) < 1000:
                return None
            pix.save(str(out))
        return str(out)
    except Exception:  # noqa: BLE001
        return None


def _small(image: str) -> bool:
    """A raster under 3000 px on its long side (the contract's low_res)."""
    try:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = None
        with Image.open(image) as im:
            return max(im.size) < 3000
    except Exception:  # noqa: BLE001
        return False


def _image_of(path: str, meta: dict) -> str | None:
    if path.lower().endswith(".pdf"):
        scan = _scan_image(path, int(meta.get("page", 0) or 0))
        if scan:
            return scan
    if meta.get("image"):
        return meta["image"]
    ext = path.rsplit(".", 1)[-1].lower()
    if ext in ("png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"):
        return path
    try:
        import pymupdf

        CACHE.mkdir(parents=True, exist_ok=True)
        out = CACHE / f"{_sha(path)}_p{meta.get('page', 0)}.png"
        if not out.exists():
            pg = pymupdf.open(path)[meta.get("page", 0)]
            z = min(200 / 72, 9000 / max(pg.rect.width, pg.rect.height))
            pg.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False).save(str(out))
        return str(out)
    except Exception:  # noqa: BLE001
        return None


def _skew_deg(g) -> float:
    """Skew of a scanned sheet in degrees (median angle of long near-horizontal strokes), 0 when unsure."""
    import cv2
    import numpy as np

    sm = cv2.resize(g, None, fx=1500 / max(g.shape), fy=1500 / max(g.shape), interpolation=cv2.INTER_AREA)
    edges = cv2.Canny(sm, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 1800, threshold=120, minLineLength=sm.shape[1] // 8, maxLineGap=4)
    if lines is None:
        return 0.0
    ang = [math.degrees(math.atan2(y2 - y1, x2 - x1)) for x1, y1, x2, y2 in lines.reshape(-1, 4).tolist()]
    ang = [a for a in ang if abs(a) < 5]
    if len(ang) < 5:
        return 0.0
    return float(np.median(ang))


def _clean_scan(image_path: str):
    """A poor scan (yellowed / grey paper, low contrast, skew): contrast-stretched to black on white and deskewed,
    saved next to the cache. Returns (clean image path, inverse map for normalised boxes) or (None, None) when the
    sheet is already clean, straight paper."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None, None
    g = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if g is None:
        return None, None
    paper, dark = np.percentile(g[::4, ::4], [50, 0.5])
    ang = _skew_deg(g)
    if paper > 235 and dark < 60 and abs(ang) < 0.3:
        return None, None
    st = np.clip((g.astype(np.float32) - dark) * 255.0 / max(paper - dark - 10, 30), 0, 255).astype(np.uint8)
    H, W = g.shape
    M = None
    if abs(ang) >= 0.3:
        M = cv2.getRotationMatrix2D((W / 2, H / 2), ang, 1.0)
        st = cv2.warpAffine(st, M, (W, H), flags=cv2.INTER_CUBIC, borderValue=255)
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{_sha(image_path)}_clean.png"
    cv2.imwrite(str(out), st)
    if M is None:
        return str(out), None
    Minv = cv2.invertAffineTransform(M)

    def back(b):
        pts = np.array([[b[0] * W, b[1] * H], [b[2] * W, b[1] * H], [b[0] * W, b[3] * H], [b[2] * W, b[3] * H]])
        q = pts @ Minv[:, :2].T + Minv[:, 2]
        return [max(0.0, q[:, 0].min() / W), max(0.0, q[:, 1].min() / H), min(1.0, q[:, 0].max() / W),
                min(1.0, q[:, 1].max() / H)]
    return str(out), back


def read_sheet(path: str, meta: dict | None = None, vision: bool | None = None) -> dict:
    """{"items": [{"text", "bbox", "src", "conf"}], "readers": [...], "cost_usd": first-read cost} (cached)."""
    meta = meta or {}
    page = int(meta.get("page", 0) or 0)
    key = f"{_sha(path)}_p{page}" + (f"_v{VOTES}{VOTE_MIN}" if VOTES > 1 else "")
    with _lock:
        if key in _mem:
            return _mem[key]
    f = CACHE / f"{key}.json"
    if f.exists():
        d = json.loads(f.read_text())
        d["cost_usd_now"] = 0.0
        vis = [it for it in d["items"] if it["src"] == "vision"]
        if vis:  # (idempotent) older caches were stored before the per-tile calibration existed
            _calibrate(vis, [it for it in d["items"] if it["src"].startswith("tesseract")])
        d["image"] = None if "pdf text layer" in d["readers"] else _image_of(path, meta)
        with _lock:
            _mem[key] = d
        return d
    items, readers, cost = [], [], 0.0
    if path.lower().endswith(".pdf"):
        items = _pdf_items(path, page)
        if len(items) >= 30:
            readers.append("pdf text layer")
        else:
            items = []
    if not items and len(meta.get("words") or []) >= 30:  # the caller's exact vector words (bp.sheets.build_meta)
        from bp.sheets import ocr_lines

        ws = [dict(w, conf=w.get("conf", 100.0)) for w in meta["words"]]
        # rotated title-block text would be glued onto the horizontal lines next to it: keep those words apart
        vert = [w for w in ws if len(w["text"]) > 2 and (w["bbox"][3] - w["bbox"][1]) > 1.5 * (w["bbox"][2] - w["bbox"][0])]
        for ln in ocr_lines([w for w in ws if w not in vert]) + [{"text": w["text"], "bbox": w["bbox"]} for w in vert]:
            items.append({"text": ln["text"], "bbox": list(ln["bbox"]), "src": "pdf", "conf": 100.0})
        readers.append("pdf text layer")
    if not items:
        img = _image_of(path, meta)
        src_img, back = img, None
        if img:
            clean, back = _clean_scan(img)
            if clean:  # both readers see the cleaned scan; their boxes are mapped back to the uploaded image
                img = clean
                readers.append("scan cleaned (contrast" + (", deskew)" if back else ")"))
        if img:
            # the Haiku tile read waits on the network, tesseract on the CPU: run them side by side (on a 4-core VM
            # one after the other took ~80 s, too long for a first question)
            with ThreadPoolExecutor(1) as ex:
                vf = ex.submit(_vision_items, img) if (VISION if vision is None else vision) else None
                t = _tess_items(img)
                v, c = vf.result() if vf is not None else ([], 0.0)
            if t:
                readers.append("tesseract (3 variants)")
            items += t
            if vf is not None:
                cost += c
                if v:
                    readers.append(f"Claude Haiku tile transcription (${c:.3f})")
                items += _calibrate(v, t)
        if back:
            for it in items:
                it["bbox"] = back(it["bbox"])
                if it.get("spans"):
                    it["spans"] = [(a, b_, back(bb)) for a, b_, bb in it["spans"]]
                it.pop("tile", None)
        img = src_img
    d = {"items": items, "readers": readers, "cost_usd": round(cost, 5)}
    if items:
        CACHE.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d))
    d["cost_usd_now"] = cost
    d["image"] = None if "pdf text layer" in readers else _image_of(path, meta)
    with _lock:
        _mem[key] = d
    return d


# ================================================================================================== parsing
def _union(bbs):
    return [min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs)]


def _sub_box(item: dict, a: int, b: int) -> list:
    """Box of characters [a, b) of an item's text: the words they fall in (tesseract), else a proportional slice."""
    if item.get("spans"):
        bbs = [bb for s, e, bb in item["spans"] if s < b and e > a]
        if bbs:
            return _union(bbs)
    x0, y0, x1, y1 = item["bbox"]
    n = max(1, len(item["text"]))
    if (y1 - y0) > 2.5 * (x1 - x0) and n > 3:  # vertical text: slice along y (reads bottom to top)
        return [x0, y1 - (y1 - y0) * b / n, x1, y1 - (y1 - y0) * a / n]
    return [x0 + (x1 - x0) * a / n, y0, x0 + (x1 - x0) * b / n, y1]


_DIG = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "i": "1", "t": "1", "|": "1",
                      "!": "1", "]": "1", "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2", "G": "6", "g": "9"})


def clean(text: str) -> str:
    """For display: OCR's degree sign after a size is an inch mark; stray dashes trimmed."""
    t = re.sub(r"(\d)\s?[°\u00ba]", r'\1"', text)
    return re.sub(r"^[\s\-\u2014\u2013_~|=]+|[\s\-\u2014\u2013_~|=]+$", "", t)


def _canon(text: str) -> str:
    t = text.replace("”", '"').replace("“", '"').replace("''", '"').replace("″", '"')
    t = t.replace("–", "-").replace("—", "-")
    return t


_FAMS = sorted(set(FAMILIES) - {"P", "V"}, key=len, reverse=True)
# known families: separator optional (OCR drops / garbles it); OCR'd prefixes ("ESCV", "Cv", "OPT") fixed below
_TAG_KNOWN = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(_FAMS) + r"|ESCV|FSCv|Fscv|Cv|cv|OPT|P1T|PlT)"
                        r"\s?[-.–]?\s?([0-9OoIlt|SZB]{1,3})(?![0-9A-Za-z\"])"
                        r"((?:\s?(?:&|AND|,)\s?\d{1,3})*)", re.I)
# any other LETTERS-NUMBER tag needs a hyphen (avoids 'NOTE 16', 'NO. 1')
_TAG_GEN = re.compile(r"(?<![A-Za-z0-9-])([A-Z]{1,4})-(\d{1,3}[A-Z]?)(?![0-9A-Za-z\"'-])")
_PREFIX_FIX = {"ESCV": "FSCV", "CV": "CV", "OPT": "DPT", "P1T": "PIT", "PLT": "PIT"}
_SHEET = re.compile(r"(?<![A-Za-z0-9])(" + DISCIPLINES + r")[-–]?\s?([0-9OSIB]\d{2}[A-Z]?)(?![0-9])")
_NOT_TAG_FAM = {"NO", "UFC", "AW", "SEE", "TYP", "OF", "TO", "X", "DN", "NPS", "SCH", "ASTM", "ANSI", "API", "ISO",
                "EN", "DIN", "SHEET", "NOTE"}


def tags_in(item: dict) -> list[dict]:
    """Tag mentions in one text item: [{"family", "num", "tag", "bbox"}]; 'DPT-1 & 2' gives two."""
    text = _canon(item["text"])
    out, taken = [], []
    for m in _TAG_KNOWN.finditer(text):
        fam = m.group(1).upper()
        fam = _PREFIX_FIX.get(fam, fam)
        num = m.group(2).translate(_DIG)
        if not num.isdigit():
            continue
        nums = [num] + re.findall(r"\d{1,3}", m.group(3) or "")
        # a sheet id like M-101 is not a tag; three-digit numbers on single-letter families are suspect
        if fam in FAMILIES and len(num) == 3 and len(fam) == 1:
            continue
        bb = _sub_box(item, m.start(), m.end())
        for n in nums:
            out.append({"family": fam, "num": int(n), "tag": f"{fam}-{int(n)}", "bbox": bb})
        taken.append((m.start(), m.end()))
    for m in _TAG_GEN.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        fam, num = m.group(1), m.group(2)
        if fam in _NOT_TAG_FAM or _SHEET.fullmatch(m.group(0)) or not num[0].isdigit():
            continue
        n = re.match(r"\d+", num).group(0)
        out.append({"family": fam, "num": int(n), "tag": f"{fam}-{num}", "bbox": _sub_box(item, m.start(), m.end())})
    # unnumbered abbreviations (PG, MAV, IF, BPCV) as whole words
    for m in re.finditer(r"(?<![A-Za-z0-9-])(PG|MAV|IF|BPCV)(?![A-Za-z0-9-])", text):
        if m.group(1) == "IF" and re.search(r"\bIF\s+(?:[A-Z]{2,}|SO|DIRECTED|REQUIRED)", text[m.start():]):
            continue  # the English word 'IF' in a note
        if m.group(1) == "IF" and len(text.split()) > 3:
            continue
        out.append({"family": m.group(1), "num": None, "tag": m.group(1), "bbox": _sub_box(item, m.start(), m.end())})
    return out


def _center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _near(a, b, k: float = 1.2) -> bool:
    (ax, ay), (bx, by) = _center(a), _center(b)
    w = max(a[2] - a[0], b[2] - b[0], 0.004)
    h = max(a[3] - a[1], b[3] - b[1], 0.004)
    return abs(ax - bx) < k * w and abs(ay - by) < k * h


def _src_kind(src: str) -> str:
    return src.split(":")[0]


_ink_cache: dict = {}


def _inked(image: str | None):
    """f(bbox) -> share of dark pixels in the box (None without an image): a box with no ink holds no label."""
    if not image or not os.path.exists(image):
        return None
    if image not in _ink_cache:
        import numpy as np
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = None
        _ink_cache.clear()
        g = np.asarray(Image.open(image).convert("L"))
        # ink = darker than halfway between the paper and the darkest strokes: a fixed 128 saw no ink at all on a
        # faded scan on yellowed paper (every box was then dropped as blank)
        paper, dark = np.percentile(g[::4, ::4], [50, 0.5])
        _ink_cache[image] = g < (paper + dark) / 2 if paper - dark > 20 else g < 128
    g = _ink_cache[image]
    H, W = g.shape

    def f(b):
        x0, y0 = int(b[0] * W), int(b[1] * H)
        x1, y1 = max(x0 + 1, math.ceil(b[2] * W)), max(y0 + 1, math.ceil(b[3] * H))
        return float(g[y0:y1, x0:x1].mean())
    return f


def tag_instances(items: list[dict], image: str | None = None) -> list[dict]:
    """Every printed tag label once: mentions from all readers merged by place. A place read differently by the
    readers keeps the reading two readers agree on, else the vision reading (tesseract confuses 5/8, 1/t)."""
    cands = []
    ink = _inked(image)
    for it in items:
        if ink and _src_kind(it["src"]) != "pdf" and ink(it["bbox"]) < 0.03:
            continue  # a misplaced vision box over blank paper
        for t in tags_in(it):
            t["src"] = _src_kind(it["src"])
            t["conf"] = it.get("conf", 50)
            cands.append(t)
    # votes per (place, tag): how many distinct readers / variants saw this tag here
    for c in cands:
        same = [d for d in cands if d["tag"] == c["tag"] and _near(c["bbox"], d["bbox"])]
        c["votes"] = len({d["src"] for d in same}) * 10 + len(same)
        c["seen_by"] = sorted({d["src"] for d in same})
    prio = {"pdf": 3, "vision": 2, "tesseract": 1}
    cands.sort(key=lambda c: (-c["votes"], -prio.get(c["src"], 0), -c["conf"]))
    kept: list[dict] = []
    for c in cands:
        if c["src"] == "tesseract" and c["votes"] < 12 and c["conf"] < 60 and not any(
                d["tag"] == c["tag"] for d in cands if d is not c and _near(c["bbox"], d["bbox"])):
            continue  # one low-confidence tesseract read nobody else confirms
        if any(_near(c["bbox"], k["bbox"], 0.9) and (k["tag"] == c["tag"] or _overlap(c["bbox"], k["bbox"]) > 0.3)
               for k in kept):
            continue
        kept.append(c)
    # a lone reading far past the family's numbering (PS-38 among PS-1..24) is a misread, not a tag
    fam_nums = defaultdict(list)
    for k in kept:
        if k["num"] is not None:
            fam_nums[k["family"]].append(k)
    for f, ks in fam_nums.items():
        nums = sorted({k["num"] for k in ks})
        for k in ks:
            others = [n for n in nums if n != k["num"]]
            if others and k["num"] > 1.25 * max(others) + 2 and len(k["seen_by"]) < 2 \
                    and sum(1 for x in ks if x["num"] == k["num"]) == 1:
                kept.remove(k)
    kept.sort(key=lambda c: (c["bbox"][1], c["bbox"][0]))
    return kept


def _overlap(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    sa = max((a[2] - a[0]) * (a[3] - a[1]), 1e-12)
    sb = max((b[2] - b[0]) * (b[3] - b[1]), 1e-12)
    return ix * iy / min(sa, sb)


def dedupe_items(items: list[dict]) -> list[dict]:
    """One reading per place for phrase search: pdf > vision > the best tesseract variant; overlapping lines of a
    lower-priority reader are dropped."""
    prio = {"pdf": 0, "vision": 1, "tesseract": 2}
    order = sorted(items, key=lambda it: (prio.get(_src_kind(it["src"]), 3), -len(it["text"]), -it.get("conf", 0)))
    kept: list[dict] = []
    for it in order:
        if not re.search(r"[A-Za-z0-9]", it["text"]) or it["bbox"][3] - it["bbox"][1] < 1e-3:
            continue
        if _src_kind(it["src"]) == "tesseract" and (it.get("conf", 100) < 20 or (
                len(re.sub(r"[^A-Za-z0-9]", "", it["text"])) < 4 and it.get("conf", 100) < 60)):
            continue  # tesseract's noise on hatching / symbols ('XN', 'ka', '<4)')
        if any(_overlap(it["bbox"], k["bbox"]) > 0.5 for k in kept):
            continue
        kept.append(it)
    return sorted(kept, key=lambda it: (it["bbox"][1], it["bbox"][0]))


def blocks(items: list[dict]) -> list[dict]:
    """Stack vertically adjacent, horizontally overlapping lines into callout blocks ('12" PUMP / DISCHARGE / HEADER')."""
    lines = dedupe_items(items)
    groups: list[list[dict]] = []
    for ln in lines:
        h = ln["bbox"][3] - ln["bbox"][1]
        best = None
        for g in groups:
            last = g[-1]["bbox"]
            gap = ln["bbox"][1] - last[3]
            xo = min(ln["bbox"][2], last[2]) - max(ln["bbox"][0], last[0])
            lh = max(h, last[3] - last[1])
            if -0.5 * lh < gap < 0.9 * lh and (xo > 0 or abs(ln["bbox"][0] - last[0]) < 2 * lh):
                best = g
                break
        if best is not None:
            best.append(ln)
        else:
            groups.append([ln])
    return [{"text": clean(" ".join(x["text"] for x in g)), "bbox": _union([x["bbox"] for x in g]), "lines": g}
            for g in groups]


_SIZE = re.compile(r'(?<![\d/.\-])(\d{1,2}(?:[ -]\d/\d)?|\d/\d)\s?(?:"|°|º)')


def sizes_in(text: str) -> list[tuple[str, int, int]]:
    """Nominal pipe sizes (inches) printed in a text: [(size, start, end)]; letter heights / scales excluded."""
    t = _canon(text)
    out = []
    for m in _SIZE.finditer(t):
        tail = t[m.end():m.end() + 12].upper()
        head = t[max(0, m.start() - 6):m.start()]
        if re.match(r"\s*(TALL|HIGH|=|MIN|MAX|O\.?C)", tail) or "=" in head or re.match(r"\s*-\s*\d", tail):
            continue
        s = m.group(1).replace(" ", "-")
        if s in NPS:
            out.append((s + '"', m.start(), m.end()))
    for m in _SIZE_MM.finditer(t):  # metric sheets: '200mm RETURN LINE', '250mm x 300mm REDUCER'
        tail = t[m.end():m.end() + 14].upper()
        if re.match(r"\s*(DIA\.?\s+BOLT|THICK|MIN|MAX|CLEAR|O\.?C|GAP|BELOW|ABOVE|HIGH|TALL)", tail):
            continue
        if int(m.group(1)) in DN:
            out.append((f"{int(m.group(1))}mm", m.start(), m.end()))
    out.sort(key=lambda x: x[1])
    return out


def _size_key(s: str) -> float:
    """Sort key in inches ('8"' -> 8, '200mm' -> 7.9, '1-1/2"' -> 1.5)."""
    if s.endswith("mm"):
        return int(s[:-2]) / 25.4
    w, _, fr = s.rstrip('"').partition("-")
    if "/" in w:
        a, b = w.split("/")
        return int(a) / int(b)
    v = float(w)
    if fr:
        a, b = fr.split("/")
        v += int(a) / int(b)
    return v


def size_instances(items: list[dict]) -> list[dict]:
    cands = []
    for it in dedupe_items(items):
        for s, a, b in sizes_in(it["text"]):
            cands.append({"size": s, "bbox": _sub_box(it, a, b), "context": clean(it["text"]), "src": _src_kind(it["src"])})
    return cands


def sheet_refs(items: list[dict], own: str = "") -> list[dict]:
    """Other sheets this one points to: [{"sheet", "bbox", "detail", "context"}]."""
    own_k = re.sub(r"[^A-Z0-9]", "", own.upper())
    lines = dedupe_items(items)
    out = []
    for it in lines:
        t = _canon(it["text"])
        for m in _SHEET.finditer(t):
            num = m.group(2)
            num = num[0].translate(_DIG) + num[1:]
            if not num[:3].isdigit():
                continue
            pref = m.group(1).upper()
            hy = "-" if "-" in m.group(0) or pref != "MS" else ""
            sheet = f"{pref}{hy}{num}"
            if own_k and re.sub(r"[^A-Z0-9]", "", sheet) == own_k:
                continue
            ctx = t
            if re.search(r"UFC|ASTM|ANSI|\d-\d{3}-\d", t[max(0, m.start() - 6):m.end() + 3]):
                continue
            det = None
            dm = re.search(r"DETAIL\s+([A-Z]\d{1,2})", t[max(0, m.start() - 30):m.start()], re.I)
            if dm:
                det = dm.group(1).upper()
            else:  # callout bubble: the detail id printed just above the sheet id
                for o in lines:
                    if re.fullmatch(r"[A-H]\d{1,2}", o["text"].strip()) and 0 < it["bbox"][1] - o["bbox"][3] < 0.03 \
                            and abs(_center(o["bbox"])[0] - _center(it["bbox"])[0]) < 0.02:
                        det = o["text"].strip()
                        break
            out.append({"sheet": sheet, "bbox": _sub_box(it, m.start(), m.end()), "detail": det, "context": ctx,
                        "src": _src_kind(it["src"])})
    # the same reference read twice at one place; with a second reader, a lone tesseract read must be confirmed
    srcs = {_src_kind(it["src"]) for it in items}
    allrefs = []
    for it in items:
        for m in _SHEET.finditer(_canon(it["text"])):
            allrefs.append((re.sub(r"[^A-Z0-9]", "", m.group(1).upper() + m.group(2)[0].translate(_DIG) + m.group(2)[1:]),
                            _src_kind(it["src"]), _sub_box(it, m.start(), m.end())))
    if "vision" in srcs and "tesseract" in srcs:
        out = [r for r in out if len({s for k, s, b in allrefs
                                      if k == re.sub(r"[^A-Z0-9]", "", r["sheet"]) and _near(b, r["bbox"], 2)}) > 1
               or any(k == re.sub(r"[^A-Z0-9]", "", r["sheet"]) and s == "vision" for k, s, b in allrefs)]
    kept = []
    for r in out:
        if not any(k["sheet"] == r["sheet"] and _near(k["bbox"], r["bbox"]) for k in kept):
            kept.append(r)
    return kept


def own_sheet_id(items: list[dict], meta: dict) -> str:
    if meta.get("sheet_number"):
        return str(meta["sheet_number"])
    # the largest sheet-id-looking text in the lower-right title block
    best, bh = "", 0.0
    for it in items:
        b = it["bbox"]
        if b[0] > 0.75 and b[1] > 0.75:
            m = re.fullmatch(r"\s*(" + DISCIPLINES + r")-?\s?(\d{3}[A-Z]?)\s*", _canon(it["text"]))
            if m and b[3] - b[1] > bh:
                best, bh = it["text"].strip(), b[3] - b[1]
    m = re.search(r"\b(" + DISCIPLINES + r")-\d{3}[A-Z]?\b", meta.get("title") or "")
    return best or (m.group(0) if m else "")


def _join_rows(body: list[dict]) -> list[dict]:
    """One line per printed row: a scan's tile reads cut a row into pieces (the note number '4.' on one tile, its
    text on the next) and two readers repeat a piece; pieces sharing a row are joined left to right, and a piece
    inside another piece of the row (same text read twice) dropped."""
    rows: list[list[dict]] = []
    for ln in sorted(body, key=lambda l: (l["bbox"][1] + l["bbox"][3]) / 2):
        b = ln["bbox"]
        for r in rows:
            rb = _union([x["bbox"] for x in r])
            ov = min(b[3], rb[3]) - max(b[1], rb[1])
            if ov >= 0.5 * min(b[3] - b[1], rb[3] - rb[1]):
                r.append(ln)
                break
        else:
            rows.append([ln])
    out = []
    for r in rows:
        r.sort(key=lambda l: l["bbox"][0])
        keep = []
        for ln in r:
            t = _norm_txt(ln["text"])
            if any(t and t in _norm_txt(o["text"]) and _overlap(ln["bbox"], o["bbox"]) > 0.3 for o in r if o is not ln
                   and len(_norm_txt(o["text"])) > len(t)):
                continue
            if keep and _overlap(ln["bbox"], keep[-1]["bbox"]) > 0.6:
                if len(ln["text"]) > len(keep[-1]["text"]):
                    keep[-1] = ln
                continue
            keep.append(ln)
        out.append({**keep[0], "text": " ".join(x["text"].strip() for x in keep),
                    "bbox": _union([x["bbox"] for x in keep])})
    return sorted(out, key=lambda l: l["bbox"][1])


def notes(items: list[dict]) -> dict | None:
    """The numbered notes block: {"heading", "bbox", "notes": {n: {"text", "bbox"}}} or None."""
    lines = dedupe_items(items)
    heads = [ln for ln in lines if re.search(r"\bNOTES?\b", ln["text"], re.I) and len(ln["text"]) < 40
             and not re.search(r"\bSEE NOTE|NOTE \d|NOTE TO", ln["text"], re.I)]
    best = None
    for h in heads:
        hb = h["bbox"]
        lh = hb[3] - hb[1]
        col = [ln for ln in lines if ln is not h and ln["bbox"][1] > hb[1] + lh * 0.5
               and hb[0] - 0.02 < ln["bbox"][0] < hb[0] + 0.05 and ln["bbox"][1] < hb[3] + 0.5]
        col.sort(key=lambda ln: ln["bbox"][1])
        body, last = [], hb[3]
        for ln in col:
            if ln["bbox"][1] - last > 4 * max(lh, ln["bbox"][3] - ln["bbox"][1]):
                break
            if any(ln is o for o in heads):  # the next notes block starts here
                break
            body.append(ln)
            last = ln["bbox"][3]
        if body and (best is None or len(body) > len(best[1])):
            best = (h, body)
    if not best:
        return None
    h, body = best
    body = _join_rows(body)
    # paragraphs: a new note starts at a printed number ('4.' / a lone '4') or after a wider line gap
    hs = sorted(ln["bbox"][3] - ln["bbox"][1] for ln in body)
    med_h = hs[len(hs) // 2]
    x_text = sorted(ln["bbox"][0] for ln in body)[len(body) // 2]  # where note text starts (numbers sit left)
    n_num = sum(bool(re.match(r"\s*\d{1,2}\s*[.)]?(\s|$)", ln["text"])) for ln in body)
    n_gap = 1 + sum(b["bbox"][1] - a["bbox"][3] > 0.6 * med_h for a, b in zip(body, body[1:]))
    by_number = n_num >= 2 and n_num >= 0.8 * n_gap  # every note carries its number: split on numbers only
    paras: list[dict] = []
    pending_num = None
    last_y1 = None
    for ln in body:
        t = ln["text"].strip()
        lone = re.fullmatch(r"(\d{1,2})\s*[.)]?", t) if ln["bbox"][2] <= x_text + 0.002 else None
        if lone:
            pending_num = int(lone.group(1))
            continue
        m = re.match(r"(\d{1,2})\s*[.)]\s+(.*)", t)
        gap = None if last_y1 is None else ln["bbox"][1] - last_y1
        start = m is not None or pending_num is not None or gap is None or (gap > 0.6 * med_h and not by_number)
        if start:
            num = int(m.group(1)) if m else pending_num
            paras.append({"num": num, "text": (m.group(2) if m else t), "lines": [ln]})
        else:
            paras[-1]["text"] += " " + t
            paras[-1]["lines"].append(ln)
        pending_num = None
        last_y1 = ln["bbox"][3]
    out: dict = {}
    for p in paras:
        n = p["num"] if p["num"] is not None and p["num"] not in out else (max(out) + 1 if out else 1)
        out[n] = {"text": p["text"].strip(), "lines": p["lines"]}
    for n, v in out.items():
        v["bbox"] = _union([ln["bbox"] for ln in v["lines"]])
        del v["lines"]
    return {"heading": h["text"], "bbox": h["bbox"], "notes": out}


def grid(items: list[dict]):
    """Sheet border grid: ({label: x_center} columns, {label: y_center} rows) from the numbers / letters in the margins."""
    cols, rows = defaultdict(list), defaultdict(list)
    for it in items:
        t = it["text"].strip()
        cx, cy = _center(it["bbox"])
        if re.fullmatch(r"\d{1,2}", t) and (cy < 0.05 or cy > 0.95):
            cols[t].append(cx)
        elif re.fullmatch(r"[A-HJ-N]", t) and (cx < 0.05 or cx > 0.95):
            rows[t].append(cy)
    def fit(d, idx):
        """Theil-Sen line position = a + b * index over every reading: a misplaced or misread margin label
        (vision boxes on single characters are the weakest) cannot shift the grid."""
        pts = [(idx(k), v) for k, vs in d.items() for v in vs]
        if len({p[0] for p in pts}) < 3:
            return None
        sl = sorted((v2 - v1) / (i2 - i1) for (i1, v1) in pts for (i2, v2) in pts if i2 > i1)
        b = sl[len(sl) // 2]
        a = sorted(v - b * i for i, v in pts)[len(pts) // 2]
        return {k: a + b * idx(k) for k in d}, b

    fc = fit(cols, int)
    fr = fit(rows, lambda k: ord(k))
    if not fc or not fr:
        return None
    (cpos, _), (rpos, _) = fc, fr
    # fill the labels nobody read (column 7 missing still has a square)
    lo, hi = min(int(k) for k in cpos), max(int(k) for k in cpos)
    b = fc[1]
    a = cpos[str(lo)] - b * lo
    cpos = {str(k): a + b * k for k in range(1, hi + 3) if 0 < a + b * k < 1 and (k <= hi or a + b * k < 0.97)}
    letters = sorted(rpos)
    rb = fr[1]
    ra = rpos[letters[0]] - rb * ord(letters[0])
    rpos = {chr(k): ra + rb * k for k in range(ord("A"), ord(letters[-1]) + 4)
            if chr(k) not in "IO" and 0.03 < ra + rb * k < 0.97}
    return cpos, rpos


def where(bbox, g) -> str:
    cx, cy = _center(bbox)
    if g:
        cols, rows = g
        c = min(cols, key=lambda k: abs(cols[k] - cx))
        r = min(rows, key=lambda k: abs(rows[k] - cy))
        return f"grid {r}-{c}"
    v = "top" if cy < 0.33 else "bottom" if cy > 0.67 else "middle"
    h = "left" if cx < 0.33 else "right" if cx > 0.67 else "centre"
    return f"{v} {h} of the sheet"


# ================================================================================================ questions
_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8}
_STOP = set("what which where is are the a an of on this that sheet plan drawing size sizes pipe pipes piping line "
            "how big diameter does do go goes run runs to from in for there any nominal show me find located "
            "label labelled labeled called".split())


def _base(meta) -> dict:
    return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": METHOD,
            "explanation": "", "unit": None}


def _ev(bbox, label, value=None, page=0, kind="box", tag=None):
    e = {"kind": kind, "page": page, "bbox": [round(min(max(v, 0.0), 1.0), 5) for v in bbox], "label": label,
         "value": value}
    if tag:  # the UI groups tag boxes into chips by family
        e["tag"], e["group"] = tag, re.split(r"-", tag)[0]
    return e


def _families_asked(q: str, present: set) -> list[str] | None:
    ql = q.lower()
    # a family code typed directly ("How many PIT?", "count the FSCV tags")
    codes = [c for c in sorted(set(present) | set(FAMILIES), key=len, reverse=True) if c not in ("IF", "P", "V", "FS")
             and re.search(r"(?<![a-z0-9])" + re.escape(c.lower()) + r"(?:s|'s)?(?![a-z0-9])", ql)]
    if codes:
        return codes
    for pat, fams in GLOSSARY:
        if re.search(pat, ql):
            hit = [f for f in fams if f in present]
            return hit or fams
    return None


def _llm_family(q: str, present: dict, cost: list) -> list[str] | None:
    """Unusual wording: Haiku picks among the families actually on the sheet (cached by question + families)."""
    if not present:
        return None
    fams = sorted(present)
    key = hashlib.sha1((q + "|" + ",".join(fams)).encode()).hexdigest()[:16]
    f = CACHE / "family" / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text()).get("families")
    from bp.generic import llm

    lst = "\n".join(f"{k}: {FAMILIES.get(k, ('?',))[0]} (e.g. {present[k][0]})" for k in fams)
    r = llm.ask(f"A question about a piping plan: {q!r}\nTag families on the sheet:\n{lst}\n"
                'Which families does the question count? JSON only: {"families": ["CODE", ...]} '
                '(empty list if none fits).', model="haiku", tag="sheets-piping-family", timeout=60)
    cost.append(float(r.get("cost_usd") or 0.0))
    d = llm.parse_json(r.get("text") or "") or {}
    out = [x for x in (d.get("families") or []) if x in present] if isinstance(d, dict) else []
    if r.get("text"):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"q": q, "families": out}))
    return out or None


def _tag_list(fam: str, nums: list[int]) -> str:
    """'FP-1 ... FP-5' for a full run, else the tags themselves (shortened with ranges past 8)."""
    nums = sorted(set(nums))
    if len(nums) >= 3 and nums == list(range(nums[0], nums[-1] + 1)):
        return f"{fam}-{nums[0]} to {fam}-{nums[-1]}"
    if len(nums) <= 8:
        return ", ".join(f"{fam}-{n}" for n in nums)
    return ", ".join(f"{fam}-{r}".replace("-", " to " + fam + "-", 2).replace(f"{fam} to {fam}-", f"{fam}-", 1)
                     if "-" in r else f"{fam}-{r}" for r in _ranges(nums).split(", "))


RECHECK_PROMPT = """This is a zoomed crop of a piping plan, {w}x{h} pixels. List every label of the form {fam}-<number>
(e.g. {ex}) printed in it. One line per label: its box as four integer pixel coordinates in this image
(left,top,right,bottom), a bar, then the label, e.g.
212,40,268,58|{ex}
Write the numbers themselves, never the letters x0,y0,x1,y1. Only labels you can actually read. No other output."""


def _family_scan(sheet: dict, fams: list[str], cost: list) -> list[dict]:
    """The asked family read nowhere (a faded / blurred scan): the whole sheet once more in small tiles upscaled ~x3,
    asking Haiku only for labels of these families. Cached per image + families. Returns tag instances."""
    from PIL import Image

    from bp.generic import llm

    img = sheet.get("image")
    if not img:
        return []
    key = hashlib.sha1(f"{img}|{os.path.getsize(img)}|{','.join(sorted(fams))}".encode()).hexdigest()[:16]
    cf = CACHE / "famscan" / f"{key}.json"
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(img).convert("RGB")
    W, H = im.size
    if cf.exists():
        got = json.loads(cf.read_text())["lines"]
    else:
        t = SEND_PX // 3
        while True:  # ~x3 zoom on small scans; at most FAMSCAN_TILES calls
            nx, ny = math.ceil((W - t * 0.12) / (t * 0.88)), math.ceil((H - t * 0.12) / (t * 0.88))
            if nx * ny <= FAMSCAN_TILES:
                break
            t = int(t * 1.15)
        t = min(t, W, H)
        tiles = [(round(i * (W - t) / max(1, nx - 1)), round(j * (H - t) / max(1, ny - 1))) for j in range(ny)
                 for i in range(nx)]
        f = SEND_PX / t
        ex = ", ".join(f"{fm}-1" for fm in fams)
        fam_txt = " or ".join(f"{fm}-<number>" for fm in fams)

        def one(xy):
            crop = im.crop((xy[0], xy[1], xy[0] + t, xy[1] + t)).resize((SEND_PX, SEND_PX), Image.LANCZOS)
            r = llm.ask(RECHECK_PROMPT.format(w=SEND_PX, h=SEND_PX, fam=fam_txt, ex=ex), [crop], model="haiku",
                        think="low", system="You read drawings exactly. Output only the requested lines.",
                        timeout=120, tag="sheets-piping-famscan")
            return xy, (r.get("text") or "").splitlines(), float(r.get("cost_usd") or 0.0)

        with ThreadPoolExecutor(min(16, len(tiles))) as exr:
            res = list(exr.map(one, tiles))
        cost.append(sum(c for _, _, c in res))
        got = [[xy[0], xy[1], f, ln] for xy, lines, _ in res for ln in lines]
        cf.parent.mkdir(parents=True, exist_ok=True)
        cf.write_text(json.dumps({"fams": fams, "lines": got}))
    items = []
    for x0, y0, f, line in got:
        m = re.match(r"\s*(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)"
                     r"\s*[|:]\s*(.+?)\s*$", line)
        if not m:
            continue
        a_, b_, c_, d_ = (float(m.group(k)) / f for k in range(1, 5))
        bb = [(x0 + min(a_, c_)) / W, (y0 + min(b_, d_)) / H, (x0 + max(a_, c_)) / W, (y0 + max(b_, d_)) / H]
        items.append({"text": m.group(5), "bbox": [min(max(v, 0.0), 1.0) for v in bb], "src": "vision-famscan",
                      "conf": 70.0})
    return [t for t in tag_instances(items, img) if t["family"] in fams]


def _recheck(sheet: dict, fam: str, found: list[dict], cost: list, avoid: list[dict] = ()) -> list[dict] | None:
    """A family's numbering has a gap (FSCV-1..5, 7): one Haiku look at a zoomed crop around the labels found,
    asking only for that family. Returns the new labels (maybe []), or None when the crop would not be a zoom."""
    from PIL import Image

    from bp.generic import llm

    b = _union([t["bbox"] for t in found])
    w, h = b[2] - b[0], b[3] - b[1]
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(sheet["image"]).convert("RGB")
    W, H = im.size
    pad_x, pad_y = max(0.25, 0.15 * w), max(0.04, 0.3 * h)  # tags of one family usually sit in a row
    r = [max(0.0, b[0] - pad_x), max(0.0, b[1] - pad_y), min(1.0, b[2] + pad_x), min(1.0, b[3] + pad_y)]
    cw, ch = (r[2] - r[0]) * W, (r[3] - r[1]) * H
    # the band in up to 4 pieces, each zoomed >= 1x (else a crop is no sharper than the tiles were)
    n = max(1, min(4, math.ceil(cw / (SEND_PX / 2))))
    f = min(3.0, SEND_PX / max(cw / n, ch))
    if f < 2.0 and ch * 2 <= SEND_PX:
        # a big scan: four pieces zoom the band barely past the tile read (FSCV-6 / 7 of M-101B missed again);
        # up to eight pieces, each at least 2x
        n = max(n, min(8, math.ceil(cw / (SEND_PX / 2))))
        f = min(3.0, SEND_PX / max(cw / n, ch))
    if f < 1.0:
        return None
    pieces = [[r[0] + (r[2] - r[0]) * i / n - (0.01 if i else 0), r[1],
               r[0] + (r[2] - r[0]) * (i + 1) / n + (0.01 if i < n - 1 else 0), r[3]] for i in range(n)]
    def piece(pc):
        key = hashlib.sha1(f"{sheet['image']}|{os.path.getsize(sheet['image'])}|{fam}|{[round(x, 4) for x in pc]}"
                           .encode()).hexdigest()[:16]
        cf = CACHE / "recheck" / f"{key}.json"
        if cf.exists():
            return pc, json.loads(cf.read_text())["lines"], 0.0
        crop = im.crop((round(pc[0] * W), round(pc[1] * H), round(pc[2] * W), round(pc[3] * H)))
        crop = crop.resize((round(crop.width * f), round(crop.height * f)), Image.LANCZOS)
        res = llm.ask(RECHECK_PROMPT.format(w=crop.width, h=crop.height, fam=fam, ex=found[0]["tag"]), [crop],
                      model="haiku", system="You read drawings exactly. Output only the requested lines.",
                      timeout=120, tag="sheets-piping-recheck")
        lines = (res.get("text") or "").splitlines()
        if res.get("text"):
            cf.parent.mkdir(parents=True, exist_ok=True)
            cf.write_text(json.dumps({"fam": fam, "lines": lines}))
        return pc, lines, float(res.get("cost_usd") or 0.0)

    with ThreadPoolExecutor(len(pieces)) as ex:  # the pieces side by side: one round trip of latency
        got = list(ex.map(piece, pieces))
    cost.append(sum(c for _, _, c in got))
    found_lines = [(pc, ln) for pc, lines, _ in got for ln in lines]
    ink = _inked(sheet["image"])
    have = {t["tag"] for t in found}
    new = []
    for r, line in found_lines:
        m = re.match(r"\s*(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)"
                     r"\s*[|:]\s*(.+?)\s*$", line)
        if not m:
            continue
        a_, b_, c_, d_ = (float(m.group(k)) / f for k in range(1, 5))
        bb = [r[0] + min(a_, c_) / W, r[1] + min(b_, d_) / H, r[0] + max(a_, c_) / W, r[1] + max(b_, d_) / H]
        for t in tags_in({"text": m.group(5), "bbox": bb}):
            if t["family"] != fam or t["tag"] in have or (ink and ink(bb) < 0.03):
                continue
            if any(_near(bb, o["bbox"]) or _overlap(bb, o["bbox"]) > 0.2 for o in list(found) + list(avoid)):
                continue  # read where a label of this family already is: a misreading of it (FSCV-6 as FSCV-8)
            t.update(src="vision-recheck", seen_by=["vision-recheck"], conf=70.0)
            have.add(t["tag"])
            new.append(t)
    return new


def _ranges(nums: list[int]) -> str:
    nums = sorted(set(nums))
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}" if j > i + 1 else f"{nums[i]}, {nums[j]}")
        i = j + 1
    return ", ".join(out)


def _count(q: str, sheet: dict, insts: list[dict], base: dict, cost: list) -> dict | None:
    present: dict = defaultdict(list)
    for t in insts:
        present[t["family"]].append(t["tag"])
    fams = _families_asked(q, set(present))
    if fams is None:
        fams = _llm_family(q, present, cost)
    if not fams:
        return None
    ql = q.lower()
    want_inst = bool(re.search(r"\b(labels?|markers?|instances?|times|occurrences?|places|locations|callouts?|"
                               r"printed|tags? on the)\b", ql))
    sel = [t for t in insts if t["family"] in fams]
    names = " + ".join(f"{f} ({FAMILIES.get(f, (f.lower(), f.lower() + 's'))[1]})" for f in fams)
    famscan = None
    missing = [f for f in fams if not any(t["family"] == f for t in sel)]
    if missing and sheet.get("image") and "pdf text layer" not in sheet["readers"] and (not sel or len(fams) > 1):
        # an asked family read nowhere: one more, closer look at the whole sheet for just these labels
        famscan = _family_scan(sheet, missing, cost)
        sel = sel + famscan
    if not sel:
        if not present:  # no tag of any family read: the reading failed, a 0 would be a guess
            return dict(base, answer=None, confidence=0.0,
                        explanation=f"No tags could be read on this sheet ({', '.join(sheet['readers']) or 'no reader'}"
                                    f"), so {names} are not counted here.")
        return dict(base, answer=0, confidence=0.3, unit="count",
                    explanation=f"No {names} tag found on this sheet by {', '.join(sheet['readers'])}"
                                + (" nor by a closer whole-sheet look for these labels" if famscan is not None else "")
                                + f". Tag families read here: {', '.join(sorted(present))}. Not found, which may mean "
                                  "absent or unreadable.")
    n_ocr = len({_src_kind(it["src"]) for it in sheet["items"]})
    rechecked = []
    for f in fams:
        nums = sorted({t["num"] for t in sel if t["family"] == f and t["num"] is not None})
        unconfirmed = n_ocr > 1 and nums and len(nums) <= 12 and not any(
            len(t.get("seen_by", [])) > 1 for t in sel if t["family"] == f)
        # a gap, an unconfirmed reading, or a short run (a missed last tag leaves no gap: FP-1..4 of 5) gets one
        # zoomed look along its row (cached; skipped on exact PDF text)
        if nums and ([k for k in range(1, nums[-1] + 1) if k not in nums] or unconfirmed or len(nums) <= 12) \
                and sheet.get("image") and f not in missing:
            new = _recheck(sheet, f, [t for t in sel if t["family"] == f], cost, avoid=sel)
            if new is not None:
                rechecked.append((f, new))
                sel += new
    numbered = [t for t in sel if t["num"] is not None]
    unnum = [t for t in sel if t["num"] is None]
    ev, parts = [], []
    if numbered and not want_inst:
        by_tag: dict = defaultdict(list)
        for t in numbered:
            by_tag[t["tag"]].append(t)
        tags = sorted(by_tag, key=lambda k: (k.split("-")[0], int(re.match(r"\d+", k.split("-")[1]).group(0))))
        for i, tg in enumerate(tags, 1):
            for j, t in enumerate(by_tag[tg]):
                ev.append(_ev(t["bbox"], f"{i}: {tg}" + (f" (label {j + 1} of {len(by_tag[tg])})"
                                                         if len(by_tag[tg]) > 1 else ""), 1 if j == 0 else 0, tag=tg))
        n = len(tags) + len(unnum)
        for f in fams:
            nums = sorted({t["num"] for t in numbered if t["family"] == f})
            if not nums:
                continue
            gaps = [k for k in range(1, nums[-1] + 1) if k not in nums]
            labels = sum(1 for t in numbered if t["family"] == f)
            s = f"{_tag_list(f, nums)}: {len(nums)} distinct"
            if labels > len(nums):
                s += f", printed at {labels} places (repeated labels counted once)"
            if gaps:
                s += f"; no {', '.join(f'{f}-{k}' for k in gaps[:8])} found (absent, or missed by the reader)"
            parts.append(s)
        conf = 0.85 if all(not [k for k in range(1, max(t['num'] for t in numbered if t['family'] == f) + 1)
                                if k not in {t['num'] for t in numbered if t['family'] == f}]
                           for f in {t['family'] for t in numbered}) else 0.6
    else:
        n = len(sel)
        for i, t in enumerate(sel, 1):
            ev.append(_ev(t["bbox"], f"{i}: {t['tag']}", 1, tag=t["tag"]))
        parts.append(f"{n} {'/'.join(fams)} labels on the sheet" +
                     (" (every printed label counted, repeats included)" if numbered else ""))
        conf = 0.55 if unnum else 0.7
    ql_valve = re.search(r"valve", ql)
    if ql_valve:
        others = sorted(f for f in present if f not in fams and len(f) > 1
                        and re.search(r"valve", FAMILIES.get(f, ("",))[0]))
        if others:
            parts.append("other valve tags on the sheet, not counted here: " + ", ".join(
                f"{f} ({FAMILIES[f][1]}, {len({t['tag'] for t in insts if t['family'] == f})})" for f in others))
    if famscan:
        parts.append(f"found only by a closer whole-sheet look for these labels (the first reading had none)")
    for f, new in rechecked:
        parts.append(f"{f} re-checked on a zoomed crop: " +
                     (f"found {', '.join(t['tag'] for t in new)}" if new else "nothing more found"))
    agreed = sum(1 for t in sel if len(t.get("seen_by", [])) > 1)
    expl = f"{'; '.join(parts)}. Counted {names} tags read from the sheet text"
    if n_ocr > 1:
        expl += f" ({agreed} of {len(sel)} labels read by two independent readers)"
        if agreed < 0.3 * len(sel):  # one reader alone (tesseract fails on blurred / faded scans)
            conf = min(conf, 0.6)
            expl += "; on this sheet only the vision reader could read the tags, so the count is less certain"
    if famscan:
        conf = min(conf, 0.5)
    expl += "."
    if unnum:
        expl += f" {', '.join(sorted({t['family'] for t in unnum}))} carry no number, so each printed label counts" \
                " once; small labels can be missed, so the drawing may contain more."
    if "PS" in fams and not want_inst:
        expl += " Pipe-support tags name support types; the actual support locations are the large filled dots" \
                " on the piping (see the notes). Ask 'how many pipe support labels' for every printed label."
    if "FP" in fams:
        other = [it["text"] for it in dedupe_items(sheet["items"]) if re.search(r"\bPUMP\b", it["text"], re.I)
                 and not re.search(r"DISCHARGE|SUCTION|HEADER|CENTRIFUGAL|FP|^\W*\d", it["text"], re.I)]
        if other:
            expl += f" Also labelled on the sheet (not FP-tagged): {', '.join(sorted(set(other))[:4])}."
    return dict(base, answer=n, confidence=conf, evidence=ev, explanation=expl, unit="count")


def _sizes_answer(q, sheet, base) -> dict:
    cands = size_instances(sheet["items"])
    if not cands:
        return dict(base, explanation="No pipe-size text (like 8\") read on this sheet.")
    cnt = Counter(c["size"] for c in cands)
    order = sorted(cnt, key=_size_key)
    ans = ", ".join(order)
    ev = [_ev(c["bbox"], f'{order.index(c["size"]) + 1}: {c["size"]} ({c["context"][:40]})') for c in
          sorted(cands, key=lambda c: _size_key(c["size"]))]
    expl = (f"{len(order)} nominal sizes on the sheet: " +
            "; ".join(f'{s} x{cnt[s]}' for s in order) +
            ". Read from every size callout (inch marks / mm); letter heights (4\" TALL) and the scale are excluded.")
    biggest = order[-1]
    ctx = [c["context"] for c in cands if c["size"] == biggest and len(c["context"]) > 6][:1]
    if ctx:
        expl += f' Largest: {biggest} ({ctx[0]}).'
    unit = "mm" if all(o.endswith("mm") for o in order) else "inch" if all(o.endswith('"') for o in order) else None
    return dict(base, answer=ans, confidence=0.7, evidence=ev, explanation=expl, unit=unit)


def _keywords(q: str) -> list[str]:
    ws = re.findall(r"[a-z0-9/]+", q.lower())
    return [w for w in ws if w not in _STOP and not re.fullmatch(r"\d+(?:/\d+)?", w) and len(w) > 1]


def _fuzzy_has(text: str, kw: str) -> bool:
    toks = re.findall(r"[a-z0-9/]+", text.lower())
    for t in toks:
        if t.startswith(kw) or kw.startswith(t) and len(t) >= 4:
            return True
        if len(kw) >= 5 and len(t) >= 5 and _ed1(t[:len(kw)], kw):
            return True
    return False


def _ed1(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    return any(a == b[:i] + b[i + 1:] for i in range(len(b)))


def _find_blocks(q: str, sheet: dict, size: str | None = None):
    kws = _keywords(q)
    if not kws:
        return [], kws
    hits = []
    for b in blocks(sheet["items"]):
        n = sum(_fuzzy_has(b["text"], k) for k in kws)
        if n == len(kws) or (len(kws) >= 3 and n >= len(kws) - 1):
            if size and size not in [s for s, _, _ in sizes_in(b["text"])]:
                continue
            hits.append((n, b))
    hits.sort(key=lambda x: (-x[0], len(x[1]["text"])))
    return [b for _, b in hits], kws


def _named_size(q, sheet, base) -> dict | None:
    bl, kws = _find_blocks(q, sheet)
    found = []
    for b in bl:
        ss = sizes_in(b["text"])
        if ss:
            found.append((ss[0][0], b))
    if not found:
        return None
    sizes = Counter(s for s, _ in found)
    s0 = sizes.most_common(1)[0][0]
    ev = [_ev(b["bbox"], f'{i}: "{b["text"][:60]}"', s) for i, (s, b) in enumerate(found, 1)]
    expl = f'Read from the callout "{found[0][1]["text"]}"'
    if len(sizes) > 1:
        expl += "; other matching callouts: " + "; ".join(f'"{b["text"]}"' for s, b in found[1:4])
    return dict(base, answer=s0, confidence=0.8 if len(sizes) == 1 else 0.55, evidence=ev,
                explanation=expl + ".", unit="mm" if s0.endswith("mm") else "inch")


def _where(q, sheet, insts, base) -> dict | None:
    g = grid(sheet["items"])
    qn = _canon(q)
    tq = tags_in({"text": qn.upper(), "bbox": [0, 0, 0, 0]})
    tq = [t for t in tq if t["num"] is not None]
    if tq:
        want = {t["tag"] for t in tq}
        sel = [t for t in insts if t["tag"] in want]
        if not sel:
            return dict(base, explanation=f"{', '.join(sorted(want))} was not found on this sheet.",
                        not_found={"kind": "label", "asked": ", ".join(sorted(want)),
                                   "available": sorted({t['tag'] for t in insts})[:12]})
        locs = [f"{t['tag']} at {where(t['bbox'], g)}" for t in sel]
        return dict(base, answer="; ".join(locs), confidence=0.75,
                    evidence=[_ev(t["bbox"], f"{i}: {t['tag']}", tag=t["tag"]) for i, t in enumerate(sel, 1)],
                    explanation=f"Located {len(sel)} label(s) on the sheet; grid squares from the sheet border.")
    size = None
    ms = sizes_in(qn)
    if ms:
        size = ms[0][0]
    bl, kws = _find_blocks(q, sheet, size)
    if not bl and size:
        bl, kws = _find_blocks(q, sheet)
    if not bl:
        return None
    main = bl[0]
    # other callouts that mention the same run (e.g. '8" CROSS CONNECTION FROM RETURN LINE')
    key = [k for k in kws if k not in ("where",)]
    related = []
    for b in blocks(sheet["items"]):
        if b is main or _overlap(b["bbox"], main["bbox"]) > 0.3 or b["text"] == main["text"] or not key:
            continue
        if any(_overlap(b["bbox"], r["bbox"]) > 0.3 or b["text"] == r["text"] for r in related):
            continue
        if sum(_fuzzy_has(b["text"], k) for k in key) >= len(key):
            related.append(b)
    related = related[:5]
    ans = f'"{main["text"]}" is labelled at {where(main["bbox"], g)}'
    if related:
        ans += "; related callouts: " + "; ".join(f'"{b["text"]}" ({where(b["bbox"], g)})' for b in related)
    ev = [_ev(main["bbox"], f'1: {main["text"][:60]}')] + \
         [_ev(b["bbox"], f'{i}: {b["text"][:60]}') for i, b in enumerate(related, 2)]
    return dict(base, answer=ans, confidence=0.5, evidence=ev,
                explanation="Found from the sheet's labels (grid squares from the sheet border). The pipe run itself "
                            "is not traced: follow the line from the boxed label on the drawing.")


def _refs_answer(q, sheet, meta, base) -> dict:
    own = own_sheet_id(sheet["items"], meta)
    refs = sheet_refs(sheet["items"], own)
    if not refs:
        return dict(base, explanation="No references to other sheets read on this sheet.")
    order = []
    for r in refs:
        if r["sheet"] not in order:
            order.append(r["sheet"])
    order.sort(key=lambda s: (s[0], s))
    det = defaultdict(set)
    for r in refs:
        if r["detail"]:
            det[r["sheet"]].add(r["detail"])
    ans = ", ".join(order)
    ev = [_ev(r["bbox"], f"{order.index(r['sheet']) + 1}: {r['sheet']}" + (f" (detail {r['detail']})"
                                                                         if r["detail"] else "")) for r in refs]
    expl = f"{len(order)} other sheets referenced in {len(refs)} places" + (f" (this sheet: {own})" if own else "")
    if det:
        expl += "; details called out: " + ", ".join(f"{'/'.join(sorted(v))} on {k}" for k, v in sorted(det.items()))
    return dict(base, answer=ans, confidence=0.7, evidence=ev, explanation=expl + ".")


def _note_answer(q, sheet, base) -> dict | None:
    nb = notes(sheet["items"])
    if not nb:
        return None
    m = re.search(r"note\s*(?:no\.?|number|#)?\s*(\d{1,2})|(\d{1,2})(?:st|nd|rd|th)\s+note", q, re.I)
    n = None
    if m:
        n = int(m.group(1) or m.group(2))
    else:
        for w, v in _WORDNUM.items():
            if re.search(rf"\b(note\s+{w}|{w}\s+note)\b", q, re.I):
                n = v
    ns = nb["notes"]
    if n is None:
        if re.search(r"how many", q, re.I):
            return dict(base, answer=len(ns), confidence=0.7, unit="count",
                        evidence=[_ev(v["bbox"], f"{k}: note {k}", 1) for k, v in sorted(ns.items())],
                        explanation=f'{len(ns)} numbered notes under "{nb["heading"]}".')
        return None
    if n not in ns:
        return dict(base, explanation=f'The notes block "{nb["heading"]}" has notes {_ranges(list(ns))}; no note {n}.',
                    evidence=[_ev(nb["bbox"], nb["heading"])])
    v = ns[n]
    return dict(base, answer=v["text"], confidence=0.75, evidence=[_ev(v["bbox"], f"note {n}", kind="text"),
                                                                  _ev(nb["bbox"], nb["heading"], kind="text")],
                explanation=f'Note {n} of "{nb["heading"]}" read from the sheet text.')


QA_PROMPT = """Text lines read from a piping plan (construction drawing). Each line: [id] text. OCR can garble a few
characters. Question: {q}
Answer from these lines only. JSON only: {{"answer": "<short answer, or null if the lines do not answer it>",
"ids": [ids of the lines you used], "why": "<one short sentence>"}}

{lines}"""


def _text_qa(q, sheet, base, cost) -> dict | None:
    from bp.generic import llm

    lines = dedupe_items(sheet["items"])
    if not lines:
        return None
    kws = _keywords(q)
    scored = sorted(range(len(lines)), key=lambda i: -sum(_fuzzy_has(lines[i]["text"], k) for k in kws))
    keep = sorted(scored[:400])
    body = "\n".join(f"[{i}] {lines[i]['text'][:160]}" for i in keep)
    key = hashlib.sha1((q + body).encode()).hexdigest()[:16]
    f = CACHE / "qa" / f"{key}.json"
    if f.exists():
        d = json.loads(f.read_text())
    else:
        r = llm.ask(QA_PROMPT.format(q=q, lines=body), model="haiku", tag="sheets-piping-qa", timeout=90)
        cost.append(float(r.get("cost_usd") or 0.0))
        d = llm.parse_json(r.get("text") or "") or {}
        if r.get("text") and isinstance(d, dict):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(d))
    if not isinstance(d, dict) or d.get("answer") in (None, "", "null"):
        return None
    ids = [i for i in d.get("ids") or [] if isinstance(i, int) and 0 <= i < len(lines)]
    if not ids:
        return None
    ev = [_ev(lines[i]["bbox"], f"{k}: {lines[i]['text'][:60]}", kind="text") for k, i in enumerate(ids, 1)]
    return dict(base, answer=str(d["answer"]), confidence=0.45, evidence=ev,
                explanation=(d.get("why") or "Read from the sheet text.") + " (Haiku over the sheet's read text,"
                                                                             " cited lines boxed)")


# ======================================================================================================== API
def detect(meta) -> float:
    title = f"{meta.get('title', '')} {meta.get('sheet_number', '')}"
    text = meta.get("text", "") or ""
    blob = f"{title} {text[:30000]}"
    s = 0.0
    if meta.get("kind") == "piping":
        s += 0.6
    if re.search(r"PIPING\s+PLAN|PIPING\s+LAYOUT|PIPING\s+ARRANGEMENT|P\s*&\s*ID|PROCESS\s+PIPING", blob, re.I):
        s += 0.4
    if re.search(r"\bM-?1\d{2}[A-Z]?\b|\bP-?\d{3}\b", title):
        s += 0.15
    n_sizes = len(sizes_in(text))
    n_tags = len(re.findall(r"\b(?:CV|PS|FP|FSCV|PIT|DPT|PG|MAV)-?\d", text))
    s += min(0.3, 0.01 * n_sizes + 0.01 * n_tags)
    if re.search(r"\b(SUCTION|DISCHARGE)\s+HEADER|\bREDUCER\b|\bCHECK VALVE\b", blob, re.I):
        s += 0.15
    if meta.get("kind") in ("arch", "slab"):
        s -= 0.3
    return max(0.0, min(1.0, s))


_RX_COUNT = re.compile(r"\b(how many|number of|count|total|montako|kuinka monta|hur många|antal|wie viele|anzahl|"
                       r"combien|cuántos|cuantas|quanti|hoeveel|mitu)\b", re.I)
_RX_SIZES = re.compile(r"\b(what|which|list)\b.*\bsizes?\b|\bsizes? of pipe|pipe sizes", re.I)
_RX_REFS = re.compile(r"\b(other|which|what|list)\b.*\b(sheets?|drawings?|details?|sections?)\b.*\b(referenc|refer|"
                      r"call|point|mention|cite|link)|\breferenced (sheets|drawings)", re.I)
_RX_NOTE = re.compile(r"\bnotes?\b", re.I)
_RX_WHERE = re.compile(r"\bwhere\b|\blocat|\bfind\b|\bgo(es)?\b.*\?|\bconnect", re.I)
_RX_SIZE_OF = re.compile(r"\b(what|which)\b.*\b(size|diameter)\b|\bhow (big|large|wide)\b|\bsize of\b", re.I)


def answer(path, question, meta) -> dict | None:
    meta = meta or {}
    q = question.strip()
    from bp.sheets import pipe_runs  # pipe lengths ("metres of 8-inch pipe", "length of the 16" suction header")
    if pipe_runs.is_length_question(q):
        r = pipe_runs.answer(path, q, meta)
        if r and r.get("answer") is not None:
            return r
    sheet = read_sheet(str(path), meta)
    base = _base(meta)
    if not sheet["items"]:
        return None
    cost = [sheet.get("cost_usd_now", 0.0)]
    sheet["cost_usd_now"] = 0.0  # the read is paid once per sheet; later questions reuse it
    insts = tag_instances(sheet["items"], sheet.get("image"))
    res = None
    try:
        if _RX_NOTE.search(q) and not _RX_REFS.search(q):
            res = _note_answer(q, sheet, base)
        if res is None and _RX_REFS.search(q):
            res = _refs_answer(q, sheet, meta, base)
        if res is None and _RX_SIZES.search(q) and not _RX_SIZE_OF.search(q.replace("sizes", "")):
            res = _sizes_answer(q, sheet, base)
        if res is None and _RX_COUNT.search(q):
            res = _count(q, sheet, insts, base, cost)
        if res is None and _RX_SIZE_OF.search(q):
            res = _named_size(q, sheet, base)
        if res is None and _RX_WHERE.search(q):
            res = _where(q, sheet, insts, base)
        if res is None:
            res = _text_qa(q, sheet, base, cost)
    finally:
        pass
    if res is None:
        return None
    if "pdf text layer" in sheet["readers"] and res.get("answer") is not None and res.get("unit") == "count" \
            and res["confidence"] >= 0.8:
        res["confidence"] = max(res["confidence"], 0.9)  # exact vector text: misses come only from the parsing
    res["cost_usd"] = round(sum(cost), 5)
    res["readers"] = sheet["readers"]
    pdf = "pdf text layer" in sheet["readers"]
    res.setdefault("sheet_how", "read from the PDF's text" if pdf else "read from the sheet (OCR + vision)")
    if meta.get("low_res") or (not pdf and sheet.get("image") and _small(sheet["image"])):
        res["low_res"] = True
    res["method"] = METHOD
    return res
