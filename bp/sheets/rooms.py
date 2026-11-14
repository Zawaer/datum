"""Room areas and baseboard (skirting) lengths on raster architectural floor plans.

Pipeline (segment_rooms), all geometry on a copy resampled to WORK_PPM pixels per metre:
  1. walls   = dark pixels (< DARK) opened by a 3 px disc: solid wall poché survives, thin linework (door
               leaves and swings, glazing lines, furniture, text, stair treads, dashed overheads) does not.
  2. gaps    = gaps in a wall line, found by closing the wall mask along x and along y. A gap band is kept
               when it is wall-thick (<= MAX_WALL_M) and either glazed (a thin line runs along >= 85 % of it:
               a window, any length up to MAX_WINDOW_M) or short enough to be a doorway (<= MAX_DOOR_M).
               Doorways (unglazed gaps) are the door openings used for baseboards.
  3. rooms   = 4-connected components of what is neither wall nor gap, not touching the image edge, >= MIN_ROOM_M2.
               Area = pixel count / px_per_m^2 (net internal area to the wall faces, doorways closed on the
               wall line). Perimeter = length of the simplified outline.
  4. labels  = OCR text lines whose centre lies in the room (tesseract via bp.sheets.ocr_words).
  baseboard = perimeter - widths of the doorways on the room's outline (windows are not deducted: the
              skirting runs under a window sill).

Scale (scale_from_bar): the scale bar is found from its printed numbers ("0 ... 10m 20m"), then its drawn bar
(the long thin line just above the numbers) gives the exact pixel span; falls back to the label centres, then
to the printed ratio on the paper size in the title block.
"""
from __future__ import annotations

import re
import tempfile
import threading

import numpy as np

from bp import sheets

WORK_PPM = 50.0      # geometry resolution (px per metre)
DARK = 110           # gray level below which a (resampled) pixel is ink
MAX_WALL_M = 0.7     # thickest wall band considered a wall line
MAX_DOOR_M = 2.1     # widest unglazed gap closed as a doorway (double doors ~1.8 m)
MAX_WIDE_M = 3.6     # widest unglazed gap closed when door swings are drawn along it (pairs of doors)
MAX_WINDOW_M = 6.0   # widest glazed gap closed as a window
MIN_ROOM_M2 = 0.8
MIN_WIDTH_M = 0.7
COARSE_PPM = 35.0    # below this many px per metre single rooms are not trusted (only totals / footprint)    # narrower spaces are niches / recesses
LINE_M = 0.25        # wall pieces shorter than this along an axis don't bridge gaps along it
FT = 0.3048
PAPER_MM = {"A0": 1189, "A1": 841, "A2": 594, "A3": 420, "A4": 297}
WET = r"\b(wc|toilets?|shower\w*|changing|hygiene|bath\w*|wash\w*|laundry|kitchen|cleaner\w*|utility|sluice)\b"
_lock = threading.RLock()


# ------------------------------------------------------------------------------------------------- image io
def _gray(image) -> np.ndarray:
    if isinstance(image, np.ndarray):
        return image if image.ndim == 2 else image[..., :3].mean(axis=2).astype(np.uint8)
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    return gray_unmarked(Image.open(image))


MARK_SAT = 85  # max - min of R, G, B above which a red pixel is pen ink, not black / grey linework or a pink fill
MARK_SAT_COOL = 50  # the same for green / blue pens (a blurred green pen on grey paper is ~(60, 130, 70))


def mark_mask(rgb: np.ndarray) -> np.ndarray | None:
    """Thin strokes of saturated colour (hand markings in red / green pen on a scan: ticks, circles, underlines, numbers)
    as a bool mask, or None when there are none. Colour fills (zone shading) are wide, not thin, and are kept."""
    import cv2

    H, W = rgb.shape[:2]

    def pen(b):  # pen colours only: red, green, blue (drawn orange / brown furniture or a pink zone is not a pen)
        b = np.ascontiguousarray(b[..., :3])
        hue = cv2.cvtColor(b, cv2.COLOR_RGB2HSV)[..., 0]  # 0..180
        sat = b.max(axis=2).astype(np.int16) - b.min(axis=2)
        red = ((hue <= 10) | (hue >= 168)) & (sat > MARK_SAT)  # pink zone fills reach ~60
        cool = (((hue >= 42) & (hue <= 85)) | ((hue >= 100) & (hue <= 128))) & (sat > MARK_SAT_COOL)
        return red | cool
    if float(pen(rgb[::4, ::4]).mean()) < 2e-4:
        return None
    m = np.zeros((H, W), np.uint8)
    for y in range(0, H, 1024):  # in bands: an int16 copy of a 10000 px sheet would be ~400 MB
        m[y:y + 1024] = pen(rgb[y:y + 1024])
    k = max(5, round(max(H, W) / 2500 * 6)) | 1  # wider than a pen stroke (~3 px at 2500 px)
    wide = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    wide = cv2.dilate(wide, np.ones((3, 3), np.uint8))
    thin = (m > 0) & (wide == 0)
    if not thin.any():
        return None
    return cv2.dilate(thin.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0  # and their anti-aliased rims


def unmark(rgb: np.ndarray) -> np.ndarray:
    """rgb with pen markings painted over in the paper's colour (see mark_mask); the input when there are none."""
    mm = mark_mask(rgb)
    if mm is None:
        return rgb
    return _inpaint(np.ascontiguousarray(rgb[..., :3]), mm)


def _inpaint(a, mm):
    """Fill the masked pixels from their surroundings: a pen stroke over paper becomes paper, over a wall the wall's
    ink continues (blanking it would open a gap that lets a room leak). Only the masked boxes are processed."""
    import cv2

    out = a.copy()
    n, lab, st, _ = cv2.connectedComponentsWithStats(mm.astype(np.uint8), 8)
    H, W = mm.shape
    for i in range(1, n):
        x, y, w, h = st[i, :4]
        x0, y0, x1, y1 = max(0, x - 6), max(0, y - 6), min(W, x + w + 6), min(H, y + h + 6)
        sub = (lab[y0:y1, x0:x1] == i).astype(np.uint8)
        out[y0:y1, x0:x1] = cv2.inpaint(np.ascontiguousarray(out[y0:y1, x0:x1]), sub, 3, cv2.INPAINT_TELEA)
    return out


_GRAY_CACHE: dict = {}  # (file, mtime, size) -> grey array, the last two colour sheets (each module loads them often)


def gray_unmarked(im) -> np.ndarray:
    """Grey array of a PIL image with coloured pen markings removed (grey / bilevel images are converted as they are)."""
    import os

    if im.mode in ("1", "L", "LA", "I", "I;16", "F"):
        return np.asarray(im.convert("L"))
    fn = getattr(im, "filename", "") or ""
    key = None
    if fn and os.path.exists(fn):
        key = (fn, os.path.getmtime(fn), im.size)
        with _lock:
            if key in _GRAY_CACHE:
                return _GRAY_CACHE[key]
    rgb = np.asarray(im.convert("RGB"))
    mm = mark_mask(rgb)
    g = np.asarray(im.convert("L"))
    if mm is not None:
        g = _inpaint(g, mm)
    g.setflags(write=False)
    if key:
        with _lock:
            _GRAY_CACHE[key] = g
            while len(_GRAY_CACHE) > 2:
                _GRAY_CACHE.pop(next(iter(_GRAY_CACHE)))
    return g


def _words(image, words=None, meta=None):
    """OCR words ({"text", "bbox" normalised, "conf"}); shares bp.sheets' per-meta cache when meta is given."""
    if words is not None:
        return words
    if meta is not None:
        return sheets.ocr_words(meta, scale=2.0 if max(meta["w"], meta["h"]) < 3000 else 1.0, min_conf=35)
    if isinstance(image, np.ndarray):
        from PIL import Image

        tf = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        Image.fromarray(_gray(image)).save(tf.name)
        path, (h, w) = tf.name, _gray(image).shape
    else:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = None
        path = str(image)
        w, h = Image.open(path).size
    return sheets.ocr_words({"image": path, "w": w, "h": h}, scale=2.0 if max(w, h) < 3000 else 1.0, min_conf=35)


# ------------------------------------------------------------------------------------------------- scale
def _bar_from_words(g, ws):
    """The scale bar from its printed numbers among OCR words (see scale_info), refined by the drawn bar; or None."""
    H, W = g.shape
    nums = []
    for w in ws:
        m = re.fullmatch(r"(\d{1,4}(?:\.\d+)?)\s*(m|M|'|’|ft)?", w["text"].strip())
        if m:
            unit = {"m": "m", "M": "m", None: None}.get(m.group(2), "ft")
            nums.append((float(m.group(1)), unit, w))
    best = None
    for v, unit, w in nums:
        if v <= 0 or unit is None:
            continue
        cy = (w["bbox"][1] + w["bbox"][3]) / 2
        hh = w["bbox"][3] - w["bbox"][1]
        row = [(v2, w2) for v2, u2, w2 in nums if abs((w2["bbox"][1] + w2["bbox"][3]) / 2 - cy) < 0.6 * hh]
        zeros = [w2 for v2, w2 in row if v2 == 0 and w2["bbox"][2] < w["bbox"][0]]
        far = max(row, key=lambda r: r[0])
        if far[1] is not w:
            continue
        val_m = far[0] * (1.0 if unit == "m" else FT)
        fx = (far[1]["bbox"][0] + far[1]["bbox"][2]) / 2 * W
        if zeros:
            z = max(zeros, key=lambda q: q["bbox"][0])
            zx = (z["bbox"][0] + z["bbox"][2]) / 2 * W
            how0 = "'0'"
        else:  # the "0" was not read: extrapolate from the two largest numbers (e.g. "10m" and "20m")
            near = [r for r in row if 0 < r[0] < far[0] and r[1]["bbox"][2] < far[1]["bbox"][0]]
            if not near:
                continue
            n_ = max(near, key=lambda r: r[0])
            nx = (n_[1]["bbox"][0] + n_[1]["bbox"][2]) / 2 * W
            zx = fx - (fx - nx) * far[0] / (far[0] - n_[0])
            z = {"bbox": [zx / W, far[1]["bbox"][1], zx / W, far[1]["bbox"][3]]}
            how0 = f"'0' (extrapolated from '{n_[1]['text']}')"
        if fx - zx < 20:
            continue
        how = f"scale bar label centres {how0} to '{far[1]['text']}' = {fx - zx:.0f} px"
        span = fx - zx
        boxes = [z["bbox"], far[1]["bbox"]]
        # refine with the drawn bar: the widest ink run in the band just above the labels
        th = hh * H
        y0, y1 = int(max(0, z["bbox"][1] * H - 5 * th)), int(z["bbox"][1] * H)
        x0, x1 = int(max(0, zx - 2 * th)), int(min(W, fx + 2 * th))
        band = g[y0:y1, x0:x1] < 128
        if band.size:
            import cv2

            n, lab, st, _ = cv2.connectedComponentsWithStats(band.astype(np.uint8), connectivity=8)
            if n > 1:
                i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_WIDTH]))
                bx0, bw = x0 + st[i, 0], st[i, 2]
                if abs(bx0 - zx) < 1.5 * th and abs(bx0 + bw - fx) < 1.5 * th and bw > 0.7 * span:
                    span = float(bw)
                    how = f"scale bar 0-{far[1]['text']} drawn {bw} px long"
                    by0 = y0 + st[i, 1]
                    boxes = [[float(bx0 / W), float(by0 / H), float((bx0 + bw) / W), float((by0 + st[i, 3]) / H)]]
        cand = {"px_per_m": float(span / val_m), "how": how, "boxes": boxes, "_k": (len(row), val_m)}
        if best is None or cand["_k"] > best["_k"]:
            best = cand
    return best


