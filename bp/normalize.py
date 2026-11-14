"""Question normaliser: free wording -> one of the question templates our exact solvers parse.

The deterministic solvers parse the dataset's fixed templates. A judge typing "what's the floor space of the
kitchen, 3.11?" gets "question not understood". Only in that case (the routed solver could not parse the
question AND abstained) the router calls `normalize()`: one Claude Haiku call that sees

  * the source type and its supported templates (real English dataset questions from the dev split, with the
    names replaced by placeholders),
  * the names this drawing actually has (Swiss room numbers + labels and apartment letters from the parsed
    DXF; IFC storey and room names from the model), and
  * the user's question,

and either rewrites the question into exactly one template with the slots filled, or answers NONE. A rewrite
that quotes a name not in the list is rejected (the model may not invent rooms or storeys). The router then
re-runs the same solver on the rewrite and shows it ("read as: ...").

Dataset questions all parse, so they never reach this code and stay $0. Cached per (question, drawing) in
cache/normalize.jsonl. Disable with BP_NORMALIZE=0.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path

CACHE = Path(os.environ.get("BP_CACHE", "cache")) / "normalize.jsonl"
_lock = threading.Lock()
_mem: dict | None = None

# Supported templates per solver, copied from the English dev-split questions (names -> <PLACEHOLDERS>).
TEMPLATES = {
    "cubicasa": [
        "How many windows are shown on this floor plan?",
        "How many floors (storeys) does this floor plan show?",
        "How many toilet bowls (WC seats) are drawn on this floor plan?",
        "How many sinks and wash basins (kitchen and bathroom combined; a double-bowl sink counts as one) are "
        "drawn on this floor plan?",
        "How many showers and bathtubs are drawn on this floor plan in total?",
        "How many doors are shown on this floor plan? Count doorways fitted with a door; open doorways without a "
        "door leaf do not count.",
        "How many saunas are on this floor plan?",
        "How many kitchens (including kitchenettes, open kitchens and utility kitchens) are on this floor plan?",
        "How many bedrooms (makuuhuone, usually marked MH) are on this floor plan?",
        "How many bathrooms or washrooms (e.g. KH, KPH, PH, PESUH, SH) are on this floor plan, not counting "
        "separate WC rooms?",
        "How many separate WC rooms (toilet rooms marked WC) are on this floor plan?",
        "How many balconies (parveke, including glazed balconies) are on this floor plan?",
    ],
    "swiss": [
        "How many rooms labelled '<LABEL>' are there on this floor?",
        "What is the net floor area of room <NUMBER> ('<LABEL>') in m²?",
        "What is the net floor area of apartment <LETTER> in m², summing all its rooms except balconies, loggias, "
        "terraces and other outdoor spaces?",
        "What is the total net area in m² of all rooms labelled '<LABEL>' on this floor?",
        "What is the total net floor area in m² of all numbered indoor rooms on this floor (excluding balconies, "
        "loggias, terraces and other outdoor spaces, shafts and voids)?",
        "How many apartments (residential units) are shown on this floor plan?",
        "How many doors (interior doors and entrance doors together) are drawn on this floor plan?",
        "How many windows are drawn on this floor plan?",
        "How many toilets (WC) are drawn on this floor plan?",
        "How many washbasins are drawn on this floor plan?",
        "How many bathtubs are drawn on this floor plan?",
        "How many showers are drawn on this floor plan?",
    ],
    "ifc": [
        "How many <ELEMENTS> are shown on the floor plan of '<STOREY>'?",
        "How many <ELEMENTS> are there in the model?",
        "What is the net floor area of the room '<ROOM>' on '<STOREY>', in m²?",
        "What is the total net floor area of all rooms (spaces) on '<STOREY>', in m²?",
        "What is the total net volume of all <walls|slabs> on '<STOREY>', in m³?",
        "What is the total length of all walls on '<STOREY>', in metres?",
        "What is the total net side area of all walls on '<STOREY>', in m²?",
    ],
}
IFC_ELEMENTS = ("rooms (spaces), doors, windows, walls, columns, beams, stairs, slabs, railings, roofs, "
                "curtain walls, ramps, footings, sanitary fixtures, light fixtures, furniture, coverings, "
                "openings, pipes, ducts")

SYSTEM = """You map a user's question about a building drawing onto exactly one supported question template.
Rules:
- Reply with ONE line: the template with every <PLACEHOLDER> filled, or the single word NONE.
- Keep the template's wording otherwise unchanged (it is parsed by a program).
- Fill names ONLY with names from the list of names on this drawing, copied exactly (same spelling and accents).
  Never invent a name, number or letter that is not in the list. If the question names something that is not
  in the list (a room, storey or apartment this drawing does not have), reply NONE.
