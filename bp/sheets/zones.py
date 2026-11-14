"""Colour-coded zones and on-sheet schedules (areas, room counts) on architectural sheets.

Two complementary answers, each with its evidence on the drawing:

1. The sheet's own tables (preferred, exact). Words are OCR'd once (tesseract via bp.sheets.ocr_words, shared cache
   with the other sheet modules; Claude Haiku reads table crops only when tesseract finds nothing), and every
   "LABEL = 6,095 SF" / "TOTAL = 144 DORMS" line becomes a row {label, value, unit, table, bbox}. A question picks
   rows (Haiku over the parsed rows, keyword fallback offline); sums are recomputed here, SF <-> m² on request,
   and every number used is a box on the table.
2. Colour zones measured on the plan (cross-check, or the answer when no table states it). Legend swatches (flat
   colour box left of a name) give the categories; the plan is segmented by colour in Lab space, the building
   footprint (all zone colours, walls/furniture lines closed, small holes filled, large ones such as "open to
   below" kept out) is split between the categories by nearest coloured pixel, and areas follow from a scale
   calibrated on the scale bar and checked against the longest printed dimension string. Zones are grouped into
   wings (west/east/north/south of the plan centre), so "measured 6,010 SF vs 6,095 SF on the schedule (-1.4 %)"
   can be reported per row.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from pathlib import Path

import numpy as np

from bp import sheets

log = logging.getLogger(__name__)

FT = 0.3048
SF_TO_M2 = FT * FT  # 0.09290304
AREA_UNITS = {"SF": "SF", "S.F.": "SF", "SF.": "SF", "SQFT": "SF", "FT2": "SF", "FT²": "SF", "GSF": "SF", "NSF": "SF",
              "M2": "m²", "M²": "m²", "SQM": "m²", "M2.": "m²"}
COUNT_UNITS = {"DORMS": "dorms", "DORM": "dorms", "ROOMS": "rooms", "ROOM": "rooms", "UNITS": "units", "UNIT": "units",
               "BEDS": "beds", "BED": "beds", "EA": "ea", "PCS": "pcs", "STALLS": "stalls", "SPACES": "spaces"}
NUM_RE = re.compile(r"^\(?(\d{1,3}(?:[,.]\d{3})+|\d+)(?:\.(\d+))?\)?$")
DIM_RE = re.compile(r"^(\d{1,4})['’]\s*[-.–]?\s*(\d{1,2})?(?:\s*(\d)/(\d))?\"?$")
STOP = {"what", "is", "the", "of", "a", "an", "on", "in", "this", "sheet", "plan", "drawing", "how", "much", "many",
        "area", "areas", "floor", "total", "square", "footage", "feet", "foot", "sf", "m2", "m²", "meters", "metres",
        "size", "big", "are", "there", "for", "and", "per", "each", "all", "its", "give", "me", "show", "by", "to",
        "level", "space", "sq", "ft", "different", "do", "does", "which", "has", "have", "with", "zone", "zones",
        "colour", "color", "coded", "measured", "measure", "legend", "category", "categories", "type", "types"}
WINGS = ("west", "east", "north", "south")
CONTEXT = set(WINGS) | {"wing", "total", "module", "building", "unit", "whole", "entire", "overall", "first",
                        "second", "third", "fourth", "ground", "upper", "lower", "combined", "together", "sum", "inside",
                        "within", "gros", "net", "approximately", "roughly", "about", "what", "calculate", "find",
                        "tell", "covered", "occupied", "used"}
ZONES_VERSION = 11  # bump when the measurement changes (invalidates the per-upload disk cache)
TOL_FRAC = 0.7  # colour tolerance as a fraction of the closest pair of legend / paper / ink colours
CLOSE_FT = 6.0  # zone fills are closed over walls, furniture and fixtures up to this size
CENTRE_BOX = 0.12  # |offset| / plan span under which a pixel is in the "centre" rather than a wing
WALL_FT = 1.0  # exterior wall thickness added around the coloured footprint (gross area to the outside face)


# ------------------------------------------------------------------------------------------------- small helpers
def _st(meta) -> dict:
    return meta.setdefault("zones", {})


def _cy(b):
    return (b[1] + b[3]) / 2


def _union(bs):
    return [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]


def _pad(b, d=0.0015):
    return [round(max(0.0, b[0] - d), 5), round(max(0.0, b[1] - d), 5), round(min(1.0, b[2] + d), 5),
            round(min(1.0, b[3] + d), 5)]


def _num(s):
    """'6,095' -> 6095, '26.562' (OCR'd thousands dot) -> 26562, '12.5' -> 12.5; None if not a number."""
    s = str(s).strip().replace(" ", "")
    m = NUM_RE.match(s)
    if not m:
        return None
    ip, frac = m.group(1), m.group(2)
    if re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", ip):
        ip = re.sub(r"[,.]", "", ip)
    v = float(ip + ("." + frac if frac else ""))
    return int(v) if v == int(v) and not frac else v


def _fmt(v, nd=0):
    if v is None:
        return "?"
    if nd == 0 or abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}"
    return f"{v:,.{nd}f}"


def _cache_file(meta) -> Path | None:
    img = meta.get("image")
    if not img:
        return None
    p = Path(img)
    try:
        st = p.stat()
    except OSError:
        return None
    return p.parent / f"zones_{p.stem}_{st.st_size}.json"


def _disk_get(meta, key):
    f = _cache_file(meta)
    if f and f.exists():
        try:
            return json.loads(f.read_text()).get(key)
        except (OSError, json.JSONDecodeError):
            return None
    return None


_disk_lock = threading.Lock()


def _disk_put(meta, key, val):
    f = _cache_file(meta)
    if not f:
        return
    with _disk_lock:
        _disk_put_locked(f, key, val)


def _disk_put_locked(f, key, val):
    try:
        d = json.loads(f.read_text()) if f.exists() else {}
    except (OSError, json.JSONDecodeError):
        d = {}
    d[key] = val
    try:
        f.write_text(json.dumps(d))
    except OSError:
        pass


def _image(meta, mode="RGB"):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(meta["image"]) as im:
        return im.convert(mode)


def words(meta) -> list[dict]:
    st = _st(meta)
    if "words" not in st:
        # a PDF text layer (meta["words"], exact) when there is one, else tesseract
        sc = 2.0 if max(meta.get("w", 0), meta.get("h", 0)) < 3000 else 1.0
        ws = sheets.words(meta, scale=sc, min_conf=35) if meta.get("image") or meta.get("words") else []
        st["words"] = ws if meta.get("words") else _dedupe_words(ws)
    return st["words"]


def _dedupe_words(ws: list[dict]) -> list[dict]:
    """OCR passes that overlap read some words twice ("SQUA" + "SQUARE", "WEST" + "WEST"): of two words whose
    boxes mostly overlap and whose texts are equal or one a prefix of the other, keep the longer."""
    out: list[dict] = []
    for w in sorted(ws, key=lambda w: (-len(w["text"]), -w.get("conf", 0))):
        b = w["bbox"]
        dup = False
        for k in out:
            c = k["bbox"]
            ix = min(b[2], c[2]) - max(b[0], c[0])
            iy = min(b[3], c[3]) - max(b[1], c[1])
            if ix <= 0 or iy <= 0:
                continue
            small = min((b[2] - b[0]) * (b[3] - b[1]), (c[2] - c[0]) * (c[3] - c[1]))
            t = w["text"].upper().rstrip(".,!")
            if ix * iy > 0.5 * small and (k["text"].upper().startswith(t) or (len(t) >= 3 and t in k["text"].upper())):
                dup = True
                break
        if not dup:
            out.append(w)
    return out


# ------------------------------------------------------------------------------------------------ table rows
def _vertical(w, aspect):
    """A word set vertically (rotated title-block text, vertical dimension strings): taller than wide."""
    b = w["bbox"]
    return len(w["text"]) > 2 and (b[3] - b[1]) > 1.3 * (b[2] - b[0]) * aspect  # ("0'", "8'" are tall but short)


def _rows_by_band(ws: list[dict], aspect: float = 1.0) -> list[list[dict]]:
    """Words grouped into baselines, each sorted left to right. A word joins the row band (median top/bottom of its
    words) it overlaps most vertically (>= half its height); a second pass reassigns every word to its best band,
    so a tall or misread neighbour seeding a row first does not split a table row."""
    def ov(b, band):
        inter = min(b[3], band[1]) - max(b[1], band[0])
        return inter / max(1e-9, min(b[3] - b[1], band[1] - band[0]))

    def bands(rows):
        out = []
        for r in rows:  # the band of the row's full-height words (underline junk read as "na", "ee" is short)
            mh = max(w["bbox"][3] - w["bbox"][1] for w in r)
            t = [w for w in r if w["bbox"][3] - w["bbox"][1] >= 0.5 * mh]
            out.append((float(np.median([w["bbox"][1] for w in t])), float(np.median([w["bbox"][3] for w in t]))))
        return out

    rows: list[list[dict]] = []
    bs: list[tuple] = []
    ws = [w for w in ws if not _vertical(w, aspect)]
    for w in sorted(ws, key=lambda w: _cy(w["bbox"])):
        best = max(range(len(rows)), key=lambda i: ov(w["bbox"], bs[i]), default=None)
        if best is not None and ov(w["bbox"], bs[best]) >= 0.5:
            rows[best].append(w)
            bs[best] = bands([rows[best]])[0]
        else:
            rows.append([w])
            bs.append((w["bbox"][1], w["bbox"][3]))
    for _ in range(2):
        bs = bands(rows)
        new: list[list[dict]] = [[] for _ in rows]
        for r_old in rows:
            for w in r_old:
                bi = max(range(len(rows)), key=lambda i: ov(w["bbox"], bs[i]))
                if ov(w["bbox"], bs[bi]) >= 0.5:
                    new[bi].append(w)
                else:
                    new.append([w])
        rows = [r for r in new if r]
    rows.sort(key=lambda r: float(np.median([_cy(w["bbox"]) for w in r])))
    return [sorted(r, key=lambda w: w["bbox"][0]) for r in rows]


def _rows_of_words(ws: list[dict], aspect: float = 1.0) -> list[list[dict]]:
    """Words grouped into baselines, each sorted left to right. Rows are chained left to right: a word joins the
    row whose last (rightmost) word it overlaps most vertically (>= half the smaller height), so a skewed scan's
    rows stay apart however wide the sheet is; a word much taller than the page's text (a stray mark read as
    "a") stays on its own instead of bridging two rows."""
    def ov(b, c):
        inter = min(b[3], c[3]) - max(b[1], c[1])
        return inter / max(1e-9, min(b[3] - b[1], c[3] - c[1]))

    ws = [w for w in ws if not _vertical(w, aspect)]
    if not ws:
        return []
    mh = float(np.median([w["bbox"][3] - w["bbox"][1] for w in ws]))
    rows: list[list[dict]] = []
    for w in sorted(ws, key=lambda w: w["bbox"][0]):
        b = w["bbox"]
        if b[3] - b[1] > 2.5 * mh:
            rows.append([w])
            continue
        best, bs = None, 0.5
        for r in rows:
            last = r[-1]["bbox"]
            if last[3] - last[1] > 2.5 * mh or last[2] > b[0] + 0.5 * (b[3] - b[1]) / aspect:
                continue
            o = ov(b, last)
            if o > bs or (best is not None and o == bs and last[2] > best[-1]["bbox"][2]):
                best, bs = r, o
        if best is None:
            rows.append([w])
        else:
            best.append(w)
    rows.sort(key=lambda r: float(np.median([_cy(w["bbox"]) for w in r])))
    return [sorted(r, key=lambda w: w["bbox"][0]) for r in rows]


