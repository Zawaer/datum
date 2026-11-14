"""Doors and windows on architectural floor plans, by classical CV at full resolution (no training data needed).

Reached through bp/sheets/arch.py (SUBMODULES: "doors" / "windows" / "doors_windows" -> openings.answer), and
reusable on its own: `find_doors(image)` / `find_windows(image)` take a path, PIL image or grey ndarray and return
pixel boxes [x0, y0, x1, y1].

Doors  : the swing arc. Ink is split into thick walls (morphological opening) and thin linework (the rest). Each
         thin connected component of door size is searched (RANSAC) for circle arcs; an arc counts as a door swing
         when it spans ~60-120 degrees, its centre (the hinge) sits on a wall end and a straight leaf runs from the
         hinge out to one arc end. Two swings whose hinges are r1 + r2 apart and that close towards each other are one
         double door. Folding doors and leaves drawn ajar (no arc) are found as straight leaf strokes; sliding doors are not.
Windows: a glazing strip in a thick wall: two or more thin parallel lines, about a wall thickness apart, running
         between two solid wall piers whose thickness matches the strip. Strips on the building's outside face are
         windows; strips between two rooms are reported separately as internal glazing.
Scale  : a PDF page's printed ratio (1:200, 1/4" = 1'-0") and paper size, else arch.scale(meta), else the median
         door-swing radius taken as 0.9 m. Rasters are worked at ~110 px/m (vector PDF pages are re-rendered).
Fallback (answer() never trusts an implausible swing reading): low-res rasters (needing > 2x upsampling), sheets where
         the swings come out far short of the CubiCasa detector or below ~1 door per 200 m2 of building bbox, use the
         detector's boxes (resampled to 40 px/m) at confidence 0.5; a Claude Haiku count on 3x3 tiles (~$0.01) can
         only raise it (0.6 when within 15 %): it undercounts dense sheets, so it never vetoes.
Schedule: on a vector PDF with a DOOR SCHEDULE page, the schedule marks printed on this sheet are an independent door
         count; agreement raises confidence, disagreement switches the answer to the schedule count (and says so).

Measured (tests/fixtures/openings/eval_gold.json): DfE school level 00, 14000 px: doors 122 found / 122 correct / 128
by hand (P 1.00, R 0.95), exterior windows 67 / 67 / 68, plus 11 internal glazed panels reported separately.
2000 px school screenshot via the detector: 120-126 doors (hand 128, P ~0.8), 75 windows. DAF dormitory (double-line
walls, grey swings): no method within 10 % of a rough structural count (~130 hinged doors), answers say so.
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

METHOD = "sheets-openings"
DARK = 110  # walls / black linework
INK = 165  # thin linework incl. grey door swings (some CAD exports draw swings ~150 grey, furniture ~170+)
# measured on the hand-checked school plan (tests/fixtures/openings/eval_gold.json); the answer's confidence is capped lower
# because a single sheet is a thin basis (the US A-101 pump house sheet scored P 5/8, R 5/6 for doors)
PRECISION = {"door": 0.98, "window": 0.99}
RECALL = {"door": 0.95, "window": 0.99}


# --------------------------------------------------------------------------------------------------- image prep
def _gray(image) -> np.ndarray:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    if isinstance(image, np.ndarray):
        a = image
        if a.ndim == 3:
            a = (a[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)).astype(np.uint8)
        return a
    from bp.sheets.rooms import gray_unmarked

    im = image if hasattr(image, "convert") else Image.open(str(image))
    return gray_unmarked(im)  # coloured pen markings on a scan are not walls or door leaves


def _line_width(dark: np.ndarray) -> int:
    """Most common horizontal run length of ink among thin runs (the drawing's line weight), in px."""
    sub = dark[:: max(1, dark.shape[0] // 1500)]
    d = np.diff(np.pad(sub.astype(np.int8), ((0, 0), (1, 1))), axis=1)
    starts = np.argwhere(d == 1)
    ends = np.argwhere(d == -1)
    runs = ends[:, 1] - starts[:, 1]
    runs = runs[(runs >= 1) & (runs <= 12)]
    if len(runs) == 0:
        return 2
    return int(np.bincount(runs).argmax())


def _layers(gray: np.ndarray, ink_thr: int = INK):
    """(dark, ink, wall, thin, lw): wall = solid fill thicker than ~3 line widths; thin = ink off the walls."""
    import cv2

    dark = gray < DARK
    ink = gray < ink_thr
    lw = max(1, _line_width(dark))
    k = max(5, 2 * lw + 3)
    wall = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    # text strokes and arrow heads survive a small opening only as specks: keep wall blobs of real size
    n, lab, st, _ = cv2.connectedComponentsWithStats(wall, 8)
    keep = np.zeros(n, bool)
    keep[1:] = (st[1:, cv2.CC_STAT_AREA] >= 4 * k * k) & (np.maximum(st[1:, 2], st[1:, 3]) >= 2 * k)
    wall = keep[lab].astype(np.uint8)
    wd = cv2.dilate(wall, np.ones((2 * lw + 3, 2 * lw + 3), np.uint8))
    thin = (ink & (wd == 0)).astype(np.uint8)
    return dark, ink, wall, thin, lw, k


# ------------------------------------------------------------------------------------------------------- doors
def _circle3(p):
    (x1, y1), (x2, y2), (x3, y3) = p
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-6:
        return None
    s1, s2, s3 = x1 * x1 + y1 * y1, x2 * x2 + y2 * y2, x3 * x3 + y3 * y3
    cx = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / d
    cy = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
    return cx, cy, math.hypot(x1 - cx, y1 - cy)


def _arc_span(ang: np.ndarray, bins: int = 72):
    """(span degrees of the longest run of occupied 5-degree bins on the circle, start angle, end angle)."""
    occ = np.zeros(bins, bool)
    occ[((ang % (2 * np.pi)) / (2 * np.pi) * bins).astype(int) % bins] = True
    if occ.all():
        return 360.0, 0.0, 2 * np.pi
    # rotate so that an empty bin is first, then find the longest run (gaps of one bin are bridged)
    z = int(np.argmin(occ))
    o = np.roll(occ, -z)
    o2 = o.copy()
    for i in range(1, bins - 1):
        if not o[i] and o[i - 1] and o[i + 1]:
            o2[i] = True
    best, cur, bs = 0, 0, 0
    for i, v in enumerate(o2):
        cur = cur + 1 if v else 0
        if cur > best:
            best, bs = cur, i - cur + 1
    a0 = ((bs + z) % bins) / bins * 2 * np.pi
    return best * 360.0 / bins, a0, a0 + best / bins * 2 * np.pi


def _leaf(thin, wall, cx, cy, r, a0, a1, lw):
    """Is there a straight leaf line from the hinge (cx, cy) to one end of the arc? Returns the end angle or None."""
    H, W = thin.shape
    best = None
    for a in (a0, a1):
        n = max(8, int(r))
        ts = np.linspace(0.12, 0.92, n)
        xs = np.clip(np.round(cx + np.cos(a) * r * ts).astype(int), 0, W - 1)
        ys = np.clip(np.round(cy + np.sin(a) * r * ts).astype(int), 0, H - 1)
        hit = 0
        rad = max(2, lw + 1)
        for x, y in zip(xs, ys):
            if thin[max(0, y - rad):y + rad + 1, max(0, x - rad):x + rad + 1].any() or \
                    wall[max(0, y - 1):y + 2, max(0, x - 1):x + 2].any():
                hit += 1
        f = hit / n
        if best is None or f > best[1]:
            best = (a, f)
    return best


def _arcs_in(pts, rmin, rmax, tol, rng, iters=1500, min_span=65, max_span=135):
    """RANSAC circle arcs among component points (N x 2, x/y). Returns [(cx, cy, r, span, a0, a1, n_inliers)]."""
    out = []
    pts = pts.astype(np.float64)
    for _ in range(3):  # up to three swings in one component (double doors, a door beside a cupboard)
        if len(pts) < 20:
            break
        # vectorised RANSAC: many triples at once, scored on a subsample, best one re-scored on all points
        idx = rng.integers(0, len(pts), (iters, 3))
        P = pts[idx]
        x1, y1, x2, y2, x3, y3 = P[:, 0, 0], P[:, 0, 1], P[:, 1, 0], P[:, 1, 1], P[:, 2, 0], P[:, 2, 1]
        d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        ok = np.abs(d) > 1e-6
        d = np.where(ok, d, 1.0)
        s1, s2, s3 = x1 * x1 + y1 * y1, x2 * x2 + y2 * y2, x3 * x3 + y3 * y3
        cx = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / d
        cy = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
        r = np.hypot(x1 - cx, y1 - cy)
        ok &= (r >= rmin) & (r <= rmax)
        best = None
        if ok.any():
            cx, cy, r = cx[ok], cy[ok], r[ok]
            sub = pts if len(pts) <= 1200 else pts[rng.choice(len(pts), 1200, replace=False)]
            D = np.abs(np.hypot(sub[None, :, 0] - cx[:, None], sub[None, :, 1] - cy[:, None]) - r[:, None]) < tol
            score = D.sum(1) * len(pts) / len(sub)
            j = int(np.argmax(score))
            c = (float(cx[j]), float(cy[j]), float(r[j]))
            inl = np.abs(np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1]) - c[2]) < tol
            k = int(inl.sum())
            if k >= 0.6 * c[2] * 0.9:  # a quarter arc has ~1.57 r pixels on its centre line; demand a good part
                best = (c, k, inl)
        if best is None:
            break
        (cx, cy, r), k, inl = best
        # refine by least squares on the inliers
        q = pts[inl]
        A = np.c_[2 * q[:, 0], 2 * q[:, 1], np.ones(len(q))]
        b = (q ** 2).sum(1)
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        cx2, cy2 = sol[0], sol[1]
        r2 = math.sqrt(max(1e-6, sol[2] + cx2 ** 2 + cy2 ** 2))
        if rmin <= r2 <= rmax and abs(r2 - r) < 0.15 * r:
            cx, cy, r = cx2, cy2, r2
            d = np.abs(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) - r)
            inl = d < tol
        ang = np.arctan2(pts[inl, 1] - cy, pts[inl, 0] - cx)
        span, a0, a1 = _arc_span(ang)
        if min_span <= span <= max_span:
            out.append((cx, cy, r, span, a0, a1, int(inl.sum())))
        pts = pts[~inl]
    return out