- A storey or room described in words may be mapped to a listed name only when the match is unambiguous
  (e.g. "ground floor" -> 'Erdgeschoss' or 'Level 0' when that is the only ground-level storey; "the kitchen"
  -> room 2.07 when exactly one room has a kitchen label). If several listed names fit, reply NONE.
- Everyday words may be mapped to a listed name when exactly one name clearly fits: "kitchen" -> the one room
  labelled 'Küche', "ground floor" -> 'Erdgeschoss' or 'Level 0'. If several rooms carry the asked label and the
  question means one of them, reply NONE (ambiguous); if it means all of them, use a "total ... labelled" template.
- Reply NONE if the question asks for something no template covers (another object type, prices, dates, ...),
  or if it is ambiguous between templates. Do not answer the question."""


def _key(question: str, path: str) -> str:
    return hashlib.sha1(f"{question}\x00{path}".encode()).hexdigest()


def _cache_get(k):
    global _mem
    with _lock:
        if _mem is None:
            _mem = {}
            if CACHE.exists():
                for line in CACHE.read_text().splitlines():
                    try:
                        r = json.loads(line)
                        _mem[r["k"]] = r
                    except (json.JSONDecodeError, KeyError):
                        pass
        return _mem.get(k)


def _cache_put(rec):
    with _lock:
        _mem[rec["k"]] = rec
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------ "could the solver parse it?"
def understood(route: str, q: dict) -> bool:
    """False when the routed solver's question parser finds no intent (the only case we normalise)."""
    question, qtype = q["question"], q.get("type")
    if route == "swiss":
        from bp.solvers.swiss import parse_question
        it = parse_question(question, qtype)
        # a label question whose label is not quoted ("rooms marked Cage d'escalier") parses without its slot
        return it is not None and not (it[0] in ("count_label", "area_label") and not it[1])
    if route == "cubicasa":
        from bp.cubicasa.questions import target
        return target(question) is not None
    if route == "ifc":
        if q.get("source") == "ifc_bench":
            return True
        if qtype in ("text", "other"):
            return False  # numeric-only templates; the text path is a different solver
        from bp.ifc.query import parse
        pq = parse(q)
        return pq["kind"] == "room_area" or pq["what"] is not None
    return True  # generic / ifctext take free text already


# ------------------------------------------------------------------ names on the drawing
def drawing_names(route: str, q: dict) -> dict:
    """{"lines": [prompt lines], "names": set of allowed quoted names, "tokens": allowed numbers/letters}"""
    if route == "swiss":
        from bp.solvers.swiss import SwissSolver
        fl = SwissSolver().floor_for(q)
        if fl is None:
            return {"lines": [], "names": set(), "tokens": set()}
        rooms = [(r.number, r.name) for r in fl.rooms if r.number]
        labels = sorted({n for _, n in rooms if n})
        letters = sorted(fl.units)
        lines = [f"Room labels: {', '.join(repr(x) for x in labels)}",
                 "Rooms (number 'label'): " + "; ".join(f"{n} '{lab or ''}'" for n, lab in rooms),
                 f"Apartment letters: {', '.join(letters) or '(none)'}"]
        return {"lines": lines, "names": set(labels), "tokens": {n for n, _ in rooms} | set(letters)}
    if route == "ifc":
        from bp.ifc import model as M
        from bp.ifc.extract import load_model
        from bp.solvers.ifc import ifc_path_for
        _, ifc = ifc_path_for(q["path"])
        if not ifc.exists():
            return {"lines": [], "names": set(), "tokens": set()}
        m = load_model(ifc)
        storeys = [s["name"] for s in m["storeys"] if s["name"]]
        names, lines = set(storeys), [f"Storeys: {', '.join(repr(s) for s in storeys)}"]
        by = M.storey_by_guid(m)
        rooms = []
        for e in m["elements"]:
            if e["cls"] == "IfcSpace":
                lab = (M.space_labels(e) or [None])[0]
                st = by.get(e.get("storey"))
                if lab:
                    rooms.append((lab, st["name"] if st else ""))
        if len(rooms) <= 300:
            lines.append("Rooms ('room' on 'storey'): " + "; ".join(f"'{r}' on '{s}'" for r, s in rooms))
            names |= {r for r, _ in rooms}
        return {"lines": lines, "names": names, "tokens": set()}
    return {"lines": [], "names": set(), "tokens": set()}


