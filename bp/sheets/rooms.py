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
MAX_WINDOW_M = 6.0   # widest glazed gap closed as a window
MIN_ROOM_M2 = 0.8
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
    return np.asarray(Image.open(image).convert("L"))


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
def scale_info(image, words=None, meta=None) -> dict | None:
    """{"px_per_m", "how", "boxes": [normalised bboxes of the bar / labels]} or None."""
    g = _gray(image)
    H, W = g.shape
    ws = _words(image, words, meta)
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
    out = best
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
def _gaps(wall, thin, axis, ppm):
    """Gap bands in wall lines along `axis` (1: horizontal walls, 0: vertical walls).
    Returns [(mask_slice_box, component mask, length_m, glazed)] in work pixels."""
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
    leafy = thin & (wall == 0)
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
        t = thin[g["r0"]:g["r1"] + 1, g["c0"]:g["c1"] + 1]
        glazed = bool(t.size) and t.mean(axis=1).max() >= 0.85
        if not glazed and length > MAX_DOOR_M * ppm:
            continue  # too wide for a door
        # an unglazed gap with no door leaf drawn at either jamb is an open niche / archway: kept as "open",
        # closed only when it lets a room leak to the outside (a door drawn half open, a bifold, a missing leaf)
        leaf = glazed or _has_leaf(leafy, g, length, ppm)
        x, y, w, h = g["c0"], g["r0"], g["c1"] - g["c0"] + 1, thick
        if axis == 0:
            x, y, w, h = y, x, h, w
        out.append(((x, y, w, h), length / ppm, glazed, leaf))
    return out


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
    disc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    wall = cv2.morphologyEx(ink, cv2.MORPH_OPEN, disc)
    # drop specks (text dots, arrow heads stay but are harmless)
    n, lab, st, _ = cv2.connectedComponentsWithStats(wall, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 0.04 * ppm * ppm
    wall = keep[lab].astype(np.uint8)

    barrier = wall.copy()
    doors, open_gaps = [], []
    for axis in (1, 0):
        for (x, y, w, h), length, glazed, leaf in _gaps(wall, thin, axis, ppm):
            if not leaf:
                open_gaps.append((x, y, w, h, length, axis))
                continue
            barrier[y:y + h, x:x + w] = 1
            if not glazed:
                doors.append({"width_m": round(length, 2), "box": (x, y, w, h), "axis": axis})

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
            doors.append({"width_m": round(length, 2), "box": (x, y, w, h), "axis": axis})
            shut += 1
    if shut:
        free, n, lab, st, border = components()
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
    if with_labels:
        _label(rooms, lab, f, W, H, _words(image, words, meta), image, src_ppm=px_per_m,
               vector=bool(words is None and meta and meta.get("words")))
    if wall_px < 3:  # low resolution: tiny unlabelled pockets are mostly fragments between door swings
        rooms = [r for r in rooms if r["label"] or r["area_m2"] >= 1.5]
    for r in rooms:
        r.pop("_i", None)
        r.pop("_c", None)
    rooms.sort(key=lambda r: -r["area_m2"])
    return {"rooms": rooms, "scale": sc or {"px_per_m": px_per_m, "how": "given"}, "px_per_m": px_per_m,
            "wall_px": round(wall_px, 1),
            "doors": doors, "footprint_m2": round(footprint, 1),
            "footprint_polys": [[[round(p[0][0] / f, 1), round(p[0][1] / f, 1)] for p in c] for c in big]}


_LABEL_OK = re.compile(r"[A-Za-z]{2,}")


def _label(rooms, lab, f, W, H, words, image=None, src_ppm=100.0, vector=False):
    """Label each room with the OCR words whose centre lies in it (stacked lines joined top to bottom). Rooms
    the page-wide OCR left unlabelled get a second, upscaled OCR pass on their own crop."""
    by_i = {r["_i"]: r for r in rooms}
    sh, sw = lab.shape

    def room_of(bb):
        cx = (bb[0] + bb[2]) / 2 * W * f
        cy = (bb[1] + bb[3]) / 2 * H * f
        return int(lab[min(sh - 1, max(0, int(cy))), min(sw - 1, max(0, int(cx)))])

    per: dict[int, list] = {}
    for w in words:
        i = room_of(w["bbox"])
        if i in by_i:
            per.setdefault(i, []).append(w)
    if image is not None and not isinstance(image, np.ndarray) and not vector:
        cscale = min(6.0, max(2.0, 240.0 / src_ppm))
        for r in rooms:
            if (r["_i"] in per and src_ppm >= 40) or r["area_m2"] < 1.5:
                continue
            ws = _crop_words(image, r["bbox"], W, H, scale=cscale)
            ws = [w for w in ws if room_of(w["bbox"]) == r["_i"]]
            if ws:
                per[r["_i"]] = ws
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
        if core.lower().strip("'s") in ROOM_WORDS or core.lower() in ROOM_WORDS or \
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
    return None


def _cached(meta) -> dict:
    with _lock:
        if "_rooms_seg" not in meta:
            seg = segment(meta["image"], meta=meta)
            rs = [r for r in seg["rooms"] if r["area_m2"] >= 1.5]
            seg["cost_usd"] = 0.0
            if rs and sum(1 for r in rs if not r["label"]) > 0.4 * len(rs):
                try:
                    seg["cost_usd"] = vision_labels(meta["image"], seg["rooms"])
                except Exception:  # noqa: BLE001
                    pass
            meta["_rooms_seg"] = seg
        return meta["_rooms_seg"]


def _norm(s):
    s = re.sub(r"\(.*?\)", " ", s.lower())
    return [re.sub(r"(?<=[a-z]{3})s$", "", w) for w in re.findall(r"[a-z]+", s)]


SYN = {"wc": "toilet", "lavatory": "toilet", "restroom": "toilet", "bathroom": "toilet", "classe": "classroom",
       "storage": "store", "storeroom": "store", "office": "office", "corridors": "corridor"}
STOP = {"the", "of", "what", "is", "area", "areas", "floor", "room", "in", "on", "a", "an", "all", "total", "sum",
        "how", "much", "many", "metre", "meter", "linear", "baseboard", "skirting", "board", "for", "and", "this",
        "plan", "drawing", "sheet", "level", "square", "m", "sq", "give", "me", "list", "each", "per", "net",
        "gross", "excluding", "except", "without", "wet", "different", "do", "need", "we", "are", "there",
        "length", "lengths", "find", "calculate", "compute", "approximately", "size", "space", "spaces"}


def match_rooms(rooms, question):
    """(rooms whose label matches the question's room words, the words) - [] when the question names no room."""
    qw = [SYN.get(w, w) for w in _norm(question) if w not in STOP]
    qw = [w for w in qw if len(w) > 1]
    if not qw:
        return [], []
    scored = []
    for r in rooms:
        lw = {SYN.get(w, w) for w in _norm(r["label"])}
        hit = sum(1 for w in qw if w in lw)
        if hit:
            scored.append((hit, r))
    if not scored:
        return [], qw
    top = max(s for s, _ in scored)
    return [r for s, r in scored if s == top], qw


def _ev_poly(r, W, H, label, value):
    return {"kind": "polygon", "page": 0, "points": [[round(x / W, 5), round(y / H, 5)] for x, y in r["polygon"]],
            "label": label, "value": value}


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
    sc = seg["scale"]
    wpx = seg.get("wall_px") or 0
    cf = 1.0 if wpx >= 3 else 0.75 if wpx >= 2 else 0.5  # thin walls: openings and faces are less certain
    if "drawn" not in sc.get("how", "") and "printed" not in sc.get("how", ""):
        cf *= 0.9
    scale_txt = f"scale {sc['px_per_m']:.1f} px/m ({sc['how']}{'; ' + sc['check'] if sc.get('check') else ''})"
    ql = question.lower()
    sel, qw = match_rooms(rooms, question)
    named = bool(sel)
    if not named:
        if qw and not re.search(r"different|each|every|all|total|whole|overall|building|footprint|gross|room", ql):
            return None  # names something we don't have a label for: let the generic path try
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
            return {"answer": seg["footprint_m2"], "unit": "m²", "confidence": round(0.6 * cf, 2),
                    "method": "sheets-rooms-footprint",
                    "cost_usd": seg.get("cost_usd", 0.0), "evidence": ev + ev_scale,
                    "explanation": f"Gross footprint inside the outer wall line's outside face = {seg['footprint_m2']} m² "
                                   f"(net room areas sum to {net:.1f} m² over {len(rooms)} rooms); {scale_txt}."}
        tot = sum(r["area_m2"] for r in sel)
        ev = [_ev_poly(r, W, H, f"{r['label'] or 'unlabelled'} {r['area_m2']:.1f} m²", r["area_m2"]) for r in sel]
        if named and len(sel) == 1:
            r = sel[0]
            return {"answer": r["area_m2"], "unit": "m²", "confidence": round(0.7 * cf, 2),
                    "method": "sheets-rooms-area",
                    "cost_usd": seg.get("cost_usd", 0.0), "evidence": ev + ev_scale,
                    "explanation": f"{r['label']}: {round(r['area_m2'] * sc['px_per_m'] ** 2):.0f} px² / "
                                   f"({sc['px_per_m']:.1f} px/m)² = {r['area_m2']:.1f} m² (net, to wall faces); {scale_txt}."}
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
            return {"answer": round(tot, 1), "unit": "m²", "confidence": round(0.6 * cf, 2),
                    "method": "sheets-rooms-area-sum",
                    "cost_usd": seg.get("cost_usd", 0.0), "evidence": ev + ev_scale,
                    "explanation": f"{' / '.join(sorted(groups))}: {txt}; {scale_txt}."}
        listing = "; ".join(parts[:40])
        return {"answer": f"Total {tot:.0f} m² net over {len(sel)} rooms. " + listing, "value": round(tot, 1),
                "unit": "m²", "confidence": round(0.55 * cf, 2), "method": "sheets-rooms-area-list",
                "cost_usd": seg.get("cost_usd", 0.0),
                "evidence": ev + ev_scale,
                "explanation": f"Each room = its enclosed pixels / ({sc['px_per_m']:.1f} px/m)²; gross footprint "
                               f"{seg['footprint_m2']} m²; {unl} rooms carry no readable label; {scale_txt}."}
    # baseboard
    tot = sum(r["baseboard_m"] for r in sel)
    nd = sum(len(r["doors"]) for r in sel)
    dw = sum(d["width_m"] for r in sel for d in r["doors"])
    per = sum(r["perimeter_m"] for r in sel)
    ev = [_ev_poly(r, W, H, f"{r['label'] or 'unlabelled'}: {r['perimeter_m']:.1f} m outline − "
                            f"{sum(d['width_m'] for d in r['doors']):.1f} m doors = {r['baseboard_m']:.1f} m",
                   r["baseboard_m"]) for r in sel]
    seen = set()
    for r in sel:
        for d in r["doors"]:
            k = tuple(round(v) for v in d["bbox"])
            if k in seen:
                continue
            seen.add(k)
            ev.append({"kind": "box", "page": 0, "bbox": [d["bbox"][0] / W, d["bbox"][1] / H, d["bbox"][2] / W,
                                                          d["bbox"][3] / H],
                       "label": f"door opening {d['width_m']:.2f} m", "value": -d["width_m"]})
    what = (" / ".join(sorted({r["label"] for r in sel})) if named else f"all {len(sel)} rooms") + \
        (" (wet rooms excluded)" if excl else "")
    return {"answer": round(tot, 1), "unit": "m", "confidence": round((0.6 if named else 0.55) * cf, 2),
            "method": "sheets-rooms-baseboard", "cost_usd": seg.get("cost_usd", 0.0), "evidence": ev + ev_scale,
            "explanation": f"{what}: room outlines {per:.1f} m − {nd} door openings {dw:.1f} m = {tot:.1f} m of "
                           f"baseboard (windows not deducted, door openings measured on the wall line); {scale_txt}."}
