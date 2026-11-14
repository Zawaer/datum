"""Everyday room words (en/de/fr/it) -> the room labels Swiss Dwellings plans actually print.

Swiss plans label rooms in German, French or Italian ('Bad', 'Bain', 'Bagno'); a judge types "bathrooms". The map
below is deterministic and closed: the labels are the full vocabulary found on all 1,040 Swiss floors of the
dataset (72 distinct labels; checked with bp.swiss.parse), grouped by what they mean. A label with a slash
('Küche/Essen', 'Wohnen/Essen') belongs to every kind one of its parts belongs to.

Used by bp/solvers/swiss.py (count / area of rooms of one kind) and shown to the normaliser (bp/normalize.py),
so a free wording can be mapped to the plan's own label ("read as: How many rooms labelled 'Bad' ...").
"""
from __future__ import annotations

import re
import unicodedata

# kind -> (labels that mean it, regex of the words a user types for it, English name)
KINDS = {
    "toilet_room": (("wc", "toilette", "toilettes", "gabinetto", "gäste-wc", "dusche/wc", "bad/wc"),
                    r"(?:toilet|wc|restroom|lavatory|loo)\s*-?\s*rooms?|restrooms?|lavator(?:y|ies)|separate\s+(?:wcs?|toilets?)|"
                    r"wc-?r(?:ä|a)ume?|toilettenr(?:ä|a)ume?|gäste-?wc", "toilet room (separate WC)"),
    "bathroom": (("bad", "bain", "bagno", "badezimmer", "salle de bain", "salle de bains", "dusche", "douche", "doccia",
                  "bad/wc", "dusche/wc", "nasszelle"),
                 r"bath\s*-?\s*rooms?|wash\s*-?\s*rooms?|shower\s*-?\s*rooms?|badezimmer\w*|b(?:ä|a)der\b|\bbad\b|"
                 r"salles?\s+de\s+bains?|salles?\s+d'eau|\bbains?\b|\bbagn[oi]\b", "bathroom"),
    "kitchen": (("küche", "cuisine", "cucina", "küche/essen", "kochen", "cuisine/repas", "cucina/pranzo"),
                r"kitchens?|kitchenettes?|k(?:ü|u)chen?\b|cuisines?|cucin[ae]\b", "kitchen"),
    "living": (("wohnen", "wohnen/essen", "wohnzimmer", "séjour", "séjour/repas", "salon", "soggiorno",
                "soggiorno/pranzo"),
               r"living\s*-?\s*rooms?|lounges?|sitting\s*-?\s*rooms?|family\s*-?\s*rooms?|wohnzimmer\w*|\bwohnen\b|"
               r"s(?:é|e)jours?\b|salons?\b|soggiorn[oi]\b", "living room"),
    "dining": (("essen", "repas", "pranzo", "wohnen/essen", "küche/essen", "séjour/repas", "soggiorno/pranzo",
                "cuisine/repas", "cucina/pranzo", "esszimmer"),
               r"dining\s*-?\s*(?:rooms?|areas?)|esszimmer\w*|\bessen\b|salles?\s+(?:à|a)\s+manger|\brepas\b|"
               r"sala\s+da\s+pranzo|\bpranzo\b", "dining room"),
    "bedroom": (("schlafzimmer", "chambre à coucher", "chambre", "camera da letto", "camera", "zimmer", "pièce",
                 "stanza"),
                r"bed\s*-?\s*rooms?|sleeping\s*-?\s*rooms?|schlafzimmer\w*|chambres?(?:\s+(?:à|a)\s+coucher)?|"
                r"camer[ae](?:\s+da\s+letto)?\b", "bedroom"),
    "corridor": (("korridor", "couloir", "corridoio", "flur", "gang", "diele", "halle", "hall", "eingangshalle",
                  "hall d'entrée", "entrée", "ingresso", "disimpegno"),
                 r"corridors?|hallways?|halls?\b|passages?|entrance\s*(?:halls?|ways?|areas?)?|entr(?:y|ies)\b|"
                 r"foyers?|korridore?\b|fl(?:u|ü)re?\b|dielen?\b|couloirs?|corridoi?o?\b|ingress[oi]\b", "corridor"),
    "balcony": (("balkon", "balcon", "balcone", "loggia"),
                r"balcon(?:y|ies)|balkone?\b|balcons?\b|balcon[ei]\b|loggi?as?\b|logge\b", "balcony"),
    "terrace": (("terrasse", "terrazza", "sitzplatz", "patio", "garten", "giardino"),
                r"terraces?|terrassen?\b|terrazz[ae]\b|patios?\b|sitzpl(?:a|ä)tze?\b|gardens?\b|g(?:a|ä)rten\b", "terrace"),
    "storage": (("reduit", "réduit", "ripostiglio", "abstellraum", "kellerabteil", "vano cantina", "compartiment cave",
                 "keller", "cave", "cantina", "estrich"),
                r"storage(?:\s*-?\s*rooms?)?|store\s*-?\s*rooms?|storerooms?|box\s*-?\s*rooms?|closets?|cellars?|"
                r"basement\s+compartments?|r(?:é|e)duits?\b|ripostigli?o?\b|abstellr(?:a|ä)um\w*|kellerabteil\w*|"
                r"\bcaves?\b|cantin[ae]\b", "storage room"),
    "stair": (("treppenhaus", "cage d'escalier", "vano scala", "treppe", "escalier", "scala"),
              r"stair\s*-?\s*wells?|stair\s*-?\s*cases?|stairs?\b|stairways?|treppenh(?:a|ä)us\w*|treppen?\b|"
              r"cages?\s+d'escaliers?|escaliers?|vani?\s+scala\b", "stairwell"),
    "lift": (("lift", "ascenseur", "ascensore", "aufzug"),
             r"lifts?\b|elevators?|aufz(?:u|ü)ge?\b|ascenseurs?|ascensori?e?\b", "lift (elevator)"),
    "laundry": (("waschen/trocknen", "waschküche", "lavanderia", "buanderie"),
                r"laundr(?:y|ies)|utility\s*-?\s*rooms?|waschk(?:ü|u)che\w*|buanderies?|lavanderi[ae]", "laundry"),
    "office": (("büro", "bürofläche", "grossraumbüro", "bureau", "ufficio"),
               r"offices?\b|studys?\b|studies\b|b(?:ü|u)ros?\b|bureaux?\b|uffic[io]\b", "office"),
}
# every room label printed on the dataset's Swiss floors (all 1,040; bp.swiss.parse), lower-cased
VOCAB = {
    "zimmer", "bad", "korridor", "küche", "balkon", "pièce", "bain", "couloir", "wohnen/essen", "schlafzimmer",
    "cuisine", "balcon", "reduit", "treppenhaus", "stanza", "wohnen", "lift", "séjour/repas", "bagno",
    "chambre à coucher", "corridoio", "loggia", "cucina", "réduit", "cage d'escalier", "balcone", "séjour",
    "soggiorno/pranzo", "raum", "camera da letto", "ripostiglio", "essen", "vano scala", "ascenseur", "soggiorno",
    "ascensore", "terrasse", "repas", "local", "büro", "halle", "waschen/trocknen", "vano cantina",
    "compartiment cave", "sitzplatz", "pranzo", "jardin d'hiver", "terrazza", "bürofläche", "wintergarten",
    "küche/essen", "lavanderia", "patio", "garten", "verkauf", "kellerabteil", "locale tecnico", "einstellhalle",
    "eingangshalle", "fahrbahn", "arkade", "hall d'entrée", "hall", "buanderie", "kinderwagen", "grossraumbüro",
    "locale", "giardino d'inverno", "surface de vente", "technik", "velo/kinderwagen",
}