def _scale_crop_words(image, ws, W, H, up=4.0):
    """OCR words (normalised to the page) of the areas around the printed word SCALE, upscaled; [] if none."""
    import shutil
    import subprocess

    from PIL import Image

    if not shutil.which("tesseract"):
        return []
    sw = [w for w in ws if re.fullmatch(r"(?i)scale\W*", w["text"].strip())]
    if not sw or len(sw) > 6:
        return []
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(image).convert("L")
    out = []
    for w in sw:
        x0, y0, x1, y1 = w["bbox"][0] * W, w["bbox"][1] * H, w["bbox"][2] * W, w["bbox"][3] * H
        h = max(4.0, y1 - y0)
        box = (int(max(0, x0 - 6 * h)), int(max(0, y0 - 7 * h)), int(min(W, x0 + 0.22 * W)), int(min(H, y1 + 7 * h)))
        if box[2] - box[0] < 10 or box[3] - box[1] < 10:
            continue
        c = im.crop(box)
        c = c.resize((int(c.width * up), int(c.height * up)), Image.LANCZOS)
        with tempfile.NamedTemporaryFile(suffix=".png") as tf:
            c.save(tf.name)
            try:
                tsv = subprocess.run(["tesseract", tf.name, "-", "--psm", "11", "tsv"], capture_output=True,
                                     text=True, timeout=30).stdout
            except subprocess.TimeoutExpired:
                continue
        for line in tsv.splitlines()[1:]:
            p = line.split("\t")
            if len(p) < 12 or not p[11].strip() or float(p[10]) < 30:
                continue
            lx, ty, wd, ht = (int(v) / up for v in p[6:10])
            out.append({"text": p[11].strip(), "conf": float(p[10]),
                        "bbox": [(box[0] + lx) / W, (box[1] + ty) / H, (box[0] + lx + wd) / W, (box[1] + ty + ht) / H]})
    return out


def scale_info(image, words=None, meta=None) -> dict | None:
    """{"px_per_m", "how", "boxes": [normalised bboxes of the bar / labels]} or None."""
    g = _gray(image)
    H, W = g.shape
    ws = _words(image, words, meta)
    out = _bar_from_words(g, ws)
    if out is None and not isinstance(image, np.ndarray) and not (meta or {}).get("words"):
        # small raster: the bar's numbers ("0' 4' 8' 16' 32'") are too small for the page OCR; read the area around
        # the printed word SCALE again, upscaled
        extra = _scale_crop_words(image, ws, W, H)
        if extra:
            out = _bar_from_words(g, extra)
    # printed ratio + paper size (fallback, or a cross-check)
    txt = " ".join(w["text"] for w in ws) + " " + ((meta or {}).get("scale") or "")
    rm = re.search(r"\b1\s*:\s*(\d{2,4})\b", txt)
    pm = re.search(r"\b(A[0-4])\b", txt)
    if rm and pm:
        ppm = max(W, H) / PAPER_MM[pm.group(1)] * 1000 / int(rm.group(1))
        if out is None:
            out = {"px_per_m": ppm, "how": f"printed scale 1:{rm.group(1)} on an {pm.group(1)} sheet", "boxes": []}
        else:
            dev = out["px_per_m"] / ppm - 1
            out["check"] = f"1:{rm.group(1)} on {pm.group(1)} gives {ppm:.1f} px/m ({100 * dev:+.1f} %)"
            if "drawn" not in out["how"] and abs(dev) < 0.03:  # label centres are coarse; the ratio is exact
                out["px_per_m"] = ppm
                out["how"] = f"printed scale 1:{rm.group(1)} on {pm.group(1)}, confirmed by the scale bar labels"
    if out:
        out.pop("_k", None)
    return out


def scale_from_bar(image, words=None, meta=None) -> float | None:
    """Pixels per metre of the sheet image, from its scale bar (or printed ratio + paper size); None if unknown."""
    s = scale_info(image, words, meta)
    return s["px_per_m"] if s else None


# ------------------------------------------------------------------------------------------------- segmentation
def _gaps(wall, thin, axis, ppm, faint=None, panels=False):
    """Gap bands in wall lines along `axis` (1: horizontal walls, 0: vertical walls).
    Returns [(mask_slice_box, component mask, length_m, glazed)] in work pixels. faint (coarse sheets only): lighter
    linework that also counts as a glazing / hatch line along a gap (a 1 px line resampled from a 2500 px render or a
    150 dpi scan is grey, not black)."""
    import cv2

    L = int(MAX_WINDOW_M * ppm)
    # only wall pieces elongated along the axis may bridge a gap: an opening with a short line kernel removes
    # thin walls running across the axis, so a room between two such walls is not mistaken for a gap
    s = max(3, int(LINE_M * ppm))
    along = cv2.morphologyEx(wall, cv2.MORPH_OPEN, np.ones((1, s) if axis == 1 else (s, 1), np.uint8))
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1) if axis == 1 else (1, L))
    pad = L + 2  # pad with empty paper so the image edge never acts as a wall end
    closed = cv2.morphologyEx(cv2.copyMakeBorder(along, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0),
                              cv2.MORPH_CLOSE, k)[pad:-pad, pad:-pad]
    band = (closed > 0) & (wall == 0)
    if axis == 0:  # work on rows: transpose vertical walls into horizontal ones
        band, thin, wall = band.T, thin.T, wall.T
        faint = faint.T if faint is not None else None
    leafy = thin & (cv2.dilate(wall, np.ones((3, 3), np.uint8)) == 0)  # not the anti-aliased rim of a wall
    leafy_d = cv2.dilate(leafy.astype(np.uint8), np.ones((1, 3), np.uint8)) > 0  # leaves drawn a little off square
    # glazing lines, allowed to wander by a pixel across rows after resampling
    thin_d = cv2.dilate((thin if faint is None else thin | faint).astype(np.uint8), np.ones((3, 1), np.uint8)) > 0
    # gap runs per row; a gap is a stack of runs in consecutive rows with (nearly) the same ends. Grouping runs
    # instead of taking connected components keeps a doorway apart from slivers along ragged wall edges.
    pad = np.zeros((band.shape[0], 1), bool)
    bb = np.hstack([pad, band, pad]).astype(np.int8)
    d = np.diff(bb, axis=1)
    rs, cs0 = np.nonzero(d == 1)
    _, cs1 = np.nonzero(d == -1)
    active: dict = {}
    groups = []
    for r, c0, c1 in zip(rs.tolist(), cs0.tolist(), (cs1 - 1).tolist()):
        g = None
        for key in ((c0, c1), (c0 - 1, c1), (c0 + 1, c1), (c0, c1 - 1), (c0, c1 + 1)):
            cand = active.get(key)
            if cand is not None and cand["r1"] == r - 1:
                g = cand
                del active[key]
                break
        if g is None:
            g = {"r0": r, "r1": r, "c0": c0, "c1": c1, "lens": []}
            groups.append(g)
        g["r1"] = r
        g["c0"], g["c1"] = min(g["c0"], c0), max(g["c1"], c1)
        g["lens"].append(c1 - c0 + 1)
        active[(c0, c1)] = g
    out = []
    for g in groups:
        thick = g["r1"] - g["r0"] + 1
        length = int(np.median(g["lens"]))
        if thick > MAX_WALL_M * ppm or thick < 2 or length < 2:
            continue
        t = thin_d[g["r0"]:g["r1"] + 1, g["c0"]:g["c1"] + 1]
        glazed = bool(t.size) and t.mean(axis=1).max() >= 0.8
        if not glazed and length > MAX_DOOR_M * ppm:
            # wider than one door: a pair / run of doors when the swings are drawn next to it, else an open bay
            if length > MAX_WIDE_M * ppm or not _has_swing(leafy, g, length, ppm):
                continue
        # an unglazed gap with no door leaf drawn at either jamb is an open niche / archway: kept as "open",
        # closed only when it lets a room leak to the outside (a door drawn half open, a bifold, a missing leaf)
        leaf = glazed or _has_leaf(leafy_d, g, length, ppm) or _has_swing(leafy, g, length, ppm)
        panel = None if not panels or glazed or not t.size else _side_panel(t, ppm)
        x, y, w, h = g["c0"], g["r0"], g["c1"] - g["c0"] + 1, thick
        if axis == 0:
            x, y, w, h = y, x, h, w
        out.append(((x, y, w, h), length / ppm, glazed, leaf, panel) if panels else
                   ((x, y, w, h), length / ppm, glazed, leaf))
    return out


