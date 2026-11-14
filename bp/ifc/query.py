"""Multilingual question -> typed IFC query (regex keyword rules, no LLM).

A query is {kind, what, measure, slots, gross, here, here_floor}:
  kind:    count | sum (a measure summed over elements) | room_area
  what:    element-class key from CLASSES (wall, door, ...)
  measure: area_floor | area_side | volume | length | None
  here:    deictic scope ("this floor", "on this plan", "here"); here_floor: one that names a floor/plan/sheet
Quoted names (storeys, rooms, the model) stay in `slots`; they are resolved against the model later.
Keyword rules are matched on the question with the quoted names removed, so a room called 'Trappe'
cannot turn the question into a stair question.
"""
from __future__ import annotations

import re
import unicodedata

from bp.templates import _Q as _Q0

# bp.templates' quote set plus Polish/Romanian „...” (U+201E ... U+201D)
_Q = _Q0 + r"|„[^”“]*”"


def _slots(question: str) -> list[str]:
    return [m.strip("'\"«»„“”‘’ ") for m in re.findall(_Q, question)]

# key -> (IFC classes counted, subtype-inclusive; word-start regex alternatives in many languages)
CLASSES = {
    "space": (["IfcSpace"], r"rooms?|spaces?|rum(?:met|mene|mets)?|rom(?:met|mene)?|ruum\w*|r(?:a|ä)um\w*|zimmer\w*|"
              r"huone\w*|tilo\w*|tila\b|tilaa?\b|pi[eè]ces?|locaux|local\b|salles?|ruimte\w*|kamers?|habitaci\w*|espacios?|"
              r"stanz\w*|vano\b|vani\b|locales|pomieszcze\w*|m[ií]stnost\w*|helyis[eé]g\w*|telpa\w*|patalp\w*"),
    "door": (["IfcDoor"], r"doors?|d(?:ø|o|ö)r(?:e|en|ene|ar|arna|r)?\b|uks\w*|ust\b|uste\w*|t(?:ü|u)r\w*|ov(?:i|ea|ia|en|et)\b|"
             r"portes?\b|deur\w*|puertas?|porta\b|porte\b|drzwi|dve[rř]\w*|ajt\w*|durvis|durys"),
    "window": (["IfcWindow"], r"windows?|vindu\w*|f(?:ö|o)nst\w*|ak(?:en|na|ent|nad|naid|ende)\b|fenster\w*|ikkun\w*|"
               r"fen(?:ê|e)tres?|ramen\b|raam\b|ventanas?|finestr\w*|okn\w*|okien|ferestre\w*|ablak\w*|log\w*s\b|langai\w*"),
    "wall": (["IfcWall"], r"walls?|v(?:æ|a|ä)gg?(?:e|en|ene|ar|arna)?\b|sein(?:a|ad|u|ade|te|ä|iä|ien|ät)?\b|w(?:ä|a)nd\w*|"
             r"murs?\b|muros?\b|muren?\b|pere(?:ț|t|ţ)i\w*|perete\w*|muur\w*|pared\w*|par(?:e|ê)de?s?\b|muri?\b|[sś]cian\w*|st[eě]n\w*|fal(?:ak|at|ai)?\b|sien\w*"),
    "column": (["IfcColumn"], r"columns?|s(?:ø|o)jle\w*|post(?:i|id|e|ide)?\b|st(?:ü|u)tz\w*|s(?:ä|a)ul\w*|pilar\w*|"
               r"poteaux?|colonnes?|kolom\w*|columnas?|pelar\w*|kolumn\w*|sloup\w*|oszlop\w*|st(?:â|a)lp\w*"),
    "beam": (["IfcBeam"], r"beams?|bj(?:æ|a)lk\w*|tala\b|tal(?:ad|u|asid|ade)\b|tr(?:ä|a)ger\w*|balk\w*|palk\w*|poutres?|"
             r"vigas?\b|travi?\b|belk\w*|belek|grinzi\w*|grind(?:a|ă)\w*|nosn\w*|gerend\w*|sij\w*"),
    "stair": (["IfcStair"], r"stairs?|staircases?|trap(?:pe|per|perne|pa|por|porna|pen)?\b|trepp?\w*|treppe\w*|portai\w*|porras|"
              r"escaliers?|escaleras?|scal[ae]\b|schod\w*|l(?:é|e)pcs\w*|k(?:ā|a)pn\w*|laipt\w*|sc(?:ă|a)ri\w*|scar(?:a|ă)\w*"),
    "slab": (["IfcSlab"], r"slabs?|d(?:æ|a)k(?:ket|kene)?\b|plad(?:e|er|en|erne)\b|plaa?d\w*|vahelae\w*|decke\w*|deck\b|"
             r"bodenplatt\w*|platten?\b|laat\w*|dalles?|vloer(?!oppervlak)\w*|losas?|solai\w*|bjälklag\w*|stropy?\b|p(?:ł|l)yt\w*|f(?:ö|o)d(?:é|e)m\w*"),
    "railing": (["IfcRailing"], r"railings?|r(?:æ|a)kv(?:æ|a)rk\w*|piir\w*|gel(?:ä|a)nder\w*|kaide\w*|garde-corps|balustrad\w*|"
                r"leuning\w*|barandill\w*|r(?:ä|a)cke\w*"),
    "sanitary": (["IfcSanitaryTerminal"], r"sanitary|sanitaire?\w*|sanitarn\w*|sanit(?:æ|a|ä)r\w*|saniteet\w*|sanitaire\w*|sanitario\w*|wc\b|toilets?|"
                 r"toilet(?:ter|ten)?\b|tualet\w*|wc-?\w*"),
    "furniture": (["IfcFurnishingElement"], r"furniture|furnishings?|m(?:ø|ö|o)bel\w*|m(?:ö|o)bler\w*|mööbli\w*|huonekal\w*|"
                  r"meubles?|meubilair|muebles?|mobili|meble"),
    "covering": (["IfcCovering"], r"coverings?|bekl(?:æ|a)dning\w*|kat(?:e|ted)\b|bekleidung\w*|verkleidung\w*|p(?:ä|a)ällyst\w*|"
                 r"rev(?:ê|e)tements?"),
    "roof": (["IfcRoof"], r"roofs?|tag(?:et|e)?\b|katus\w*|d(?:ä|a)ch(?:er)?\b|katto\w*|katot\b|toits?\b|daken?\b|tejados?"),
    "curtain_wall": (["IfcCurtainWall"], r"curtain\s*walls?|facadeelement\w*|vorhangfassad\w*|klaasfassaad\w*|lasijulkisivu\w*|murs?\s+rideaux?"),
    "ramp": (["IfcRamp"], r"ramps?|rampe\w*|kaldtee\w*|luiska\w*"),
    "footing": (["IfcFooting"], r"footings?|foundations?|fundament\w*|vundament\w*|perustu\w*|anturi\w*|fondations?"),
    "plate": (["IfcPlate"], r"plates?\b"),
    "member": (["IfcMember"], r"members?\b"),
    "opening": (["IfcOpeningElement"], r"openings?|(?:å|a)bning\w*|ava\w*|(?:ö|o)ffnung\w*|aukko\w*"),
    "pipe": (["IfcPipeSegment"], r"pipes?|r(?:ø|ö|o)r\b|toru\w*|rohr\w*|putki\w*|putke\w*|tuyaux?"),
    "duct": (["IfcDuctSegment"], r"ducts?|kanal\w*|kanaal\w*|kanav\w*|gaines?"),
    "light": (["IfcLightFixture"], r"light\s*fixtures?|luminaires?|lamp(?:s|e|er|id|en)?\b|valaisi\w*|leuchte\w*|valgust\w*|iluminat\w*|verlichting\w*|leuchten\w*"),
    "proxy": (["IfcBuildingElementProxy"], r"proxy|proxies"),
    "building_storey": (["IfcBuildingStorey"], r"storeys?|stor(?:ies|y)|floors|levels?|etage\w*|korrus(?:t|te|eid)\b|"
                        r"geschoss\w*|kerro\w*|niveaux?|verdieping\w*|plantas\b|piani\b"),
}

