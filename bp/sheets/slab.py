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
import re
from pathlib import Path

log = logging.getLogger(__name__)

METHOD = "sheets-slab"
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
    hits = len(re.findall(r"slab|foundation|footing|reinforc|rebar|S\.?O\.?G|\bD\d{2}\s*@", blob, re.I))
    return min(1.0, s + min(0.2, 0.04 * hits))


# ----------------------------------------------------------------------------------------------- text
def _num(s: str):
    t = s.replace(",", "").replace(" ", "")
    if re.fullmatch(r"\d{2,6}", t):
        return int(t)
    return None


def _pdf_words(path: str, page: int, W: int, H: int) -> list[dict]:
    try:
        import pymupdf
    except ImportError:
        return []
    try:
        pg = pymupdf.open(path)[page]
    except Exception:  # noqa: BLE001
        return []
    pw, ph = pg.rect.width, pg.rect.height
    out = []
    d = pg.get_text("dict")
    for b in d.get("blocks", []):
        for ln in b.get("lines", []):
            dx, dy = ln.get("dir", (1, 0))
            vertical = abs(dy) > abs(dx)
            for sp in ln.get("spans", []):
                txt = sp.get("text", "").strip()
                if not txt:
                    continue
                x0, y0, x1, y1 = sp["bbox"]
                # spans keep their words together; split horizontal spans into words by character share
                words = txt.split()
                if vertical or len(words) == 1:
                    out.append({"text": txt if vertical else words[0], "conf": 99.0, "vertical": vertical,
                                "bbox": [x0 / pw, y0 / ph, x1 / pw, y1 / ph]})
                    continue
                n = len(txt)
                pos = 0
                for w in words:
                    i = txt.index(w, pos)
                    a, b2 = i / n, (i + len(w)) / n
                    out.append({"text": w, "conf": 99.0, "vertical": False,
                                "bbox": [(x0 + a * (x1 - x0)) / pw, y0 / ph, (x0 + b2 * (x1 - x0)) / pw, y1 / ph]})
                    pos = i + len(w)
    return out


def _ocr(meta) -> tuple[list[dict], list[dict], str]:
    """(horizontal words, vertical words, source). Words: {"text","bbox" (normalised),"conf"}."""
    from bp.sheets import ocr_words

    path = meta.get("path") or meta.get("image")
    if str(path).lower().endswith(".pdf"):
        ws = _pdf_words(path, meta.get("page", 0), meta.get("w", 1), meta.get("h", 1))
        if len(ws) > 30:
            return [w for w in ws if not w["vertical"]], [w for w in ws if w["vertical"]], "pdf-text"
    w = meta.get("w") or 2000
    scale = 3.0 if w < 3000 else (2.0 if w < 6000 else 1.0)
    hor = ocr_words(meta, scale=scale, psm=11)
    if not hor:
        return [], [], "none"
    # rotated pass for vertical dimension strings (text reading bottom-to-top)
    ver = []
    try:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = None
        rp = Path(meta.get("_slab_cache_dir") or Path(meta["image"]).parent) / "slab_rot90.png"
        if not rp.exists():
            Image.open(meta["image"]).convert("L").rotate(-90, expand=True).save(rp)
        rmeta = {"image": str(rp)}
        for x in ocr_words(rmeta, scale=scale, psm=11):
            a0, b0, a1, b1 = x["bbox"]  # in the rotated image (rotated clockwise): x' = 1 - y, y' = x
            ver.append({"text": x["text"], "conf": x["conf"], "vertical": True,
                        "bbox": [b0, 1 - a1, b1, 1 - a0]})
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
            if -0.5 * h < gap < 1.2 * h and ov > 0 and abs(ln["bbox"][0] - last[0]) < 6 * h:
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
    if re.search(r"TOP FACE|\bT\.?F\.?\b|TOP\b", t):
        faces.append("top")
    if re.search(r"BOTTOM FACE|\bB\.?F\.?\b", t):
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
def _gray(meta, max_side=3200):
    import cv2

    g = cv2.imread(meta["image"], cv2.IMREAD_GRAYSCALE)
    f = 1.0
    if max(g.shape) > max_side:
        f = max_side / max(g.shape)
        g = cv2.resize(g, (round(g.shape[1] * f), round(g.shape[0] * f)), interpolation=cv2.INTER_AREA)
    return g, f


