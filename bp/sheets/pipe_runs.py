"""Pipe run lengths on piping plans ("How many metres of 8-inch pipe?", "Total length of the 16" suction header",
"Linear feet of pipe by size").

Plain geometry, no model call of its own:

  1. scale: the printed scale (SCALE: 1/4" = 1'-0", 1" = 20', 1:50) x the raster's dpi (known for a PDF render,
     else from the sheet size the aspect ratio matches), checked against the graphic scale bar (0 2' 4' 8' labels
     in a row: px per foot is the slope of label x over label value) and against the pipes themselves (the gap
     between the two walls of a double-line pipe is the pipe's outside diameter, which only takes standard values).
  2. linework: the ink of the page (a vector PDF page: its line drawings rendered without the text; a raster: the
     image thresholded), long horizontal / vertical strokes kept by a morphological opening (drops the lettering).
  3. pipes: two parallel strokes whose spacing is a standard outside diameter at this scale (16" = 16.0 in,
     12" = 12.75 in, 8" = 8.625 in ...) with nothing in between them that stops there; the size comes from the
     spacing. Each stroke is the wall of one pipe only (greedy, pipes with joint / fitting ticks running wall to
     wall first, so the gap between two neighbouring pipes is not taken for a third). Pieces of the same size on
     one centreline are bridged across valves / flanges, and run ends are carried to the centreline of the pipe
     they tee into or turn into, so lengths are centreline lengths, fittings included.
  4. labels (when the shared text read of piping.py is available): size labels (8", 16" SUCTION HEADER) are
     matched to the nearest traced pipe as a cross-check, and a named run ("suction header") is found by its label.

Limits, stated in every answer: single-line small bore (2" and under, drawn as one line) is not separated from
other linework and is not measured; risers / drops (vertical pipe) have no plan length; pipe hidden under
equipment or drawn dashed (below grade, in trench) is measured only where both walls are drawn; diagonal runs
are not traced (plans are almost always orthogonal).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

METHOD = "sheets-piping-runs"
CACHE = Path(os.environ.get("BP_PIPE_RUNS_CACHE", "cache/sheets/pipe_runs"))
FT_M = 0.3048

# nominal pipe size (in) -> outside diameter (in), ASME B36.10 / B36.19
OD = {3: 3.5, 4: 4.5, 5: 5.563, 6: 6.625, 8: 8.625, 10: 10.75, 12: 12.75, 14: 14.0, 16: 16.0, 18: 18.0,
      20: 20.0, 24: 24.0, 30: 30.0, 36: 36.0}
DN = {80: 3, 100: 4, 125: 5, 150: 6, 200: 8, 250: 10, 300: 12, 350: 14, 400: 16, 450: 18, 500: 20, 600: 24,
      750: 30, 900: 36}  # metric nominal size (mm) -> NPS
NPS_DN = {v: k for k, v in DN.items()}
SMALL_OD = {0.5: 0.84, 0.75: 1.05, 1: 1.315, 1.25: 1.66, 1.5: 1.9, 2: 2.375, 2.5: 2.875}
TOL = 0.07  # relative tolerance of a measured wall spacing against a standard OD
MIN_PX = 6  # wall spacings below this many px are not trusted as double-line pipe (text, hatching)

# sheet sizes (in) a raster's aspect ratio is matched against, to get its dpi
SHEETS = [(34, 22), (36, 24), (44, 34), (48, 36), (42, 30), (30, 42), (24, 18), (17, 11), (11, 8.5),
          (46.81, 33.11), (33.11, 23.39), (23.39, 16.54), (16.54, 11.69), (11.69, 8.27)]


# ------------------------------------------------------------------------------------------------ scale
def parse_scale(text: str) -> dict | None:
    """Printed drawing scale -> {"paper_in_per_ft": ..} (imperial) or {"ratio": N} (metric 1:N); None if absent."""
    t = (text or "").replace("′", "'").replace("″", '"').replace("''", '"')
    m = re.search(r"(\d+(?:\s*-\s*|\s+)?\d*/?\d*)\s*\"\s*=\s*(\d+)\s*'\s*-?\s*(\d+)?\s*\"?", t)
    if m:
        a = m.group(1).replace(" ", "").replace("-", " ").strip()
        try:
            if " " in a:  # 1-1/2" (mixed number)
                w, f = a.split()
                n, d = f.split("/")
                val = float(w) + float(n) / float(d)
            elif "/" in a:
                n, d = a.split("/")
                val = float(n) / float(d)
            else:
                val = float(a)
            ft = float(m.group(2)) + float(m.group(3) or 0) / 12
            if val > 0 and ft > 0:
                return {"paper_in_per_ft": val / ft, "text": m.group(0).strip()}
        except (ValueError, ZeroDivisionError):
            pass
    m = re.search(r"\b1\s*:\s*(\d{1,4})\b", t)
    if m and int(m.group(1)) >= 5:
        return {"ratio": int(m.group(1)), "text": m.group(0)}
    return None


def dpi_of(w: int, h: int) -> float | None:
    """dpi of a full-sheet raster, from the standard sheet size its aspect ratio matches (None if none does)."""
    W, H = max(w, h), min(w, h)
    best = None
    for a, b in SHEETS:
        A, B = max(a, b), min(a, b)
        err = abs(W / H - A / B) / (A / B)
        if err < 0.012 and (best is None or err < best[0]):
            best = (err, W / A)
    return best[1] if best else None


def px_per_ft_from(scale: dict, dpi: float) -> float | None:
    if not scale or not dpi:
        return None
    if "paper_in_per_ft" in scale:
        return dpi * scale["paper_in_per_ft"]
    if "ratio" in scale:
        return dpi * 12.0 / scale["ratio"]
    return None


def scale_bar(items: list[dict], W: int, H: int, metric: bool = False) -> dict | None:
    """Graphic scale bar from positioned text: >= 3 labels like 0 / 2' / 4' / 8' (or 0 500 1000 2000 mm) on one row,
    x increasing with value. -> {"px_per_ft", "labels": [...], "bbox"} (px per unit = least-squares slope of label
    centre x on value; unit: as printed, else mm for values >= 100, else m on a metric sheet, else feet)."""
    cand = []
    for it in items or []:
        t = it.get("text", "").strip().replace("′", "'")
        m = re.fullmatch(r"(\d{1,4})\s*('|FT|FEET|MM|M)?", t, re.I)
        if not m:
            continue
        unit = (m.group(2) or "").upper()
        b = it["bbox"]
        if max(b) <= 1.5:
            b = [b[0] * W, b[1] * H, b[2] * W, b[3] * H]
        cand.append({"v": int(m.group(1)), "unit": unit, "x": (b[0] + b[2]) / 2, "y": (b[1] + b[3]) / 2,
                     "h": b[3] - b[1], "bbox": b})
    best = None
    for c in cand:
        if c["v"] != 0:
            continue
        row = [d for d in cand if abs(d["y"] - c["y"]) < max(c["h"], 8) and d["x"] >= c["x"] - 2]
        row = sorted({d["v"]: d for d in row}.values(), key=lambda d: d["x"])
        vals = [d["v"] for d in row]
        units = {d["unit"] for d in row} - {""}
        if len(row) < 3 or vals != sorted(vals) or len(units) > 1:
            continue
        u = units.pop() if units else ("MM" if max(vals) >= 100 else "M" if metric else "'")
        per_ft = {"'": 1.0, "FT": 1.0, "FEET": 1.0, "M": FT_M, "MM": FT_M * 1000}[u]
        xs = np.array([d["x"] for d in row])
        vs = np.array([d["v"] for d in row], float)
        k, c0 = np.polyfit(vs, xs, 1)
        resid = float(np.max(np.abs(xs - (k * vs + c0))))
        if k <= 0 or resid > 0.08 * k * vs.max():
            continue
        if best is None or len(row) > len(best["labels"]):
            sym = {"'": "'", "FT": "'", "FEET": "'", "M": " m", "MM": " mm"}[u]
            best = {"px_per_ft": float(k) * per_ft, "labels": [f"{d['v']}{sym}" for d in row],
                    "resid_px": round(resid, 1),
                    "bbox": [min(d["bbox"][0] for d in row), min(d["bbox"][1] for d in row),
                             max(d["bbox"][2] for d in row), max(d["bbox"][3] for d in row)]}
    return best


# ------------------------------------------------------------------------------------------------ linework
def _load_gray(image):
    import cv2

    if isinstance(image, np.ndarray):
        return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(str(image)) as im:
        return np.asarray(im.convert("L"))


def vector_mask(pdf: str, page: int, zoom: float) -> np.ndarray | None:
    """Ink of a vector PDF page's line drawings only (no text), rendered at `zoom` px per pt in the displayed
    (rotated) orientation. None when the page has (almost) no vector linework."""
    import cv2
    import pymupdf

    pg = pymupdf.open(pdf)[page]
    drs = pg.get_drawings()
    if sum(len(d["items"]) for d in drs) < 200:
        return None
    m = pg.rotation_matrix
    W, H = int(round(pg.rect.width * zoom)), int(round(pg.rect.height * zoom))
    mask = np.zeros((H, W), np.uint8)

    def P(p):
        q = pymupdf.Point(p) * m
        return (int(round(q.x * zoom)), int(round(q.y * zoom)))

    for d in drs:
        if d.get("type") == "f":  # fills only (arrowheads, dots, hatching): not walls
            continue
        col = d.get("color") or (0, 0, 0)
        if sum(col[:3]) / 3 > 0.5:  # screened (grey) linework: building background, existing work
            continue
        for it in d["items"]:
            if it[0] == "l":
                cv2.line(mask, P(it[1]), P(it[2]), 1, 1)
            elif it[0] == "re":
                r = it[1]
                pts = [P((r.x0, r.y0)), P((r.x1, r.y0)), P((r.x1, r.y1)), P((r.x0, r.y1))]
                cv2.polylines(mask, [np.array(pts, np.int32)], True, 1, 1)
            elif it[0] == "qu":
                q = it[1]
                pts = [P(q.ul), P(q.ur), P(q.lr), P(q.ll)]
                cv2.polylines(mask, [np.array(pts, np.int32)], True, 1, 1)
            elif it[0] == "c":
                cv2.line(mask, P(it[1]), P(it[4]), 1, 1)
    return mask


def drawing_area(mask: np.ndarray) -> np.ndarray:
    """1 inside the drawing, 0 over the title block: a full-height rule in the right 30 % of the sheet (or a
    full-width rule in the bottom 25 %) cuts off what lies beyond it."""
    H, W = mask.shape
    area = np.ones((H, W), np.uint8)
    v = strokes(mask, "v", int(0.6 * H), gap=20)
    xs = [r[0] for r in v if r[0] > 0.7 * W and r[0] < W - 0.02 * W]
    if xs:
        area[:, int(min(xs)) - 3:] = 0
    h = strokes(mask, "h", int(0.6 * W), gap=20)
    ys = [r[0] for r in h if r[0] > 0.75 * H and r[0] < H - 0.02 * H]
    if ys:
        area[int(min(ys)) - 3:, :] = 0
    return area


def ink_mask(gray: np.ndarray, thr: int = 160) -> np.ndarray:
    return (gray < thr).astype(np.uint8)


def strokes(mask: np.ndarray, axis: str, minlen: int = 40, gap: int = 30) -> np.ndarray:
    """Long straight strokes along `axis` ('h' or 'v'): array of [c, a0, a1, thick] (c = centre row for 'h' /
    column for 'v', a0..a1 = extent along the stroke, inclusive). Adjacent rows of one stroke are merged."""
    import cv2

    m = mask if axis == "h" else mask.T
    o = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (minlen, 1)))
    d = np.diff(np.pad(o, ((0, 0), (1, 1))).astype(np.int8), axis=1)
    ys, xs = np.nonzero(d)
    vals = d[ys, xs]
    starts = xs[vals == 1]
    ends = xs[vals == -1] - 1
    rows = ys[vals == 1]
    order = np.lexsort((starts, rows))
    rows, starts, ends = rows[order], starts[order], ends[order]
    out = []  # [row_sum, n, a0, a1, last_row]
    open_ = []
    for r, s, e in zip(rows.tolist(), starts.tolist(), ends.tolist()):
        hit = None
        for o_ in open_:
            if o_[4] == r - 1 and min(e, o_[3]) - max(s, o_[2]) > 0.5 * min(e - s, o_[3] - o_[2]):
                hit = o_
                break
        if hit is not None and hit[1] < 4:
            hit[0] += r
            hit[1] += 1
            hit[2] = min(hit[2], s)
            hit[3] = max(hit[3], e)
            hit[4] = r
        else:
            o_ = [r, 1, s, e, r]
            out.append(o_)
            open_.append(o_)
        open_ = [o_ for o_ in open_ if o_[4] >= r - 1]
    if not out:
        return np.zeros((0, 4))
    a = np.array([[o_[0] / o_[1], o_[2], o_[3], o_[1]] for o_ in out], float)
    return _bridge(a[np.argsort(a[:, 0])], gap)


def _bridge(a: np.ndarray, gap: int) -> np.ndarray:
    """Join strokes on one line (within 1.5 px) whose ends are at most `gap` px apart (a stroke broken where
    another line crosses it, or a dashed line with short gaps)."""
    if not len(a) or gap <= 0:
        return a
    order = np.lexsort((a[:, 1], np.round(a[:, 0] / 1.5)))
    out = []
    for r in a[order]:
        for o in out[-6:]:
            if abs(o[0] - r[0]) <= 1.5 and r[1] - o[2] <= gap and r[2] > o[1] - gap:
                o[1], o[2] = min(o[1], r[1]), max(o[2], r[2])
                break
        else:
            out.append(r.copy())
    out = np.array(out)
    return out[np.argsort(out[:, 0])]


# ------------------------------------------------------------------------------------------------ pipes
def size_for(width_px: float, ppf: float, small: bool = False) -> tuple[float | None, float]:
    """(nominal size in, relative error) of a wall spacing; None when it is not a standard outside diameter."""
    inch = width_px / ppf * 12.0
    best = (None, 9.0)
    table = dict(OD, **SMALL_OD) if small else OD
    for nps, od in table.items():
        e = abs(inch - od) / od  # drawn at the outside diameter (what CAD pipe libraries do)
        if e < best[1]:
            best = (nps, e)
    tol = max(TOL, 1.6 / max(width_px, 1.0))  # +-1.6 px of line placement on a low-resolution raster
    return best if best[1] <= tol else (None, best[1])


def _sub(iv: list, a: float, b: float) -> list:
    """intervals `iv` minus [a, b]"""
    out = []
    for x0, x1 in iv:
        if b <= x0 or a >= x1:
            out.append((x0, x1))
            continue
        if a > x0:
            out.append((x0, a))
        if b < x1:
            out.append((b, x1))
    return out


def _joints(mask_ax: np.ndarray, ca: float, cb: float, a0: float, a1: float) -> int:
    """number of ticks running exactly wall to wall between rows ca..cb over a0..a1 (joints, flanges, fitting
    ends), as opposed to lines that only cross the band (a perpendicular pipe or wall passing through)."""
    H, W = mask_ax.shape
    r0, r1 = int(round(ca)) + 2, int(round(cb)) - 1
    x0, x1 = max(0, int(a0)), min(W, int(a1) + 1)
    if r1 <= r0 or x1 - x0 < 3:
        return 0
    band = mask_ax[r0:r1, x0:x1]
    full = band.mean(axis=0) > 0.9
    if not full.any():
        return 0
    w = cb - ca
    far = int(round(0.6 * w))

    def at(r):
        return mask_ax[min(H - 1, max(0, r)), x0:x1] > 0

    o = max(2, min(5, int(round(0.25 * w))))
    up, dn = at(int(round(ca)) - o), at(int(round(cb)) + o)
    upf, dnf = at(int(round(ca)) - far), at(int(round(cb)) + far)
    # a tick that stops at both walls (joint) or sticks out a little on both sides (flange); one that goes on
    # past one wall only is a branch or a bigger pipe's tick, one that goes far past both is a line crossing
    ok = full & ((~up & ~dn) | (up & dn & ~upf & ~dnf))
    # count clusters of adjacent columns
    return int(np.count_nonzero(np.diff(np.concatenate([[0], ok.astype(np.int8)])) == 1))


def pair_pipes(segs: np.ndarray, mask_ax: np.ndarray, ppf: float, minlen: int = 40, sizes=None) -> list[dict]:
    """Double-line pipe pieces along one axis (rows = the stroke direction of `mask_ax`). `sizes`: the nominal
    sizes allowed (e.g. the ones printed on the sheet), None = any standard size."""
    sizes = set(sizes) if sizes else set(OD)
    wmax = max(OD[s] for s in sizes if s in OD) * ppf / 12 * (1 + TOL) if sizes & set(OD) else 0
    wmin = max(MIN_PX, min(OD[s] for s in sizes if s in OD) * ppf / 12 * (1 - TOL) - 1.6)
    n = len(segs)
    cands = []
    for i in range(n):
        ci, i0, i1 = segs[i, 0], segs[i, 1], segs[i, 2]
        j = i + 1
        while j < n and segs[j, 0] - ci <= wmax:
            cj, j0, j1 = segs[j, 0], segs[j, 1], segs[j, 2]
            w = cj - ci
            j += 1
            if w < wmin:
                continue
            a0, a1 = max(i0, j0), min(i1, j1)
            if a1 - a0 < max(minlen, 0.6 * w):
                continue
            nps, err = size_for(w, ppf)
            if nps is None or nps not in sizes:
                continue
            iv = [(a0, a1)]
            # strokes strictly between the walls stop the pipe there, unless they run through (extend past the
            # piece on both sides: a building line or another pipe's wall crossing) or are its centreline
            for k in range(i + 1, j - 1):
                ck, k0, k1 = segs[k, 0], segs[k, 1], segs[k, 2]
                if ck - ci < 2 or cj - ck < 2 or k1 < a0 or k0 > a1:
                    continue
                if abs(ck - (ci + cj) / 2) < 0.1 * w:
                    continue
                if k0 <= a0 + 0.5 * w and k1 >= a1 - 0.5 * w:  # spans the whole piece: a line crossing it
                    continue
                iv = _sub(iv, k0 - 2, k1 + 2)
            for x0, x1 in iv:
                if x1 - x0 >= max(minlen, 0.6 * w):
                    jn = _joints(mask_ax, ci, cj, x0, x1)
                    cands.append({"i": i, "j": j - 1, "c": (ci + cj) / 2, "w": float(w), "a0": float(x0),
                                  "a1": float(x1), "size": nps, "err": err, "joints": jn,
                                  "score": (x1 - x0) * (1 + min(jn, 6)) * (1 - err)})
    # each stroke is the wall of one pipe at any point along it: strongest candidates claim first
    claimed: dict[int, list] = {}
    out = []
    for c in sorted(cands, key=lambda c: (c["joints"] == 0, -c["score"])):
        iv = [(c["a0"], c["a1"])]
        for k in (c["i"], c["j"]):
            for x0, x1 in claimed.get(k, []):
                iv = _sub(iv, x0, x1)
        for x0, x1 in iv:
            if x1 - x0 < max(minlen, 0.6 * c["w"]):
                continue
            d = dict(c, a0=x0, a1=x1)
            out.append(d)
            claimed.setdefault(c["i"], []).append((x0, x1))
            claimed.setdefault(c["j"], []).append((x0, x1))
    return out


def _merge(pieces: list[dict], ppf: float) -> list[dict]:
    """Same size, same centreline (within 15 % of the diameter), gap up to max(3 x OD, 2 ft): one run."""
    runs = []
    for p in sorted(pieces, key=lambda p: (p["size"], p["c"], p["a0"])):
        for r in runs:
            if r["size"] != p["size"] or abs(r["c"] - p["c"]) > 0.15 * r["w"]:
                continue
            gap = max(p["a0"] - r["a1"], r["a0"] - p["a1"])
            if gap <= max(3 * r["w"], 2 * ppf):
                n = r["n"]
                r["c"] = (r["c"] * n + p["c"]) / (n + 1)
                r["a0"], r["a1"] = min(r["a0"], p["a0"]), max(r["a1"], p["a1"])
                r["n"] += 1
                r["joints"] += p["joints"]
                r["pieces"].append((p["a0"], p["a1"]))
                break
        else:
            runs.append(dict(p, n=1, pieces=[(p["a0"], p["a1"])]))
    return runs


def _connect(hruns: list[dict], vruns: list[dict]):
    """Carry run ends to the centreline of a perpendicular run they meet (tees, elbows): centreline lengths."""
    for A, B in ((hruns, vruns), (vruns, hruns)):
        for r in A:
            for end in ("a0", "a1"):
                x = r[end]
                best = None
                for q in B:
                    # q runs along the other axis: q["c"] is its position along r; r["c"] must lie within q's extent
                    if not (q["a0"] - r["w"] <= r["c"] <= q["a1"] + r["w"]):
                        continue
                    d = abs(q["c"] - x)
                    reach = q["w"] / 2 + 0.6 * r["w"] + 4
                    if d <= reach and (best is None or d < best[0]):
                        best = (d, q["c"])
                if best is not None:
                    r[end + "_conn"] = best[1]
    for r in hruns + vruns:
        for end in ("a0", "a1"):
            if end + "_conn" in r:
                r[end] = r.pop(end + "_conn")
        if r["a0"] > r["a1"]:
            r["a0"], r["a1"] = r["a1"], r["a0"]


def trace_runs(image, scale, minlen: int | None = None, mask: np.ndarray | None = None, sizes=None) -> list[dict]:
    """Straight double-line pipe runs on a plan image.

    image: path or greyscale array of the sheet (ignored when `mask` (1 = ink) is given); scale: px per foot of
    that image (float); sizes: nominal sizes to look for (default: every standard size from 3" up).
    -> [{size_in, polyline_px [[x, y], [x, y]], length_px, length_ft, length_m, width_px,
    axis, joints}], longest first."""
    ppf = float(scale)
    # strokes shorter than ~half a foot are lettering; on a 300 dpi 1/4" plan that is 40 px
    minlen = int(minlen or min(40, max(10, round(0.53 * ppf))))
    gap = int(min(30, max(3, round(0.4 * ppf))))
    if mask is None:  # thin lines on a low-resolution raster are grey, not black
        mask = ink_mask(_load_gray(image), 160 if ppf >= 40 else 232)
    mask = mask * drawing_area(mask)
    out = []
    hruns, vruns = [], []
    for axis, m, bucket in (("h", mask, hruns), ("v", mask.T, vruns)):
        segs = strokes(mask, axis, minlen, gap)
        if len(segs):  # the sheet border / title-block rules are not pipe walls
            segs = segs[(segs[:, 2] - segs[:, 1]) < 0.75 * m.shape[1]]
        pieces = pair_pipes(segs, m, ppf, minlen, sizes)
        bucket.extend(_merge(pieces, ppf))
        for r in bucket:
            r["axis"] = axis
    _connect(hruns, vruns)
    allr = hruns + vruns
    jointed = sum(r["a1"] - r["a0"] for r in allr if r["joints"]) / max(1.0, sum(r["a1"] - r["a0"] for r in allr))
    for r in allr:
        L = r["a1"] - r["a0"]
        if L < max(minlen, 1.5 * r["w"]):  # a stub (flange pair, valve body): not a run
            continue
        # where pipes are drawn with joint / fitting ticks (most of the traced length has them), a pair of parallel
        # lines with hardly any (< 1 per 15 ft) is an equipment outline, a symbol or two unrelated lines, not pipe
        if jointed > 0.5 and r["joints"] < L / (15 * ppf):
            continue
        c = r["c"]
        pl = [[r["a0"], c], [r["a1"], c]] if r["axis"] == "h" else [[c, r["a0"]], [c, r["a1"]]]
        ft = L / ppf
        out.append({"size_in": r["size"], "polyline_px": [[round(x, 1), round(y, 1)] for x, y in pl],
                    "length_px": round(L, 1), "length_ft": round(ft, 2), "length_m": round(ft * FT_M, 3),
                    "width_px": round(r["w"], 1), "od_in": round(r["w"] / ppf * 12, 2), "axis": r["axis"],
                    "joints": int(r["joints"]), "pieces": len(r["pieces"])})
    return sorted(out, key=lambda r: -r["length_px"])


def od_check(runs: list[dict]) -> float:
    """Share of traced length whose wall spacing is within 3 % of a standard OD: ~1 when the scale is right."""
    tot = sum(r["length_px"] for r in runs) or 1.0
    good = sum(r["length_px"] for r in runs if abs(r["od_in"] - OD.get(r["size_in"], 0)) / OD.get(r["size_in"], 1)
               <= 0.03 or abs(r["od_in"] - r["size_in"]) / r["size_in"] <= 0.03)
    return good / tot


# ------------------------------------------------------------------------------------------------ text, leaders
def _pdf_lines(pdf: str, page: int, zoom: float) -> list[dict]:
    """Text-layer lines of a PDF page in px of the displayed page at `zoom`."""
    import pymupdf

    pg = pymupdf.open(pdf)[page]
    m = pg.rotation_matrix
    out = []
    for blk in pg.get_text("dict").get("blocks", []):
        for ln in blk.get("lines", []):
            txt = " ".join(s["text"].strip() for s in ln.get("spans", []) if s.get("text", "").strip())
            if not txt:
                continue
            r = pymupdf.Rect(ln["bbox"]) * m
            r.normalize()
            out.append({"text": re.sub(r"\s+", " ", txt), "bbox": [r.x0 * zoom, r.y0 * zoom, r.x1 * zoom, r.y1 * zoom]})
    return out


def _raster_lines(path: str, meta: dict, W: int, H: int) -> tuple[list[dict], float]:
    """Positioned text of a raster sheet from the piping module's shared, cached read (tesseract + Haiku tiles,
    paid once per sheet for every piping question). ([], 0) when it is unavailable."""
    try:
        from bp.sheets import piping

        d = piping.read_sheet(str(path), meta)
    except Exception as e:  # noqa: BLE001
        log.info("pipe_runs: no sheet text (%s)", e)
        return [], 0.0
    out = []
    for it in d.get("items", []):
        b = it.get("bbox") or [0, 0, 0, 0]
        out.append({"text": it.get("text", ""), "bbox": [b[0] * W, b[1] * H, b[2] * W, b[3] * H]})
    return out, float(d.get("cost_usd_now", 0.0) or 0.0)


RX_SIZE_LABEL = re.compile(r"(?<![\d/.])(?:(\d{1,2})\s*(?:\"|\u201d|''|-?\s*INCH\b|-?\s*IN\b)|"
                           r"DN\s*(\d{2,3})\b|(\d{2,3})\s*MM\b)", re.I)


def _nps(m) -> int | None:
    """NPS of a RX_SIZE_LABEL / RX_Q_SIZE match (inch label, DN, or mm)."""
    if m.group(1):
        return int(m.group(1))
    return DN.get(int(m.group(2) or m.group(3)))


def sheet_sizes(lines: list[dict]) -> list[int]:
    """Double-line sizes (3" and up) printed on the sheet."""
    from collections import Counter

    n, named = Counter(), set()
    kw = re.compile(r"HEADER|LINE|PIPE|\bSS\b|REDUCER|INCREASER|VENTURI|\bFROM\b|\bTO\b|SUCTION|DISCHARGE", re.I)
    for ln in lines:
        for m in RX_SIZE_LABEL.finditer(ln["text"]):
            v = _nps(m)
            if v in OD:
                n[v] += 1
                if kw.search(ln["text"]):
                    named.add(v)
    # a size read once with nothing around it is more likely an OCR slip than a pipe
    return sorted(v for v in n if n[v] >= 2 or v in named)


def leader_targets(mask: np.ndarray, bbox, ppf: float, k_max: int = 4) -> list[tuple[float, float]]:
    """Where a label's leader line may point: the far ends of the diagonal lines leaving the label box, nearest
    to the label first (straight horizontal / vertical linework is removed first, so pipe walls do not join the
    leader to the network). The caller keeps the one that lands on a pipe of the label's size."""
    import cv2

    H, W = mask.shape
    padx, pady = int(3 * ppf), int(0.9 * ppf)  # a leader may leave the text through a horizontal shoulder
    R = int(14 * ppf)  # leaders on these sheets are at most ~14 ft of drawing long
    X0, Y0 = max(0, int(bbox[0]) - R), max(0, int(bbox[1]) - R)
    X1, Y1 = min(W, int(bbox[2]) + R), min(H, int(bbox[3]) + R)
    sub = mask[Y0:Y1, X0:X1].copy()
    k = max(10, int(0.45 * ppf))
    hv = cv2.morphologyEx(sub, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1))) | \
        cv2.morphologyEx(sub, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, k)))
    diag = sub & (1 - cv2.dilate(hv, np.ones((3, 3), np.uint8)))
    # blank the label's own lettering
    diag[max(0, int(bbox[1]) - Y0 - 2):max(0, int(bbox[3]) - Y0 + 2),
         max(0, int(bbox[0]) - X0 - 2):max(0, int(bbox[2]) - X0 + 2)] = 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(diag, connectivity=8)
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    found = []
    for i in range(1, n):
        bx, by, bw, bh, area = st[i]
        gx0, gy0 = bx + X0, by + Y0
        if max(bw, bh) < 0.8 * ppf or gx0 > bbox[2] + padx or gx0 + bw < bbox[0] - padx or \
                gy0 > bbox[3] + pady or gy0 + bh < bbox[1] - pady:
            continue
        ys, xs = np.nonzero(lab == i)
        gx, gy = xs + X0, ys + Y0
        # distance of the component to the label box (0 inside); it has to start next to the label
        dx = np.maximum(0, np.maximum(bbox[0] - gx, gx - bbox[2]))
        dy = np.maximum(0, np.maximum(bbox[1] - gy, gy - bbox[3]))
        near = np.min(np.where((dx <= padx) & (dy <= pady), dx + 3 * dy, np.inf))
        if not np.isfinite(near):
            continue
        far = (gx - cx) ** 2 + (gy - cy) ** 2
        j = int(np.argmax(far))
        found.append((near, (float(gx[j]), float(gy[j]))))
    return [p for _, p in sorted(found)[:k_max]]