def _unit_of(t: str):
    u = t.strip().upper().rstrip(":;,")
    if u in AREA_UNITS:
        return "area", AREA_UNITS[u]
    if u in COUNT_UNITS:
        return "count", COUNT_UNITS[u]
    return None, None


def parse_rows(ws: list[dict], aspect: float = 1.0, grouping=None) -> list[dict]:
    """Schedule rows from OCR words: [{"id", "label", "value", "unit", "kind", "table", "total", "bbox",
    "value_bbox"}]. A row is: label words, then (after a gap) a number and its unit on the same baseline.
    `aspect` = image width / height (word gaps are measured in text heights, horizontally)."""
    out = []
    for r in (grouping or _rows_by_band)(ws, aspect):
        hs = [w["bbox"][3] - w["bbox"][1] for w in r]
        md = float(np.median(hs))
        mh = float(np.percentile([x for x in hs if x <= 2.5 * md], 80))  # junk (underlines read as "na") is short
        r = [w for w in r if w["bbox"][3] - w["bbox"][1] <= 2.5 * mh]  # and stray symbols tall
        r = [w for w in r if w["bbox"][3] - w["bbox"][1] > 0.5 * mh or w["text"] in ("=", ":")]  # underline junk
        h = mh / aspect  # text height in x-normalised units
        i = 0
        while i < len(r):
            t = r[i]["text"]
            kind, unit = _unit_of(t)
            v = _num(t)
            # number + unit ("6,095 SF") or unit glued ("6,095SF")
            if v is None:
                m = re.fullmatch(r"([\d,.]+)\s*(SF|S\.F\.|M2|M²|DORMS|ROOMS)", t.strip(), re.I)
                if m and _num(m.group(1)) is not None:
                    v, (kind, unit) = _num(m.group(1)), _unit_of(m.group(2))
                    j_unit, j_num = i, i
                else:
                    i += 1
                    continue
            else:
                j_num = i
                nxt = r[i + 1] if i + 1 < len(r) else None
                if nxt and (nxt["bbox"][0] - r[i]["bbox"][2]) < 2.5 * h and _unit_of(nxt["text"])[0]:
                    kind, unit = _unit_of(nxt["text"])
                    j_unit = i + 1
                elif nxt is None and len(t) >= 2:
                    kind, unit, j_unit = "?", None, i  # unit lost by OCR: resolved by column alignment below
                else:
                    i += 1
                    continue
            # label: walk left from the number, first gap up to 10 text heights, then words closer than 2.2
            lab = []
            k = j_num - 1
            first = True
            has_eq = False
            edge = r[j_num]["bbox"][0]
            while k >= 0:
                w = r[k]
                gap = edge - w["bbox"][2]
                if gap > (30 * h if first else 2.2 * h) or _unit_of(w["text"])[0] or \
                        (_num(w["text"]) is not None and not first and re.fullmatch(r"[\d,.]{3,}", w["text"])):
                    break
                if w["text"].strip().endswith(("=", ":")):
                    has_eq = True
                if w["text"].strip() not in ("=", ":", "-", "—", "_"):
                    if not first or len(w["text"]) > 1 or w["text"].isalnum():
                        lab.insert(0, w)
                        first = False
                edge = w["bbox"][0]
                k -= 1
            # OCR junk inside labels: lone letters / marks ("WEST V WING", "\\") and stutters ("FIRST FIRST")
            lab = [w for w in lab if len(w["text"]) > 1 or w["text"].isdigit() or w["text"] in "&+"]
            def _junk(i_, w):
                t = w["text"].rstrip(":;.,").upper()
                later = [x["text"].upper() for x in lab[i_ + 1:]]
                return (i_ + 1 < len(lab) and later[0].startswith(t)) or \
                    (len(t) <= 4 and any(x.startswith(t) and x != t for x in later)) or \
                    bool(re.fullmatch(r"[A-Z][a-z]", w["text"]))  # "COMMON Si SPACE"
            lab = [w for i_, w in enumerate(lab) if not _junk(i_, w)]
            if not lab:
                i = j_unit + 1
                continue
            label = re.sub(r"\s*[=:]\s*$", "", " ".join(w["text"] for w in lab)).strip(" =:-_|")
            label = re.sub(r"\s+=\s*", " ", label)
            if not re.search(r"[A-Za-z]{3,}", label):
                i = j_unit + 1
                continue
            parts = lab + r[j_num:j_unit + 1]
            out.append({"label": label, "value": v, "unit": unit, "kind": kind, "num_x1": r[j_num]["bbox"][2],
                        "has_eq": has_eq, "_lab": lab,
                        "total": bool(re.search(r"\b(sub)?total\b", label, re.I)),
                        "bbox": _union([w["bbox"] for w in parts]), "value_bbox": _union([w["bbox"] for w in
                                                                                          r[j_num:j_unit + 1]]),
                        "label_bbox": _union([w["bbox"] for w in lab])})
            i = j_unit + 1
    # a number whose unit OCR dropped joins the column it is right-aligned with (and takes that column's unit)
    known = [x for x in out if x["kind"] != "?"]
    for x in [x for x in out if x["kind"] == "?"]:
        # (OCR may also have swallowed the unit into the number's box: then it ends where the units end)
        col = [y for y in known if min(abs(y["num_x1"] - x["num_x1"]), abs(y["value_bbox"][2] - x["num_x1"])) < 0.004
               and abs(y["label_bbox"][0] - x["label_bbox"][0]) < 0.01]
        if col:
            near = min(col, key=lambda y: abs(y["bbox"][1] - x["bbox"][1]))
            x["kind"], x["unit"] = near["kind"], near["unit"]
    out = [x for x in out if x["kind"] != "?"]
    # a schedule is a column: keep rows with another row right-aligned with them (or an explicit "label = value");
    # a lone "81 SF" room tag paired with some word to its left is not a table row
    def col(x):
        return [y for y in out if y is not x and abs(y["num_x1"] - x["num_x1"]) < 0.004
                and abs(y["bbox"][1] - x["bbox"][1]) < 0.15]
    out = [x for x in out if x["has_eq"] or col(x)]
    # labels start at the table's left edge: drop words of a neighbouring paragraph glued on the left
    for x in out:
        lefts = sorted(y["label_bbox"][0] for y in col(x))
        if lefts:
            edge = float(np.median(lefts))
            keep = [w for w in x["_lab"] if w["bbox"][0] >= edge - 0.004]
            if keep and len(keep) < len(x["_lab"]) and x["label_bbox"][0] < edge - 0.01:
                x["_lab"] = keep
                x["label"] = re.sub(r"\s*[=:]\s*$", "", " ".join(w["text"] for w in keep)).strip(" =:-_|")
                x["label_bbox"] = _union([w["bbox"] for w in keep])
                x["bbox"] = _union([x["label_bbox"], x["value_bbox"]])
                x["total"] = bool(re.search(r"\b(sub)?total\b", x["label"], re.I))
    for x in out:
        x.pop("_lab", None)
    out.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))
    _tables(out, ws)
    for n, x in enumerate(out):
        x["id"] = n
    return out


def _tables(rows, ws):
    """Group rows into tables (left-aligned labels, stacked) and name each by the heading line above it."""
    lines = sheets.ocr_lines(ws) if ws else []
    groups: list[list[dict]] = []
    for r in rows:
        for g in groups:
            last = g[-1]
            hh = last["bbox"][3] - last["bbox"][1]
            aligned = abs(r["label_bbox"][0] - g[0]["label_bbox"][0]) < 0.01 or \
                abs(r.get("num_x1", 0) - g[-1].get("num_x1", 1)) < 0.004
            if aligned and -0.6 * hh <= r["bbox"][1] - last["bbox"][3] < 5 * hh and r["kind"] == g[0]["kind"]:
                g.append(r)
                break
        else:
            groups.append([r])
    groups.sort(key=lambda g: g[0]["bbox"][1])
    for g in groups:
        top = g[0]
        hh = top["bbox"][3] - top["bbox"][1]
        # a group that starts right under a row of the same kind continues that table (OCR shifted its labels)
        above = [r for r in rows if r not in g and r.get("table") and r["kind"] == top["kind"]
                 and -0.6 * hh <= top["bbox"][1] - r["bbox"][3] < 3 * hh and abs(r["label_bbox"][0] - top["label_bbox"][0]) < 0.03]
        if above:
            for r in g:
                r["table"] = max(above, key=lambda r: r["bbox"][3])["table"]
            continue
        cand = [ln for ln in lines if ln["bbox"][3] <= top["bbox"][1] + 0.2 * hh
                and top["bbox"][1] - ln["bbox"][3] < 3.5 * hh and abs(ln["bbox"][0] - top["label_bbox"][0]) < 0.06
                and top["label_bbox"][0] - 0.01 < ln["bbox"][0] and not re.search(r"\d", ln["text"])]
        title = ""
        if cand:
            ln = max(cand, key=lambda ln: ln["bbox"][3])
            # tesseract may split the heading into pieces on the same baseline
            lx = top["label_bbox"][0]
            same = [x for x in lines if abs(_cy(x["bbox"]) - _cy(ln["bbox"])) < 0.5 * (ln["bbox"][3] - ln["bbox"][1])
                    and lx - 0.01 < x["bbox"][0] < lx + 0.12]
            same = [x for x in same if not re.search(r"\d", x["text"])] or [ln]
            title = " ".join(x["text"] for x in sorted(same, key=lambda x: x["bbox"][0]))
            title = re.sub(r"[^A-Za-z0-9 ()/&-]", "", title).strip()
        for r in g:
            r["table"] = title or ("SCHEDULE" if g[0]["kind"] == "area" else "COUNT")


VISION_ROWS = """This is a crop of a construction drawing sheet ({w}x{h} px). List every row of every table / schedule
in it that gives an AREA or a COUNT (e.g. "WEST WING DORMITORY = 6,095 SF", "TOTAL = 144 DORMS"). JSON only:
{{"rows": [{{"table": "<table heading>", "label": "<row label as printed>", "value": <number>, "unit": "<unit as
printed, e.g. SF, m2, DORMS>", "bbox": [<left>, <top>, <right>, <bottom>]}}]}} with bbox as integer pixels of this crop
around the whole row, e.g. "bbox": [812, 140, 1190, 162] (numbers, never the words). Empty list if there is no such
table."""