def _swings(gray, px_per_m=None, layers=None):
    """Door swing arcs: [{"c": (cx, cy), "r", "a0", "a1", "span", "leaf", "hinge_wall", "score"}] in px."""
    import cv2

    dark, ink, wall, thin, lw, k = layers or _layers(gray)
    H, W = gray.shape
    if px_per_m:
        rmin, rmax = 0.4 * px_per_m, 1.6 * px_per_m
    else:
        rmin, rmax = max(12.0, 5 * lw, max(W, H) / 300), max(W, H) / 30  # sheet-relative without a scale
    n, lab, st, _ = cv2.connectedComponentsWithStats(thin, 8)
    rng = np.random.default_rng(0)
    tol = max(1.5, 0.8 * lw + 0.8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if max(w, h) < 0.6 * rmin or max(w, h) > 2.6 * rmax + 4 * k or a < 1.2 * rmin:
            continue
        if min(w, h) < 0.4 * rmin:  # a straight line: no arc
            continue
        sub = lab[y:y + h, x:x + w] == i
        ys, xs = np.nonzero(sub)
        pts = np.c_[xs + x, ys + y]
        if len(pts) > 4000:
            pts = pts[rng.choice(len(pts), 4000, replace=False)]
        for cx, cy, r, span, a0, a1, ni in _arcs_in(pts, rmin, rmax, tol, rng):
            la, lf = _leaf(thin, wall, cx, cy, r, a0, a1, lw)
            hx, hy = int(round(cx)), int(round(cy))
            rr = max(3, int(0.12 * r))
            near = wall[max(0, hy - rr):hy + rr + 1, max(0, hx - rr):hx + rr + 1]
            hinge_wall = bool(near.any())
            # the arc's free end should also land on a wall/jamb or the other leaf (not floating like a chair back)
            fill = ni / max(1.0, r * math.radians(span))
            # the arc runs through free space: its middle is not on (or hugging) a solid mass
            am = (a0 + a1) / 2
            mx, my = int(cx + r * math.cos(am)), int(cy + r * math.sin(am))
            o = 2 * lw + 4
            if wall[max(0, my - o):my + o + 1, max(0, mx - o):mx + o + 1].any():
                continue
            score = 0.35 * min(1, lf / 0.8) + 0.25 * hinge_wall + 0.2 * min(1, fill) + 0.2 * (70 <= span <= 110)
            out.append({"c": (cx, cy), "r": r, "a0": a0, "a1": a1, "span": span, "leaf": lf, "leaf_a": la,
                        "hinge_wall": hinge_wall, "fill": fill, "score": score})
    return out


def _swing_box(s):
    cx, cy = s["c"]
    r = s["r"]
    angs = np.linspace(s["a0"], s["a1"], 16)
    xs = np.r_[cx, cx + r * np.cos(angs)]
    ys = np.r_[cy, cy + r * np.sin(angs)]
    return [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]


def _pair(s, t):
    """Two swings of one double door: hinges r1 + r2 apart, both closing towards the gap between them."""
    (x1, y1), (x2, y2) = s["c"], t["c"]
    d = math.hypot(x2 - x1, y2 - y1)
    rs = s["r"] + t["r"]
    if abs(d - rs) > 0.22 * rs or max(s["r"], t["r"]) > 2.2 * min(s["r"], t["r"]):
        return False
    ux, uy = (x2 - x1) / d, (y2 - y1) / d
    # each swing's closed-leaf end (one of a0/a1) points along the hinge line towards the other hinge
    def toward(sw, vx, vy):
        return max(math.cos(sw["a0"]) * vx + math.sin(sw["a0"]) * vy, math.cos(sw["a1"]) * vx + math.sin(sw["a1"]) * vy)
    if toward(s, ux, uy) < 0.85 or toward(t, -ux, -uy) < 0.85:
        return False
    # and both swing to the same side of the hinge line
    def side(sw):
        m = (sw["a0"] + sw["a1"]) / 2
        return math.cos(m) * -uy + math.sin(m) * ux
    return side(s) * side(t) > 0


def doors_detail(image, px_per_m=None, min_score=0.6, layers=None, footprint=None):
    """Doors with their parts: [{"bbox": px box, "leaves": 1|2, "score", "swings": [...]}], reading order.
    footprint: (mask, f) of the building (from _windows); swings whose hinge is off the building are dropped."""
    gray = _gray(image)
    sw = [s for s in _swings(gray, px_per_m, layers) if s["score"] >= min_score * 0.75 and s["hinge_wall"]]
    if footprint is not None:
        m, f = footprint
        sw = [s for s in sw if 0 <= int(s["c"][1] / f) < m.shape[0] and 0 <= int(s["c"][0] / f) < m.shape[1]
              and m[int(s["c"][1] / f), int(s["c"][0] / f)]]
    # suppress near-duplicate swings (one arc found twice from overlapping components)
    sw.sort(key=lambda s: -s["score"])
    uniq = []
    for s in sw:
        if any(math.hypot(s["c"][0] - u["c"][0], s["c"][1] - u["c"][1]) < 0.25 * s["r"] and abs(s["r"] - u["r"]) < 0.25 * s["r"]
               for u in uniq):
            continue
        uniq.append(s)
    used = set()
    doors = []
    for i, s in enumerate(uniq):
        if i in used:
            continue
        partner = None
        for j, t in enumerate(uniq):
            if j <= i or j in used:
                continue
            if _pair(s, t):
                partner = j
                break
        if partner is not None:
            used |= {i, partner}
            t = uniq[partner]
            b1, b2 = _swing_box(s), _swing_box(t)
            doors.append({"bbox": [min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])],
                          "leaves": 2, "score": (s["score"] + t["score"]) / 2 + 0.05, "swings": [s, t]})
        else:
            used.add(i)
            doors.append({"bbox": _swing_box(s), "leaves": 1, "score": s["score"], "swings": [s]})
    doors = [d for d in doors if d["score"] >= min_score]
    doors.sort(key=lambda d: (round(d["bbox"][1] / max(1, gray.shape[0] / 40)), d["bbox"][0]))
    return doors


def _leaf_doors(layers, px_per_m, footprint, taken):
    """Doors drawn without a swing: a straight leaf standing ajar (5-45 degrees off the wall) from a wall end, or
    a folding door's zig-zag. Hough segments of door length on the thin layer, starting at a wall."""
    import cv2

    dark, ink, wall, thin, lw, k = layers
    lmin, lmax = (0.35 * px_per_m, 1.4 * px_per_m) if px_per_m else (max(8 * k, max(wall.shape) / 250), 30 * k)
    # isolated thin components of door size that are made of a few straight strokes (a leaf, a zig-zag)
    n, lab, st, _ = cv2.connectedComponentsWithStats(thin, 8)
    segs = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if not (0.7 * lmin <= max(w, h) <= 1.6 * lmax) or a > 6 * lmax * lw:
            continue
        crop = ((lab[y:y + h, x:x + w] == i) * 255).astype(np.uint8)
        ss = cv2.HoughLinesP(np.pad(crop, 2), 1, np.pi / 360, threshold=int(lmin * 0.4),
                             minLineLength=int(lmin * 0.6), maxLineGap=max(2, lw * 2))
        if ss is None:
            continue
        ss = [(x1 + x - 2, y1 + y - 2, x2 + x - 2, y2 + y - 2) for x1, y1, x2, y2 in ss.reshape(-1, 4).tolist()]
        # straightness: one stroke-width band around the segments holds nearly all of the component's ink
        band = np.zeros_like(crop)
        for x1, y1, x2, y2 in ss:
            cv2.line(band, (x1 - x, y1 - y), (x2 - x, y2 - y), 255, 2 * lw + 3)
        if (crop[band > 0] > 0).sum() < 0.85 * (crop > 0).sum():
            continue
        segs += ss
    if not segs:
        return []
    m, f = footprint
    H, W = wall.shape
    rr = 2 * k

    def at_wall(x, y):
        x, y = int(x), int(y)
        return bool(wall[max(0, y - rr):y + rr + 1, max(0, x - rr):x + rr + 1].any())

    cands = []
    for x1, y1, x2, y2 in segs:
        L = math.hypot(x2 - x1, y2 - y1)
        if not (lmin <= L <= lmax):
            continue
        ang = math.degrees(math.atan2(abs(y2 - y1), abs(x2 - x1)))
        off = min(ang, 90 - ang)
        if off < 6:  # axis-aligned: a wall face, sliding panel, furniture edge or dimension line
            continue
        w1, w2 = at_wall(x1, y1), at_wall(x2, y2)
        if not (w1 or w2):
            continue
        # the free end stands near the opposite jamb (a leader line ends at its note, away from any wall)
        fx, fy = (x2, y2) if w1 else (x1, y1)
        hx, hy = (x1, y1) if w1 else (x2, y2)
        q = int(1.05 * L)
        bx0, by0 = max(0, int(fx) - q), max(0, int(fy) - q)
        wy, wx = np.nonzero(wall[by0:int(fy) + q + 1, bx0:int(fx) + q + 1])
        if not len(wx) or not (np.hypot(wx + bx0 - hx, wy + by0 - hy) > 0.6 * L).any():
            continue
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if not (0 <= int(cy / f) < m.shape[0] and 0 <= int(cx / f) < m.shape[1] and m[int(cy / f), int(cx / f)]):
            continue
        if any(b[0] - 0.2 * L <= cx <= b[2] + 0.2 * L and b[1] - 0.2 * L <= cy <= b[3] + 0.2 * L for b in taken):
            continue
        # a stroke running along a solid mass (the edge of a filled arrow / north point) is not a leaf
        nx, ny = -(y2 - y1) / L, (x2 - x1) / L
        o = 2 * lw + 6
        if any(wall[min(H - 1, max(0, int(cy + sg * ny * o))), min(W - 1, max(0, int(cx + sg * nx * o)))]
               for sg in (-1, 1)):
            continue
        cands.append((min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2), L, off, w1 and w2))
    # one door per cluster of segments (a folding door is two or four; Hough splits lines too)
    out = []
    for c in sorted(cands, key=lambda c: -c[4]):
        b = [float(c[0]), float(c[1]), float(c[2]), float(c[3])]
        hit = None
        for o in out:
            ob = o["bbox"]
            g = 0.3 * c[4]
            if b[0] <= ob[2] + g and ob[0] <= b[2] + g and b[1] <= ob[3] + g and ob[1] <= b[3] + g:
                hit = o
                break
        if hit:
            ob = hit["bbox"]
            hit["bbox"] = [min(ob[0], b[0]), min(ob[1], b[1]), max(ob[2], b[2]), max(ob[3], b[3])]
            hit["segments"] += 1
        else:
            out.append({"bbox": b, "leaves": 1, "kind": "leaf", "segments": 1, "score": 0.6 if c[5] < 45 else 0.5})
    for o in out:  # pad thin boxes so the mark is visible
        b = o["bbox"]
        pad = 0.1 * max(b[2] - b[0], b[3] - b[1])
        o["bbox"] = [max(0.0, b[0] - pad), max(0.0, b[1] - pad), min(W, b[2] + pad), min(H, b[3] + pad)]
    return out


def analyse(image, px_per_m=None, ink_thr: int = INK, lowres: bool = False) -> dict:
    """Doors and windows in one pass (shared layers; doors limited to the building footprint).
    {"doors": doors_detail items, "windows": exterior strips, "internal_glazing": interior strips, "size": (W, H)}"""
    import cv2

    gray = _gray(image)
    layers = _layers(gray, ink_thr)
    raw = doors_detail(gray, px_per_m, layers=layers)  # door swings close their openings in the footprint
    strips, inside, f = _windows(gray, px_per_m, layers, [d["bbox"] for d in raw], lowres)
    grow = int((1.0 * px_per_m if px_per_m else 20 * layers[5]) / f) | 1
    fp = cv2.dilate(inside.astype(np.uint8), np.ones((grow, grow), np.uint8)).astype(bool)
    doors = doors_detail(gray, px_per_m, layers=layers, footprint=(fp, f))
    for d in doors:
        d["kind"] = "swing"
    doors += _leaf_doors(layers, px_per_m, (fp, f), [d["bbox"] for d in doors] + [w["bbox"] for w in strips])
    H = gray.shape[0]
    doors.sort(key=lambda d: (round(d["bbox"][1] / max(1, H / 40)), d["bbox"][0]))
    return {"doors": doors, "windows": [w for w in strips if w["exterior"]],
            "internal_glazing": [w for w in strips if not w["exterior"]], "size": (gray.shape[1], gray.shape[0])}


DOOR_LEAF_M = 0.9  # typical single leaf width; the median swing radius gives the scale when none is printed


def estimate_px_per_m(gray) -> float | None:
    """Scale from the drawing itself: median radius of clear door swings / 0.9 m (None with < 5 swings)."""
    gray = _gray(gray)
    sw = [s for s in _swings(gray) if s["score"] >= 0.85 and 75 <= s["span"] <= 105 and s["hinge_wall"]]
    if len(sw) < 5:
        return None
    r = np.array([s["r"] for s in sw])
    p25, p50, p75 = np.percentile(r, [25, 50, 75])
    log.info("openings scale estimate: %d swings, r p25/50/75 = %.0f/%.0f/%.0f px", len(r), p25, p50, p75)
    if p75 / p25 > 1.5:  # radii all over the place: arcs of text and symbols, not a door population
        return None
    if p25 < 1.2 * max(12.0, max(gray.shape) / 300):  # piled up at the search floor: small symbols, not doors
        return None
    return float(p50) / DOOR_LEAF_M


TARGET_PX_PER_M = 110.0  # the pixel density the thresholds were tuned at (DfE school, 1:200 A2 at 14000 px)
MAX_SIDE = 16000