def _side_panel(t, ppm):
    """A glazed side panel at one end of a doorway gap (t: the gap's thin-line mask, rows across the wall, columns
    along it): from one end, a run of columns with glazing lines across the wall, 0.25-1.2 m long, then >= 0.6 m of
    clear opening. Returns (end 0 | 1, panel length in work px) or None."""
    if t.shape[0] < 3:
        return None
    inner = t[1:-1] if t.shape[0] > 4 else t
    col = inner.any(axis=0)
    n = col.size
    for end in (0, 1):
        c = col if end == 0 else col[::-1]
        k = 0
        while k < n and c[k:k + 3].any():  # a run of line-crossed columns, one or two missing columns bridged
            k += 1
        if not (0.25 * ppm <= k <= 1.2 * ppm) or n - k < 0.6 * ppm:
            continue
        if c[k + int(0.1 * ppm):].mean() > 0.15:  # the rest is open (a door opening), not more glazing
            continue
        # lines along the panel: most of its rows in the panel part carry a line over >= 80 % of it
        part = t[:, :k] if end == 0 else t[:, n - k:]
        if part.mean(axis=1).max() < 0.8:
            continue
        return end, k
    return None


def _scan_like(g) -> bool:
    """A scanned / photographed sheet: grey paper noise and soft edges (lots of mid-grey next to the ink), unlike
    a CAD render or screenshot whose paper is clean white."""
    sub = g[::4, ::4]
    paper = sub[sub >= 230]
    dark = float((sub < 100).mean())
    mid = float(((sub >= 100) & (sub < 230)).mean())
    return bool(paper.size and (paper < 250).mean() > 0.3) or (dark > 0 and mid / dark > 1.8)


def _has_swing(leafy, g, length, ppm):
    """Door swings drawn along a gap: enough thin linework within 0.5 m of the gap, on one side, between its
    jambs (arcs of a pair of doors, double-acting doors drawn as arcs only). Open niches have none that close."""
    d = int(0.5 * ppm)
    e = max(1, int(0.1 * ppm))
    H, W = leafy.shape
    cols = slice(g["c0"] + e, max(g["c0"] + e + 1, g["c1"] - e))
    for rows in (slice(max(0, g["r0"] - d), g["r0"]), slice(g["r1"] + 1, min(H, g["r1"] + 1 + d))):
        if leafy[rows, cols].sum() >= 0.4 * length:
            return True
    return False


def _has_leaf(leafy, g, length, ppm):
    """A drawn door leaf: a thin straight line square to the wall, starting at one end of the gap, at least 40 %
    of the gap long (single leaf ~100 %, each leaf of a pair ~50 %), on either side of the wall."""
    k = max(2, int(0.12 * ppm))
    ln = max(3, int(0.4 * length))
    H, W = leafy.shape
    for c in (g["c0"], g["c1"]):
        cols = slice(max(0, c - k), min(W, c + k + 1))
        for rows in (slice(max(0, g["r0"] - ln), g["r0"]), slice(g["r1"] + 1, min(H, g["r1"] + 1 + ln))):
            blk = leafy[rows, cols]
            if blk.shape[0] >= ln and blk.size and blk.mean(axis=0).max() >= 0.8:
                return True
    return False


def segment_rooms(image, px_per_m: float | None = None, words=None, meta=None, with_labels: bool = True) -> list[dict]:
    """Rooms of a floor plan image: [{"polygon": [[x, y], ...] (image px), "area_m2", "perimeter_m",
    "doors": [{"width_m", "bbox"}], "baseboard_m", "label", "bbox"}], largest first.
    The returned list has attributes-like extras in rooms[i]; whole-sheet info via segment()."""
    return segment(image, px_per_m, words, meta, with_labels)["rooms"]


