"""What the demo says out loud: one short sentence per answer, in the question's language.

The sentence is built here, on the server, from the answer the server itself returned (see /api/speak in
app/server.py): the browser only sends an answer id, so the endpoint cannot be used to read arbitrary text.
Numbers stay digits ("20", "15,47"): ElevenLabs reads them out in the language we pass as language_code.
"""
from __future__ import annotations

import re

LANGS = ("en", "fi", "de", "fr", "it", "nl", "sv")

# ISO-639-3 codes (ElevenLabs Scribe answers with these) and a few names -> the two-letter codes above
_ISO3 = {"eng": "en", "fin": "fi", "deu": "de", "ger": "de", "fra": "fr", "fre": "fr", "ita": "it", "nld": "nl",
         "dut": "nl", "swe": "sv"}

# words that mark a language in a short drawing question (scored by count; ties and no hits -> English)
_MARKERS = {
    "fi": r"kuinka|montako|monta|paljonko|mikä|mitkä|onko|ovat|ovea|ikkunaa|huonetta|pinta-ala|pituus|kerros\w*|"
          r"tässä|piirustuksessa|pohjapiirroksessa|asunto\w*|neliö\w*|yhteensä|on",
    "de": r"wie|viele|viel|welche|gibt|es|die|der|das|im|auf|ist|sind|türen|fenster|räume|fläche|grundriss|"
          r"zeichnung|wohnungen|insgesamt|des",
    "fr": r"combien|quelle|quel|est|de|des|la|le|les|sur|ce|cette|plan|portes|fenêtres|pièces|surface|"
          r"logements|y|a-t-il|il",
    "it": r"quante|quanti|quale|qual|è|sono|ci|di|del|della|nel|nella|porte|finestre|stanze|superficie|pianta|"
          r"appartamenti|il|lo",
    "nl": r"hoeveel|welke|wat|is|zijn|er|het|de|op|deze|tekening|plattegrond|deuren|ramen|kamers|oppervlakte|"
          r"woningen|totaal|van",
    "sv": r"hur|många|mycket|vilken|vilka|är|finns|det|på|den|här|ritningen|planen|dörrar|fönster|rum|area|"
          r"lägenheter|totalt|av",
}
_MARK_RE = {k: re.compile(rf"(?<![\w-])(?:{v})(?![\w-])", re.I) for k, v in _MARKERS.items()}
_EN = re.compile(r"(?<![\w-])(?:how|many|much|what|which|is|are|there|the|this|of|in|on|plan|drawing|floor|doors|"
                 r"windows|rooms|area|total|model)(?![\w-])", re.I)


def norm_lang(code: str | None) -> str | None:
    c = (code or "").strip().lower().replace("_", "-").split("-")[0]
    c = _ISO3.get(c, c)
    return c if c in LANGS else None


def detect_lang(question: str) -> str:
    """Best guess at the language of a short drawing question; English unless another one clearly wins."""
    q = question or ""
    scores = {k: len(r.findall(q)) for k, r in _MARK_RE.items()}
    if re.search(r"[äö]", q) and not re.search(r"ü|ß", q):  # ä/ö without ü/ß: Finnish or Swedish
        scores["fi"] += 1
        scores["sv"] += 1
    if re.search(r"å", q, re.I):
        scores["sv"] += 2
    if re.search(r"[üß]", q):
        scores["de"] += 2
    if re.search(r"[éèêàç]", q):
        scores["fr"] += 1
    scores["en"] = len(_EN.findall(q))
    best = max(scores, key=lambda k: (scores[k], k == "en"))
    return best if scores[best] > 0 else "en"


