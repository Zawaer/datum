"""Swiss Dwellings solver: exact answers from the DXF twin of the asked PDF/PNG.

Question -> intent with multilingual patterns (en/de/fr/it), then pure geometry (bp/swiss/parse.py).
Evidence is drawn on the page the user asked about (the PDF, or its PNG render: same page, same
normalised coordinates), mapped via room numbers that appear in both files.

Confidence is lowered wherever the parse took a path that is rarely exercised on dev
(unusual fixture signature, label found by distance, apartment drawn as several outlines,
no PDF fills to tell outdoor spaces apart, ...), so the router can fall back.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from bp import compare as C
from bp import notfound as NF
from bp.data import data_root
from bp.swiss import rooms as RK
from bp.swiss.parse import FILL_COMMON, parse_floor
from bp.swiss.rooms import kind_match
from bp.templates import _SQ

SYMBOL_PATTERNS = [
    ("apartment", r"apartments?\b|wohnungen|appartamenti|logements|appartements|residential units"),
    ("door", r"\bdoors?\b|türen|\bportes?\b"),
    ("window", r"windows?\b|fenster|fenêtres?|finestre"),
    ("toilet", r"toilets?\b|\bwcs?\b"),
    ("washbasin", r"wash ?basins?|lavabos?\b|lavabi|sinks?\b"),
    ("bathtub", r"bath ?tubs?|badewannen?|baignoires?|vasche|vasca"),
    ("shower", r"showers?\b|duschen?|douches?|docce|doccia"),
]
LABEL_KW = r"labell?ed|bezeichnung|désignation|désignées|denominazione|denominati|\b(?:marked|tagged|called|named)\b"
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
    # paired and word-boundary aware: "What's" opens nothing, 'Cage d'escalier' stays whole
    m = re.search(_SQ, q)
    return m.group(0)[1:-1] if m else None


_TOTAL_KW = (r"\b(?:total\w*|all|combined|together|altogether|sum\w*|gesamt\w*|insgesamt|alle[nrs]?|zusammen|tous|"
             r"toutes|ensemble|tutt[ie]|complessiv\w*|somm\w*)\b")


_PLURAL_WORDS = {"küchen", "bäder", "balkone", "räume", "flure", "korridore", "terrassen", "treppen", "bagni", "cucine",
                 "camere", "balconi", "stanze", "logge", "corridoi", "terrazze"}


def _apartment(q: str):
    """'apartment B' / 'Wohnung A' / 'unit C' (an upper-case letter, so 'apartments are' is not one)."""
    m = re.search(r"(?i:apartment|wohnung|appartement|appartamento|logement|unit)\s+([A-Z]{1,2}\d*)\b", q)
    return m.group(1) if m else None


def _kind_intent(q: str, what: str):
    """Room-kind intents for free wording ("How many bathrooms?", "area of the kitchen"), from bp/swiss/rooms.py."""
    # "... except balconies, loggias" names kinds the question is NOT about
    text = re.sub(r"\b(?:except|excluding|exclusive of|without|not counting|apart from|ohne|ausser|außer|exkl\w*|hors|"
                  r"sauf|sans|esclus[aeio]|escluso|eccetto|tranne|senza)\b.*", "", strip_quoted(q), flags=re.I | re.S)
    km = kind_match(text)
    if km is None:
        return None
    kind, word = km
    if what == "count":
        return ("count_kind", kind, _apartment(q))
    plural = bool(re.search(_TOTAL_KW, q, re.I)) or word.endswith("s") or word in _PLURAL_WORDS
    return ("area_kind", kind, _apartment(q), plural)


def strip_quoted(q: str) -> str:
    return re.sub(r"«[^»]*»|[\"“„][^\"”“]*[\"”“]", " ", q)


def parse_question(q: str, qtype: str | None):
    ql = q.lower()
    if qtype == "count":
        if re.search(LABEL_KW, ql):
            lab = _quoted(q)
            if lab is None and (ki := _kind_intent(q, "count")):
                return ki  # "rooms labelled bathroom": no quoted label, but an everyday room word
            return ("count_label", lab)
        # "toilet rooms" / "separate WCs" are rooms, not the toilet symbol; "bathrooms in apartment B" are rooms,
        # not apartments
        ki = _kind_intent(q, "count")
        if ki and (ki[1] == "toilet_room" or ki[2]):
            return ki
        for kind, pat in SYMBOL_PATTERNS:
            if re.search(pat, ql):
                return ("count_symbol", kind)
        return ki
    if qtype == "area":
        m = re.search(APT_RE, q, re.I)
        if m and re.search(r"apartment|wohnung|appartement|appartamento", ql) and not (
                (ki := _kind_intent(q, "area")) and ki[1] != "room" and _apartment(q)):
            return ("area_apartment", m.group(1).upper())
        m = re.search(ROOM_RE, q, re.I)
        if m:
            return ("area_room", m.group(1), _quoted(q))
        # free wording: "room 3.29 labeled 'Balkon'", "the 'Küche' room, U1.09": a room number like 3.29 / U1.09
        # (no dataset area template other than the one above carries one)
        m = re.search(r"(?<![\w.])([A-Z]?\d+\.\d{2})(?![\w.])", q)
        if m and re.search(r"room|raum|pièce|locale|stanza", ql):
            return ("area_room", m.group(1), _quoted(q.replace(f'"{m.group(1)}"', m.group(1))
                                                      .replace(f"'{m.group(1)}'", m.group(1))))
        if re.search(NUMBERED_KW, ql):
            return ("area_numbered", None)
        if re.search(LABEL_KW, ql):
            lab = _quoted(q)
            if lab is None and (ki := _kind_intent(q, "area")):
                return ki
            return ("area_label", lab)
        if _quoted(q) is None and (ki := _kind_intent(q, "area")) and ki[1] != "room":
            return ki
    return None


ROOM_LABELS = set(json.loads((Path(__file__).resolve().parents[1] / "swiss/room_labels.json").read_text()))


def _norm(s):
    return unicodedata.normalize("NFKC", s or "").strip().lower()


def _apt_rooms(rooms_num, letter):
    """The rooms an apartment's net area sums (outdoor spaces, shafts and common rooms excluded)."""
    return [r for r in rooms_num if r.unit == letter and not r.outdoor and not r.shaft_void and r.fill != FILL_COMMON]


