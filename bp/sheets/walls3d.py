"""Wall geometry of a raster floor plan for the 3D view (app/static/plan3d.js, served by /api/walls).

The wall mask is rooms.py's (dark pixels at rooms.WORK_PPM px/m, opened by a 3 px disc, specks dropped), and its
openings are rooms._gaps(): a glazed gap in a wall line is a window, an unglazed one with a leaf or swing drawn is a
door. Enclosed spaces (what the walls and closed openings shut off from the sheet edge) tell whether the walls look
like a building at all (`plausible`), and which wall pieces belong to it: wall clusters without enclosed rooms (title
block lettering, a north arrow, a legend) are dropped. The kept mask becomes simplified polygons with holes (cv2
contours + approxPolyDP), coarsened until they fit in `max_segments` edges. All coordinates are normalised to the
page ([0, 1] across its width and height), so they line up with the evidence boxes the answers carry.
"""
from __future__ import annotations

import time

import numpy as np

from bp.sheets import rooms

WALL_M = 0.2           # typical wall thickness: the scale guess when nothing printed gives one
MIN_PIECE_M = 0.6      # wall pieces smaller than this across (and under MIN_PIECE_M2) are lettering, not walls
MIN_PIECE_M2 = 0.12
BRIDGE_M = 3.0        # openings up to this wide are closed when testing which spaces the walls enclose


def gray(image) -> np.ndarray:
    """8-bit grayscale of an image path (cv2 decodes a 139 MP PNG in ~0.3 s) or array."""
    if isinstance(image, np.ndarray):
        return rooms._gray(image)
    import cv2

    g = cv2.imread(str(image), cv2.IMREAD_GRAYSCALE)
    return g if g is not None else rooms._gray(str(image))


