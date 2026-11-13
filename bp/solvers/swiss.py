"""Swiss Dwellings solver: exact answers from the DXF twin of the asked PDF/PNG.

Question -> intent with multilingual patterns (en/de/fr/it), then pure geometry.
Evidence is drawn on the PDF page the user asked about (coordinates mapped via
room numbers that appear in both files).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from bp.data import data_root
from bp.swiss.parse import FILL_COMMON, parse_floor

SYMBOL_PATTERNS = [
    ("apartment", r"apartments|wohnungen|appartamenti|logements|appartements"),
    ("door", r"\bdoors\b|türen|portes|porte\b"),
    ("window", r"windows|fenster|fenêtres|finestre"),
    ("toilet", r"toilets|\bwcs?\b"),
    ("washbasin", r"washbasins|lavabos|lavabi"),
    ("bathtub", r"bathtubs|badewannen|baignoires|vasche"),
    ("shower", r"showers|duschen|douches|docce"),
]
LABEL_KW = r"labell?ed|bezeichnung|désignation|désignées|denominazione|denominati"
NUMBERED_KW = r"numbered|nummerierten|numérotées|numerati"
APT_RE = r"(?:apartment|wohnung|appartement|appartamento)\s+([A-Z]{1,2}\d*)\b"
ROOM_RE = r"(?:room|raum|pièce|locale)\s+([A-Z]?\d+(?:\.\d+)*)\s*\("


def _quoted(q: str) -> str | None:
    m = re.search(r"«\s*(.+?)\s*»", q)
    if m:
        return m.group(1)
    m = re.search(r"'(.+)'", q)  # greedy: handles labels like 'Cage d'escalier'
    return m.group(1) if m else None


def parse_question(q: str, qtype: str):
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
            return None, None
        return parse_floor(str(dxf), str(pdf) if pdf.exists() else None), str(Path(q["path"]).with_suffix(".pdf"))

    def __call__(self, q):
        intent = parse_question(q["question"], q["type"])
        fl, pdf_rel = self.floor_for(q)
        base = {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": "swiss-dxf"}
        if intent is None or fl is None:
            return {**base, "explanation": "question not understood" if fl else "no DXF twin"}
        ev = []

        def box(geom, label, value=None):
            if fl.to_page:
                ev.append({"kind": "box", "file": pdf_rel, "page": 0, "bbox": fl.norm_bbox(geom, 0.1),
                           "label": label, "value": value})

        def poly(room, value):
            if fl.to_page and room.poly.area > 0:
                lab = " ".join(x for x in (room.number, room.name) if x)
                ev.append({"kind": "polygon", "file": pdf_rel, "page": 0, "points": fl.norm_poly(room.poly),
                           "label": lab, "value": value})

        kind = intent[0]
        if kind == "count_symbol":
            what = intent[1]
            if what == "apartment":
                items = list(fl.units.items())
                for i, (letter, up) in enumerate(sorted(items), 1):
                    box(up, f"{i}: apartment {letter}", 1)
                n = len(items)
                expl = f"{n} apartment outlines with a unit label"
            else:
                syms = sorted((s for s in fl.symbols if s.kind == what),
                              key=lambda s: (-round(s.geom.centroid.y, 0), s.geom.centroid.x))
                for i, s in enumerate(syms, 1):
                    box(s.geom, f"{what} {i}", 1)
                n = len(syms)
                expl = f"{n} {what} symbols found in the CAD layers"
            return {**base, "answer": n, "confidence": 0.97, "evidence": ev, "explanation": expl}

        rooms_num = [r for r in fl.rooms if r.number]
        if kind == "count_label":
            label = _norm(intent[1])
            hits = [r for r in rooms_num if _norm(r.name) == label]
            for i, r in enumerate(hits, 1):
                poly(r, 1)
            conf = 0.97 if hits or any(_norm(r.name) for r in rooms_num) else 0.5
            return {**base, "answer": len(hits), "confidence": conf, "evidence": ev,
                    "explanation": f"{len(hits)} rooms labelled '{intent[1]}'"}

        if kind == "area_room":
            num = intent[1]
            hits = [r for r in rooms_num if r.number == num]
            if not hits:
                return {**base, "explanation": f"room {num} not found"}
            r = hits[0]
            poly(r, r.area)
            src = "printed label" if r.area_text is not None else "outline geometry"
            return {**base, "answer": round(r.area, 2), "confidence": 0.97, "evidence": ev,
                    "explanation": f"room {num} {r.name or ''}: {r.area:.2f} m² ({src})"}

        if kind == "area_label":
            label = _norm(intent[1])
            hits = [r for r in rooms_num if _norm(r.name) == label]
            for r in hits:
                poly(r, r.area)
            tot = round(sum(r.area for r in hits), 2)
            return {**base, "answer": tot, "confidence": 0.95 if hits else 0.3, "evidence": ev,
                    "explanation": " + ".join(f"{r.area:.2f}" for r in hits) + f" = {tot:.2f} m²"}

        if kind == "area_numbered":
            hits = [r for r in rooms_num if not r.outdoor and not r.shaft_void]
            for r in hits:
                poly(r, r.area)
            tot = round(sum(r.area for r in hits), 2)
            return {**base, "answer": tot, "confidence": 0.9, "evidence": ev,
                    "explanation": f"sum of {len(hits)} numbered indoor rooms = {tot:.2f} m²"}

        if kind == "area_apartment":
            letter = intent[1]
            if letter not in fl.units:
                return {**base, "explanation": f"apartment {letter} not found"}
            hits = [r for r in rooms_num if r.unit == letter and not r.outdoor and not r.shaft_void and r.fill != FILL_COMMON]
            for r in hits:
                poly(r, r.area)
            tot = round(sum(r.area for r in hits), 2)
            return {**base, "answer": tot, "confidence": 0.9, "evidence": ev,
                    "explanation": f"apartment {letter}: {len(hits)} rooms = {tot:.2f} m²"}
        return base
