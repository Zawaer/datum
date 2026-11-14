"""Comparative and superlative questions: "Which room is the largest?", "Is apartment B bigger than apartment A?",
"Which apartment has the most bedrooms?", "How much bigger is the living room than the kitchen?".

This module only reads the *shape* of the question (deterministic patterns, en/de/fr/it/fi/nl/sv/es); the exact
solvers (bp/solvers/swiss.py, bp/solvers/ifc.py) resolve the operands on their drawing and compute the answer from
the same geometry their area / count answers use.

parse(question) -> None, or
  {"op": "max" | "min"           superlative: which X is the largest / has the most N
         "cmp"                   yes/no: is X bigger than Y / does X have more N than Y
         "diff"                  how much bigger is X than Y / how many more N does X have than Y
         "which2",               which is bigger, X or Y
   "dir": +1 (bigger / more) or -1 (smaller / fewer),
   "measure": "area" | "count",
   "counted": text naming what is counted (count measure), else "",
   "subject": the question without the comparison words (superlatives),
   "left", "right": the two operands' text (comparatives)}

No dataset question (Swiss Dwellings, IFC models; all splits, all languages) parses: checked with
`python -m bp.compare check`, so dataset answers cannot change.
"""
from __future__ import annotations

import re
import unicodedata

# comparative adjectives (need a "than" word after them)
_BIG = (r"bigger|larger|greater|roomier|more\s+spacious|gr(?:ö|o|oe)(?:ß|ss)er(?:e[nmrs]?)?|suurempi|isompi|"
        r"groter|st(?:ö|o)rre|plus\s+(?:grand(?:e|s|es)?|spacieu(?:x|se|ses))|pi(?:ù|u)\s+(?:grand[ei]|spazios[oaie])|"
        r"m(?:á|a)s\s+grandes?|mayor(?:es)?")
_SMALL = (r"smaller|tinier|kleiner(?:e[nmrs]?)?|pienempi|mindre|plus\s+petit(?:e|s|es)?|pi(?:ù|u)\s+piccol[oaie]|"
          r"m(?:á|a)s\s+peque(?:ñ|n)[oa]s?|menor(?:es)?")
# superlatives (no "than" after them)
_BIGGEST = (r"largest|biggest|greatest|roomiest|most\s+spacious|gr(?:ö|o|oe)(?:ß|ss)te[nmrs]?|"
            r"plus\s+(?:grand(?:e|s|es)?|spacieu(?:x|se|ses))|pi(?:ù|u)\s+(?:grand[ei]|spazios[oaie])|suurin|suurimm?\w*|"
            r"isoin|isoimm?\w*|grootste?|st(?:ö|o)rsta?|m(?:á|a)s\s+grandes?|mayor(?:es)?")
_SMALLEST = (r"smallest|tiniest|kleinste[nmrs]?|plus\s+petit(?:e|s|es)?|pi(?:ù|u)\s+piccol[oaie]|pienin|pienimm?\w*|"
             r"minsta|minst|m(?:á|a)s\s+peque(?:ñ|n)[oa]s?|menor(?:es)?")
# "more / most N" and "fewer / fewest N" (a count of N)
_MORE = r"more|mehr|plus\s+d[e']|pi(?:ù|u)|enemm(?:ä|a)n|meer|fler|m(?:á|a)s"
_FEWER = r"fewer|less|weniger|moins\s+d[e']|meno|v(?:ä|a)hemm(?:ä|a)n|minder|f(?:ä|a)rre|menos"
_MOST = r"most|(?:die|am)\s+meisten|le\s+plus\s+d[e']|pi(?:ù|u)|eniten|meeste|flest|m(?:á|a)s"
_FEWEST = r"fewest|least|(?:die|am)\s+wenigsten|le\s+moins\s+d[e']|meno|v(?:ä|a)hiten|minste|f(?:ä|a)rst|menos"
_THAN = r"than|als|que|qu'|di|del|dell[aoe']|dei|degli|kuin|dan|än"
_HOW_MUCH = (r"how\s+much|by\s+how\s+much|how\s+many|(?:um\s+)?wie\s*viele?|de\s+combien|combien|di\s+quanto|quant[oie]|kuinka\s+(?:paljon|monta)|paljonko|"
             r"montako|hoeveel|hur\s+m(?:ycket|ånga)|cu(?:á|a)nt[oa]s?")
