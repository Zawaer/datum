"""Architectural floor plans (school / dormitory / office style sheets): doors and windows, room areas, areas by
colour zone, baseboard lengths, and anything printed in a table on the sheet.

* Scale: from the scale bar's printed numbers ("0 10m 20m", "0' 20' 40' 80'") read by OCR, else from the printed
  ratio (1:200) and the paper size in the title block (A0-A4), else none (areas then abstain).
* Doors / windows: the CubiCasa YOLO detector (bp/cubicasa) transfers well to clean CAD plans once the sheet is
  resampled to the pixel density it was trained at (~50 px per metre); every detection is a numbered box.
* Rooms: free space enclosed by dark linework (walls, glazing lines, door leaves and swings; detected doors are
  closed off), each labelled with the OCR'd words inside it. Area = pixel count / (px per m)². Baseboard =
  room perimeter minus the widths of the doors on its boundary, with the arithmetic in the explanation.
* Colour zones: a legend (swatch + name) is read; pixels of each swatch colour (thin lines closed) are measured.
* Printed tables (ROOM COUNT / SQUARE FOOTAGE / schedules): bp/sheets/textqa.py (OCR lines + Haiku citing ids).
"""
from __future__ import annotations

import math
import re
import threading

import numpy as np

from bp import sheets
from bp.sheets import textqa

FT = 0.3048
PAPER_MM = {"A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297), "A4": (297, 210),
            "ANSI D": (864, 559), "ANSI E": (1118, 864), "ARCH D": (914, 610), "ARCH E": (1219, 914)}
DET_PX_PER_M = 53.0  # resample to this before the detector (CubiCasa training plans are ~40-80 px/m)
_lock = threading.RLock()
_model = None


def detect(meta) -> float:
    s = sheets.kw_score(meta, "arch")
    if meta.get("kind") in ("slab", "piping"):
        s = min(s, 0.3)
    return s


# --------------------------------------------------------------------------------------------- question intent
def intent(q: str) -> str:
    ql = q.lower()
    if re.search(r"baseboard|skirting|base board|jalkalista|sockelleiste|plinth", ql):
        return "baseboard"
    if re.search(r"\b(door|doors|doorway)\b", ql) and re.search(r"how many|count|number", ql):
        return "doors" if not re.search(r"\bwindows?\b", ql) else "doors_windows"
    if re.search(r"\bwindows?\b", ql) and re.search(r"how many|count|number", ql):
        return "windows"
    if re.search(r"how many|count|number of", ql) and re.search(r"room|classroom|office|toilet|store|dorm", ql):
        return "rooms_count"
    if re.search(r"area|square f|\bsf\b|sq\.? ?ft|m²|m2|footage|floor space", ql):
        return "area"
    if re.search(r"perimeter", ql):
        return "baseboard"
    return "text"


# ------------------------------------------------------------------------------------------------------- scale
def _image(meta, gray=True):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(meta["image"])
    return im.convert("L" if gray else "RGB")


def words(meta):
    if "_arch_words" not in meta:
        scale = 2.0 if max(meta["w"], meta["h"]) < 3000 else 1.0
        meta["_arch_words"] = sheets.ocr_words(meta, scale=scale, min_conf=35)
    return meta["_arch_words"]


