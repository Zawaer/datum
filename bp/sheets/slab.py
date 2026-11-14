"""Structural slab / foundation plans: slab area by type (thickness + bars), reinforcement, trenches, sumps,
control-joint panels, bottom-reinforcement pads.

Pipeline (cached once per upload in meta["slab"]):
  1. text   : PDF text layer if present, else Tesseract (bp.sheets.ocr_words, x3 upscale on small rasters, plus a
              90-degree-rotated pass for vertical dimension strings); Haiku vision transcription as the last resort.
  2. notes  : OCR lines grouped into blocks; a block with "SLAB" and a thickness / bar spec ("300 SLAB-ON-GRADE W/ D16
              @ 300 ... TOP OF SLAB EL. = 9400") defines a slab type. Trench lengths, sumps, CJ labels, scale.
  3. scale  : mm per px from the dimension strings (consecutive numbers of one dimension chain: their centres are
              (a+b)/2 mm apart), cross-checked against the overall extent of the slab outline.
  4. regions: enclosed white areas of the drawing (flood fill), thin wall bands trimmed by an opening; areas only
              separated by thin lines (control joints, dimension lines) merge into one slab zone; zones walled on
              all sides are slab zones. Each zone becomes a rectilinear polygon and is grown outward to the outer
              face of its edge beam (shared walls split half-half), so the areas match the dimension strings.
  5. typing : a note inside a zone types it; zones left untyped take the nearest unused note outside the
              building (notes with leaders).
  6. answers: arithmetic over the zones, with the side lengths snapped to printed dimensions where they agree.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

METHOD = "sheets-slab"
WALL_BAND = 0.009  # wall band (edge beam) width bound, share of the long image side
_DEBUG: list = []
_LAST: dict = {}
_BAR = r"(?:[DTYHRN]\s?\d{1,2}|#\s?\d{1,2}|Ø\s?\d{1,2}|\d{1,2}\s?M)"
_BAR_RE = re.compile(rf"(?<![\w#])({_BAR})\s*(?:@|AT|C/C|CC|c/c)\s*(\d{{1,4}}\s*(?:\"|IN\b)?(?:\s*O\.?\s?C\.?(?:\s?E\.?W\.?)?)?)",
                     re.I)
_THK_RE = re.compile(r"\b(\d{2,3}|\d{1,2}(?:\s*\"|\s*IN\.?|\s*INCH))\s*(?:MM\s*)?(?:THK\.?\s*|THICK\s*)?(?:CONCRETE\s*)?"
                     r"(?:SLAB|SOG|S\.O\.G)", re.I)
# feet-inches dimension strings: 40'-8", 1' - 0", 8", 3'-2 1/2"
_FTIN_RE = re.compile(r"(?<![\d/])(?:(\d{1,3})\s*'\s*-?\s*)?(?:(\d{1,2})(?:\s+(\d)/(\d{1,2}))?\s*\")|(?<![\d/])(\d{1,3})\s*'(?!\s*-?\s*\d)")


def _ftin_mm(m) -> float | None:
    ft, inch, num, den, ft_only = m.groups()
    if ft_only:
        return int(ft_only) * 304.8
    v = (int(ft) if ft else 0) * 12 + (int(inch) if inch else 0) + (int(num) / int(den) if num else 0)
    return v * 25.4 if v else None


def _fmt_ftin(mm: float) -> str:
    inch = round(mm / 25.4)
    return f"{inch // 12}'-{inch % 12}\""


def _dim_tokens(words, vertical):
    """Feet-inches dimensions spread over several words ("40'", "-", "8\""): joined per text line, parsed, boxed."""
    from bp.sheets import ocr_lines

    if not words:
        return []
    # vertical dimension text reads bottom-to-top: rotate it into a left-to-right line (x' = -y, y' = x)
    T = (lambda b: [-b[3], b[0], -b[1], b[2]]) if vertical else (lambda b: b)
    Ti = (lambda b: [b[1], -b[2], b[3], -b[0]]) if vertical else (lambda b: b)
    ws = [{**w, "bbox": T(w["bbox"])} for w in words]
    out = []
    for ln in ocr_lines(ws):
        parts = sorted(ln["words"], key=lambda w: w["bbox"][0])
        text, spans = "", []
        for w in parts:
            if text:
                text += " "
            spans.append((len(text), len(text) + len(w["text"]), w))
            text += w["text"]
        for m in _FTIN_RE.finditer(text):
            v = _ftin_mm(m)
            if not v:
                continue
            used = [w for a, b, w in spans if a < m.end() and b > m.start()]
            bb = [min(w["bbox"][0] for w in used), min(w["bbox"][1] for w in used),
                  max(w["bbox"][2] for w in used), max(w["bbox"][3] for w in used)]
            out.append({"text": m.group(0), "v": v, "bbox": Ti(bb), "conf": min(w.get("conf", 99) for w in used)})
    return out
_EL_RE = re.compile(r"EL(?:EV)?\.?\s*[=:]?\s*\+?\s*(-?\d[\d.,]*)", re.I)


# ----------------------------------------------------------------------------------------------- detect
def detect(meta) -> float:
    blob = f"{meta.get('title', '')} {meta.get('text', '')[:30000]}"
    s = 0.8 if meta.get("kind") == "slab" else 0.0
    if re.search(r"foundation|slab[- ]on[- ]grade|slab plan|\bS-?1\d\d", meta.get("title", ""), re.I):
        s = max(s, 0.85)
    if re.search(r"FOUNDATION AND SLAB PLAN|SLAB PLAN|\d{2,3}\s*(?:MM\s*)?SLAB[- ]ON[- ]GRADE", blob, re.I):
        s = max(s, 0.8)
    hits = len(re.findall(r"slab|foundation|footing|reinforc|rebar|S\.?O\.?G|\bD\d{2}\s*@", blob, re.I))
    s = min(1.0, s + min(0.2, 0.04 * hits))
    if meta.get("kind") != "slab" and re.search(r"PIP(?:E|ING)\s+SUPPORT", meta.get("title", ""), re.I):
        s = min(s, 0.5)  # "PIPE SUPPORT PLAN S-101": a structural sheet number, but the piping module's PS tags
    return s


# ----------------------------------------------------------------------------------------------- text
def _num(s: str):
    t = s.replace(",", "").replace(" ", "")
    if re.fullmatch(r"\d{2,6}", t):
        return int(t)
    return None


def _pdf_vertical_words(meta):
    """{(text, cx, cy): is_vertical} for the PDF page's words, from each text line's writing direction as displayed
    (short vertical words like 14' are not recognisable from their box shape). None if not a PDF."""
    path = str(meta.get("path") or "")
    if not path.lower().endswith(".pdf"):
        return None
    try:
        import pymupdf

        pg = pymupdf.open(path)[meta.get("page", 0)]
        R = pg.rotation_matrix
        W, H = pg.rect.width, pg.rect.height
        dirs = {}
        d = pg.get_text("dict")
        for bi, b in enumerate(d.get("blocks", [])):
            for li, ln in enumerate(b.get("lines", [])):
                dx, dy = ln.get("dir", (1, 0))
                q = pymupdf.Point(dx, dy) * R - pymupdf.Point(0, 0) * R
                dirs[(b.get("number", bi), li)] = abs(q.y) > abs(q.x)
        out = {}
        for x0, y0, x1, y1, t, bno, lno, _wno in pg.get_text("words"):
            r = pymupdf.Rect(x0, y0, x1, y1) * R
            r.normalize()
            out[(t, round((r.x0 + r.x1) / 2 / W, 3), round((r.y0 + r.y1) / 2 / H, 3))] = dirs.get((bno, lno), False)
        return out
    except Exception:  # noqa: BLE001
        return None


def _ocr(meta) -> tuple[list[dict], list[dict], str]:
    """(horizontal words, vertical words, source). Words: {"text","bbox" (normalised),"conf"}."""
    from bp.sheets import ocr_words

    pw = meta.get("words") if meta.get("text_source", "pdf") == "pdf" else None
    if not pw:
        path = str(meta.get("path") or "")
        if path.lower().endswith(".pdf"):
            from bp.sheets import pdf_words

            pw = pdf_words(path, meta.get("page", 0))
    if pw and len(pw) > 30:
        Wi, Hi = meta.get("w") or 1, meta.get("h") or 1
        vdirs = _pdf_vertical_words(meta)
        hor, ver = [], []
        for w in pw:
            x0, y0, x1, y1 = w["bbox"]
            key = (w["text"], round((x0 + x1) / 2, 3), round((y0 + y1) / 2, 3))
            if vdirs is not None and key in vdirs:
                vert = vdirs[key]
            else:
                vert = len(w["text"]) >= 2 and (y1 - y0) * Hi > 1.5 * (x1 - x0) * Wi
            (ver if vert else hor).append({**w, "conf": 99.0, "vertical": vert})
        return hor, ver, "pdf-text"
    w = meta.get("w") or 2000
    scale = 3.0 if w < 3000 else (2.0 if w < 6000 else 1.0)
    hor = ocr_words(meta, scale=scale, psm=11)
    if not hor:
        return [], [], "none"
    # rotated pass for vertical dimension strings (text reading bottom-to-top)
    ver = meta.get("_slab_rot_ocr")
    if ver is None:
        ver = []
        try:
            from PIL import Image

            Image.MAX_IMAGE_PIXELS = None
            rp = Path(meta.get("_slab_cache_dir") or Path(meta["image"]).parent) / (Path(meta["image"]).stem + ".rot90.png")
            if not rp.exists():
                Image.open(meta["image"]).convert("L").rotate(-90, expand=True).save(rp)
            for x in ocr_words({"image": str(rp)}, scale=scale, psm=11):
                a0, b0, a1, b1 = x["bbox"]  # in the rotated image (rotated clockwise): x' = 1 - y, y' = x
                ver.append({"text": x["text"], "conf": x["conf"], "vertical": True, "bbox": [b0, 1 - a1, b1, 1 - a0]})
            meta["_slab_rot_ocr"] = ver
        except Exception as e:  # noqa: BLE001
            log.warning("slab: rotated OCR failed: %s", e)
    return hor, ver, "tesseract"


def _blocks(lines: list[dict]) -> list[dict]:
    """Group text lines into note blocks (lines stacked with a small gap and overlapping in x)."""
    blocks: list[dict] = []
    for ln in sorted(lines, key=lambda l: l["bbox"][1]):
        h = ln["bbox"][3] - ln["bbox"][1]
        for b in blocks:
            bb = b["bbox"]
            last = b["lines"][-1]["bbox"]
            gap = ln["bbox"][1] - last[3]
            ov = min(bb[2], ln["bbox"][2]) - max(bb[0], ln["bbox"][0])
            nb = [min(bb[0], ln["bbox"][0]), min(bb[1], ln["bbox"][1]), max(bb[2], ln["bbox"][2]), max(bb[3], ln["bbox"][3])]
            small = (nb[2] - nb[0]) < 0.2 and (nb[3] - nb[1]) < 0.12
            if small and -0.5 * h < gap < 1.2 * h and ov > 0 and abs(ln["bbox"][0] - last[0]) < 6 * h:
                b["lines"].append(ln)
                b["bbox"] = [min(bb[0], ln["bbox"][0]), min(bb[1], ln["bbox"][1]), max(bb[2], ln["bbox"][2]),
                             max(bb[3], ln["bbox"][3])]
                break
        else:
            blocks.append({"lines": [ln], "bbox": list(ln["bbox"])})
    for b in blocks:
        b["text"] = " ".join(l["text"] for l in b["lines"])
    return blocks


def _parse_type(text: str) -> dict | None:
    t = text.upper().replace("SLAB-ON- GRADE", "SLAB-ON-GRADE").replace("SLAB-ON GRADE", "SLAB-ON-GRADE")
    if "SLAB" not in t:
        return None
    m = _THK_RE.search(t)
    bars = _BAR_RE.findall(t)
    if not m and not bars:
        return None
    if re.search(r"TRENCH LENGTH|SEE SHEET|NOTES?:", t) and not m:
        return None
    el = _EL_RE.search(t)
    bar = [re.sub(r"\s", "", b).upper() + " @ " + re.sub(r"\s+", " ", s).strip() for b, s in bars]
    thk_mm = thk_in = None
    if m:
        g1 = m.group(1)
        if re.search(r"\"|IN", g1):
            thk_in = int(re.match(r"\d+", g1).group(0))
            if thk_in < 4:  # no slab is under 4": OCR lost the leading 1 of a 12" / 10" on a small scan
                thk_in += 10
            thk_mm = round(thk_in * 25.4)
        else:
            thk_mm = int(g1)
    faces = []
    if re.search(r"TOP FACE|\bT\.?F\.?\b|\bT\s*&\s*B\b|EACH FACE|\bE\.?F\.?\b", t):
        faces.append("top")
    if re.search(r"BOTTOM FACE|\bB\.?F\.?\b|\bT\s*&\s*B\b|EACH FACE|\bE\.?F\.?\b", t):
        faces.append("bottom")
    return {"thickness_mm": thk_mm, "thickness_in": thk_in, "bars": bar,
            "default": bool(re.search(r"U\.?N\.?O\.?|UNLESS (?:OTHERWISE )?NOTED|TYP(?:ICAL)?\b", t)),
            "elevation": el.group(1).rstrip(".,") if el else None, "faces": faces,
            "bottom_as_indicated": bool(re.search(r"BOTTOM FACE REINF\w* AS INDICATED", t)),
            "kind": "slab-on-grade" if "ON-GRADE" in t or "SOG" in t else "slab"}


def _type_name(ty: dict) -> str:
    if ty.get("thickness_in"):
        s = f"{ty['thickness_in']}\" ({ty['thickness_mm']} mm)"
    else:
        s = f"{ty['thickness_mm']} mm" if ty.get("thickness_mm") else "slab"
    if ty.get("bars"):
        s += " w/ " + ", ".join(ty["bars"])
    return s


# ----------------------------------------------------------------------------------------------- geometry
_INK_FREE: dict = {}  # path -> grey (the last two sheets: analyse() reads it three times)


def _ink_free_gray(path):
    key = (path, os.path.getmtime(path) if os.path.exists(path) else 0)
    if key in _INK_FREE:
        return _INK_FREE[key].copy()
    g = _ink_free_gray_read(path)
    while len(_INK_FREE) >= 2:
        _INK_FREE.pop(next(iter(_INK_FREE)))
    _INK_FREE[key] = g
    return g.copy()


def _ink_free_gray_read(path):
    """The sheet in greyscale with coloured hand markings (red / green / blue pen: check marks, circles, underlines on a
    marked-up scan) inpainted away: in plain grey they are dark strokes, and one across a room splits its slab zone
    in two. Only when the colour is sparse (a few marks over a black-ink drawing); a drawing printed in colour is
    left alone."""
    import cv2
    import numpy as np

    c = cv2.imread(path, cv2.IMREAD_COLOR)
    if c is None:
        return cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
    sat = (c.max(axis=2).astype(np.int16) - c.min(axis=2)) > 45
    dark = g < 200
    n_col = int((sat & (g < 235)).sum())
    if not n_col or n_col > 0.25 * max(1, int(dark.sum())):
        return g
    S = max(g.shape)
    r = max(1, round(S / 2500))
    m = cv2.dilate(sat.astype(np.uint8), np.ones((2 * r + 1, 2 * r + 1), np.uint8)) > 0
    # what lies under a marking is filled in from around it (inpainting): a wall line crossed by a pen stroke
    # stays continuous instead of getting a paper-coloured gap the slab zone would leak through
    keep = (c.max(axis=2) < 110) & ~sat  # black ink next to the stroke is never touched
    return cv2.inpaint(g, (m & ~keep).astype(np.uint8), max(3, 2 * r), cv2.INPAINT_TELEA)


def _gray(meta, max_side=2000, stretch=True):
    import cv2

    g = _ink_free_gray(meta["image"])
    f = 1.0
    if max(g.shape) > max_side:
        f = max_side / max(g.shape)
        g = cv2.resize(g, (round(g.shape[1] * f), round(g.shape[0] * f)), interpolation=cv2.INTER_AREA)
    # scans and photos: grey paper, faded ink. Stretch so the paper is white and the ink dark, like a clean render
    import numpy as np

    paper = float(np.percentile(g, 60))
    ink = float(np.percentile(g, 0.5))
    if stretch == "paper":
        # gain only (grey paper -> light grey 235, ink kept dark, noise not amplified): on unscaled grey paper (~220)
        # the segmentation's ink threshold (200) sits just under the paper, so a blurred thin line (a dimension line
        # across a room) reads several pixels wide and closes off the paper between dimension lines; scaled to
        # pure white, faint wall lines drop under the threshold and rooms leak
        if ink > 120 and paper - ink > 30:
            # faded scan (the darkest ink is mid-grey): lines sit above the threshold and rooms leak. Stretch the
            # ink to dark and the paper to 235, smoothing the amplified noise first
            import cv2

            g = cv2.medianBlur(g, 3)
            g = np.clip((g.astype(np.float32) - ink) * (195.0 / (paper - ink)) + 40, 0, 255).astype(np.uint8)
        elif paper >= 245 and ink > 80 and os.environ.get("SLAB_FAINT", "1") == "1":
            # clean paper but faint ink (a scan of a hi-res render, downscaled: wall outlines mid-grey and broken
            # under the threshold, rooms leak into each other): the ink is darkened, the paper left
            g = np.clip((g.astype(np.float32) - ink) * ((paper - 20.0) / (paper - ink)) + 20, 0, 255).astype(np.uint8)
        elif 120 < paper < 235:
            g = np.clip(g.astype(np.float32) * (235.0 / paper), 0, 255).astype(np.uint8)
        return g, f
    if stretch and (paper < 245 or ink > 40):
        if paper - ink > 30:
            g = np.clip((g.astype(np.float32) - ink) * 255.0 / (paper - ink), 0, 255).astype(np.uint8)
    return g, f


def _shade_mask(g):
    """Hatched / shaded areas: dense small marks (a lossy raster breaks hatch lines into dots), closed into blobs."""
    import cv2
    import numpy as np

    S = max(g.shape)
    d = (g < 200).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(d, connectivity=8)
    lim = max(4, round(S * 0.002))
    small = (st[:, 2] <= lim) & (st[:, 3] <= lim) & (st[:, 4] <= lim * lim)
    small[0] = False
    diag = _diag_strokes(d, S)
    m = (small[lab] | (diag > 0)).astype(np.float32)
    r = max(7, round(S * 0.0075)) | 1
    den = cv2.blur(m, (r, r))
    out = (den > 0.06).astype(np.uint8)
    out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, np.ones((r, r), np.uint8))
    return cv2.morphologyEx(out, cv2.MORPH_OPEN, np.ones((r, r), np.uint8))