_OR = r"or|oder|ou|o|vai|tai|of|eller"
_WHICH = r"which|what|welche[rsmn]?|was|quel(?:le)?s?|lequel|laquelle|qual[ei]?|kumpi|kumman|mik(?:ä|a)|welke?|vilke[nt]|cu(?:á|a)l(?:es)?"
_DIFF = r"difference\s+(?:in\s+(?:area|size)\s+)?between|unterschied\s+zwischen|diff(?:é|e)rence\s+entre|differenza\s+tra|ero\b"


def _norm(q: str) -> str:
    return unicodedata.normalize("NFKC", q).lower()


def _w(rx: str) -> str:
    """Whole words only (a trailing apostrophe, as in "plus d'", may be glued to the next word)."""
    return rf"(?<![\w'])(?:{rx})(?:(?<=')|(?!\w))"


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" ?¿!.,;:")


def parse(question: str) -> dict | None:
    t = _norm(question)
    # yes/no or how-much comparatives: an adjective (or more/fewer) followed later by a "than" word
    m = re.search(rf"(?P<adj>{_w(_BIG)}|{_w(_SMALL)})", t)
    mc = re.search(rf"(?P<adj>{_w(_MORE)}|{_w(_FEWER)})\s+(?P<n>[\w\-' ]+?)\s+{_w(_THAN)}", t)
    for kind, mm in (("area", m), ("count", mc)):
        if not mm:
            continue
        rest = t[mm.end():] if kind == "area" else t[mm.end("n"):]
        th = re.search(_w(_THAN), rest)
        big = bool(re.fullmatch(_BIG if kind == "area" else _MORE, mm.group("adj")))
        before = t[:mm.start()]
        if th:
            # count: "does apartment A have more bedrooms than B" / "how many more bedrooms does A have than B"
            left = before + " " + rest[:th.start()] if kind == "area" else t[:mm.end("n")]
            how = re.search(_w(_HOW_MUCH), before)
            return {"op": "diff" if how else "cmp", "dir": 1 if big else -1, "measure": kind,
                    "counted": _clean(mm.group("n")) if kind == "count" else "",
                    "left": _clean(left), "right": _clean(rest[th.end():]), "subject": ""}
        # "which is bigger, the kitchen or the bathroom?" / "what is larger: X or Y"
        if kind == "area" and re.search(_w(_WHICH), before) and re.search(_w(_OR), rest):
            parts = re.split(_w(_OR), re.sub(r"^\s*[,:]\s*", "", rest), maxsplit=1)
            if len(parts) == 2 and parts[0].strip(" ,:") and parts[1].strip(" ?"):
                return {"op": "which2", "dir": 1 if big else -1, "measure": "area", "counted": "",
                        "left": _clean(parts[0]), "right": _clean(parts[1]), "subject": ""}
    # difference between X and Y
    md = re.search(rf"{_w(_DIFF)}(?P<a>.+?)\s+(?:and|und|et|e|ja|en|och|y)\s+(?P<b>.+)$", t)
    if md:
        return {"op": "diff", "dir": 0, "measure": "area", "counted": "", "left": _clean(md.group("a")),
                "right": _clean(md.group("b")), "subject": ""}
    # superlatives
    for rx, op in ((_BIGGEST, "max"), (_SMALLEST, "min")):
        m = re.search(_w(rx), t)
        if m:
            return {"op": op, "dir": 1 if op == "max" else -1, "measure": "area", "counted": "",
                    "subject": _clean(t[:m.start()] + " " + t[m.end():]), "left": "", "right": ""}
    for rx, op in ((_FEWEST, "min"), (_MOST, "max")):
        m = re.search(rf"{_w(rx)}\s+(?P<n>[\w\-' ]+)", t)
        if m and re.search(_w(_WHICH) + "|" + _w(r"wo|où|dove|missä|waar|var|dónde|donde"), t[:m.start()]):
            return {"op": op, "dir": 1 if op == "max" else -1, "measure": "count", "counted": _clean(m.group("n")),
                    "subject": _clean(t[:m.start()]), "left": "", "right": ""}
    return None


# ------------------------------------------------------------------ words shared by both solvers
APT = r"apartments?|flats?|units?|wohnung(?:en)?|appartements?|appartament[oi]|logements?|asun(?:to|no)\w*|huoneisto\w*|" \
      r"l(?:ä|a)genhet\w*|apartamentos?|pisos?|viviendas?"
STOREY = r"storeys?|stor(?:y|ies)|floors?|levels?|geschoss\w*|stockwerk\w*|etage\w*|(?:é|e)tages?|niveaux?|piani|piano|" \
         r"kerro\w*|verdieping\w*|v(?:å|a)ning\w*|plantas?|pisos?"