def _zones(g):
    """Slab zones: list of {"mask" (bool HxW), "panels": [masks]}. See module doc, step 4."""
    import cv2
    import numpy as np

    H, W = g.shape
    S = max(H, W)
    d = cv2.dilate((g < 200).astype(np.uint8), np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats((1 - d).astype(np.uint8), connectivity=4)
    min_a = 0.003 * W * H
    k = max(9, round(S * 0.011)) | 1
    ker = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    panels = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < min_a or x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1:
            continue
        m = (lab[y:y + h, x:x + w] == i).astype(np.uint8)
        mo = cv2.morphologyEx(m, cv2.MORPH_OPEN, ker)
        n2, l2, s2, _ = cv2.connectedComponentsWithStats(mo, connectivity=4)
        for j in range(1, n2):
            if s2[j, 4] < min_a:
                continue
            pm = np.zeros((H, W), np.uint8)
            pm[y:y + h, x:x + w] = (l2 == j)
            # restore the full extent (the opening rounds corners): component pixels near the opened part
            pm = cv2.dilate(pm, ker) & (lab == i).astype(np.uint8)
            panels.append(pm)
    if not panels:
        return [], d
    # merge panels separated by thin lines only
    r = max(3, round(S * 0.0025))
    kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    dil = [cv2.dilate(p, kd) for p in panels]
    parent = list(range(len(panels)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a in range(len(panels)):
        for b in range(a + 1, len(panels)):
            if (dil[a] & dil[b]).sum() > 2 * r:
                parent[find(a)] = find(b)
    groups: dict = {}
    for i in range(len(panels)):
        groups.setdefault(find(i), []).append(i)
    zones = []
    kc = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * r + 3, 2 * r + 3))
    for idx in groups.values():
        m = np.zeros((H, W), np.uint8)
        for i in idx:
            m |= panels[i]
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kc)
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        m = np.zeros((H, W), np.uint8)
        cv2.drawContours(m, cs, -1, 1, -1)
        zones.append({"mask": m, "panels": [panels[i] for i in idx]})
    return zones, d


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


def _outward_offsets(g, zmask, pts, others, d):
    """Per polygon edge, distance (px) from the inner face to the outer face of the edge beam: scan outward along
    samples of the edge, last mark before a long blank run. Shared walls (another zone beyond) count half."""
    import numpy as np

    H, W = g.shape
    S = max(H, W)
    dark = g < 200
    maxd = max(20, round(S * 0.02))
    blank = max(6, round(S * 0.004))
    offs = []
    n = len(pts)
    area2 = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy) or 1
        # outward normal: for a CCW polygon in image coords (y down), area2 < 0 ... pick by testing the mask
        nx, ny = dy / L, -dx / L
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        tx, ty = int(round(mx + nx * 4)), int(round(my + ny * 4))
        if 0 <= tx < W and 0 <= ty < H and zmask[ty, tx]:
            nx, ny = -nx, -ny
        vals, shared = [], 0
        for t in np.linspace(0.1, 0.9, 15):
            sx, sy = x0 + dx * t, y0 + dy * t
            last, run, hit_other = 0, 0, False
            for s in range(1, maxd):
                px, py = int(round(sx + nx * s)), int(round(sy + ny * s))
                if not (0 <= px < W and 0 <= py < H):
                    break
                if others[py, px]:
                    hit_other = True
                    break
                if dark[py, px]:
                    last, run = s, 0
                else:
                    run += 1
                    if run >= blank and last > 0:
                        break
            if hit_other:
                shared += 1
                vals.append(s / 2)
            else:
                vals.append(last)
        v = float(np.median(vals)) if vals else 0.0
        offs.append((v, shared > len(vals) / 2, (nx, ny)))
    return offs


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
    bold = ((g < 110) & (zmask > 0)).astype(np.uint8)
    Lh, Lv = max(15, int((x1 - x0) * 0.5)), max(15, int((y1 - y0) * 0.5))
    hl = cv2.morphologyEx(bold, cv2.MORPH_OPEN, np.ones((2, Lh), np.uint8))
    vl = cv2.morphologyEx(bold, cv2.MORPH_OPEN, np.ones((Lv, 2), np.uint8))
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
    for o, x, y, w, h in cuts:
        if o == "H":
            cut[max(0, y - 2):y + h + 2, :] = 0 if False else cut[max(0, y - 2):y + h + 2, :]
            cut[max(0, y - 2):y + h + 2, x - 3:x + w + 3] = 0
        else:
            cut[y - 3:y + h + 3, max(0, x - 2):x + w + 2] = 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(cut.astype(np.uint8), connectivity=4)
    big = [i for i in range(1, n) if st[i, 4] > 0.02 * zmask.sum()]
    return max(1, len(big)), cuts