def text_blocks(lines: list[dict]) -> list[dict]:
    """Stacked lines of one note ("12\" PUMP" / "DISCHARGE" / "HEADER") joined into one label."""
    ls = sorted(lines, key=lambda ln: (ln["bbox"][1], ln["bbox"][0]))
    used = [False] * len(ls)
    out = []
    for i, a in enumerate(ls):
        if used[i]:
            continue
        used[i] = True
        blk = dict(a, bbox=list(a["bbox"]))
        last = a
        for j in range(i + 1, len(ls)):
            b = ls[j]
            if used[j]:
                continue
            h = last["bbox"][3] - last["bbox"][1]
            if b["bbox"][1] - last["bbox"][3] > 0.9 * h:
                if b["bbox"][1] - last["bbox"][3] > 3 * h:
                    break
                continue
            if abs(b["bbox"][0] - last["bbox"][0]) <= 0.6 * h and b["bbox"][1] > last["bbox"][1] + 0.5 * h:
                used[j] = True
                blk["text"] += " " + b["text"]
                bb = blk["bbox"]
                blk["bbox"] = [min(bb[0], b["bbox"][0]), bb[1], max(bb[2], b["bbox"][2]), b["bbox"][3]]
                last = b
        out.append(blk)
    return out


def _dist_to_run(pt, r) -> float:
    (ax, ay), (bx, by) = r["polyline_px"]
    px, py = pt
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def label_check(lines: list[dict], runs: list[dict], ppf: float) -> dict:
    """Bare size labels (8", 12" ...) vs the traced pipe nearest to them (within 6 ft): how many agree."""
    agree = total = 0
    for ln in lines:
        m = RX_SIZE_LABEL.fullmatch(ln["text"].strip())
        if not m or _nps(m) not in OD:
            continue
        c = ((ln["bbox"][0] + ln["bbox"][2]) / 2, (ln["bbox"][1] + ln["bbox"][3]) / 2)
        near = [r for r in runs if _dist_to_run(c, r) <= 6 * ppf]
        if not near:
            continue
        total += 1
        agree += any(r["size_in"] == _nps(m) for r in near)
    return {"labels_near_pipe": total, "agree": agree}