# measure keywords
_SIDE = r"side\s*area|sideareal\w*|seitenfl(?:ä|a)che\w*|k(?:ü|u)lje\w*\s*pind\w*|k(?:ü|u)ljepind\w*|sivupinta\w*|" \
        r"surface\s+lat(?:é|e)rale|zijoppervlak\w*|wall\s*area|v(?:æ|a)gareal\w*|wandfl(?:ä|a)che\w*|seina\w*pind\w*"
# note: casefold turns German "groß" into "gross", so English "gross" must be followed by a measure word
_GROSS = r"\bgross (?:floor|side|area|volume|internal)|\bbrutto\w*|\bbruto\w*|\bbrut\b|kogupind\w*"
_TOTAL = r"total\w*|all\b|samlede?|alle\b|alles?\b|k(?:õ|o)ik\w*|k(?:õ|o)igi|kokku|gesamt\w*|insgesamt|summ\w*|yhteens(?:ä|a)|" \
         r"kaikk\w*|tous|toutes|totale?|totaal|todos?|todas?|tutti|tutte|zusammen"

# deictic scope: "this floor / this plan / on this level" (and the same in the dataset's other languages). On a plan
# sheet `<model>_plan-NN-<storey>.pdf` it means that sheet's storey; on the .ifc itself it names no storey.
HERE_FLOOR = (r"\bth(?:is|e\s+current)\s+(?:floor|level|storey|story|plan|sheet|drawing|page)\b|"
              r"\b(?:diese[mnrs]?|dieses)\s+(?:geschoss|stockwerk|etage|ebene|plan|grundriss|zeichnung|blatt)\w*|"
              r"\b(?:cet|ce|cette)\s+(?:étage|etage|niveau|plan|dessin|feuille)\b|"
              r"\b(?:questo|questa|quest')\s*(?:piano|livello|pianta|disegno|tavola)\b|"
              r"\bt(?:ä|a)(?:ss|ll)(?:ä|a)\s+(?:kerrokse\w*|tasol\w*|tasos\w*|pohjapiirustukse\w*|piirustukse\w*)|"
              r"\bselle(?:l|s)\s+(?:korruse\w*|plaani\w*|joonise\w*|tasandi\w*)|"
              r"\b(?:esta|este)\s+(?:planta|piso|nivel|plano)\b|"
              r"\b(?:deze|dit)\s+(?:verdieping|bouwlaag|niveau|plattegrond|tekening)\b|"
              r"\b(?:tym|tej)\s+(?:pi(?:ę|e)trze|kondygnacji|rzucie|poziomie)\b|"
              r"\b(?:acest|aceast(?:ă|a))\s+(?:etaj|nivel|plan)\w*|"
              r"\b(?:denne|dette|denna|detta)\s+(?:etage|etasje|plan|v(?:å|a)ning)\w*")
