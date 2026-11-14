"""End-to-end answers on real dataset drawings (marked `data`: skipped without data/ and, for CubiCasa, the
detector weights). Each question is from the test split and was answered exactly in the published run."""
import pytest

from bp.data import source_of
from bp.score import is_correct

pytestmark = pytest.mark.data

SWISS = "data/swiss_dwellings/site3387_bldg5238_floor23498.pdf"
CASES = [
    pytest.param(SWISS, "area", "What is the net floor area of room 7.01 ('Balkon') in m²?", 15.47, "swiss",
                 id="swiss-room-area"),
    pytest.param(SWISS, "count", "How many apartments (residential units) are shown on this floor plan?", 2, "swiss",
                 id="swiss-apartment-count"),
    pytest.param("data/ifc_models/bsc-duplex_duplex-m-20111024-rooms-and-spaces.ifc", "count",
                 "How many rooms (spaces) are there in the model 'Duplex Apartment - mechanical (rooms and spaces)'?",
                 37, "ifc", id="ifc-space-count"),
    pytest.param("data/ifc_models/kit-fzk-haus_ac20-fzk-haus_plan-01-erdgeschoss.pdf", "area",
                 "What is the net floor area of the room 'Küche (6)' on 'Erdgeschoss', in m²?", 16.31, "ifc",
                 id="ifc-room-area"),
    pytest.param("data/cubicasa5k/colorful-10266.png", "count",
                 "How many doors are shown on this floor plan? Count doorways fitted with a door; open doorways "
                 "without a door leaf do not count.", 6, "cubicasa", marks=pytest.mark.weights, id="cubicasa-doors"),
]


@pytest.fixture(scope="module")
def router():
    from bp.router import Router

    return Router(crosscheck=False)


@pytest.mark.parametrize("path, qtype, question, gold, route", CASES)
def test_answer(router, path, qtype, question, gold, route):
    q = {"path": path, "type": qtype, "question": question, "source": source_of(path),
         "ext": path.rsplit(".", 1)[-1].lower()}
    res = router(q)
    assert res.get("route") == route
    assert is_correct(qtype, res.get("answer"), gold), res.get("answer")
    assert res.get("evidence"), "an answer must point at its proof on the drawing"
    assert float(res.get("cost_usd") or 0) == 0.0


def test_swiss_unknown_room_abstains_or_flags(router):
    q = {"path": SWISS, "type": "area", "question": "What is the net floor area of room 99.99 ('Ballsaal') in m²?",
         "source": "swiss_dwellings", "ext": "pdf"}
    res = router(q)
    assert res.get("answer") is None or float(res.get("confidence") or 0) < 0.5
