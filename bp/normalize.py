"""Question normaliser: free wording -> one of the question templates our exact solvers parse.

The deterministic solvers parse the dataset's fixed templates. A judge typing "what's the floor space of the
kitchen, 3.11?" gets "question not understood". Only in that case (the routed solver could not parse the
question AND abstained) the router calls `normalize()`: one Claude Haiku call that sees

  * the source type and its supported templates (real English dataset questions from the dev split, with the
    names replaced by placeholders),
  * the names this drawing actually has (Swiss room numbers + labels and apartment letters from the parsed
    DXF; IFC storey and room names from the model), and
  * the user's question,

and either rewrites the question into exactly one template with the slots filled, or answers NONE. For Swiss
plans the list also maps everyday room words onto the plan's own labels (bp/swiss/rooms.py: "bathroom" -> 'Bad'),
so a semantic match is allowed and shown ("read as: How many rooms labelled 'Bad' ..."). A rewrite
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
TRIES = int(os.environ.get("BP_NORMALIZE_TRIES", "2"))  # calls before a NONE is final
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
        # comparisons (bp/compare.py): smallest / fewest / smaller work the same way
        "Which room is the largest on this floor?",
        "Which room in apartment <LETTER> is the largest?",
        "Which room labelled '<LABEL>' is the largest?",
        "Which apartment is the largest?",
        "Which apartment has the most rooms labelled '<LABEL>'?",
        "Is apartment <LETTER> larger than apartment <LETTER>?",
        "Is room <NUMBER> ('<LABEL>') larger than room <NUMBER> ('<LABEL>')?",
        "How much larger is room <NUMBER> ('<LABEL>') than room <NUMBER> ('<LABEL>'), in m²?",
        "How much larger is apartment <LETTER> than apartment <LETTER>, in m²?",
    ],
    "ifc": [
        "How many <ELEMENTS> are shown on the floor plan of '<STOREY>'?",
        "How many <ELEMENTS> are there in the model?",
        "What is the net floor area of the room '<ROOM>' on '<STOREY>', in m²?",
        "What is the total net floor area of all rooms (spaces) on '<STOREY>', in m²?",
        "What is the total net volume of all <walls|slabs> on '<STOREY>', in m³?",
        "What is the total length of all walls on '<STOREY>', in metres?",
        "What is the total net side area of all walls on '<STOREY>', in m²?",
        # comparisons (bp/compare.py): smallest / fewest / smaller work the same way
        "Which room on '<STOREY>' is the largest?",
        "Which room in the model is the largest?",
        "Which storey has the most <ELEMENTS>?",
        "Is the room '<ROOM>' on '<STOREY>' larger than the room '<ROOM>' on '<STOREY>'?",
        "How much larger is the room '<ROOM>' on '<STOREY>' than the room '<ROOM>' on '<STOREY>', in m²?",
        "Does '<STOREY>' have more <ELEMENTS> than '<STOREY>'?",
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
- A room word may be mapped semantically onto this drawing's own label: Swiss plans print room names in German,
  French or Italian, so "bathrooms" -> rooms labelled 'Bad', "kitchen" -> 'Küche'. Use the "Room words -> labels"
  list when it is given; map only to a label that is in it, and only when exactly one label fits (if a word maps
  to two labels on this drawing, reply NONE).
- The question may be typed casually, with typos, or in any language (English, German, French, Italian,
  Spanish, Swedish, Finnish, ...): read it for its meaning first. "sinks" alone, or "showers or bathtubs", map to
  the combined template that counts exactly those objects.
- Reply NONE if the question asks for something no template covers (another object type, prices, dates, ...),
  or if it is ambiguous between templates. Do not answer the question.
Examples (template lists and names vary by drawing; these only show the style):
- "how many sinks?" -> How many sinks and wash basins (kitchen and bathroom combined; a double-bowl sink counts as
  one) are drawn on this floor plan?
- "numbr of colums" (IFC) -> How many columns are there in the model?
- "¿Cuántas ventanas hay en E01?" (storey 'E01' listed) -> How many windows are shown on the floor plan of 'E01'?
- "how big is the kitchen?" (one room 'Küche (6)' on 'Erdgeschoss') -> What is the net floor area of the room
  'Küche (6)' on 'Erdgeschoss', in m²?
- "total floor area?" / "net area of the whole floor" (Swiss) -> What is the total net floor area in m² of all
  numbered indoor rooms on this floor (excluding balconies, loggias, terraces and other outdoor spaces, shafts and
  voids)?
- "Kumpi on isompi, olohuone vai keittiö?" (one 'Wohnen' room 5.06, one 'Küche' room 5.09) -> Is room 5.06
  ('Wohnen') larger than room 5.09 ('Küche')?
- "which flat is the biggest?" -> Which apartment is the largest?
- "who is the architect?" / "what does it cost?" / "energy rating?" -> NONE"""


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
    if route in ("swiss", "ifc") and q.get("source") != "ifc_bench":
        from bp.compare import parse as compare
        if compare(question) is not None:
            return True  # a comparison the solver read; it flags "unparsed" itself when an operand is unclear
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
        from bp.swiss.rooms import synonym_lines
        syn = synonym_lines(labels)
        lines = [f"Room labels: {', '.join(repr(x) for x in labels)}",
                 *(["Room words -> labels on this plan: " + "; ".join(syn)] if syn else []),
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
    if route == "swiss":  # every room number and apartment letter (comparison templates name two)
        for m in re.finditer(r"\broom ([A-Z]?\d+(?:\.\d+)*) \(", rewrite):
            if m.group(1) not in allowed["tokens"]:
                return f"room {m.group(1)} is not on this drawing"
        for m in re.finditer(r"\bapartment ([A-Z]{1,2}\d*)\b", rewrite):
            if m.group(1) not in allowed["tokens"]:
                return f"apartment {m.group(1)} is not on this drawing"
    if "<" in rewrite and ">" in rewrite:
        return "placeholder left unfilled"
    return None


def _unwrap(line: str) -> str:
    """Drop quotes the model put around the whole rewrite ('"How many sinks ...?"'), which read as a name slot."""
    m = re.fullmatch(r"[\"'“”‘’«»„](.+)[\"'“”‘’«»]", line.strip())
    return m.group(1).strip() if m and m.group(1).rstrip().endswith("?") else line


def normalize(route: str, q: dict) -> dict:
    """-> {"question": rewrite or None, "cost_usd", "why"}. One Haiku call per (question, drawing), cached."""
    if route not in TEMPLATES:
        return {"question": None, "cost_usd": 0.0, "why": "no templates for this drawing type"}
    # Swiss prompts carry the room-word map since v2; v4: any-language rule, examples, a second call on NONE;
    # v5: comparison templates. Earlier cached NONEs are not reused; earlier rewrites still are (v5 only adds
    # templates), so a warmed cache stays warm
    k = _key(q["question"] + "\x00v5", q.get("path", ""))
    hit = _cache_get(k)
    if hit is None:
        old = _cache_get(_key(q["question"] + "\x00v4", q.get("path", "")))
        hit = old if old is not None and old.get("rewrite") else None
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
    # Haiku through the CLI runs at a fixed temperature and declines a clear question now and then ("numbr of
    # colums" gave NONE on one call in three): a NONE or rejected rewrite gets one more call. Every rewrite still
    # has to pass _valid (names on this drawing only), so a second call cannot invent a room or storey.
    cost, raws = 0.0, []
    for _ in range(TRIES):
        res = ask(prompt, SYSTEM, "haiku", tag="normalize", timeout=120, retries=1)
        cost += float(res.get("cost_usd") or 0.0)
        if res.get("error"):
            return {"question": None, "cost_usd": cost, "why": f"normaliser call failed: {res['error'][:80]}"}
        text = (res.get("text") or "").strip().strip("`").strip()
        line = next((x.strip() for x in text.splitlines() if x.strip()), "")
        line = re.sub(r"^(?:rewritten question|answer)\s*:\s*", "", line, flags=re.I).strip()
        line = _unwrap(line)
        raws.append(line)
        if not line or re.fullmatch(r"NONE\.?", line, re.I):
            rewrite, why = None, "no supported question matches"
        else:
            bad = _valid(route, line, allowed)
            rewrite, why = (None, f"rewrite rejected: {bad}") if bad else (line, "")
        if rewrite:
            break
    line = " || ".join(raws)
    _cache_put({"k": k, "question": q["question"], "path": q.get("path", ""), "route": route, "raw": line,
                "rewrite": rewrite, "why": why, "cost_usd": cost})
    return {"question": rewrite, "cost_usd": cost, "why": why}


# ------------------------------------------------------------------ typed units and two-part counts
# Dataset questions on Swiss plans and IFC models are metric and never say feet (checked on all 127,043); a
# typed "in square feet" is stripped before parsing and the metric answer is converted afterwards.
_UNIT = re.compile(r"\s*,?\s*\b(?:(?:in|as|en|em|auf)\s+)?(?P<u>square\s+f(?:ee|oo)t|sq\.?\s*f(?:ee)?t|sqft|ft²|ft2"
                   r"|cubic\s+f(?:ee|oo)t|cu\.?\s*ft|feet|foot|ft)(?![\w²])\.?", re.I)
FT_FACTOR = {"area": (10.7639, "ft²"), "length": (3.28084, "ft"), "volume": (35.3147, "ft³")}
METRIC_ROUTES = {"swiss", "ifc"}


def unit_request(question: str) -> tuple[str, bool]:
    """-> (question without the imperial unit phrase, True if feet were asked for)."""
    m = _UNIT.search(question)
    if not m:
        return question, False
    q = (question[:m.start()] + question[m.end():]).strip()
    return (q if q.strip(" ?.,") else question), True


def to_feet(res: dict, qtype: str) -> dict:
    """Convert a metric numeric answer to the imperial unit of the same dimension (in place)."""
    from bp.score import to_number
    f = FT_FACTOR.get(qtype)
    v = to_number(res.get("answer")) if f else None
    if v is None:
        if res.get("answer") is not None and not f:  # feet asked on a count / text question: answer unchanged
            res["explanation"] = "(no unit conversion for this question) " + (res.get("explanation") or "")
        return res
    res["answer_metric"] = res["answer"]
    res["answer"] = round(v * f[0], 1)
    res["unit"] = f[1]
    res["explanation"] = (f"{res['answer']} {f[1]} (= {v:g} {'m²' if qtype == 'area' else 'm³' if qtype == 'volume' else 'm'}"
                          f" × {f[0]}) | " + (res.get("explanation") or ""))
    return res


# "how many doors and windows?" -> two questions. Only plain plural nouns of separately counted objects; the
# dataset's combined counts ("sinks and wash basins", "showers and bathtubs") are not in the list, so no dataset
# question splits (checked on all 127,043).
COUNTABLE = {"doors", "windows", "walls", "columns", "beams", "stairs", "staircases", "rooms", "spaces", "slabs",
             "toilets", "wcs", "bedrooms", "bathrooms", "kitchens", "balconies", "apartments", "flats", "saunas",
             "railings", "washbasins", "bathtubs", "showers", "sinks", "floors", "storeys"}
_COMBINED = {frozenset({"showers", "bathtubs"}), frozenset({"sinks", "washbasins"})}
_MULTI = re.compile(r"^\s*(?P<lead>how many|number of|count(?: the)?)\s+(?P<a>[a-z]+)\s*(?:,|and|&|\+)\s*"
                    r"(?:(?:how many|number of)\s+)?(?P<b>[a-z]+)\b(?P<rest>[^?]*)\??\s*$", re.I)


def split_multi(question: str) -> list[tuple[str, str]] | None:
    """-> [(noun, sub-question), (noun, sub-question)] for "how many X and Y ...", else None."""
    m = _MULTI.match(question)
    if not m:
        return None
    a, b = m.group("a").lower(), m.group("b").lower()
    if a == b or a not in COUNTABLE or b not in COUNTABLE or frozenset({a, b}) in _COMBINED:
        return None
    rest = m.group("rest").rstrip()
    return [(a, f"How many {a}{rest}?"), (b, f"How many {b}{rest}?")]