def detect_openings(image, px_per_m=None) -> dict:
    """analyse() at a working resolution: small rasters (screenshots, 2000-3000 px JPGs) are upsampled so that
    door swings are ~100 px in radius (to TARGET_PX_PER_M when the scale is known, else to ~12000 px on the long
    side); boxes come back in the input image's pixels. Adds "factor" (working / input)."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    if isinstance(image, np.ndarray):
        im = Image.fromarray(_gray(image))
    else:
        im = image if hasattr(image, "convert") else Image.open(str(image))
        im = Image.fromarray(_gray(im))
    W, H = im.size
    est = None
    if not px_per_m and max(W, H) >= 6000:
        px_per_m = est = estimate_px_per_m(np.asarray(im))
    if px_per_m:
        f = TARGET_PX_PER_M / px_per_m
    else:
        f = 12000 / max(W, H)
    f = max(1.0, min(f, 3.0, MAX_SIDE / max(W, H)))
    if f < 1.15:
        f = 1.0
    work = im if f == 1.0 else im.resize((round(W * f), round(H * f)), Image.BICUBIC)
    # rasters needing > 2x upsampling (screenshots, ~2000 px JPGs) lose door swings to sub-pixel dotted lines;
    # measured on the school screenshot the result is unusable, so callers get a "low_res" flag to abstain on
    res = analyse(np.asarray(work), px_per_m * f if px_per_m else None)
    res["low_res"] = f >= 2
    res["px_per_m_estimated"] = est
    if f != 1.0:
        for key in ("doors", "windows", "internal_glazing"):
            for d in res[key]:
                d["bbox"] = [v / f for v in d["bbox"]]
                d.pop("swings", None)
        res["size"] = (W, H)
    res["factor"] = f
    return res


def find_doors(image, px_per_m=None) -> list[list[float]]:
    """Pixel boxes [x0, y0, x1, y1] of the doors (a double door is one box; swing, folding and ajar leaves)."""
    return [d["bbox"] for d in detect_openings(image, px_per_m)["doors"]]


# ----------------------------------------------------------------------------------------------------- windows
def _inside(wall, strips, px_per_m, k):
    """(mask of the building footprint at 1/f resolution, f): thick walls plus glazing strips, door swings
    and gaps up to ~1.5 m closed, holes filled. Everything else is outside."""
    import cv2

    H, W = wall.shape
    f = 8 if max(H, W) > 6000 else 4
    # wall pieces of real size only (bold title text and the north arrow also survive the wall opening)
    n, lab, st, _ = cv2.connectedComponentsWithStats(wall, 8)
    big = np.zeros(n, bool)
    big[1:] = np.maximum(st[1:, 2], st[1:, 3]) >= (1.0 * px_per_m if px_per_m else 15 * k)
    m = cv2.resize(big[lab].astype(np.uint8) * 255, (W // f, H // f), interpolation=cv2.INTER_AREA) > 0
    m = m.astype(np.uint8)
    for b in strips:
        x0, y0, x1, y1 = (int(v / f) for v in b)
        m[y0:y1 + 1, x0:x1 + 1] = 1
    gap = int((1.5 * px_per_m if px_per_m else 25 * k) / f) | 1
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (gap, gap)))
    ff = np.pad(1 - m, 1, constant_values=1).astype(np.uint8)
    mask = np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8)
    cv2.floodFill(ff, mask, (0, 0), 2)
    inside = (ff[1:-1, 1:-1] != 2).astype(np.uint8)
    # the building is the big blob(s); bold title-block text and the north arrow are small ones
    n, lab, st, _ = cv2.connectedComponentsWithStats(inside, 8)
    if n > 1:
        big = st[1:, cv2.CC_STAT_AREA].max()
        keep = np.zeros(n, bool)
        keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 0.1 * big
        inside = keep[lab]
    return inside.astype(bool), f


def windows_detail(image, px_per_m=None, layers=None):
    """Glazing strips in thick walls: [{"bbox", "axis": "h"|"v", "exterior": bool, "lines": n, "score"}]."""
    gray = _gray(image)
    return _windows(gray, px_per_m, layers or _layers(gray))[0]


def _windows(gray, px_per_m, layers, extra_boxes=(), lowres=False):
    """(strips, building footprint mask at 1/f, f)."""
    import cv2

    dark, ink, wall, thin, lw, k = layers
    H, W = gray.shape
    res = []
    # glazing lines are black; grey hatch/furniture stays out (on upsampled low-res rasters thin lines are grey)
    if lowres:  # off the walls' anti-aliased rims (two rims of a thin wall would pair up as a glazing strip)
        thinl = (ink & (cv2.dilate(wall, np.ones((5, 5), np.uint8)) == 0)).astype(np.uint8)
    else:
        thinl = (dark & (wall == 0)).astype(np.uint8)
    minlen = max(4 * k, int(0.35 * px_per_m) if px_per_m else 4 * k)
    doors_xy = [list(b) for b in extra_boxes]
    for axis in ("h", "v"):
        door_t = doors_xy if axis == "h" else [[b[1], b[0], b[3], b[2]] for b in doors_xy]
        t = thinl if axis == "h" else thinl.T.copy()
        wl = wall if axis == "h" else wall.T.copy()
        # long straight lines along the axis
        lines = cv2.morphologyEx(t, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (minlen, 1)))
        # strips: lines that pair up across about one wall thickness. Close across the axis by the max wall thickness
        tmax = int(max(6 * k, 0.65 * px_per_m)) if px_per_m else 9 * k
        band = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, tmax)))
        band = cv2.morphologyEx(band, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (minlen, 1)))
        n, lab, st, _ = cv2.connectedComponentsWithStats(band, 4)
        for i in range(1, n):
            x, y, w, h, a = st[i]
            if h < 2 * lw + 2 or h > tmax + 2 * lw or w < minlen:
                continue
            # count the distinct lines across the strip at its middle third
            cols = lines[y:y + h, x + w // 3:x + 2 * w // 3]
            prof = cols.mean(1) > 0.6
            nl = int(np.sum(np.diff(np.r_[0, prof.astype(np.int8)]) == 1))
            if nl < 2:
                continue
            # fill between the lines must be light (white glazing), not a hatched or solid band
            mid = t[y:y + h, x + w // 3:x + 2 * w // 3]
            if mid.mean() > 0.6:
                continue
            # ... and not a solid wall: the anti-aliased fringes of a thin wall on an upsampled raster pair up too
            if wl[y:y + h, x + w // 3:x + 2 * w // 3].mean() > 0.15:
                continue
            # solid piers of about the strip's depth at both ends (wall pieces or the end of another strip)
            def pier(x0, x1):
                x0, x1 = max(0, x0), min(wl.shape[1], x1)
                if x1 <= x0:
                    return 0.0
                blk = wl[y + 1:y + h - 1, x0:x1]
                return float(blk.any(axis=1).mean()) if blk.size else 0.0
            g = 3 * lw + 6
            pl, pr = pier(x - g, x + 2), pier(x + w - 2, x + w + g)
            side_panel = False
            if min(pl, pr) < 0.6:
                # a glazed side panel (vision panel) beside a door: a pier at one end, the door opening at the other
                if max(pl, pr) < 0.6 or not door_t:
                    continue
                ex = x + w if pl >= 0.6 else x  # the open end
                yc = y + h / 2
                if not any(b[0] - g <= ex <= b[2] + g and b[1] - g <= yc <= b[3] + g for b in door_t):
                    continue
                side_panel = True
            # depth of the wall beside the strip ~ strip depth (walls a little thicker than the strip are fine)
            if axis == "h":
                bx = [x, y, x + w, y + h]
            else:
                bx = [y, x, y + h, x + w]
            res.append({"bbox": [float(v) for v in bx], "axis": axis, "lines": nl,
                        "score": 0.6 + 0.2 * (nl >= 3) + 0.2 * (min(pl, pr) > 0.9), **({"side_panel": True}
                                                                                         if side_panel else {})})
    inside, f = _inside(wall, [r["bbox"] for r in res] + list(extra_boxes), px_per_m, k)
    # exterior: looking out from the strip on one side, no wall is met before the edge of the sheet
    block = cv2.resize(wall * 255, (W // f, H // f), interpolation=cv2.INTER_AREA) > 0
    for b in [r["bbox"] for r in res] + list(extra_boxes):  # glazing and door swings block the view too
        block[int(b[1] / f):int(b[3] / f) + 1, int(b[0] / f):int(b[2] / f) + 1] = True
    for r in res:
        x0, y0, x1, y1 = (v / f for v in r["bbox"])
        sides = []
        for sgn in (-1, 1):
            free = 0
            for t in (0.3, 0.5, 0.7):  # three parallel rays across the strip's length
                if r["axis"] == "h":
                    c = int(x0 + t * (x1 - x0))
                    ray = block[:max(0, int(y0) - 2), c][::-1] if sgn < 0 else block[int(y1) + 3:, c]
                else:
                    c = int(y0 + t * (y1 - y0))
                    ray = block[c, :max(0, int(x0) - 2)][::-1] if sgn < 0 else block[c, int(x1) + 3:]
                # skip the rest of this wall (piers beside the strip are not "met"): start past 2 strip depths
                skip = int(2 * (y1 - y0 if r["axis"] == "h" else x1 - x0)) + 2
                free += not ray[skip:].any()
            sides.append(free == 3)
            # or: just past the outer face lies outside the footprint
            dpt = (y1 - y0 if r["axis"] == "h" else x1 - x0) + 3
            px, py = ((x0 + x1) / 2, (y0 - dpt if sgn < 0 else y1 + dpt)) if r["axis"] == "h" else \
                ((x0 - dpt if sgn < 0 else x1 + dpt), (y0 + y1) / 2)
            if not (0 <= int(py) < inside.shape[0] and 0 <= int(px) < inside.shape[1]) or not inside[int(py), int(px)]:
                sides[-1] = True
        r["exterior"] = bool(any(sides))
    res.sort(key=lambda d: (round(d["bbox"][1] / max(1, H / 40)), d["bbox"][0]))
    return res, inside, f


def find_windows(image, px_per_m=None, exterior_only=True) -> list[list[float]]:
    """Pixel boxes of the windows (each glazed panel between wall piers is one window)."""
    r = detect_openings(image, px_per_m)
    return [d["bbox"] for d in r["windows"] + ([] if exterior_only else r["internal_glazing"])]


# -------------------------------------------------------------------------------------------- sheet module API
def detect(meta) -> float:
    """Not a sheet type of its own: bp/sheets/arch.py routes door / window questions here."""
    from bp import sheets

    return 0.5 * sheets.kw_score(meta, "arch")


def intent(question: str) -> str | None:
    q = question.lower()
    d = re.search(r"\bdoor(s|way|ways)?\b|\bovi|\bovet|\btür", q)
    w = re.search(r"\bwindows?\b|\bikkun|\bfenster", q)
    if not re.search(r"how many|count|number|quantity|total|list|montako|kuinka|anzahl|wie viele", q):
        return None
    return "doors_windows" if d and w else "doors" if d else "windows" if w else None


def _pdf_scale(meta):
    """px per metre on meta["image"] for a PDF page: printed ratio (1:200, 1 : 50, 1/4" = 1'-0") from the page text
    and the page's physical size. None when the page has no ratio or more than one different ratio."""
    path = str(meta.get("path") or "")
    if not path.lower().endswith(".pdf"):
        return None
    t = f"{meta.get('scale') or ''}\n{meta.get('text') or ''}"
    ratios = {int(m) for m in re.findall(r"\b1\s*:\s*(\d{2,4})\b", t)}
    for a, b in re.findall(r"(\d+)/(\d+)\"\s*=\s*1'\s*-?\s*0\"", t):
        ratios.add(round(12 * int(b) / int(a)))
    for a in re.findall(r"\b(\d)\"\s*=\s*1'\s*-?\s*0\"", t):
        ratios.add(round(12 / int(a)))
    ratios = {r for r in ratios if 10 <= r <= 2000}
    if len(ratios) != 1:
        return None
    try:
        import pymupdf

        pg = pymupdf.open(path)[int(meta.get("page") or 0)]
    except Exception:  # noqa: BLE001
        return None
    paper_m = max(pg.rect.width, pg.rect.height) / 72 * 0.0254
    return max(meta["w"], meta["h"]) / paper_m / ratios.pop()


def _scale(meta):
    """px per metre on meta["image"]: the PDF page's printed ratio, else arch's scale reader."""
    s = _pdf_scale(meta)
    if s:
        return s
    try:
        from bp.sheets import arch

        sc = arch.scale(meta)
        return sc["px_per_m"] if sc else None
    except Exception as e:  # noqa: BLE001
        log.info("openings: no scale (%s)", e)
        return None


def _work_image(meta, ppm):
    """(image path, px_per_m on it, factor vs meta image): a vector PDF page is re-rendered when the stored raster is
    too coarse for door swings (target ~TARGET_PX_PER_M, or ~12000 px on the long side without a scale)."""
    img, path = meta["image"], str(meta.get("path") or "")
    W, H = meta.get("w") or 0, meta.get("h") or 0
    need = (TARGET_PX_PER_M / ppm) if ppm else (12000 / max(1, W, H))
    if not path.lower().endswith(".pdf") or need < 1.3:
        return img, ppm, 1.0
    try:
        import pymupdf

        pg = pymupdf.open(path)[int(meta.get("page") or 0)]
        long_pt = max(pg.rect.width, pg.rect.height)
        target = min(MAX_SIDE, max(W, H) * need)
        zoom = target / long_pt
        out = Path(img).with_name(f"openings_p{meta.get('page') or 0}_{int(target)}.png")
        if not out.exists():
            pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, colorspace=pymupdf.csGRAY).save(str(out))
        f = target / max(W, H)
        return str(out), (ppm * f if ppm else None), f
    except Exception as e:  # noqa: BLE001
        log.warning("openings: PDF re-render failed: %s", e)
        return img, ppm, 1.0


# The CubiCasa detector on a big sheet is the slow half of a first door question on the CPU-only demo VM (139 MP school
# plan: swing reading ~22 s, detector ~40 s on 4 vCPU). When the swing reading stands on its own (vector swings, or a
# full-resolution raster with doors), the answer goes out without it and the detector runs right after, in the
# background, as the sanity check it is; its verdict (cv_ok) is applied to the cached reading for later questions.
DEFER_YOLO = os.environ.get("BP_OPENINGS_DEFER_YOLO", "1") == "1"
YOLO_WAIT_S = 40.0  # an answer that needs the deferred detector waits this long for it
_inflight_lock = __import__("threading").Lock()
_inflight: dict = {}


def analyse_meta(meta) -> dict:
    """detect_openings() for an upload, cached in meta["openings"] and on disk next to the page image. Questions
    asked at once on the same sheet share one reading (the first computes, the others wait for it)."""
    if "openings" in meta:
        return meta["openings"]
    from concurrent.futures import Future

    ppm = _scale(meta)
    img, wppm, f = _work_image(meta, ppm)
    st = os.stat(img)
    key = hashlib.sha1(f"{img}|{st.st_size}|{st.st_mtime}|{wppm}|v2".encode()).hexdigest()[:12]
    cf = Path(meta["image"]).with_name(f"openings_{key}.json")
    with _inflight_lock:
        fut = _inflight.get(str(cf))
        owner = fut is None
        if owner:
            fut = _inflight[str(cf)] = Future()
    if not owner:
        res = fut.result()
    else:
        try:
            res = _analyse_uncached(meta, ppm, img, wppm, f, cf)
            fut.set_result(res)
        except BaseException as e:
            fut.set_exception(e)
            raise
        finally:
            with _inflight_lock:
                _inflight.pop(str(cf), None)
    meta["openings"] = res
    return res


