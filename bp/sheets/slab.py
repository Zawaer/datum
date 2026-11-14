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

import logging
import math
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

METHOD = "sheets-slab"
WALL_BAND = 0.009  # wall band (edge beam) width bound, share of the long image side
_DEBUG: list = []
_BAR = r"(?:[DTYHRN]\s?\d{1,2}|#\s?\d{1,2}|Ø\s?\d{1,2}|\d{1,2}\s?M)"
_BAR_RE = re.compile(rf"\b({_BAR})\s*(?:@|AT|C/C|CC|c/c)\s*(\d{{2,4}})", re.I)
_THK_RE = re.compile(r"\b(\d{2,3})\s*(?:MM\s*)?(?:THK\.?\s*|THICK\s*)?(?:CONCRETE\s*)?(?:SLAB|SOG|S\.O\.G)", re.I)
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
    return min(1.0, s + min(0.2, 0.04 * hits))


# ----------------------------------------------------------------------------------------------- text
def _num(s: str):
    t = s.replace(",", "").replace(" ", "")
    if re.fullmatch(r"\d{2,6}", t):
        return int(t)
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
        hor, ver = [], []
        for w in pw:
            x0, y0, x1, y1 = w["bbox"]
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
    bar = [re.sub(r"\s", "", b).upper() + f" @ {s}" for b, s in bars]
    faces = []
    if re.search(r"TOP FACE|\bT\.?F\.?\b|\bT\s*&\s*B\b|EACH FACE|\bE\.?F\.?\b", t):
        faces.append("top")
    if re.search(r"BOTTOM FACE|\bB\.?F\.?\b|\bT\s*&\s*B\b|EACH FACE|\bE\.?F\.?\b", t):
        faces.append("bottom")
    return {"thickness_mm": int(m.group(1)) if m else None, "bars": bar,
            "elevation": el.group(1).rstrip(".,") if el else None, "faces": faces,
            "bottom_as_indicated": bool(re.search(r"BOTTOM FACE REINF\w* AS INDICATED", t)),
            "kind": "slab-on-grade" if "ON-GRADE" in t or "SOG" in t else "slab"}


def _type_name(ty: dict) -> str:
    s = f"{ty['thickness_mm']} mm" if ty.get("thickness_mm") else "slab"
    if ty.get("bars"):
        s += " w/ " + ", ".join(ty["bars"])
    return s


# ----------------------------------------------------------------------------------------------- geometry
def _gray(meta, max_side=2000):
    import cv2

    g = cv2.imread(meta["image"], cv2.IMREAD_GRAYSCALE)
    f = 1.0
    if max(g.shape) > max_side:
        f = max_side / max(g.shape)
        g = cv2.resize(g, (round(g.shape[1] * f), round(g.shape[0] * f)), interpolation=cv2.INTER_AREA)
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


def _bbox(m):
    import numpy as np

    ys, xs = np.nonzero(m)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else (0, 0, 0, 0)


def _min_side(m):
    x0, y0, x1, y1 = _bbox(m)
    return min(x1 - x0, y1 - y0)


def _zones(g, k=None):
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

    ker = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * r + 1, 2 * r + 1))
    for i, (x, y, w, h, _a) in keep.items():
        x0, y0, x1, y1 = max(0, x - r), max(0, y - r), min(W, x + w + r), min(H, y + h + r)
        sub = lab[y0:y1, x0:x1]
        ring = cv2.dilate((sub == i).astype(np.uint8), ker) & (sub != i)
        js, cnt = np.unique(sub[ring > 0], return_counts=True)
        for j, c in zip(js, cnt):
            if j in keep and j != i and c >= min_touch:
                parent[find(i)] = find(j)
                if _DEBUG: _DEBUG.append((i, j, int(c), keep[i], keep[j]))
    groups: dict = {}
    for i in keep:
        groups.setdefault(find(i), []).append(i)
    kc = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * r + 3, 2 * r + 3))
    cands = []
    for idx in groups.values():
        if sum(keep[i][4] for i in idx) < 0.008 * W * H:
            continue
        m = cv2.morphologyEx(np.isin(lab, idx).astype(np.uint8), cv2.MORPH_CLOSE, kc)
        cands.append((m, _ring_walled(g, m)))
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
        if sp:
            d["k"] = d["v"] / (sp[1] - sp[0])
            est.append(d["k"])
    if len(est) < 3:
        return None, dims, 0
    e = np.array(est)
    med = float(np.median(e))
    good = [d for d in dims if "k" in d and abs(d["k"] / med - 1) < 0.04]
    for d in dims:
        d["inlier"] = d in good
    # long dimensions dominate (a 1 px tick error matters less on 12,000 mm than on 600 mm)
    k = sum(d["v"] ** 2 * d["k"] for d in good) / sum(d["v"] ** 2 for d in good)
    return k, dims, len(good)


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
def _vision_text(meta) -> dict:
    """Last resort without OCR: Haiku reads the slab notes + overall dimensions (one call, ~$0.01)."""
    from PIL import Image

    from bp.generic import llm

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
    d["cost_usd"] = r.get("cost_usd", 0.0)
    return d


