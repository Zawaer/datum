"""bp/intent.py: two asks in one question are split; non-English questions are detected for translation."""
from bp.intent import needs_translation, part_label, split_asks, valid_translation


def test_split_two_asks():
    assert split_asks("How many check valves and what size is the discharge header?") == [
        "How many check valves?", "What size is the discharge header?"]
    p = split_asks("How many doors are listed in the pumphouse door schedule, and how many of them are 3'-0\" wide?")
    assert p[1] == "How many of the doors listed in the pumphouse door schedule are 3'-0\" wide?"
    assert [part_label(x) for x in p] == ["Doors", "3'-0\" wide"]


def test_no_split_of_one_ask():
    for q in ("How many sinks and wash basins are drawn on this floor plan?", "How many doors and windows?",
              "What is the total area of the east and west wings?", "Slab area by type (thickness and bars)?"):
        assert split_asks(q) is None, q


def test_foreign_detection():
    assert needs_translation("Montako luokkahuonetta tässä kerroksessa on?")
    assert needs_translation("Mikä on 300 mm laatan pinta-ala siinä osassa, jossa on D22-raudoitus?")
    assert needs_translation("Hur många grupprum finns det på plan 00?")
    assert needs_translation("Wie groß ist die gesamte Verkehrsfläche (Circulation) im 2. OG?")
    assert not needs_translation("What is the reinforcement of the tank floor slab?")


def test_translation_keeps_numbers():
    src = "Mikä on 300 mm laatan pinta-ala siinä osassa, jossa on D22-raudoitus?"
    assert valid_translation(src, "What is the area of the 300 mm slab in the part with D22 reinforcement?")
    assert not valid_translation(src, "What is the area of the slab with D22 reinforcement?")