# per language: units, trust lines, abstention, and the noun after "how many" in the question
T = {
    "en": dict(over="more than", dec=".", area="square metres", length="metres", volume="cubic metres",
               geo="Verified by geometry", bim="Looked up in the BIM model", vis="Detected by vision",
               llm="Answered by an AI model",
               track="right {p} percent of the time on similar drawings", check="check the marks on the drawing",
               conflict="Two independent methods disagree, so check the evidence.",
               abstain="Not sure, so no guess.", none="That is not in the file, so no guess.",
               noun=r"\bhow\s+many\s+([a-z][\w-]*)",
               skip={"of", "are", "is", "there", "the", "times", "more", "do", "does", "different", "separate"}),
    "fi": dict(over="yli", dec=",", area="neliömetriä", length="metriä", volume="kuutiometriä",
               geo="Varmistettu geometriasta", bim="Haettu BIM-mallista", vis="Tunnistettu konenäöllä",
               llm="Tekoälymallin vastaus",
               track="vastaavissa piirustuksissa oikein {p} prosentissa tapauksista",
               check="tarkista merkinnät piirustuksesta",
               conflict="Kaksi erillistä menetelmää on eri mieltä, joten tarkista todisteet.",
               abstain="En ole varma, joten en arvaa.", none="Sitä ei ole tiedostossa, joten en arvaa.",
               noun=r"\b(?:kuinka|montako|monta)\s+(?:monta\s+)?([a-zåäö][\w-]*)", skip={"on", "kpl", "monta"}),
    "de": dict(over="über", dec=",", area="Quadratmeter", length="Meter", volume="Kubikmeter",
               geo="Durch Geometrie geprüft", bim="Im BIM-Modell nachgeschlagen", vis="Per Bilderkennung erkannt",
               llm="Von einem KI-Modell beantwortet",
               track="bei ähnlichen Zeichnungen in {p} Prozent der Fälle richtig",
               check="bitte die Markierungen prüfen",
               conflict="Zwei unabhängige Methoden sind sich uneinig, bitte die Belege prüfen.",
               abstain="Nicht sicher, daher keine Schätzung.", none="Das steht nicht in der Datei, daher keine Schätzung.",
               noun=r"\bwie\s+viele\s+([a-zäöüß][\w-]*)", skip={"gibt", "sind", "es", "der", "die", "das"}),
    "fr": dict(over="plus de", dec=",", area="mètres carrés", length="mètres", volume="mètres cubes",
               geo="Vérifié par la géométrie", bim="Lu dans la maquette BIM", vis="Détecté par vision",
               llm="Réponse d'un modèle d'IA",
               track="juste dans {p} pour cent des cas sur des plans similaires",
               check="vérifiez les repères sur le plan",
               conflict="Deux méthodes indépendantes ne sont pas d'accord, vérifiez les preuves.",
               abstain="Pas sûr, donc pas de supposition.", none="Ce n'est pas dans le fichier, donc pas de supposition.",
               noun=r"\bcombien\s+(?:de\s+|d')([a-zàâçéèêëîïôûùüÿœ][\w-]*)", skip=set()),
    "it": dict(over="in oltre il", dec=",", area="metri quadrati", length="metri", volume="metri cubi",
               geo="Verificato dalla geometria", bim="Letto dal modello BIM", vis="Rilevato dalla visione artificiale",
               llm="Risposta di un modello di IA",
               track="corretto {p} per cento dei casi su disegni simili",
               check="controlla i riquadri sul disegno",
               conflict="Due metodi indipendenti non sono d'accordo, controlla le prove.",
               abstain="Non ne sono sicuro, quindi non tiro a indovinare.",
               none="Non è nel file, quindi non tiro a indovinare.",
               noun=r"\bquant[eiao]\s+([a-zàèéìòù][\w-]*)", skip={"ci", "sono", "ne"}),
    "nl": dict(over="meer dan", dec=",", area="vierkante meter", length="meter", volume="kubieke meter",
               geo="Geverifieerd met geometrie", bim="Opgezocht in het BIM-model", vis="Gedetecteerd met beeldherkenning",
               llm="Beantwoord door een AI-model",
               track="bij vergelijkbare tekeningen in {p} procent van de gevallen juist",
               check="controleer de markeringen op de tekening",
               conflict="Twee onafhankelijke methoden zijn het oneens, controleer het bewijs.",
               abstain="Niet zeker, dus geen gok.", none="Dat staat niet in het bestand, dus geen gok.",
               noun=r"\bhoeveel\s+([a-zë][\w-]*)", skip={"zijn", "er", "staan", "is"}),
    "sv": dict(over="över", dec=",", area="kvadratmeter", length="meter", volume="kubikmeter",
               geo="Verifierat med geometri", bim="Uppslaget i BIM-modellen", vis="Upptäckt med bildigenkänning",
               llm="Besvarat av en AI-modell",
               track="rätt i {p} procent av fallen på liknande ritningar",
               check="kontrollera markeringarna på ritningen",
               conflict="Två oberoende metoder är oense, så kontrollera underlaget.",
               abstain="Inte säker, så ingen gissning.", none="Det finns inte i filen, så ingen gissning.",
               noun=r"\bhur\s+många\s+([a-zåäö][\w-]*)", skip={"finns", "är", "det"}),
}