def _vision_rows(meta) -> tuple[list[dict], float]:
    """Fallback without tesseract: Haiku reads table rows on 2x2 tiles of the sheet (~$0.02)."""
    from bp.generic import llm

    if os.environ.get("BP_ZONES_LLM", "1") != "1":
        return [], 0.0
    im = _image(meta)
    W, H = im.size
    rows, cost = [], 0.0
    for ty in range(2):
        for tx in range(2):
            x0, y0 = int(tx * W * 0.48), int(ty * H * 0.48)
            x1, y1 = int(min(W, x0 + W * 0.52)), int(min(H, y0 + H * 0.52))
            crop = im.crop((x0, y0, x1, y1))
            f = min(1.0, 1568 / max(crop.size))
            small = crop.resize((int(crop.width * f), int(crop.height * f)))
            r = llm.ask(VISION_ROWS.format(w=small.width, h=small.height), [small], model="haiku",
                        tag="sheets-zones-rows", timeout=120)
            cost += r.get("cost_usd", 0.0)
            d = llm.parse_json(r["text"]) or {}
            for it in (d.get("rows") if isinstance(d, dict) else None) or []:
                try:
                    b = [float(v) for v in it["bbox"]]
                    v = _num(str(it["value"]).replace(" ", "")) if not isinstance(it["value"], (int, float)) \
                        else it["value"]
                except (KeyError, TypeError, ValueError):
                    continue
                kind, unit = _unit_of(str(it.get("unit", "")).replace(" ", ""))
                if v is None or not kind:
                    continue
                bb = [(x0 + b[0] / f) / W, (y0 + b[1] / f) / H, (x0 + b[2] / f) / W, (y0 + b[3] / f) / H]
                if any(abs(bb[1] - q["bbox"][1]) < 0.004 and abs(bb[0] - q["bbox"][0]) < 0.02 for q in rows):
                    continue  # the same row seen on two overlapping tiles
                lab = str(it.get("label", "")).strip(" =")
                rows.append({"label": lab, "value": v, "unit": unit, "kind": kind,
                             "total": bool(re.search(r"\b(sub)?total\b", lab, re.I)), "bbox": bb, "value_bbox": bb,
                             "label_bbox": bb, "table": str(it.get("table") or "SCHEDULE")})
    rows.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))
    for n, x in enumerate(rows):
        x["id"] = n
    return rows, cost


def _reread_rows(meta, ws, rs, aspect):
    """OCR misses a value now and then on scans ("EAST WING CIRCULATION = pended"): every text line that starts at
    a table's label column inside the table's height but gave no row is read again on its own (2x, one line)."""
    out = list(rs)
    for kind in ("area", "count"):
        tr = [r for r in rs if r["kind"] == kind]
        if len(tr) < 3:
            continue
        lx = float(np.median([r["label_bbox"][0] for r in tr]))
        rx = max(r["value_bbox"][2] for r in tr)
        rh = float(np.median([r["bbox"][3] - r["bbox"][1] for r in tr]))
        # a total row under the last one read (or a row above the first) is looked for too
        y0, y1 = min(r["bbox"][1] for r in tr) - 2.5 * rh, max(r["bbox"][3] for r in tr) + 4 * rh
        for line in _rows_of_words(ws, aspect):
            lw = [w for w in line if lx - 0.006 <= w["bbox"][0] <= rx]
            if not lw or not (y0 <= _cy(lw[0]["bbox"]) <= y1):
                continue
            if min(w["bbox"][0] for w in lw) > lx + 0.01 or not re.search(r"[A-Za-z]{3,}", " ".join(w["text"] for w in lw)):
                continue
            if any(abs(_cy(r["bbox"]) - _cy(lw[0]["bbox"])) < 0.5 * (r["bbox"][3] - r["bbox"][1]) for r in out):
                continue
            hh = max(w["bbox"][3] - w["bbox"][1] for w in lw)
            reg = [max(0.0, lx - 0.004), max(0.0, min(w["bbox"][1] for w in lw) - 0.3 * hh), min(1.0, rx + 0.004),
                   min(1.0, max(w["bbox"][3] for w in lw) + 0.3 * hh)]
            got = []
            for sc_, psm in ((2.0, 7), (3.0, 7), (3.0, 11)):
                try:
                    ww = [dict(w) for w in sheets.ocr_words(meta, region=reg, scale=sc_, psm=psm, min_conf=0)]
                except Exception:  # noqa: BLE001
                    ww = []
                for i_, w in enumerate(ww[1:], 1):  # the table's unit misread on a scan ("SE", "5F" for SF)
                    if kind == "area" and w["text"] in ("SE", "5F", "SP", "S.F", "SF,", "Sf") and \
                            _num(ww[i_ - 1]["text"]) is not None:
                        w["text"] = "SF"
                got = parse_rows(ww, aspect)
                if any(g["kind"] == kind for g in got):
                    break
            for g in got:
                if g["kind"] == kind:
                    g["reread"] = True
                    out.append(g)
    if len(out) > len(rs):
        out.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))
        _tables(out, ws)
        for n, x in enumerate(out):
            x["id"] = n
    return out


def rows(meta) -> list[dict]:
    st = _st(meta)
    if "rows" in st:
        return st["rows"]
    rs = _disk_get(meta, f"rows_v{ZONES_VERSION}") if not meta.get("words") else None
    if rs is None:
        ws = words(meta)
        aspect = (meta.get("w") or 1) / (meta.get("h") or 1)
        rs = parse_rows(ws, aspect=aspect) if ws else []
        if ws and not meta.get("words"):
            # a skewed scan: rows chained word to word find what the flat bands merged; add the rows they add
            for x in parse_rows(ws, aspect=aspect, grouping=_rows_of_words):
                cy = _cy(x["value_bbox"])
                if not any(abs(_cy(y["value_bbox"]) - cy) < 0.5 * (y["bbox"][3] - y["bbox"][1]) and
                           abs(y["value_bbox"][2] - x["value_bbox"][2]) < 0.02 for y in rs):
                    x["chained"] = True
                    rs.append(x)
            rs.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))
            _tables(rs, ws)
            for n, x in enumerate(rs):
                x["id"] = n
        if rs and not meta.get("words") and meta.get("image"):
            rs = _reread_rows(meta, ws, rs, aspect)
        cost = 0.0
        if not ws and meta.get("image") and ((meta.get("classify") or {}).get("has_tables")):
            rs, cost = _vision_rows(meta)
        st["cost_usd"] = st.get("cost_usd", 0.0) + cost
        if not meta.get("words"):
            _disk_put(meta, f"rows_v{ZONES_VERSION}", rs)
    if not meta.get("words"):
        _repair_labels(rs)
    st["rows"] = rs
    return rs


# words a schedule row label is made of: a scan's misread label word ("TOTAL COMMON Pace", "OTAL") is put back to
# the nearest of these or of the words the table's other rows spell the same way
_LABEL_WORDS = {"TOTAL", "SUBTOTAL", "FLOOR", "FIRST", "SECOND", "THIRD", "FOURTH", "GROUND", "BASEMENT", "AREA",
                "SPACE", "COMMON", "CIRCULATION", "DORMITORY", "DORMS", "UTILITY", "WING", "NORTH", "SOUTH", "EAST",
                "WEST", "EXTERIOR", "INTERIOR", "STAIR", "STAIRS", "ROOM", "ROOMS", "OFFICE", "STORAGE", "GROSS",
                "NET", "MECHANICAL", "ELECTRICAL", "LOBBY", "CORRIDOR", "KITCHEN", "LAUNDRY", "LOUNGE", "SUPPORT"}


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _join_split_words(label: str) -> str:
    """'TOTAL COMMO OMMON SPACE' -> 'TOTAL COMMON SPACE': one word read as two overlapping pieces (the second
    starting with the first's tail, allowing its last letter misread), or the same word twice."""
    ws = label.split()
    out: list[str] = []
    for w in ws:
        if out:
            a, au, wu = out[-1], out[-1].upper(), w.upper()
            if au == wu and len(wu) >= 3:
                continue
            if len(au) >= 4 and len(wu) >= 4 and au.isalpha() and wu.isalpha():
                joined = None
                for i in range(1, 3):
                    tail = au[i:]
                    if len(tail) >= 3 and (wu.startswith(tail) or wu.startswith(tail[:-1])) and len(wu) > len(tail) - 1:
                        joined = a[:i] + w
                        break
                if joined:
                    out[-1] = joined
                    continue
        out.append(w)
    return " ".join(out)


def _complete_groups(tr: list[dict]) -> None:
    """Labels that lost their first words on a scan (the label column read from mid-word), completed from their
    group: rows up to a 'TOTAL <stem>' row are '<stem> <suffix>' (WEST WING DORMITORY / WEST WING CIRCULATION /
    TOTAL WEST WING). 'DORMITORY' -> NORTH WING DORMITORY, 'WING CIRCULATION' -> EAST WING CIRCULATION,
    'ON SPACE' -> COMMON SPACE, 'TOTAL NO' -> TOTAL NORTH WING."""
    groups, cur = [], []
    for r in tr:
        cur.append(r)
        if re.match(r"\s*TOTAL\b", r["label"], re.I):
            groups.append(cur)
            cur = []
    stems = [re.sub(r"^\s*TOTAL\s*", "", g[-1]["label"].upper()).strip() for g in groups]
    full = [s_ for s_ in stems if len(s_.split()) >= 2]
    suffixes = set()
    for g, st in zip(groups, stems):
        for r in g[:-1]:
            lab = r["label"].upper().strip()
            if st and lab.startswith(st + " "):
                suffixes.add(lab[len(st) + 1:])
    if not full or not suffixes:
        return
    for g, st in zip(groups, stems):
        if len(g) < 2:
            continue
        if st not in full:  # a cut total ("TOTAL NO"): the stem of a member that reads whole
            cands = {m.upper()[: -len(sfx) - 1] for r in g[:-1] for sfx in suffixes
                     for m in [r["label"].strip()] if m.upper().endswith(" " + sfx)}
            cands = {c for c in cands if st and c.startswith(st) and len(c.split()) >= 2}
            if len(cands) != 1:
                continue
            st = cands.pop()
            g[-1]["label_read"], g[-1]["label"] = g[-1]["label"], f"TOTAL {st}"
        wholes = [st] + [f"{st} {sfx}" for sfx in suffixes]
        for r in g[:-1]:
            lab = r["label"].upper().strip()
            if lab in wholes or not lab:
                continue
            hit = [w for w in wholes if w.endswith(lab) and (len(w) == len(lab) or w[-len(lab) - 1] in " " or
                                                                   len(lab) >= 4)]
            if len(hit) == 1:
                r["label_read"], r["label"] = r["label"], hit[0]


def _split_words(w: str, vocab: set) -> str:
    """'EASTWINGCIRCULATION' -> 'EAST WING CIRCULATION' when it is made of vocabulary words, else unchanged."""
    u = w.upper()
    best: dict = {0: []}
    for i in range(len(u)):
        if i not in best:
            continue
        for v in vocab:
            if u.startswith(v, i) and (i + len(v) not in best or len(best[i]) + 1 < len(best[i + len(v)])):
                best[i + len(v)] = best[i] + [v]
    return " ".join(best[len(u)]) if len(u) in best and len(best[len(u)]) > 1 else w