def _valid(route, rewrite, allowed) -> str | None:
    """Reason to reject a rewrite, or None if it only uses names from the drawing."""
    from bp.templates import slots
    for s in slots(rewrite):
        if s not in allowed["names"]:
            return f"name '{s}' is not on this drawing"
    if route == "swiss":
        m = re.search(r"\broom ([A-Z]?\d+(?:\.\d+)*) \(", rewrite)
        if m and m.group(1) not in allowed["tokens"]:
            return f"room {m.group(1)} is not on this drawing"
        m = re.search(r"\bapartment ([A-Z]{1,2}\d*)\b", rewrite)
        if m and m.group(1) not in allowed["tokens"]:
            return f"apartment {m.group(1)} is not on this drawing"
    if "<" in rewrite and ">" in rewrite:
        return "placeholder left unfilled"
    return None


def normalize(route: str, q: dict) -> dict:
    """-> {"question": rewrite or None, "cost_usd", "why"}. One Haiku call per (question, drawing), cached."""
    if route not in TEMPLATES:
        return {"question": None, "cost_usd": 0.0, "why": "no templates for this drawing type"}
    k = _key(q["question"], q.get("path", ""))
    hit = _cache_get(k)
    if hit is not None:
        return {"question": hit["rewrite"], "cost_usd": 0.0, "why": hit.get("why", ""), "cached": True}
    try:
        allowed = drawing_names(route, q)
    except Exception as e:  # noqa: BLE001  names are a help, not a requirement
        allowed = {"lines": [], "names": set(), "tokens": set(), "err": repr(e)[:100]}
    tpl = "\n".join(f"- {t}" for t in TEMPLATES[route])
    extra = f"\n<ELEMENTS> is one of: {IFC_ELEMENTS}." if route == "ifc" else ""
    kind = {"cubicasa": "a raster floor plan of a Finnish home (no names on it)",
            "swiss": "a Swiss apartment floor plan (one floor)",
            "ifc": "an IFC building model (BIM) or a floor plan rendered from it"}[route]
    names = "\n".join(allowed["lines"]) or "(no names)"
    prompt = (f"Drawing: {kind}\n\nSupported templates:\n{tpl}{extra}\n\nNames on this drawing:\n{names}\n\n"
              f"User question: {q['question']}\n\nRewritten question (or NONE):")
    from bp.ifctext.llm import ask
    res = ask(prompt, SYSTEM, "haiku", tag="normalize", timeout=120, retries=1)
    cost = float(res.get("cost_usd") or 0.0)
    if res.get("error"):
        return {"question": None, "cost_usd": cost, "why": f"normaliser call failed: {res['error'][:80]}"}
    text = (res.get("text") or "").strip().strip("`").strip()
    line = next((x.strip() for x in text.splitlines() if x.strip()), "")
    line = re.sub(r"^(?:rewritten question|answer)\s*:\s*", "", line, flags=re.I).strip()
    if not line or re.fullmatch(r"NONE\.?", line, re.I):
        rewrite, why = None, "no supported question matches"
    else:
        bad = _valid(route, line, allowed)
        rewrite, why = (None, f"rewrite rejected: {bad}") if bad else (line, "")
    _cache_put({"k": k, "question": q["question"], "path": q.get("path", ""), "route": route, "raw": line,
                "rewrite": rewrite, "why": why, "cost_usd": cost})
    return {"question": rewrite, "cost_usd": cost, "why": why}