def trust_kind(method: str) -> str:
    """The same badge the answer card shows (howOf in app.js): geo / bim / vis / llm / none."""
    m = method or ""
    if re.search(r"-na$|-none$", m):
        return "none"
    if m.startswith("swiss"):
        return "geo"
    if m.startswith("ifc-text"):
        return "bim"
    if m.startswith("ifc") and not m.startswith("ifctext"):
        return "geo"
    if m.startswith("cubicasa") or re.search(r"ground|^vlm", m):
        return "vis"
    return "llm"


def pct(right: int, n: int) -> str:
    """Like the card: never round up to 100 % unless every one was right."""
    if right >= n:
        return "100"
    p = int(1000 * right / n) / 10
    return f"{int(10000 * right / n) / 100:.2f}" if p >= 99.9 else f"{p:.1f}"


def _num(v: float, typ: str, dec: str) -> str:
    if typ == "count":
        return str(int(round(v)))
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", dec)


def clean(text: str, limit: int = 200) -> str:
    """First sentence of a free-text answer, without markdown, list marks or anything a voice should not read."""
    t = re.sub(r"[`*_#>|\[\]{}<>\\]", " ", str(text or ""))
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"^\s*[-•\d.)]+\s+", "", t.strip().split("\n")[0])
    t = re.sub(r"\s+([,.;:!?])", r"\1", " ".join(t.split()))
    m = re.match(r"(.+?[.!?])(?:\s|$)", t)
    t = m.group(1) if m and len(m.group(1)) >= 12 else t
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return t


def sentence(rec: dict, lang: str) -> str:
    """rec: {question, answer, type, method, calibration, crosscheck} as /api/ask returned them."""
    L = T.get(lang) or T["en"]
    ans, typ, method = rec.get("answer"), rec.get("type") or "count", rec.get("method") or ""
    kind = trust_kind(method)
    if ans is None:
        return L["abstain"]
    if kind == "none":
        return L["none"]
    if isinstance(ans, bool):
        ans = str(ans)
    if isinstance(ans, (int, float)):
        n = _num(float(ans), typ, L["dec"])
        if typ == "count":
            noun = ""
            mm = re.search(L["noun"], rec.get("question") or "", re.I)
            if mm and int(round(float(ans))) != 1 and mm.group(1).lower() not in L["skip"]:
                noun = " " + mm.group(1).lower() if lang != "de" else " " + mm.group(1)
            head = f"{n}{noun}."
        else:
            head = f"{n} {L.get(typ, '')}".rstrip() + "."
    else:
        head = clean(ans)
        if not head:
            return L["abstain"]
        if head[-1] not in ".!?…":
            head += "."
    cc = (rec.get("crosscheck") or {}).get("status")
    if cc == "conflict":
        return f"{head} {L['conflict']}"
    c = rec.get("calibration") or {}
    badge = L[kind]
    if c.get("measured") and c.get("n"):
        p = pct(int(c["right"]), int(c["n"])).removesuffix(".0")
        if lang != "en" and "." in p:  # "99,95 prosenttia" comes out garbled in some languages: say "over 99"
            p = f"{L['over']} {p.split('.')[0]}"
        elif lang == "it":
            p = f"nel {p}"
        return f"{head} {badge}, {L['track'].format(p=p)}."
    if kind in ("geo", "bim"):
        return f"{head} {badge}."
    return f"{head} {badge}; {L['check']}."