def _repair_labels(rs: list[dict]) -> None:
    """Scan misreads of table row labels, in place (the value is left as read):
    - a word that is no word of the table's other rows nor of _LABEL_WORDS -> the nearest such word within 1-2
      edits ("Pace" -> SPACE, "OTAL" -> TOTAL), so "total common space" finds TOTAL COMMON SPACE;
    - a row of a repeated group that lost its last word: WEST WING DORMITORY / WEST WING CIRCULATION / TOTAL WEST
      WING, ..., NORTH WING DORMITORY / NORTH WING / TOTAL NORTH WING -> NORTH WING CIRCULATION."""
    by_table: dict = {}
    for r in rs:
        by_table.setdefault(r.get("table"), []).append(r)
    for tr in by_table.values():
        vocab = set(_LABEL_WORDS)
        for r in tr:
            vocab |= {w for w in re.findall(r"[A-Z]{4,}", r["label"]) if w in _LABEL_WORDS or
                      sum(w in re.findall(r"[A-Z]{4,}", o["label"]) for o in tr) >= 2}
        for r in tr:  # a word read twice by overlapping OCR passes: "COMMO OMMON", "SUBTOT UBTOTAL", "SUBTOTAL SUBTOTAL"
            lab = _join_split_words(r["label"])
            if lab != r["label"]:
                r["label_read"], r["label"] = r["label"], lab
                r["total"] = bool(re.search(r"\b(sub)?total\b", lab, re.I))
        for r in tr:  # "NORTH WING.CIRCULATION", "EASTWINGCIRCULATION": words run together on a scan
            lab = re.sub(r"(?<=[A-Za-z])[.,_](?=[A-Za-z])", " ", r["label"])
            lab = re.sub(r"[A-Za-z]{9,}", lambda m: _split_words(m.group(0), vocab), lab)
            # a word cut in two by a space ("CIRCULAT ION")
            ws, out_w = lab.split(), []
            for w in ws:
                if out_w and (out_w[-1] + w).upper() in vocab and out_w[-1].upper() not in vocab:
                    out_w[-1] = out_w[-1] + w
                else:
                    out_w.append(w)
            lab = " ".join(out_w)
            if lab != r["label"]:
                r["label_read"], r["label"] = r["label"], lab
        for r in tr:
            def fix(m):
                w = m.group(0)
                if w.upper() in vocab or len(w) < 3:
                    return w
                best = min(vocab, key=lambda v: (_lev(w.upper(), v), abs(len(v) - len(w))))
                if _lev(w.upper(), best) <= (1 if len(w) <= 4 else 2):
                    return best
                # the start of a word lost ("ULATION" of CIRCULATION): the one vocabulary word it ends
                ends = [v for v in vocab if len(w) >= 5 and v.endswith(w.upper()) and len(v) > len(w)]
                return ends[0] if len(ends) == 1 else w
            lab = re.sub(r"[A-Za-z]{3,}", fix, r["label"])
            if lab != r["label"]:
                r["label_read"], r["label"] = r["label"], lab
                r["total"] = bool(re.search(r"\b(sub)?total\b", lab, re.I))
        _complete_groups(tr)
        # a total whose label lost its first words ("SPACE = 4,499" for TOTAL COMMON SPACE): its value is the sum of
        # the rows since the last total, the first of which it names
        start = 0
        for i, r in enumerate(tr):
            if r.get("total"):
                start = i + 1
                continue
            grp = tr[start:i]
            if len(grp) >= 2 and abs(sum(g["value"] for g in grp) - r["value"]) < 0.5 and \
                    set(re.findall(r"[A-Z]{3,}", r["label"].upper())) <= set(re.findall(r"[A-Z]{3,}", grp[0]["label"].upper())):
                r["label_read"], r["label"] = r["label"], "TOTAL " + grp[0]["label"].strip()
                r["total"] = True
                start = i + 1
        # groups: "<stem> <suffix>" rows followed by "TOTAL <stem>"
        totals = [(i, re.sub(r"^TOTAL\s+", "", r["label"].upper()).strip()) for i, r in enumerate(tr)
                  if re.match(r"TOTAL\s+\w", r["label"], re.I)]
        pos: dict = {}  # (rows above the TOTAL row, suffix) -> how many groups print it there
        for i, stem in totals:
            for back in range(1, 5):
                if i - back < 0:
                    break
                lab = tr[i - back]["label"].upper().strip()
                if lab.startswith(stem + " "):
                    pos[(back, lab[len(stem) + 1:])] = pos.get((back, lab[len(stem) + 1:]), 0) + 1
        for i, stem in totals:
            for back in range(1, 5):
                if i - back < 0:
                    break
                r = tr[i - back]
                if r["label"].upper().strip() != stem:
                    continue
                cand = [(n, suf) for (b, suf), n in pos.items() if b == back and n >= 2]
                if len(cand) == 1:
                    r["label_read"], r["label"] = r["label"], f"{r['label'].strip()} {cand[0][1]}"


# ---------------------------------------------------------------------------------------------------- legend
def legend(meta) -> list[dict]:
    """[{"name", "rgb", "bbox" (name text), "swatch" (bbox)}]: flat colour boxes just left of a text line."""
    st = _st(meta)
    if "legend" in st:
        return st["legend"]
    ws = words(meta)
    out = []
    if ws and meta.get("image"):
        a = np.asarray(_image(meta))
        H, W = a.shape[:2]
        for r in _rows_of_words(ws, W / H):
            # split the baseline into phrases (gap > 1.5 text heights)
            hs = float(np.median([w["bbox"][3] - w["bbox"][1] for w in r]))
            phrases, cur = [], [r[0]]
            for w in r[1:]:
                if (w["bbox"][0] - cur[-1]["bbox"][2]) * W > 1.5 * hs * H:
                    phrases.append(cur)
                    cur = [w]
                else:
                    cur.append(w)
            phrases.append(cur)
            for ph in phrases:
                name = " ".join(w["text"] for w in ph).strip(" =:-|")
                if not re.search(r"[A-Za-z]{3,}", name) or re.search(r"\d{2,}\s*(SF|DORMS)|=", name):
                    continue
                b = _union([w["bbox"] for w in ph])
                th = (b[3] - b[1]) * H
                y = int(_cy(b) * H)
                xr = int(b[0] * W - 0.4 * th)
                xl = max(0, int(xr - 4 * th))
                if xr - xl < 5:
                    continue
                band = a[max(0, y - int(0.2 * th)):y + int(0.2 * th) + 1, xl:xr].astype(int)
                if band.size == 0:
                    continue
                # the swatch: the longest run of one non-white, non-black colour ending near the text
                med = np.median(band.reshape(-1, 3), 0)
                diff = np.abs(band - med).sum(2) < 18
                frac = diff.mean()
                lum = med.mean()
                if frac < 0.55 or lum > 247 or lum < 60:
                    continue
                cols = np.where(diff.mean(0) > 0.8)[0]
                if len(cols) < 1.2 * th:
                    continue
                sx0, sx1 = (xl + cols.min()) / W, (xl + cols.max()) / W
                out.append({"name": re.sub(r"\s+", " ", name), "rgb": [int(v) for v in med], "bbox": b,
                            "swatch": [sx0, b[1], sx1, b[3]]})
    # one legend = several swatches stacked in a column; drop isolated flukes
    out = [o for o in out if re.search(r"[A-Za-z]{4,}", o["name"])]
    if len(out) >= 2:
        # the legend: the biggest set of swatches stacked in one column, rows close together
        groups = []
        for o in sorted(out, key=lambda o: o["swatch"][1]):
            for g in groups:
                hh = g[-1]["swatch"][3] - g[-1]["swatch"][1]
                if abs(o["swatch"][0] - g[0]["swatch"][0]) < 0.01 and o["swatch"][1] - g[-1]["swatch"][3] < 4 * hh:
                    g.append(o)
                    break
            else:
                groups.append([o])
        out = max(groups, key=len)
        out = out if len(out) >= 2 else []
    else:
        out = []
    st["legend"] = out
    return out


# ------------------------------------------------------------------------------------------------------ scale
def _dim_ft(t: str):
    t = t.strip().replace("’", "'").replace("”", '"')
    m = re.fullmatch(r"(\d{1,4})'\s*[-.–]?\s*(\d{1,2})?\"?", t)
    if not m:
        m = re.fullmatch(r"(\d{2,4})-(\d{1,2})\"", t)  # OCR dropped the foot mark: 323-4"
    if not m:
        return None
    return int(m.group(1)) + (int(m.group(2)) / 12 if m.group(2) else 0)


def _ink_thr(W):
    """Grey level under which a pixel is linework: thin lines on small rasters are anti-aliased to mid grey."""
    return 110 if W > 8000 else 165


def _dim_line_px(gray, b, W, H):
    """(length px, (x0, x1, y)) between the ticks (slash or extension line) either side of the text box b on its
    horizontal dimension line, walking outward from the text centre; None if no such line."""
    th = (b[3] - b[1]) * H
    cx = int((b[0] + b[2]) / 2 * W)
    ink = gray < _ink_thr(W)
    ys = [y for y in range(int(b[3] * H) + 1, int(b[3] * H + 2 * th))] + \
        [y for y in range(int(b[1] * H) - 1, int(b[1] * H - 2 * th), -1)]
    # dimension text sits above its line (US and ISO practice): look below first, then above
    d = max(3, int(0.45 * th))
    for y in ys:
        if not (0 <= y - d and y + d < gray.shape[0]) or not ink[y, cx]:
            continue
        run = ink[y - 1:y + 2].any(0)
        ends = []
        for step in (-1, 1):
            x = cx
            while 0 < x < W - 1 and run[x]:
                # a tick: ink a little above AND below the line (vertical extension line or '/' slash)
                if any(ink[y - d, min(W - 1, max(0, x + e))] and ink[y + d, min(W - 1, max(0, x - e))]
                       for e in (-d, 0, d)) and abs(x - cx) > 0.6 * (b[2] - b[0]) * W / 2:
                    break
                x += step
            ends.append(x)
        if ends[1] - ends[0] > 3 * th and run[ends[0]] and run[ends[1]]:
            return ends[1] - ends[0], (ends[0], ends[1], y)
    return None


def _bar_px(gray, ws_row, W, H):
    """Length px of the scale bar drawn under (or over) its row of numbers: the longest dark run in a band of
    ~3 text heights next to the labels, overlapping their x range."""
    b = _union([w["bbox"] for w in ws_row])
    th = (b[3] - b[1]) * H
    x0, x1 = int(b[0] * W), int(b[2] * W)
    best = None
    for y in list(range(int(b[3] * H) + 1, int(b[3] * H + 3 * th))) + list(range(int(b[1] * H - 3 * th), int(b[1] * H))):
        if not 0 <= y < gray.shape[0]:
            continue
        row = gray[y] < _ink_thr(W)
        xs = np.where(row[max(0, x0 - int(th)):min(W, x1 + int(th))])[0]
        if len(xs) < 0.5 * (x1 - x0):
            continue
        # contiguous span (allow 2 px gaps)
        xs = xs + max(0, x0 - int(th))
        brk = np.where(np.diff(xs) > 2)[0]
        segs = np.split(xs, brk + 1)
        sg = max(segs, key=len)
        if best is None or sg[-1] - sg[0] > best[1] - best[0]:
            best = (int(sg[0]), int(sg[-1]), y)
    return best