def _diag_strokes(dark, S):
    import cv2
    import numpy as np

    L = max(7, round(S * 0.0045))
    k1 = np.eye(L, dtype=np.uint8)
    return cv2.morphologyEx(dark, cv2.MORPH_OPEN, k1) | cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.fliplr(k1).copy())


def _erase_pdf_shading(meta, g):
    """Vector PDF: erase the grey hatch strokes (shaded bottom-reinforcement areas) before segmenting, so shaded
    pads never split a slab zone. Only pixels no black stroke (wall, joint, outline) passes through are erased.
    Rasters: unchanged."""
    if not str(meta.get("path") or "").lower().endswith(".pdf"):
        return g
    try:
        import cv2
        import numpy as np

        from bp.sheets import pdf_paths

        H, W = g.shape
        hatch = np.zeros((H, W), np.uint8)
        black = np.zeros((H, W), np.uint8)

        def draw(m, it, t):
            if it[0] == "l":
                (x0, y0), (x1, y1) = it[1], it[2]
                cv2.line(m, (round(x0 * W), round(y0 * H)), (round(x1 * W), round(y1 * H)), 1, t)
            elif it[0] == "re":
                x0, y0, x1, y1 = it[1]
                cv2.rectangle(m, (round(x0 * W), round(y0 * H)), (round(x1 * W), round(y1 * H)), 1, t)
            elif it[0] in ("c", "qu"):
                pts = np.array([(round(x * W), round(y * H)) for x, y in it[1:]], np.int32)
                cv2.polylines(m, [pts], it[0] == "qu", 1, t)

        for d in pdf_paths(meta):
            c = d.get("stroke")
            if not c:
                continue
            grey = 0.03 < max(c) < 0.7
            for it in d["items"]:
                draw(hatch if grey else black, it, 3 if grey else 2)
        if not hatch.any():
            return g
        out = g.copy()
        out[(hatch > 0) & (cv2.dilate(black, np.ones((3, 3), np.uint8)) == 0)] = 255
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("slab: could not erase PDF shading: %s", e)
        return g


def _erase_raster_shading(g):
    """Raster (no vector paths): erase the diagonal hatch strokes (the shaded bottom-reinforcement areas) inside the
    hatched blobs of _shade_mask before segmenting, keeping long straight lines (walls, joints, outlines) and the
    stipple of wall bands. On a scan the hatch strokes read as solid ink, so a hatched strip along a wall was cut out
    of its slab zone. Scans only (grey paper): on a clean render the thin hatch never blocks the flood fill."""
    import cv2
    import numpy as np

    try:
        sh = _shade_mask(g)
        if not sh.any():
            return g
        S = max(g.shape)
        dark = (g < 200).astype(np.uint8)
        L = max(15, round(S * 0.02))
        lines = (cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((1, L), np.uint8))
                 | cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((L, 1), np.uint8)))
        lines = cv2.dilate(lines, np.ones((3, 3), np.uint8))
        out = g.copy()
        diag = cv2.dilate(_diag_strokes(dark, S), np.ones((3, 3), np.uint8))
        out[(sh > 0) & (diag > 0) & (dark > 0) & (lines == 0)] = 255
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("slab: could not erase raster shading: %s", e)
        return g


def _chains_px(spans, vertical, tol=3.0, gap=0.0):
    """Dimension lines as (cross coordinate, lo, hi) runs: all spans on one line merged (outliers included: their
    ends may be off, but the line's extent is right)."""
    rows: list = []
    for d in spans:
        c = d["span"][0] if vertical else d["span"][1]
        lo, hi = (d["span"][1], d["span"][3]) if vertical else (d["span"][0], d["span"][2])
        for r in rows:
            if abs(r[0] - c) <= tol and lo <= r[2] + tol + gap and hi >= r[1] - tol - gap:
                r[1], r[2] = min(r[1], lo), max(r[2], hi)
                break
        else:
            rows.append([c, lo, hi])
    return rows