# bare "rooms" / "Zimmer" / "pièces": the plans' generic room label ('Zimmer' is what a Swiss plan prints in a
# bedroom-or-study). Counted with the bedroom labels; the explanation also gives the number of all numbered spaces.
ROOM_LABELS = ("zimmer", "pièce", "stanza", "raum", "camera", "chambre", "schlafzimmer", "chambre à coucher",
               "camera da letto")
ROOM_RX = r"\brooms?\b|\bzimmer\b|\bpi(?:è|e)ces?\b|\bstanz[ae]\b|\br(?:ä|a)ume?\b"

# a count of 0 is an honest answer only for kinds every flat has a label for; for the others (a lift, an office,
# a laundry) "none labelled" may just mean "not labelled", so the solver abstains with the label list instead
ZERO_OK = {"bathroom", "kitchen", "bedroom", "room", "living", "corridor", "balcony"}


def norm(s) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "").strip().lower())


def label_parts(label: str) -> list[str]:
    n = norm(label)
    return [n] + [p.strip() for p in n.split("/") if p.strip() and "/" in n]


def display(label: str) -> str:
    """'gäste-wc' -> 'Gäste-WC', 'cage d'escalier' -> 'Cage d'escalier' (how the plans print them)."""
    return re.sub(r"\bwc\b", "WC", label[:1].upper() + label[1:], flags=re.I)


def labels_for(kind: str) -> tuple:
    return ROOM_LABELS if kind == "room" else KINDS[kind][0]


def matches(kind: str, label: str) -> bool:
    want = set(labels_for(kind))
    return any(p in want for p in label_parts(label))


def kind_name(kind: str) -> str:
    return "room" if kind == "room" else KINDS[kind][2]


def kind_match(text: str):
    """(kind, matched words) for the room kind a question asks about, or None. First mention wins; a bare "rooms"
    only counts if nothing more specific is named."""
    t = unicodedata.normalize("NFKC", text).lower()
    best = None
    for kind, (_, rx, _) in KINDS.items():
        m = re.search(rx, t)
        if m and (best is None or m.start() < best[1] or (m.start() == best[1] and m.end() > best[2])):
            best = (kind, m.start(), m.end(), m.group(0))
    if best:
        return best[0], best[3]
    m = re.search(ROOM_RX, t)
    return ("room", m.group(0)) if m else None


def kind_in(text: str) -> str | None:
    km = kind_match(text)
    return km[0] if km else None


def synonym_lines(labels) -> list[str]:
    """For the normaliser: which labels on this plan each everyday room word means."""
    out = []
    for kind in list(KINDS) + ["room"]:
        hit = sorted({lab for lab in labels if lab and matches(kind, lab)})
        if hit:
            out.append(f"{kind_name(kind)} -> " + ", ".join(f"'{h}'" for h in hit))
    return out