def scale(meta) -> dict | None:
    """{"px_per_m", "how", "evidence"} or None."""
    if "_arch_scale" in meta:
        return meta["_arch_scale"]
    W = meta["w"]
    out = None
    ws = words(meta)
    # 1) scale bar: numbers with a unit ("10m", "20'") on one line, plus a "0" left of them
    cands = []
    for w in ws:
        m = re.fullmatch(r"(\d{1,4})\s*(m|M|'|’|ft)", w["text"].strip())
        if m:
            cands.append((float(m.group(1)), "m" if m.group(2) in "mM" else "ft", w))
    best = None
    for unit in ("m", "ft"):
        cs = [c for c in cands if c[1] == unit and c[0] > 0]
        for c in cs:
            cy = (c[2]["bbox"][1] + c[2]["bbox"][3]) / 2
            row = [d for d in cs if abs((d[2]["bbox"][1] + d[2]["bbox"][3]) / 2 - cy) < 0.006]
            zeros = [w for w in ws if re.fullmatch(r"[0Oo]\s*('|’|m)?", w["text"].strip())
                     and abs((w["bbox"][1] + w["bbox"][3]) / 2 - cy) < 0.006 and w["bbox"][2] < c[2]["bbox"][0]]
            if not zeros or not row:
                continue
            z = max(zeros, key=lambda w: w["bbox"][0])  # the nearest 0 to the left
            far = max(row, key=lambda d: d[0])
            zx = (z["bbox"][0] + z["bbox"][2]) / 2
            fx = (far[2]["bbox"][0] + far[2]["bbox"][2]) / 2
            if fx <= zx:
                continue
            px = (fx - zx) * W
            val_m = far[0] * (1.0 if unit == "m" else FT)
            if px / val_m < 1:
                continue
            k = (len(row), far[0])
            if best is None or k > best[0]:
                best = (k, px / val_m, f"scale bar '0' to '{far[2]['text']}' = {px:.0f} px",
                        [z["bbox"], far[2]["bbox"]])
    if best:
        out = {"px_per_m": best[1], "how": best[2], "boxes": best[3]}
    # 2) printed ratio + paper size
    ratio = None
    m = re.search(r"1\s*:\s*(\d{2,4})", meta.get("scale") or "")
    if m:
        ratio = int(m.group(1))
    paper = None
    txt = " ".join(w["text"] for w in ws)
    pm = re.search(r"\b(?:ISO\s*)?(A[0-4])\b", txt)
    if pm:
        paper = pm.group(1)
    if ratio and paper:
        pw = max(PAPER_MM[paper])
        ppm = max(meta["w"], meta["h"]) / pw * 1000 / ratio
        if out is None:
            out = {"px_per_m": ppm, "how": f"printed scale 1:{ratio} on an {paper} sheet", "boxes": []}
        else:
            dev = abs(out["px_per_m"] / ppm - 1)
            out["check"] = f"agrees with 1:{ratio} on {paper} within {100 * dev:.1f} %" if dev < 0.03 else \
                f"differs from 1:{ratio} on {paper} by {100 * dev:.0f} %"
            if dev < 0.03:
                out["px_per_m"] = ppm  # the printed ratio is exact; the bar reading only confirms it
                out["how"] += f"; 1:{ratio} on {paper}"
    meta["_arch_scale"] = out
    return out


def metric(meta) -> bool:
    u = meta.get("units")
    if u in ("metric", "imperial"):
        return u == "metric"
    return not re.search(r"\d+'\s*-\s*\d+\"", " ".join(w["text"] for w in words(meta)))


# --------------------------------------------------------------------------------------------------- detector
def _det_model():
    global _model
    with _lock:
        if _model is None:
            from bp.cubicasa.infer import load

            _model = load("cache/cubicasa/weights/best.pt")
        return _model


def detections(meta):
    """[(cls, score, bbox normalised)] for the whole sheet, at the detector's pixel density."""
    if "_arch_det" in meta:
        return meta["_arch_det"]
    import tempfile

    from bp.cubicasa.infer import predict

    sc = scale(meta)
    im = _image(meta, gray=False)
    f = DET_PX_PER_M / sc["px_per_m"] if sc else min(1.0, 6000 / max(im.size))
    f = min(f, 2.0)
    if abs(f - 1) > 0.05:
        from PIL import Image

        im = im.resize((max(1, round(im.width * f)), max(1, round(im.height * f))), Image.LANCZOS)
    with tempfile.NamedTemporaryFile(suffix=".png") as tf:
        im.save(tf.name)
        with _lock:
            dets = predict(_det_model(), tf.name, "t1024", conf=0.25)
    meta["_arch_det"] = dets
    meta["_arch_det_scale"] = f
    return dets


def _in_frame(meta, b):
    """Drop detections in the title block / legend / notes area: keep those inside the drawn building's extent
    (the bounding box of the thick wall mass), padded."""
    ext = building_extent(meta)
    if ext is None:
        return True
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return ext[0] - 0.02 <= cx <= ext[2] + 0.02 and ext[1] - 0.02 <= cy <= ext[3] + 0.02


def count_symbols(meta, what: str, thr: float = 0.35):
    dets = [d for d in detections(meta) if d[0] == what and d[1] >= thr and _in_frame(meta, d[2])]
    return dets