def _judge(res, meta):
    """cv_ok: whether the swing / strip reading stands (else the detector's or the vision tiles' answer is used)."""
    yd = len((res.get("yolo") or {}).get("doors") or [])
    if res.get("vector"):
        res["low_res"] = False  # the doors come from the vector drawing, whatever the raster's resolution
    # swing reading implausibly short of the detector (unfilled double-line walls, grey swings): treat as low-res
    res["cv_ok"] = bool(res.get("vector")) or not res["low_res"] and not (yd >= 10 and len(res["doors"]) < 0.6 * yd) \
        and not (len(res["doors"]) < 3 and yd > len(res["doors"]))  # 1-2 swings on a scan: not a reading
    # plausibility: a floor plan has at least ~1 door per 100 m2 of building (bbox area, needs a scale)
    if res["cv_ok"] and res.get("px_per_m") and not res.get("vector"):
        if "footprint_bbox_m2" not in res:
            try:
                ext = building_bbox(_gray(meta["image"]))
            except Exception:  # noqa: BLE001
                ext = None
            if ext:
                res["footprint_bbox_m2"] = round((ext[2] - ext[0]) * meta["w"] * (ext[3] - ext[1]) * meta["h"]
                                                 / res["px_per_m"] ** 2)
        area = res.get("footprint_bbox_m2")
        if area and len(res["doors"]) < area / 100 * 0.5:  # bbox overstates an L / T footprint: allow half
            res["cv_ok"] = False
    if not res["cv_ok"] and "haiku" not in res and os.environ.get("BP_OPENINGS_HAIKU", "1") == "1":
        try:
            res["haiku"] = haiku_openings(meta["image"])
        except Exception as e:  # noqa: BLE001
            log.warning("openings: vision tiles failed: %s", e)


def _write(cf, res):
    try:
        cf.write_text(json.dumps(res))
    except OSError:
        pass


def _finish_yolo(meta, ppm, res, cf, early=None):
    """The deferred detector run (background thread), inside the process memory budget; updates res in place.
    early: the Future of a run already started (small rasters), waited for instead of a second run."""
    from bp import memgate

    try:
        if early is not None:
            y = early.result()
        else:
            with memgate.hold(memgate.cost(int(meta.get("w") or 0) * int(meta.get("h") or 0), "answer"),
                              tag=memgate.tag_for(meta.get("image") or ""), label="openings detector"):
                y = yolo_openings(meta["image"], ppm)
    except Exception as e:  # noqa: BLE001
        log.warning("openings: deferred detector failed: %s", e)
        y = None
    if y is not None:
        res["yolo"] = y
    res.pop("yolo_pending", None)
    _judge(res, meta)
    _write(cf, res)


def _analyse_uncached(meta, ppm, img, wppm, f, cf) -> dict:
    res = None
    if cf.exists():
        try:
            res = json.loads(cf.read_text())
        except json.JSONDecodeError:
            res = None
    if res is not None:
        if res.get("yolo_pending"):  # the process ended before the deferred detector run finished: run it now
            __import__("threading").Thread(target=_finish_yolo, args=(meta, ppm, res, cf), daemon=True).start()
        return res
    # a small raster (a screenshot, a ~2000 px JPG) always needs the detector (its swing reading is low-res) and the
    # detector on its ~5000 px resample takes ~35 s on the 4-core VM: start it now, next to the swing reading (~7 s)
    early = None
    if not str(meta.get("path") or "").lower().endswith(".pdf") and 0 < max(meta.get("w") or 0, meta.get("h") or 0) < 4000:
        from concurrent.futures import ThreadPoolExecutor

        ex = ThreadPoolExecutor(1, thread_name_prefix="openings-yolo")
        early = ex.submit(yolo_openings, meta["image"], ppm)
        ex.shutdown(wait=False)
    r = detect_openings(img, wppm)
    W, H = r["size"]

    def norm(items):
        return [{"bbox": [d["bbox"][0] / W, d["bbox"][1] / H, d["bbox"][2] / W, d["bbox"][3] / H],
                 **{k: d[k] for k in ("leaves", "kind", "score", "exterior", "lines") if k in d}} for d in items]
    res = {"doors": norm(r["doors"]), "windows": norm(r["windows"]), "internal_glazing": norm(r["internal_glazing"]),
           "low_res": bool(r.get("low_res")), "render_factor": f,
           "px_per_m": (wppm or r.get("px_per_m_estimated") or 0) / f or None,
           "scale_from": "printed scale" if wppm else "median door swing = 0.9 m" if r.get("px_per_m_estimated") else None,
           "solid_walls": None}
    # vector PDF page: door swings read from the drawing's own curves are exact; they replace the raster swings
    # (leaf-only / folding doors found on the raster are kept when no vector swing covers them)
    if str(meta.get("path") or "").lower().endswith(".pdf"):
        try:
            vd = vector_doors(meta["path"], meta.get("page") or 0)
        except Exception as e:  # noqa: BLE001
            log.warning("openings: vector doors failed: %s", e)
            vd = None
        if vd and len(vd["doors"]) >= 3:
            vb = [d["bbox"] for d in vd["doors"]]

            def covered(b):
                cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                return any(v[0] - 0.003 <= cx <= v[2] + 0.003 and v[1] - 0.003 <= cy <= v[3] + 0.003 for v in vb)
            extra = [d for d in res["doors"] if d.get("kind") == "leaf" and not covered(d["bbox"])] \
                if not res["low_res"] and len(vb) >= 20 else []  # small sheets: leader lines look like leaves
            res["doors"] = [{"bbox": d["bbox"], "leaves": d["leaves"], "kind": "vector-swing"}
                            for d in vd["doors"]] + extra
            res["doors"].sort(key=lambda d: (round(d["bbox"][1] * 40), d["bbox"][0]))
            res["vector"] = {"swing_doors": len(vd["doors"]), "arcs": vd["arcs"], "raster_leaf_doors": len(extra)}
    # the symbol detector always runs (free; ~5 s on a GPU, ~40 s for a 139 MP sheet on the 4-core VM): fallback for
    # low-res rasters and a sanity check. A reading that stands without it answers first (DEFER_YOLO)
    defer = DEFER_YOLO and (bool(res.get("vector")) or (not res["low_res"] and len(res["doors"]) >= 3))
    if defer:
        res["yolo_pending"] = True
    else:
        try:
            res["yolo"] = early.result() if early is not None else yolo_openings(meta["image"], ppm)
        except Exception as e:  # noqa: BLE001
            log.warning("openings: detector fallback failed: %s", e)
    _judge(res, meta)
    _write(cf, res)
    if defer:
        __import__("threading").Thread(target=_finish_yolo, args=(meta, ppm, res, cf, early), daemon=True).start()
    return res


# CubiCasa YOLO fallback for low-res rasters. Measured on the 2000 px school screenshot (resampled to 40 px/m,
# door >= 0.3, window >= 0.55, boxes inside the building): doors 126 found vs 128 by hand (P 0.81, R 0.80: misses
# and false boxes nearly cancel), windows ~76 vs 68 (P ~0.88, R 0.99). 53 / 70 px/m were worse for doors.
YOLO_PX_PER_M = 40.0
YOLO_THR = {"door": 0.3, "window": 0.55}
YOLO_PRECISION = {"door": 0.81, "window": 0.88}