_NOTE_KW = re.compile(r"SLAB|SUMP|TRENCH|NOTES?\b|SHADED|HATCH|REINF", re.I)


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
    keyb = [b for b in blocks if _NOTE_KW.search(b["text"])]
    if not keyb or len(keyb) > 25:
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
        ws = ocr_words(meta, region=tuple(round(v, 4) for v in bx), scale=4.0, psm=6, min_conf=40)
        crop_nums[tuple(bx)] = {t for w in ws for t in re.findall(r"\d{3,6}", w["text"])}

    def fix(note, bx):
        def sub(m):
            t = m.group(0)
            near = crop_nums.get(tuple(bx), set())
            if not is_general.get(tuple(bx)) or not near or t in near:
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
            out.append({"text": fix(n, bx), "bbox": bb, "lines": [], "read": "haiku+ocr"})
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
    hor, ver, src = _ocr(meta)
    g, f = _gray(meta)
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
            twin = next((t for t in types if t["thickness_mm"] == ty["thickness_mm"] and t["bars"] == ty["bars"]
                         and (t["text"] in ty["text"] or ty["text"] in t["text"])), None)
            if twin is None:
                types.append(ty)
            elif len(ty["text"]) > len(twin["text"]):
                area = lambda bb: (bb[2] - bb[0]) * (bb[3] - bb[1])  # noqa: E731
                bb = min(twin["bbox"], ty["bbox"], key=area)
                twin.clear()
                twin.update(ty)
                twin["bbox"] = bb

    # scale
    k, dims, n_scale = _scale_from_dims(hor, ver, W, H, g)
    scale_src = f"{n_scale} dimension-string pairs" if k else None

    # zones
    zones, _outside = _zones(g, k)
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
        pts = _clean_poly(pts)
        out_zones.append({"inner": pts, "gross": gross, "inner_px": _poly_area(pts), "gross_px": _poly_area(gross),
                          "panels": n_pan, "cuts": cuts, "walled": round(z["walled"], 3),
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
    for z in sorted(out_zones, key=lambda z: -z["gross_px"]):
        if z["type"] is not None:
            continue
        poly = Polygon(z["gross"])
        cands = [(poly.distance(Point((t["bbox"][0] + t["bbox"][2]) / 2 * W, (t["bbox"][1] + t["bbox"][3]) / 2 * H)), ti)
                 for ti, t in enumerate(types) if ti not in used]
        if cands:
            dist, ti = min(cands)
            if dist < 0.15 * S:
                z["type"], z["type_how"] = ti, f"nearest note outside the zone ({dist * (k or 0) / 1000:.1f} m away, leader)"
                used.add(ti)
    union = np.zeros_like(g, dtype=np.uint8)
    for z in zones:
        union |= z["mask"]
    pads = _hatch(g, union) if zones else []

    # notes: trenches, sumps, CJ, scale
    trenches = []
    tr_text = "\n".join(b["text"] for b in blocks if b.get("read")) or full_text
    for m in re.finditer(r"([A-Z][A-Z ]{2,40}?)\s+TRENCH\s+LENGTH\s*[-=:]?\s*(\d[\d,]*)", tr_text.upper()):
        trenches.append({"name": m.group(1).strip().title() + " trench", "length_mm": int(m.group(2).replace(",", ""))})
    by_len: dict = {}
    for t in trenches:  # the same note read twice (overlapping crops / OCR leftovers): keep the cleanest name
        cur = by_len.get(t["length_mm"])
        if cur is None or len(t["name"]) > len(cur["name"]):
            by_len[t["length_mm"]] = t
    trenches = [t for t in trenches if by_len.get(t["length_mm"]) is t]
    tl_blocks = [b for b in blocks if "TRENCH" in b["text"].upper()]
    sump_blocks = [b for b in blocks if re.search(r"\bSUMP\b", b["text"].upper())]
    sumps = []
    for b in sump_blocks:
        m = re.search(r"SUMP\s*(\d{3,4})\s*[X×x]\s*(\d{3,4})\s*[X×x]\s*(\d{2,4})", b["text"].upper())
        sumps.append({"text": b["text"], "bbox": b["bbox"], "dims": [int(v) for v in m.groups()] if m else None})
    cj_words = [w for w in hor + ver if re.fullmatch(r"C\.?J\.?", w["text"].upper())]
    sc = re.search(r"SCALE\s*:?\s*1\s*:\s*(\d+)", full_text.upper())
    hatch_note = next((b for b in blocks if re.search(r"SHADED|HATCH", b["text"].upper())), None)
    low = bool(meta.get("low_res")) if "low_res" in meta else (src != "pdf-text" and max(meta.get("w") or 0, meta.get("h") or 0) < 3000)
    res = {"v": 1, "src": src, "low_res": low, "W": W, "H": H, "f": f, "k": k, "scale_src": scale_src,
           "scale_note": f"1:{sc.group(1)}" if sc else None, "types": types, "zones": out_zones,
           "pads": pads, "trenches": trenches, "trench_blocks": [b["bbox"] for b in tl_blocks],
           "trench_labels": [{"text": b["text"], "bbox": b["bbox"]} for b in tl_blocks],
           "sumps": sumps, "cj_words": [w["bbox"] for w in cj_words],
           "hatch_note": hatch_note["text"] if hatch_note else None,
           "chains": _chains(dims),
           "dims": [{k2: d[k2] for k2 in ("v", "vertical", "bbox", "span", "k", "inlier") if k2 in d} for d in dims], "cost_usd": cost,
           "text": full_text,
           "stairs": [b["bbox"] for b in blocks if re.search(r"\bSTAIR", b["text"], re.I) and b["bbox"][2] > b["bbox"][0]]}
    meta["slab"] = res
    return res


# ----------------------------------------------------------------------------------------------- answer helpers
def _m2(px, k):
    return px * k * k / 1e6


def _norm_pts(pts, W, H):
    return [[round(x / W, 5), round(y / H, 5)] for x, y in pts]


def _zone_explain(z, a, k, dims, key="gross", stairs=(), WH=(1, 1)):
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
        if (x1 - x0) * (y1 - y0) < 0.04 * big and any(
                b[0] - 0.06 < cx < b[2] + 0.06 and b[1] - 0.06 < cy < b[3] + 0.06 for b in stairs):
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
        return f"{v:,.0f}" + (f" ({d['how']})" if d and d.get("how") else "") if d else f"{v:,.0f}*"

    txt = " + ".join(f"{lab(w, pw)} × {lab(h, ph)}" for w, h, _, pw, ph in parts)
    star = " (* measured; other sides are printed dimensions)" if printed < 2 * len(parts) else " (sides = printed dimensions)"
    tail = f"; stair well ({sum(dropped):.1f} m²) left out" if dropped else ""
    return total, f"{txt} mm = {total:.2f} m²" + (star if printed else " (sides measured)") + tail, parts


def _zone_area(z, A):
    """Slab area = clear area inside the edge beams / walls (the stippled bands are walls, not slab). Returns
    (net m², explanation incl. the gross outline for reference, parts)."""
    k = A["k"]
    dims = A["dims"] + A.get("chains", [])
    a_meas = _m2(z["inner_px"], k)
    stairs = A.get("stairs", [])
    a, how, used = _zone_explain(z, a_meas, k, dims, key="inner", stairs=stairs, WH=(A["W"], A["H"]))
    g_meas = _m2(z["gross_px"], k)
    ga, ghow, _ = _zone_explain(z, g_meas, k, A["dims"], key="gross", stairs=stairs, WH=(A["W"], A["H"]))
    return a, f"clear area inside the walls: {how}; outer faces: {ghow}", used


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
                        out.append({"v": tot, "vertical": vertical, "how": " + ".join(f"{p:,}" for p in parts)})
    return out


def _type_of(z, A):
    return A["types"][z["type"]] if z.get("type") is not None else None


def _match_zones(q, A):
    """Zones selected by a thickness / bar mention in the question, or None for 'no filter'."""
    ql = q.upper()
    thk = [int(x) for x in re.findall(r"\b(\d{2,3})\s*(?:MM)?\s*(?:THICK|THK|SLAB|SOG|-?MM)", ql)]
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
def answer(path, question, meta) -> dict | None:
    q = question.strip()
    ql = q.lower()
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
            if hits and not re.search(r"\btotal|all|sum\b", ql):
                return _res(best["length_mm"] / div, conf0 + 0.1,
                            f"{best['name']}: {best['length_mm']:,} mm per the general notes "
                            f"(\"approximate trench lengths\")", ev, A, "trench", "mm" if div == 1 else "m")
            tot = sum(t["length_mm"] for t in A["trenches"])
            return _res(tot / div, conf0 + 0.05, " + ".join(f"{t['length_mm']:,}" for t in A["trenches"])
                        + f" mm = {tot:,} mm ({', '.join(t['name'] for t in A['trenches'])}; lengths from the notes)",
                        ev, A, "trench", "mm" if div == 1 else "m")
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
            and not re.search(r"\barea\b|how much|m2|m²|square", ql):
        sel, desc = _match_zones(q, A)
        tys = [(z, _type_of(z, A)) for z in (zones if sel is None else sel) if _type_of(z, A)]
        if not tys and A["types"]:
            tys = [(None, t) for t in A["types"]]
        if not tys:
            # no "<thk> SLAB W/ <bar> @ <s>" note (e.g. a tank slab detailed bar by bar): list the bar callouts
            calls = []
            pat = (rf"\b(?:\d+\s*-\s*)?{_BAR}\s*(?:(?:HOOP|RADIAL BARS|BARS)\s*)?(?:@|X|x)\s*\d{{2,5}}"
                   r"(?:\s*(?:E\.?\s?W\.?|EACH WAY|TOP AND BOTTOM|TOP|BOTTOM|LONG|O\.?C\.?))*")
            for m in re.finditer(pat, A.get("text", ""), re.I):
                c = re.sub(r"\s+", " ", m.group(0)).strip()
                if c not in calls:
                    calls.append(c)
            if not calls or not re.search(r"bars?|reinforc|rebar", ql):
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
                if len(tys) > 1 and v:
                    v = f"{t['thickness_mm']} mm slab: {v}"
            if v:
                out.append(v)
                ev.append(_text_ev(t["bbox"], f"note: {t['text'][:80]}"))
                if z:
                    ev.append(_zone_ev(z, A, _type_name(t), None))
        if not out:
            return None
        ans = out[0] if len(out) == 1 else "; ".join(out)
        return _res(ans, conf0 + 0.1 if len(out) == 1 else conf0, "read from the slab note(s): "
                    + " | ".join(t["text"][:90] for _, t in tys), ev, A, "note")

    # ---- areas
    if re.search(r"\barea\b|how much slab|m2|m²|square|how big|size of", ql) or "slab" in ql:
        if not zones or not k or not any(_type_of(z, A) for z in zones):
            return None  # no slab zone tied to a slab note: not a plan this module understands (let generic answer)
        rows = []
        for z in zones:
            a, how, used = _zone_area(z, A)
            rows.append((z, a, how, used))
        conf = conf0
        typed = [r for r in rows if _type_of(r[0], A)]
        if len(typed) < len(rows):
            conf *= 0.8
        sel, desc = _match_zones(q, A)
        by_type = re.search(r"by type|per type|each type|each slab|by thickness|breakdown|types? of slab", ql)
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
                expl += f" → total {tot:.2f} m²"
            return _res(round(tot, 2), conf, f"{desc} slab: {expl}", ev, A, "area", "m²")
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
            ans = "; ".join(f"{n}: {sum(v):.1f} m²" for n, v in groups.items()) + f" (total {tot:.1f} m²)"
            expl = " | ".join(f"[{_type_name(_type_of(z, A)) if _type_of(z, A) else 'untyped'}] {how}"
                              for z, a, how, used in rows)
            return _res(ans, conf, expl, ev, A, "area-by-type", "m²")
        expl = " + ".join(f"{a:.2f}" for _, a, _, _ in rows) + f" = {tot:.2f} m² (" + " | ".join(
            f"[{_type_name(_type_of(z, A)) if _type_of(z, A) else 'untyped'}] {how}" for z, a, how, used in rows) + ")"
        return _res(round(tot, 2), conf, f"total slab area: {expl}", ev, A, "area", "m²")

    if re.search(r"how many .*(slab types|types of slab|slab zones)", ql):
        n = len({_type_name(t) for t in A["types"]})
        return _res(n, conf0, f"{n} distinct slab notes", [_text_ev(t["bbox"], t["text"][:80]) for t in A["types"]],
                    A, "note")
    return None