# ------------------------------------------------------------------------------------------------------- rooms
def _work(meta):
    """(dark mask at work resolution, factor work/original, px_per_m at work res)."""
    if "_arch_work" in meta:
        return meta["_arch_work"]
    from PIL import Image

    sc = scale(meta)
    im = _image(meta)
    f = 1.0
    if sc:
        f = min(1.0, 45.0 / sc["px_per_m"])  # ~45 px per metre is plenty for areas within ~1 %
    if f < 0.98:
        im = im.resize((round(im.width * f), round(im.height * f)), Image.LANCZOS)
    a = np.asarray(im)
    dark = a < 120  # walls, glazing, door leaves, text; furniture is drawn grey and stays out
    meta["_arch_work"] = (dark, f, (sc["px_per_m"] * f) if sc else None)
    return meta["_arch_work"]


def building_extent(meta):
    if "_arch_ext" in meta:
        return meta["_arch_ext"]
    import cv2

    dark, f, ppm = _work(meta)
    k = max(3, int(round((ppm or 40) * 0.15)))  # walls are >= ~0.15 m thick; lines and text are thinner
    thick = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(thick, 8)
    H, W = dark.shape
    big = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] > 0.0005 * W * H]
    if not big:
        meta["_arch_ext"] = None
        return None
    x0 = min(st[i, 0] for i in big) / W
    y0 = min(st[i, 1] for i in big) / H
    x1 = max(st[i, 0] + st[i, 2] for i in big) / W
    y1 = max(st[i, 1] + st[i, 3] for i in big) / H
    meta["_arch_ext"] = (x0, y0, x1, y1)
    return meta["_arch_ext"]


def rooms(meta):
    """[{"label", "area_m2", "perimeter_m", "points" (normalised polygon), "bbox", "doors": [door bboxes]}]."""
    if "_arch_rooms" in meta:
        return meta["_arch_rooms"]
    import cv2

    dark, f, ppm = _work(meta)
    if ppm is None:
        meta["_arch_rooms"] = []
        return []
    H, W = dark.shape
    bar = dark.copy()
    doors = count_symbols(meta, "door", 0.3)
    for _, _, b in doors:  # close each detected door's opening (its box), so rooms do not leak through it
        x0, y0, x1, y1 = int(b[0] * W), int(b[1] * H), int(math.ceil(b[2] * W)), int(math.ceil(b[3] * H))
        cv2.rectangle(bar.view(np.uint8), (x0, y0), (x1, y1), 1, max(1, int(ppm * 0.05)))
    # thin gaps (a wall end that misses its neighbour by a pixel) closed with a small dilation
    bar = cv2.dilate(bar.astype(np.uint8), np.ones((3, 3), np.uint8))
    free = (bar == 0).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(free, 4)
    ext = building_extent(meta)
    min_px = 1.0 * ppm * ppm  # rooms >= 1 m²
    lab_words = [w for w in words(meta) if re.search(r"[A-Za-z]{2,}", w["text"])]
    out = []
    for i in range(1, n):
        a = st[i, cv2.CC_STAT_AREA]
        x, y, w, h = st[i, 0], st[i, 1], st[i, 2], st[i, 3]
        if a < min_px or x == 0 or y == 0 or x + w >= W or y + h >= H:
            continue
        if a > 0.25 * W * H:
            continue
        if ext and not (ext[0] - 0.01 <= x / W and (x + w) / W <= ext[2] + 0.01 and ext[1] - 0.01 <= y / H
                        and (y + h) / H <= ext[3] + 0.01):
            continue
        m = lab[y:y + h, x:x + w] == i
        cs0, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        filled = np.zeros_like(m, np.uint8)
        cv2.drawContours(filled, cs0, -1, 1, -1)
        filled = filled.astype(bool) | m
        holes = (filled & ~m).astype(np.uint8)
        # big enclosed holes (a core inside a hall) are not floor; text and symbols are
        hn, _, hst, _ = cv2.connectedComponentsWithStats(holes, 4)
        area_px = int(filled.sum())
        area_px -= sum(int(hst[j, cv2.CC_STAT_AREA]) for j in range(1, hn) if hst[j, cv2.CC_STAT_AREA] > 2.0 * ppm * ppm)
        # label = OCR words inside the filled region
        lw = []
        for wd in lab_words:
            cx, cy = (wd["bbox"][0] + wd["bbox"][2]) / 2 * W - x, (wd["bbox"][1] + wd["bbox"][3]) / 2 * H - y
            if 0 <= cx < w and 0 <= cy < h and filled[int(cy), int(cx)]:
                lw.append(wd)
        if not lw:
            continue
        lw.sort(key=lambda d: (round(d["bbox"][1] * 300), d["bbox"][0]))
        label = re.sub(r"\s+", " ", " ".join(d["text"] for d in lw)).strip(" |!’'")
        cs, _ = cv2.findContours(filled.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cs, key=cv2.contourArea)
        poly = cv2.approxPolyDP(c, max(1.0, 0.05 * ppm), True)[:, 0, :]
        per_px = cv2.arcLength(poly.reshape(-1, 1, 2), True)
        pts = [[(px + x) / W, (py + y) / H] for px, py in poly]
        bb = [x / W, y / H, (x + w) / W, (y + h) / H]
        # doors on this room's boundary: the box overlaps the room's dilated mask edge
        rd = []
        for _, _, b in doors:
            bx0, by0, bx1, by1 = b[0] * W - x, b[1] * H - y, b[2] * W - x, b[3] * H - y
            ix0, iy0 = max(0, int(bx0) - 3), max(0, int(by0) - 3)
            ix1, iy1 = min(w, int(math.ceil(bx1)) + 3), min(h, int(math.ceil(by1)) + 3)
            if ix1 > ix0 and iy1 > iy0 and filled[iy0:iy1, ix0:ix1].any():
                rd.append(b)
        out.append({"label": label, "area_m2": area_px / ppm ** 2, "perimeter_m": per_px / ppm, "points": pts,
                    "bbox": bb, "doors": rd})
    meta["_arch_rooms"] = out
    return out