def _dimension_zones(out_zones, types, used, dims, W, H, S):
    """Dimension-driven check of the raster zones (and zones for slab notes the flood missed):
    - a ragged zone (> 8 corners) or one that an interior dimension chain says is longer is rebuilt as the rectangle
      its dimension lines span; when that differs from the raster area by > 10 % the rectangle wins (and says so);
    - a slab note with no zone gets the rectangle of the smallest dimensions enclosing it."""
    from shapely.geometry import box as sbox

    hs = [d for d in dims if d.get("span") and not d["vertical"]]
    vs = [d for d in dims if d.get("span") and d["vertical"]]
    if not hs or not vs:
        return
    xt = sorted({c for d in hs if d.get("inlier") for c in (d["span"][0], d["span"][2])})
    yt = sorted({c for d in vs if d.get("inlier") for c in (d["span"][1], d["span"][3])})
    # a chain may only extend a zone when its strings measure true at the sheet's scale: a misread span (a scan's
    # blurred tick merging two stacked dimensions outside the wall) otherwise stretched a room past its wall
    ks = sorted(d["k"] for d in dims if d.get("inlier") and d.get("k"))
    kmed = ks[len(ks) // 2] if ks else None

    def true(d):
        return d.get("inlier") or kmed is None or (d.get("k") and abs(d["k"] / kmed - 1) < 0.12)

    hch = _chains_px([d for d in hs if true(d)], False, gap=0.025 * S)
    vch = _chains_px([d for d in vs if true(d)], True, gap=0.025 * S)
    tol = 0.012 * S
    snap_tol = 0.004 * S

    def snap(v, ticks):
        b = min(ticks, key=lambda t: abs(t - v), default=None)
        return float(b) if b is not None and abs(b - v) <= snap_tol else v

    for z in out_zones:
        pts = z["inner"]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        ragged = len(pts) > 8
        ext = []
        for c, lo, hi in vch:  # a vertical chain inside the zone measures its full length
            if x0 + tol < c < x1 - tol and lo < y1 and hi > y0 and (lo < y0 - tol or hi > y1 + tol):
                y0, y1 = min(y0, lo), max(y1, hi)
                ext.append("a vertical dimension chain inside the room")
        for c, lo, hi in hch:
            if y0 + tol < c < y1 - tol and lo < x1 and hi > x0 and (lo < x0 - tol or hi > x1 + tol):
                x0, x1 = min(x0, lo), max(x1, hi)
                ext.append("a horizontal dimension chain inside the room")
        if not ragged and not ext:
            continue
        r = [snap(x0, xt), snap(y0, yt), snap(x1, xt), snap(y1, yt)]
        a_dim = (r[2] - r[0]) * (r[3] - r[1])
        a_ras = z["inner_px"]
        if abs(a_dim - a_ras) / max(a_ras, 1e-9) <= 0.10:
            continue
        others = [sbox(*_bbox_pts(o["inner"])) for o in out_zones if o is not z]
        if any(sbox(*r).intersection(o).area > 0.03 * a_dim for o in others):
            continue
        why = "its traced outline was ragged" if ragged else ext[0] + " runs past the traced outline"
        z["raster_inner"], z["raster_px"] = pts, a_ras
        z["inner"] = [(r[0], r[1]), (r[0], r[3]), (r[2], r[3]), (r[2], r[1])]
        z["inner_px"] = a_dim
        z["dim_note"] = f"rebuilt from the dimension strings ({why}; traced area was {a_ras / a_dim * 100:.0f} % of it)"
    # slab notes without a zone
    for ti, t in enumerate(types):
        if ti in used:
            continue
        cx, cy = (t["bbox"][0] + t["bbox"][2]) / 2 * W, (t["bbox"][1] + t["bbox"][3]) / 2 * H
        hx = sorted([d for d in hs if d["span"][0] < cx < d["span"][2] and d["span"][2] - d["span"][0] >= 0.02 * S
                     and d.get("inlier")], key=lambda d: abs(d["span"][1] - cy))
        if not hx:
            continue
        wpx = hx[0]["span"][2] - hx[0]["span"][0]
        vy = sorted([d for d in vs if d["span"][1] < cy < d["span"][3] and d["span"][3] - d["span"][1] >= 0.6 * wpx
                     and d.get("inlier")], key=lambda d: abs(d["span"][0] - cx))
        if not vy:
            continue
        r = [hx[0]["span"][0], vy[0]["span"][1], hx[0]["span"][2], vy[0]["span"][3]]
        if max(r[2] - r[0], r[3] - r[1]) > 0.5 * S:
            continue
        a_dim = (r[2] - r[0]) * (r[3] - r[1])
        if any(sbox(*r).intersection(sbox(*_bbox_pts(o["inner"]))).area > 0.15 * a_dim for o in out_zones):
            continue
        pts = [(r[0], r[1]), (r[0], r[3]), (r[2], r[3]), (r[2], r[1])]
        out_zones.append({"inner": pts, "gross": pts, "inner_px": a_dim, "gross_px": a_dim, "stair_parts": [],
                          "panels": 1, "cuts": [], "walled": None, "type": ti, "centroid": [cx, cy],
                          "type_how": "room spanned by the dimension strings around the note",
                          "dim_note": "the traced outline missed this room: built from the dimension strings"})
        used.add(ti)


def _merge_untyped(out_zones, S):
    """A zone left without any slab note that lies across one thin line (a joint, a dimension or hidden line the
    flood fill could not bridge, typical of a blurred scan) from a zone with a note is the rest of that slab: merged
    into it. Zones apart by a wall band (a gap wider than a line) stay separate."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    gap = max(4.0, 0.004 * S)
    for z in [z for z in out_zones if z["type"] is None and (z.get("walled") or 0) >= 0.95]:
        try:
            pz = Polygon(z["inner"]).buffer(0)
        except Exception:  # noqa: BLE001
            continue
        if pz.is_empty:
            continue
        x0, y0, x1, y1 = pz.bounds
        side = min(x1 - x0, y1 - y0)
        best = None
        for t in out_zones:
            if t is z or t["type"] is None:
                continue
            pt = Polygon(t["inner"]).buffer(0)
            if pt.is_empty or pz.distance(pt) > gap or pz.area > pt.area:
                continue
            shared = pz.buffer(gap, join_style=2).intersection(pt.buffer(gap, join_style=2)).area / (2 * gap)
            if shared >= 0.5 * side and (best is None or shared > best[0]):
                best = (shared, t, pt)
        if best is None:
            continue
        _, t, pt = best
        h = gap / 2 + 1
        u = unary_union([pz.buffer(h, join_style=2), pt.buffer(h, join_style=2)]).buffer(-h, join_style=2)
        g = unary_union([Polygon(z["gross"]).buffer(h, join_style=2),
                         Polygon(t["gross"]).buffer(h, join_style=2)]).buffer(-h, join_style=2)
        if u.geom_type != "Polygon" or g.geom_type != "Polygon":
            continue
        u, g = u.simplify(1.5), g.simplify(1.5)
        env = u.envelope
        others = [Polygon(o["inner"]).buffer(0) for o in out_zones if o is not t and o is not z]
        if u.area >= 0.9 * env.area and not any(env.intersection(o).area > 0.01 * env.area for o in others):
            # the two parts fill their bounding rectangle but for details the flood fill went round (a trench
            # outline in a corner): the slab is the rectangle
            u = env
        t["inner"] = [(float(x), float(y)) for x, y in list(u.exterior.coords)[:-1]]
        t["gross"] = [(float(x), float(y)) for x, y in list(g.exterior.coords)[:-1]]
        t["inner_px"], t["gross_px"] = u.area, g.area
        t["panels"] = (t.get("panels") or 1) + (z.get("panels") or 1)
        t["cuts"] = list(t.get("cuts") or []) + list(z.get("cuts") or [])
        t["stair_parts"] = list(t.get("stair_parts") or []) + list(z.get("stair_parts") or [])
        t["centroid"] = [float(u.centroid.x), float(u.centroid.y)]
        t["merged_note"] = "a part with no note of its own across a thin line was added"
        out_zones.remove(z)


def _bbox_pts(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _read_zone_note(meta, z, W, H):
    """Haiku transcription of the slab note inside one zone (crop of the full-resolution image). (type | None, cost)"""
    from PIL import Image

    from bp.generic import llm

    Image.MAX_IMAGE_PIXELS = None
    x0, y0, x1, y1 = _bbox_pts(z["inner"])
    cache = meta.setdefault("_slab_reads", {})
    key = f"zone:{x0 / W:.3f},{y0 / H:.3f},{x1 / W:.3f},{y1 / H:.3f}"
    cost = 0.0
    if key not in cache:
        im = Image.open(meta["image"]).convert("L")
        IW, IH = im.size
        crop = im.crop((round(x0 / W * IW), round(y0 / H * IH), round(x1 / W * IW), round(y1 / H * IH)))
        crop.thumbnail((1568, 1568), Image.LANCZOS)
        r = llm.ask("Crop of one room of a structural slab / foundation plan. Transcribe the slab note in it exactly "
                    "(e.g. '300 SLAB-ON-GRADE W/ D16 @ 300 TOP FACE ... TOP OF SLAB EL. = 9400'), with its centre as "
                    'fractions of the crop. JSON only: {"note": "..." or null, "x": 0..1, "y": 0..1}',
                    [crop.convert("RGB")], model="haiku", tag="sheets-slab-zone-note", timeout=90)
        cost = float(r.get("cost_usd") or 0.0)
        d = llm.parse_json(r["text"]) or {}
        cache[key] = d if isinstance(d, dict) else {}
    d = cache[key]
    ty = _parse_type(str(d.get("note") or ""))
    if not ty or not ty.get("thickness_mm"):
        return None, cost
    try:
        fx, fy = float(d.get("x", 0.5)), float(d.get("y", 0.5))
    except (TypeError, ValueError):
        fx, fy = 0.5, 0.5
    cx, cy = (x0 + fx * (x1 - x0)) / W, (y0 + fy * (y1 - y0)) / H
    ty.update({"text": str(d["note"]), "bbox": [cx - 0.02, cy - 0.01, cx + 0.02, cy + 0.01]})
    return ty, cost


def _deskew(g):
    """Level a slightly rotated scan: median angle of its long near-horizontal / near-vertical lines. Returns
    (g, inverse 2x3 affine or None)."""
    import cv2
    import numpy as np

    H, W = g.shape
    S = max(H, W)
    edges = (g < 128).astype(np.uint8) * 255
    lines = cv2.HoughLinesP(edges, 1, np.pi / 1800, threshold=int(S * 0.08), minLineLength=int(S * 0.12),
                            maxLineGap=int(S * 0.004))
    if lines is None:
        return g, None
    angs = []
    for x0, y0, x1, y1 in lines.reshape(-1, 4):
        a = math.degrees(math.atan2(y1 - y0, x1 - x0))
        a = (a + 45) % 90 - 45  # fold vertical onto horizontal
        if abs(a) < 3:
            angs.append(a)
    if len(angs) < 5:
        return g, None
    ang = float(np.median(angs))
    if abs(ang) < 0.15:
        return g, None
    M = cv2.getRotationMatrix2D((W / 2, H / 2), ang, 1.0)
    g2 = cv2.warpAffine(g, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=255)
    return g2, cv2.invertAffineTransform(M)


def _unrotate(out_zones, pads, Minv):
    def tp(p):
        x, y = p
        return (float(Minv[0, 0] * x + Minv[0, 1] * y + Minv[0, 2]), float(Minv[1, 0] * x + Minv[1, 1] * y + Minv[1, 2]))

    for z in out_zones:
        for key in ("inner", "gross", "raster_inner"):
            if z.get(key):
                z[key] = [tp(p) for p in z[key]]
        z["stair_parts"] = []
        cuts = []
        for o, x, y, w, h in z.get("cuts", []):
            cx, cy = tp((x + w / 2, y + h / 2))
            cuts.append((o, cx - w / 2, cy - h / 2, w, h))
        z["cuts"] = cuts
    for pd in pads:
        pd["poly"] = [list(tp(p)) for p in pd["poly"]]
        xs, ys = [p[0] for p in pd["poly"]], [p[1] for p in pd["poly"]]
        pd["bbox"] = [min(xs), min(ys), max(xs), max(ys)]


def _bbox(m):
    import numpy as np

    ys, xs = np.nonzero(m)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else (0, 0, 0, 0)


def _min_side(m):
    x0, y0, x1, y1 = _bbox(m)
    return min(x1 - x0, y1 - y0)


def _zones(g, k=None, joint_pts=None):
    """Slab zones: list of {"mask"}. Enclosed white areas (hatch strokes ignored); thin strips (wall bands between
    their outlines) dropped; areas separated only by a thin line (control joint, dimension line) merged."""
    import cv2
    import numpy as np

    H, W = g.shape
    S = max(H, W)
    dark = (g < 200).astype(np.uint8)
    d = cv2.dilate(dark, np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats((1 - d).astype(np.uint8), connectivity=4)
    lab0 = lab.copy()
    min_a = 0.0004 * W * H
    # wall bands (edge beams up to ~0.8 m) must not survive the opening as panels of their own
    ko = max(9, round(S * 0.011)) | 1
    kopen = cv2.getStructuringElement(cv2.MORPH_RECT, (ko, ko))
    keep = {}
    lab2 = np.zeros_like(lab)
    nxt = 1
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < min_a or x <= 3 or y <= 3 or x + w >= W - 3 or y + h >= H - 3 or w > 0.9 * W or h > 0.9 * H:
            continue
        m = (lab[y:y + h, x:x + w] == i).astype(np.uint8)
        core = cv2.morphologyEx(m, cv2.MORPH_OPEN, kopen)
        # thin parts (wall-band strips between their outlines) are cut off; each remaining core is a panel
        nc, lc, sc, _ = cv2.connectedComponentsWithStats(core, connectivity=4)
        for j in range(1, nc):
            if sc[j, 4] < min_a:
                continue
            cj = (lc == j).astype(np.uint8) & (lab2[y:y + h, x:x + w] == 0)
            lab2[y:y + h, x:x + w][cj > 0] = nxt
            ys, xs = np.nonzero(cj)
            keep[nxt] = (x + xs.min(), y + ys.min(), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1, int(cj.sum()))
            nxt += 1
    lab = lab2
    r = max(5, round(S * 0.0028))
    min_touch = max(15, round(S * 0.008))
    parent = {i: i for i in keep}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    # a bold joint line (2-3x a thin line) separates panels further apart; it is merged across only where a joint
    # label ("CJ", "EJ", "CJ AND STEP") sits on it, so a wall band is never bridged by mistake
    rb = max(r + 3, round(S * 0.0045))
    labels = np.array(joint_pts or [], dtype=float).reshape(-1, 2)
    ker = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * r + 1, 2 * r + 1))
    kerb = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * rb + 1, 2 * rb + 1))
    for i, (x, y, w, h, _a) in keep.items():
        x0, y0, x1, y1 = max(0, x - rb), max(0, y - rb), min(W, x + w + rb), min(H, y + h + rb)
        sub = lab[y0:y1, x0:x1]
        me = (sub == i).astype(np.uint8)
        ring = cv2.dilate(me, ker) & (sub != i)
        js, cnt = np.unique(sub[ring > 0], return_counts=True)
        for j, c in zip(js, cnt):
            if j in keep and j != i and c >= min_touch:
                parent[find(i)] = find(j)
                if _DEBUG: _DEBUG.append((i, j, int(c), keep[i], keep[j]))
        if len(labels):
            ringb = cv2.dilate(me, kerb) & (sub != i)
            for j in np.unique(sub[ringb > 0]):
                if j not in keep or j == i or find(j) == find(i):
                    continue
                ys, xs = np.nonzero(ringb & (sub == j))
                if len(xs) < min_touch:
                    continue
                gx, gy = xs + x0, ys + y0
                bx0, bx1, by0, by1 = gx.min() - 2 * rb, gx.max() + 2 * rb, gy.min() - 2 * rb, gy.max() + 2 * rb
                if ((labels[:, 0] > bx0) & (labels[:, 0] < bx1) & (labels[:, 1] > by0) & (labels[:, 1] < by1)).any():
                    parent[find(i)] = find(j)
    groups: dict = {}
    for i in keep:
        groups.setdefault(find(i), []).append(i)
    kc = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * r + 3, 2 * r + 3))
    cands = []
    for idx in groups.values():
        if sum(keep[i][4] for i in idx) < 0.004 * W * H:
            continue
        m = cv2.morphologyEx(np.isin(lab, idx).astype(np.uint8), cv2.MORPH_CLOSE, kc)
        cands.append((m, _ring_walled(g, m)))
    _LAST["cands"] = cands
    zones = [m for m, wl in cands if wl >= 0.75 and _min_side(m) >= 0.05 * S]
    if zones:  # slab zones form one building: keep the cluster around the largest zone (drops title-block cells)
        boxes = [_bbox(m) for m in zones]
        big = max(range(len(zones)), key=lambda i: zones[i].sum())
        near, grow = {big}, True
        gap = 0.04 * S
        while grow:
            grow = False
            for i, b in enumerate(boxes):
                if i not in near and any(b[0] - gap < boxes[j][2] and boxes[j][0] - gap < b[2] and
                                         b[1] - gap < boxes[j][3] and boxes[j][1] - gap < b[3] for j in near):
                    near.add(i)
                    grow = True
        zones = [zones[i] for i in sorted(near)]
    # outside = the paper around the building: open areas not walled in (between dimension chains, sheet margin)
    outside = np.zeros((H, W), np.uint8)
    for m, wl in cands:
        if wl < 0.75:
            outside |= m
    big = (st[:, 4] > 0.02 * W * H)
    big[0] = False
    for i in np.nonzero(big)[0]:
        x, y, w, h, a = st[i]
        if x <= 3 or y <= 3 or x + w >= W - 3 or y + h >= H - 3 or w > 0.9 * W or h > 0.9 * H:
            outside[lab0 == i] = 1
    bw = max(5, round(S * WALL_BAND))
    kb = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * bw + 1, 2 * bw + 1))
    out_b = cv2.dilate(outside, kb)
    res = []
    for zi, m in enumerate(zones):
        other = np.zeros((H, W), np.uint8)
        for zj, m2 in enumerate(zones):
            if zj != zi:
                other |= m2
        # details inside the slab (hatching, trenches, symbols, text) break the white area: close over them,
        # but never across the wall band into the paper outside or a neighbouring zone
        free = ((out_b == 0) & (cv2.dilate(other, kb) == 0)).astype(np.uint8)
        nf, lf = cv2.connectedComponents(free, connectivity=4)
        ids = np.unique(lf[(m > 0) & (free > 0)])
        full = np.isin(lf, ids[ids > 0]).astype(np.uint8)
        # ... but only within the zone's own extent (the open paper outside is not always walled off)
        ys, xs = np.nonzero(m)
        box = np.zeros((H, W), np.uint8)
        box[max(0, ys.min() - 3):ys.max() + 4, max(0, xs.min() - 3):xs.max() + 4] = 1
        full = cv2.morphologyEx(full & box, cv2.MORPH_OPEN, kopen) | m
        cs, _ = cv2.findContours(full.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cs, key=cv2.contourArea)
        f = np.zeros((H, W), np.uint8)
        cv2.drawContours(f, [c], -1, 1, -1)
        res.append({"mask": f, "walled": dict((id(mm), wl) for mm, wl in cands).get(id(m), 1.0)})
    zones = res
    return zones, outside


def _ring_walled(g, m) -> float:
    """Share of a zone's surroundings (a ring just outside it) that is wall band (dense marks), not open paper."""
    import cv2
    import numpy as np

    S = max(g.shape)
    r1, r2 = max(3, round(S * 0.002)), max(10, round(S * 0.009))
    out1 = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_RECT, (2 * r1 + 1, 2 * r1 + 1)))
    out2 = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_RECT, (2 * r2 + 1, 2 * r2 + 1)))
    ring = (out2 > 0) & (out1 == 0)
    dark = (g < 215).astype(np.float32)
    den = cv2.blur(dark, (2 * r2 + 1, 2 * r2 + 1))
    # ring sampled along the boundary: a point counts as walled if the band beyond it carries marks
    return float(((den > 0.04) & ring).sum() / max(1, ring.sum()))