def scale(meta) -> dict | None:
    """{"px_per_ft", "how", "boxes", "check"}: scale bar ('0' to the farthest labelled tick) and the longest
    printed horizontal dimension string measured between its end ticks; the bar wins, the dimension checks it."""
    st = _st(meta)
    if "scale" in st:
        return st["scale"]
    ws = words(meta)
    W, H = meta.get("w"), meta.get("h")
    out = None
    if ws and W:
        gray = np.asarray(_image(meta, "L")) if meta.get("image") else None
        # (a) scale bar: numbers with a foot mark on one baseline, a 0 at the left; the bar drawn next to them
        bar = None
        for r in _rows_of_words(ws, W / H):
            toks = []
            for w in r:
                for part in w["text"].split():
                    m = re.fullmatch(r"(\d{1,3})['’]", part)  # "20'" (a 323'-4" dimension is not a bar label)
                    if m:
                        toks.append((int(m.group(1)), w))
            if len(toks) < 2:  # low-res OCR drops the foot marks: bare ascending numbers next to a drawn bar
                bare = [(int(w["text"]), w) for w in r if re.fullmatch(r"\d{1,3}", w["text"])]
                if len(bare) >= 2 and gray is not None:
                    toks = toks + bare
            zeros = [w for v, w in toks if v == 0] + [w for w in r if re.fullmatch(r"[0O]['’]?", w["text"])]
            if not zeros and toks and gray is not None:
                # the 0 itself misread ("a7" for "0' 7'"): the leftmost word of the label row stands in for it
                lw = min(r, key=lambda w: w["bbox"][0])
                if lw["bbox"][2] < min(w["bbox"][0] for _, w in toks if _ > 0) and len(lw["text"]) <= 3:
                    zeros = [lw]
            far = [(v, w) for v, w in toks if v > 0]
            if not zeros or not far:
                continue
            z = min(zeros, key=lambda w: w["bbox"][0])
            v, fw = max(far, key=lambda t: (t[1]["bbox"][0], t[0]))
            if fw["bbox"][0] <= z["bbox"][2]:
                continue
            # label centres (a word like "O' 7'" holds two numbers: take the 0's own character)
            zx = z["bbox"][0] + (z["bbox"][2] - z["bbox"][0]) * (0.25 if len(z["text"]) > 3 else 0.5)
            fx = (fw["bbox"][0] + fw["bbox"][2]) / 2
            px = (fx - zx) * W
            how = f"scale bar labels 0' to {v}' = {px:.0f} px"
            drawn = False
            if gray is not None:
                seg = _bar_px(gray, [w for w in r if z["bbox"][0] <= w["bbox"][0] <= fw["bbox"][0]], W, H)
                if seg and 0.85 < (seg[1] - seg[0]) / px < 1.2:
                    px = seg[1] - seg[0]
                    how = f"scale bar 0' to {v}' drawn {px:.0f} px long"
                    drawn = True
            if not drawn and (gray is not None or not any(re.search(r"['’]", w["text"]) for _, w in toks)):
                continue  # labels with no bar drawn next to them are not a scale bar
            if px > 50 and (bar is None or v > bar[0]):
                bar = (v, px / v, [z["bbox"], fw["bbox"]], how)
        # (b) dimension strings (low-confidence OCR words too: the line check below vets them)
        dims = []
        allw = ws if meta.get("words") or not meta.get("image") else sheets.ocr_words(meta, min_conf=0)
        for w in allw:
            ft = _dim_ft(w["text"])
            if ft is None or ft < 10 or (w["bbox"][2] - w["bbox"][0]) * W < (w["bbox"][3] - w["bbox"][1]) * H:
                continue
            dims.append((ft, w))
        dims.sort(key=lambda t: -t[0])
        dim = None
        if dims and gray is not None:
            for ft, w in dims[:4]:
                r = _dim_line_px(gray, w["bbox"], W, H)
                if r:
                    dim = (ft, r[0] / ft, [w["bbox"]], f"dimension {w['text']} = {ft:.2f} ft over {r[0]:.0f} px")
                    break
        if bar:
            out = {"px_per_ft": bar[1], "how": bar[3], "boxes": bar[2]}
            if dim:
                dev = dim[1] / bar[1] - 1
                out["check"] = f"{dim[3]}: {dim[1]:.2f} px/ft, {100 * dev:+.1f} % from the bar"
                out["boxes"] = bar[2] + dim[2]
                if abs(dev) < 0.03:
                    # both read: the dimension spans 4-5x the bar, so it is the finer ruler
                    out["px_per_ft"] = dim[1]
                    out["how"] = f"{dim[3]} (scale bar agrees within {100 * abs(dev):.1f} %)"
        elif dim:
            out = {"px_per_ft": dim[1], "how": dim[3], "boxes": dim[2]}
    st["scale"] = out
    return out


# ------------------------------------------------------------------------------------------------ colour zones
def _lab(rgb):
    import cv2

    a = np.asarray(rgb, np.uint8).reshape(-1, 1, 3)
    return cv2.cvtColor(a, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)