# ------------------------------------------------------------------------------------------------ sheet analysis
def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _pick_scale(lines: list[dict], extra_text: str = "") -> dict | None:
    cands = [parse_scale(ln["text"]) for ln in lines if re.search(r"SCALE", ln["text"], re.I)]
    cands = [c for c in cands if c]
    if not cands:
        cands = [c for c in (parse_scale(ln["text"]) for ln in lines) if c]
    if not cands and extra_text:
        c = parse_scale(extra_text)
        cands = [c] if c else []
    if not cands:
        return None
    from collections import Counter

    k = Counter(c["text"] for c in cands).most_common(1)[0][0]
    return next(c for c in cands if c["text"] == k)


def analyse(path: str, meta: dict | None = None) -> dict | None:
    """Scale, traced runs and text of a sheet (cached on disk per file + page). None when no scale is found."""
    meta = meta or {}
    path = str(path)
    page = int(meta.get("page", 0) or 0)
    key = f"{_sha(path)}_p{page}"
    f = CACHE / f"{key}.json"
    if f.exists():
        try:
            d = json.loads(f.read_text())
            d["cost_usd_now"] = 0.0
            return d
        except json.JSONDecodeError:
            pass
    cost = 0.0
    mask = None
    src = None
    if path.lower().endswith(".pdf"):
        import pymupdf

        pg = pymupdf.open(path)[page]
        zoom = min(300 / 72, 12000 / max(pg.rect.width, pg.rect.height))
        mask = vector_mask(path, page, zoom)
        lines = _pdf_lines(path, page, zoom)
        dpi = zoom * 72
        if mask is not None:
            src = "vector"
        else:  # a scanned PDF: its raster
            img = meta.get("image")
            if not img:
                return None
            gray = _load_gray(img)
            dpi = gray.shape[1] / (pg.rect.width / 72)
            z = dpi / 72
            lines = [dict(ln, bbox=[v / zoom * z for v in ln["bbox"]]) for ln in lines]
            src = "raster"
    else:
        gray = _load_gray(meta.get("image") or path)
        H, W = gray.shape
        lines, cost = _raster_lines(path, meta, W, H)
        dpi = dpi_of(W, H)
        src = "raster"
    if src == "raster":
        H, W = gray.shape
    else:
        H, W = mask.shape
    # the classifier's read of the printed scale (meta["scale"]) backs up a text read that missed it
    scale = _pick_scale(lines, f'{meta.get("scale") or ""} {meta.get("text") or ""}')
    stated = px_per_ft_from(scale, dpi) if scale else None
    bar = scale_bar(lines, W, H, metric=bool(scale and "ratio" in scale))
    cal = []
    if stated:
        cal.append(("stated", stated))
    if bar and (not stated or abs(bar["px_per_ft"] / stated - 1) > 0.04):
        cal.append(("bar", bar["px_per_ft"]))
    if not cal and dpi:  # no printed scale read: the common plan scales, judged by how pipe-like the result is
        cal = [("guessed", dpi * k) for k in (1 / 8, 3 / 16, 1 / 4, 3 / 8, 1 / 2)] + \
              [("guessed", dpi * 12 / n) for n in (20, 25, 50)]
    if not cal:
        return None
    sizes = sheet_sizes(lines) or None
    best = None
    for how, ppf in cal:
        m = mask if src == "vector" else ink_mask(gray, 160 if ppf >= 40 else 232)
        runs = trace_runs(None, ppf, mask=m, sizes=sizes)
        ok = od_check(runs) * sum(r["length_px"] for r in runs) / ppf
        if best is None or ok > best[0]:
            best = (ok, how, ppf, runs, m)
    _, how, ppf, runs, m = best
    # leader targets of named-run labels (headers, mains, lines), for "the 16" suction header"
    named = []
    for ln in text_blocks(lines):
        if re.search(r"HEADER|MAIN|RETURN|SUPPLY|SUCTION|DISCHARGE|LOOP|LINE\b", ln["text"], re.I) and \
                RX_SIZE_LABEL.search(ln["text"]):
            named.append({"text": ln["text"], "bbox": ln["bbox"], "targets": leader_targets(m, ln["bbox"], ppf)})
    metric = bool(scale and "ratio" in scale) or sum(bool(re.search(r"\d\s*MM\b|DN\s*\d", ln["text"], re.I))
                                                     for ln in lines) > sum(bool(re.search(r"\d\s*\"", ln["text"]))
                                                                            for ln in lines)
    d = {"src": src, "metric": metric, "w": W, "h": H, "dpi": dpi, "px_per_ft": ppf, "calibration": how,
         "scale_text": (scale or {}).get("text"), "stated_px_per_ft": stated,
         "bar": bar, "sizes_on_sheet": sizes, "runs": runs, "od_check": round(od_check(runs), 3),
         "labels": label_check(lines, runs, ppf), "named": named, "cost_usd": cost}
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d, default=float))
    except OSError:
        pass
    d["cost_usd_now"] = cost
    return d