def _rect_poly(m, eps):
    """Rectilinear polygon (list of (x,y)) approximating the outer contour of mask m."""
    import cv2

    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea)
    ap = cv2.approxPolyDP(c, eps, True)[:, 0, :].astype(float)
    # edges -> orientation; merge runs of the same orientation, drop tiny jogs
    edges = []
    for i in range(len(ap)):
        p, q = ap[i], ap[(i + 1) % len(ap)]
        dx, dy = q[0] - p[0], q[1] - p[1]
        L = math.hypot(dx, dy)
        if L < 1e-6:
            continue
        o = "H" if abs(dx) >= abs(dy) else "V"
        edges.append([o, p, q, L])
    merged = []
    for e in edges:
        if merged and merged[-1][0] == e[0]:
            merged[-1][2] = e[2]
            merged[-1][3] += e[3]
            merged[-1].append(e)
        else:
            merged.append(list(e))
    if len(merged) > 1 and merged[0][0] == merged[-1][0]:
        merged[0][1] = merged[-1][1]
        merged[0][3] += merged[-1][3]
        merged.pop()
    # drop jogs shorter than 2*eps (merge their neighbours)
    changed = True
    while changed and len(merged) > 4:
        changed = False
        for i, e in enumerate(merged):
            if e[3] < 2 * eps:
                a, b = merged[i - 1], merged[(i + 1) % len(merged)]
                if a[0] == b[0]:
                    a[2] = b[2]
                    a[3] += b[3] + e[3]
                    for idx in sorted({i, (i + 1) % len(merged)}, reverse=True):
                        merged.pop(idx)
                    changed = True
                    break
    # each edge: its constant coordinate (median of the endpoints)
    lines = []
    for o, p, q, *_ in merged:
        c = (p[1] + q[1]) / 2 if o == "H" else (p[0] + q[0]) / 2
        lines.append((o, c, p, q))
    pts = []
    for i in range(len(lines)):
        a, b = lines[i - 1], lines[i]
        if a[0] == b[0]:
            continue
        x = b[1] if b[0] == "V" else a[1]
        y = b[1] if b[0] == "H" else a[1]
        pts.append((x, y))
    return pts


def _outward_offsets(g, zmask, pts, others, outside):
    """Per polygon edge, distance (px) from the inner face to the outer face of the edge beam: scan outward along
    samples of the edge until the open paper outside the building (or, for a shared wall, the neighbouring zone:
    half the wall each). Samples that reach neither take the median of the edges that did."""
    import numpy as np

    H, W = g.shape
    S = max(H, W)
    maxd = max(20, round(S * 0.025))
    offs = []
    n = len(pts)
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy) or 1
        nx, ny = dy / L, -dx / L
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        tx, ty = int(round(mx + nx * 4)), int(round(my + ny * 4))
        if 0 <= tx < W and 0 <= ty < H and zmask[ty, tx]:
            nx, ny = -nx, -ny
        vals, shared = [], 0
        for t in np.linspace(0.08, 0.92, 21):
            sx, sy = x0 + dx * t, y0 + dy * t
            for s in range(1, maxd):
                px, py = int(round(sx + nx * s)), int(round(sy + ny * s))
                if not (0 <= px < W and 0 <= py < H):
                    break
                if others[py, px]:
                    shared += 1
                    vals.append(s / 2)
                    break
                if outside[py, px]:
                    vals.append(s - 1.5)  # the outer face line was dilated by 1 px when the paper was found
                    break
        v = float(np.median(vals)) if len(vals) >= 5 else None
        offs.append([v, shared > len(vals) / 2, (nx, ny)])
    known = [o[0] for o in offs if o[0] is not None and not o[1]]
    fill = float(np.median(known)) if known else 0.0
    for o in offs:
        if o[0] is None:
            o[0] = fill
    return [tuple(o) for o in offs]


def _offset_poly(pts, offs):
    """Move each rectilinear edge outward by its offset; new vertices = intersections of consecutive edges."""
    n = len(pts)
    lines = []
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        v, _, (nx, ny) = offs[i]
        if abs(x1 - x0) >= abs(y1 - y0):
            lines.append(("H", (y0 + y1) / 2 + ny * v))
        else:
            lines.append(("V", (x0 + x1) / 2 + nx * v))
    out = []
    for i in range(n):
        a, b = lines[i - 1], lines[i]
        x = a[1] if a[0] == "V" else b[1]
        y = a[1] if a[0] == "H" else b[1]
        out.append((x, y))
    return out


def _clean_poly(pts):
    """Drop repeated and collinear vertices of a rectilinear polygon."""
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > 0.5 or abs(p[1] - out[-1][1]) > 0.5:
            out.append(p)
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) <= 0.5 and abs(out[0][1] - out[-1][1]) <= 0.5:
        out.pop()
    changed = True
    while changed and len(out) > 4:
        changed = False
        for i in range(len(out)):
            a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
            if (abs(a[0] - b[0]) <= 0.5 and abs(b[0] - c[0]) <= 0.5) or (abs(a[1] - b[1]) <= 0.5 and abs(b[1] - c[1]) <= 0.5):
                out.pop(i)
                changed = True
                break
    return out


def _rects(pts):
    """Rectilinear polygon -> disjoint rectangles (x0, y0, x1, y1), merged where they stack with equal x-range."""
    from shapely.geometry import Polygon, box

    P = Polygon(pts)
    ys = sorted({round(p[1], 1) for p in pts})
    xs = sorted({round(p[0], 1) for p in pts})
    rects = []
    for y0, y1 in zip(ys, ys[1:]):
        row = [(x0, x1) for x0, x1 in zip(xs, xs[1:]) if P.contains(box(x0, y0, x1, y1).centroid)]
        runs = []
        for x0, x1 in row:
            if runs and abs(runs[-1][1] - x0) < 0.5:
                runs[-1][1] = x1
            else:
                runs.append([x0, x1])
        for x0, x1 in runs:
            prev = next((r for r in rects if abs(r[0] - x0) < 0.5 and abs(r[2] - x1) < 0.5 and abs(r[3] - y0) < 0.5), None)
            if prev:
                prev[3] = y1
            else:
                rects.append([x0, y0, x1, y1])
    return sorted(rects, key=lambda r: -(r[2] - r[0]) * (r[3] - r[1]))


def _poly_area(pts):
    n = len(pts)
    return abs(sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))) / 2


def _refine_edges(g, pts, zmask):
    """Move each side of the clear-area polygon onto the wall's inner face: the most continuous straight line
    within ~0.6 % of the image of where the white area stopped (fill and closing can overshoot a few px)."""
    H, W = g.shape
    S = max(H, W)
    R = max(4, round(S * 0.006))
    dark = g < 180
    n = len(pts)
    lines = []
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        horiz = abs(x1 - x0) >= abs(y1 - y0)
        c = (y0 + y1) / 2 if horiz else (x0 + x1) / 2
        a0, a1 = sorted((x0, x1) if horiz else (y0, y1))
        L = a1 - a0
        lo, hi = int(a0 + 0.1 * L), int(a1 - 0.1 * L)
        best, bestf = c, 0.0
        if hi - lo >= 10:
            for d in range(-R, R + 1):
                cc = int(round(c + d))
                if not (0 <= cc < (H if horiz else W)):
                    continue
                f = float((dark[cc, lo:hi] if horiz else dark[lo:hi, cc]).mean())
                if f > bestf + 0.02 or (abs(f - bestf) <= 0.02 and abs(cc - c) < abs(best - c)):
                    best, bestf = cc, max(f, bestf)
        lines.append((horiz, best if bestf >= 0.8 else c))
    out = []
    for i in range(n):
        a, b = lines[i - 1], lines[i]
        x = a[1] if not a[0] else b[1]
        y = a[1] if a[0] else b[1]
        out.append((float(x), float(y)))
    return _clean_poly(out)


def _has_treads(g, r, k=None):
    """A stair drawn in plan: >= 4 parallel tread lines across most of the box, 3+ equal steps of 180-400 mm
    (either direction)."""
    import numpy as np

    H, W = g.shape
    x0, y0, x1, y1 = [int(round(v)) for v in r]
    pad = 3
    sub = g[max(0, y0 - pad):min(H, y1 + pad), max(0, x0 - pad):min(W, x1 + pad)]
    if sub.size == 0 or min(sub.shape) < 12:
        return False
    import cv2

    for a in (sub, np.ascontiguousarray(sub.T)):
        m = cv2.morphologyEx((a < 225).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((1, 7), np.uint8)) > 0
        n = a.shape[1]
        # a tread row: one continuous marked run over >= 45 % of the box width
        rows = []
        for i in range(m.shape[0]):
            row = m[i]
            best = run = 0
            for v in row:
                run = run + 1 if v else 0
                best = max(best, run)
            if best >= 0.45 * n:
                rows.append(i)
        # collapse adjacent rows (a line 2-3 px thick) into one tread
        lines = []
        for i in rows:
            if lines and i - lines[-1][-1] <= 2:
                lines[-1].append(i)
            else:
                lines.append([i])
        c = [float(np.mean(l)) for l in lines]
        lo, hi = (180 / k, 400 / k) if k else (6, 40)
        gaps = np.diff(c)
        for i in range(len(gaps) - 2):
            g3 = gaps[i:i + 3]
            if all(lo <= v <= hi for v in g3) and (g3.max() - g3.min()) <= 0.2 * g3.mean():
                return True
    return False