def zones(meta) -> dict | None:
    """{"px_per_ft", "categories": [{"name", "rgb", "area_sf", "parts": [{"points", "area_sf", "wing"}],
    "wings": {wing: area_sf}}], "footprint_sf"} measured from the legend colours, or None."""
    st = _st(meta)
    if "zones" in st:
        return st["zones"]
    leg = legend(meta)
    sc = scale(meta)
    if len(leg) < 2 or not sc or not meta.get("image"):
        st["zones"] = None
        return None
    cached = _disk_get(meta, "zones")
    if cached and cached.get("legend") == [x["name"] for x in leg] and cached.get("px_per_ft") == sc["px_per_ft"] \
            and cached.get("v") == ZONES_VERSION:
        st["zones"] = cached
        return cached
    import cv2

    rgb = np.asarray(_image(meta))
    H, W = rgb.shape[:2]
    f = 4 if max(H, W) > 6000 else (2 if max(H, W) > 3000 else 1)  # work at ~1/4 resolution on big sheets
    small = cv2.resize(rgb, (W // f, H // f), interpolation=cv2.INTER_AREA)
    h, w = small.shape[:2]
    ppf = sc["px_per_ft"] / f  # px per foot at the working resolution
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
    # paper white and ink black compete too, so a light grey zone does not swallow the paper; the tolerance
    # adapts to how far apart the legend colours are (JPEG / scan colour noise needs slack)
    cols = _lab([x["rgb"] for x in leg] + [[255, 255, 255], [0, 0, 0]])
    d = np.stack([np.linalg.norm(lab - c, axis=2) for c in cols], 0)  # distance to each colour (8-bit Lab)
    near = d.argmin(0)
    sep = min(float(np.linalg.norm(cols[i] - cols[j])) for i in range(len(cols)) for j in range(i + 1, len(cols)))
    tol = float(np.clip(TOL_FRAC * sep, 8.0, 24.0))
    raw = [(near == i) & (d[i] < tol) for i in range(len(leg))]
    # blank the legend swatches and the table / notes column
    for x in leg:
        s = x["swatch"]
        raw = [m & ~_rect(h, w, s, pad=0.004) for m in raw]
    # isolated flecks (antialiased greys along lines) out: opening by ~0.6 ft
    k_open = max(2, int(round(0.6 * ppf)))
    raw = [cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((k_open, k_open), np.uint8))
           if k_open >= 2 else m.astype(np.uint8) for m in raw]
    union = np.zeros((h, w), np.uint8)
    for m in raw:
        union |= m
    # the main plan: the largest cluster of zone colour (key plans and legends are small, far-off copies)
    gap = max(3, int(round(12 * ppf)))
    big = cv2.dilate(union, np.ones((gap, gap), np.uint8))
    n, labs, stt, _ = cv2.connectedComponentsWithStats(big, 8)
    if n < 2:
        st["zones"] = None
        return None
    # prefer the cluster that carries dimension strings: an isometric / 3D view in the same colours has none
    dimw = [w for w in words(meta) if (_dim_ft(w["text"]) or 0) >= 10]
    sizes = []
    for i in range(1, n):
        x, y, ww, hh, _ = stt[i]
        bx0, by0, bx1, by1 = (x - 0.15 * ww) / w, (y - 0.15 * hh) / h, (x + 1.15 * ww) / w, (y + 1.15 * hh) / h
        nd = sum(bx0 <= (d["bbox"][0] + d["bbox"][2]) / 2 <= bx1 and by0 <= _cy(d["bbox"]) <= by1 for d in dimw)
        sizes.append((float(union[labs == i].sum()) * (1 + min(nd, 4)), i))
    main = max(sizes)[1]
    keep = labs == main
    union = union & keep
    raw = [m & keep for m in raw]
    # footprint: walls, furniture lines and fixtures closed (~2 ft), holes under 150 SF filled ("open to below",
    # courtyards and stairs stay out)
    k = max(3, int(round(CLOSE_FT * ppf)))
    fp = cv2.morphologyEx(union, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    inv = (1 - fp).astype(np.uint8)
    n2, l2, s2, _ = cv2.connectedComponentsWithStats(inv, 4)
    small_hole = 150 * ppf * ppf
    for i in range(1, n2):
        x, y, ww, hh, a = s2[i]
        if a < small_hole and x > 0 and y > 0 and x + ww < w and y + hh < h:
            fp[l2 == i] = 1
    # gross area is to the outside face of the exterior walls: grow the footprint by one wall thickness
    kw = int(round(WALL_FT * ppf))
    if kw >= 1:
        fp = cv2.dilate(fp, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * kw + 1, 2 * kw + 1)))
    # each footprint pixel belongs to the nearest coloured pixel's category
    seed = np.zeros((h, w), np.int32)
    for i, m in enumerate(raw):
        seed[m.astype(bool)] = i + 1
    src = (seed == 0).astype(np.uint8)
    _, lbl = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    # map label ids (one per seed pixel) back to categories
    ids = lbl[seed > 0]
    lut = np.zeros(lbl.max() + 1, np.int32)
    lut[ids] = seed[seed > 0]
    cat = lut[lbl] * fp
    # wings: clusters of each category grouped across corridors (~10 ft), named by the side of the plan centre
    ys, xs = np.nonzero(fp)
    cx0, cy0 = xs.mean(), ys.mean()
    spanx, spany = xs.max() - xs.min(), ys.max() - ys.min()
    # wings: each category's pieces grouped across corridors (~10 ft), named by the side of the plan centre
    res = []
    for i, x in enumerate(leg):
        m = (cat == i + 1).astype(np.uint8)
        grp = cv2.dilate(m, np.ones((max(3, int(10 * ppf)),) * 2, np.uint8)) & fp
        ng, lg, sg, cg = cv2.connectedComponentsWithStats(grp, 8)
        parts, wings = [], {}
        for j in range(1, ng):
            pm = (m & (lg == j).astype(np.uint8))
            a_sf = float(pm.sum()) / ppf ** 2
            if a_sf < 20:
                continue
            gx, gy = cg[j]
            dx, dy = (gx - cx0) / max(spanx, 1), (gy - cy0) / max(spany, 1)
            if max(abs(dx), abs(dy)) < CENTRE_BOX:
                wing = "centre"
            elif abs(dx) >= abs(dy):
                wing = "east" if dx > 0 else "west"
            else:
                wing = "south" if dy > 0 else "north"
            wings[wing] = wings.get(wing, 0.0) + a_sf
            cs, _ = cv2.findContours(pm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in cs:
                ca = cv2.contourArea(c) / ppf ** 2
                if ca < 10:
                    continue
                poly = cv2.approxPolyDP(c, 1.0, True)[:, 0, :]
                parts.append({"points": [[round(float(px) * f / W, 5), round(float(py) * f / H, 5)] for px, py in poly],
                              "area_sf": round(ca, 1), "wing": wing})
        res.append({"name": x["name"], "rgb": x["rgb"], "area_sf": round(float(m.sum()) / ppf ** 2, 1),
                    "parts": parts, "wings": {k_: round(v, 1) for k_, v in wings.items()},
                    "legend_bbox": x["bbox"], "swatch": x["swatch"]})
    out = {"px_per_ft": sc["px_per_ft"], "scale_how": sc["how"], "categories": res,
           "footprint_sf": round(float(fp.sum()) / ppf ** 2, 1), "legend": [x["name"] for x in leg],
           "v": ZONES_VERSION}
    _disk_put(meta, "zones", out)
    st["zones"] = out
    return out


def _rect(h, w, b, pad=0.0):
    m = np.zeros((h, w), bool)
    m[max(0, int((b[1] - pad) * h)):int((b[3] + pad) * h) + 1, max(0, int((b[0] - pad) * w)):int((b[2] + pad) * w) + 1] = True
    return m


# ------------------------------------------------------------------------------------------- matching zones<->rows
def _toks(s):
    return {t for t in re.findall(r"[a-z]{3,}", s.lower()) if t not in STOP}


def _stem(t):
    return re.sub(r"(ies|es|s)$", "", t)


def _row_zones(z: dict, label: str, total: bool):
    """[(category, wing or None)] that a schedule row describes, or None when the colours cannot stand for it.
    WEST WING DORMITORY -> DORMITORY + ACCESSIBLE (ABA) DORMITORY in the west wing; TOTAL WEST WING -> every
    colour in the west wing; TOTAL COMMON SPACE -> the common-area colour; SUBTOTAL / TOTAL <n> FLOOR -> all."""
    if not z:
        return None
    wing = next((w_ for w_ in WINGS if re.search(rf"\b{w_}\b", label, re.I)), None)
    cats = z["categories"]
    lt = {_stem(t) for t in _toks(label)} - set(WINGS) - {"wing", "total", "subtotal"}
    if total and wing and not lt:
        return [(c, wing) for c in cats]
    if total and re.search(r"subtotal|floor|building|overall|gross", label, re.I) and not wing:
        return [(c, None) for c in cats]
    if re.search(r"\bcommon\b", label, re.I):
        if not total or wing:
            return None  # the common colour covers common space + its circulation + utility: only the total compares
        hit = [(c, None) for c in cats if re.search(r"\bcommon\b", c["name"], re.I)]
        return hit or None
    hit = [(c, wing) for c in cats if lt & {_stem(t) for t in _toks(c["name"])}]
    return hit or None


def zone_match(z: dict, label: str, total: bool = False) -> float | None:
    """Measured SF for a schedule row (see _row_zones); None when the colours do not correspond to it."""
    rz = _row_zones(z, label, total)
    if rz is None:
        return None
    if all(w is None for _, w in rz) and len(rz) == len(z["categories"]):
        return z["footprint_sf"]
    return sum((c["wings"].get(w, 0.0) if w else c["area_sf"]) for c, w in rz)


# --------------------------------------------------------------------------------------------------- answering
def is_mine(q: str) -> bool:
    ql = q.lower()
    return bool(re.search(r"area|square f|square met|square metre|sq\.? ?ft|\bsf\b|sq\.? ?f|m²|m2|sq\.? ?m|footage|floor space|how big|size of|"
                          r"colou?r|legend|zone|schedule|table|module|"
                          r"fläche|flaeche|wie groß|wie gross|quadratmeter|pinta-?ala|neliö|kuinka suuri|yta\b|ytan|"
                          r"kvadratmeter|superficie|surface", ql)
                or (re.search(r"how many|number of|count|wie viele|anzahl|montako|kuinka monta|hur många|antal", ql)
                    and re.search(r"dorm|room|unit|bed|apartment|zimmer|wohn|huone|rum\b|rummen", ql)))


def wants_metric(q: str, rs) -> bool | None:
    ql = q.lower()
    if re.search(r"m²|m2\b|sq\.? ?m|square met|metres|meters|sqm|neliömet|neliometr|quadratmeter|kvadratmeter|"
                 r"mètres? carr|metros? cuadr", ql):
        return True
    if re.search(r"square f|\bsf\b|sq\.? ?f|feet|foot", ql):
        return False
    return None


PICK = """Question about a construction drawing: {question}

The tables printed on the sheet, one row per line, "[id] TABLE | label = value unit":
{rows}

Pick the rows that answer the question. JSON only:
{{"groups": [{{"name": "<what this number is, short>", "ids": [<row ids>]}}], "confidence": "high" | "medium" | "low",
  "note": "<one short line>"}}
Rules: one group per number in the answer. A group of one row reads that row; a group of several rows adds them up
(only when no printed total row already gives that number: prefer the printed TOTAL row). For a question about the
areas of the different areas / zones / types, give one group per category (e.g. dormitory = the wings' dormitory
rows, circulation = all circulation rows, common space, utility, ...) and nothing for totals. Counts (rooms, dorms)
come from count rows. What the question excludes ("excluding / without / except / not counting the exterior
stair") is left out: pick the printed row that already leaves it out (a SUBTOTAL above it), never the excluded row
itself. A question about the area shown in a legend colour on the plan ("coloured as 2nd floor common area (pink)")
is answered by the schedule's row for that category when there is one (TOTAL COMMON SPACE). If the tables do not
answer it, "groups": []."""


def _pick_llm(meta, question, rs):
    from bp.generic import llm

    if os.environ.get("BP_ZONES_LLM", "1") != "1":
        return None, 0.0
    cache = _st(meta).setdefault("picks", {})
    if question in cache:
        return cache[question], 0.0
    txt = "\n".join(f"[{r['id']}] {r['table']} | {r['label']} = {_fmt(r['value'], 2)} {r['unit']}" for r in rs)
    # the model's pick is kept with the upload: the same question on the same file gets the same rows (no flip
    # between asks or after a restart)
    dkey = "pick_" + hashlib.sha1((question + "\n" + txt).encode()).hexdigest()[:16]
    hit = _disk_get(meta, dkey)
    if isinstance(hit, dict):
        cache[question] = hit
        return hit, 0.0
    r = llm.ask(PICK.format(question=question, rows=txt), model="haiku", tag="sheets-zones-pick", timeout=90)
    d = llm.parse_json(r.get("text", ""))
    if not isinstance(d, dict) or not isinstance(d.get("groups"), list):
        return None, r.get("cost_usd", 0.0)
    gs = []
    for g in d["groups"]:
        ids = [i for i in (g.get("ids") or []) if isinstance(i, int) and 0 <= i < len(rs)]
        if ids:
            gs.append({"name": str(g.get("name") or rs[ids[0]]["label"]), "ids": ids})
    out = {"groups": gs, "confidence": d.get("confidence", "medium"), "note": d.get("note") or ""}
    cache[question] = out
    _disk_put(meta, dkey, out)
    return out, r.get("cost_usd", 0.0)


ORD = {"1st": "first", "2nd": "second", "3rd": "third", "4th": "fourth", "ground": "first",
       "erste": "first", "ersten": "first", "zweite": "second", "zweiten": "second", "dritte": "third",
       "ensimmäinen": "first", "ensimmäisen": "first", "toinen": "second", "toisen": "second", "kolmas": "third",
       "kolmannen": "third", "eg": "first", "og": "second"}
TOTAL_RX = re.compile(r"\b(total|totals|overall|whole|entire|gross|all|altogether|combined|gesamt\w*|insgesamt|"
                      r"yhteens[äa]|koko|kaikki|totalt|sum)\b", re.I)
_MSTOP = {"what", "whats", "is", "the", "of", "a", "an", "on", "in", "this", "that", "how", "many", "much", "are",
          "there", "for", "and", "to", "sheet", "plan", "drawing", "sf", "s", "do", "does", "we", "have", "at", "per",
          "area", "areas", "size", "square", "feet", "foot", "footage", "metres", "meters", "m2", "net", "space"}


def _mtoks(s: str) -> set:
    """Words for matching a question to a row label: lower case, ordinals spelled out ("2nd" -> second), stemmed."""
    ws = re.findall(r"[a-zäöü0-9]+", s.lower().replace("2. og", "second").replace("1. og", "first"))
    out = set()
    for w in ws:
        w = ORD.get(w, w)
        if len(w) < 3 or w in _MSTOP or w.isdigit():
            continue
        out.add(_stem(w))
    return out


def _guard_pick(question, rs, pick):
    """Deterministic checks on the rows a model picked: a single TOTAL / SUBTOTAL row is replaced by a row whose
    own label is named in the question ("dorm rooms on the SECOND FLOOR" -> SECOND FLOOR = 48, not TOTAL = 144;
    "total FIRST FLOOR area" -> TOTAL FIRST FLOOR = 28,770, not SUBTOTAL); a TOTAL picked while the question names a
    part that no row has (a row OCR lost) is not answered from the total."""
    qm = _mtoks(question)
    asks_total = bool(TOTAL_RX.search(question))
    excl = re.search(r"\b(?:excluding|excludes?|without|except(?:\s+for)?|not\s+(?:counting|including)|"
                     r"exclusive\s+of|minus|less)\b(.+)$", question, re.I)
    ex_t = (_mtoks(excl.group(1)) - {"total", "area", "floor", "the"}) if excl else set()
    if ex_t:  # a question that leaves a row out is never answered by that row
        groups = []
        for g in pick["groups"]:
            if len(g["ids"]) == 1 and ex_t & _mtoks(rs[g["ids"][0]]["label"]):
                r = rs[g["ids"][0]]
                subs = [x for x in rs if x["kind"] == r["kind"] and re.search(r"\bsub\s?total\b", x["label"], re.I)]
                if subs:
                    sub = min(subs, key=lambda x: abs(x["bbox"][1] - r["bbox"][1]))
                    g = {**g, "name": sub["label"], "ids": [sub["id"]],
                         "guard": f"the question excludes {r['label']}: the subtotal without it"}
                else:
                    continue
            elif len(g["ids"]) > 1:
                g = {**g, "ids": [i for i in g["ids"] if not ex_t & _mtoks(rs[i]["label"])]}
                if not g["ids"]:
                    continue
            groups.append(g)
        pick = {**pick, "groups": groups}
    out = []
    for g in pick["groups"]:
        if ex_t and not ex_t & set().union(*(_mtoks(rs[i]["label"]) for i in g["ids"])):
            out.append(g)  # already free of the excluded row: not switched to a row the question names
            continue
        if len(g["ids"]) >= 3:
            # a sum is of one category: rows lacking the word most of them share (EXTERIOR STAIR among the
            # ...CIRCULATION rows) are not part of it
            toks = [_mtoks(rs[i]["label"]) - set(WINGS) - {"wing", "total"} for i in g["ids"]]
            cnt = {}
            for t in toks:
                for u in t:
                    cnt[u] = cnt.get(u, 0) + 1
            if cnt:
                top, n = max(cnt.items(), key=lambda kv: kv[1])
                if n >= len(toks) - 1 and n < len(toks):
                    g = {**g, "ids": [i for i, t in zip(g["ids"], toks) if top in t],
                         "guard": f"kept the {top} rows only"}
        if len(g["ids"]) != 1:
            out.append(g)
            continue
        r = rs[g["ids"][0]]
        same = [x for x in rs if x["kind"] == r["kind"]]

        def score(x):
            lm = _mtoks(x["label"]) - {"total", "subtotal"}
            hit = sum(any(t == u or (min(len(t), len(u)) >= 4 and (t.startswith(u) or u.startswith(t))) for u in qm)
                      for t in lm)
            cover = hit / len(lm) if lm else 0.0
            return (cover >= 0.999 and hit > 0, hit, cover, x["total"] == asks_total)

        best = max(same, key=score)
        if r["total"] and not score(r)[0] and score(best)[:2] > score(r)[:2] and score(best)[0]:
            out.append({"name": best["label"], "ids": [best["id"]], "guard": f"{r['label']} -> {best['label']}"})
            continue
        if r["total"] and not asks_total:
            keys = qm & {"first", "second", "third", "fourth", "west", "east", "north", "south"}
            # a floor the table's own total names ("TOTAL FIRST FLOOR") is the sheet's context, not a part
            keys -= {t for x in same if x["total"] for t in _mtoks(x["label"])}
            if keys:
                cand = [x for x in same if not x["total"] and keys <= _mtoks(x["label"])]
                if len(cand) == 1:
                    out.append({"name": cand[0]["label"], "ids": [cand[0]["id"]],
                                "guard": f"{r['label']} -> {cand[0]['label']}"})
                    continue
                classes = [{"first", "second", "third", "fourth"}, set(WINGS)]
                siblings = any(keys & c and any(_mtoks(x["label"]) & c for x in rs) for c in classes)
                if not cand and siblings:
                    # the table lists parts of this kind (FIRST, THIRD FLOOR) but not the asked one (OCR lost the
                    # SECOND FLOOR row): its TOTAL is not the answer. ("first floor" on a table without floor rows
                    # is only the sheet's context.)
                    return {"groups": [], "confidence": "low", "note": "the asked part is not a row of the table"}
        out.append(g)
    return {**pick, "groups": out}


def _parts_check(rs, r):
    """(sum, [rows]) of the rows a TOTAL row adds up: the rows above it in its table back to the previous total
    (a SUBTOTAL met on the way counts as one part and ends the walk); None if there are none."""
    tab = [x for x in rs if x["table"] == r["table"] and x["kind"] == r["kind"]]
    tab.sort(key=lambda x: x["bbox"][1])
    i = tab.index(r) if r in tab else -1
    parts = []
    for x in reversed(tab[:i]):
        if x["total"]:
            if re.search(r"subtotal", x["label"], re.I):
                parts.append(x)
            break
        parts.append(x)
    if len(parts) < 2:
        return None
    return sum(x["value"] for x in parts), parts[::-1]


def _pick_kw(question, rs):
    """Offline row choice: TOTAL row whose words match, else the rows whose label contains the asked words."""
    ql = question.lower()
    want_count = bool(re.search(r"how many|number of|count", ql)) and not re.search(r"area|footage|\bsf\b", ql)
    pool = [r for r in rs if r["kind"] == ("count" if want_count else "area")]
    if not pool:
        return None
    qt = {_stem(t) for t in _toks(question)}
    if want_count:
        qt -= {"dorm", "room", "unit"}
    per = re.search(r"\bper\b|\beach\b", ql)

    def lt(r):
        return {_stem(t) for t in _toks(r["label"])}

    if re.search(r"different|each (area|zone|type|category)|by (area|zone|type|category)|breakdown|all areas", ql):
        gs = {}
        for r in pool:
            if r["total"]:
                continue
            ks = lt(r) - set(WINGS) - {"wing"}
            key = " ".join(sorted(ks)) or r["label"]
            gs.setdefault(key, []).append(r["id"])
        return {"groups": [{"name": rs[v[0]]["label"] if len(v) == 1 else k, "ids": v} for k, v in gs.items()],
                "confidence": "medium", "note": "one group per row label"}
    if per and want_count:
        rows_ = [r for r in pool if not r["total"]]
        return {"groups": [{"name": r["label"], "ids": [r["id"]]} for r in rows_], "confidence": "medium", "note": ""}
    tot = [r for r in pool if r["total"] and qt and qt <= lt(r) | {"total"}]
    if tot and (re.search(r"total|whole|entire|overall|gross", ql) or not qt - {"total"}):
        best = max(tot, key=lambda r: (len(qt & lt(r)), -len(lt(r))))
        return {"groups": [{"name": best["label"], "ids": [best["id"]]}], "confidence": "high", "note": ""}
    if not qt - {"total"}:
        tots = [r for r in pool if r["total"]]
        if tots:
            best = max(tots, key=lambda r: (r["value"], -r["bbox"][1]))
            return {"groups": [{"name": best["label"], "ids": [best["id"]]}], "confidence": "medium", "note": ""}
    m = [r for r in pool if not r["total"] and qt - {"total"} and (qt - {"total"}) <= lt(r)]
    if not m:
        m = [r for r in pool if r["total"] and (qt - {"total"}) and (qt - {"total"}) <= lt(r)]
        m = m[:1]
    if not m:
        return None
    return {"groups": [{"name": " + ".join(r["label"] for r in m) if len(m) > 1 else m[0]["label"],
                        "ids": [r["id"] for r in m]}], "confidence": "medium" if len(m) > 1 else "high", "note": ""}


def _conv(v, unit, metric):
    """(value, unit) in the asked system."""
    if unit == "SF" and metric:
        return v * SF_TO_M2, "m²"
    if unit == "m²" and metric is False:
        return v / SF_TO_M2, "SF"
    return v, unit


def _scale_ev(sc):
    return [{"kind": "text", "page": 0, "bbox": _pad(b), "label": "scale read here", "value": None}
            for b in (sc or {}).get("boxes") or []]


def _pct(m, s):
    return f"{100 * (m / s - 1):+.1f} %" if s else ""


DIM_Q = re.compile(r"\b(overall|total|building|whole|entire|outside|gross|external)\b.*\b(length|width|depth|long|wide|"
                   r"deep|dimension)|\b(length|width|depth|dimension)s? of the (building|plan|floor|whole)|how (long|wide|"
                   r"deep) is the (building|plan)", re.I)


def answer(path, question, meta):
    if DIM_Q.search(question) and not re.search(r"\barea\b", question, re.I):
        return _answer_dimension(meta, question)
    if not is_mine(question):
        return None
    rs = rows(meta)
    cost = _st(meta).get("cost_usd", 0.0)
    ql = question.lower()
    metric = wants_metric(question, rs)
    want_measure = bool(re.search(r"\bmeasur|colou?r|legend|zone|module type|shaded|highlight", ql))
    pick = None
    if rs and not (want_measure and re.search(r"\bmeasur", ql)):
        kw = _pick_kw(question, rs)
        if kw and kw.get("confidence") == "high" and len(kw["groups"]) == 1 and len(kw["groups"][0]["ids"]) == 1 \
                and not rs[kw["groups"][0]["ids"][0]]["total"] and not TOTAL_RX.search(question):
            # the question names one row exactly ("area of the west wing dormitory"): that row, no model pick
            # (the model once took TOTAL WEST WING for it)
            pick, c = kw, 0.0
        else:
            pick, c = _pick_llm(meta, question, rs)
        cost += c
        if pick is None:
            pick = kw
        if pick and pick["groups"]:
            pick = _guard_pick(question, rs, pick)
            if not pick["groups"]:
                return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": round(cost, 5),
                        "method": "sheets-zones-schedule-none",
                        "explanation": "the sheet's table has no row for the part asked about (only a total)"}
    low = _low_res(meta)
    if pick and pick["groups"]:
        res = _answer_rows(meta, question, rs, pick, metric)
        res["cost_usd"] = round(cost, 5)
        if low:
            res["low_res"] = low
        return res
    # no table answers it: measure the colour zones
    res = _answer_measured(meta, question, metric)
    if res is not None:
        res["cost_usd"] = round(cost, 5)
        if low:
            res["low_res"] = low
    return res