def _door_width_m(meta, b):
    _, f, ppm = _work(meta)
    H, W = _work(meta)[0].shape
    return max((b[2] - b[0]) * W, (b[3] - b[1]) * H) / ppm


def match_rooms(rs, question: str):
    """Rooms whose label best matches the question (all rooms with the best word overlap)."""
    q = question.lower()
    stop = {"the", "of", "what", "is", "area", "floor", "room", "rooms", "in", "on", "this", "plan", "how", "many",
            "much", "total", "metres", "meters", "linear", "baseboard", "baseboards", "skirting", "length", "needed",
            "for", "m2", "m²", "square", "a", "all", "level", "sheet", "drawing", "there", "are", "do", "we", "need",
            "give", "me", "and", "with", "by", "shown", "each", "per", "its", "s"}
    qt = {t for t in re.findall(r"[a-z]+", q) if t not in stop and len(t) > 1}
    if not qt:
        return [], set()
    scored = []
    for r in rs:
        lt = set(re.findall(r"[a-z]+", r["label"].lower()))
        hit = len(qt & lt) + 0.5 * sum(1 for t in qt for u in lt if len(t) > 3 and (t.startswith(u[:4]) and u.startswith(t[:4])) and t != u)
        if hit:
            scored.append((hit, r))
    if not scored:
        return [], qt
    top = max(s for s, _ in scored)
    return [r for s, r in scored if s == top and top >= max(1, 0.6 * len(qt))], qt


# -------------------------------------------------------------------------------------------------- colour zones
def legend(meta):
    """[(name, rgb, text bbox)] of colour swatches left of legend text lines."""
    im = _image(meta, gray=False)
    a = np.asarray(im)
    H, W = a.shape[:2]
    lines = sheets.ocr_lines(words(meta))
    out = []
    for ln in lines:
        b = ln["bbox"]
        if not re.search(r"[A-Za-z]{3,}", ln["text"]):
            continue
        h = (b[3] - b[1]) * H
        y = int((b[1] + b[3]) / 2 * H)
        x1 = int(b[0] * W) - int(0.6 * h)
        x0 = max(0, x1 - int(3 * h))
        if x1 <= x0:
            continue
        patch = a[max(0, y - int(h * 0.25)):y + int(h * 0.25) + 1, x0:x1].reshape(-1, 3).astype(int)
        if len(patch) < 10:
            continue
        med = np.median(patch, 0)
        sat = med.max() - med.min()
        uni = np.mean(np.abs(patch - med).sum(1) < 30)
        if uni > 0.7 and (sat > 12 or 150 < med.mean() < 245):  # a flat colour (incl. light grey) swatch
            out.append((re.sub(r"^[^A-Za-z0-9]+", "", ln["text"]).strip(), tuple(int(v) for v in med), b))
    return out