def _cj_panels(g, zmask):
    """Control-joint panels of a zone: the zone cut by bold straight lines that run (nearly) wall to wall."""
    import cv2
    import numpy as np

    ys, xs = np.nonzero(zmask)
    if not len(xs):
        return 1, []
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    bold = ((g < 140) & (zmask > 0)).astype(np.uint8)
    Lh, Lv = max(15, int((x1 - x0) * 0.5)), max(15, int((y1 - y0) * 0.5))
    # bold = 2+ px thick (thin dimension / extension lines are 1 px); small breaks (lossy rasters) are bridged
    hl = cv2.morphologyEx(cv2.morphologyEx(bold, cv2.MORPH_CLOSE, np.ones((1, 7), np.uint8)), cv2.MORPH_OPEN,
                          np.ones((2, Lh), np.uint8))
    vl = cv2.morphologyEx(cv2.morphologyEx(bold, cv2.MORPH_CLOSE, np.ones((7, 1), np.uint8)), cv2.MORPH_OPEN,
                          np.ones((Lv, 2), np.uint8))
    cuts = []
    for m, o in ((hl, "H"), (vl, "V")):
        n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        for i in range(1, n):
            x, y, w, h, _a = st[i]
            if o == "H":
                row = int(y + h // 2)
                xs_r = np.nonzero(zmask[row])[0]
                if len(xs_r) and x - xs_r.min() < 0.06 * (x1 - x0) and xs_r.max() - (x + w) < 0.06 * (x1 - x0):
                    cuts.append(("H", x, y, w, h))
            else:
                col = int(x + w // 2)
                ys_c = np.nonzero(zmask[:, col])[0]
                if len(ys_c) and y - ys_c.min() < 0.06 * (y1 - y0) and ys_c.max() - (y + h) < 0.06 * (y1 - y0):
                    cuts.append(("V", x, y, w, h))
    cut = zmask.copy()
    for o, x, y, w, h in cuts:  # a joint runs wall to wall: cut the zone's whole extent along it
        if o == "H":
            cut[max(0, y - 2):y + h + 2, :] = 0
        else:
            cut[:, max(0, x - 2):x + w + 2] = 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(cut.astype(np.uint8), connectivity=4)
    big = [i for i in range(1, n) if st[i, 4] > 0.02 * zmask.sum()]
    return max(1, len(big)), cuts


def _hatch(g, union_mask):
    """Hatched / shaded pads inside the slab zones: list of {bbox, area_px, poly} (px)."""
    import cv2
    import numpy as np

    S = max(g.shape)
    m = (_shade_mask(g) & (union_mask > 0)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=4)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < (S * 0.01) ** 2:
            continue
        cs, _ = cv2.findContours((lab == i).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cs, key=cv2.contourArea)
        poly = cv2.approxPolyDP(c, 2.0, True)[:, 0, :].tolist()
        out.append({"bbox": [int(x), int(y), int(x + w), int(y + h)], "area_px": float(a), "poly": poly})
    return out


# ----------------------------------------------------------------------------------------------- scale
def _tick_span(g, cx, cy, x0, x1, th):
    """For a horizontal dimension text centred at (cx, cy) with x-extent x0..x1 and height th (px): find its dimension
    line just below (or through) the text, then the extension lines (thin strokes crossing the dimension line well
    above and below it, past any arrowhead / tick blob) left and right of the text. Returns (left_x, right_x, row)."""
    H, W = g.shape
    line = g < 245
    probe = max(4, int(th * 2))
    row = None
    for dy in list(range(int(th * 0.5), int(th * 2.4) + 1)) + list(range(-int(th * 0.4), int(th * 0.4) + 1)):
        y = int(round(cy + dy))
        if not (2 <= y < H - 2):
            continue
        lx, rx = max(0, int(x0) - probe), min(W, int(x1) + probe)
        a = line[y - 1:y + 2, lx:int(x0)].any(0).mean() if int(x0) > lx else 0
        b = line[y - 1:y + 2, int(x1):rx].any(0).mean() if rx > int(x1) else 0
        if a > 0.8 and b > 0.8:
            row = y
            break
    if row is None:
        return None
    ext = g < 235
    up_rows = [row - d for d in range(3, 8) if row - d >= 0]
    dn_rows = [row + d for d in range(3, 8) if row + d < H]

    def is_tick(x):
        def hits(rs):
            return sum(ext[r, max(0, x - 1):x + 2].any() and not ext[r, max(0, x - 4)] and not ext[r, min(W - 1, x + 4)]
                       for r in rs)
        return hits(up_rows) >= 4 or hits(dn_rows) >= 4

    def walk(x, step):
        gap = 0
        while 1 < x < W - 2:
            if line[row - 1:row + 2, x].any():
                gap = 0
            else:
                gap += 1
                if gap > 3:
                    return None
            if is_tick(x):
                return x
            x += step
        return None

    L = walk(int(x0) - 1, -1)
    R = walk(int(x1) + 1, 1)
    if L is None or R is None or R - L < (x1 - x0):
        return None
    return L, R, row


def _scale_from_dims(hor, ver, W, H, g=None):
    """mm per px: each dimension number over the span between the ticks of its own dimension line (median)."""
    import numpy as np

    dims = []
    for ws, vertical in ((hor, False), (ver, True)):
        ft = _dim_tokens(ws, vertical)
        for t in ft:
            x0, y0, x1, y1 = t["bbox"]
            dims.append({"v": t["v"], "vertical": vertical, "bbox": t["bbox"], "imperial": True,
                         "px": [x0 * W, y0 * H, x1 * W, y1 * H]})
        for w in ws:
            v = _num(w["text"])
            if v is None or v < 100 or v > 200000 or w.get("conf", 99) < 50:
                continue
            x0, y0, x1, y1 = w["bbox"]
            dims.append({"v": v, "vertical": vertical, "bbox": w["bbox"],
                         "px": [x0 * W, y0 * H, x1 * W, y1 * H]})
    if g is None:
        return None, dims, 0
    gT = np.ascontiguousarray(g.T)
    est = []
    for d in dims:
        x0, y0, x1, y1 = d["px"]
        if not d["vertical"]:
            sp = _tick_span(g, (x0 + x1) / 2, (y0 + y1) / 2, x0, x1, y1 - y0)
            if sp:
                d["span"] = [sp[0], sp[2], sp[1], sp[2]]
        else:  # vertical text reads bottom-to-top; its line runs to the right of it in the transposed image
            sp = _tick_span(gT, (y0 + y1) / 2, (x0 + x1) / 2, y0, y1, x1 - x0)
            if sp:
                d["span"] = [sp[2], sp[0], sp[2], sp[1]]
        if sp and sp[1] - sp[0] > 0 and d["v"] > 0:  # a zero-length span or a "0" read would divide by zero
            d["k"] = d["v"] / (sp[1] - sp[0])
            if sp[1] - sp[0] >= 0.015 * max(g.shape):  # short spans: a 1 px tick error or a stray match decides
                est.append(d["k"])
    if len(est) < 3:
        return None, dims, 0
    e = np.array(est)
    # the scale most dimensions agree on (a misread number gives a stray ratio; garbage does not cluster)
    support = [int((np.abs(e / v - 1) < 0.04).sum()) for v in e]
    best = int(np.argmax(support))
    if support[best] < 3:
        for d in dims:
            d["inlier"] = False
        return None, dims, 0  # no three dimensions agree: no trustworthy scale, areas abstain
    med = float(np.median(e[np.abs(e / e[best] - 1) < 0.04]))
    good = [d for d in dims if "k" in d and abs(d["k"] / med - 1) < 0.04
            and abs(d["span"][2] - d["span"][0]) + abs(d["span"][3] - d["span"][1]) >= 0.015 * max(g.shape)]
    for d in dims:
        d["inlier"] = d in good
    if not good:
        return None, dims, 0
    # long dimensions dominate (a 1 px tick error matters less on 12,000 mm than on 600 mm)
    k = sum(d["v"] ** 2 * d["k"] for d in good) / sum(d["v"] ** 2 for d in good)
    return k, dims, len(good)


_PAPER_MM = {"ANSI A": 279.4, "ANSI B": 431.8, "ANSI C": 558.8, "ANSI D": 863.6, "ANSI E": 1117.6,
             "ARCH C": 609.6, "ARCH D": 914.4, "ARCH E": 1219.2, "ISO A0": 1189, "ISO A1": 841, "ISO A2": 594,
             "ISO A3": 420}


def _scale_from_sheet(text, W, H):
    """Fallback scale when no three dimension strings agree: the printed drawing scale times the printed sheet
    size (title block "SIZE: ANSI D" / "ISO A1"), assuming the image is the whole sheet. (k, how) or None."""
    t = text.upper()
    m = re.search(r"\b(ANSI|ARCH|ISO)\s*([A-E]|A[0-4])\b", t)
    if m:
        key = f"{m.group(1)} {m.group(2)}"
    else:
        # the size box unread (a small screenshot): the common full-size sheet of the image's proportions
        ar = max(W, H) / max(1, min(W, H))
        key = next((k for k, a in (("ANSI D", 34 / 22), ("ARCH D", 36 / 24), ("ISO A1", 841 / 594))
                    if abs(ar / a - 1) < 0.008), None)
        if key is None:
            return None
    paper = _PAPER_MM.get(key)
    sm = re.search(r"SCALE\s*:?\s*1\s*:\s*(\d{1,4})\b", t)
    if sm:
        factor = int(sm.group(1))
    else:
        sm = re.search(r"SCALE\s*:?\s*(\d+)\s*/\s*(\d+)\s*\"?\s*=\s*1\s*'\s*-?\s*0", t) or \
            re.search(r"SCALE\s*:?\s*(\d+)\s*\"?\s*=\s*1\s*'\s*-?\s*0()", t)
        if not sm:
            return None
        inch = int(sm.group(1)) / (int(sm.group(2)) if sm.group(2) else 1)
        factor = 12 / inch
    if not paper or not factor:
        return None
    return paper * factor / max(W, H), f"sheet size {key} × scale {sm.group(0).split(':')[-1].strip()} (assumes the image is the whole sheet)"


def _snap_to(v, ticks, tol):
    """Nearest tick within tol, preferring ticks of long (overall) dimensions: those mark the outer faces."""
    near = [(t, w) for t, w in ticks.items() if abs(t - v) <= tol]
    if not near:
        return v
    return float(max(near, key=lambda tw: (tw[1], -abs(tw[0] - v)))[0])


def _snap(L_mm, dims, tol=0.006):
    """A printed dimension close to a measured length (prefers larger, i.e. overall, dimensions)."""
    best = None
    for d in dims:
        r = abs(d["v"] - L_mm) / max(L_mm, 1)
        if r <= tol and (best is None or r < best[1] - 0.003):
            best = (d, r)
    return best[0] if best else None


# ----------------------------------------------------------------------------------------------- analyse
def _vision_pad_labels(meta, word: str) -> tuple[list[str], float]:
    """'<WORD> PAD #n' labels listed by Haiku from the whole sheet (one call, ~$0.0005, kept with the upload)."""
    from PIL import Image

    from bp.generic import llm

    cache = meta.setdefault("_slab_reads", {})
    key = f"padlabels:{word}"
    if isinstance(cache.get(key), list):
        return cache[key], 0.0
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(meta["image"]) as im:
        im = im.convert("RGB")
        im.thumbnail((1568, 1568))
    r = llm.ask(f'Construction drawing. List every label of the form "{word} PAD #<n>" (equipment pads; they may be '
                f'printed vertically). JSON only: {{"labels": ["{word} PAD #1", ...]}}', [im], model="haiku",
                tag="sheets-slab-pads", timeout=90)
    d = llm.parse_json(r.get("text") or "") or {}
    labels = [str(x) for x in (d.get("labels") or [])] if isinstance(d, dict) else []
    if r.get("text"):
        cache[key] = labels
        _save_reads(meta)
    return labels, float(r.get("cost_usd") or 0.0)


def _reads_file(meta) -> Path | None:
    img = meta.get("image")
    if not img:
        return None
    try:
        return Path(meta.get("_slab_cache_dir") or Path(img).parent) / f"slab_reads_{Path(img).stem}_{Path(img).stat().st_size}.json"
    except OSError:
        return None


def _load_reads(meta) -> None:
    """The model's readings of this sheet (note crops, zone crops) are kept with the upload: after a restart the
    slab is analysed from the same readings, so its answers don't change (the same file, the same answers)."""
    if "_slab_reads" in meta:
        return
    f = _reads_file(meta)
    try:
        meta["_slab_reads"] = json.loads(f.read_text()) if f is not None and f.exists() else {}
    except (OSError, ValueError):
        meta["_slab_reads"] = {}


def _save_reads(meta) -> None:
    f = _reads_file(meta)
    if f is None or not meta.get("_slab_reads"):
        return
    try:
        f.write_text(json.dumps(meta["_slab_reads"]))
    except (OSError, TypeError, ValueError):
        pass


def _vision_text(meta) -> dict:
    """Last resort without OCR: Haiku reads the slab notes + overall dimensions (one call, ~$0.01)."""
    from PIL import Image

    from bp.generic import llm

    cache = meta.setdefault("_slab_reads", {})
    if isinstance(cache.get("vision_text"), dict):
        return {**cache["vision_text"], "cost_usd": 0.0}

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(meta["image"]) as im:
        im = im.convert("RGB")
        im.thumbnail((1568, 1568))
    prompt = ("Structural slab/foundation plan. Transcribe exactly, JSON only: {\"slab_notes\": [{\"text\": "
              "\"<full note, e.g. 300 SLAB-ON-GRADE W/ D16 @ 300 TOP OF SLAB EL. = 9400>\", \"x\": <centre 0..1>, "
              "\"y\": <centre 0..1>}], \"general_notes\": \"<the NOTES block text>\", \"overall_width_mm\": <largest "
              "horizontal dimension>, \"overall_height_mm\": <largest vertical dimension>, \"scale\": \"1:50\"}")
    r = llm.ask(prompt, [im], model="haiku", tag="sheets-slab-read", timeout=90)
    d = llm.parse_json(r["text"]) or {}
    d = d if isinstance(d, dict) else {}
    if r.get("text"):
        cache["vision_text"] = dict(d)
    d["cost_usd"] = r.get("cost_usd", 0.0)
    return d


# bar marks too ("D19 RADIAL BARS ... LONG", "D19 @ 250 E.W TOP AND BOTTOM" on a tank slab detailed bar by bar): a
# scan garbles them as much as the slab notes
_NOTE_KW = re.compile(r"SLAB|SUMP|TRENCH|NOTES?\b|SHADED|HATCH|REINF|\b[DT]\d{2}\b|RADIAL|\bHOOP\b", re.I)


def _merge_boxes(boxes):
    boxes = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    boxes.pop(j)
                    changed = True
                    break
            if changed:
                break
    return boxes


def _reread_notes(meta, blocks):
    """Tesseract garbles small note text ("W/ D22" -> "022"). Re-read every note that matters (slab types, sumps,
    trenches, the general notes) with one small Haiku call per note crop (~$0.0005 each). Returns (blocks, cost)."""
    from PIL import Image

    from bp.generic import llm

    if os.environ.get("BP_SLAB_REREAD", "1") != "1":
        return blocks, 0.0
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(meta["image"]).convert("L")
    W, H = im.size
    small_src = max(W, H) < 3000
    keyb = [b for b in blocks if _NOTE_KW.search(b["text"])]
    if not keyb or len(keyb) > 40:
        return blocks, 0.0
    boxes = []
    for b in keyb:
        x0, y0, x1, y1 = b["bbox"]
        lh = max(0.004, (y1 - y0) / max(1, len(b["lines"])))
        if re.match(r"\s*NOTES?\b", b["text"], re.I) or "TRENCH LENGTH" in b["text"].upper():
            boxes.append([x0 - 0.005, y0 - lh, min(1, x0 + 0.5), y0 + 0.075, "general"])  # the notes column
        else:
            boxes.append([x0 - 3 * lh, y0 - 2.5 * lh, x1 + 3 * lh, y1 + 2.5 * lh, "note"])
    general = _merge_boxes([[max(0, a), max(0, b), min(1, c), min(1, d)] for a, b, c, d, t in boxes if t == "general"])
    notes_b = []
    for a, b, c, d, t in boxes:
        if t == "note" and (c - a) < 0.25 and (d - b) < 0.2:
            bx = [round(max(0, a), 4), round(max(0, b), 4), round(min(1, c), 4), round(min(1, d), 4)]
            if not any(n[0] <= (a + c) / 2 <= n[2] and n[1] <= (b + d) / 2 <= n[3] and (n[2] - n[0]) >= (c - a) * 0.9
                       for n in notes_b):  # a note already covered by another crop
                notes_b.append(bx)
    boxes = general + notes_b
    is_general = {tuple(bx): bx in general for bx in boxes}
    cache = meta.setdefault("_slab_reads", {})
    cost = 0.0

    def read(bx):
        crop = im.crop((round(bx[0] * W), round(bx[1] * H), round(bx[2] * W), round(bx[3] * H)))
        f = min(4.0, 1400 / max(crop.width, crop.height))
        if f > 1:
            crop = crop.resize((round(crop.width * f), round(crop.height * f)), Image.LANCZOS)
        r = llm.ask("Crop of a construction drawing. Transcribe every text note in it exactly as printed (keep "
                    "bar marks like D16, @ spacings, EL. values, numbers). One note per list item, lines of one "
                    "note joined with spaces; numbered notes stay separate items. JSON only: "
                    '{"notes": ["..."]}', [crop.convert("RGB")], model="haiku", tag="sheets-slab-note", timeout=90)
        d = llm.parse_json(r["text"]) or {}
        notes = d.get("notes") if isinstance(d, dict) else None
        return float(r.get("cost_usd") or 0.0), ([str(n) for n in notes] if isinstance(notes, list) else None)

    todo = [bx for bx in boxes if ",".join(f"{v:.4f}" for v in bx) not in cache]
    if todo:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=6) as ex:
            for bx, (c, notes) in zip(todo, ex.map(read, todo)):
                cost += c
                cache[",".join(f"{v:.4f}" for v in bx)] = notes
    # numbers in each crop re-OCRed at a higher zoom: a vision-read number with no OCR twin but a one-digit-off OCR
    # number is replaced by the OCR one (Haiku sometimes "reads" 1825 as 1625 on a small raster)
    from bp.sheets import ocr_words

    crop_nums = {}
    for bx in boxes:
        ws = ocr_words(meta, region=tuple(round(v, 4) for v in bx), scale=4.0, psm=6, min_conf=85)
        crop_nums[tuple(bx)] = {t for w in ws for t in re.findall(r"\d{3,6}", w["text"])}

    def fix(note, bx):
        def sub(m):
            t = m.group(0)
            near = crop_nums.get(tuple(bx), set())
            # only where Haiku saw a small raster (it misread 1825 as 1625 at 2000 px); on a sharp crop Haiku
            # is the better reader and Tesseract the one that slips (4275 -> 1275 on a scan)
            if not small_src or not is_general.get(tuple(bx)) or not near or t in near:
                return t
            alt = [o for o in near if len(o) == len(t) and sum(a != b for a, b in zip(o, t)) == 1]
            return alt[0] if len(alt) == 1 else t
        return re.sub(r"(?<![\dA-Z])\d{4,6}(?!\d)", sub, note)

    def toks(t):
        return set(re.findall(r"[A-Z]{2,}|\d{2,}", t.upper()))

    out, seen = [], set()
    for bx in boxes:
        inside_b = [b for b in blocks if bx[0] <= (b["bbox"][0] + b["bbox"][2]) / 2 <= bx[2]
                    and bx[1] <= (b["bbox"][1] + b["bbox"][3]) / 2 <= bx[3]]
        for n in cache.get(",".join(f"{v:.4f}" for v in bx)) or []:
            # locate the note: the OCR block in the crop sharing most words with it
            best = max(inside_b, key=lambda b: len(toks(n) & toks(b["text"])), default=None)
            bb = best["bbox"] if best is not None and len(toks(n) & toks(best["text"])) >= 2 else bx
            key = re.sub(r"\W", "", n.upper())
            if key in seen:
                continue
            seen.add(key)
            out.append({"text": fix(n, bx), "bbox": bb, "lines": [], "read": "haiku+ocr",
                        "general": bool(is_general.get(tuple(bx)))})
    if not out:
        return blocks, cost
    # keep OCR blocks that the re-read crops do not cover; the crops' notes replace the rest
    def inside(b):
        cx, cy = (b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2
        return any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in boxes if cache.get(
            ",".join(f"{v:.4f}" for v in (x0, y0, x1, y1))))
    return [b for b in blocks if not inside(b)] + out, cost


def analyse(meta) -> dict:
    if isinstance(meta.get("slab"), dict) and meta["slab"].get("v") == 1:
        return meta["slab"]
    import numpy as np

    from bp.sheets import ocr_lines

    cost = 0.0
    _load_reads(meta)
    hor, ver, src = _ocr(meta)
    g, f = _gray(meta)
    g, rot = _deskew(g)  # a scan's slight rotation breaks straight-line tests (joints, ticks): measure level
    # the flood fill works on the unstretched grey (a stretched scan turns paper noise into barriers); the line
    # tests (dimension ticks, joints) on the stretched one
    g_raw = _gray(meta, stretch="paper")[0]
    scan_like = float(np.percentile(_gray(meta, stretch=False)[0], 60)) < 240  # grey paper: a scan or a photo
    if rot is not None:
        import cv2

        g_raw = cv2.warpAffine(g_raw, cv2.invertAffineTransform(rot), (g_raw.shape[1], g_raw.shape[0]),
                               flags=cv2.INTER_NEAREST, borderValue=255)  # nearest: thin wall lines stay dark
    g_seg = _erase_pdf_shading(meta, g_raw)
    if g_seg is g_raw and scan_like and os.environ.get("BP_SLAB_RASTER_HATCH", "1") == "1":
        g_seg = _erase_raster_shading(g_raw)
    H, W = g.shape
    lines = ocr_lines(hor) if hor else []
    blocks = _blocks(lines)
    vis = None
    if not hor:
        vis = _vision_text(meta)
        cost += vis.get("cost_usd", 0.0)
        src = "vision"
        for n in vis.get("slab_notes") or []:
            try:
                x, y = float(n["x"]), float(n["y"])
            except (KeyError, TypeError, ValueError):
                continue
            blocks.append({"text": n.get("text", ""), "bbox": [x - 0.03, y - 0.015, x + 0.03, y + 0.015], "lines": []})
        gn = vis.get("general_notes") or ""
        blocks.append({"text": gn, "bbox": [0, 0, 0, 0], "lines": []})
    if src == "tesseract":
        blocks, c = _reread_notes(meta, blocks)
        cost += c
    full_text = "\n".join(b["text"] for b in blocks)

    # slab types
    types = []
    for b in blocks:
        ty = _parse_type(b["text"])
        if ty:
            ty.update({"text": b["text"], "bbox": b["bbox"]})
            # the same note read twice (a crop cut it short): keep the fuller reading, at the tighter location
            def near(a, b, d=0.04):
                return a[0] - d < b[2] and b[0] - d < a[2] and a[1] - d < b[3] and b[1] - d < a[3]

            twin = next((t for t in types if t["thickness_mm"] == ty["thickness_mm"] and t["bars"] == ty["bars"]
                         and (t["text"] in ty["text"] or ty["text"] in t["text"]) and near(t["bbox"], ty["bbox"])), None)
            if twin is None:
                types.append(ty)
            elif len(ty["text"]) > len(twin["text"]):
                area = lambda bb: (bb[2] - bb[0]) * (bb[3] - bb[1])  # noqa: E731
                bb = min(twin["bbox"], ty["bbox"], key=area)
                twin.clear()
                twin.update(ty)
                twin["bbox"] = bb

    if any(t["thickness_mm"] for t in types):  # bar callouts without a thickness are details, not slab types
        types = [t for t in types if t["thickness_mm"]]

    # scale
    k, dims, n_scale = _scale_from_dims(hor, ver, W, H, g)
    scale_src = f"{n_scale} dimension-string pairs" if k else None
    k2 = _scale_from_sheet(full_text + " " + " ".join(w["text"] for w in hor + ver)
                           + (f" SCALE: {meta['scale']}" if meta.get("scale") else ""), W, H)
    if not k and k2:
        k, scale_src = k2
    elif k and k2 and n_scale < 6 and not 0.5 < k / k2[0] < 2:
        # a few misread dimension strings agreeing by chance (a rough scan: 4 pairs gave 3 mm/px where the printed
        # 1/4" = 1'-0" on ANSI D says 21): the printed scale and sheet size win
        k, scale_src = k2[0], k2[1] + f" (the {n_scale} dimension pairs read disagreed)"

    # zones
    joint_pts = [((w["bbox"][0] + w["bbox"][2]) / 2 * W, (w["bbox"][1] + w["bbox"][3]) / 2 * H) for w in hor + ver
                 if re.fullmatch(r"[CE]\.?J\.?", w["text"].upper())]
    zones, _outside = _zones(g_seg, k, joint_pts)
    S = max(H, W)
    good = []
    for z in zones:
        z["walled"] = _ring_walled(g, z["mask"])
        if z["walled"] >= 0.75 and z["mask"].sum() > 0.01 * W * H:
            good.append(z)
    zones = good
    if vis and not k and zones:
        ow = vis.get("overall_width_mm")
        union = np.zeros_like(g, dtype=np.uint8)
        for z in zones:
            union |= z["mask"]
        xs = np.nonzero(union.any(0))[0]
        if ow and len(xs):
            k = float(ow) / (xs.max() - xs.min() + 2 * 0.3 / 21 * 0)  # inner extent: rough
            scale_src = "overall dimension read by vision (rough)"

    eps = max(3.0, S * 0.003)
    xt, yt = {}, {}
    for d in dims:
        if d.get("inlier"):
            t, cs = (yt, (d["span"][1], d["span"][3])) if d["vertical"] else (xt, (d["span"][0], d["span"][2]))
            for c in cs:
                t[round(c, 1)] = max(t.get(round(c, 1), 0), d["v"])
    out_zones = []
    for i, z in enumerate(zones):
        others = np.zeros_like(g, dtype=bool)
        for j, z2 in enumerate(zones):
            if j != i:
                others |= z2["mask"] > 0
        pts = _rect_poly(z["mask"], eps)
        if len(pts) < 4:
            continue
        offs = _outward_offsets(g, z["mask"], pts, others, _outside)
        gross = _offset_poly(pts, offs)
        # snap the outer faces to the dimension-line ticks (extension lines) when one is close
        tol = 0.015 * S
        gross = _clean_poly([(_snap_to(x, xt, tol), _snap_to(y, yt, tol)) for x, y in gross])
        if len(gross) < 4:
            continue
        n_pan, cuts = _cj_panels(g, z["mask"])
        pts = _refine_edges(g, _clean_poly(pts), z["mask"])
        rr = _rects(pts)
        big = max(((r[2] - r[0]) * (r[3] - r[1]) for r in rr), default=0)
        stair_parts = [[float(v) for v in r] for r in rr
                       if (r[2] - r[0]) * (r[3] - r[1]) < 0.06 * big and _has_treads(g, r, k)]
        out_zones.append({"inner": pts, "gross": gross, "inner_px": _poly_area(pts), "gross_px": _poly_area(gross),
                          "stair_parts": stair_parts, "panels": n_pan, "cuts": cuts, "walled": round(z["walled"], 3),
                          "centroid": [float(np.mean([p[0] for p in pts])), float(np.mean([p[1] for p in pts]))]})
    # assign notes: inside first, then nearest unused (leadered notes outside)
    from shapely.geometry import Point, Polygon

    used = set()
    for z in out_zones:
        poly = Polygon(z["gross"])
        z["type"] = None
        for ti, ty in enumerate(types):
            cx = (ty["bbox"][0] + ty["bbox"][2]) / 2 * W
            cy = (ty["bbox"][1] + ty["bbox"][3]) / 2 * H
            if poly.contains(Point(cx, cy)) and ti not in used:
                z["type"], z["type_how"] = ti, "note inside the zone"
                used.add(ti)
                break
    # a zone with no note inside: its note may be one the text pass missed (small boxed text on a mid-size raster)
    # -> one Haiku read of the zone's own crop
    if src not in ("pdf-text",) and os.environ.get("BP_SLAB_REREAD", "1") == "1":
        for z in out_zones:
            if z["type"] is not None or z["inner_px"] < 0.03 * W * H:
                continue
            ty, c = _read_zone_note(meta, z, W, H)
            cost += c
            if ty:
                types.append(ty)
                z["type"], z["type_how"] = len(types) - 1, "note inside the zone (read from the zone's crop)"
                used.add(len(types) - 1)
    # notes outside every zone (with a leader): each goes to the nearest zone still without a note
    pairs = []
    for ti, t in enumerate(types):
        if ti in used:
            continue
        pt = Point((t["bbox"][0] + t["bbox"][2]) / 2 * W, (t["bbox"][1] + t["bbox"][3]) / 2 * H)
        for zi, z in enumerate(out_zones):
            if z["type"] is None:
                pairs.append((Polygon(z["gross"]).distance(pt), ti, zi))
    for dist, ti, zi in sorted(pairs):
        z = out_zones[zi]
        if ti in used or z["type"] is not None or dist >= 0.15 * S:
            continue
        z["type"], z["type_how"] = ti, f"nearest note outside the zone ({dist * (k or 0) / 1000:.1f} m away, leader)"
        used.add(ti)
    default = next((ti for ti, t in enumerate(types) if t.get("default")), None)
    if default is not None:  # "12\" SLAB-ON-GRADE U.N.O.": every slab zone without its own note
        for z in out_zones:
            if z["type"] is None:
                z["type"], z["type_how"] = default, "the U.N.O. (unless noted otherwise) slab note"
    _merge_untyped(out_zones, S)
    if k and os.environ.get("BP_SLAB_DIMZONES", "1") == "1":
        _dimension_zones(out_zones, types, used, dims, W, H, S)
    union = np.zeros_like(g, dtype=np.uint8)
    for z in zones:
        union |= z["mask"]
    pads = _hatch(g, union) if zones else []

    # notes: trenches, sumps, CJ, scale
    trenches = []
    # trench lengths come from the general notes when they were read as a whole (fragment crops of the same
    # notes repeat them garbled)
    tr_text = ("\n".join(b["text"] for b in blocks if b.get("general"))
               or "\n".join(b["text"] for b in blocks if b.get("read")) or full_text)
    for m in re.finditer(r"([A-Z][A-Z ]{2,40}?)\s+TRENCH\s+LENGTH\s*[-=:]?\s*(\d[\d,]*)", tr_text.upper()):
        trenches.append({"name": m.group(1).strip().title() + " trench", "length_mm": int(m.group(2).replace(",", ""))})
    for m in re.finditer(r"(?:^|\n|\d\.\s|\.\s)([A-Z][A-Z ,/]{3,80}?),?\s*APPROXIMATELY\s*((?:\d+\s*'\s*-?\s*)?\d+(?:\s+\d/\d+)?\s*\")\s*LONG",
                         tr_text.upper()):
        fm = _FTIN_RE.search(m.group(2))
        v = _ftin_mm(fm) if fm else None
        if v:
            name = re.sub(r"\s+", " ", m.group(1)).strip(" ,").title()
            trenches.append({"name": name if "Trench" in name else name + " trench", "length_mm": round(v),
                             "printed": m.group(2).replace(" ", "")})
    by_len: dict = {}
    for t in trenches:  # the same note read twice (overlapping crops / OCR leftovers): keep the cleanest name
        cur = by_len.get(t["length_mm"])
        if cur is None or len(t["name"]) > len(cur["name"]):
            by_len[t["length_mm"]] = t
    trenches = [t for t in trenches if by_len.get(t["length_mm"]) is t]
    # a reading that lost a digit (427 for 4275) is the same note
    trenches = [t for t in trenches if not any(o is not t and str(o["length_mm"]).startswith(str(t["length_mm"]))
                                               and len(str(o["length_mm"])) > len(str(t["length_mm"])) for o in trenches)]
    tl_blocks = [b for b in blocks if "TRENCH" in b["text"].upper()]
    sump_blocks = [b for b in blocks if re.search(r"\bSUMP\b", b["text"].upper())]
    sumps = []
    for b in sump_blocks:
        m = re.search(r"SUMP\s*(\d{3,4})\s*[X×x]\s*(\d{3,4})\s*[X×x]\s*(\d{2,4})", b["text"].upper())
        sumps.append({"text": b["text"], "bbox": b["bbox"], "dims": [int(v) for v in m.groups()] if m else None})
    cj_words = [w for w in hor + ver if re.fullmatch(r"C\.?J\.?", w["text"].upper())]
    sc = re.search(r"SCALE\s*:?\s*1\s*:\s*(\d+)", full_text.upper())
    hatch_note = next((b for b in blocks if re.search(r"SHADED|HATCH", b["text"].upper())), None)
    inl = [d for d in dims if d.get("inlier")]
    imperial = bool(inl) and sum(bool(d.get("imperial")) for d in inl) > len(inl) / 2
    if not inl:  # no dimension evidence: inch slab notes say the sheet is imperial
        imperial = any(t.get("thickness_in") for t in types)
    low = bool(meta.get("low_res")) if "low_res" in meta else (src != "pdf-text" and max(meta.get("w") or 0, meta.get("h") or 0) < 3000)
    if rot is not None:  # geometry back into the uploaded image's own coordinates (evidence is drawn on it)
        _unrotate(out_zones, pads, rot)
    res = {"v": 1, "src": src, "low_res": low, "imperial": imperial, "W": W, "H": H, "f": f, "k": k, "scale_src": scale_src,
           "scale_note": f"1:{sc.group(1)}" if sc else None, "types": types, "zones": out_zones,
           "pads": pads, "trenches": trenches, "trench_blocks": [b["bbox"] for b in tl_blocks],
           "trench_labels": [{"text": b["text"], "bbox": b["bbox"]} for b in tl_blocks],
           "sumps": sumps, "cj_words": [w["bbox"] for w in cj_words],
           "hatch_note": hatch_note["text"] if hatch_note else None,
           "chains": _chains(dims),
           "dims": [{k2: d[k2] for k2 in ("v", "vertical", "bbox", "span", "k", "inlier") if k2 in d} for d in dims], "cost_usd": cost,
           "text": full_text,
           # vertical words grouped into lines in the frame they read in (rotated a quarter turn back)
           "labels_text": "\n".join(ln["text"] for ln in (ocr_lines(hor) if hor else []) + (ocr_lines(
               [{**w, "bbox": [1 - w["bbox"][3], w["bbox"][0], 1 - w["bbox"][1], w["bbox"][2]]} for w in ver])
               if ver else [])),
           "stairs": [b["bbox"] for b in blocks if re.search(r"\bSTAIR", b["text"], re.I) and b["bbox"][2] > b["bbox"][0]]}
    meta["slab"] = res
    _save_reads(meta)
    return res


# ----------------------------------------------------------------------------------------------- answer helpers
def _m2(px, k):
    return px * k * k / 1e6


def _norm_pts(pts, W, H):
    return [[round(x / W, 5), round(y / H, 5)] for x, y in pts]


def _zone_explain(z, a, k, dims, key="gross", stairs=(), WH=(1, 1), imperial=False):
    """Zone area as rectangles: '19,800 × 12,000 mm = 237.60 m²' (+ more rectangles for L-shapes). A side equal
    to a printed dimension (within 0.6 %) uses the printed value; others are measured (rounded to 10 mm)."""
    hd = [d for d in dims if not d["vertical"]]
    vd = [d for d in dims if d["vertical"]]
    parts, total, printed, dropped = [], 0.0, 0, []
    rects = _rects(z[key])
    big = max(((r[2] - r[0]) * (r[3] - r[1]) for r in rects), default=0)
    for x0, y0, x1, y1 in rects:
        w, h = (x1 - x0) * k, (y1 - y0) * k
        # a small appendage labelled as a stair well is not slab (the stair pit of S-100F)
        cx, cy = (x0 + x1) / 2 / WH[0], (y0 + y1) / 2 / WH[1]
        drawn = any(min(x1, r[2]) - max(x0, r[0]) > 0.5 * (x1 - x0) and min(y1, r[3]) - max(y0, r[1]) > 0.3 * (y1 - y0)
                    for r in z.get("stair_parts", []))
        labelled = (x1 - x0) * (y1 - y0) < 0.04 * big and any(
            b[0] - 0.06 < cx < b[2] + 0.06 and b[1] - 0.06 < cy < b[3] + 0.06 for b in stairs)
        if key == "inner" and (drawn or labelled):
            dropped.append(w * h / 1e6)
            continue
        dw, dh = _snap(w, hd), _snap(h, vd)
        w2 = dw["v"] if dw else round(w, -1)
        h2 = dh["v"] if dh else round(h, -1)
        printed += bool(dw) + bool(dh)
        ar = w2 * h2 / 1e6
        total += ar
        parts.append((w2, h2, ar, dw, dh))
    a_kept = a - sum(dropped)
    if not parts or abs(total - a_kept) / max(a_kept, 1e-9) > 0.03:
        return a_kept, f"measured {a_kept:.2f} m²" + (f" (stair well {sum(dropped):.1f} m² left out)" if dropped else ""), []
    def lab(v, d):
        if not d:
            return (_fmt_ftin(v) if imperial else f"{v:,.0f}") + "*"
        t = _fmt_ftin(v) if d.get("imperial") else f"{v:,.0f}"
        return t + (f" ({d['how']})" if d.get("how") else "")

    txt = " + ".join(f"{lab(w, pw)} × {lab(h, ph)}" for w, h, _, pw, ph in parts)
    star = " (* measured; other sides are printed dimensions)" if printed < 2 * len(parts) else " (sides = printed dimensions)"
    tail = f"; stair well ({sum(dropped):.1f} m²) left out" if dropped else ""
    unit = "" if imperial else " mm"
    return total, f"{txt}{unit} = {total:.2f} m²" + (star if printed else " (sides measured)") + tail, parts


def _zone_area(z, A):
    """Slab area = clear area inside the edge beams / walls (the stippled bands are walls, not slab). Returns
    (net m², explanation incl. the gross outline for reference, parts)."""
    k = A["k"]
    dims = A["dims"] + A.get("chains", [])
    a_meas = _m2(z["inner_px"], k)
    stairs = A.get("stairs", [])
    a, how, used = _zone_explain(z, a_meas, k, dims, key="inner", stairs=stairs, WH=(A["W"], A["H"]),
                                 imperial=bool(A.get("imperial")))
    g_meas = _m2(z["gross_px"], k)
    ga, ghow, _ = _zone_explain(z, g_meas, k, A["dims"], key="gross", stairs=stairs, WH=(A["W"], A["H"]),
                                imperial=bool(A.get("imperial")))
    note = f" [{z['dim_note']}]" if z.get("dim_note") else ""
    return a, f"clear area inside the walls: {how}{note}; outer faces: {ghow}", used


def _chains(dims):
    """Sums of runs of adjacent dimensions on one dimension line ('5,800 + 7,400 + 6,300 = 19,500'): clear spans
    between walls are often only printed as such a chain."""
    out = []
    for vertical in (False, True):
        ds = [d for d in dims if d.get("span") and d.get("inlier") and d["vertical"] == vertical]
        rows: dict = {}
        for d in ds:
            key = round((d["span"][0] if vertical else d["span"][1]) / 3)
            rows.setdefault(key, []).append(d)
        for row in rows.values():
            a0 = 1 if vertical else 0
            row.sort(key=lambda d: d["span"][a0])
            for i in range(len(row)):
                tot, parts = 0, []
                for j in range(i, len(row)):
                    if j > i and abs(row[j]["span"][a0] - row[j - 1]["span"][a0 + 2]) > 4:
                        break
                    tot += row[j]["v"]
                    parts.append(row[j]["v"])
                    if len(parts) > 1:
                        imp = all(d.get("imperial") for d in row[i:j + 1])
                        out.append({"v": tot, "vertical": vertical, "imperial": imp,
                                    "how": " + ".join(_fmt_ftin(p) if imp else f"{p:,}" for p in parts)})
    return out


def _type_of(z, A):
    return A["types"][z["type"]] if z.get("type") is not None else None


def _match_zones(q, A):
    """Zones selected by a thickness / bar mention in the question, or None for 'no filter'."""
    ql = q.upper()
    thk = [int(x) for x in re.findall(r"\b(\d{2,3})\s*(?:MM)?\s*(?:THICK|THK|SLAB|SOG|-?MM)", ql)]
    thk += [round(int(x) * 25.4) for x in re.findall(r"\b(\d{1,2})\s*(?:\"|''|-?IN\.?\b|-?INCH(?:ES)?\b)", ql)]
    bars = [re.sub(r"\s", "", b) for b in re.findall(r"\b([DTYHN]\s?\d{1,2}|#\s?\d{1,2})\b", ql)]
    if not thk and not bars:
        return None, None
    sel = []
    for z in A["zones"]:
        ty = _type_of(z, A)
        if not ty:
            continue
        ok = True
        if thk and ty.get("thickness_mm") not in thk:
            ok = False
        if bars and not any(any(b == tb.split("@")[0].strip() for tb in ty.get("bars", [])) for b in bars):
            ok = False
        if ok:
            sel.append(z)
    desc = " ".join([f"{t} mm" for t in thk] + bars)
    return sel, desc


def _res(answer, conf, expl, ev, A, path_suffix="", unit=None):
    r = {"answer": answer, "confidence": round(conf, 2), "explanation": expl, "evidence": ev,
         "method": METHOD + (f"-{path_suffix}" if path_suffix else ""), "cost_usd": round(A.get("cost_usd", 0.0), 5)}
    if unit:
        r["unit"] = unit
    if A.get("imperial") and unit == "m²":  # imperial sheet: answer in square feet, metric arithmetic kept
        f = 10.7639
        if isinstance(answer, (int, float)):
            r["answer"] = round(answer * f, 1)
        elif isinstance(answer, str):
            r["answer"] = re.sub(r"(\d[\d,]*\.?\d*) m²", lambda m: f"{float(m.group(1).replace(',', '')) * f:,.0f} SF", answer)
        r["unit"] = "SF"
        r["explanation"] = expl + f" (1 m² = 10.764 SF{'; = ' + format(r['answer'], ',') + ' SF' if isinstance(answer, (int, float)) else ''})"
        for e in ev:
            if e.get("unit") == "m²" and isinstance(e.get("value"), (int, float)):
                e["value"], e["unit"] = round(e["value"] * f, 1), "SF"
    if A.get("low_res"):
        r["low_res"] = "small raster: notes re-read by vision, sides measured at about 2 cm per pixel"
    if A.get("scale_note"):
        r["scale"] = A["scale_note"]
    if path_suffix.startswith("area"):
        r["sheet_how"] = "measured inside the walls, sides checked against the dimension strings"
    return r


def _text_ev(bbox, label):
    return {"kind": "text", "page": 0, "bbox": [round(v, 5) for v in bbox], "label": label}


def _zone_ev(z, A, label, value):
    """A slab zone (clear area inside its walls), coloured by slab type in the UI legend."""
    t = _type_of(z, A)
    return {"kind": "polygon", "page": 0, "points": _norm_pts(z["inner"], A["W"], A["H"]), "label": label,
            "value": None if value is None else float(value), "unit": "m²",
            "category": _type_name(t) if t else "untyped"}


def _base_conf(A):
    c = 0.85 if A["src"] == "pdf-text" else (0.7 if A["src"] == "tesseract" else 0.45)
    if not A.get("k"):
        c *= 0.5
    return c


# ----------------------------------------------------------------------------------------------- answer
_OUT_OF_SCOPE = (r"\bcosts?\b|\bprice|\bpay\b|€|\$|\bdollars?\b|\beuros?\b|budget|\blabou?r\b|man-?hours?|duration|"
                 r"\bhow long (?:will|does|to)\b|\bweigh|\bheavy|\bmass\b|\bkg\b|\btonn?es?\b|\btons?\b|strength|\bmpa\b|\bpsi\b|"
                 r"\bwho\b|\bwhen\b|\bdate\b|warrant|supplier|manufacturer of|carbon|co2|emission")
_VOLUME = r"\bvolume|\bm3\b|m³|cubic|\byd3\b|\bcy\b|how much concrete|\bft3\b"


def _vol_or_area(r, A, ql):
    """Volume results: evidence carries m³; imperial sheets answer in cubic yards (ft³ when asked)."""
    if r.get("unit") != "m³":
        return r
    if r.get("method", "").endswith("area"):
        r["method"] = r["method"][:-4] + "volume"
    elif r.get("method", "").endswith("area-by-type"):
        r["method"] = r["method"].replace("area-by-type", "volume-by-type")
    r.pop("sheet_how", None)
    for e in r["evidence"]:
        if e.get("kind") == "polygon":
            e["unit"] = "m³"
    if A.get("imperial"):
        f, u = (35.3147, "ft³") if re.search(r"ft3|ft³|cubic f", ql) else (1.30795, "CY")
        if isinstance(r["answer"], (int, float)):
            r["answer"] = round(r["answer"] * f, 1)
        elif isinstance(r["answer"], str):
            r["answer"] = re.sub(r"(\d[\d,]*\.?\d*) m³", lambda m: f"{float(m.group(1).replace(',', '')) * f:,.1f} {u}",
                                 r["answer"])
        r["explanation"] += f" (1 m³ = {f:g} {u})"
        r["unit"] = u
        for e in r["evidence"]:
            if e.get("unit") == "m³" and isinstance(e.get("value"), (int, float)):
                e["value"], e["unit"] = round(e["value"] * f, 2), u
    return r


def answer(path, question, meta) -> dict | None:
    q = question.strip()
    ql = q.lower()
    # intent check: only what a slab plan states or measures (areas, volumes, bars, thickness, elevations, trench
    # lengths, counts). Prices, quantities the sheet does not give, people, dates -> None (the general reader decides)
    if re.search(_OUT_OF_SCOPE, ql):
        return None
    A = analyse(meta)
    W, H = A["W"], A["H"]
    conf0 = _base_conf(A)

    # ---- trenches
    if "trench" in ql:
        if A["trenches"] and re.search(r"length|long|how far|metre|meter|\bmm\b", ql):
            toks = set(re.findall(r"[a-z]+", ql)) - {"trench", "the", "of", "length", "what", "is", "how", "long",
                                                       "total", "a", "in", "mm", "m"}
            best = max(A["trenches"], key=lambda t: len(toks & set(t["name"].lower().split())))
            hits = len(toks & set(best["name"].lower().split()))
            ev = [_text_ev(b, "trench note") for b in A["trench_blocks"]]
            div = 1 if re.search(r"\bin mm\b|millimet", ql) else 1000
            ulen = "mm" if div == 1 else "m"
            if A.get("imperial") and div != 1:
                div, ulen = 304.8, "ft"
            if hits and not re.search(r"\btotal|all|sum\b", ql):
                v = round(best["length_mm"] / div, 3)
                if ulen == "ft":  # an imperial sheet: as printed (5'-6"), with the decimal feet
                    v = f"{best.get('printed') or _fmt_ftin(best['length_mm'])} ({best['length_mm'] / div:.2f} ft)"
                return _res(v, conf0 + 0.1,
                            f"{best['name']}: {best['length_mm']:,} mm per the general notes"
                            + (f" = {best['printed']}" if best.get("printed") else "")
                            + " (approximate trench lengths)", ev, A, "trench", ulen)
            tot = sum(t["length_mm"] for t in A["trenches"])
            return _res(round(tot / div, 3), conf0 + 0.05, " + ".join(f"{t['length_mm']:,}" for t in A["trenches"])
                        + f" mm = {tot:,} mm ({', '.join(t['name'] for t in A['trenches'])}; lengths from the notes)",
                        ev, A, "trench", ulen)
        if re.search(r"how many|number|count", ql):
            n = len(A["trenches"])
            labels = [t for t in A["trench_labels"] if not re.search(r"LENGTH", t["text"].upper())]
            if not n:
                n = len(labels)
            ev = [_text_ev(t["bbox"], f"trench {i + 1}: {t['text'][:40]}") for i, t in enumerate(labels)]
            names = ", ".join(t["name"] for t in A["trenches"])
            return _res(n, conf0, f"{n} trenches listed in the notes ({names})" if A["trenches"]
                        else f"{n} trench labels on the plan", ev, A, "trench")

    # ---- sumps
    if "sump" in ql:
        if not A["sumps"]:
            return None
        s = A["sumps"][0]
        if re.search(r"how many|number|count", ql):
            ev = [_text_ev(x["bbox"], f"sump {i + 1}: {x['text'][:40]}") for i, x in enumerate(A["sumps"])]
            return _res(len(A["sumps"]), conf0, f"{len(A['sumps'])} sump label(s) on the plan", ev, A, "sump")
        if s["dims"]:
            a, b, c = s["dims"]
            if "volume" in ql:
                v = a * b * c / 1e9
                return _res(round(v, 4), conf0, f"{a} × {b} × {c} mm = {v:.3f} m³", [_text_ev(s["bbox"], s["text"])],
                            A, "sump")
            return _res(f"{a} × {b} mm, {c} mm deep", conf0, f"read from the note '{s['text']}'",
                        [_text_ev(s["bbox"], s["text"])], A, "sump")

    zones = A["zones"]
    k = A.get("k")

    # ---- control joints / panels
    if re.search(r"panel|control joint|\bcj\b|joints", ql) and "trench" not in ql:
        sel, desc = _match_zones(q, A)
        sel = zones if sel is None else sel
        if not sel:
            return None
        if re.search(r"panel", ql):
            n = sum(z["panels"] for z in sel)
            ev = [_zone_ev(z, A, f"{_type_name(_type_of(z, A)) if _type_of(z, A) else 'zone'}: {z['panels']} panels",
                           z["panels"]) for z in sel]
            for z in sel:
                for o, x, y, w, h in z["cuts"]:
                    ev.append({"kind": "box", "page": 0, "bbox": [x / W, y / H, (x + w) / W, (y + h) / H],
                               "label": "control joint", "value": None})
            parts = " + ".join(str(z["panels"]) for z in sel)
            return _res(n, conf0 * 0.9, f"slab zones cut by bold wall-to-wall joint lines: {parts} = {n} panels", ev,
                        A, "cj")
        n = sum(len(z["cuts"]) for z in sel)
        ev = []
        for z in sel:
            for o, x, y, w, h in z["cuts"]:
                ev.append({"kind": "box", "page": 0, "bbox": [x / W, y / H, (x + w) / W, (y + h) / H],
                           "label": f"joint {len(ev) + 1}", "value": 1})
        return _res(n, conf0 * 0.8, f"{n} bold wall-to-wall joint lines ({len(A['cj_words'])} 'CJ' labels read)", ev,
                    A, "cj")

    # ---- equipment pads (pump / generator pads): labelled, not hatched
    em = re.search(r"\b(pump|equipment|generator|genset|machine|transformer|tank)\s+pads?\b", ql)
    if em:
        word = em.group(1).upper()
        txt = "\n".join([A.get("labels_text") or "", A.get("text") or "", meta.get("text") or ""])
        rx = rf"{word}\s*PAD\s*(?:NO\.?|#)?\s*(\d{{1,2}})\b"
        nums = sorted({int(n) for n in re.findall(rx, txt, re.I)})
        how = "read on the plan"
        if A.get("src") != "pdf-text":
            # the labels run vertically and the rotated OCR misses some (#1..#4 of 5 is a complete run too): one
            # look by the vision model at the sheet, its labels added
            vis, c = _vision_pad_labels(meta, word)
            nums2 = sorted({int(n) for n in re.findall(rx, " ".join(vis), re.I)} | set(nums))
            if nums2 and nums2 == list(range(1, len(nums2) + 1)) and nums2 != nums:
                nums, how = nums2, "read on the plan by the vision model (they are printed vertically)"
        if not nums or nums != list(range(1, len(nums) + 1)) or not re.search(r"how many|number|count", ql):
            return None  # the general reader looks (the hatched areas are bottom reinforcement, not these pads;
            # an incomplete run of labels, "#7" alone, is a misreading)
        n = len(nums)
        return _res(n, conf0 * 0.8, f"{n} '{word} PAD #n' labels {how}: "
                    + ", ".join(f"#{k}" for k in nums), [], A, "pads")

    # ---- bottom reinforcement pads (hatched)
    if re.search(r"bottom reinforc|hatch|shaded|pad", ql):
        if not A["pads"] or not k:
            return None
        if re.search(r"how many|number|count", ql):
            n = len(A["pads"])
            ev = [{"kind": "box", "page": 0, "bbox": [p["bbox"][0] / W, p["bbox"][1] / H, p["bbox"][2] / W,
                                                       p["bbox"][3] / H], "label": f"pad {i + 1}", "value": 1}
                  for i, p in enumerate(A["pads"])]
            return _res(n, conf0 * 0.5, f"{n} hatched areas detected (touching pads merge into one)", ev, A, "pads")
        areas = [_m2(p["area_px"], k) for p in A["pads"]]
        tot = sum(areas)
        ev = [{"kind": "polygon", "page": 0, "points": _norm_pts(p["poly"], W, H), "label": f"pad {i + 1}",
               "value": round(a, 2), "unit": "m²", "category": "bottom reinforcement (shaded)"}
              for i, (p, a) in enumerate(zip(A["pads"], areas))]
        return _res(round(tot, 1), conf0 * 0.55, f"{len(areas)} hatched areas measured at {k:.2f} mm/px: "
                    + " + ".join(f"{a:.1f}" for a in areas) + f" = {tot:.1f} m²"
                    + (f" (legend: {A['hatch_note'][:80]})" if A.get("hatch_note") else "")
                    + "; shading detection is approximate", ev, A, "pads", "m²")

    # ---- reinforcement / thickness / elevation (text)
    if re.search(r"\bbars?\b|reinforc|rebar|mesh|thick|elevation|top of slab|\bt\.?o\.?s\b|\bel\b", ql) \
            and not re.search(r"\barea\b|how much|m2|m²|square|" + _VOLUME, ql):
        sel, desc = _match_zones(q, A)
        tys = [(z, _type_of(z, A)) for z in (zones if sel is None else sel) if _type_of(z, A)]
        if sel is not None and not tys:  # the note exists but no zone took it: answer from the note itself
            thk_q = {round(int(x) * 25.4) for x in re.findall(r"\b(\d{1,2})\s*(?:\"|-?IN\.?\b|-?INCH)", q.upper())}
            thk_q |= {int(x) for x in re.findall(r"\b(\d{2,3})\s*(?:MM)?\s*(?:THICK|THK|SLAB|SOG)", q.upper())}
            tys = [(None, t) for t in A["types"] if t.get("thickness_mm") in thk_q]
        if not tys and A["types"]:
            tys = [(None, t) for t in A["types"]]
        if not tys:
            # no "<thk> SLAB W/ <bar> @ <s>" note (e.g. a tank slab detailed bar by bar): list the bar callouts
            calls = []
            pat = (rf"\b(?:\d+\s*-\s*)?{_BAR}\s*(?:(?:HOOP|RADIAL BARS|BARS|CLOSED TIES|TIES|STIRRUPS)\s*)?"
                   r"(?:@|X|x)\s*\d{2,5}"
                   r"(?:\s*(?:E\.?\s?W\.?|EACH WAY|TOP AND BOTTOM|TOP|BOTTOM|LONG|O\.?C\.?))*"
                   rf"|\b{_BAR}\s*(?:RADIAL|HOOP|STIRRUP|DOWEL)S?(?:\s*BARS?)?\b")
            # OCR reads a metric bar's D as 0 ("TYP ROOF REINF. 022 @ 300")
            text = re.sub(r"(?<![\w.])0([1-3]\d)(?=\s*@)", r"D\1", A.get("text", ""))
            typ = bool(re.search(r"\btyp(?:ical)?\b", ql))
            for line in text.split("\n"):
                for m in re.finditer(pat, line, re.I):
                    c = re.sub(r"\s+", " ", m.group(0)).strip()
                    if typ and re.search(r"\bTYP", line, re.I):
                        c = "TYP " + c
                    if c not in calls:
                        calls.append(c)
            if typ and any(c.startswith("TYP ") for c in calls):  # "the typical reinforcement": the TYP callout
                calls = [c[4:] for c in calls if c.startswith("TYP ")]
            calls = [c[4:] if c.startswith("TYP ") else c for c in calls]
            if not calls or not re.search(r"bars?|reinforc|rebar", ql):
                return None
            kind = re.search(r"\b(radial|hoop|stirrup|dowel)", ql)
            if kind:  # "the radial bars": the callouts naming them
                calls = [c for c in calls if kind.group(1).upper() in c.upper()] or calls
            elif not any("@" in c for c in calls):
                # only bar marks with a length (an extra "D22x3000" under the columns): the reinforcement itself
                # ("D19 @ 250 E.W.") was not read, so the general reader looks instead of a misleading part answer
                return None
            return _res("; ".join(calls[:8]), conf0 * 0.6, f"{len(calls)} bar callouts read on the sheet (no slab-type "
                        "note)", [], A, "bars")
        out, ev = [], []
        for z, t in tys:
            if re.search(r"elevation|top of slab|\bt\.?o\.?s\b|\bel\b", ql):
                v = f"{_type_name(t)}: top of slab EL. {t['elevation']}" if t.get("elevation") else None
            elif "thick" in ql:
                v = f"{t['thickness_mm']} mm ({', '.join(t['bars'])})" if t.get("thickness_mm") else None
            else:
                faces = " top face" if "top" in t.get("faces", []) else ""
                extra = "; bottom face reinforcing as indicated (hatched pads)" if t.get("bottom_as_indicated") else ""
                v = f"{', '.join(t['bars'])}{faces}{extra}" if t.get("bars") else None
                if len({_type_name(tt) for _, tt in tys}) > 1 and v:
                    v = f"{_type_name(t).split(' w/')[0]} slab: {v}"
            if v:
                out.append(v)
                ev.append(_text_ev(t["bbox"], f"note: {t['text'][:80]}"))
                if z:
                    ev.append(_zone_ev(z, A, _type_name(t), None))
        if not out:
            return None
        out = list(dict.fromkeys(out))  # the same note on two rooms answers once
        ans = out[0] if len(out) == 1 else "; ".join(out)
        return _res(ans, conf0 + 0.1 if len(out) == 1 else conf0, "read from the slab note(s): "
                    + " | ".join(t["text"][:90] for _, t in tys), ev, A, "note")

    # ---- areas
    volume = bool(re.search(_VOLUME, ql))
    if volume or re.search(r"\barea\b|how much slab|\bm2\b|m²|square|\bsq\.?\s?f|\bsf\b|how big|size of|footprint",
                           ql):
        if not zones or not k or not any(_type_of(z, A) for z in zones):
            return None  # no slab zone tied to a slab note: not a plan this module understands (let generic answer)
        rows = []
        for z in zones:
            a, how, used = _zone_area(z, A)
            rows.append((z, a, how, used))
        conf = conf0
        if A.get("scale_src") and "sheet size" in A["scale_src"]:
            conf *= 0.7  # scale from the sheet size: right only if the image is the whole, uncropped sheet
        typed = [r for r in rows if _type_of(r[0], A)]
        if typed and len(typed) < len(rows):
            # closed areas no slab note claims (title-block cells, pits, pads drawn as rooms) are not counted
            skipped = [r for r in rows if not _type_of(r[0], A)]
            z0, a0, h0, u0 = typed[0]
            typed[0] = (z0, a0, h0 + f" ({len(skipped)} closed area(s) with no slab note, "
                        f"{sum(r[1] for r in skipped):.1f} m², not counted)", u0)
            rows = typed
            conf *= 0.9
            zones = [r[0] for r in rows]
        elif len(typed) < len(rows):
            conf *= 0.8
        used_t = {z.get("type") for z in zones}
        if any(i not in used_t for i in range(len(A["types"]))):
            conf *= 0.7  # a slab note found no zone: some slab was not segmented (area is likely short)
        if any(len(z["inner"]) > 8 for z in zones):
            conf *= 0.75  # ragged outline: the zone probably leaked or lost a corner
        if any(z.get("dim_note") for z in zones):
            conf *= 0.85  # a zone rebuilt from the dimension strings: right size, assumed rectangular
        U = "m²"
        if volume:  # concrete volume = slab area x slab thickness, per zone
            vrows = []
            for z, a, how, used in rows:
                t = _type_of(z, A)
                if not t or not t.get("thickness_mm"):
                    continue
                th = t["thickness_mm"] / 1000
                vrows.append((z, a * th, f"{a:.2f} m² × {th:.3f} m = {a * th:.2f} m³ (area: {how})", used))
            if not vrows:
                return None
            rows, U = vrows, "m³"
            zones = [r[0] for r in rows]
        sel, desc = _match_zones(q, A)
        by_type = re.search(r"by (?:slab )?type|per (?:slab )?type|each (?:slab )?type|each slab|by thickness|breakdown|"
                            r"types? of slab", ql)
        if sel is not None:
            rs = [r for r in rows if r[0] in sel]
            if not rs:
                return None
            tot = sum(r[1] for r in rs)
            ev = []
            for z, a, how, used in rs:
                t = _type_of(z, A)
                ev.append(_zone_ev(z, A, f"{_type_name(t)} ({z.get('type_how', '')})", round(a, 2)))
                ev.append(_text_ev(t["bbox"], f"type note: {t['text'][:80]}"))
            expl = " + ".join(f"[{_type_name(_type_of(z, A))}] {how}" for z, a, how, used in rs)
            if len(rs) > 1:
                expl += f" → total {tot:.2f} {U}"
            return _vol_or_area(_res(round(tot, 2), conf, f"{desc} slab: {expl}", ev, A, "area", U), A, ql)
        tot = sum(r[1] for r in rows)
        ev = []
        for z, a, how, used in rows:
            t = _type_of(z, A)
            ev.append(_zone_ev(z, A, _type_name(t) if t else "slab zone (type unread)", round(a, 2)))
            if t:
                ev.append(_text_ev(t["bbox"], f"type note: {t['text'][:80]}"))
        if by_type:
            groups: dict = {}
            for z, a, how, used in rows:
                t = _type_of(z, A)
                groups.setdefault(_type_name(t) if t else "untyped", []).append(a)
            ans = "; ".join(f"{n}: {sum(v):.1f} {U}" for n, v in groups.items()) + f" (total {tot:.1f} {U})"
            expl = " | ".join(f"[{_type_name(_type_of(z, A)) if _type_of(z, A) else 'untyped'}] {how}"
                              for z, a, how, used in rows)
            return _vol_or_area(_res(ans, conf, expl, ev, A, "area-by-type", U), A, ql)
        expl = " + ".join(f"{a:.2f}" for _, a, _, _ in rows) + f" = {tot:.2f} {U} (" + " | ".join(
            f"[{_type_name(_type_of(z, A)) if _type_of(z, A) else 'untyped'}] {how}" for z, a, how, used in rows) + ")"
        what = "total concrete volume" if volume else "total slab area"
        return _vol_or_area(_res(round(tot, 2), conf, f"{what}: {expl}", ev, A, "area", U), A, ql)

    if re.search(r"how many .*(slab types|types of slab|slab zones)", ql):
        n = len({_type_name(t) for t in A["types"]})
        return _res(n, conf0, f"{n} distinct slab notes", [_text_ev(t["bbox"], t["text"][:80]) for t in A["types"]],
                    A, "note")
    return None


def warm(meta):
    """Upload-time warm-up (bp.sheets.warm_upload): run the analysis once so the first question is instant."""
    analyse(meta)
