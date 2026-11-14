"""bp/router.py: question-type guessing (typed questions and uploads) and the static route tables."""
import pytest

from bp.router import ROUTES, UPLOAD_ROUTES, Router, guess_type
from bp.solvers import SOLVERS


@pytest.mark.parametrize("q, t", [
    ("How many doors are shown on this floor plan?", "count"),
    ("how many windows?", "count"),
    ("Kuinka monta ikkunaa?", "count"),
    ("Montako makuuhuonetta?", "count"),
    ("Wie viele Fenster?", "count"),
    ("Combien de portes?", "count"),
    ("Quanti bagni?", "count"),
    ("Hur många dörrar?", "count"),
    ("Ile okien?", "count"),
    ("number of columns", "count"),
    ("What is the net floor area of the room 'Küche (6)' on 'Erdgeschoss', in m²?", "area"),
    ("What is the net floor area of room 7.01 ('Balkon') in m²?", "area"),
    ("Wie gross ist die Fläche?", "area"),
    ("What is the total net side area of all walls on 'E01', in m²?", "area"),
    ("What is the total length of all walls on 'E01', in metres?", "length"),
    ("What is the total net volume of all walls on 'E01', in m³?", "volume"),
    ("Who is the architect?", "text"),
    ("What is the title of the sheet?", "text"),
    ("Which room is the largest?", "text"),
])
def test_guess_type(q, t):
    assert guess_type(q) == t


@pytest.mark.parametrize("q, t", [
    ("What is the area of the toilet?", "area"),
    ("What is the floor area of the mobile home?", "area"),
    ("Who drew the profile?", "text"),
])
def test_guess_type_substring_false_positives(q, t):
    assert guess_type(q) == t


def test_every_route_has_a_solver():
    for name in list(ROUTES.values()) + list(UPLOAD_ROUTES.values()):
        assert name in SOLVERS, name


def test_router_constructs_without_loading_solvers():
    r = Router(crosscheck=False)
    assert r._solvers == {}  # solvers (and torch) load lazily on the first question
