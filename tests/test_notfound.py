"""A name the drawing does not have (bp/notfound.py): the structured abstention, the chips' substituted questions,
the one normaliser call that may map the name onto one of the drawing's own (stubbed here: no LLM), and that
dataset template questions never reach that call."""
import pytest

from bp import notfound as NF


# ---------------------------------------------------------------- no data needed
def test_ranked_dedupes_most_frequent_first_keeps_drawing_order_on_ties():
    assert NF.ranked(["Bad", "Zimmer", None, "Zimmer", "Küche", "Bad", "Zimmer", ""]) == ["Zimmer", "Bad", "Küche"]
    assert NF.ranked(["Erdgeschoss", "Dachgeschoss"]) == ["Erdgeschoss", "Dachgeschoss"]


def test_abstain_structure():
    names = [f"L{i}" for i in range(20)] + ["L5", "L5"]
    r = NF.abstain({"method": "swiss-dxf", "evidence": []}, "label", "skibidi", names)
    assert r["answer"] is None and r["method"] == "swiss-dxf"
    assert r["not_found"] == {"kind": "label", "asked": "skibidi",
                              "available": ["L5"] + [f"L{i}" for i in range(20) if i != 5][:11]}
    assert len(r["not_found"]["available"]) == NF.MAX_AVAILABLE
    assert r["_not_found_all"][0] == "L5" and len(r["_not_found_all"]) == 20  # all names, for the normaliser
    assert r["explanation"].startswith("No room on this plan is labelled 'skibidi'.")


@pytest.mark.parametrize("kind, asked, where, text", [
    ("label", "skibidi", "on this plan", "No room on this plan is labelled 'skibidi'."),
    ("room", "9.99", "on this plan", "There is no room 9.99 on this plan."),
    ("room", "Kitchen", "on 'Erdgeschoss'", "There is no room named 'Kitchen' on 'Erdgeschoss'."),
    ("storey", "Level 99", "in this model", "There is no storey named 'Level 99' in this model."),
    ("apartment", "Q", "on this plan", "There is no apartment Q on this plan."),
])
def test_sentence(kind, asked, where, text):
    assert NF.sentence(kind, asked, where) == text


@pytest.mark.parametrize("q, asked, name, kind, out", [
    ("How many rooms labelled 'skibidi' are there on this floor?", "skibidi", "Zimmer", "label",
     "How many rooms labelled 'Zimmer' are there on this floor?"),
    ('how many "Zimer" rooms?', "Zimer", "Zimmer", "label", 'how many "Zimmer" rooms?'),
    ("Wie viele Räume mit der Bezeichnung «Kuche»?", "Kuche", "Küche", "label",
     "Wie viele Räume mit der Bezeichnung «Küche»?"),
    ("What is the net floor area of room 9.99 ('Bad') in m²?", "9.99", "6.02", "room",
     "What is the net floor area of room 6.02 ('Bad') in m²?"),
    ("What is the net floor area of apartment Q in m²?", "Q", "A", "apartment",
     "What is the net floor area of apartment A in m²?"),
    # 'A' also occurs as a word: the apartment slot is the one replaced
    ("A question: what is the area of apartment E?", "E", "A", "apartment", "A question: what is the area of apartment A?"),
    ("How many doors are shown on the floor plan of 'Level 99'?", "Level 99", "Erdgeschoss", "storey",
     "How many doors are shown on the floor plan of 'Erdgeschoss'?"),
    # the room is replaced, the storey after it stays
    ("What is the net floor area of the room 'Kitchen' on 'Erdgeschoss', in m²?", "Kitchen", "Küche (6)", "room",
     "What is the net floor area of the room 'Küche (6)' on 'Erdgeschoss', in m²?"),
])
def test_substitute(q, asked, name, kind, out):
    assert NF.substitute(q, asked, name, kind) == out


def test_substitute_missing():
    assert NF.substitute("How many rooms?", "skibidi", "Zimmer", "label") is None
    assert NF.substitute("How many rooms?", "", "Zimmer", "label") is None


def test_options_are_the_chips():
    nf = {"kind": "label", "asked": "skibidi", "available": [f"L{i}" for i in range(12)]}
    opts = NF.options("How many rooms labelled 'skibidi' are there on this floor?", nf)
    assert len(opts) == 8
    assert opts[0] == {"name": "L0", "question": "How many rooms labelled 'L0' are there on this floor?"}


def test_match_name_only_returns_a_listed_name(monkeypatch, tmp_path):
    from bp import normalize as N
    from bp.ifctext import llm

    monkeypatch.setattr(N, "CACHE", tmp_path / "n.jsonl")
    monkeypatch.setattr(N, "_mem", None)
    replies = iter(["Zimmer", "Schlafzimmer", "NONE", "Küche", "'Bad'"])
    monkeypatch.setattr(llm, "ask", lambda *a, **k: {"text": next(replies), "cost_usd": 0.001})
    names = ["Zimmer", "Bad", "Küche (6)"]

    def m(asked):
        return N.match_name("swiss", {"question": f"rooms labelled '{asked}'?", "path": "p"},
                            {"kind": "label", "asked": asked}, names)["name"]
    assert m("Zimer") == "Zimmer"
    assert m("bedroom") is None          # a name not on the drawing is refused
    assert m("skibidi") is None
    assert m("kitchen") == "Küche (6)"   # the bare form of exactly one listed 'name (n)'
    assert m("bath") == "Bad"            # quotes around the reply are dropped
    assert m("Zimer") == "Zimmer"        # cached: no sixth call (the iterator is empty)
    assert N.match_name("swiss", {"question": "apartment Q?", "path": "p"},
                        {"kind": "apartment", "asked": "Q"}, ["A", "B"])["cost_usd"] == 0.0  # letters: no call