# ------------------------------------------------------------------------------------------------ questions
RX_LENGTH = re.compile(r"\b(length|lengths|long|lineal|linear|metres?|meters?|feet|foot|ft|footage|take-?off|"
                       r"how much pipe|how much piping)\b|\bm\b(?!\w)", re.I)
RX_PIPEISH = re.compile(r"pipe|piping|header|\brun\b|\bmain\b|suction|discharge|return|supply|loop|line\b|"
                        r"\d+\s*(?:\"|”|-?\s*inch|in\b)", re.I)
RX_Q_SIZE = re.compile(r"(?<![\d/.])(?:(\d{1,2})\s*(?:\"|\u201d|''|-?\s*inch(?:es)?\b|-?\s*in\b)|"
                       r"DN\s*(\d{2,3})\b|(\d{2,3})\s*-?\s*mm\b)", re.I)
RX_BY_SIZE = re.compile(r"by size|per size|each size|for each|breakdown|every size|all sizes", re.I)
RX_METRIC = re.compile(r"\b(metres?|meters?|m)\b", re.I)
RX_NAMED = re.compile(r"(suction|discharge|return|supply|fill|drain|header|main|loop|cross[- ]connection)", re.I)


def is_length_question(q: str) -> bool:
    """A question about how much / how long pipe is (for piping.py's dispatcher)."""
    return bool(RX_LENGTH.search(q) and RX_PIPEISH.search(q)) and \
        not re.search(r"how many (?!met|feet|ft|m\b)", q, re.I)


