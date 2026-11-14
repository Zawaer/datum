"""bp/typofix.py: misspelt English words are fixed; real words (any supported language), numbers and ids never."""
import json
from pathlib import Path

import pytest

from bp.typofix import fix_typos, is_word

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("typed, fixed", [
    ("how mnay windws", "how many windows"),
    ("how many bathroms are there", "how many bathrooms are there"),
    ("numbr of colums", "number of columns"),
    ("How mnay Doors?", "How many Doors?"),
])
def test_fixes_typos(typed, fixed):
    assert fix_typos(typed) == fixed


@pytest.mark.parametrize("q", [
    "What is the reinforcement of the tank floor slab?",          # tank is not "than"
    "Total bathroom floor area in one dorm module (for tiling)?",  # one is not "on"
    "Mikä on 300 mm laatan pinta-ala siinä osassa, jossa on D22-raudoitus?",  # siinä is not "sinkä"
    "Kuinka suuri paineiskusäiliö (surge tank) on?",
    "Paljonko yhteistiloja (common space) ensimmäisessä kerroksessa on neliömetreinä?",
    "Wie viele Räume hat das Haus?",                               # Haus is not "has"
    "Hur många grupprum finns det på plan 00?",
    "What is the U-value of the external walls?",                  # U-value is not "U-valve"
    "How many doors are on sheet A-101F and how many FSI tags?",   # sheet ids and tags
    "Is the slab D22 @ 300 or D19 @ 250?",
])
def test_never_changes_real_words(q):
    assert fix_typos(q) == q


def test_judge_questions_untouched():
    for line in (ROOT / "analysis/judge_questions.jsonl").read_text().splitlines():
        q = json.loads(line)["question"]
        assert fix_typos(q) == q, q


def test_lexicon_languages():
    for w in ("tank", "one", "value", "siinä", "laatan", "Fläche", "grupprum", "valves", "headers"):
        assert is_word(w), w
    assert not is_word("windws")