# ---------------------------------------------------------------- on dataset drawings
SWISS = "data/swiss_dwellings/site2246_bldg3132_floor14260.pdf"
IFC = "data/ifc_models/kit-fzk-haus_ac20-fzk-haus_plan-01-erdgeschoss.pdf"


@pytest.fixture
def router(monkeypatch):
    """A router with the normaliser on, whose LLM steps are stubs that record their calls."""
    from bp import normalize as N
    from bp.router import Router

    calls = {"match": [], "normalize": []}
    picks = {}

    def match_name(route, q, nf, names):
        calls["match"].append(nf["asked"])
        pick = picks.get(nf["asked"])
        assert pick is None or pick in names
        return {"name": pick, "cost_usd": 0.0, "why": "" if pick else "no listed name matches"}

    def normalize(route, q):
        calls["normalize"].append(q["question"])
        return {"question": None, "cost_usd": 0.0, "why": "stub"}

    monkeypatch.setattr(N, "match_name", match_name)
    monkeypatch.setattr(N, "normalize", normalize)
    r = Router(crosscheck=False)
    r.normalize = True
    r.calls, r.picks = calls, picks
    return r


@pytest.mark.data
def test_swiss_unknown_label_is_structured(router):
    res = router({"question": "How many rooms labelled 'skibidi' are there on this floor?", "path": SWISS,
                  "source": "swiss_dwellings"})
    assert res["answer"] is None
    nf = res["not_found"]
    assert nf["kind"] == "label" and nf["asked"] == "skibidi"
    assert nf["available"][0] in ("Zimmer", "Korridor") and set(nf["available"]) >= {"Bad", "Küche", "Zimmer"}
    assert len(nf["available"]) == len(set(nf["available"])) <= 12
    assert res["explanation"].startswith("No room on this plan is labelled 'skibidi'.")
    assert nf["options"][0]["question"] == f"How many rooms labelled '{nf['available'][0]}' are there on this floor?"
    assert "_not_found_all" not in res
    assert router.calls["match"] == ["skibidi"]


@pytest.mark.data
def test_swiss_typo_is_read_as_the_plan_label(router):
    router.picks["Zimer"] = "Zimmer"
    res = router({"question": "How many rooms labelled 'Zimer' are there on this floor?", "path": SWISS,
                  "source": "swiss_dwellings"})
    assert res["answer"] == 5 and "not_found" not in res
    assert res["normalized_question"] == "How many rooms labelled 'Zimmer' are there on this floor?"
    assert res["explanation"].startswith("read as: ")


@pytest.mark.data
@pytest.mark.parametrize("q, kind", [
    ("What is the net floor area of room 9.99 ('Bad') in m²?", "room"),
    ("What is the net floor area of apartment Q in m², summing all its rooms except balconies, loggias, terraces "
     "and other outdoor spaces?", "apartment"),
    ("What is the total net area in m² of all rooms labelled 'skibidi' on this floor?", "label"),
])
def test_swiss_other_kinds(router, q, kind):
    res = router({"question": q, "path": SWISS, "source": "swiss_dwellings", "type": "area"})
    assert res["answer"] is None and res["not_found"]["kind"] == kind and res["not_found"]["options"]


@pytest.mark.data
def test_ifc_unknown_storey_and_room(router):
    res = router({"question": "How many doors are shown on the floor plan of 'Level 99'?", "path": IFC,
                  "source": "ifc_models"})
    assert res["not_found"]["kind"] == "storey" and res["not_found"]["available"] == ["Erdgeschoss", "Dachgeschoss"]
    router.picks["Kitchen"] = "Küche (6)"
    res = router({"question": "What is the net floor area of the room 'Kitchen' on 'Erdgeschoss', in m²?",
                  "path": IFC, "source": "ifc_models"})
    assert res["answer"] == pytest.approx(16.31, abs=0.01)
    assert "'Küche (6)'" in res["normalized_question"]


@pytest.mark.data
def test_dataset_templates_never_reach_the_llm_steps(router):
    """Every dataset question on a few test drawings is answered without either normaliser call."""
    from bp.data import load_questions

    want = {SWISS, IFC, "data/swiss_dwellings/site3387_bldg5238_floor23498.pdf",
            "data/ifc_models/bsc-duplex_duplex-m-20111024-rooms-and-spaces.ifc"}
    qs = [q for q in load_questions() if q["path"] in want]
    assert len(qs) > 20
    for q in qs:
        res = router(q)
        assert res.get("answer") is not None, q["question"]
        assert "not_found" not in res
    assert router.calls == {"match": [], "normalize": []}