# room words beyond bp/swiss/rooms.py's en/de/fr/it (fi, nl, sv, es), for operands and kind filters only
EXTRA_KINDS = {
    "kitchen": r"keitti(?:ö|o)\w*|keuken\w*|k(?:ö|o)k(?:et)?\b|cocinas?",
    "living": r"olohuone\w*|woonkamer\w*|vardagsrum\w*|sal(?:ó|o)n\b|sala\s+de\s+estar",
    "bedroom": r"makuuhuone\w*|slaapkamer\w*|sovrum\w*|dormitorios?",
    "bathroom": r"kylpyhuone\w*|badkamer\w*|badrum\w*|ba(?:ñ|n)os?\b",
    "balcony": r"parvek\w*|balk(?:ó|o)n\w*",
    "corridor": r"eteinen|eteis\w*|k(?:ä|a)yt(?:ä|a)v\w*|gang\b|hal\b|hall(?:en)?\b|pasillos?",
    "toilet_room": r"\bwc\b|vessa\w*|toilet\b|toalett\w*|aseos?",
}
ROOM_WORD = r"rooms?|spaces?|zimmer|r(?:ä|a)ume?|pi(?:è|e)ces?|stanz[ae]|locali?|huone\w*|tila\w*|kamers?|ruimtes?|" \
            r"rum(?:met)?|habitaci(?:ó|o)n(?:es)?|cuartos?|espacios?|vani?"


def kind_of(text: str):
    """(kind, word) of an everyday room word in `text` (bp/swiss/rooms.py kinds + the extra languages), or None."""
    from bp.swiss.rooms import kind_match
    t = unicodedata.normalize("NFKC", text).lower()
    best = None
    km = kind_match(t)
    if km and km[0] != "room":
        best = (km[0], km[1], t.find(km[1]))
    for kind, rx in EXTRA_KINDS.items():
        m = re.search(rf"(?<!\w)(?:{rx})", t)
        if m and (best is None or m.start() < best[2]):
            best = (kind, m.group(0), m.start())
    if best:
        return best[0], best[1]
    return km  # ("room", word) or None


def fmt(v: float, unit: str) -> str:
    """'18.96 m²', '1 window', '3 bedrooms' (count units are given in the plural)."""
    if unit == "m²":
        return f"{v:.2f} m²"
    n = int(round(v))
    return f"{n} {unit[:-1] if n == 1 and unit.endswith('s') else unit}"


def typed(v, unit: str, qtype: str | None):
    """A difference as a number when the question's type already carries its unit (area -> m², count), else as text
    with the unit ("8.90 m²"): the app shows a number's unit from the question type, and "how much bigger is the
    living room than the kitchen?" is typed as text."""
    if (unit == "m²" and qtype == "area") or (unit != "m²" and qtype == "count"):
        return v
    return f"{v:.2f} m²" if unit == "m²" else fmt(v, unit)


def verdict_text(a_name, a_val, b_name, b_val, unit):
    """-> ('apartment B 81.55 m² vs apartment A 62.59 m²: apartment B is larger by 18.96 m²', a - b)."""
    d = round(a_val - b_val, 2)
    if abs(d) < 1e-9:
        rel = "they are equal"
    else:
        hi = a_name if d > 0 else b_name
        rel = f"{hi} is larger by {fmt(abs(d), unit)}" if unit == "m²" else f"{hi} has {fmt(abs(d), unit)} more"
    if unit == "m²":
        return f"{a_name} {fmt(a_val, unit)} vs {b_name} {fmt(b_val, unit)}: {rel}", d
    return f"{a_name} has {fmt(a_val, unit)}, {b_name} {fmt(b_val, unit)}: {rel}", d


if __name__ == "__main__":  # python -m bp.compare check: no dataset question may parse as a comparison
    import sys

    from bp.data import load_questions

    if sys.argv[1:2] == ["check"]:
        qs = [q for q in load_questions() if q["source"] in ("swiss_dwellings", "ifc_models")]
        hits = [q for q in qs if parse(q["question"]) is not None]
        print(f"{len(qs)} Swiss + IFC-model questions, {len(hits)} parse as comparisons")
        for q in hits[:20]:
            print(" ", q["source"], repr(q["question"][:150]), parse(q["question"]))
    else:
        for a in sys.argv[1:]:
            print(a, "->", parse(a))