def detect(meta) -> float:
    try:
        from bp.sheets import kw_score

        return kw_score(meta, "piping")
    except Exception:  # noqa: BLE001
        return 0.0


def _fmt(v: float) -> str:
    return f"{v:.1f}"


def _sz(nps, metric: bool = False) -> str:
    return f'{NPS_DN[nps]} mm ({nps}")' if metric and nps in NPS_DN else f'{nps}"'


def _ev(r, W, H, unit, metric=False):
    (x0, y0), (x1, y1) = r["polyline_px"]
    h = r["width_px"] / 2
    bx = [min(x0, x1) - (h if r["axis"] == "v" else 0), min(y0, y1) - (h if r["axis"] == "h" else 0),
          max(x0, x1) + (h if r["axis"] == "v" else 0), max(y0, y1) + (h if r["axis"] == "h" else 0)]
    val = r["length_m"] if unit == "m" else r["length_ft"]
    return {"kind": "box", "page": 0, "bbox": [bx[0] / W, bx[1] / H, bx[2] / W, bx[3] / H],
            "points": [[x0 / W, y0 / H], [x1 / W, y1 / H]],
            "label": f'{_sz(r["size_in"], metric)} run {r["length_ft"]:.1f} ft ({r["length_m"]:.2f} m)',
            "value": round(val, 2)}