def _fmt_ftin(ft: float) -> str:
    f = int(ft)
    i = int(round((ft - f) * 12))
    if i == 12:
        f, i = f + 1, 0
    return f"{f}'-{i}\""


def _reread_dims(meta, dims, W, H):
    """A scan: the overall dimension string is often missed or misread (323'-0" for 323'-4"). The band around the
    longest horizontal string read (where the overall one sits, just outside its chain) is read again at 3x, and of
    near-equal readings of the longest one the reading that the strings of its chain add up to wins."""
    hz = [d for d in dims if not d[1]]
    if not hz:
        return dims
    top = max(hz, key=lambda d: d[0])[2]["bbox"]
    hh = max(top[3] - top[1], 0.005)
    reg = [0.0, max(0.0, top[1] - 6 * hh), 1.0, min(1.0, top[3] + 6 * hh)]
    extra = []
    for sc_, psm in ((3.0, 11), (2.0, 6)):
        try:
            ws = sheets.ocr_words(meta, region=reg, scale=sc_, psm=psm, min_conf=0)
        except Exception:  # noqa: BLE001
            ws = []
        for w in ws:
            ft = _dim_ft(w["text"])
            b = w["bbox"]
            if ft is None or ft < 10 or (b[3] - b[1]) * H > (b[2] - b[0]) * W:
                continue
            extra.append((ft, False, {**w, "band": True}))
    alld = dims + extra
    hz = [d for d in alld if not d[1]]
    big = max(d[0] for d in hz)
    # each of the longest strings once more on its own, tight and at 3x: the inches a small scan loses come back
    # ("323'" -> 323'-4")
    seen, drop = [], set()
    for i, d in enumerate(sorted(range(len(alld)), key=lambda j: -alld[j][0])):
        i, d = d, alld[d]
        b = d[2]["bbox"]
        if d[1] or d[0] < 0.95 * big:
            continue
        if any(abs(b[0] - o[0]) < 0.01 and abs(b[1] - o[1]) < 0.01 for o in seen):
            if d[2].get("band"):
                drop.add(i)
            continue
        seen.append(b)
        w_, h_ = b[2] - b[0], b[3] - b[1]
        reg = [max(0.0, b[0] - 0.3 * w_), max(0.0, b[1] - 0.4 * h_), min(1.0, b[2] + 1.2 * w_), min(1.0, b[3] + 0.4 * h_)]
        reads = []
        for psm in (7, 11):
            try:
                reads += [_dim_ft(w["text"]) for w in sheets.ocr_words(meta, region=reg, scale=3.0, psm=psm, min_conf=0)]
            except Exception:  # noqa: BLE001
                pass
        reads = [r for r in reads if r and abs(r - d[0]) <= 0.02 * d[0]]
        if reads:
            best = max(set(reads), key=reads.count)
            if best != d[0]:
                alld[i] = (best, d[1], {**d[2], "text": _fmt_ftin(best), "reread": True})
        elif d[2].get("band"):
            drop.add(i)  # a band reading the tight look does not confirm: noise
        else:
            continue
        big = max(x[0] for j, x in enumerate(alld) if not x[1] and j not in drop)
    alld = [d for j, d in enumerate(alld) if j not in drop]
    hz = [d for d in alld if not d[1]]
    big = max(d[0] for d in hz)
    near = [d for d in hz if d[0] >= big * 0.985]
    vals = sorted({round(d[0], 2) for d in near})
    if len(vals) > 1:
        # the chain of strings on one line next to it (133'-10" + 55'-8" + 133'-10" under 323'-4")
        def chain_sum(d):
            b = d[2]["bbox"]
            cy, h_ = (b[1] + b[3]) / 2, b[3] - b[1]
            row = {}
            for e in hz:
                eb = e[2]["bbox"]
                ey = (eb[1] + eb[3]) / 2
                if e is not d and e[0] < 0.8 * d[0] and 0.5 * h_ < abs(ey - cy) < 6 * h_:
                    row.setdefault(round(ey / max(h_, 1e-6)), {})[round((eb[0] + eb[2]) / 2, 2)] = e[0]
            return [sum(v.values()) for v in row.values() if len(v) >= 2]
        for d in sorted(near, key=lambda d: -d[0]):
            if any(abs(s_ - d[0]) < 0.1 for s_ in chain_sum(d)):
                return [x for x in alld if x not in near or x is d]
    return alld