def building_bbox(gray) -> list[float] | None:
    """Normalised bbox of the drawn building on a raster of any resolution: the big blobs of solid wall or colour fill
    (anything well off white, opened so that 1-px lines, text and the sheet frame drop out)."""
    import cv2

    g = _gray(gray)
    s = 1500 / max(g.shape)
    if s < 1:
        g = cv2.resize(g, (round(g.shape[1] * s), round(g.shape[0] * s)), interpolation=cv2.INTER_AREA)
    m = cv2.morphologyEx((g < 235).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m = cv2.dilate(m, np.ones((15, 15), np.uint8))  # join the wings / modules of one building
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    if n < 2:
        return None
    H, W = m.shape
    # a building blob is big both ways (a notes / disclaimer paragraph is wide but short)
    ok = [i for i in range(1, n) if st[i, 2] >= 0.1 * W and st[i, 3] >= 0.1 * H]
    if not ok:
        return None
    big = max(st[i, cv2.CC_STAT_AREA] for i in ok)
    keep = [i for i in ok if st[i, cv2.CC_STAT_AREA] >= 0.25 * big]
    x0 = min(st[i, 0] for i in keep) / W
    y0 = min(st[i, 1] for i in keep) / H
    x1 = max(st[i, 0] + st[i, 2] for i in keep) / W
    y1 = max(st[i, 1] + st[i, 3] for i in keep) / H
    return [x0, y0, x1, y1]


_ROOMWORD = re.compile(r"^(?:\d{1,4}\s*(?:sf|sq\.?\s*ft|m2|m²)|sf|m2|m²)$", re.I)


def main_plan(meta) -> list[float] | None:
    """Normalised bbox of the floor plan(s) a door / window count is about, when the sheet also carries other drawings
    (a 3D / isometric view, a key plan, details, a title block): the large drawing blobs that carry room names or
    area tags. None when that does not single anything out (one drawing, or no readable room names)."""
    import cv2

    from bp.sheets import rooms as rooms_mod

    try:
        g = _gray(meta["image"])
    except Exception:  # noqa: BLE001
        return None
    s = 1500 / max(g.shape)
    if s < 1:
        g = cv2.resize(g, (round(g.shape[1] * s), round(g.shape[0] * s)), interpolation=cv2.INTER_AREA)
    H, W = g.shape
    paper = float(np.percentile(g[::3, ::3], 90))  # grey / yellowed scan paper is not ink
    m = cv2.morphologyEx((g < min(235.0, paper - 20)).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m = cv2.dilate(m, np.ones((15, 15), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    blobs = [i for i in range(1, n) if st[i, 2] >= 0.08 * W and st[i, 3] >= 0.08 * H]
    if len(blobs) < 2:
        return None

    def ortho_frac(i, skew=False):  # a plan is drawn square; a 3D / isometric view is not
        x, y, w, h = st[i, :4]
        e = cv2.Canny(g[y:y + h, x:x + w], 50, 150)
        ls = cv2.HoughLinesP(e, 1, np.pi / 180, 30, minLineLength=max(15, min(w, h) // 20), maxLineGap=3)
        if ls is None:
            return 1.0
        ls = ls.reshape(-1, 4).astype(float)
        L = np.hypot(ls[:, 2] - ls[:, 0], ls[:, 3] - ls[:, 1])
        a = np.degrees(np.arctan2(np.abs(ls[:, 3] - ls[:, 1]), np.abs(ls[:, 2] - ls[:, 0])))
        ok = (a < 4) | (a > 86)
        if not skew:
            return float(L[ok].sum() / max(1e-6, L.sum()))
        # share of the line length along one oblique direction (an isometric's 30-degree edges)
        h_, _ = np.histogram(a, bins=18, range=(0, 90), weights=L)
        return float((h_[3:15] + h_[4:16]).max() / max(1e-6, L.sum()))

    def oblique(i):  # an isometric / 3D view: few square lines, most along one slant
        return ortho_frac(i) < 0.5 and ortho_frac(i, skew=True) >= 0.4

    def _union(ids):
        return [min(st[i, 0] for i in ids) / W, min(st[i, 1] for i in ids) / H,
                max(st[i, 0] + st[i, 2] for i in ids) / W, max(st[i, 1] + st[i, 3] for i in ids) / H]

    try:
        words = meta.get("words") or rooms_mod._words(meta["image"], None, meta)
    except Exception:  # noqa: BLE001
        return None
    names = []
    for w in words:
        t = str(w.get("text", "")).strip(" .,:;()").lower()
        if (t in rooms_mod.ROOM_WORDS and len(t) >= 3 and t not in ("and", "of")) or _ROOMWORD.match(t) or \
                re.fullmatch(r"(bed|bath|class|store|office|toilet|kitchen|corridor|closet|dorm|living|dining)\w*", t):
            names.append(((w["bbox"][0] + w["bbox"][2]) / 2, (w["bbox"][1] + w["bbox"][3]) / 2))
    score = {}
    for i in blobs:
        x, y, w, h = st[i, :4]
        score[i] = sum(1 for cx, cy in names if x <= cx * W <= x + w and y <= cy * H <= y + h
                       and lab[min(H - 1, int(cy * H)), min(W - 1, int(cx * W))] == i)
    best = max(score.values())
    if best < 4:
        # no readable room names (a rough scan): keep the square-drawn drawings, drop big skewed ones (3D views)
        area = {i: int(st[i, 2]) * int(st[i, 3]) for i in blobs}
        bigs = [i for i in blobs if area[i] >= 0.3 * max(area.values())]
        of = {i: (ortho_frac(i), ortho_frac(i, skew=True)) for i in bigs}
        log.info("openings: main plan by drawing direction (square, oblique): %s",
                 {int(i): (round(a, 2), round(b, 2)) for i, (a, b) in of.items()})
        # only a clearly oblique drawing (an isometric: most lines along one slant) beside square ones is dropped
        sq = {i: not (a < 0.5 and b >= 0.4) for i, (a, b) in of.items()}
        if all(sq.values()) or not any(a >= 0.85 for a, _ in of.values()):
            return None
        top = max(area[i] for i in bigs if sq[i])
        keep = [i for i in blobs if area[i] >= 0.1 * top and (sq[i] if i in sq else not oblique(i))]
        return _union(keep)
    keep = [i for i in blobs if score[i] >= max(2, 0.25 * best)]
    big = max(int(st[i, 2]) * int(st[i, 3]) for i in keep)
    keep += [i for i in blobs if i not in keep and int(st[i, 2]) * int(st[i, 3]) >= 0.3 * big and not oblique(i)]
    if len(keep) == len(blobs):
        return None
    log.info("openings: main plan %s (room words per drawing %s)", [round(v, 3) for v in _union(keep)],
             sorted(score.values(), reverse=True))
    return _union(keep)


def _in_plan(items, box):
    if not box:
        return items
    return [d for d in items if box[0] <= (d["bbox"][0] + d["bbox"][2]) / 2 <= box[2]
            and box[1] <= (d["bbox"][1] + d["bbox"][3]) / 2 <= box[3]]


def yolo_openings(image, px_per_m=None) -> dict:
    """{"doors": [...], "windows": [...]} (normalised boxes, score) from the CubiCasa detector on the raster resampled
    to YOLO_PX_PER_M (without a scale: to 4800 px on the long side), limited to the building's bbox."""
    import tempfile

    from PIL import Image

    from bp.cubicasa.infer import load, predict

    Image.MAX_IMAGE_PIXELS = None
    from bp.sheets.rooms import unmark

    im = image if hasattr(image, "convert") else Image.open(str(image))
    im = im.convert("RGB")
    rgb = np.asarray(im)
    clean = unmark(rgb)  # pen markings on a scan: the detector boxed red / green ticks as doors
    if clean is not rgb:
        im = Image.fromarray(clean)
    W, H = im.size
    f = YOLO_PX_PER_M / px_per_m if px_per_m else 4800 / max(W, H)  # no scale: ~40 px/m on an A2/D sheet
    f = max(0.25, min(f, 10000 / max(W, H)))
    big = im.resize((round(W * f), round(H * f)), Image.LANCZOS)
    global _YOLO
    if _YOLO is None:
        _YOLO = load("cache/cubicasa/weights/best.pt")
    with tempfile.NamedTemporaryFile(suffix=".png") as tf:
        big.save(tf.name)
        dets = predict(_YOLO, tf.name, "t1024", conf=0.15)
    ext = building_bbox(np.asarray(im.convert("L")))
    out = {"doors": [], "windows": [], "factor": f, "px_per_m": px_per_m, "extent": ext}
    for cls, sc, b in dets:
        if cls not in YOLO_THR or sc < YOLO_THR[cls]:
            continue
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if ext and not (ext[0] - 0.01 <= cx <= ext[2] + 0.01 and ext[1] - 0.01 <= cy <= ext[3] + 0.01):
            continue
        out[cls + "s"].append({"bbox": [float(v) for v in b], "score": round(float(sc), 3)})
    for k in ("doors", "windows"):
        out[k].sort(key=lambda d: (round(d["bbox"][1] * 40), d["bbox"][0]))
    return out


_YOLO = None

HAIKU_PROMPT = """This is one tile ({w}x{h} px) of an architectural floor plan. Mark every DOOR and every WINDOW in it.
Door: a door leaf with its swing arc (quarter circle), a folding/bifold door, or a sliding door; a double door
(two leaves in one opening) is ONE door; a wardrobe/closet door counts as a door. Window: a glazed panel in an outside
wall (thin parallel lines or a small rectangle interrupting the wall); several panels side by side between solid
piers count separately. Ignore furniture, stairs, text and anything cut off at the tile edge by more than half.
JSON only: {{"doors": [[x0,y0,x1,y1], ...], "windows": [[x0,y0,x1,y1], ...]}} in this tile's pixels."""


def haiku_openings(image, ext=None, grid=3, model="haiku", max_side=1400) -> dict:
    """Doors / windows read by Claude vision on a grid x grid split of the building bbox (tiles do not overlap, so
    each box belongs to exactly one tile: no duplicates). Cached per image + tile. ~$0.002-0.004 per tile."""
    from PIL import Image

    from bp.generic import llm

    Image.MAX_IMAGE_PIXELS = None
    im = image if hasattr(image, "convert") else Image.open(str(image))
    im = im.convert("RGB")
    W, H = im.size
    ext = ext or building_bbox(np.asarray(im.convert("L"))) or [0, 0, 1, 1]
    X0, Y0, X1, Y1 = ext[0] * W, ext[1] * H, ext[2] * W, ext[3] * H
    h = hashlib.sha1(np.asarray(im.resize((64, 64))).tobytes()).hexdigest()[:12]
    cache = Path("cache/openings")
    cache.mkdir(parents=True, exist_ok=True)
    out = {"doors": [], "windows": [], "cost_usd": 0.0, "tiles": grid * grid}

    def read(cell):  # one tile: (tile origin, scale, reply, cost of a new call)
        gx, gy = cell
        tx0, tx1 = X0 + (X1 - X0) * gx / grid, X0 + (X1 - X0) * (gx + 1) / grid
        ty0, ty1 = Y0 + (Y1 - Y0) * gy / grid, Y0 + (Y1 - Y0) * (gy + 1) / grid
        tile = im.crop((int(tx0), int(ty0), int(tx1), int(ty1)))
        s = min(3.0, max_side / max(tile.size))  # small tiles are upscaled: swings must be visible
        if abs(s - 1) > 0.05:
            tile = tile.resize((round(tile.width * s), round(tile.height * s)), Image.LANCZOS)
        cf = cache / f"{h}_{grid}_{gx}{gy}_{model}_{tile.width}.json"
        if cf.exists():
            return tx0, ty0, s, json.loads(cf.read_text()), 0.0
        r = llm.ask(HAIKU_PROMPT.format(w=tile.width, h=tile.height), [tile], model=model,
                    tag="openings-tiles", timeout=120)
        d = llm.parse_json(r["text"]) or {}
        d = d if isinstance(d, dict) else {}
        d["cost_usd"] = r.get("cost_usd", 0.0)
        if r.get("text"):
            cf.write_text(json.dumps(d))
        return tx0, ty0, s, d, d["cost_usd"]

    from concurrent.futures import ThreadPoolExecutor

    # the tiles at once (they wait on the API; one after the other was ~30 s of a first question on a screenshot)
    with ThreadPoolExecutor(grid * grid) as ex:
        reads = list(ex.map(read, [(gx, gy) for gy in range(grid) for gx in range(grid)]))
    for tx0, ty0, s, d, c in reads:
        out["cost_usd"] += c
        for k in ("doors", "windows"):
            for b in d.get(k) or []:
                if not (isinstance(b, list) and len(b) == 4):
                    continue
                try:
                    bx = [float(v) for v in b]
                except (TypeError, ValueError):
                    continue
                gb = [(tx0 + bx[0] / s) / W, (ty0 + bx[1] / s) / H, (tx0 + bx[2] / s) / W, (ty0 + bx[3] / s) / H]
                out[k].append({"bbox": gb})
    return out


def _ev(b, label):
    return {"kind": "box", "page": 0, "bbox": [round(float(v), 5) for v in b], "label": label, "value": 1}


# Closet / wardrobe / cupboard doors are not doors (Stoa's convention, as in the CubiCasa5k gold, where wardrobe
# swings belong to the "FixedFurniture Closet" symbol and only Door objects count): they are reported separately.
CLOSET_LEAF_M = 0.55       # a leaf narrower than this is a cupboard / wardrobe leaf (room doors are >= ~0.7 m)
CLOSET_DEPTH_M = 0.8       # the space a closet door opens into is shallower than this (WC cubicles ~0.85 m) ...
CLOSET_AREA_M2 = 2.0       # ... and smaller than this
CLOSET_WORDS = re.compile(r"^(vh|var|var\.|cl|clo|clos|closet|wardrobe|ward|cupboard|cpd|cupbd|linen|lin)$", re.I)


def closet_doors(meta, doors, px_per_m=None) -> dict:
    """{index in doors: reason} for the doors that open a closet / wardrobe / cupboard rather than a room.
    doors: [{"bbox": normalised, "leaves"?}]. Cues: a leaf < CLOSET_LEAF_M; a door box touching a free space
    (bp/sheets/rooms.py segmentation) shallower than CLOSET_DEPTH_M and smaller than CLOSET_AREA_M2; a closet label
    (VH, VAR, CL, closet, wardrobe, cupboard) within 1 m of the door."""
    if not doors or not meta.get("image"):
        return {}
    from bp.sheets import rooms as rooms_mod

    try:
        seg = rooms_mod._cached(meta)
    except Exception as e:  # noqa: BLE001
        log.info("closet check: no room segmentation (%s)", e)
        seg = None
    W, H = meta.get("w") or 0, meta.get("h") or 0
    ppm = (seg or {}).get("px_per_m") or px_per_m
    if not (W and H and ppm):
        return {}
    lab = f = None
    bands = []
    small_ids = {}
    if seg and seg.get("_lab"):
        lab, f = seg["_lab"]["lab"], seg["_lab"]["f"]
        wppm = ppm * f / 2  # stats on every 2nd work pixel
        sub = lab[::2, ::2]
        n = int(sub.max()) + 1
        ys, xs = np.nonzero(sub)
        ls = sub[ys, xs]
        cnt = np.bincount(ls, minlength=n)
        mnx, mny = np.full(n, 1 << 30), np.full(n, 1 << 30)
        mxx, mxy = np.full(n, -1), np.full(n, -1)
        np.minimum.at(mnx, ls, xs)
        np.minimum.at(mny, ls, ys)
        np.maximum.at(mxx, ls, xs)
        np.maximum.at(mxy, ls, ys)
        del ys, xs, ls
        for i in np.nonzero(cnt)[0].tolist():
            ww, hh = mxx[i] - mnx[i] + 1, mxy[i] - mny[i] + 1
            area = cnt[i] / wppm ** 2
            if 0.35 <= min(hh, ww) / wppm < CLOSET_DEPTH_M and 0.2 <= area < CLOSET_AREA_M2:  # not a hollow-wall sliver
                small_ids[i] = (min(hh, ww) / wppm, float(area))
        # a closet has one way in: a small space between two doorway bands is a door recess / lobby, not a closet
        nband = dict.fromkeys(small_ids, 0)
        sh, sw = lab.shape
        bands = seg.get("bands") or [dd["box"] for dd in seg.get("doors") or []]
        for bx, by, bw, bh in bands:
            ring = lab[max(0, by - 2):min(sh, by + bh + 2), max(0, bx - 2):min(sw, bx + bw + 2)]
            for i in set(np.unique(ring).tolist()) & set(small_ids):
                nband[i] += 1
        small_ids = {i: v for i, v in small_ids.items() if nband[i] <= 1}
    words = []
    try:
        words = meta.get("words") or rooms_mod._words(meta["image"], None, meta)
    except Exception:  # noqa: BLE001
        words = []
    cw = [w for w in words if CLOSET_WORDS.match(str(w.get("text", "")).strip(" .,:;()"))]
    out = {}
    for k, d in enumerate(doors):
        x0, y0, x1, y1 = d["bbox"]
        side_m = max((x1 - x0) * W, (y1 - y0) * H) / ppm
        leaf = side_m / (2 if d.get("leaves") == 2 else 1)
        why = None
        if 0.2 < leaf < CLOSET_LEAF_M:
            why = f"leaf {leaf:.2f} m (< {CLOSET_LEAF_M} m)"
        if why is None and lab is not None and small_ids:
            sh, sw = lab.shape
            pad = 0.1 * ppm * f
            a0, b0 = max(0, int(x0 * W * f - pad)), max(0, int(y0 * H * f - pad))
            a1, b1 = min(sw, int(x1 * W * f + pad) + 1), min(sh, int(y1 * H * f + pad) + 1)
            # the space must lie across this door's own doorway band (not behind a wall stub next to it)
            mine = [(bx, by, bw, bh) for bx, by, bw, bh in bands
                    if bx < a1 and bx + bw > a0 and by < b1 and by + bh > b0]
            ids = set()
            for bx, by, bw, bh in mine:
                ring = lab[max(0, by - 2):min(sh, by + bh + 2), max(0, bx - 2):min(sw, bx + bw + 2)]
                ids |= set(np.unique(ring).tolist())
            if not mine:
                ids = set(np.unique(lab[b0:b1, a0:a1]).tolist())
            ids &= set(small_ids)
            if ids:
                dep, ar = small_ids[min(ids, key=lambda i: small_ids[i][1])]
                why = f"opens into a {dep:.2f} m deep, {ar:.1f} m² space"
        if why is None and cw:
            r = 1.0 * ppm
            cx, cy = (x0 + x1) / 2 * W, (y0 + y1) / 2 * H
            for w in cw:
                wx, wy = (w["bbox"][0] + w["bbox"][2]) / 2 * W, (w["bbox"][1] + w["bbox"][3]) / 2 * H
                if abs(wx - cx) < r + (x1 - x0) * W / 2 and abs(wy - cy) < r + (y1 - y0) * H / 2:
                    why = f"labelled '{w['text']}'"
                    break
        if why:
            out[k] = why
    return out


def _side_panels(meta, windows) -> list[dict]:
    """Glazed side panels beside doors (vision panels: a short glazed piece between a pier and a door opening) from
    the room segmentation's wall gaps (bp/sheets/rooms.py), normalised boxes, minus those a window box already covers.
    For the detector path: its window class finds the windows in outside walls but hardly any of these."""
    from bp.sheets import rooms as rooms_mod

    W, H = meta.get("w") or 0, meta.get("h") or 0
    if not (W and H):
        return []
    ppm0 = (meta.get("openings") or {}).get("px_per_m")
    if "_rooms_seg" not in meta and (not ppm0 or W * H * (rooms_mod.WORK_PPM / ppm0) ** 2 > 60e6):
        return []  # the room segmentation would take too long here (a 10000 px sheet at 23 px/m: ~300 MP of work)
    try:
        seg = rooms_mod._cached(meta)
    except Exception as e:  # noqa: BLE001
        log.info("side panels: no room segmentation (%s)", e)
        return []
    ppm = seg.get("px_per_m") or 0
    if not ppm:
        return []
    mx, my = 0.15 * ppm / W, 0.15 * ppm / H

    def near(a, b):
        return a[0] - mx <= b[2] and b[0] - mx <= a[2] and a[1] - my <= b[3] and b[1] - my <= a[3]
    out = []
    for p in seg.get("side_panels") or []:
        if not 0.35 <= p["length_m"] <= 1.0:
            continue
        b = [p["bbox"][0] / W, p["bbox"][1] / H, p["bbox"][2] / W, p["bbox"][3] / H]
        if any(near(b, w["bbox"]) for w in windows) or any(near(b, o["bbox"]) for o in out):
            continue
        out.append({"bbox": b, "kind": "side-panel", "score": 0.5})
    return out


_CL = r"(?:closet|wardrobe|cupboard|komero|vaatekaap)\w*"


def closet_mode(question: str) -> str:
    """"exclude" (default, Stoa's convention), "include" (the question / a clarify pick asks to count them too) or
    "only" (the question counts the closet doors themselves)."""
    q = question.lower()
    if re.search(r"\(closets: with\b|\b(?:includ\w*|with|plus|and|also|count\w*)\s+(?:the\s+|all\s+)?" + _CL, q) \
            or re.search(_CL + r"\s+(?:doors?\s+)?(?:included|too|as well)", q):
        return "include"
    if re.search(r"\b(?:how many|number of|count)\s+(?:the\s+)?" + _CL, q):
        return "only"
    return "exclude"


CLOSET_VLM_MAX = 40  # doors on the plan up to which a vision read of the room names beside each door is affordable
CLOSET_NAME = re.compile(r"\b(closet|clo|clos|cl|wardrobe|ward|cupboard|cpd|cupbd|linen|lin|w\.?i\.?c|vh|var|"
                         r"komero|vaatehuone|schrank)\b", re.I)
WET_NAME = re.compile(r"\b(wc|toilet|bath|shower|lav|wash|restroom)", re.I)
CLOSET_SF = 25.0  # a space printed smaller than this (2.3 m²) is a closet whatever its name (MECH 9 SF, LINEN 12 SF)
VCLOSET_PROMPT = """This is an architectural floor plan. Red numbered boxes mark door symbols found on it (boxes 1..{n}).
A door connects two spaces. For each box give the name of the SMALLER of the two spaces the door connects, as printed
on the plan (e.g. "CLOSET", "MECH", "BATH", "Store", "Corridor"), and that space's printed area if one is printed
next to its name (e.g. "18 SF", "4.5 m2"), else "". Use "" for a name you cannot read; do not guess.
If a box clearly holds no door at all (a piece of equipment, furniture, a symbol or text), give ["NOT A DOOR", ""].
JSON only: {{"1": ["CLOSET", "18 SF"], "2": ["BATH", "51 SF"], ...}}"""


def _printed_m2(t: str):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(sf|sq\.?\s*ft|ft2|ft²|m2|m²|sqm)", t or "", re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return v * 0.092903 if m.group(2).lower().startswith(("s", "f")) and "m" not in m.group(2).lower() else v


def vision_closets(meta, doors, model="haiku") -> tuple[dict, float]:
    """({index: why} for doors whose smaller side is a closet, cost): Claude reads, for each numbered door box on a
    crop of the plan, the printed name (and area) of the smaller space it opens; a closet name (closet, wardrobe,
    cupboard, linen, WIC) or a printed area under CLOSET_SF (not a WC / bath) makes it a closet door. Cached."""
    from PIL import Image, ImageDraw

    from bp.generic import llm

    if not doors or len(doors) > CLOSET_VLM_MAX or not meta.get("image"):
        return {}, 0.0
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(meta["image"]).convert("RGB")
    W, H = im.size
    bx = [min(d["bbox"][0] for d in doors), min(d["bbox"][1] for d in doors),
          max(d["bbox"][2] for d in doors), max(d["bbox"][3] for d in doors)]
    pad = 0.04 * max(bx[2] - bx[0], bx[3] - bx[1]) + 0.01
    box = [max(0.0, bx[0] - pad) * W, max(0.0, bx[1] - pad) * H, min(1.0, bx[2] + pad) * W, min(1.0, bx[3] + pad) * H]
    key = hashlib.sha1((f"{meta['image']}|{W}x{H}|" + json.dumps([[round(v, 4) for v in d["bbox"]] for d in doors])
                        + model).encode()).hexdigest()[:12]
    cf = Path(meta["image"]).with_name(f"openings_closets_{key}.json")
    got, cost = None, 0.0
    if cf.exists():
        try:
            got = json.loads(cf.read_text())
        except json.JSONDecodeError:
            got = None
    if got is None:
        c = im.crop([int(v) for v in box])
        s = min(3.0, 1600 / max(c.size))
        c = c.resize((max(1, int(c.width * s)), max(1, int(c.height * s))), Image.LANCZOS)
        dr = ImageDraw.Draw(c)
        for i, d in enumerate(doors, 1):
            b = d["bbox"]
            r = [(b[0] * W - box[0]) * s, (b[1] * H - box[1]) * s, (b[2] * W - box[0]) * s, (b[3] * H - box[1]) * s]
            dr.rectangle(r, outline=(255, 0, 0), width=2)
            dr.text((r[0] + 2, r[1] + 1), str(i), fill=(255, 0, 0), font_size=18)
        res = llm.ask(VCLOSET_PROMPT.format(n=len(doors)), [c], model=model, tag="openings-closets", think=False)
        cost = res.get("cost_usd", 0.0)
        js = llm.parse_json(res.get("text", ""))
        if not isinstance(js, dict):
            return {}, cost
        got = {k: v for k, v in js.items() if isinstance(v, list) and len(v) == 2}
        try:
            cf.write_text(json.dumps(got))
        except OSError:
            pass
    out = {}
    for i in range(len(doors)):
        v = got.get(str(i + 1))
        if not v:
            continue
        name, area = str(v[0] or "").strip(), str(v[1] or "").strip()
        m2 = _printed_m2(area) or _printed_m2(name)
        if re.fullmatch(r"(?i)not\s*a\s*door", name):
            out[i] = "not a door (equipment or a symbol, read by vision)"
        elif name and CLOSET_NAME.search(name):
            out[i] = f"opens a '{name}{' ' + area if area else ''}' (read by vision)"
        elif m2 is not None and m2 < CLOSET_SF * 0.092903 and not WET_NAME.search(name):
            out[i] = f"opens a {area} {name or 'space'} (smaller than {CLOSET_SF:.0f} SF; read by vision)"
    return out, cost


def _split_closets(meta, doors, px_per_m=None, mode="exclude"):
    """(counted doors, closet doors with "why", not counted), the closet check never failing the answer. mode (see
    closet_mode): include -> closets are counted (still marked), only -> only closets are counted."""
    if mode == "include":
        return list(doors), []
    try:
        cl = closet_doors(meta, doors, px_per_m)
    except Exception as e:  # noqa: BLE001
        log.warning("closet check failed: %s", e)
        cl = {}
    if os.environ.get("BP_OPENINGS_HAIKU", "1") == "1" and 0 < len(doors) <= CLOSET_VLM_MAX:
        try:
            vc, cost = vision_closets(meta, doors)
            meta["_closet_cost"] = meta.get("_closet_cost", 0.0) + cost
            for k, why in vc.items():
                if why.startswith("not a door"):
                    cl[k] = why
                else:
                    cl.setdefault(k, why)
        except Exception as e:  # noqa: BLE001
            log.warning("vision closet check failed: %s", e)
    # boxes that are no door at all (equipment arcs, a detector's half box) leave the count and the closet list
    nd = {k for k, w in cl.items() if w.startswith("not a door")}
    if nd:
        meta["_not_doors"] = [dict(doors[k], why=cl[k]) for k in sorted(nd)]
        keep = [k for k in range(len(doors)) if k not in nd]
        cl = {keep.index(k): w for k, w in cl.items() if k not in nd}
        doors = [doors[k] for k in keep]
    if mode == "only":
        return [dict(doors[k], why=cl[k]) for k in sorted(cl)], [d for k, d in enumerate(doors) if k not in cl]
    return [d for k, d in enumerate(doors) if k not in cl], [dict(d, why=cl[k]) for k in sorted(cl) for d in [doors[k]]]


def _closet_ev(cs, mode="exclude"):
    out = []
    for i, d in enumerate(cs, 1):
        e = _ev(d["bbox"], f"other door {i}: not counted" if mode == "only" else
                f"closet door {i}: not counted ({d['why']})")
        e["value"] = None
        e["on"] = False  # the viewer shows it unticked (not in the sum); a judge can tick it back in
        out.append(e)
    return out


_NOT_ROOM = re.compile(r"\b(this|these|whole|entire|each|every|all|floor|plan|level|sheet|drawing|building|module|"
                       r"storey|story|house|unit|wing|project|page)\b", re.I)


def room_scope(question: str) -> str | None:
    """The room a door question is about ("doors into the Multi-Purpose Hall" -> "Multi-Purpose Hall"), or None."""
    m = None
    for m in re.finditer(r"\b(?:into|in|inside|to|of|for|from|serving|off|onto)\s+(?:the\s+)?([A-Za-z][\w\-' ]{2,60})",
                         question):
        pass
    if not m:
        return None
    ph = re.split(r"[?.,;]| on | at | of this| in this", m.group(1))[0].strip()
    if not ph or _NOT_ROOM.search(ph) or re.fullmatch(r"(?i)(total|all|them|it|there)", ph):
        return None
    return ph


def _answer_room_doors(meta, question, name):
    """Doors into one named room: the doorway openings on that room's outline (bp/sheets/rooms.py segmentation: wall
    gaps closed by a drawn leaf / swing, a double door is one opening), with the door symbols at them as a check."""
    from bp.sheets import rooms as rooms_mod

    try:
        sel, seg = rooms_mod.named_rooms(meta, name)
    except Exception as e:  # noqa: BLE001
        log.warning("openings: room scope failed: %s", e)
        return None
    if not sel:
        if not seg.get("rooms"):
            return None
        names = sorted({r["label"] for r in seg["rooms"] if r["label"]}, key=str.lower)
        # the whole sheet's count would answer another question: ask which room is meant
        return {"answer": None, "confidence": 0.0, "method": f"{METHOD}-room-ask", "evidence": [],
                "cost_usd": seg.get("cost_usd", 0.0),
                "explanation": f"I found no room named '{name}' on this sheet, so I cannot count the doors into it. "
                               f"Rooms I can read: {', '.join(names[:40]) or 'none'}. Which one do you mean, or should "
                               f"I count every door on the sheet?"}
    W, H = meta.get("w") or 0, meta.get("h") or 0
    if not (W and H):
        return None
    room = max(sel, key=lambda r: r["area_m2"])
    if len({r["label"] for r in sel}) > 1 and len(sel) > 1:
        return None  # two different rooms answer to the name: let the whole-sheet reader ask
    ops = [d for d in room.get("doors_all", room["doors"]) if d["width_m"] >= 0.5]
    if (seg.get("wall_px") or 0) < 3:  # walls 1-2 px: blurred window gaps read as doorways; keep those with a door
        ok = rooms_mod.symbol_confirmed(meta, seg, ops)
        ops = ok if ok is not None else ops
    if not ops:
        return None
    ev = [_ev([d["bbox"][0] / W, d["bbox"][1] / H, d["bbox"][2] / W, d["bbox"][3] / H],
              f"door opening {i} ({d['width_m']:.2f} m)") for i, d in enumerate(ops, 1)]
    pts = [[round(x / W, 5), round(y / H, 5)] for x, y in room["polygon"]]
    ev.append({"kind": "polygon", "page": 0, "points": pts, "label": rooms_mod._name(room), "value": None})
    nd = sum(1 for d in ops if d["width_m"] >= 1.4)
    conf = 0.7 if not seg.get("scan") and (seg.get("wall_px") or 0) >= 3 else 0.55
    return {"answer": len(ops), "confidence": conf, "method": f"{METHOD}-room", "cost_usd": seg.get("cost_usd", 0.0),
            "explanation": f"{len(ops)} door openings on the outline of the {rooms_mod._name(room)} "
                           f"({room['area_m2']:.0f} m²): "
                           f"gaps in its walls closed by a drawn door leaf or swing ({nd} of them wide enough for a "
                           f"pair of leaves, counted once each). Openings in a folding partition inside the room and "
                           f"open archways without a door are not counted. Each opening is a numbered box.",
            "evidence": ev, "counts": {"doors": len(ops), "double": nd}}


def answer(path, question, meta):
    it = intent(question)
    if it is None:
        return None
    if it == "doors" and closet_mode(question) == "exclude":
        name = room_scope(question)
        if name:
            out = _answer_room_doors(meta, question, name)
            if out is not None:
                return out  # (an "-ask" result when the room is not on the sheet)
    r = analyse_meta(meta)
    import time

    if "_main_plan" not in meta:
        try:
            meta["_main_plan"] = main_plan(meta)
        except Exception as e:  # noqa: BLE001
            log.warning("openings: main plan failed: %s", e)
            meta["_main_plan"] = None
    mp = meta["_main_plan"]
    if mp and r.get("cv_ok", not r["low_res"]) and len(_in_plan(r["doors"], mp)) < 3 and r.get("yolo_pending"):
        # the swings read stand outside the plan (letters of the title block, a 3D view): the detector decides
        t_end = time.monotonic() + YOLO_WAIT_S
        while r.get("yolo_pending") and time.monotonic() < t_end:
            time.sleep(0.5)
    if not r.get("cv_ok", not r["low_res"]) and not r.get("yolo") and r.get("yolo_pending"):
        # the swing reading looked usable at first (a scan PDF re-rendered to full size: a handful of swings) but did
        # not stand, so the answer is the deferred detector's: wait for it rather than abstain
        t_end = time.monotonic() + YOLO_WAIT_S
        while r.get("yolo_pending") and time.monotonic() < t_end:
            time.sleep(0.5)
    if mp:  # count on the floor plan only: not in a 3D view, key plan, detail or the title block beside it
        y = r.get("yolo")
        ok = r.get("cv_ok", not r["low_res"])
        r = dict(r, doors=_in_plan(r["doors"], mp), windows=_in_plan(r["windows"], mp),
                 internal_glazing=_in_plan(r["internal_glazing"], mp),
                 yolo=dict(y, doors=_in_plan(y.get("doors") or [], mp), windows=_in_plan(y.get("windows") or [], mp))
                 if y else y)
        yd = len((r.get("yolo") or {}).get("doors") or [])
        if ok and not r.get("vector") and len(r["doors"]) < 3 and yd >= 3:
            r["cv_ok"] = False  # no swings read on the plan itself (grey swings): the detector's boxes
    if not r.get("cv_ok", not r["low_res"]):
        y = r.get("yolo")
        closets = []
        if y and y.get("doors") and it in ("doors", "doors_windows"):
            cmode = closet_mode(question)
            yd, closets = _split_closets(meta, y["doors"], r.get("px_per_m"), cmode)
            y = dict(y, doors=yd)
        panels = []
        if y and y.get("windows") and it in ("windows", "doors_windows"):
            panels = _side_panels(meta, y["windows"])
            if panels:
                y = dict(y, windows=y["windows"] + panels)
        out = _answer_yolo(it, y, r.get("haiku"), size=(meta.get("w"), meta.get("h")),
                           px_per_m=r.get("px_per_m"))
        if out is not None and panels:
            nw = len(y["windows"])
            out["explanation"] += (f" The window count is every glazed panel: {nw - len(panels)} window symbols plus "
                                   f"{len(panels)} glazed side panels beside doors (vision panels, read from the wall "
                                   f"gaps; marked).")
            out["counts"]["side_panels"] = len(panels)
            if it == "windows":
                out["answer"] = f"{nw} windows ({nw - len(panels)} window symbols + {len(panels)} glazed side panels)"
        if out is not None and closets:
            out["evidence"] += _closet_ev(closets, cmode)
            out["counts"]["closet_doors"] = len(closets) if cmode != "only" else len(y["doors"])
            if cmode == "only":
                out["explanation"] += " Only closet / cupboard doors are counted; the other doors are marked."
                if it == "doors":
                    out["answer"] = f"{len(y['doors'])} closet / cupboard doors"
            else:
                out["explanation"] += f" {len(closets)} closet / cupboard doors are marked but not counted."
                if it == "doors" and isinstance(out["answer"], int):
                    out["answer"] = f"{out['answer']} doors (+{len(closets)} closet doors not counted)"
        if out is not None:
            out["cost_usd"] = out.get("cost_usd", 0.0) + meta.pop("_closet_cost", 0.0)
            _note_not_doors(out, meta)
            _add_schedule_check(out, meta, it)
        return out
    ev, parts, conf = [], [], []
    if it in ("doors", "doors_windows"):
        ds = r["doors"]
        if not ds:
            return None
        cmode = closet_mode(question)
        ds, closets = _split_closets(meta, ds, r.get("px_per_m"), cmode)
        r = dict(r, doors=ds, closets=closets, closet_mode=cmode)
        ev += _closet_ev(closets, cmode)
        nd = sum(1 for d in ds if d.get("leaves") == 2)
        nl = sum(1 for d in ds if d.get("kind") == "leaf")
        nv = sum(1 for d in ds if d.get("kind") == "vector-swing")
        for i, d in enumerate(ds, 1):
            tag = " (double)" if d.get("leaves") == 2 else " (folding / ajar leaf)" if d.get("kind") == "leaf" else ""
            ev.append(_ev(d["bbox"], f"door {i}{tag}"))
        src = (f"{nv} read from the PDF's vector door swings, " if nv else "")
        parts.append(f"{len(ds)} doors ({src}{nd} double doors counted once, {nl} drawn as a folding or ajar leaf "
                     f"without a swing)" + (f"; {len(closets)} closet / cupboard doors not counted (marked)"
                                            if closets else ""))
        conf.append(0.9 if nv else 0.8 if len(ds) >= 5 else 0.55)
    if it in ("windows", "doors_windows"):
        ws = r["windows"]
        yw = (r.get("yolo") or {}).get("windows") or []
        if not ws and len(yw) >= 5:
            # no glazing strips in solid walls (double-line walls, small window symbols): the detector's windows
            r = dict(r, windows=yw, internal_glazing=[])
            ws = yw
            parts.append(f"{len(ws)} windows from the symbol detector (this drawing's walls are not solid, so the "
                         f"wall-strip reading found none; expect ~1 in 8 wrong or missed)")
            for i, w in enumerate(ws, 1):
                ev.append(_ev(w["bbox"], f"window {i}"))
            conf.append(0.45)
            ws = None
        if ws is not None and not ws and it == "windows":
            return None
    if it in ("windows", "doors_windows") and ws is not None:
        for i, w in enumerate(ws, 1):
            ev.append(_ev(w["bbox"], f"window {i}"))
        ig = len(r["internal_glazing"])
        for i, g in enumerate(r["internal_glazing"], 1):
            ev.append(_ev(g["bbox"], f"internal glazed panel {i}"))
        parts.append(f"{len(ws)} windows in outside walls (each glazed panel between wall piers)"
                     + (f" + {ig} internal glazed panels (vision panels beside doors, glazed screens) = {len(ws) + ig} "
                        f"glazed panels in all; the count is every glazed panel, as a window schedule would list them "
                        f"(outside walls only: {len(ws)})" if ig else ""))
        conf.append(0.8 if ws else 0.3)
    ig = len(r["internal_glazing"])
    # convention: every glazed panel between piers is a window, internal vision panels included; the split is given
    wtxt = (f"{len(r['windows']) + ig} windows ({len(r['windows'])} in outside walls + {ig} internal glazed panels)"
            if ig else f"{len(r['windows'])} windows")
    if it == "doors_windows":
        ans = f"{len(r['doors'])} doors and {wtxt}"
    elif it == "doors":
        ans = len(r["doors"])
        if r.get("closet_mode") == "only":
            ans = f"{len(r['doors'])} closet / cupboard doors"
        elif r.get("closets"):
            ans = f"{len(r['doors'])} doors (+{len(r['closets'])} closet doors not counted)"
    else:
        ans = len(r["windows"]) if not ig else wtxt
    expl = ("Found " + "; ".join(parts) + ". Every counted item is a numbered box: check the marked ones. "
            "Doors are read from their swing arcs (plus folding / ajar leaves); sliding doors and openings "
            "without a door symbol are not counted.")
    out = {"answer": ans, "confidence": round(min(conf), 2), "method": f"{METHOD}-cv",
           "cost_usd": meta.pop("_closet_cost", 0.0),
           "explanation": expl, "evidence": ev,
           "counts": {"doors": len(r["doors"]), "windows": len(r["windows"]) + ig, "exterior_windows": len(r["windows"]),
                      "internal_glazing": len(r["internal_glazing"]), "closet_doors": len(r.get("closets") or [])}}
    _note_not_doors(out, meta)
    _add_schedule_check(out, meta, it)
    return out


def _note_not_doors(out, meta):
    """Boxes the vision check found to hold no door (equipment arcs, a half box): marked, not counted."""
    nd = meta.pop("_not_doors", None)
    if not nd:
        return
    for i, d in enumerate(nd, 1):
        e = _ev(d["bbox"], f"not a door {i}: not counted ({d['why']})")
        e["value"] = None
        e["on"] = False
        out["evidence"].append(e)
    out["explanation"] += f" {len(nd)} found symbol(s) hold no door (equipment or a symbol) and are not counted."
    out.setdefault("counts", {})["not_doors"] = len(nd)


def _agree(a, b, tol=0.15):
    return max(a, b) > 0 and abs(a - b) / max(a, b) <= tol


COARSE_DOOR_PX = 13  # median detector door box (long side, original px): school 2000 px 18, dorm 2000 px 11
COARSE_PX_PER_M = 15


def _answer_yolo(it, y, hk=None, size=None, px_per_m=None):
    """Swings not readable: the detector's boxes at 0.5; a Claude vision count on tiles agreeing within 15 % raises
    it to 0.6 and is quoted; a disagreeing one is ignored (it undercounts dense sheets)."""
    if not y or (it == "doors" and not y["doors"]) or (it == "windows" and not y["windows"]):
        return None
    ev, parts = [], []
    if it in ("doors", "doors_windows"):
        ev += [_ev(d["bbox"], f"door {i}") for i, d in enumerate(y["doors"], 1)]
        parts.append(f"{len(y['doors'])} doors")
    if it in ("windows", "doors_windows"):
        ev += [_ev(d["bbox"], f"window {i}" + (" (glazed side panel)" if d.get("kind") == "side-panel" else ""))
               for i, d in enumerate(y["windows"], 1)]
        parts.append(f"{len(y['windows'])} windows")
    ans = len(y["doors"]) if it == "doors" else len(y["windows"]) if it == "windows" else \
        f"{len(y['doors'])} doors and {len(y['windows'])} windows"
    # the detector's count stands on its own (school 2000 px: 120 vs 128 by hand; dorm PNG: 204 vs 198); a Claude
    # vision count on tiles can only raise confidence: it undercounts dense sheets (109 on the dorm), so no veto
    conf, notes = 0.5, []
    ks = ["doors"] if it == "doors" else ["windows"] if it == "windows" else ["doors", "windows"]
    if any(len(y[k]) < 3 for k in ks if not (k == "windows" and it == "doors_windows")):
        conf = 0.3  # implausibly few symbols for a floor plan
    if hk and all(_agree(len(y[k]), len(hk[k])) for k in ks):
        notes.append(f"a separate vision count on {hk['tiles']} tiles agrees ("
                     + ", ".join(f"{len(hk[k])} {k}" for k in ks) + ")")
        conf = min(0.6, conf + 0.1)
    expl = ("Found " + " and ".join(parts) + " with the symbol detector (door swings could not be read directly on "
            "this drawing, so expect a few wrong or missed boxes: about 1 in 5 for doors on our test sheet)"
            + ("; " + "; ".join(notes) if notes else "") + ". Every counted item is a numbered box: check the marked "
            "ones; a higher-resolution upload or the PDF gives a more exact count.")
    low = not (size and max(size) >= 3000)  # the low-resolution note only for genuinely small images
    # too coarse to count: door symbols only a few pixels across (dorm at 2000 px: the detector finds a third)
    if it in ("doors", "doors_windows") and y["doors"] and size and size[0] and size[1]:
        W, H = size
        med = float(np.median([max((d["bbox"][2] - d["bbox"][0]) * W, (d["bbox"][3] - d["bbox"][1]) * H)
                               for d in y["doors"]]))
        if med < COARSE_DOOR_PX or (px_per_m and px_per_m < COARSE_PX_PER_M):
            n = len(y["doors"])
            what = f"~{med:.0f} px across" + (f" at {px_per_m:.0f} px per metre" if px_per_m else "")
            low = f"doors are {what}; upload the PDF or a larger image"
            ans = f"at least {n} doors (image too coarse to count reliably)" if it == "doors" else \
                f"at least {n} doors (image too coarse to count reliably) and {len(y['windows'])} windows"
            conf = 0.25
            expl = (f"At least {n} doors: the door symbols in this image are only {what}, so the detector misses "
                    f"many of them (on a test sheet at this size it found a third). Each found door is a numbered "
                    f"box; upload the PDF or a larger image for a real count.")
    return {"answer": ans, "confidence": conf, "method": f"{METHOD}-yolo", "cost_usd": (hk or {}).get("cost_usd", 0.0),
            "low_res": low,
            "explanation": expl, "evidence": ev,
            "counts": {"doors": len(y["doors"]), "windows": len(y["windows"]),
                       "vision_doors": len(hk["doors"]) if hk else None,
                       "vision_windows": len(hk["windows"]) if hk else None}}


_TAG = re.compile(r"^[A-Z]?\d{2,4}[A-Z]?$")
_DIM = re.compile(r"^\d+'\s*-\s*\d+")


def _is_width(ln: str) -> bool:
    if _DIM.match(ln):
        return True
    return bool(re.fullmatch(r"\d{3,4}", ln)) and 500 <= int(ln) <= 3000  # metric leaf width in mm


def schedule_doors(pdf_path: str) -> dict | None:
    """Door marks from the DOOR SCHEDULE(s) in a PDF: {"page": i, "schedules": [{mark: rows}, ...]} (a mark listed
    twice = a pair of leaves). A row is a mark followed within 3 lines by a leaf width (3' - 0" or 915)."""
    try:
        import pymupdf

        doc = pymupdf.open(pdf_path)
    except Exception:  # noqa: BLE001
        return None
    for i, pg in enumerate(doc):
        t = pg.get_text()
        if "DOOR SCHEDULE" not in t.upper():
            continue
        lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
        per, cur = [], None
        for k, ln in enumerate(lines):
            u = ln.upper()
            if "SCHEDULE" in u:
                cur = {} if "DOOR SCHEDULE" in u else None
                if cur is not None:
                    per.append(cur)
                continue
            if _is_width(ln) and k and (re.fullmatch(r"[A-Z]{1,2}|\d{3,4}", lines[k - 1])):
                continue  # a width (or height) column value, not a mark
            if cur is not None and _TAG.match(ln) and any(_is_width(x) for x in lines[k + 1:k + 4]):
                cur[ln] = cur.get(ln, 0) + 1
        per = [d for d in per if d]
        if per:
            return {"page": i, "schedules": per}
    return None


def _add_schedule_check(res, meta, it):
    """Vector PDF with a door schedule: the schedule's marks printed on this sheet are an independent door count."""
    if it == "windows" or not str(meta.get("path") or "").lower().endswith(".pdf"):
        return
    sch = meta.setdefault("_openings_schedule", schedule_doors(meta["path"]))
    if not sch:
        return
    words = {w.get("text", "").strip() for w in (meta.get("words") or [])} or set(
        (meta.get("text") or "").split())
    best = None
    for sd in sch["schedules"]:
        on = [m for m in sd if m in words]
        if on and (best is None or len(on) > len(best[0])):
            best = (on, sd)
    if not best:
        return
    on, sd = best
    n = len(on)
    ours = res.get("counts", {}).get("doors")
    msg = (f"Cross-check: the door schedule (page {sch['page'] + 1}) lists {len(sd)} doors, {n} of whose marks "
           f"({', '.join(sorted(on))}) are on this sheet")
    if ours is not None:
        msg += "; that agrees with the drawn count" if ours == n else \
            f"; the drawn count ({ours}) DISAGREES with that, so the answer uses the schedule's {n} (the boxes are " \
            f"the drawn symbols: check them)"
    res["explanation"] += " " + msg + "."
    res["schedule_doors"] = n
    if ours is not None and ours != n and n >= 2:
        if it == "doors":
            res["answer"] = n
        elif isinstance(res.get("answer"), str):
            res["answer"] = re.sub(r"^\d+ doors", f"{n} doors", res["answer"])
        res["confidence"] = max(res.get("confidence", 0), 0.7)
    elif ours == n:
        res["confidence"] = max(res.get("confidence", 0), 0.9)


# ------------------------------------------------------------------------------------------ vector PDF door swings
def _page_segments(page):
    """All stroked line pieces of a PDF page as an (N, 4) array in page (unrotated) coordinates, Bézier curves
    flattened to 8 pieces each, plus the stroke grey level per piece."""
    segs, grey = [], []
    ts = np.linspace(0, 1, 9)
    for x in page.get_drawings():
        if x.get("type") == "f" or not x.get("color"):
            continue
        g = float(np.mean(x["color"][:3]))
        for it in x["items"]:
            if it[0] == "l":
                segs.append((it[1].x, it[1].y, it[2].x, it[2].y))
                grey.append(g)
            elif it[0] == "c":
                p0, p1, p2, p3 = it[1:5]
                bx = (1 - ts) ** 3 * p0.x + 3 * (1 - ts) ** 2 * ts * p1.x + 3 * (1 - ts) * ts ** 2 * p2.x + ts ** 3 * p3.x
                by = (1 - ts) ** 3 * p0.y + 3 * (1 - ts) ** 2 * ts * p1.y + 3 * (1 - ts) * ts ** 2 * p2.y + ts ** 3 * p3.y
                for k in range(8):
                    segs.append((bx[k], by[k], bx[k + 1], by[k + 1]))
                    grey.append(g)
    return np.array(segs, float).reshape(-1, 4), np.array(grey, float)


def _vector_arcs(S, rmax):
    """Circle arcs among chains of short pieces (a curve tessellated into lines, or flattened Béziers): pieces joined
    end to end through degree-2 nodes without sharp turns. [(cx, cy, r, span_deg, a0, a1, chain idx)]."""
    import collections

    L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])
    idx = np.nonzero((L > 1e-3) & (L < 0.6 * rmax))[0]
    q = 1 / max(1e-4, 0.002 * rmax)

    def key(x, y):
        return (round(x * q), round(y * q))

    adj = collections.defaultdict(list)
    ends = {}
    for i in idx:
        a, b = key(S[i, 0], S[i, 1]), key(S[i, 2], S[i, 3])
        ends[i] = (a, b)
        adj[a].append(i)
        adj[b].append(i)

    def unit(i, frm):
        a, b = ends[i]
        v = (S[i, 2] - S[i, 0], S[i, 3] - S[i, 1]) if a == frm else (S[i, 0] - S[i, 2], S[i, 1] - S[i, 3])
        n = math.hypot(*v) or 1.0
        return v[0] / n, v[1] / n

    used, out = set(), []
    for i in idx:
        if i in used:
            continue
        used.add(i)
        chain = [i]
        for start in ends[i]:
            cur, k = i, (ends[i][1] if start == ends[i][0] else ends[i][0])
            ext = []
            while len(adj[k]) == 2:
                nxt = adj[k][0] if adj[k][1] == cur else adj[k][1]
                if nxt in used:
                    break
                d1 = unit(cur, ends[cur][0] if ends[cur][1] == k else ends[cur][1])
                d2 = unit(nxt, k)
                if d1[0] * d2[0] + d1[1] * d2[1] < math.cos(math.radians(35)):
                    break
                ext.append(nxt)
                used.add(nxt)
                cur = nxt
                k = ends[nxt][1] if ends[nxt][0] == k else ends[nxt][0]
            chain = ext[::-1] + chain if start == ends[i][0] else chain + ext
        if len(chain) < 2:
            continue
        P = np.r_[S[chain, :2], S[chain, 2:]]
        A = np.c_[2 * P[:, 0], 2 * P[:, 1], np.ones(len(P))]
        sol, *_ = np.linalg.lstsq(A, (P ** 2).sum(1), rcond=None)
        cx, cy = sol[0], sol[1]
        r = math.sqrt(max(0.0, sol[2] + cx * cx + cy * cy))
        err = np.abs(np.hypot(P[:, 0] - cx, P[:, 1] - cy) - r).max() / max(r, 1e-9)
        if not (0 < r <= rmax) or err > 0.08:
            continue
        ang = np.sort(np.arctan2(P[:, 1] - cy, P[:, 0] - cx) % (2 * np.pi))
        gaps = np.diff(np.r_[ang, ang[0] + 2 * np.pi])
        g = int(np.argmax(gaps))
        a0 = ang[(g + 1) % len(ang)]
        span = 2 * np.pi - gaps[g]
        out.append((cx, cy, r, math.degrees(span), a0, a0 + span, chain, err))
    return out


def vector_doors(pdf_path, page=0) -> dict | None:
    """Doors from the vector drawing of a PDF page: quarter-circle swings (60-120 degrees) whose radius is a door
    leaf, a straight leaf piece ~r long from the hinge (when drawn), paired into double doors. The leaf radius is
    taken from the page scale when printed, else from the dominant radius among the quarter arcs.
    Returns {"doors": [{"bbox" (normalised to the rotated page), "leaves", "r_m"}], "arcs": n, "r_pt": [...]}
    or None when the page has no vector arcs (a scan)."""
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    pg = doc[int(page)]
    S, grey = _page_segments(pg)
    if len(S) < 50:
        return None
    long_pt = max(pg.rect.width, pg.rect.height)
    t = pg.get_text()
    ratios = {int(m) for m in re.findall(r"\b1\s*:\s*(\d{2,4})\b", t)}
    for a, b in re.findall(r"(\d+)/(\d+)\"\s*=\s*1'\s*-?\s*0\"", t):
        ratios.add(round(12 * int(b) / int(a)))
    for a in re.findall(r"\b(\d{1,2})\"\s*=\s*(\d{1,3})'\s*-?\s*0\"", t):
        ratios.add(round(12 * int(a[1]) / int(a[0])))
    ratios = {r for r in ratios if 10 <= r <= 2000}
    pt_per_m = (72 / 0.0254) / ratios.pop() if len(ratios) == 1 else None
    rmax = 1.6 * pt_per_m if pt_per_m else long_pt / 30
    allarcs = _vector_arcs(S, rmax)

    def has_leaf(a):
        """a straight piece ~r long starting at the hinge, along one end of the arc (the drawn door leaf)"""
        cx, cy, r = a[0], a[1], a[2]
        L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])
        for e0, e1 in ((0, 2), (2, 0)):
            near = (np.hypot(S[:, e0] - cx, S[:, e0 + 1] - cy) < 0.15 * r) & (L > 0.6 * r) & (L < 1.25 * r)
            for i in np.nonzero(near)[0]:
                ang = math.atan2(S[i, e1 + 1] - cy, S[i, e1] - cx)
                for end in (a[4], a[5]):
                    if abs((ang - end + math.pi) % (2 * math.pi) - math.pi) < math.radians(12):
                        return True
        return False

    # a quarter swing (>= 3 pieces); a swing drawn part-open (30-60 degrees, e.g. corridor doors shown at 45, often
    # only 2 pieces) needs its leaf. Radius limits first, the leaf test is the slow part.
    if pt_per_m:
        allarcs = [a for a in allarcs if 0.5 * pt_per_m <= a[2] <= 1.5 * pt_per_m]
    arcs = [a for a in allarcs if 60 <= a[3] <= 120 and len(a[6]) >= 3 and a[7] <= 0.03]
    if arcs and not pt_per_m:
        rs = np.array([a[2] for a in arcs])
        hist, edges = np.histogram(np.log(rs), bins=30)
        k = int(np.argmax(hist))
        mode = math.exp((edges[k] + edges[k + 1]) / 2)
        arcs = [a for a in arcs if 0.55 * mode <= a[2] <= 1.8 * mode]
        allarcs = [a for a in allarcs if 0.55 * mode <= a[2] <= 1.8 * mode]
    arcs += [a for a in allarcs if (30 <= a[3] < 60 or (60 <= a[3] <= 120 and (len(a[6]) < 3 or a[7] > 0.03)))
             and has_leaf(a)]  # rough or short arcs count with a drawn leaf
    if not arcs:
        return {"doors": [], "arcs": 0, "pt_per_m": pt_per_m}
    sw = [{"c": (a[0], a[1]), "r": a[2], "a0": a[4], "a1": a[5], "span": a[3]} for a in arcs]
    # duplicates (the same arc drawn twice / in two layers)
    uniq = []
    for s in sw:
        if not any(math.hypot(s["c"][0] - u["c"][0], s["c"][1] - u["c"][1]) < 0.1 * s["r"] and
                   abs(s["r"] - u["r"]) < 0.1 * s["r"] for u in uniq):
            uniq.append(s)
    # a run of identical arcs closer than a leaf width (locker / cupboard fronts, seat rows) is furniture, not doors
    crowd = [sum(1 for u in uniq if u is not s and abs(u["r"] - s["r"]) < 0.15 * s["r"] and
                 math.hypot(u["c"][0] - s["c"][0], u["c"][1] - s["c"][1]) < 1.3 * s["r"]) for s in uniq]
    uniq = [s for s, c in zip(uniq, crowd) if c < 2]
    used, doors = set(), []
    for i, s in enumerate(uniq):
        if i in used:
            continue
        used.add(i)
        mate = next((j for j in range(i + 1, len(uniq)) if j not in used and _pair(s, uniq[j])), None)
        parts = [s] if mate is None else [s, uniq[mate]]
        if mate is not None:
            used.add(mate)
        bs = [_swing_box(p) for p in parts]
        doors.append({"bbox": [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs),
                               max(b[3] for b in bs)], "leaves": len(parts),
                      "r_m": round(float(np.mean([p["r"] for p in parts])) / pt_per_m, 2) if pt_per_m else None})
    # page (unrotated) coords -> rotated page as rendered -> normalised
    M = pg.rotation_matrix
    W, H = pg.rect.width, pg.rect.height
    for d in doors:
        r = pymupdf.Rect(*d["bbox"]) * M
        d["bbox"] = [r.x0 / W, r.y0 / H, r.x1 / W, r.y1 / H]
    doors.sort(key=lambda d: (round(d["bbox"][1] * 40), d["bbox"][0]))
    return {"doors": doors, "arcs": len(uniq), "pt_per_m": pt_per_m,
            "r_pt": sorted(round(s["r"], 2) for s in uniq)[:: max(1, len(uniq) // 10)]}
