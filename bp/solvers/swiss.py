"""Swiss Dwellings solver: exact answers from the DXF twin of the asked PDF/PNG.

Question -> intent with multilingual patterns (en/de/fr/it), then pure geometry (bp/swiss/parse.py).
Evidence is drawn on the page the user asked about (the PDF, or its PNG render: same page, same
normalised coordinates), mapped via room numbers that appear in both files.

Confidence is lowered wherever the parse took a path that is rarely exercised on dev
(unusual fixture signature, label found by distance, apartment drawn as several outlines,
no PDF fills to tell outdoor spaces apart, ...), so the router can fall back.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from bp.data import data_root
from bp.swiss.parse import FILL_COMMON, parse_floor

SYMBOL_PATTERNS = [
    ("apartment", r"apartments?\b|wohnungen|appartamenti|logements|appartements|residential units"),
    ("door", r"\bdoors?\b|türen|\bportes?\b"),
    ("window", r"windows?\b|fenster|fenêtres?|finestre"),
    ("toilet", r"toilets?\b|\bwcs?\b"),
    ("washbasin", r"wash ?basins?|lavabos?\b|lavabi|sinks?\b"),
    ("bathtub", r"bath ?tubs?|badewannen?|baignoires?|vasche|vasca"),
    ("shower", r"showers?\b|duschen?|douches?|docce|doccia"),
]
LABEL_KW = r"labell?ed|bezeichnung|désignation|désignées|denominazione|denominati"
NUMBERED_KW = r"numbered|nummerierten|numérotées|numerati"
APT_RE = r"(?:apartment|wohnung|appartement|appartamento|unit)\s+([A-Z]{1,2}\d*)\b"
ROOM_RE = r"(?:room|raum|pièce|locale)\s+([A-Z]?\d+(?:\.\d+)*)\s*\("
SANITARY = ("toilet", "washbasin", "bathtub", "shower")


def _quoted(q: str) -> str | None:
    m = re.search(r"«\s*(.+?)\s*»", q)
    if m:
        return m.group(1)
    m = re.search(r"[\"“„](.+?)[\"”“]", q)
    if m:
        return m.group(1)
    m = re.search(r"'(.+)'", q)  # greedy: handles labels like 'Cage d'escalier'
    return m.group(1) if m else None


def parse_question(q: str, qtype: str | None):
    ql = q.lower()
    if qtype == "count":
        if re.search(LABEL_KW, ql):
            return ("count_label", _quoted(q))
        for kind, pat in SYMBOL_PATTERNS:
            if re.search(pat, ql):
                return ("count_symbol", kind)
        return None
    if qtype == "area":
        m = re.search(APT_RE, q, re.I)
        if m and re.search(r"apartment|wohnung|appartement|appartamento", ql):
            return ("area_apartment", m.group(1).upper())
        m = re.search(ROOM_RE, q, re.I)
        if m:
            return ("area_room", m.group(1), _quoted(q))
        if re.search(NUMBERED_KW, ql):
            return ("area_numbered", None)
        if re.search(LABEL_KW, ql):
            return ("area_label", _quoted(q))
    return None


def _norm(s):
    return unicodedata.normalize("NFKC", s or "").strip().lower()


class SwissSolver:
    def __init__(self, variant=None):
        self.root = data_root()

    def floor_for(self, q):
        p = self.root / q["path"]
        dxf = p.with_suffix(".dxf")
        pdf = p.with_suffix(".pdf")
        if not dxf.exists():
            return None
        return parse_floor(str(dxf), str(pdf) if pdf.exists() else None)

    def __call__(self, q):
        base = {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": "swiss-dxf"}
        intent = parse_question(q["question"], q.get("type"))
        try:
            fl = self.floor_for(q)
        except Exception as e:  # noqa: BLE001  one unreadable drawing must not take the run down
            return {**base, "explanation": f"DXF twin could not be parsed: {type(e).__name__}: {str(e)[:120]}"}
        if fl is None:
            return {**base, "explanation": "no DXF twin"}
        if intent is None:
            return {**base, "explanation": "question not understood"}
        try:
            return self._answer(q, fl, intent, base)
        except Exception as e:  # noqa: BLE001
            return {**base, "explanation": f"solver error: {type(e).__name__}: {str(e)[:120]}"}

    def _answer(self, q, fl, intent, base):
        # evidence goes on the asked drawing if it is the PDF or its PNG render (same page, same
        # normalised coordinates); anything else gets it on the PDF twin
        ext = Path(q["path"]).suffix.lower()
        page_file = q["path"] if ext in (".pdf", ".png") else str(Path(q["path"]).with_suffix(".pdf"))
        ev = []
        notes = []  # reasons the confidence was lowered
        if not fl.to_page:
            notes.append("no page mapping (no evidence)")
        elif fl.fit_rms is not None and fl.fit_rms > 0.004:
            notes.append(f"page mapping is loose (rms {fl.fit_rms:.3f})")

        def box(geom, label, value=None, pad=0.1):
            if fl.to_page:
                ev.append({"kind": "box", "file": page_file, "page": 0, "bbox": fl.norm_bbox(geom, pad),
                           "label": label, "value": value})

        def poly(room, value, label=None):
            if fl.to_page and room.poly.area > 0:
                lab = label or " ".join(x for x in (room.number, room.name) if x)
                ev.append({"kind": "polygon", "file": page_file, "page": 0, "points": fl.norm_poly(room.poly),
                           "label": lab, "value": value})

        def area_text(room):
            # the printed "x.xx m²" on the PDF, if the label has one
            if not (fl.to_page and room.area_pos and fl.pdf_words):
                return
            u, v = fl.norm_pt(*room.area_pos)
            want = f"{room.area_text:.2f}"
            cands = [w for w in fl.pdf_words if w[0] == want]
            if cands:
                w = min(cands, key=lambda w: (w[1] + w[3] - 2 * u) ** 2 + (w[2] + w[4] - 2 * v) ** 2)
                if abs((w[1] + w[3]) / 2 - u) < 0.02 and abs((w[2] + w[4]) / 2 - v) < 0.02:
                    ev.append({"kind": "text", "file": page_file, "page": 0,
                               "bbox": [round(c, 5) for c in w[1:]], "label": f"label read: '{want} m²'"})

        def done(answer, c, expl):
            if notes:  # page-mapping notes only concern the evidence; the rest is already in c
                expl += " [" + "; ".join(dict.fromkeys(notes)) + "]"
            return {**base, "answer": answer, "confidence": round(c, 2), "evidence": ev, "explanation": expl}

        def room_conf(rooms):
            """Confidence from how each room's outline and area were found."""
            c = 0.98
            for r in rooms:
                if r.assigned in ("nearest", "none"):
                    c = min(c, 0.7)
                    notes.append(f"room {r.number}: label outside every outline")
                elif r.assigned == "shared":
                    c = min(c, 0.75)
                    notes.append(f"room {r.number}: outline shared with another label")
                if r.area_text is None and r.holes:
                    c = min(c, 0.9)
                    notes.append(f"room {r.number}: {len(r.holes)} shaft(s) subtracted")
            return c

        kind = intent[0]
        if kind == "count_symbol":
            what = intent[1]
            if what == "apartment":
                items = sorted(fl.units.items())
                for i, (letter, up) in enumerate(items, 1):
                    box(up, f"apartment {i}", 1, pad=0.0)
                n = len(fl.unit_labels)
                c = 0.97
                if n != len(items):
                    c = 0.7
                    notes.append("a unit label has no outline")
                if fl.n_unit_outlines != n:
                    c = min(c, 0.93)  # more outlines than labels: labels decide (always so on dev)
                expl = (f"{n} labelled apartments ({', '.join(fl.unit_labels)}); "
                        f"{fl.n_unit_outlines} unit outlines on layer UNIT_OUTLINE")
                return done(n, c, expl)
            syms = sorted((s for s in fl.symbols if s.kind == what),
                          key=lambda s: (-round(s.geom.centroid.y, 0), s.geom.centroid.x))
            for i, s in enumerate(syms, 1):
                box(s.geom, f"{what} {i}", 1, pad=0.03 if what not in ("door", "window") else 0.05)
            n = len(syms)
            c = 0.98 if what in ("door", "window") else 0.97
            unsure = [s for s in syms if not s.sure]
            if unsure:
                c = 0.7
                notes.append(f"{len(unsure)} {what} symbol(s) with an unusual drawing")
            if what in SANITARY:
                # unknown fixture shapes inside a wet room might be the asked fixture drawn differently
                wet = [r.poly for r in fl.rooms if r.number and any(
                    r.poly.contains(s.geom.centroid) for s in fl.symbols if s.kind in SANITARY)]
                odd = [s for s in fl.symbols if s.kind == "other" and s.odd
                       and any(p.contains(s.geom.centroid) for p in wet)]
                if odd:
                    c = min(c, 0.75)
                    notes.append(f"{len(odd)} unrecognised fixture(s) in a bathroom")
            src = "layer DOOR (one frame polyline each)" if what == "door" else \
                "layer WINDOW (one outline each)" if what == "window" else "layer FIXTURE (classified by shape)"
            return done(n, c, f"{n} {what} symbols on {src}")

        rooms_num = [r for r in fl.rooms if r.number]
        if kind == "count_label":
            label = _norm(intent[1])
            if not label:
                return {**base, "explanation": "no room label found in the question"}
            hits = sorted((r for r in rooms_num if _norm(r.name) == label),
                          key=lambda r: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", r.number)])
            for i, r in enumerate(hits, 1):
                poly(r, 1, f"room {i}: {r.number} {r.name}")
            c = 0.97
            if not hits:
                # the plan has no such name at all: 0 is likely right only if the name is foreign to the plan
                c = 0.6
                notes.append("label not found on this plan")
            return done(len(hits), c, f"{len(hits)} rooms labelled '{intent[1]}'"
                        + (f": {', '.join(r.number for r in hits)}" if hits else ""))

        if kind == "area_room":
            num = intent[1]
            hits = [r for r in rooms_num if r.number == num]
            if not hits:
                return {**base, "explanation": f"room {num} not found"}
            r = hits[0]
            c = room_conf([r])
            if intent[2] and r.name and _norm(intent[2]) != _norm(r.name):
                c = min(c, 0.6)
                notes.append(f"room {num} is labelled '{r.name}', question says '{intent[2]}'")
            if len(hits) > 1:
                c = min(c, 0.6)
                notes.append(f"room number {num} appears {len(hits)} times")
            poly(r, r.area)
            area_text(r)
            src = "printed label" if r.area_text is not None else "outline geometry"
            return done(round(r.area, 2), c, f"room {num} {r.name or ''}: {r.area:.2f} m² ({src})")

        if kind == "area_label":
            label = _norm(intent[1])
            hits = [r for r in rooms_num if _norm(r.name) == label]
            for r in hits:
                poly(r, r.area)
            tot = round(sum(r.area for r in hits), 2)
            c = room_conf(hits) if hits else 0.3
            if not hits:
                notes.append("label not found on this plan")
            return done(tot, c, (" + ".join(f"{r.area:.2f}" for r in hits) or "0") + f" = {tot:.2f} m²")

        if kind == "area_numbered":
            hits = [r for r in rooms_num if not r.outdoor and not r.shaft_void]
            for r in hits:
                poly(r, r.area)
            tot = round(sum(r.area for r in hits), 2)
            c = min(room_conf(hits), 0.97)
            nofill = [r for r in rooms_num if r.fill is None]
            if not fl.pdf_words and not any(r.fill for r in rooms_num):
                c = min(c, 0.6)
                notes.append("no PDF room fills: outdoor spaces told apart by name only")
            elif nofill:
                c = min(c, 0.85)
                notes.append(f"{len(nofill)} room(s) without a PDF fill")
            n_out = sum(1 for r in rooms_num if r.outdoor)
            return done(tot, c, f"sum of {len(hits)} numbered indoor rooms = {tot:.2f} m² "
                                f"({n_out} outdoor excluded)")

        if kind == "area_apartment":
            letter = intent[1]
            if letter not in fl.units:
                return {**base, "explanation": f"apartment {letter} not found"}
            hits = [r for r in rooms_num if r.unit == letter and not r.outdoor and not r.shaft_void
                    and r.fill != FILL_COMMON]
            for r in hits:
                poly(r, r.area)
            tot = round(sum(r.area for r in hits), 2)
            c = min(room_conf(hits), 0.97)
            if letter in fl.unit_by_distance:
                c = min(c, 0.7)
                notes.append(f"label 'apartment {letter}' lies outside its outline")
            if letter in fl.unit_merged:
                c = min(c, 0.7)
                notes.append(f"apartment {letter} is drawn as several outlines")
            if any(r.fill is None for r in hits):
                c = min(c, 0.8)
                notes.append("room(s) without a PDF fill")
            return done(tot, c, f"apartment {letter}: {len(hits)} rooms = {tot:.2f} m²")
        return {**base, "explanation": "question not understood"}