def guess_px_per_m(g: np.ndarray) -> float | None:
    """Last-resort scale: the median thickness of the thick dark strokes taken as a WALL_M wall."""
    import cv2

    H, W = g.shape
    f = min(1.0, 4000 / max(H, W))
    s = cv2.resize(g, (max(1, round(W * f)), max(1, round(H * f))), interpolation=cv2.INTER_AREA) if f < 1 else g
    ink = cv2.morphologyEx((s < rooms.DARK).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    dist = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    # local maxima of the distance (the strokes' centre lines) of strokes at least 3 px thick
    ridge = dist[(dist >= 1.5) & (dist >= cv2.dilate(dist, np.ones((3, 3), np.uint8)) - 1e-3)]
    if ridge.size < 200:
        return None
    t = 2 * float(np.median(ridge)) / f  # stroke thickness in source px
    return t / WALL_M


def extract(g: np.ndarray, px_per_m: float, max_segments: int = 4000, mode: str = "auto") -> dict:
    """Wall polygons, doors and windows of a plan image (see the module doc). `g`: 8-bit grayscale.
    mode "solid": walls are filled (poché) strokes; "outline": walls drawn as two thin parallel lines (filled in
    between here); "auto": solid, and outline when the solid walls don't enclose a plausible building."""
    import cv2

    t0 = time.time()
    H, W = g.shape
    f = rooms.WORK_PPM / px_per_m
    ppm = px_per_m * f
    size = (max(1, round(W * f)), max(1, round(H * f)))
    # --- rooms.segment()'s wall mask and thin-line layer (same thresholds, same resampling)
    small = cv2.resize(g, size, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)
    ink = (small < rooms.DARK).astype(np.uint8)
    if f > 1.2:  # a low-resolution sheet: anti-aliased thin walls (1-2 source px) turn grey when upsampled; keep them
        ink |= cv2.resize((g < 160).astype(np.uint8), size, interpolation=cv2.INTER_NEAREST)
    del small
    _, dark = cv2.threshold(g, 127, 255, cv2.THRESH_BINARY_INV)
    thin = cv2.resize(dark, size, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_NEAREST) > 40
    del dark
    solid = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    if mode == "auto":  # hollow walls leave only their thin outlines in the solid mask: median ridge < 0.14 m
        t_solid = _stroke_m(solid, ppm)
        mode = "solid" if t_solid >= 0.14 else "outline"
        alt = "outline" if mode == "solid" else "solid"
    else:
        alt = None

    def run(m):
        w = solid if m == "solid" else solid | _outline_fill(thin, ppm)
        o = _build(_despeck(w, ppm), thin, ppm, size, (W, H), px_per_m, max_segments, outline=m == "outline")
        o["wall_style"] = m
        return o

    out = run(mode)
    if alt and not out["plausible"]:
        o2 = run(alt)
        if o2["plausible"] or o2["enclosed_m2"] > out["enclosed_m2"]:
            out = o2
    out["ms"] = round(1000 * (time.time() - t0))
    return out


def _stroke_m(mask, ppm) -> float:
    """Median thickness (m) of a mask's strokes, from the distance transform's ridge."""
    import cv2

    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    ridge = dist[(dist >= 1) & (dist >= cv2.dilate(dist, np.ones((3, 3), np.uint8)) - 1e-3)]
    return 2 * float(np.median(ridge)) / ppm if ridge.size else 0.0


def _despeck(wall, ppm):
    import cv2

    n, lab, st, _ = cv2.connectedComponentsWithStats(wall, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 0.04 * ppm * ppm
    return keep[lab].astype(np.uint8)


def _outline_fill(thin, ppm):
    """Walls drawn as outlines (two thin parallel lines 0.08-0.35 m apart, white or tinted between): the band
    between them, kept where it runs on for at least 0.6 m and is a few pixels thick (not a single line)."""
    import cv2

    t = thin.astype(np.uint8)
    k = max(3, round(0.35 * ppm))
    L = max(5, round(0.6 * ppm))
    out = np.zeros_like(t)
    for close_k, long_k, thick_k in (((k, 1), (1, L), (4, 1)), ((1, k), (L, 1), (1, 4))):
        # kernels as (rows, cols): close across the wall, then keep long bands at least 4 px across
        c = cv2.morphologyEx(t, cv2.MORPH_CLOSE, np.ones(close_k, np.uint8))
        c = cv2.morphologyEx(c, cv2.MORPH_OPEN, np.ones(long_k, np.uint8))
        c = cv2.morphologyEx(c, cv2.MORPH_OPEN, np.ones(thick_k, np.uint8))
        out |= c
    return out


def _build(wall, thin, ppm, size, full, px_per_m, max_segments, outline=False):
    import cv2

    sw, sh = size
    W, H = full
    # --- openings in the wall lines
    barrier = wall.copy()
    doors, windows = [], []
    # doorways and windows closed for the enclosure test: wall pieces running along an axis (a short line opening drops
    # the walls across it) are bridged along it over gaps up to BRIDGE_M. A low-resolution sheet loses door leaves and
    # glazing lines, so _gaps misses openings; the outline style skips _gaps (gaps between outline walls and filled
    # furniture are too noisy to show as doors / windows, and it is slow on thousands of thin pieces)
    s_ = max(3, round(0.3 * ppm))
    L = max(3, round((1.1 if outline else BRIDGE_M) * ppm))  # outline walls: table rulings would bridge too
    for line, span in (((1, s_), (1, L)), ((s_, 1), (L, 1))):
        along = cv2.morphologyEx(wall, cv2.MORPH_OPEN, np.ones(line, np.uint8))
        barrier |= cv2.morphologyEx(along, cv2.MORPH_CLOSE, np.ones(span, np.uint8))
    for axis in () if outline else (1, 0):
        for (x, y, w, h), length, glazed, leaf in rooms._gaps(wall, thin, axis, ppm):
            thick = (h if axis == 1 else w) / ppm
            if not leaf or length < 0.5 or thick < 0.08 or (not glazed and length > 2.4):
                continue
            barrier[y:y + h, x:x + w] = 1
            (windows if glazed else doors).append({"box": (x, y, w, h), "axis": axis, "width_m": round(length, 2)})
    # --- enclosed spaces
    free = (barrier == 0).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist())
    min_px = rooms.MIN_ROOM_M2 * ppm * ppm
    room = np.zeros(n, bool)
    for i in range(1, n):
        x, y, w, h = st[i, :4]
        frame = x < 0.04 * sw and x + w > 0.96 * sw and y < 0.04 * sh and y + h > 0.96 * sh  # the paper in a sheet frame
        if i not in border and not frame and st[i, cv2.CC_STAT_AREA] >= min_px and min(w, h) >= rooms.MIN_WIDTH_M * ppm:
            room[i] = True
    room_mask = room[lab]
    # buildings: clusters of walls + rooms; clusters with little enclosed area (lettering, logos, frames) are dropped
    solid = cv2.morphologyEx(((barrier > 0) | room_mask).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    nc, clab = cv2.connectedComponents(solid, connectivity=8)
    carea = np.bincount(clab[room_mask], minlength=nc).astype(float) / ppm ** 2
    keep_c = np.zeros(nc, bool)
    if nc > 1 and carea[1:].max() > 0:
        keep_c[1:] = carea[1:] >= max(8.0, 0.05 * carea[1:].max())
    inb = keep_c[clab]
    kept_wall = (wall > 0) & inb
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(kept_wall.astype(np.uint8), connectivity=8)
    big = np.zeros(n2, bool)
    big[1:] = (np.maximum(st2[1:, 2], st2[1:, 3]) >= MIN_PIECE_M * ppm) | (st2[1:, 4] >= MIN_PIECE_M2 * ppm * ppm)
    kept_wall = big[lab2].astype(np.uint8)
    in_rooms = room_mask & inb
    enclosed_m2 = float(in_rooms.sum()) / ppm ** 2
    rooms_n = int(len(np.unique(lab[in_rooms])))
    wall_m2 = float(kept_wall.sum()) / ppm ** 2
    ys, xs = np.nonzero(kept_wall)
    if xs.size:
        bx0, by0, bx1, by1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    else:
        bx0 = by0 = 0
        bx1, by1 = sw, sh
    # footprint: the kept clusters with their insides filled (gross area to the outer wall faces)
    ocs, _ = cv2.findContours(inb.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    footprint_m2 = sum(cv2.contourArea(c) for c in ocs) / ppm ** 2
    # --- polygons: contours of the kept mask, simplified until they fit
    # one-pixel jaggies (resampled diagonals, hatch ends) cost vertices for nothing
    smooth = cv2.morphologyEx(cv2.morphologyEx(kept_wall, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)),
                              cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cs, hier = cv2.findContours(smooth, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    eps, min_a = 0.035 * ppm, 0.0
    polys = []
    if cs:
        hier = hier[0]
        areas = np.array([cv2.contourArea(c) for c in cs])
        for _ in range(20):
            simp = [cv2.approxPolyDP(c, eps, True) if areas[i] >= min_a else None for i, c in enumerate(cs)]
            nseg = sum(len(s) for s in simp if s is not None and len(s) >= 3)
            if nseg <= max_segments:
                break
            eps *= 1.25
            min_a = max(min_a * 2, 0.05 * ppm * ppm)
        polys = []
        sx, sy = 1.0 / sw, 1.0 / sh

        def ring(c):
            return [[round((float(p[0][0]) + 0.5) * sx, 5), round((float(p[0][1]) + 0.5) * sy, 5)] for p in c]

        for i, c in enumerate(cs):
            if hier[i][3] >= 0 or simp[i] is None or len(simp[i]) < 3:
                continue  # holes are collected under their outer ring
            holes, j = [], hier[i][2]
            while j >= 0:
                if simp[j] is not None and len(simp[j]) >= 3:
                    holes.append(ring(simp[j]))
                j = hier[j][0]
            polys.append({"outer": ring(simp[i]), "holes": holes})
        nseg = sum(len(p["outer"]) + sum(len(h) for h in p["holes"]) for p in polys)
    else:
        nseg = 0

    def nbox(o):
        x, y, w, h = o["box"]
        return {"bbox": [round(x / sw, 5), round(y / sh, 5), round((x + w) / sw, 5), round((y + h) / sh, 5)],
                "axis": "h" if o["axis"] == 1 else "v", "width_m": o["width_m"]}

    # openings of the kept building only (gaps between title-block letters are not doors)
    def inside(o):
        x, y, w, h = o["box"]
        return bool(inb[min(sh - 1, y + h // 2), min(sw - 1, x + w // 2)])

    doors = [nbox(o) for o in doors if inside(o)]
    windows = [nbox(o) for o in windows if inside(o)]
    plausible = bool(rooms_n >= 3 and enclosed_m2 >= 20 and enclosed_m2 >= 0.3 * footprint_m2 and len(polys) >= 1)
    return {"size": [W, H], "px_per_m": round(px_per_m, 3), "work_ppm": round(ppm, 2),
            "page_m": [round(W / px_per_m, 3), round(H / px_per_m, 3)],
            "walls": polys, "doors": doors[:3000], "windows": windows[:3000],
            "bounds": [round(float(bx0) / sw, 5), round(float(by0) / sh, 5), round(float(bx1) / sw, 5), round(float(by1) / sh, 5)],
            "rooms_n": rooms_n, "enclosed_m2": round(enclosed_m2, 1), "footprint_m2": round(footprint_m2, 1), "wall_m2": round(wall_m2, 1),
            "plausible": plausible, "segments": int(nseg), "simplify_m": round(eps / ppm, 3)}


# ------------------------------------------------------------------------------------------------- uploads
VERSION = 2


def _scale_for(g: np.ndarray, path: str, page: int, folder, ocr_wait: float):
    """(px_per_m on `g`, how, final). Order: what the sheet specialists already measured (rooms / arch / openings),
    the scale bar or printed ratio (PDF text layer, or the upload's OCR if it is ready within `ocr_wait` s), a
    PDF page's printed ratio on its real paper size, the wall thickness. final=False when the OCR was still running."""
    import concurrent.futures as cf
    import json
    import re
    from pathlib import Path

    from bp import sheets

    H, W = g.shape
    folder = Path(folder)
    meta = None
    if (folder / f"sheet_meta_p{page}.json").exists():
        try:
            meta = sheets.build_meta(path, page, cache_dir=folder, do_classify=False)
        except Exception:  # noqa: BLE001
            meta = None
    k = W / float(meta["w"]) if meta and meta.get("w") else 1.0  # meta's image -> g
    if meta:
        for key, how in (("_rooms_seg", "rooms"), ("_arch_scale", "arch")):
            v = meta.get(key)
            ppm = (v or {}).get("px_per_m") or ((v or {}).get("scale") or {}).get("px_per_m")
            if ppm:
                return float(ppm) * k, f"scale read for the {how} answers", True
        img = Path(meta.get("image") or "")
        for f in sorted(img.parent.glob("openings_*.json")) if img.name else []:
            try:
                o = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if o.get("px_per_m") and o.get("scale_from") == "printed scale":
                return float(o["px_per_m"]) * k, "scale read for the door count", True
    words = sheets.pdf_words(path, page) if path.lower().endswith(".pdf") else []
    final = True
    sc = None
    if len(words) >= 20:
        sc = rooms.scale_info(g, words=words)
    elif meta is not None:
        ex = cf.ThreadPoolExecutor(1)
        fut = ex.submit(rooms.scale_info, g, None, meta)  # waits on the upload's own OCR (shared cache) if running
        try:
            sc = fut.result(timeout=ocr_wait)
        except cf.TimeoutError:
            final = False
        except Exception:  # noqa: BLE001
            sc = None
        ex.shutdown(wait=False)
    if sc and sc.get("px_per_m"):
        return float(sc["px_per_m"]), sc.get("how") or "scale bar", True
    if path.lower().endswith(".pdf"):  # printed ratio on the page's real paper size
        txt = " ".join(w["text"] for w in words) + " " + str((meta or {}).get("scale") or "")
        m = re.search(r"\b1\s*:\s*(\d{2,4})\b", txt)
        if m:
            try:
                import pymupdf

                with pymupdf.open(path) as doc:
                    pw_m = doc[page].rect.width / 72 * 0.0254
                return W / pw_m / int(m.group(1)), f"printed scale 1:{m.group(1)} on the PDF's paper size", True
            except Exception:  # noqa: BLE001
                pass
    ppm = guess_px_per_m(g)
    return ppm, f"estimated: walls taken as {WALL_M} m thick", final


def for_upload(path: str, page: int = 0, max_segments: int = 4000, ocr_wait: float = 8.0) -> tuple[dict, bool]:
    """extract() for an upload's page (path: the stored working file, raster or PDF), on its most detailed raster
    (a raster's .full.png copy, a PDF page's sheet render). Returns (result, final): cache it only when final."""
    from pathlib import Path

    from bp import sheets

    p = Path(path)
    folder = p.parent
    if p.suffix.lower() == ".pdf":
        img, _, _ = sheets._image_for(str(p), page, folder)  # the same render the sheet specialists read
    else:
        full = p.with_name(p.name + ".full.png")
        img = str(full if full.exists() else p)
    g = gray(img)
    ppm, how, final = _scale_for(g, str(p), page, folder, ocr_wait)
    if not ppm or not np.isfinite(ppm) or ppm <= 0:
        return {"walls": [], "plausible": False, "why": "no scale"}, True
    # a scale far off what the walls say (a misread bar) would make 3 m walls 30 m tall: trust the walls then
    est = guess_px_per_m(g)
    if est and not 0.25 <= ppm / est <= 4:
        ppm, how = est, f"estimated: walls taken as {WALL_M} m thick (the read scale {how!r} disagreed)"
    out = extract(g, ppm, max_segments=max_segments)
    out["scale"] = {"px_per_m": round(ppm, 3), "how": how, "estimated": how.startswith("estimated")}
    out["version"] = VERSION
    return out, final