def _answer_dimension(meta, question):
    """Overall length / width of the building: the longest printed dimension string (horizontal for length,
    the other direction for width / depth when it was read), kept as printed (323'-4"), its line measured as a check."""
    ws = words(meta)
    W, H = meta.get("w") or 1, meta.get("h") or 1
    allw = ws if meta.get("words") or not meta.get("image") else sheets.ocr_words(meta, min_conf=0)
    dims = []
    for w in allw:
        ft = _dim_ft(w["text"])
        if ft is None or ft < 10:
            continue
        b = w["bbox"]
        vert = (b[3] - b[1]) * H > (b[2] - b[0]) * W
        dims.append((ft, vert, w))
    if not dims:
        return None
    if not meta.get("words") and meta.get("image"):
        dims = _reread_dims(meta, dims, W, H)
    want_w = bool(re.search(r"\b(width|wide|depth|deep)\b", question, re.I))
    hz = [d for d in dims if not d[1]]
    vt = [d for d in dims if d[1]]
    if want_w:
        pool = vt if vt else []  # rasters: rotated text is rarely OCR'd, then we cannot tell width from length
        if not pool:
            return None
    else:
        pool = hz or dims
    ft, vert, w = max(pool, key=lambda d: d[0])
    # if both directions were read, "length" is the longer one
    if not want_w and vt and max(d[0] for d in vt) > ft:
        ft, vert, w = max(vt, key=lambda d: d[0])
    text = _fmt_ftin(ft)
    ev = [{"kind": "text", "page": 0, "bbox": _pad(w["bbox"]), "label": f"dimension {text}", "value": round(ft, 3)}]
    conf, check = 0.75, ""
    sc = scale(meta)
    if sc and not vert and meta.get("image"):
        try:
            r = _dim_line_px(np.asarray(_image(meta, "L")), w["bbox"], W, H)
        except Exception:  # noqa: BLE001
            r = None
        if r:
            meas = r[0] / sc["px_per_ft"]
            dev = meas / ft - 1
            x0, x1, y = r[1]
            ev.append({"kind": "polyline", "page": 0, "points": [[x0 / W, y / H], [x1 / W, y / H]], "closed": False,
                       "label": f"dimension line, measured {meas:.1f} ft", "value": round(meas, 2), "unit": "ft"})
            if "dimension" not in sc["how"] or abs(dev) > 1e-6:
                check = f"; its line measures {meas:.1f} ft at the sheet's scale ({100 * dev:+.1f} %)"
            conf = 0.9 if abs(dev) < 0.03 else 0.6
    which = "width" if want_w else "length"
    return {"answer": text, "display": text, "value_ft": round(ft, 4), "value_m": round(ft * FT, 3),
            "confidence": conf, "method": "sheets-zones-dimension", "cost_usd": 0.0, "unit": "ft-in",
            "explanation": f"Overall {which}: the longest {'vertical' if vert else 'horizontal'} dimension string on "
                           f"the plan reads {text} ({ft:.2f} ft = {ft * FT:.2f} m){check}",
            "evidence": ev, **({"low_res": _low_res(meta)} if _low_res(meta) else {})}


def _low_res(meta):
    """A one-line hint when the raster is too small to read small table text reliably (no PDF text layer)."""
    if meta.get("words"):
        return None
    if meta.get("low_res") or max(meta.get("w") or 0, meta.get("h") or 0) < 3000:
        return "small image: table text read by OCR at low resolution, check the numbers"
    return None


def _answer_rows(meta, question, rs, pick, metric):
    z = None
    try:
        z = zones(meta)
    except Exception:  # noqa: BLE001 - the cross-check never blocks the schedule answer
        log.exception("zones cross-check failed")
    ev, parts, nums, checks, sum_mismatch = [], [], [], [], []
    units = set()
    for g in pick["groups"]:
        grs = [rs[i] for i in g["ids"]]
        unit = grs[0]["unit"]
        vals = [r["value"] for r in grs]
        tot = sum(vals)
        units.add(unit)
        cv, cu = _conv(tot, unit, metric)
        for r in grs:
            rv, _ = _conv(r["value"], r["unit"], metric)
            ev.append({"kind": "cell", "page": 0, "bbox": _pad(r["bbox"]), "label": r["label"].capitalize(),
                       "value": round(rv, 2), "unit": _conv(1, r["unit"], metric)[1],
                       "text": f"{_fmt(r['value'], 2)} {r['unit']}", "table": r["table"].capitalize()})
        arith = (" + ".join(_fmt(v, 2) for v in vals) + f" = {_fmt(tot, 2)} {unit}") if len(vals) > 1 else \
            f"{_fmt(tot, 2)} {unit}"
        if len(grs) == 1 and grs[0]["total"]:
            pc = _parts_check(rs, grs[0])
            if pc:
                ps, prs = pc
                if abs(ps - tot) <= max(1, 0.002 * tot):
                    arith += f" (checks: {' + '.join(_fmt(x['value'], 2) for x in prs)} = {_fmt(ps, 2)})"
                else:
                    arith += f" (the rows above it add up to {_fmt(ps, 2)}, not {_fmt(tot, 2)}: a misread is possible)"
                    sum_mismatch.append(grs[0]["label"])
        if cu != unit:
            arith += f" = {_fmt(cv, 1)} {cu} (x 0.0929)"
        parts.append((g["name"], cv, cu, arith))
        nums.append(cv)
        # the colour zones measured on the plan, as a cross-check
        if z and unit == "SF" and grs[0]["kind"] == "area":
            ms = [zone_match(z, r["label"], r["total"]) for r in grs]
            if all(m is not None for m in ms) and grs:
                msum = sum(ms)
                checks.append(f"{g['name']}: measured {_fmt(msum)} SF vs {_fmt(tot)} SF on the schedule "
                              f"({_pct(msum, tot)})")
                ev.extend(_zone_ev(z, grs))
    nd = 1 if metric else 0
    if len(parts) == 1:
        name, v, u, arith = parts[0]
        ans = round(v, nd) if nd else int(round(v)) if abs(v - round(v)) < 1e-6 or u in ("SF", "dorms") else v
        expl = f"{name}: {arith}, read from the sheet's {rs[pick['groups'][0]['ids'][0]]['table'].lower()} table"
    elif len({round(v, 3) for _, v, _, _ in parts}) == 1 and re.search(r"\beach\b|\bper\b|\bevery\b", question, re.I):
        v, u = parts[0][1], parts[0][2]  # "how many dorms per floor": every row says the same
        ans = round(v, nd) if nd else int(round(v))
        expl = f"{_fmt(v, nd)} {u} on each row: " + "; ".join(f"{n} = {a}" for n, _, _, a in parts)
    else:
        ans = "; ".join(f"{n}: {_fmt(v, nd)} {u}" for n, v, u, _ in parts)
        expl = "Read from the sheet's tables: " + "; ".join(f"{n} = {a}" for n, _, _, a in parts)
    if checks:
        expl += ". Cross-check, colour zones measured on the plan at " + \
                f"{z['px_per_ft']:.2f} px/ft ({z['scale_how']}): " + "; ".join(checks)
    conf = {"high": 0.9, "medium": 0.75, "low": 0.5}.get(pick.get("confidence"), 0.7)
    if sum_mismatch:
        conf = min(conf, 0.55)
    return {"answer": ans, "confidence": conf, "method": "sheets-zones-schedule", "cost_usd": 0.0,
            "explanation": expl, "evidence": ev, "unit": parts[0][2] if len(parts) == 1 else None}


def _zone_ev(z, grs):
    """Polygons of the zones a schedule row corresponds to (value None: the schedule gives the number)."""
    out, seen = [], set()
    for r in grs:
        for c, wing in _row_zones(z, r["label"], r["total"]) or []:
            for k, p in enumerate(c["parts"]):
                if (wing and p["wing"] != wing) or (c["name"], k) in seen:
                    continue
                seen.add((c["name"], k))
                out.append({"kind": "polygon", "page": 0, "points": p["points"], "category": c["name"],
                            "label": f"{c['name']} ({p['wing']}): measured {_fmt(p['area_sf'])} SF",
                            "value": round(p["area_sf"] * SF_TO_M2, 1), "unit": "m²", "role": "cross-check"})
    return out


def _answer_measured(meta, question, metric):
    z = zones(meta)
    if not z:
        return None
    ql = question.lower()
    qt = {_stem(t) for t in _toks(question)}
    wing = next((w_ for w_ in WINGS if re.search(rf"\b{w_}\b", ql)), None)
    hit = [c for c in z["categories"] if qt & {_stem(t) for t in _toks(c["name"])}]
    # every content word of the question must be a legend word (or context): "total bedroom area in the
    # dormitory module" names bedrooms, which the DORMITORY colour does not measure, so abstain
    named = {_stem(t) for c in z["categories"] for t in _toks(c["name"])}
    uncovered = qt - named - CONTEXT
    if hit and uncovered and not re.search(r"colou?r|legend|zone", ql):
        return None
    if not hit:
        if qt - set(WINGS) - {"wing", "total", "common"} and not re.search(r"colou?r|legend|zone|different|each|type", ql):
            return None  # asks about something the legend does not name
        hit = z["categories"]
    is_metric = bool(metric)
    ev, rows_, vals = [], [], []
    for c in hit:
        a = c["wings"].get(wing, 0.0) if wing else c["area_sf"]
        v, u = _conv(a, "SF", is_metric)
        vals.append(v)
        rows_.append(f"{c['name']}{' (' + wing + ' wing)' if wing else ''}: {_fmt(v, 1 if is_metric else 0)} {u}")
        ev.append({"kind": "box", "page": 0, "bbox": _pad(_union([c["swatch"], c["legend_bbox"]])),
                   "label": f"legend: {c['name']}", "value": None})
        for p in c["parts"]:
            if wing and p["wing"] != wing:
                continue
            pv, _ = _conv(p["area_sf"], "SF", is_metric)
            ev.append({"kind": "polygon", "page": 0, "points": p["points"], "category": c["name"],
                       "label": f"{c['name']} ({p['wing']}): {_fmt(pv, 1 if is_metric else 0)} {u}",
                       "value": round(p["area_sf"] * SF_TO_M2, 1), "unit": "m²"})
    u = "m²" if is_metric else "SF"
    if len(hit) == 1 or (not re.search(r"different|each|type|categor|legend|breakdown", ql) and
                         re.search(r"total|sum|combined|together", ql)):
        s = sum(vals)
        ans = round(s, 1) if is_metric else int(round(s))
        expl_v = " + ".join(_fmt(v, 1 if is_metric else 0) for v in vals) + f" = {_fmt(s, 1 if is_metric else 0)} {u}" \
            if len(vals) > 1 else f"{_fmt(s, 1 if is_metric else 0)} {u}"
        expl = f"{', '.join(c['name'] for c in hit)}: {expl_v}"
    else:
        ans = "; ".join(rows_)
        expl = "; ".join(rows_)
    expl += (f". Measured from the legend colours on the plan (footprint of each colour, walls and furniture closed, "
             f"split by nearest colour) at {z['px_per_ft']:.2f} px/ft ({z['scale_how']}); a measurement, so expect a "
             f"few % against a schedule")
    sc = scale(meta)
    return {"answer": ans, "confidence": 0.5, "method": "sheets-zones-measured", "cost_usd": 0.0,
            "explanation": expl, "evidence": ev + _scale_ev(sc), "unit": u}


# ------------------------------------------------------------------------------------------------------- detect
def detect(meta) -> float:
    """High when the sheet carries an area / count schedule or a colour legend (computed from OCR, cached)."""
    s = 0.0
    if (meta.get("classify") or {}).get("has_tables"):
        s = 0.4
    try:
        rs = rows(meta) if (meta.get("image") or meta.get("words")) else []
    except Exception:  # noqa: BLE001
        rs = []
    na = sum(r["kind"] == "area" for r in rs)
    if na >= 3:
        s = max(s, 0.9)
    elif na >= 1:
        s = max(s, 0.6)
    elif rs:
        s = max(s, 0.5)
    if s < 0.9 and meta.get("image"):
        try:
            if len(legend(meta)) >= 2:
                s = max(s, 0.8)
        except Exception:  # noqa: BLE001
            pass
    return s