HERE_ANY = HERE_FLOOR + r"|\bhere\b|\bhier\b|\bici\b|\bsiin\b|\baqu(?:í|i)\b|\btutaj\b|\baici\b|\bh(?:ä|a)r\b"


def norm(s) -> str:
    s = unicodedata.normalize("NFKC", str(s or "")).casefold()
    return re.sub(r"\s+", " ", s).strip()


def strip_slots(question: str) -> str:
    return re.sub(_Q, " X ", question)


def _first_class(text: str):
    best = None
    for key, (_, rx) in CLASSES.items():
        m = re.search(rf"(?<!\w)(?:{rx})", text, flags=re.I)
        if m and (best is None or m.start() < best[1]):
            best = (key, m.start())
    return best[0] if best else None


def parse(q: dict) -> dict:
    question = q["question"]
    qtype = q.get("type")
    sl = _slots(question)
    text = norm(strip_slots(question))
    what = _first_class(text)
    side = bool(re.search(_SIDE, text, re.I))
    gross = bool(re.search(_GROSS, text, re.I))
    total = bool(re.search(_TOTAL, text, re.I))
    here_floor = bool(re.search(HERE_FLOOR, text, re.I))
    here = here_floor or bool(re.search(HERE_ANY, text, re.I))
    out = {"type": qtype, "what": what, "slots": sl, "gross": gross, "total": total, "text": text,
           "here": here, "here_floor": here_floor}
    if qtype == "count":
        out.update(kind="count", measure=None)
    elif qtype == "area":
        if what in (None, "space") or (not side and what not in ("wall", "slab", "curtain_wall", "covering", "window",
                                                                    "door", "roof")):
            out.update(kind="room_area", what="space", measure="area_floor")
        else:
            out.update(kind="sum", measure="area_side" if what in ("wall", "curtain_wall") or side else "area")
    elif qtype == "volume":
        out.update(kind="sum", measure="volume", what=what or "slab")
    elif qtype == "length":
        out.update(kind="sum", measure="length", what=what or "wall")
    else:
        out.update(kind="text", measure=None)
    return out
