"""Typo fixing for typed questions: "how mnay windws" is read as "how many windows".

Only a word that is not a real word is changed. A token is left alone when it is
- a word in the lexicon: common English, Finnish, German and Swedish words, plus every word of the question corpora
  (bp/typofix_words.txt, built from the dataset, judge and fixture questions), so "tank", "one", "value" stay;
- in a question written in Finnish, German or Swedish (the normaliser translates those; a near-miss against the
  English vocabulary there is a different word, "siinä" is not "sink");
- not plain ASCII letters (ä, ö, å, ß, é ...), all capitals (FSI, ELEC, ABA), or glued to a digit, hyphen, slash,
  dot or apostrophe (D22, CV-1, U-value, A-101F, 3'-0"): numbers, sheet ids and tags are never touched.
A remaining unknown word is replaced by the closest word of the question vocabulary (VOCAB) when it is near enough:
same first letter, length within one, similarity >= 0.75.
"""
from __future__ import annotations

import difflib
import re
from functools import lru_cache
from pathlib import Path

# words of typical questions: the targets a misspelt word may be corrected to
VOCAB = frozenset("""how many much what which where who is are the this that there on in of shown drawn plan floor
drawing sheet page number total area height width length ceiling dimensions scale architect title date revision
window windows door doors toilet toilets room rooms bedroom bedrooms bathroom bathrooms kitchen kitchens sauna saunas
sink sinks shower showers bathtub bathtubs stair stairs staircase staircases storey storeys floors level levels
balcony balconies wall walls column columns parking spaces space elevator lift corridor living dining garage
closet closets office offices show shows does have has with and for from all each any can see find list name
names labelled labeled marked count give tell please whats into than then them they their these those
dorm dorms dormitory dormitories baseboard baseboards skirting slab slabs piping pipe pipes valve valves classroom
classrooms hall library meters metres linear footage square feet wing wings circulation trench trenches""".split())

# common words that are never typos (English first, then Finnish, German, Swedish)
_COMMON = """a about above across after again against all almost along also always am among an and another any are
around as at away back be because been before being below between both but by came can cannot come could day did
different do does doing done down during each either else end enough even ever every few first for found four from
full get gets give given go goes going good got great had half has have having he her here high him his how however
if in inside into is it its just keep kind know large last least left less like little long look lot low made main
make many may me mean means more most much must my near need needed needs never new next no none nor not now number
of off often old on once one ones only open or other others our out outside over own part parts per put rather
really right said same say see seen set several she should show side since small so some such sure take taken tell
than that the their them then there these they thing things think this those three through to together too top
total two under up upon us use used using very want was way we well were what when where whether which while who
whole whom whose why will with within without would yes yet you your
add added adds also amount amounts approx approximately average big biggest bigger bottom calculate calculated
check checked compare cost costs cover covered covers cubic deep depth detail details east edge edges entire
estimate exact exactly external find finish floor full gross hold holds inner internal largest larger long longest
lower main max maximum mean measure measured middle min minimum net north number outer overall perimeter quantity
read rough shown size sized sizes small smallest south square surface tall tank tanks thick thickness tile tiles
tiling total type types upper value values volume west whole wide width
air beam beams bed beds bath baths bars bar block blocks building buildings concrete deck door duct ducts entry
exit fire flow fuel gas glass grade header headers heads hole holes house lab labs mesh metal module modules note
notes opening openings pad pads panel panels plate plates pool pump pumps rebar riser roof roofs run runs schedule
schedules section sections slope steel step steps store stores support supports tag tags tank trench unit units
vent wire wires wood yard zone zones generator separator separators filter filters suction discharge surge check
reinforcement reinforced bedroom tiling wc wcs hall multi purpose group storage service common dorm
mikä mitä missä montako monta paljonko kuinka onko tässä siinä jossa joissa ja tai sekä on ei ole ovat oli kaikki
kerroksessa kerros kerroksen pinta ala alue koko yhteensä huone huoneet huonetta osassa osa laatan laatta
wie viele viel was wo welche welcher welches wer ist sind hat haben gibt das der die den dem des ein eine einer
und oder im in auf mit von zu für aus bei nach alle allen gesamte gesamt fläche groß große breite länge höhe
hur många mycket vad var vilken vilka finns det är och eller på av för med till alla den som har plan rum
""".split()


@lru_cache(maxsize=1)
def lexicon() -> frozenset[str]:
    words = set(VOCAB) | set(_COMMON)
    f = Path(__file__).with_name("typofix_words.txt")
    if f.exists():
        words |= {w.strip().lower() for w in f.read_text(encoding="utf-8").split() if w.strip()}
    return frozenset(words)


# words that mark a question as written in Finnish, German or Swedish (not English words as well)
_FOREIGN = frozenset("""mikä mitä missä montako monta paljonko kuinka onko tässä siinä jossa joissa sekä ovat
kerroksessa yhteensä wie viele welche welcher welches wieviel gibt sind ist hat haben fläche gesamte groß
hur många finns vilken vilka är och sammanlagt""".split())
_TOKEN = re.compile(r"[^\W\d_]+")
_GLUE = set("0123456789-/.'’\"_#")


def is_word(w: str) -> bool:
    """A real word (any supported language) or a plural / singular of one."""
    lw = w.lower()
    lex = lexicon()
    return lw in lex or (lw.endswith("s") and lw[:-1] in lex) or (lw + "s") in lex or \
        (lw.endswith("es") and lw[:-2] in lex)


def is_foreign(question: str) -> bool:
    return any(t.lower() in _FOREIGN for t in _TOKEN.findall(question))


def fix_typos(question: str) -> str:
    """The question with misspelt English words corrected (see the module docstring); anything doubtful is kept."""
    if not question or is_foreign(question):
        return question

    def fix(m: re.Match) -> str:
        w = m.group(0)
        s, e = m.start(), m.end()
        if (s > 0 and question[s - 1] in _GLUE) or (e < len(question) and question[e] in _GLUE):
            return w  # part of a number, tag, sheet id or hyphenated word
        if len(w) < 3 or not w.isascii() or (w.isupper() and len(w) > 1) or is_word(w):
            return w
        lw = w.lower()
        c = difflib.get_close_matches(lw, VOCAB, n=1, cutoff=0.75)
        if not c or abs(len(c[0]) - len(lw)) > 1 or c[0][0] != lw[0]:
            return w
        return c[0].capitalize() if w[0].isupper() else c[0]

    return _TOKEN.sub(fix, question)