def segment(image, px_per_m=None, words=None, meta=None, with_labels=True) -> dict:
    import cv2

    g = _gray(image)
    H, W = g.shape
    scan = _scan_like(g)
    if scan:
        # grey scan paper / toner that is never black: stretch paper to white and ink to black first, so the ink,
        # thin-line and fill thresholds below mean the same as on a clean render (grey paper hid every door swing)
        sub = g[::4, ::4]
        lo, hi = float(np.percentile(sub, 0.5)), float(np.percentile(sub, 90))
        if hi - lo > 40 and (hi < 245 or lo > 15):
            lut = np.clip((np.arange(256) - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)
            g = lut[g]
    sc = None
    if px_per_m is None:
        sc = scale_info(image, words, meta)
        if sc is None:
            return {"rooms": [], "scale": None, "doors": [], "footprint_m2": None}
        px_per_m = sc["px_per_m"]
    # low-resolution sheets (screenshots, ~15-30 px/m) are upsampled to the work resolution: the same metric
    # thresholds then apply, and the resampled thin lines stay lighter than the solid walls
    f = WORK_PPM / px_per_m
    ppm = px_per_m * f
    size = (max(1, round(W * f)), max(1, round(H * f)))
    small = cv2.resize(g, size, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)
    ink = (small < DARK).astype(np.uint8)
    # thin black linework (not the grey furniture layer), any ink in the work cell
    thin = cv2.resize((g < 128).astype(np.uint8) * 255, size,
                      interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_NEAREST) > 40
    # how thick the walls are in the source pixels: thin walls (< ~3 px) make areas and openings less reliable
    dist = cv2.distanceTransform(cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), cv2.DIST_L2, 3)
    ridge = dist[dist >= 1.5]
    wall_px = float(2 * np.median(ridge) / f) if ridge.size else 0.0
    # coarse sources (screenshots, 2500 px renders, 150 dpi scans): single-pixel glazing / serving-hatch lines are
    # resampled to mid grey (~190-215), so they fail the black test and a hall leaked into its servery and kitchen
    faint = None
    if px_per_m < 40 or scan:
        paper = float(np.percentile(g[::4, ::4], 90))  # 255 on a render, ~220 on grey scan paper
        faint = cv2.resize((g < min(220.0, paper - 35)).astype(np.uint8) * 255, size,
                           interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_NEAREST) > 40
    disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    wall = cv2.morphologyEx(ink, cv2.MORPH_OPEN, disc)
    # drop specks (text dots, arrow heads stay but are harmless)
    n, lab, st, _ = cv2.connectedComponentsWithStats(wall, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 0.04 * ppm * ppm
    wall = keep[lab].astype(np.uint8)

    barrier = wall.copy()
    glazing, side_panels = [], []
    doors, open_gaps, bands = [], [], []  # bands: every gap closed (doorways, glazing, shut openings), work px
    for axis in (1, 0):
        for (x, y, w, h), length, glazed, leaf, panel in _gaps(wall, thin, axis, ppm, faint, panels=True):
            if panel:  # a glazed side panel beside the doorway: (x, y, w, h) of the panel part, work px
                end, k = panel
                if axis == 1:
                    pb = (x, y, k, h) if end == 0 else (x + w - k, y, k, h)
                else:
                    pb = (x, y, w, k) if end == 0 else (x, y + h - k, w, k)
                side_panels.append({"length_m": round(k / ppm, 2), "box": pb, "axis": axis})
            if not leaf:
                open_gaps.append((x, y, w, h, length, axis))
                continue
            barrier[y:y + h, x:x + w] = 1
            bands.append((x, y, w, h))
            if not glazed:
                doors.append({"width_m": round(length, 2), "box": (x, y, w, h), "axis": axis})
            else:
                glazing.append({"length_m": round(length, 2), "box": (x, y, w, h), "axis": axis})

    def components():
        free = (barrier == 0).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
        border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
        return free, n, lab, st, border

    free, n, lab, st, border = components()
    sh, sw = free.shape
    shut = 0
    for x, y, w, h, length, axis in open_gaps:  # openings onto the outside are doors, leaf drawn or not
        ring = lab[max(0, y - 2):y + h + 2, max(0, x - 2):x + w + 2]
        if border & set(np.unique(ring).tolist()):
            barrier[y:y + h, x:x + w] = 1
            bands.append((x, y, w, h))
            doors.append({"width_m": round(length, 2), "box": (x, y, w, h), "axis": axis})
            shut += 1
    if shut:
        free, n, lab, st, border = components()
    for gz in glazing:  # what lies on either side of a glazed band: two spaces (internal) or the outside
        x, y, w, h = gz["box"]
        side = []
        for sg in (-1, 1):
            v = 0
            for o in range(1, int(0.8 * ppm)):  # step off the band (through a thick wall's frame lines) to a space
                if gz["axis"] == 1:
                    px, py = x + w // 2, (y - o if sg < 0 else y + h - 1 + o)
                else:
                    px, py = (x - o if sg < 0 else x + w - 1 + o), y + h // 2
                if not (0 <= px < sw and 0 <= py < sh):
                    break
                v = int(lab[py, px])
                if v:
                    break
            side.append(v)
        gz["outside"] = any(v == 0 or v in border for v in side)
    door_lab = np.zeros(free.shape, np.int32)
    for j, d in enumerate(doors, 1):
        x, y, w, h = d["box"]
        door_lab[y:y + h, x:x + w] = j
    rooms = []
    min_px = MIN_ROOM_M2 * ppm * ppm
    for i in range(1, n):
        if i in border or st[i, cv2.CC_STAT_AREA] < min_px:
            continue
        x, y, w, h, a = st[i]
        # pad by 3 px to see the adjacent doorway bands
        x0, y0, x1, y1 = max(0, x - 3), max(0, y - 3), min(sw, x + w + 3), min(sh, y + h + 3)
        m = (lab[y0:y1, x0:x1] == i).astype(np.uint8)
        if 2 * cv2.distanceTransform(m, cv2.DIST_L2, 3).max() < MIN_WIDTH_M * ppm:
            continue  # a sliver (wall niche, door recess), not a room
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        c = max(cs, key=cv2.contourArea)
        poly = cv2.approxPolyDP(c, 0.03 * ppm, True)[:, 0, :].astype(float)
        poly[:, 0] += x0
        poly[:, 1] += y0
        # pixel-centre outline sits half a pixel inside the region: grow the perimeter by that
        per_px = cv2.arcLength(poly.astype(np.float32).reshape(-1, 1, 2), True) + 4
        mdil = cv2.dilate(m, np.ones((5, 5), np.uint8))
        touch = sorted(set(np.unique(door_lab[y0:y1, x0:x1][mdil > 0])) - {0})
        ds = [doors[j - 1] for j in touch]
        # a doorway band shorter than 0.5 m that touches the room only at its end is a wall return, not a door
        ds = [d for d in ds if d["width_m"] >= 0.5]
        area = a / ppm ** 2
        perim = per_px / ppm
        dw = sum(d["width_m"] for d in ds)
        rooms.append({
            "polygon": [[round(px / f, 1), round(py / f, 1)] for px, py in poly],
            "bbox": [x / f, y / f, (x + w) / f, (y + h) / f],
            "area_m2": round(area, 2), "perimeter_m": round(perim, 2),
            "doors": [{"width_m": d["width_m"], "bbox": [d["box"][0] / f, d["box"][1] / f,
                                                         (d["box"][0] + d["box"][2]) / f,
                                                         (d["box"][1] + d["box"][3]) / f]} for d in ds],
            "baseboard_m": round(max(0.0, perim - dw), 2),
            "label": "", "_i": i})
    # buildings = clusters of walls + rooms; rooms in tiny clusters (bold title-block text, logos) are dropped.
    # footprint = everything enclosed by the outermost walls of the kept clusters (gross area to outer faces)
    solid = ((barrier > 0) | np.isin(lab, [r["_i"] for r in rooms])).astype(np.uint8)
    solid = cv2.morphologyEx(solid, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    nc, clab = cv2.connectedComponents(solid, connectivity=8)
    carea = np.zeros(nc)
    for r in rooms:
        y, x = np.argwhere(lab == r["_i"])[0]
        r["_c"] = int(clab[y, x])
        carea[r["_c"]] += r["area_m2"]
    keep_c = {c for c in range(1, nc) if carea[c] >= max(8.0, 0.05 * carea.max())}
    rooms = [r for r in rooms if r["_c"] in keep_c]
    big = []
    for c in keep_c:
        cs, _ = cv2.findContours((clab == c).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        big.append(max(cs, key=cv2.contourArea))
    footprint = sum(cv2.contourArea(c) for c in big) / ppm ** 2
    # colour-filled space diagrams (rooms shaded by type) are read by the colour-zone path, not by wall gaps
    inside = np.isin(lab[::3, ::3], [r["_i"] for r in rooms])
    fill_gray = float(np.median(small[::3, ::3][inside])) if inside.any() else 255.0
    paper_gray = float(np.percentile(small[::3, ::3], 90))  # grey scan paper: rooms are as grey as the paper
    seg_extra = {"lab": lab, "f": f, "W": W, "H": H, "src_ppm": px_per_m,
                 "vector": bool(words is None and meta and meta.get("words"))}
    if with_labels:
        _label(rooms, lab, f, W, H, _words(image, words, meta), image, src_ppm=px_per_m,
               vector=bool(words is None and meta and meta.get("words")))
    if wall_px < 3:  # low resolution: tiny unlabelled pockets are mostly fragments between door swings
        rooms = [r for r in rooms if r["label"] or r["area_m2"] >= 1.5]
    for r in rooms:
        r["id"] = int(r.pop("_i"))
        r.pop("_c", None)
    rooms.sort(key=lambda r: -r["area_m2"])
    return {"rooms": rooms, "scale": sc or {"px_per_m": px_per_m, "how": "given"}, "px_per_m": px_per_m,
            "wall_px": round(wall_px, 1), "_lab": seg_extra, "scan": scan,
            "fill_gray": fill_gray, "paper_gray": paper_gray,
            "doors": doors, "bands": bands, "footprint_m2": round(footprint, 1),
            "glazing": [{"bbox": [gz["box"][0] / f, gz["box"][1] / f, (gz["box"][0] + gz["box"][2]) / f,
                                  (gz["box"][1] + gz["box"][3]) / f], "length_m": gz["length_m"],
                         "outside": gz["outside"]} for gz in glazing],
            "side_panels": [{"bbox": [p["box"][0] / f, p["box"][1] / f, (p["box"][0] + p["box"][2]) / f,
                                      (p["box"][1] + p["box"][3]) / f], "length_m": p["length_m"]} for p in side_panels],
            "footprint_polys": [[[round(p[0][0] / f, 1), round(p[0][1] / f, 1)] for p in c] for c in big]}


_LABEL_OK = re.compile(r"[A-Za-z]{2,}|\b[A-Z]?\d{2,4}[A-Z]?\b")


def _label(rooms, lab, f, W, H, words, image=None, src_ppm=100.0, vector=False):
    """Label each room with the page words whose centre lies in it (stacked lines joined top to bottom).
    Crop OCR of single rooms is left to relabel(), run lazily for the rooms a question needs."""
    by_i = {r["_i"]: r for r in rooms}
    sh, sw = lab.shape

    def room_of(bb):
        cx = (bb[0] + bb[2]) / 2 * W * f
        cy = (bb[1] + bb[3]) / 2 * H * f
        return int(lab[min(sh - 1, max(0, int(cy))), min(sw - 1, max(0, int(cx)))])

    def near_room(bb):
        """a word whose centre is on a wall / door swing: the room most of its box overlaps, within 0.3 m"""
        x0, y0 = int(bb[0] * W * f), int(bb[1] * H * f)
        x1, y1 = int(bb[2] * W * f) + 1, int(bb[3] * H * f) + 1
        pad = int(0.3 * WORK_PPM)
        blk = lab[max(0, y0 - pad):min(sh, y1 + pad), max(0, x0 - pad):min(sw, x1 + pad)]
        ids, cnt = np.unique(blk[blk > 0], return_counts=True)
        ok = [(c, i) for i, c in zip(ids.tolist(), cnt.tolist()) if i in by_i]
        return max(ok)[1] if ok else None

    per: dict[int, list] = {}
    for w in words:
        i = room_of(w["bbox"])
        if i not in by_i and _LABEL_OK.search(str(w.get("text", ""))):
            i = near_room(w["bbox"])
        if i in by_i:
            per.setdefault(i, []).append(w)
    _join_labels(by_i, per, vector)


def _join_labels(by_i, per, vector):
    for i, ws in per.items():
        lns = [ln for ln in sheets.ocr_lines(ws) if _LABEL_OK.search(ln["text"])]
        lns.sort(key=lambda ln: ln["bbox"][1])
        groups = []
        for ln in lns:  # stack lines that sit right under each other into one label
            h = ln["bbox"][3] - ln["bbox"][1]
            if groups and ln["bbox"][1] - groups[-1][-1]["bbox"][3] < 1.2 * h and \
                    abs((ln["bbox"][0] + ln["bbox"][2]) - (groups[-1][-1]["bbox"][0] + groups[-1][-1]["bbox"][2])) / 2 \
                    < 4 * h:
                groups[-1].append(ln)
            else:
                groups.append([ln])
        labels = [(" ".join(x["text"] for x in gr) if vector else _clean(" ".join(x["text"] for x in gr)))
                  for gr in groups]
        by_i[i]["label"] = " / ".join(dict.fromkeys(x for x in labels if x))


ROOM_WORDS = set("""room rooms hall wc toilet toilets store stores lobby office kitchen stair stairs lift plant bed bath
dorm gym lab shop cafe mech elec elev corr closet foyer entry den study staff group class meeting sick head heads
lab hub art music dining living laundry server parent changing showers shower lounge porch deck patio garage
utility janitor jan cust stor clo mud wash vest hall day unit suite main open play quiet sensory and of""".split())


def _clean(t):
    """OCR label words that look like words: room vocabulary, or >= 5 letters (OCR noise is mostly short)."""
    t = re.sub(r"[|~_—=;:]+", " ", t)
    ws = []
    for w in t.split():
        core = re.sub(r"[^A-Za-z'-]", "", w)
        if re.fullmatch(r"[A-Z]?\d{2,4}[A-Z]?", w.strip(".,")):  # room numbers ("214", "B12", "214A")
            ws.append(w.strip(".,"))
        elif core.lower().strip("'s") in ROOM_WORDS or core.lower() in ROOM_WORDS or \
                (len(core) >= 5 and core.replace("-", "").replace("'", "").isalpha()
                 and re.search(r"[aeiouy]", core.lower())):
            ws.append(w.strip(".,"))
    if ws and all(w.lower() in ("and", "of") for w in ws):
        return ""
    return " ".join(ws).strip()


def _crop_words(image, bbox, W, H, scale=2.0):
    """OCR one room's crop (upscaled); words with bboxes normalised to the full image."""
    import shutil
    import subprocess

    from PIL import Image

    if not shutil.which("tesseract"):
        return []
    Image.MAX_IMAGE_PIXELS = None
    x0, y0, x1, y1 = (max(0, int(bbox[0])), max(0, int(bbox[1])), min(W, int(bbox[2])), min(H, int(bbox[3])))
    im = Image.open(image).convert("L").crop((x0, y0, x1, y1))
    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
    out = []
    with tempfile.NamedTemporaryFile(suffix=".png") as tf:
        im.save(tf.name)
        try:
            tsv = subprocess.run(["tesseract", tf.name, "-", "--psm", "11", "tsv"], capture_output=True, text=True,
                                 timeout=60).stdout
        except subprocess.TimeoutExpired:
            return []
    for line in tsv.splitlines()[1:]:
        p = line.split("\t")
        if len(p) < 12 or not p[11].strip() or float(p[10]) < 40:
            continue
        lx, ty, wd, ht = (int(v) / scale for v in p[6:10])
        out.append({"text": p[11].strip(), "conf": float(p[10]),
                    "bbox": [(x0 + lx) / W, (y0 + ty) / H, (x0 + lx + wd) / W, (y0 + ty + ht) / H]})
    return out


VLABEL_PROMPT = """This is part of an architectural floor plan. Red numbers mark rooms. For each red number, read the room
name printed in that room. If you cannot actually read it, give "" (do not guess from the furniture).
JSON only: {{"1": "Classroom", "2": "WC", ...}} for the numbers {nums}; use "" when you cannot tell."""


def vision_labels(image, rooms, budget_usd: float = 0.3, model: str = "haiku") -> float:
    """Fill missing room labels with a VLM read of the sheet (tiles with numbered rooms). Returns the cost.
    For low-resolution sheets whose printed names are too small for OCR. Cached next to the image."""
    import hashlib
    import json
    import os

    from PIL import Image, ImageDraw

    from bp.generic import llm

    todo = [r for r in rooms if not r["label"] and r["area_m2"] >= 1.5]
    if not todo or isinstance(image, np.ndarray):
        return 0.0
    key = hashlib.sha1(json.dumps([[round(v) for v in r["bbox"]] for r in todo]).encode()).hexdigest()[:12]
    cache = f"{image}.rooms_vlabels_{key}.json"
    got = None
    if os.path.exists(cache):
        try:
            got = json.load(open(cache))
        except (OSError, ValueError):
            got = None
    cost = 0.0
    if got is None:
        got = {}
        Image.MAX_IMAGE_PIXELS = None
        im = Image.open(image).convert("RGB")
        W, H = im.size
        xs = [((r["bbox"][0] + r["bbox"][2]) / 2, (r["bbox"][1] + r["bbox"][3]) / 2) for r in todo]
        x0, y0 = min(x for x, _ in xs), min(y for _, y in xs)
        x1, y1 = max(x for x, _ in xs), max(y for _, y in xs)
        nx = max(1, round((x1 - x0) / max(1, (y1 - y0))))  # ~square tiles over the rooms' extent
        ny = 2 if len(todo) > 30 else 1
        nx = max(1, min(4, nx * ny))
        tw, th = (x1 - x0) / nx + 1, (y1 - y0) / ny + 1
        for ty in range(ny):
            for tx in range(nx):
                if cost >= budget_usd:
                    break
                ids = [i for i, (cx, cy) in enumerate(xs) if x0 + tx * tw <= cx < x0 + (tx + 1) * tw + 1
                       and y0 + ty * th <= cy < y0 + (ty + 1) * th + 1]
                if not ids:
                    continue
                bx0 = max(0, min(todo[i]["bbox"][0] for i in ids) - 20)
                by0 = max(0, min(todo[i]["bbox"][1] for i in ids) - 20)
                bx1 = min(W, max(todo[i]["bbox"][2] for i in ids) + 20)
                by1 = min(H, max(todo[i]["bbox"][3] for i in ids) + 20)
                crop = im.crop((int(bx0), int(by0), int(bx1), int(by1)))
                sc = min(4.0, 1500 / max(crop.size))
                crop = crop.resize((int(crop.width * sc), int(crop.height * sc)), Image.LANCZOS)
                d = ImageDraw.Draw(crop)
                for n, i in enumerate(ids, 1):
                    cx, cy = (xs[i][0] - bx0) * sc, (xs[i][1] - by0) * sc
                    d.text((cx + 6, cy + 6), str(n), fill=(230, 0, 0), font_size=max(14, int(18 * sc / 2)))
                res = llm.ask(VLABEL_PROMPT.format(nums=f"1..{len(ids)}"), [crop], model=model, tag="rooms-vlabel")
                cost += res.get("cost_usd", 0.0)
                js = llm.parse_json(res.get("text", "")) or {}
                for n, i in enumerate(ids, 1):
                    v = js.get(str(n)) if isinstance(js, dict) else None
                    if isinstance(v, str) and v.strip() and "?" not in v:  # guesses from furniture are dropped
                        got[str(i)] = v.strip()
        try:
            json.dump(got, open(cache, "w"))
        except OSError:
            pass
    for i, r in enumerate(todo):
        if got.get(str(i)):
            r["label"] = got[str(i)]
            r["label_source"] = "vision"
    return cost


# ------------------------------------------------------------------------------------------------- answering
CROP_PROMPT = """Each image is one room cut out of an architectural floor plan (everything outside the room is blanked).
Image k is room k. Read the room NAME printed inside each room (e.g. "Secondary Classroom (Severe Needs)", "Library",
"WC", "Corridor"), exactly as printed, without room numbers or areas. If no name is printed in it or you cannot
actually read it, give "" (never guess from the furniture or the shape).
JSON only: {{"1": "...", "2": "...", ...}} for rooms {nums}."""
CROP_TEXT_PX = 2.4   # upscale coarse crops so the printed names (~0.3-0.4 m tall) are >= ~16 px for the VLM
CROP_MAX_PX = 1100
CROP_BATCH = 12


def crop_labels(seg, image, rooms, min_m2: float = 2.0, model: str = "haiku", overwrite: bool = True) -> float:
    """Room names read by a VLM, one cut-out crop per room (upscaled, the rest of the sheet blanked so a
    neighbour's name cannot leak in), CROP_BATCH rooms per call, calls in parallel. For coarse rasters (2500 px
    renders, screenshots, 150 dpi scans) where tesseract garbles names ("Secorrtery Cissrocen"). Sets
    r["label"] (label_source "vision"; overwrite: OCR labels too, they are noise at this resolution). Cached next to
    the image; returns the cost."""
    import concurrent.futures as cf
    import hashlib
    import json
    import os

    import cv2
    from PIL import Image

    from bp.generic import llm

    x = seg.get("_lab") or {}
    if not x or isinstance(image, np.ndarray):
        return 0.0
    todo = [r for r in rooms if r["area_m2"] >= min_m2 and r.get("label_source") != "vision"
            and (overwrite or not r["label"])]
    if not todo:
        return 0.0
    key = hashlib.sha1(json.dumps([[round(v) for v in r["bbox"]] for r in todo]).encode()).hexdigest()[:12]
    cache = f"{image}.rooms_crops_{key}.json"
    got = None
    if os.path.exists(cache):
        try:
            got = json.load(open(cache))
        except (OSError, ValueError):
            got = None
    cost = 0.0
    if got is None:
        lab, f = x["lab"], x["f"]
        sh, sw = lab.shape
        Image.MAX_IMAGE_PIXELS = None
        im = Image.open(image).convert("L")
        W, H = im.size
        # the source raster's own resolution: a scan PDF page rendered at 300 dpi from a 150 dpi image has half the
        # detail its pixel count suggests, but upscaling it further does not hurt
        up = max(1.0, min(4.0, CROP_TEXT_PX * 50.0 / max(1.0, x["src_ppm"])))
        pad_w = max(2, int(0.35 * WORK_PPM))
        crops = []
        for r in todo:
            bx0, by0, bx1, by1 = (int(v * f) for v in r["bbox"])
            bx0, by0, bx1, by1 = max(0, bx0 - pad_w), max(0, by0 - pad_w), min(sw, bx1 + pad_w), min(sh, by1 + pad_w)
            m = (lab[by0:by1, bx0:bx1] == r["id"]).astype(np.uint8)
            m = cv2.dilate(m, np.ones((2 * pad_w + 1, 2 * pad_w + 1), np.uint8))
            ix0, iy0 = int(bx0 / f), int(by0 / f)
            ix1, iy1 = min(W, max(ix0 + 1, int(bx1 / f))), min(H, max(iy0 + 1, int(by1 / f)))
            c = np.asarray(im.crop((ix0, iy0, ix1, iy1))).copy()
            mm = cv2.resize(m, (c.shape[1], c.shape[0]), interpolation=cv2.INTER_NEAREST)
            c[mm == 0] = 255
            s = min(up, CROP_MAX_PX / max(c.shape))
            ci = Image.fromarray(c)
            if s != 1:
                ci = ci.resize((max(1, int(ci.width * s)), max(1, int(ci.height * s))), Image.LANCZOS)
            crops.append(ci)
        batches = [list(range(i, min(len(todo), i + CROP_BATCH))) for i in range(0, len(todo), CROP_BATCH)]

        def run(ids):
            res = llm.ask(CROP_PROMPT.format(nums=f"1..{len(ids)}"), [crops[i] for i in ids], model=model,
                          tag="rooms-croplabel", think=False)
            js = llm.parse_json(res.get("text", "")) or {}
            out = {}
            for n, i in enumerate(ids, 1):
                v = js.get(str(n)) if isinstance(js, dict) else None
                if isinstance(v, str) and v.strip() and "?" not in v:
                    out[str(i)] = v.strip()
            return res.get("cost_usd", 0.0), out

        got = {}
        with cf.ThreadPoolExecutor(min(6, len(batches))) as ex:
            for c_, out in ex.map(run, batches):
                cost += c_
                got.update(out)
        try:
            json.dump(got, open(cache, "w"))
        except OSError:
            pass
    for i, r in enumerate(todo):
        if got.get(str(i)):
            r["label"] = got[str(i)]
            r["label_source"] = "vision"
        elif overwrite and r["label"]:
            r["label_ocr"], r["label"] = r["label"], ""
    return cost


def detect(meta) -> float:
    s = sheets.kw_score(meta, "arch")
    if meta.get("kind") in ("slab", "piping"):
        s = min(s, 0.3)
    return s


def intent(q: str) -> str | None:
    ql = q.lower()
    if re.search(r"baseboard|skirting|base board|jalkalista|sockelleiste|plinth|linear met", ql):
        return "baseboard"
    if re.search(r"\barea|m2|m²|square met|sq\.? ?m|footprint|how big|size of", ql):
        return "area"
    if re.search(r"how many|number of|\bcount\b", ql) and not re.search(r"\b(doors?|windows?|doorways?)\b", ql):
        return "count"
    return None


def _cached(meta) -> dict:
    with _lock:
        if "_rooms_seg" not in meta:
            seg = segment(meta["image"], meta=meta)
            seg["cost_usd"] = 0.0
            meta["_rooms_seg"] = seg
        return meta["_rooms_seg"]


def relabel(seg, image, rooms, budget_s: float = 30.0) -> int:
    """Upscaled crop OCR of the given rooms (largest first) until the time budget is spent; returns how many
    rooms got a new label. Only for raster text (a PDF text layer is already exact)."""
    import time

    x = seg.get("_lab") or {}
    if not x or x.get("vector") or isinstance(image, np.ndarray):
        return 0
    lab, f, W, H = x["lab"], x["f"], x["W"], x["H"]
    sh, sw = lab.shape
    cscale = min(6.0, max(2.0, 240.0 / x["src_ppm"]))
    t0, n = time.time(), 0
    for r in sorted(rooms, key=lambda r: -r["area_m2"]):
        if r.get("_crop_ocr") or time.time() - t0 > budget_s:
            continue
        r["_crop_ocr"] = True
        ws = []
        for w in _crop_words(image, r["bbox"], W, H, scale=cscale):
            cx = (w["bbox"][0] + w["bbox"][2]) / 2 * W * f
            cy = (w["bbox"][1] + w["bbox"][3]) / 2 * H * f
            if int(lab[min(sh - 1, int(cy)), min(sw - 1, int(cx))]) == r["id"]:
                ws.append(w)
        if ws:
            old = r["label"]
            tmp = {r["id"]: r}
            _join_labels(tmp, {r["id"]: ws}, False)
            if r["label"] and r["label"] != old:
                n += 1
            elif not r["label"]:
                r["label"] = old
    return n


def _norm(s):
    s = re.sub(r"\(.*?\)", " ", s.lower())
    return [w[:-1] if w.endswith("s") and w[:-1] in SYN else re.sub(r"(?<=[a-z]{3})s$", "", w)  # "WCs" -> "wc"
            for w in re.findall(r"[a-z0-9]+", s)]


SYN = {"wc": "toilet", "lavatory": "toilet", "restroom": "toilet", "bathroom": "toilet", "classe": "classroom",
       "storage": "store", "storeroom": "store", "corridors": "corridor", "hallway": "corridor",
       # halls: "Multi-Purpose Hall", "Main hall", "Sports hall", "Assembly", "Gymnasium" all answer "the hall"
       "purpose": "hall", "assembly": "hall", "gymnasium": "hall", "gym": "hall", "auditorium": "hall",
       "dining": "hall", "multipurpose": "hall", "bedroom": "bed", "dorm": "dormitory"}
STOP = {"the", "of", "what", "is", "area", "areas", "floor", "room", "in", "on", "a", "an", "all", "total", "sum",
        "how", "much", "many", "metre", "meter", "linear", "baseboard", "skirting", "board", "for", "and", "this",
        "plan", "drawing", "sheet", "level", "square", "m", "m2", "sq", "give", "me", "list", "each", "per", "net",
        "gross", "excluding", "except", "without", "wet", "different", "do", "need", "we", "are", "there",
        "length", "lengths", "find", "calculate", "compute", "approximately", "size", "space", "spaces", "main",
        "metres", "meters", "base", "boards", "skirtings", "inside", "within", "by", "to", "be", "should",
        "rooms", "every", "whole", "building", "overall", "footprint", "much", "big", "large", "required", "needed",
        "does", "doe", "need", "needs", "have", "has", "get", "install", "lay", "fit",
        # finishes asked for a room type ("m2 of tiling for all WCs"): the trade, not a room name
        "tiling", "tile", "tiles", "tiled", "flooring", "carpet", "carpeting", "paint", "painting", "plaster", "screed",
        "vinyl", "covering", "finish", "finishes", "wall", "walls", "ceiling", "ceilings"}


def _close(a, b):
    """Word match tolerant of OCR slips: equal, one letter dropped (4+ letters), or one edit (5+ letters)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1 or a.isdigit() or b.isdigit() or max(len(a), len(b)) < 4:
        return False
    if min(len(a), len(b)) < 5 and len(a) == len(b):  # short words: only a dropped letter ("Hal" for "Hall")
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    return any(b[:i] + b[i + 1:] == a for i in range(len(b)))


def query_words(question):
    stop = STOP | {x for w in STOP for x in _norm(w)}
    qw = [SYN.get(w, w) for w in _norm(question) if w not in stop]
    return [w for w in qw if len(w) > 1 and not re.fullmatch(r"\d+(m|m2)?", w) or re.fullmatch(r"[a-z]?\d{2,4}[a-z]?", w)]


def match_rooms(rooms, question):
    """(rooms whose label matches the question's room words, the words) - [] when the question names no room.
    Words match after synonyms (WC = toilet, Multi-Purpose / Sports / Main hall = hall) and one OCR slip."""
    qw = query_words(question)
    if not qw:
        return [], []
    scored = []
    for r in rooms:
        lw = {SYN.get(w, w) for w in _norm(r["label"])}
        hit = sum(1 for w in qw if any(_close(w, x) for x in lw))
        if hit:
            scored.append((hit, r))
    if not scored:
        return [], qw
    top = max(s for s, _ in scored)
    return [r for s, r in scored if s == top], qw


IDENT_PROMPT = """This is a floor plan with its rooms numbered in red (1..{n}). The printed room names are too small to read
reliably at this resolution. Which numbered room is the "{name}"? Judge from the layout, the furniture and fittings drawn
in each room, the room's size and shape, and the shape / length of the printed name text. Answer only if you are sure.
JSON only: {{"room": <number or null>, "confidence": "high" | "medium" | "low", "why": "<short>"}}"""
IDENT_MODEL = "sonnet"


def identify_room(seg, image, name: str, model: str = IDENT_MODEL):
    """(room, why, cost) for a room whose printed name is unreadable (a ~2000 px screenshot): a VLM picks the numbered
    room that is `name` from the plan's layout, furniture and the shape of the printed text; only a "high" confidence
    pick is taken. A hall-type name must also be the largest compact room. Cached next to the image."""
    import hashlib
    import json
    import os

    import cv2
    from PIL import Image, ImageDraw

    from bp.generic import llm

    x = seg.get("_lab") or {}
    rooms = [r for r in seg["rooms"] if r["area_m2"] >= 4][:60]
    if not x or isinstance(image, np.ndarray) or len(rooms) < 3:
        return None, "", 0.0
    lab, f = x["lab"], x["f"]
    key = hashlib.sha1((name.lower() + model + json.dumps([[round(v) for v in r["bbox"]] for r in rooms]))
                       .encode()).hexdigest()[:12]
    cache = f"{image}.rooms_ident_{key}.json"
    js, cost = None, 0.0
    if os.path.exists(cache):
        try:
            js = json.load(open(cache))
        except (OSError, ValueError):
            js = None
    if js is None:
        Image.MAX_IMAGE_PIXELS = None
        im = Image.open(image).convert("RGB")
        W, H = im.size
        x0, y0 = max(0, min(r["bbox"][0] for r in rooms) - 20), max(0, min(r["bbox"][1] for r in rooms) - 20)
        x1, y1 = min(W, max(r["bbox"][2] for r in rooms) + 20), min(H, max(r["bbox"][3] for r in rooms) + 20)
        c = im.crop((int(x0), int(y0), int(x1), int(y1)))
        s = min(4.0, 1800 / max(c.size))
        c = c.resize((max(1, int(c.width * s)), max(1, int(c.height * s))), Image.LANCZOS)
        d = ImageDraw.Draw(c)
        sh, sw = lab.shape
        for i, r in enumerate(rooms, 1):
            bx0, by0, bx1, by1 = (int(v * f) for v in r["bbox"])
            m = (lab[max(0, by0):min(sh, by1 + 1), max(0, bx0):min(sw, bx1 + 1)] == r["id"]).astype(np.uint8)
            if m.any():  # the most interior point of the room, where a number cannot fall outside it
                dt = cv2.distanceTransform(np.pad(m, 1), cv2.DIST_L2, 3)[1:-1, 1:-1]
                py, px = np.unravel_index(int(np.argmax(dt)), dt.shape)
                cx, cy = (bx0 + px) / f, (by0 + py) / f
            else:
                cx, cy = (r["bbox"][0] + r["bbox"][2]) / 2, (r["bbox"][1] + r["bbox"][3]) / 2
            tx, ty = (cx - x0) * s, (cy - y0) * s
            d.rectangle([tx - 13, ty - 12, tx + 13, ty + 12], fill=(255, 255, 255))
            d.text((tx - 11, ty - 11), str(i), fill=(230, 0, 0), font_size=20)
        res = llm.ask(IDENT_PROMPT.format(n=len(rooms), name=name), [c], model=model, tag="rooms-identify")
        cost = res.get("cost_usd", 0.0)
        js = llm.parse_json(res.get("text", "")) or {}
        if not isinstance(js, dict):
            js = {}
        try:
            json.dump(js, open(cache, "w"))
        except OSError:
            pass
    k = js.get("room")
    if not (isinstance(k, int) and 1 <= k <= len(rooms)) or str(js.get("confidence", "")).lower() != "high":
        return None, str(js.get("why") or ""), cost
    room = rooms[k - 1]
    if "hall" in {SYN.get(w, w) for w in query_words(name)}:
        # an assembly hall is the sheet's largest compact room (corridors are long and thin)
        def compact(r):
            bw, bh = r["bbox"][2] - r["bbox"][0], r["bbox"][3] - r["bbox"][1]
            return max(bw, bh) <= 2.5 * max(1e-6, min(bw, bh)) and \
                r["area_m2"] * seg["px_per_m"] ** 2 >= 0.6 * bw * bh
        comp = sorted((r for r in rooms if compact(r)), key=lambda r: -r["area_m2"])
        if not comp or comp[0] is not room or (len(comp) > 1 and comp[1]["area_m2"] > 0.75 * room["area_m2"]):
            return None, "the pick is not clearly the largest hall-like room", cost
        room["identified_verified"] = "the largest compact room on the plan"
    return room, str(js.get("why") or ""), cost


def named_rooms(meta, name: str):
    """(rooms whose label matches `name`, seg) for other modules (doors into a named room): the same reading as a room
    area question, incl. the per-room vision crops on coarse sheets; ([], seg) when no room matches."""
    seg = _cached(meta)
    rooms = seg["rooms"]
    if not rooms or not query_words(name):
        return [], seg
    coarse = seg.get("px_per_m", 100) < COARSE_PPM or (seg.get("wall_px") or 0) < 3 or seg.get("scan", False)
    if coarse:
        with _lock:
            lk = seg.setdefault("_crop_lock", threading.Lock())
        with lk:
            if not seg.get("_crop_read"):
                try:
                    seg["cost_usd"] = seg.get("cost_usd", 0.0) + crop_labels(seg, meta["image"], rooms)
                except Exception:  # noqa: BLE001
                    import logging

                    logging.getLogger(__name__).exception("room crop labels failed")
                seg["_crop_read"] = True
    sel, qw = match_rooms(rooms, name)
    if sel and seg.get("_crop_read") and len(qw) >= 2:
        lw = lambda r: {SYN.get(w, w) for w in _norm(r["label"])}  # noqa: E731
        sel = [r for r in sel if all(any(_close(w, x) for x in lw(r)) for w in set(qw))]
    if not sel and not seg.get("_crop_read"):
        cand = [r for r in rooms if r["area_m2"] >= 1.5]
        if relabel(seg, meta["image"], cand, budget_s=30.0):
            sel, qw = match_rooms(rooms, name)
    if not sel and coarse:
        sel = _identified(meta, seg, name)
    return sel, seg


def symbol_confirmed(meta, seg, openings_list):
    """The doorway bands (room["doors"] items, image px) that a drawn door symbol (bp/sheets/openings.py: swings or the
    detector's boxes) touches. For very coarse sheets (walls < 3 px), where window gaps whose glazing lines blurred
    away read as doorways; None when no door symbols are available."""
    try:
        from bp.sheets import openings

        o = openings.analyse_meta(meta)
    except Exception:  # noqa: BLE001
        return None
    boxes = o["doors"] if o.get("cv_ok", not o.get("low_res")) else ((o.get("yolo") or {}).get("doors") or [])
    if not boxes:
        return None
    W, H = meta.get("w") or seg["_lab"]["W"], meta.get("h") or seg["_lab"]["H"]
    g = 0.25 * seg["px_per_m"]
    bx = [[b["bbox"][0] * W - g, b["bbox"][1] * H - g, b["bbox"][2] * W + g, b["bbox"][3] * H + g] for b in boxes]
    return [d for d in openings_list
            if any(d["bbox"][0] <= b[2] and b[0] <= d["bbox"][2] and d["bbox"][1] <= b[3] and b[1] <= d["bbox"][3]
                   for b in bx)]


def room_phrase(question: str) -> str:
    """The room named in a question ("What is the floor area of the Multi-Purpose Hall?" -> "Multi-Purpose Hall")."""
    rx = re.compile(r"(?:the\s+)?([A-Za-z][\w\-' ()]{2,60}?)(?=\s+(?:need|needs|have|has|require|requires|get)\b|"
                    r"\s*[?.]|$)")
    best = None
    for p in re.finditer(r"\b(?:of|in|for|into|does|do)\s+", question):
        m = rx.match(question, p.end())
        if m:
            best = m.group(1).strip()
    return best or question


def _identified(meta, seg, name):
    """[room] picked by identify_room (names unreadable), marked on the room; [] when not confident."""
    try:
        room, why, cost = identify_room(seg, meta["image"], name)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("room identification failed")
        return []
    seg["cost_usd"] = seg.get("cost_usd", 0.0) + cost
    if room is None:
        return []
    room.setdefault("label", "")
    room["identified_as"] = name
    room["identified_why"] = why
    return [room]


def _name(r):
    if r["label"]:
        return r["label"]
    return f"{r['identified_as']} (identified by layout)" if r.get("identified_as") else "unlabelled"


def _ev_poly(r, W, H, label, value):
    return {"kind": "polygon", "page": 0, "points": [[round(x / W, 5), round(y / H, 5)] for x, y in r["polygon"]],
            "label": label, "value": value, "unit": "m²"}


ALL_RX = r"\b(different|each|every|all|total|whole|overall|building|footprint|gross|rooms|list|per room|sum)\b"


def answer(path, question, meta):
    it = intent(question)
    if it is None or not meta.get("image"):
        return None
    seg = _cached(meta)
    rooms = seg["rooms"]
    if not rooms:
        return None
    W, H = meta.get("w"), meta.get("h")
    if not W:
        H, W = _gray(meta["image"]).shape
    if seg.get("fill_gray", 255) < min(235.0, seg.get("paper_gray", 255.0) - 20):
        return None  # rooms are shaded (a colour-coded space diagram): areas belong to the colour-zone path
    big = [r for r in rooms if r["area_m2"] >= 4]
    if seg.get("px_per_m", 0) >= 40 and len(big) >= 10 and sum(1 for r in big if r["label"]) < 0.1 * len(big):
        # readable resolution yet almost no room carries a name: not a solid-wall plan with room labels (e.g. a
        # colour-coded space diagram with outlined walls and furniture); let the table / colour-zone paths answer
        return None
    sc = seg["scale"]
    wpx = seg.get("wall_px") or 0
    cf = 1.0 if wpx >= 3 else 0.75 if wpx >= 2 else 0.5  # thin walls: openings and faces are less certain
    if "drawn" not in sc.get("how", "") and "printed" not in sc.get("how", ""):
        cf *= 0.9
    vector = bool((seg.get("_lab") or {}).get("vector"))
    small_text = not vector and seg.get("px_per_m", 100) < 40
    low_res = None
    if wpx < 3 or small_text:
        low_res = (f"walls ~{wpx:.1f} px thick" if wpx < 3 else "") + \
            ("; " if wpx < 3 and small_text else "") + ("room names too small to read reliably" if small_text else "")
    scale_txt = f"scale {sc['px_per_m']:.1f} px/m ({sc['how']}{'; ' + sc['check'] if sc.get('check') else ''})"
    ql = question.lower()
    # coarse sheets (screenshots, 2500 px renders, scans): walls of 1-3 px and blurred door swings make single
    # rooms merge or split (the hall read 13 / 47 / 288 m² for 245), and names are unreadable. Whole-building
    # totals and the footprint hold up; named rooms and wet-room exclusions are left to other paths.
    coarse = seg.get("px_per_m", 100) < COARSE_PPM or wpx < 3 or seg.get("scan", False)
    if it == "count" and not coarse:
        return None  # a crisp sheet's room names are counted by the arch module from the page text
    if seg.get("scan"):
        low_res = (low_res + "; " if low_res else "") + "scanned sheet"
    if coarse:
        cf *= 0.6
        if query_words(question) or re.search(r"exclud|except|without|wet|dry rooms?", ql):
            # a named room (or a split by room type) on a coarse sheet: OCR garbles the names here, so every room is
            # read off its own cut-out crop by a VLM (one batch for the sheet, cached); faint glazing / hatch lines
            # close rooms as on a crisp sheet, so the outline holds within a few % (hall 246 / 241 m² for 245)
            with _lock:
                lk = seg.setdefault("_crop_lock", threading.Lock())
            with lk:  # questions asked at once wait for the one reading
                if not seg.get("_crop_read"):
                    try:
                        seg["cost_usd"] = seg.get("cost_usd", 0.0) + crop_labels(seg, meta["image"], rooms)
                    except Exception:  # noqa: BLE001
                        import logging

                        logging.getLogger(__name__).exception("room crop labels failed")
                    seg["_crop_read"] = True
            if not any(r.get("label_source") == "vision" for r in rooms):
                return None
            cf = cf / 0.6 * 0.8
            low_res = (low_res + "; " if low_res else "") + "room names read from per-room crops by a vision model"
    sel, qw = match_rooms(rooms, question)
    if sel and seg.get("_crop_read") and len(qw) >= 2:
        # names read off coarse crops: a half match ("Hall" for "Multi-Purpose Hall" when the hall's own name was
        # unreadable, a "Dining Room" via the hall synonym) is not trusted; the room list is offered instead
        lw = lambda r: {SYN.get(w, w) for w in _norm(r["label"])}  # noqa: E731
        sel = [r for r in sel if all(any(_close(w, x) for x in lw(r)) for w in set(qw))]
    raw = re.findall(r"[a-z0-9]+", re.sub(r"\(.*?\)", " ", ql))
    plural = {SYN.get(n, n) for t, n in zip(raw, _norm(question)) if t.endswith("s") and n != t}
    if sel and qw and not seg.get("_crop_read") and not seg.get("_relabel_all") and \
            (plural & set(qw) or re.search(r"\b(all|every|each)\b", ql)):
        # a room type asked for in the plural ("all WCs"): rooms whose small name the page OCR missed would be left
        # out of the sum, so the unlabelled ones are read off their own crops first (budgeted)
        seg["_relabel_all"] = True
        cand = [r for r in rooms if not r["label"] and r["area_m2"] >= 1.0]
        if cand and relabel(seg, meta["image"], cand, budget_s=25.0):
            sel, qw = match_rooms(rooms, question)
    if qw and not sel and not seg.get("_crop_read"):
        # the question names a room we have no label for: read the unlabelled / larger rooms' own crops (budgeted)
        cand = [r for r in rooms if r["area_m2"] >= 1.5]
        if relabel(seg, meta["image"], cand, budget_s=30.0):
            sel, qw = match_rooms(rooms, question)
        if not sel and sum(1 for r in cand if not r["label"]) > 0.4 * max(1, len(cand)):
            try:
                seg["cost_usd"] = seg.get("cost_usd", 0.0) + vision_labels(meta["image"], rooms)
            except Exception:  # noqa: BLE001
                pass
            sel, qw = match_rooms(rooms, question)
    if not sel and qw and coarse and seg.get("_crop_read") and it != "count" and not re.search(ALL_RX, ql):
        # names unreadable even on the per-room crops (a ~2000 px screenshot): a confident pick by layout / furniture
        sel = _identified(meta, seg, room_phrase(question))
        if sel:
            cf *= 0.9 if sel[0].get("identified_verified") else 0.8  # a hall pick is checked against the shapes
            low_res = (low_res + "; " if low_res else "") + \
                f"the room was identified by its layout and furnishing, not its (unreadable) name: {sel[0]['identified_why']}"
    if it == "count":
        # rooms of a type counted by their names: only on coarse sheets (scans, small rasters) where the names were read
        # off per-room crops; a crisp sheet's own labels are counted by the arch module from the page text
        if not (coarse and seg.get("_crop_read") and sel and qw):
            return None
        big = [r for r in rooms if r["area_m2"] >= 4]
        if sum(1 for r in big if r.get("label_source") == "vision") < 0.6 * len(big):
            return None  # most names unreadable even on the crops (a ~2000 px screenshot): a count would be short
        lw = lambda r: {SYN.get(w, w) for w in _norm(r["label"])}  # noqa: E731
        sel = [r for r in sel if r.get("label_source") == "vision" and
               all(any(_close(w, x) for x in lw(r)) for w in set(qw))]
        if len(sel) >= 3:  # one type of room has one size and shape: a long corridor crop misread as one is dropped
            asp = [max(r["bbox"][2] - r["bbox"][0], r["bbox"][3] - r["bbox"][1]) /
                   max(1e-6, min(r["bbox"][2] - r["bbox"][0], r["bbox"][3] - r["bbox"][1])) for r in sel]
            ma, mm = float(np.median(asp)), float(np.median([r["area_m2"] for r in sel]))
            sel = [r for r, a in zip(sel, asp) if a <= max(2.5, 2 * ma) and 0.4 * mm <= r["area_m2"] <= 2.5 * mm]
        if not sel:
            return None
        names = sorted({r["label"] for r in sel})
        ev = [_ev_poly(r, W, H, f"{r['label']} {i}", 1) for i, r in enumerate(sel, 1)]
        for e in ev:
            e.pop("unit", None)
        return {"answer": len(sel), "confidence": round(0.75 * cf, 2), "method": "sheets-rooms-count",
                "cost_usd": seg.get("cost_usd", 0.0), "evidence": ev, "low_res": low_res,
                "explanation": f"{len(sel)} rooms named {' / '.join(names)}: each enclosed room's name was read off its "
                               f"own cut-out crop by a vision model (the page text is too coarse here); every counted "
                               f"room is outlined and numbered."}
    named = bool(sel)
    if any(r.get("label_source") == "vision" for r in sel):
        # names read by a VLM off an unreadable raster may be wrong (one crop per room is the surer read)
        cf *= 0.85 if seg.get("_crop_read") else 0.6
    base = {"unit": "m²" if it == "area" else "m", "cost_usd": seg.get("cost_usd", 0.0), "scale": sc.get("how", "")}
    if low_res:
        base["low_res"] = low_res
    if not named:
        if qw and not re.search(ALL_RX, ql):
            names = sorted({r["label"] for r in rooms if r["label"]}, key=lambda t: t.lower())
            return {**base, "answer": None, "confidence": 0.0, "method": "sheets-rooms-ask",
                    "evidence": [],
                    "explanation": f"I found no room named '{' '.join(qw)}' on this sheet. Rooms I can read: "
                                   f"{', '.join(names[:40]) or 'none'}. Which one do you mean, or should I total "
                                   f"all rooms?"}
        sel = list(rooms)
    excl = re.search(r"exclud|except|without|not .*wet|dry rooms?", ql) is not None
    if excl and re.search(r"wet|toilet|wc|bath|shower|kitchen", ql):
        sel = [r for r in sel if not re.search(WET, r["label"].lower())]
    ev_scale = [{"kind": "box", "page": 0, "bbox": b, "label": "scale bar", "value": None} for b in sc.get("boxes", [])]
    unl = sum(1 for r in sel if not r["label"])
    if it == "area":
        if re.search(r"footprint|gross|building area|overall|whole building", ql) and not named:
            ev = [{"kind": "polygon", "page": 0, "points": [[x / W, y / H] for x, y in p], "label": "footprint",
                   "value": None} for p in seg["footprint_polys"]]
            net = sum(r["area_m2"] for r in rooms)
            return {**base, "answer": seg["footprint_m2"], "confidence": round(0.6 * cf, 2),
                    "method": "sheets-rooms-footprint", "evidence": ev + ev_scale,
                    "explanation": f"Gross footprint to the outside face of the outer walls = {seg['footprint_m2']} m² "
                                   f"(net room areas sum to {net:.1f} m² over {len(rooms)} rooms); {scale_txt}."}
        tot = sum(r["area_m2"] for r in sel)
        ev = [_ev_poly(r, W, H, f"{_name(r)} {r['area_m2']:.1f} m²", r["area_m2"]) for r in sel]
        if named and len(sel) == 1:
            r = sel[0]
            return {**base, "answer": r["area_m2"], "confidence": round(0.7 * cf, 2),
                    "method": "sheets-rooms-area", "evidence": ev + ev_scale,
                    "explanation": f"{_name(r)}: {round(r['area_m2'] * sc['px_per_m'] ** 2):.0f} px² / "
                                   f"({sc['px_per_m']:.1f} px/m)² = {r['area_m2']:.1f} m² (net, to wall faces); "
                                   f"{scale_txt}."}
        groups: dict[str, list] = {}
        for r in sel:
            groups.setdefault(r["label"] or "unlabelled", []).append(r["area_m2"])
        un = groups.pop("unlabelled", [])
        parts = [f"{k} {sum(v):.1f} m²"
                 + (f" ({len(v)} rooms: " + " + ".join(f"{x:.1f}" for x in v) + ")" if len(v) > 1 else "")
                 for k, v in sorted(groups.items(), key=lambda kv: -sum(kv[1]))]
        if un:
            parts.append(f"{len(un)} unlabelled spaces {sum(un):.1f} m²")
        if named:
            txt = f"{len(sel)} rooms: " + " + ".join(f"{r['area_m2']:.1f}" for r in sel) + f" = {tot:.1f} m²"
            return {**base, "answer": round(tot, 1), "confidence": round(0.6 * cf, 2),
                    "method": "sheets-rooms-area-sum", "evidence": ev + ev_scale,
                    "explanation": f"{' / '.join(sorted(groups))}: {txt}; {scale_txt}."}
        if coarse:
            return {**base, "answer": round(tot, 1), "confidence": round(0.55 * cf, 2),
                    "method": "sheets-rooms-area-total", "evidence": ev + ev_scale,
                    "explanation": f"{len(sel)} enclosed spaces sum to {tot:.0f} m² net (gross footprint "
                                   f"{seg['footprint_m2']} m²); room names are not readable at this resolution, so "
                                   f"no per-room split; {scale_txt}."}
        listing = "; ".join(parts[:40])
        return {**base, "answer": f"Total {tot:.0f} m² net over {len(sel)} rooms. " + listing, "value": round(tot, 1),
                "confidence": round(0.55 * cf, 2), "method": "sheets-rooms-area-list", "evidence": ev + ev_scale,
                "explanation": f"Each room = its enclosed pixels / ({sc['px_per_m']:.1f} px/m)²; gross footprint "
                               f"{seg['footprint_m2']} m²; {unl} rooms carry no readable label; {scale_txt}."}
    # baseboard: evidence values add up to the answer (outlines + minus each door opening once per room side)
    if wpx < 3 and named:
        # walls 1-2 px: window gaps whose glazing blurred away read as doorways; only gaps with a door symbol count
        for r in sel:
            if "doors_all" not in r:
                ok = symbol_confirmed(meta, seg, r["doors"])
                if ok is not None:
                    r["doors_all"], r["doors"] = r["doors"], ok
                    r["baseboard_m"] = round(max(0.0, r["perimeter_m"] - sum(d["width_m"] for d in ok)), 2)
    nd = sum(len(r["doors"]) for r in sel)
    dw = sum(d["width_m"] for r in sel for d in r["doors"])
    per = sum(r["perimeter_m"] for r in sel)
    tot = per - dw
    ev = []
    for r in sel:
        pts = [[round(x / W, 5), round(y / H, 5)] for x, y in r["polygon"]]
        ev.append({"kind": "polyline", "page": 0, "points": pts + pts[:1], "closed": True, "unit": "m",
                   "label": f"{_name(r)}: outline {r['perimeter_m']:.1f} m − doors "
                            f"{sum(d['width_m'] for d in r['doors']):.1f} m = {r['baseboard_m']:.1f} m",
                   "value": r["perimeter_m"]})
    sides: dict = {}
    for r in sel:
        for d in r["doors"]:
            k = tuple(round(v) for v in d["bbox"])
            sides.setdefault(k, [d, 0])[1] += 1
    for d, n in sides.values():
        ev.append({"kind": "box", "page": 0, "unit": "m",
                   "bbox": [d["bbox"][0] / W, d["bbox"][1] / H, d["bbox"][2] / W, d["bbox"][3] / H],
                   "label": f"door opening {d['width_m']:.2f} m" + (f" × {n} sides" if n > 1 else ""),
                   "value": round(-d["width_m"] * n, 2)})
    what = (" / ".join(sorted({_name(r) for r in sel})) if named else f"all {len(sel)} rooms") + \
        (" (wet rooms excluded)" if excl else "")
    return {**base, "answer": round(tot, 1), "confidence": round((0.6 if named else 0.55) * cf, 2),
            "method": "sheets-rooms-baseboard", "evidence": ev + ev_scale,
            "explanation": f"{what}: room outlines {per:.1f} m − {nd} door openings {dw:.1f} m = {tot:.1f} m of "
                           f"baseboard (windows not deducted, door openings measured on the wall line); {scale_txt}."}