def _hatch(g, union_mask):
    """Hatched (diagonal-line) pads inside the slab zones: list of (bbox px, area px)."""
    import cv2
    import numpy as np

    S = max(g.shape)
    dark = (g < 200).astype(np.uint8)
    L = max(7, round(S * 0.005))
    k1 = np.eye(L, dtype=np.uint8)
    k2 = np.fliplr(k1).copy()
    diag = cv2.morphologyEx(dark, cv2.MORPH_OPEN, k1) | cv2.morphologyEx(dark, cv2.MORPH_OPEN, k2)
    r = max(7, round(S * 0.006)) | 1
    den = cv2.blur(diag.astype(np.float32), (r, r))
    m = ((den > 0.10) & (union_mask > 0)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((r, r), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((r, r), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=4)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < (S * 0.012) ** 2:
            continue
        cs, _ = cv2.findContours((lab == i).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cs, key=cv2.contourArea)
        poly = cv2.approxPolyDP(c, 2.5, True)[:, 0, :].tolist()
        out.append({"bbox": [int(x), int(y), int(x + w), int(y + h)], "area_px": float(a), "poly": poly})
    return out


# ----------------------------------------------------------------------------------------------- scale
def _scale_from_dims(hor, ver, W, H):
    """mm per px (median of consecutive-pair estimates within dimension chains) and the dimension list."""
    import numpy as np

    dims = []
    for ws, vertical in ((hor, False), (ver, True)):
        for w in ws:
            v = _num(w["text"])
            if v is None or v < 50 or v > 200000 or w.get("conf", 99) < 50:
                continue
            x0, y0, x1, y1 = w["bbox"]
            dims.append({"v": v, "vertical": vertical, "cx": (x0 + x1) / 2 * W, "cy": (y0 + y1) / 2 * H,
                         "bbox": w["bbox"]})
    est = []
    for vertical in (False, True):
        ds = [d for d in dims if d["vertical"] == vertical]
        a_key, c_key = ("cx", "cy") if vertical else ("cy", "cx")
        a_key, c_key = ("cx", "cy") if vertical else ("cy", "cx")
        # chains: same cross coordinate (+-4 px)
        ds.sort(key=lambda d: d[a_key])
        chains, cur = [], []
        for d in ds:
            if cur and abs(d[a_key] - cur[-1][a_key]) > 5:
                chains.append(cur)
                cur = []
            cur.append(d)
        if cur:
            chains.append(cur)
        for ch in chains:
            ch.sort(key=lambda d: d[c_key])
            for a, b in zip(ch, ch[1:]):
                gap = b[c_key] - a[c_key]
                if gap > 5:
                    est.append((a["v"] + b["v"]) / 2 / gap)
    if len(est) < 3:
        return None, dims, 0
    e = np.array(est)
    med = float(np.median(e))
    good = e[np.abs(e / med - 1) < 0.03]
    return (float(np.median(good)) if len(good) else med), dims, int(len(good))


def _snap(L_mm, dims, tol=0.02):
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
    full_text = "\n".join(b["text"] for b in blocks)

    # slab types
    types = []
    for b in blocks:
        ty = _parse_type(b["text"])
        if ty:
            ty.update({"text": b["text"], "bbox": b["bbox"]})
            types.append(ty)

    # scale
    k, dims, n_scale = _scale_from_dims(hor, ver, W, H)
    scale_src = f"{n_scale} dimension-string pairs" if k else None

    # zones
    zones, _d = _zones(g)
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

    eps = max(2.0, S * 0.0015)
    out_zones = []
    for i, z in enumerate(zones):
        others = np.zeros_like(g, dtype=bool)
        for j, z2 in enumerate(zones):
            if j != i:
                others |= z2["mask"] > 0
        pts = _rect_poly(z["mask"], eps)
        if len(pts) < 4:
            continue
        offs = _outward_offsets(g, z["mask"], pts, others, _d)
        gross = _offset_poly(pts, offs)
        n_pan, cuts = _cj_panels(g, z["mask"])
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
    for m in re.finditer(r"([A-Z][A-Z ]{2,40}?)\s+TRENCH\s+LENGTH\s*[-=:]?\s*(\d[\d,]*)", full_text.upper()):
        trenches.append({"name": m.group(1).strip().title() + " trench", "length_mm": int(m.group(2).replace(",", ""))})
    tl_blocks = [b for b in blocks if "TRENCH" in b["text"].upper()]
    sump_blocks = [b for b in blocks if re.search(r"\bSUMP\b", b["text"].upper())]
    sumps = []
    for b in sump_blocks:
        m = re.search(r"SUMP\s*(\d{3,4})\s*[X×x]\s*(\d{3,4})\s*[X×x]\s*(\d{2,4})", b["text"].upper())
        sumps.append({"text": b["text"], "bbox": b["bbox"], "dims": [int(v) for v in m.groups()] if m else None})
    cj_words = [w for w in hor + ver if re.fullmatch(r"C\.?J\.?", w["text"].upper())]
    sc = re.search(r"SCALE\s*:?\s*1\s*:\s*(\d+)", full_text.upper())
    hatch_note = next((b for b in blocks if re.search(r"SHADED|HATCH", b["text"].upper())), None)
    res = {"v": 1, "src": src, "W": W, "H": H, "f": f, "k": k, "scale_src": scale_src,
           "scale_note": f"1:{sc.group(1)}" if sc else None, "types": types, "zones": out_zones,
           "pads": pads, "trenches": trenches, "trench_blocks": [b["bbox"] for b in tl_blocks],
           "trench_labels": [{"text": b["text"], "bbox": b["bbox"]} for b in tl_blocks],
           "sumps": sumps, "cj_words": [w["bbox"] for w in cj_words],
           "hatch_note": hatch_note["text"] if hatch_note else None,
           "dims": [{"v": d["v"], "vertical": d["vertical"], "bbox": d["bbox"]} for d in dims], "cost_usd": cost,
           "text": full_text}
    meta["slab"] = res
    return res


# ----------------------------------------------------------------------------------------------- answer helpers
def _m2(px, k):
    return px * k * k / 1e6


def _norm_pts(pts, W, H):
    return [[round(x / W, 5), round(y / H, 5)] for x, y in pts]


def _zone_explain(z, a, k, dims):
    """'19,800 x 12,000 mm = 237.6 m2' when the zone is a rectangle whose sides match printed dimensions."""
    xs = [p[0] for p in z["gross"]]
    ys = [p[1] for p in z["gross"]]
    w_mm, h_mm = (max(xs) - min(xs)) * k, (max(ys) - min(ys)) * k
    if len(z["gross"]) == 4:
        dw = _snap(w_mm, [d for d in dims if not d["vertical"]])
        dh = _snap(h_mm, [d for d in dims if d["vertical"]])
        if dw and dh:
            area = dw["v"] * dh["v"] / 1e6
            return area, f"{dw['v']:,} × {dh['v']:,} mm = {area:.2f} m² (sides match the printed dimensions)", [dw, dh]
        return a, f"{w_mm:,.0f} × {h_mm:,.0f} mm (measured) = {a:.2f} m²", []
    # rectilinear: main rectangle + rest
    return a, f"rectilinear outline, {len(z['gross'])} corners, bbox {w_mm:,.0f} × {h_mm:,.0f} mm, measured {a:.2f} m²", []


def _zone_area(z, A):
    k = A["k"]
    a_meas = _m2(z["gross_px"], k)
    a, how, used = _zone_explain(z, a_meas, k, A["dims"])
    if abs(a - a_meas) / max(a_meas, 1e-9) > 0.03:
        a, how, used = a_meas, f"measured {a_meas:.2f} m²", []
    return a, how, used


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


def _res(answer, conf, expl, ev, A, path_suffix=""):
    return {"answer": answer, "confidence": round(conf, 2), "explanation": expl, "evidence": ev,
            "method": METHOD + (f"-{path_suffix}" if path_suffix else ""), "cost_usd": round(A.get("cost_usd", 0.0), 5)}


def _text_ev(bbox, label):
    return {"kind": "text", "page": 0, "bbox": [round(v, 5) for v in bbox], "label": label}


def _zone_ev(z, A, label, value):
    return {"kind": "polygon", "page": 0, "points": _norm_pts(z["gross"], A["W"], A["H"]), "label": label,
            "value": value}


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
            if hits and not re.search(r"\btotal|all|sum\b", ql):
                return _res(best["length_mm"] / 1000, conf0 + 0.1,
                            f"{best['name']}: {best['length_mm']:,} mm per the general notes "
                            f"(\"approximate trench lengths\")", ev, A, "trench")
            tot = sum(t["length_mm"] for t in A["trenches"])
            return _res(tot / 1000, conf0 + 0.05, " + ".join(f"{t['length_mm']:,}" for t in A["trenches"])
                        + f" mm = {tot:,} mm ({', '.join(t['name'] for t in A['trenches'])}; lengths from the notes)",
                        ev, A, "trench")
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
               "value": round(a, 2)} for i, (p, a) in enumerate(zip(A["pads"], areas))]
        return _res(round(tot, 1), conf0 * 0.55, f"{len(areas)} hatched areas measured at {k:.2f} mm/px: "
                    + " + ".join(f"{a:.1f}" for a in areas) + f" = {tot:.1f} m²"
                    + (f" (legend: {A['hatch_note'][:80]})" if A.get("hatch_note") else ""), ev, A, "pads")

    # ---- reinforcement / thickness / elevation (text)
    if re.search(r"\bbars?\b|reinforc|rebar|mesh|thick|elevation|top of slab|\bt\.?o\.?s\b|\bel\b", ql) \
            and not re.search(r"\barea\b|how much|m2|m²|square", ql):
        sel, desc = _match_zones(q, A)
        tys = [(z, _type_of(z, A)) for z in (zones if sel is None else sel) if _type_of(z, A)]
        if not tys and A["types"]:
            tys = [(None, t) for t in A["types"]]
        if not tys:
            return None
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
        if not zones or not k:
            return None
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
            return _res(round(tot, 2), conf, f"{desc} slab: {expl}", ev, A, "area")
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
            return _res(ans, conf, expl, ev, A, "area-by-type")
        expl = " + ".join(f"{a:.2f}" for _, a, _, _ in rows) + f" = {tot:.2f} m² (" + " | ".join(
            f"[{_type_name(_type_of(z, A)) if _type_of(z, A) else 'untyped'}] {how}" for z, a, how, used in rows) + ")"
        return _res(round(tot, 2), conf, f"total slab area: {expl}", ev, A, "area")

    if re.search(r"how many .*(slab types|types of slab|slab zones)", ql):
        n = len({_type_name(t) for t in A["types"]})
        return _res(n, conf0, f"{n} distinct slab notes", [_text_ev(t["bbox"], t["text"][:80]) for t in A["types"]],
                    A, "note")
    return None