def _apt_conf(fl, letter, hits, room_conf, notes):
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
    return c


def _kind_rooms(fl, kind, pool):
    """(rooms of one kind, the unnamed ones among them) in `pool`: by label (bp/swiss/rooms.py); many plans print
    bathrooms / WCs with a number but no name, and their fixtures say what they are: a bath or shower inside the
    outline = bathroom, a toilet without one = separate toilet room."""
    hits = [r for r in pool if r.name and RK.matches(kind, r.name)]
    unnamed = []
    if kind in ("bathroom", "toilet_room"):
        def holds(r, kinds):
            return any(s.kind in kinds and r.poly.intersects(s.geom.centroid) for s in fl.symbols)
        for r in pool:
            if r.name:
                continue
            wet = holds(r, ("bathtub", "shower"))
            if (kind == "bathroom" and wet) or (kind == "toilet_room" and not wet and holds(r, ("toilet",))):
                unnamed.append(r)
        hits += unnamed
    return hits, unnamed


def _rname(r):
    return " ".join(x for x in (r.number, f"'{r.name}'" if r.name else "(unnamed)") if x)


def _nat(r):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", r.number)]


ROOM_NUM_RE = r"(?<![\w.])([a-z]?\d+\.\d{2})(?![\w.])"



def _holes(fl, poly) -> list:
    """Inner rings (courtyards, rooms a corridor wraps around) in page coordinates, so the UI can cut them out."""
    ax, bx, ay, by = fl.to_page
    geom = poly if poly.geom_type == "Polygon" else max(poly.geoms, key=lambda p: p.area)
    return [[[round(ax * x + bx, 5), round(ay * y + by, 5)] for x, y in r.coords]
            for r in geom.interiors if len(r.coords) >= 4]

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
        # comparisons first ("is apartment B bigger than A?"); no dataset question parses as one (bp/compare.py)
        cp = C.parse(q["question"])
        intent = ("compare", cp) if cp else parse_question(q["question"], q.get("type"))
        try:
            fl = self.floor_for(q)
        except Exception as e:  # noqa: BLE001  one unreadable drawing must not take the run down
            return {**base, "method": "swiss-error", "error": f"parse: {type(e).__name__}: {str(e)[:200]}",
                    "explanation": f"DXF twin could not be parsed: {type(e).__name__}: {str(e)[:120]}"}
        if fl is None:
            return {**base, "explanation": "no DXF twin"}
        if intent is None:
            labels = sorted({r.name for r in fl.rooms if r.number and r.name})
            return {**base, "explanation": "question not understood; this plan can answer counts of rooms by label "
                    "or kind (bathrooms, kitchens, bedrooms, balconies ...), of doors, windows, toilets, washbasins, "
                    "bathtubs, showers and apartments, and room or apartment areas. Room labels on this plan: "
                    + ", ".join(f"'{x}'" for x in labels)}
        try:
            out = self._answer(q, fl, intent, base)
            if out.get("read_as"):  # a room word mapped onto the plan's own label: say how it was read
                out["normalized_question"] = rq = out.pop("read_as")
                out["explanation"] = f"read as: {rq} | {out.get('explanation') or ''}"
            return out
        except Exception as e:  # noqa: BLE001
            return {**base, "method": "swiss-error", "error": f"answer: {type(e).__name__}: {str(e)[:200]}",
                    "explanation": f"solver error: {type(e).__name__}: {str(e)[:120]}"}

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
                           "holes": _holes(fl, room.poly), "label": lab, "value": value})

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
                # 0 is a real answer only for a room name this kind of plan uses (the 34 labels the dev split asks
                # about: 'Küche', 'Balcon', ...; dev never asks for a label that is absent, so this costs nothing
                # there). Anything else is more likely a misread name than an honest zero.
                if label not in ROOM_LABELS:
                    return NF.abstain(base, "label", intent[1], [r.name for r in rooms_num])
                c = 0.6
                notes.append("label not found on this plan")
            return done(len(hits), c, f"{len(hits)} rooms labelled '{intent[1]}'"
                        + (f": {', '.join(r.number for r in hits)}" if hits else ""))

        if kind in ("count_kind", "area_kind"):
            return self._kind(fl, intent, rooms_num, base, poly, area_text, done, room_conf)

        if kind == "compare":
            return self._compare(fl, intent[1], rooms_num, base, poly, box, done, room_conf, notes, q.get("type"))

        if kind == "area_room":
            num = intent[1]
            hits = [r for r in rooms_num if r.number == num]
            if not hits:
                return NF.abstain(base, "room", num, [r.number for r in rooms_num])
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
            if not hits:  # an area summed over nothing is not an answer
                return NF.abstain(base, "label", intent[1], [r.name for r in rooms_num])
            for r in hits:
                poly(r, r.area)
            tot = round(sum(r.area for r in hits), 2)
            c = room_conf(hits)
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
                return NF.abstain(base, "apartment", letter, sorted(fl.units))
            hits = _apt_rooms(rooms_num, letter)
            for r in hits:
                poly(r, r.area)
            tot = round(sum(r.area for r in hits), 2)
            c = _apt_conf(fl, letter, hits, room_conf, notes)
            return done(tot, c, f"apartment {letter}: {len(hits)} rooms = {tot:.2f} m²")
        return {**base, "explanation": "question not understood"}

    @staticmethod
    def _kind(fl, intent, rooms_num, base, poly, area_text, done, room_conf):
        """Rooms of one everyday kind ("bathrooms") = rooms whose label means it (bp/swiss/rooms.py)."""
        kind, letter = intent[1], intent[2]
        name = RK.kind_name(kind)
        if letter is not None and letter not in fl.units:
            return NF.abstain(base, "apartment", letter, sorted(fl.units))
        pool = [r for r in rooms_num if letter is None or r.unit == letter]
        where = f" in apartment {letter}" if letter else ""
        hits, unnamed = _kind_rooms(fl, kind, pool)
        hits = sorted(hits, key=lambda r: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", r.number)])
        labels = sorted({r.name for r in hits if r.name})
        fx = "a bath or shower" if kind == "bathroom" else "a toilet"
        all_labels = sorted({r.name for r in rooms_num if r.name})
        word_labels = ", ".join(f"'{RK.display(x)}'" for x in RK.labels_for(kind)[:6])
        listing = "labels on this plan: " + ", ".join(f"'{x}'" for x in all_labels)
        lab_q = " or ".join(f"'{x}'" for x in labels)
        if intent[0] == "count_kind":
            if not hits:
                known = all(RK.norm(x) in RK.VOCAB for x in all_labels)
                if kind not in RK.ZERO_OK or not known or not pool:
                    return {**base, "explanation": f"no room{where} is labelled as a {name} ({word_labels}); "
                                                   f"{listing}. Ask for one of these labels"}
                return {**done(0, 0.85, f"no room{where} carries a {name} label ({word_labels}); {listing}"),
                        "read_as": f"How many rooms labelled as a {name} ({word_labels}) are there on this floor?"}
            for i, r in enumerate(hits, 1):
                poly(r, 1, f"{name} {i}: {r.number} {r.name}")
            per = ", ".join(f"{r.number} '{r.name}'" if r.name else f"{r.number} (unnamed, holds {fx})" for r in hits)
            what = "the plan's label for a bedroom or other room" if kind == "room" else f"the plan's word for {name}"
            n_lab = len(hits) - len(unnamed)
            parts = ([f"{n_lab} labelled {lab_q} ({what})"] if n_lab else []) + \
                    ([f"{len(unnamed)} numbered but unnamed, identified by {fx} drawn inside"] if unnamed else [])
            expl = f"{len(hits)} {name}{'s' if len(hits) != 1 else ''}{where}: " + "; ".join(parts) + f": {per}"
            c = 0.97
            if kind == "room":
                # "rooms" is the plan's 'Zimmer'/'Pièce'/'Stanza' label; say how many spaces there are in all
                c = 0.8
                expl += f"; all numbered spaces{where} (kitchens, baths, corridors ... included): {len(pool)}"
            what_q = f"rooms labelled {lab_q}" if not unnamed else (f"{name}s (rooms labelled {lab_q} or holding {fx})"
                                                                    if lab_q else f"{name}s (rooms holding {fx})")
            rq = f"How many {what_q} are there on this floor?" if not letter else \
                f"How many {what_q} are there in apartment {letter}?"
            return {**done(len(hits), c, expl), "read_as": rq}
        # area
        if not hits:
            return {**base, "explanation": f"no room{where} is labelled as a {name} ({word_labels}); {listing}"}
        plural = intent[3]
        if not plural and len(hits) > 1:
            return {**base, "explanation": f"{len(hits)} rooms{where} are labelled {lab_q} ("
                                           + ", ".join(r.number for r in hits) + "): ask for one by its number "
                                           f"(e.g. 'area of room {hits[0].number}') or for the total of all of them"}
        for r in hits:
            poly(r, r.area)
        if len(hits) == 1:
            area_text(hits[0])
        tot = round(sum(r.area for r in hits), 2)
        c = room_conf(hits)
        if len(hits) == 1:
            r = hits[0]
            rq = f"What is the net floor area of room {r.number} ('{r.name}') in m²?"
            expl = f"room {r.number} '{r.name}' (the {name}{where}): {r.area:.2f} m²"
        else:
            rq = f"What is the total net area in m² of all rooms labelled {lab_q}" + \
                (f" in apartment {letter}?" if letter else " on this floor?")
            expl = f"{len(hits)} rooms labelled {lab_q}{where}: " + " + ".join(f"{r.area:.2f}" for r in hits) + \
                f" = {tot:.2f} m²"
        return {**done(tot, c, expl), "read_as": rq}

    # ------------------------------------------------------------------ comparisons (bp/compare.py)
    @staticmethod
    def _compare(fl, cp, rooms_num, base, poly, box, done, room_conf, notes, qtype=None):
        """Superlatives and comparatives from the same rooms / apartment sums the area and count answers use."""
        res = {**base, "method": "swiss-dxf-compare", "comparison": cp["op"]}
        letters = sorted(fl.units)

        def fin(answer, c, expl):
            return {**done(answer, c, expl), "method": res["method"], "comparison": cp["op"]}

        cval = 1 if qtype == "count" else None  # (a 1 on a text-typed answer would be drawn as "1 m²")

        def ev_item(x, label):  # a counted room (outline) or symbol (box)
            if hasattr(x, "poly"):
                poly(x, cval, label)
            else:
                box(x.geom, label, cval, pad=0.05)

        def apt_in(text):
            m = re.search(rf"(?<!\w)(?:{C.APT})\s+([a-z]{{1,2}}\d*)(?!\w)", text)
            if m and m.group(1).upper() in fl.units:
                return m.group(1).upper()
            return None

        def indoor(pool):  # "rooms": labelled (or holding a fixture), not outdoor, not a shaft or void
            return [r for r in pool if not r.outdoor and not r.shaft_void and r.counts_as_room]

        def kind_pool(kind, pool, label=None):
            if label is not None:
                return [r for r in pool if _norm(r.name) == _norm(label)]
            if kind in (None, "room"):
                return indoor(pool)
            return _kind_rooms(fl, kind, pool)[0]

        def plural(name):
            if " (" in name:
                return name.replace(" (", "s (", 1)
            return name[:-1] + "ies" if name.endswith("y") else name + "s"

        def counted_what(text):
            """-> (plural description, function apartment letter -> (count, rooms or symbols)) or None"""
            lab = _quoted(text)
            if lab is not None:  # (the parse is lower-case: show the plan's own spelling)
                lab = next((r.name for r in rooms_num if _norm(r.name) == _norm(lab)), lab)
                def fl_(letter):
                    hits = [r for r in rooms_num if r.unit == letter and _norm(r.name) == _norm(lab)]
                    return len(hits), hits
                return f"rooms labelled '{lab}'", fl_
            km = C.kind_of(text)
            if km is not None:
                kind = km[0]

                def f(letter, kind=kind):
                    pool = [r for r in rooms_num if r.unit == letter]
                    hits = _kind_rooms(fl, kind, pool)[0] if kind != "room" else \
                        [r for r in pool if r.name and RK.matches("room", r.name)]
                    return len(hits), hits
                if kind == "room":
                    notes.append("rooms = the plan's 'Zimmer' / 'Pièce' / 'Stanza' and bedroom labels")
                return plural(RK.kind_name(kind)), f
            for sym, pat in SYMBOL_PATTERNS:
                if sym != "apartment" and re.search(pat, text):
                    def g(letter, sym=sym):
                        # a symbol belongs to the apartment of a room within 0.8 m of it (doors and windows sit in
                        # the walls between room outlines; an entrance door counts for its apartment)
                        hits = [x for x in fl.symbols if x.kind == sym and any(
                            r.unit == letter and r.poly.distance(x.geom.centroid) <= 0.8 for r in rooms_num)]
                        return len(hits), hits
                    return f"{sym}s", g
            return None

        def operand(text, other=None, count=False):
            """-> ("apt", letter) | ("rooms", [room], kind) | ("error", why). `other`: the left operand, whose
            kind / apartment-ness a bare right side ("... than apartment A's", "... than B") takes over."""
            letter = apt_in(text)
            m = re.search(rf"(?<!\w)(?:{C.APT})\s+([a-z])(?!\w)", text)
            if letter is None and m and m.group(1).upper() not in fl.units and fl.units:
                return "error", f"apartment {m.group(1).upper()} not found; apartments on this plan: " + \
                    ", ".join(letters)
            if letter is None and other and other[0] == "apt":
                m = re.fullmatch(r"(?:(?:the\s+one\s+of|that\s+of|the|die|der|das|l'|la|le|il|lo)\s*)?([a-z]{1,2})"
                                 r"(?:'s)?", text)
                if m and m.group(1).upper() in fl.units:
                    letter = m.group(1).upper()
            if count:
                return ("apt", letter) if letter else ("error", "could not tell which apartments to compare")
            ql = _quoted(text)
            km = C.kind_of(strip_quoted(text))
            kind = km[0] if km and km[0] != "room" else None
            if kind is None and ql is None and letter and other and other[0] == "rooms" and other[2]:
                kind = other[2]  # "is apartment B's kitchen bigger than apartment A's?"
            mnum = re.search(ROOM_NUM_RE, text)
            if mnum:
                hits = [r for r in rooms_num if r.number.lower() == mnum.group(1)]
                return ("rooms", hits[:1], None) if hits else ("error", f"room {mnum.group(1).upper()} not found")
            if ql or kind:
                pool = [r for r in rooms_num if letter is None or r.unit == letter]
                hits = kind_pool(kind, pool, ql)
                what = f"'{ql}'" if ql else f"the {RK.kind_name(kind)}"
                what += f" in apartment {letter}" if letter else ""
                if not hits:
                    return "error", f"no room labelled as {what} on this plan"
                if len(hits) > 1:
                    return "error", (f"{len(hits)} rooms are {what} (" + ", ".join(_rname(r) for r in hits) +
                                     "): name one by its number, e.g. 'room " + hits[0].number + "'")
                return "rooms", hits, kind
            if letter:
                return "apt", letter
            return "error", "could not tell what to compare"

        def value(op_):
            """-> (display name, m², rooms, confidence)"""
            if op_[0] == "apt":
                hits = _apt_rooms(rooms_num, op_[1])
                return (f"apartment {op_[1]}", round(sum(r.area for r in hits), 2), hits,
                        _apt_conf(fl, op_[1], hits, room_conf, notes))
            r = op_[1][0]
            return f"room {_rname(r)}", round(r.area, 2), [r], room_conf([r])

        if cp["op"] in ("cmp", "diff", "which2"):
            if cp["measure"] == "count":
                cw = counted_what(cp["counted"])
                a = operand(cp["left"], count=True)
                b = operand(cp["right"], other=a, count=True)
                if cw is None or a[0] != "apt" or b[0] != "apt":
                    return {**res, "unparsed": True, "explanation": "count comparisons on this plan are between "
                            "apartments (" + ", ".join(letters) + ") and of rooms of one kind or of doors / windows / "
                            "fixtures, e.g. 'does apartment A have more bedrooms than apartment B?'"}
                what, f = cw
                (va, ia), (vb, ib) = f(a[1]), f(b[1])
                na, nb = f"apartment {a[1]}", f"apartment {b[1]}"
                for i, x in enumerate(ia, 1):
                    ev_item(x, f"apartment {a[1]}: {what[:-1]} {i}")
                for i, x in enumerate(ib, 1):
                    ev_item(x, f"apartment {b[1]}: {what[:-1]} {i}")
                if a[1] == b[1]:
                    return {**res, "explanation": f"both sides of the comparison are {na}"}
                expl, d = C.verdict_text(na, va, nb, vb, what)
                c = 0.95
            else:
                a = operand(cp["left"])
                b = operand(cp["right"], other=a)
                for x in (a, b):
                    if x[0] == "error":
                        return {**res, "unparsed": "could not tell" in x[1], "explanation": x[1]}
                if a[0] != b[0]:
                    notes.append("comparing a room with an apartment")
                (na, va, ra, ca), (nb, vb, rb, cb) = value(a), value(b)
                for r in ra:
                    poly(r, r.area, f"{na}: {_rname(r)}" if a[0] == "apt" else None)
                for r in rb:
                    poly(r, r.area, f"{nb}: {_rname(r)}" if b[0] == "apt" else None)
                if (na, ra) == (nb, rb):
                    return {**res, "explanation": f"both sides of the comparison are {na}"}
                expl, d = C.verdict_text(na, va, nb, vb, "m²")
                what, c = "m²", min(ca, cb)
            unit = what if cp["measure"] == "count" else "m²"
            if cp["op"] == "which2":
                if abs(d) < 1e-9:
                    return fin("equal", c, expl)
                win = (na, va) if (d > 0) == (cp["dir"] > 0) else (nb, vb)
                return fin(f"{win[0]} ({C.fmt(win[1], unit)})", c, expl)
            if cp["op"] == "diff":
                sign = 1 if cp["dir"] >= 0 else -1
                ans = round(abs(d), 2) if cp["dir"] == 0 else round(sign * d, 2)
                if cp["measure"] == "count":
                    ans = int(round(ans))
                neg, ans = ans < 0, C.typed(ans, unit, qtype)
                return fin(ans, c, expl + (" (asked the other way round, so the difference is negative)"
                                            if neg else ""))
            yes = d > 0 if cp["dir"] > 0 else d < 0
            if abs(d) < 1e-9:
                return fin("no, they are equal", c, expl)
            small = "smaller" if unit == "m²" else "fewer"
            big = "larger" if unit == "m²" else "more"
            ans = f"yes, by {C.fmt(abs(d), unit)}" if yes else \
                f"no, {na} is {small if cp['dir'] > 0 else big} by {C.fmt(abs(d), unit)}" if unit == "m²" else \
                f"no, {na} has {C.fmt(abs(d), unit)} {big if cp['dir'] < 0 else small}"
            return fin(ans, c, expl)

        # superlatives
        subj = cp["subject"]
        letter = apt_in(subj)
        best = max if cp["op"] == "max" else min
        word = ("largest" if cp["op"] == "max" else "smallest") if cp["measure"] == "area" else \
            ("most" if cp["op"] == "max" else "fewest")
        if cp["measure"] == "count":
            cw = counted_what(cp["counted"])
            if cw is None or not letters or letter or re.search(rf"(?<!\w)(?:{C.ROOM_WORD})(?!\w)", subj) and \
                    not re.search(rf"(?<!\w)(?:{C.APT})(?!\w)", subj):
                return {**res, "unparsed": cw is None, "explanation": "on this plan 'most' / 'fewest' compares "
                        "apartments (" + (", ".join(letters) or "none labelled") + ") by a count of rooms of one kind "
                        "or of doors / windows / fixtures, e.g. 'which apartment has the most bedrooms?'"}
            what, f = cw
            vals = {x: f(x) for x in letters}
            top = best(v[0] for v in vals.values())
            win = [x for x in letters if vals[x][0] == top]
            for x in win:
                for i, it in enumerate(vals[x][1], 1):
                    ev_item(it, f"apartment {x}: {what[:-1]} {i}")
            expl = f"{what} per apartment: " + ", ".join(f"{x} {vals[x][0]}" for x in letters) + \
                f"; {word}: " + " and ".join(f"apartment {x}" for x in win) + f" ({top})"
            ans = " and ".join(f"apartment {x}" for x in win) + f" ({top} {what if top != 1 else what[:-1]})"
            return fin(ans, 0.95 if len(letters) > 1 else 0.6, expl)
        ql = _quoted(subj)
        if ql is not None:
            ql = next((r.name for r in rooms_num if _norm(r.name) == _norm(ql)), ql)
        km = C.kind_of(strip_quoted(subj))
        if letter is None and km is None and ql is None and re.search(rf"(?<!\w)(?:{C.APT})(?!\w)", subj):
            if not letters:
                return {**res, "explanation": "no labelled apartments on this plan"}
            vals = {x: value(("apt", x)) for x in letters}
            top = best(v[1] for v in vals.values())
            win = [x for x in letters if vals[x][1] == top]
            for x in win:
                for r in vals[x][2]:
                    poly(r, r.area, f"apartment {x}: {_rname(r)}")
            c = min(vals[x][3] for x in letters)
            expl = "net area per apartment (rooms except outdoor spaces, shafts and common rooms): " + \
                ", ".join(f"{x} {vals[x][1]:.2f} m²" for x in letters) + f"; {word}: " + \
                " and ".join(f"apartment {x}" for x in win)
            if len(letters) == 1:
                c = min(c, 0.6)
                notes.append("only one apartment on this plan")
            return fin(" and ".join(f"apartment {x}" for x in win) + f" ({top:.2f} m²)", c, expl)
        pool = [r for r in rooms_num if letter is None or r.unit == letter]
        kind = km[0] if km else None
        cands = kind_pool(kind, pool, ql)
        if kind not in (None, "room") or ql:
            desc = f"rooms labelled '{ql}'" if ql else plural(RK.kind_name(kind))
        else:
            desc = "numbered indoor rooms (outdoor spaces, shafts, voids and unlabelled outlines excluded)"
        where = f" in apartment {letter}" if letter else " on this floor"
        if not cands:
            return {**res, "explanation": f"no {desc}{where}"}
        top = best(r.area for r in cands)
        win = sorted((r for r in cands if r.area == top), key=_nat)
        for r in win:
            poly(r, r.area, f"{word}: {_rname(r)}")
        rest = sorted((r for r in cands if r not in win), key=lambda r: -r.area if cp["op"] == "max" else r.area)
        for r in rest:
            poly(r, r.area)
        c = room_conf(cands)
        if len(cands) == 1:
            notes.append(f"only one {desc[:-1] if desc.endswith('s') else desc}{where}")
        expl = f"{word} of {len(cands)} {desc}{where}: " + " and ".join(f"{_rname(r)} {r.area:.2f} m²" for r in win)
        if rest:
            expl += "; next: " + ", ".join(f"{_rname(r)} {r.area:.2f} m²" for r in rest[:4])
        in_apt = bool(re.search(rf"(?<!\w)(?:{C.APT})(?!\w)", subj))  # "which flat has the biggest living room?"
        ans = " and ".join(_rname(r).replace("'", "") + (f" in apartment {r.unit}" if in_apt and r.unit else "")
                           for r in win) + f" ({top:.2f} m²{' each' if len(win) > 1 else ''})"
        return fin(ans, c, expl)