def colour_areas(meta):
    import cv2

    if "_arch_colours" in meta:
        return meta["_arch_colours"]
    sc = scale(meta)
    leg = legend(meta)
    if not sc or len(leg) < 2:
        meta["_arch_colours"] = None
        return None
    a = np.asarray(_image(meta, gray=False)).astype(int)
    H, W = a.shape[:2]
    ppm = sc["px_per_m"]
    out = []
    for name, rgb, tb in leg:
        d = np.abs(a - np.array(rgb)).sum(2)
        m = (d < 24).astype(np.uint8)
        # the swatches themselves and the legend block are not floor
        lx0, ly0 = int(min(t[2][0] for t in leg) * W) - 200, int(min(t[2][1] for t in leg) * H) - 40
        lx1, ly1 = int(max(t[2][2] for t in leg) * W) + 10, int(max(t[2][3] for t in leg) * H) + 40
        m[max(0, ly0):ly1, max(0, lx0):lx1] = 0
        k = max(3, int(ppm * 1.0))  # close furniture / fixtures / wall lines drawn over the fill (~1 m)
        mc = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        mc = cv2.morphologyEx(mc, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        cs, _ = cv2.findContours(mc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        mc = np.zeros_like(mc)
        cv2.drawContours(mc, cs, -1, 1, -1)  # white furniture inside a zone is still that zone's floor
        n, lab, st, _ = cv2.connectedComponentsWithStats(mc, 8)
        polys, tot = [], 0.0
        for i in range(1, n):
            if st[i, cv2.CC_STAT_AREA] < 4 * ppm * ppm:  # specks and the key plan's tiny copies stay out? (>= 4 m²)
                continue
            # key plans are small copies away from the main drawing: kept out by the size filter on the far side
            area = st[i, cv2.CC_STAT_AREA] / ppm ** 2
            cs, _ = cv2.findContours((lab == i).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            c = max(cs, key=cv2.contourArea)
            poly = cv2.approxPolyDP(c, 2.0, True)[:, 0, :]
            polys.append({"points": [[px / W, py / H] for px, py in poly], "area_m2": area})
            tot += area
        out.append({"name": name, "rgb": rgb, "text_bbox": tb, "area_m2": tot, "parts": polys})
    meta["_arch_colours"] = out
    return out


# -------------------------------------------------------------------------------------------------------- answer
def _ev_box(b, label, value=None, kind="box"):
    return {"kind": kind, "bbox": [round(v, 5) for v in b], "label": label, "value": value}


def _fmt_area(m2, is_metric):
    if is_metric:
        return round(m2, 1), "m²"
    return int(round(m2 / FT ** 2)), "SF"


SUBMODULES = {  # intent -> specialist modules (bp/sheets/<name>.py, each answer(path, question, meta)), in order
    "doors": ["openings"], "windows": ["openings"], "doors_windows": ["openings"],
    "area": ["zones", "rooms"], "rooms_count": ["zones", "rooms"], "baseboard": ["rooms"], "text": ["zones"],
}


def answer(path, question, meta):
    """Dispatcher: the specialist modules for the question's intent first (openings / rooms / zones), then the
    printed text (textqa), then this module's own fallback implementation below."""
    import importlib

    it = intent(question)
    tried = []
    for name in SUBMODULES.get(it, []):
        try:
            mod = importlib.import_module(f"bp.sheets.{name}")
        except ImportError:
            continue
        r = mod.answer(path, question, meta)
        if r is not None and r.get("answer") is not None:
            r.setdefault("method", f"sheets-{name}")
            return r
        if r is not None:
            tried.append(r)
    r = _answer_builtin(path, question, meta, it)
    if (r is None or r.get("answer") is None) and tried:
        return max(tried, key=lambda x: bool(x.get("not_found")))  # keep a specialist's "not on this drawing"
    return r


def _answer_builtin(path, question, meta, it):
    if it in ("doors", "windows", "doors_windows"):
        return _answer_count(meta, it)
    if it == "text":
        return None  # notes / dimensions / title block: the generic reader (text layer or grounded vision) is better
    if it == "area" or it == "rooms_count":
        # a printed table / schedule / dimension answers first when the sheet has one
        if it != "rooms_count" or (meta.get("classify") or {}).get("has_tables"):
            r = textqa.answer(meta, question)
            if r and r.get("answer") is not None and r.get("confidence", 0) >= 0.5:
                return r
        if it == "area":
            return _answer_area(meta, question)
        if it == "rooms_count":
            return _answer_rooms_count(meta, question)
        return None
    if it == "baseboard":
        return _answer_baseboard(meta, question)
    return None


def _answer_count(meta, it):
    what = {"doors": ["door"], "windows": ["window"], "doors_windows": ["door", "window"]}[it]
    sc = scale(meta)
    ev, parts = [], []
    for w in what:
        ds = count_symbols(meta, w)
        ds.sort(key=lambda d: (round((d[2][1] + d[2][3]) / 2 * 40), d[2][0]))
        for i, (_, s, b) in enumerate(ds, 1):
            ev.append(_ev_box(b, f"{w} {i}", 1))
        parts.append(f"{len(ds)} {w}{'s' if len(ds) != 1 else ''}")
    n = len(ev)
    conf = 0.65 if sc else 0.45
    if not sc:
        note = "no scale found, so the sheet was read at a default size (less reliable)"
    else:
        note = f"sheet resampled to {DET_PX_PER_M:.0f} px/m ({sc['how']})"
    expl = (f"{', '.join(parts)} found by the plan-symbol detector (trained on residential plans, run on this sheet "
            f"in overlapping tiles; {note}). Each box is one counted item; double doors count as one door, and every "
            f"glazed panel between wall piers counts as one window")
    ans = n if len(what) == 1 else ", ".join(parts)
    return {"answer": ans, "confidence": conf, "evidence": ev, "cost_usd": 0.0,
            "method": f"sheets-arch-detector-{'+'.join(what)}", "explanation": expl}


def _scale_ev(sc):
    return [_ev_box(b, "scale read here", None, "text") for b in sc.get("boxes") or []]


def _answer_area(meta, question):
    sc = scale(meta)
    if not sc:
        return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": "sheets-arch-noscale",
                "explanation": "no printed scale bar or scale ratio + paper size found, so areas cannot be measured"}
    is_metric = metric(meta)
    ql = question.lower()
    # (b) colour-coded zones with a legend
    cols = colour_areas(meta)
    if cols:
        hit = [c for c in cols if c["name"] and all(t in ql for t in re.findall(r"[a-z]{4,}", c["name"].lower())
                                                    if t not in ("floor", "area"))]
        if re.search(r"colou?r|legend|zone|module|categor|each type|by type", ql):
            hit = hit or cols
        if hit:
            ev, rows = [], []
            for c in hit:
                v, u = _fmt_area(c["area_m2"], is_metric)
                rows.append(f"{c['name']}: {v:,} {u}")
                ev.append(_ev_box(c["text_bbox"], f"legend: {c['name']}", None, "text"))
                for k, p in enumerate(c["parts"], 1):
                    pv, _ = _fmt_area(p["area_m2"], is_metric)
                    ev.append({"kind": "polygon", "points": p["points"], "label": f"{c['name']} part {k}: {pv:,} {u}",
                               "value": round(p["area_m2"], 2) if is_metric else None})
            tot = sum(c["area_m2"] for c in hit)
            v, u = _fmt_area(tot, is_metric)
            ans = (v if is_metric else f"{v:,} SF") if len(hit) == 1 else "; ".join(rows)
            return {"answer": ans, "confidence": 0.25, "evidence": ev + _scale_ev(sc), "cost_usd": 0.0,
                    "method": "sheets-arch-colour",
                    "explanation": f"area of the legend colour(s), measured from the coloured pixels (furniture lines "
                                   f"closed) at {sc['px_per_m']:.2f} px/m ({sc['how']}); measured on the drawing, so "
                                   f"expect a few % error versus a schedule: " + "; ".join(rows)}
    # (c) rooms by label
    rs = rooms(meta)
    if not rs:
        return None
    total_q = re.search(r"total|gross|whole|entire|all rooms|overall|building|level|floor area\b", ql) and \
        not match_rooms(rs, question)[0]
    sel, qt = match_rooms(rs, question)
    if not sel and not total_q:
        return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": "sheets-arch-noroom",
                "explanation": f"no room labelled like '{' '.join(sorted(qt))}' was found on this plan",
                "not_found": {"kind": "room", "asked": " ".join(sorted(qt)),
                              "available": sorted({r["label"] for r in rs})[:60]}}
    if total_q:
        sel = rs
    ev = []
    tot = 0.0
    for r in sel:
        v, u = _fmt_area(r["area_m2"], is_metric)
        ev.append({"kind": "polygon", "points": r["points"], "label": f"{r['label']}: {v} {u}",
                   "value": round(r["area_m2"], 2) if is_metric else None})
        tot += r["area_m2"]
    v, u = _fmt_area(tot, is_metric)
    expl = (f"{len(sel)} room{'s' if len(sel) > 1 else ''} labelled "
            f"{', '.join(sorted({r['label'] for r in sel}))[:200]}: " if not total_q else
            f"all {len(sel)} labelled rooms: ") + \
        " + ".join(f"{_fmt_area(r['area_m2'], is_metric)[0]}" for r in sel[:30]) + \
        (" + ..." if len(sel) > 30 else "") + f" = {v} {u}; measured inside the walls at {sc['px_per_m']:.1f} px/m " \
        f"({sc['how']}{'; ' + sc['check'] if sc.get('check') else ''})"
    conf = 0.6 if len(sel) == 1 else 0.5
    if total_q:
        conf = 0.35
        expl += "; corridors and rooms without a readable label may be missing"
    return {"answer": v if is_metric else f"{v:,} SF", "confidence": conf, "evidence": ev + _scale_ev(sc),
            "cost_usd": 0.0, "method": "sheets-arch-rooms", "explanation": expl}


def _answer_rooms_count(meta, question):
    rs = rooms(meta)
    sel, qt = match_rooms(rs, question)
    if not sel:
        return None
    ev = [{"kind": "polygon", "points": r["points"], "label": f"{r['label']} {i}", "value": 1}
          for i, r in enumerate(sel, 1)]
    return {"answer": len(sel), "confidence": 0.55, "evidence": ev, "cost_usd": 0.0, "method": "sheets-arch-rooms-count",
            "explanation": f"{len(sel)} enclosed rooms whose label matches '{' '.join(sorted(qt))}' "
                           f"({', '.join(sorted({r['label'] for r in sel}))[:160]})"}


def _answer_baseboard(meta, question):
    sc = scale(meta)
    if not sc:
        return None
    is_metric = metric(meta)
    rs = rooms(meta)
    sel, qt = match_rooms(rs, question)
    if not sel:
        if re.search(r"total|all|whole|entire|building|level", question.lower()):
            sel = rs
        else:
            return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": "sheets-arch-noroom",
                    "explanation": f"no room labelled like '{' '.join(sorted(qt))}' was found on this plan",
                    "not_found": {"kind": "room", "asked": " ".join(sorted(qt)),
                                  "available": sorted({r["label"] for r in rs})[:60]}}
    ev, rows, tot = [], [], 0.0
    for r in sel:
        dw = [_door_width_m(meta, b) for b in r["doors"]]
        L = max(0.0, r["perimeter_m"] - sum(dw))
        tot += L
        rows.append(f"{r['label']}: perimeter {r['perimeter_m']:.1f} m - {len(dw)} door opening"
                    f"{'s' if len(dw) != 1 else ''} ({' + '.join(f'{d:.2f}' for d in dw) or '0'} m) = {L:.1f} m")
        ev.append({"kind": "polygon", "points": r["points"], "label": f"{r['label']}: {L:.1f} m of baseboard",
                   "value": None})
        for k, b in enumerate(r["doors"], 1):
            ev.append(_ev_box(b, f"door opening {k} ({_door_width_m(meta, b):.2f} m, no baseboard)", None))
    val = round(tot, 1) if is_metric else f"{tot / FT:,.0f} LF"
    expl = "; ".join(rows[:12]) + (" ..." if len(rows) > 12 else "") + \
        (f"; total {tot:.1f} m" if len(rows) > 1 else "") + \
        f". Perimeter measured inside the walls at {sc['px_per_m']:.1f} px/m ({sc['how']})"
    return {"answer": val, "confidence": 0.5 if len(sel) == 1 else 0.4, "evidence": ev + _scale_ev(sc),
            "cost_usd": 0.0, "method": "sheets-arch-baseboard", "explanation": expl}