def _sum_expr(runs, unit, k=8):
    vals = [r["length_m"] if unit == "m" else r["length_ft"] for r in runs]
    s = " + ".join(_fmt(v) for v in vals[:k])
    if len(vals) > k:
        s += f" + {len(vals) - k} shorter ({_fmt(sum(vals[k:]))})"
    return s


CAVEAT = ("Centreline lengths of the double-line pipe drawn in plan, fittings and valves included, measured to the "
          "centreline of the pipe each run tees into; not included: single-line small bore (2\" and under), risers "
          "and drops (no plan length), and pipe where both walls are not drawn (dashed below-grade runs, under "
          "equipment).")


def answer(path, question, meta) -> dict | None:
    meta = meta or {}
    q = question.strip()
    if not is_length_question(q):
        return None
    d = analyse(str(path), meta)
    if not d or not d["runs"]:
        return None
    runs, ppf, W, H = d["runs"], d["px_per_ft"], d["w"], d["h"]
    metric = bool(d.get("metric"))
    feet = re.search(r"\bfeet|\bft\b|foot", q, re.I)
    unit = "m" if (RX_METRIC.search(q) or metric) and not feet else "ft"
    conv = FT_M if unit == "m" else 1.0
    ul = "m" if unit == "m" else "ft"
    calib = (f"scale {d['scale_text'] or '?'} at {d['dpi']:.0f} dpi = {ppf:.1f} px/ft" if d["calibration"] == "stated"
             else f"graphic scale bar {'/'.join(d['bar']['labels'])} = {ppf:.1f} px/ft" if d["calibration"] == "bar"
             else f"no scale read; {ppf:.1f} px/ft is the common plan scale at which the pipe walls best match "
                  f"standard outside diameters (GUESSED)")
    if d.get("bar") and d["calibration"] == "stated":
        calib += f" (scale bar agrees: {d['bar']['px_per_ft']:.1f} px/ft)"
    lc = d.get("labels") or {}
    check = f"; {lc['agree']}/{lc['labels_near_pipe']} size labels sit on a traced pipe of that size" \
        if lc.get("labels_near_pipe") else ""
    conf = {"vector": 0.6, "raster": 0.5}[d["src"]]
    if d["calibration"] == "guessed":
        conf = 0.2
    if ppf < 30:
        conf = min(conf, 0.25)  # low-resolution raster: wall spacing to +-1.5 px, sizes can slip one step
    conf *= 0.6 + 0.4 * min(1.0, d.get("od_check", 0))
    base = {"method": METHOD, "cost_usd": round(d.get("cost_usd_now", 0.0), 5), "unit": ul,
            "px_per_ft": round(ppf, 2), "source": d["src"]}
    m = RX_Q_SIZE.search(q)
    size = _nps(m) if m else None
    named = RX_NAMED.search(q)

    label = None
    if named:  # the printed label that best matches the question's words ("12\" F/S DISCHARGE HEADER")
        stop = {"the", "of", "on", "this", "plan", "sheet", "what", "is", "how", "long", "total", "length", "in",
                "feet", "foot", "ft", "metres", "meters", "m", "pipe", "piping", "a", "an", "linear", "much", "are",
                "there", "inch", "inches", "lengths", "s"}
        qt = {w for w in re.findall(r"[a-z/]+", q.lower()) if w not in stop}
        # the label must carry the question's specific naming words ("suction"); generic ones ("header") may be
        # lost to the text read and only add to the score
        need = {w.lower() for w in RX_NAMED.findall(q)} - {"header", "main", "loop"}
        best = (0, None)
        toks = [set(re.findall(r"[a-z/]+", n["text"].lower())) for n in d["named"]]
        df = {w: sum(w in t for t in toks) for w in qt}
        for n, lt in zip(d["named"], toks):
            mm = RX_SIZE_LABEL.search(n["text"])
            if size is not None and (not mm or _nps(mm) != size):
                continue
            if not all(w in n["text"].lower() for w in need):
                continue
            # rarer words ("F/S") count more than "header"; a naming word the question does not use ("PUMP")
            # counts against the label
            sc = sum(1.0 / df[w] for w in qt & lt) - 0.3 * len({w for w in lt - qt if len(w) >= 4})
            if sc > best[0]:
                best = (sc, n)
        label = best[1]
        if size is None and label is not None:
            size = _nps(RX_SIZE_LABEL.search(label["text"]))

    if named and size is None and re.search(r"\bthe\b", q, re.I):
        return None  # "the suction header" with no such label on the sheet: let the generic path say so

    if size is not None and named:
        cands = [r for r in runs if r["size_in"] == size]
        if not cands:
            return None
        pick, how = None, ""
        if label is not None:
            hits = [(_dist_to_run(t, r), r) for t in label.get("targets") or [] for r in cands]
            hits = [(dd, r) for dd, r in hits if dd <= max(0.5 * r["width_px"] + 0.5 * ppf, 1.0 * ppf)]
            if hits:
                pick = min(hits, key=lambda h: h[0])[1]
                how = f'the run the leader of "{label["text"]}" points at'
        if pick is None:
            pick = max(cands, key=lambda r: r["length_px"])
            how = f'the longest straight {_sz(size, metric)} run (no leader traced to it)'
        v = pick["length_ft"] * conv
        return dict(base, answer=round(v, 2 if unit == "m" else 1), confidence=round(conf * 0.95, 3),
                    explanation=(f'{_sz(size, metric)} {named.group(1).lower()} = {how}: '
                                 f'{pick["length_px"]:.0f} px / {ppf:.1f} '
                                 f'px/ft = {pick["length_ft"]:.1f} ft = {pick["length_m"]:.2f} m ({calib}). '
                                 f"Other {_sz(size, metric)} runs on the sheet: {len(cands) - 1}. {CAVEAT}"),
                    evidence=[_ev(pick, W, H, unit, metric)])

    if size is not None:
        sel = [r for r in runs if r["size_in"] == size]
        if size not in OD:
            return dict(base, answer=None, confidence=0.0, evidence=[],
                        explanation=f'{_sz(size, metric)} pipe is drawn single-line at this scale; '
                                    'its length is not measured.')
        if not sel:
            return dict(base, answer=None, confidence=0.0, evidence=[],
                        explanation=f'No double-line {_sz(size, metric)} pipe traced ({calib}). {CAVEAT}')
        tot = sum(r["length_ft"] for r in sel) * conv
        return dict(base, answer=round(tot, 1), confidence=round(conf, 3),
                    explanation=(f'{_sz(size, metric)} pipe: {len(sel)} straight runs, '
                                 f'{_sum_expr(sel, unit)} = {tot:.1f} {ul}'
                                 + (f" (= {tot / FT_M:.1f} ft)" if unit == "m" else f" (= {tot * FT_M:.1f} m)")
                                 + f"; {calib}{check}. {CAVEAT}"),
                    evidence=[_ev(r, W, H, unit, metric) for r in sel])

    # by size (also "total length of pipe")
    by = {}
    for r in runs:
        by.setdefault(r["size_in"], []).append(r)
    parts = []
    total = 0.0
    for s in sorted(by, reverse=True):
        v = sum(r["length_ft"] for r in by[s]) * conv
        total += v
        parts.append(f'{_sz(s, metric)}: {v:.1f} {ul}')
    if RX_BY_SIZE.search(q) or not re.search(r"\btotal\b|all (the )?pip", q, re.I):
        ans = "; ".join(parts) + f" (total {total:.1f} {ul})"
    else:
        ans = round(total, 1)
    ev = [_ev(r, W, H, unit, metric) for s in sorted(by, reverse=True) for r in by[s]]
    expl = " | ".join(f'{_sz(s, metric)}: {_sum_expr(by[s], unit, 5)} = '
                      f'{sum(r["length_ft"] for r in by[s]) * conv:.1f} {ul}'
                      for s in sorted(by, reverse=True))
    return dict(base, answer=ans, confidence=round(conf * 0.9, 3),
                explanation=f"{expl}; total {total:.1f} {ul}; {calib}{check}. {CAVEAT}", evidence=ev)
