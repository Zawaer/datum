"""Projects (app/projects.py): several uploads asked as one building. Create / list / upload (files and a .zip) /
ask (an explicit floor, the whole building summed per floor, buildings never mixed) and the clarify follow-ups,
on small synthetic plans; the specialists are stubbed, so no model call and no heavy reading runs."""
import io
import json
import zipfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import app.projects as P  # noqa: E402
import app.server as S  # noqa: E402


def _plan(seed: int) -> bytes:
    im = Image.new("L", (400, 300), 255)
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 380, 280], outline=0, width=4)
    d.line([200, 20, 200, 280], fill=0, width=3)
    d.text((40 + seed, 40), f"plan {seed}", fill=0)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


@pytest.fixture()
def cl(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(S, "SHEET_CHECK", False)
    monkeypatch.setattr(S, "SHEET_TYPES", False)
    monkeypatch.setattr(S, "_gpu_warm", lambda m: None, raising=False)
    monkeypatch.setattr(P, "PROJECTS", tmp_path / "projects")
    return TestClient(S.app)


def _new(cl) -> str:
    r = cl.post("/api/projects", json={"name": "Test"})
    assert r.status_code == 200
    return r.json()["id"]


def _up(cl, pid, name, body):
    r = cl.post(f"/api/projects/{pid}/upload?name={name}", content=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_level_and_building_from_titles():
    assert P.level_of("Special_School_Plan_Level_00")["n"] == 0
    assert P.level_of("LEVEL 01 FLOOR PLAN")["label"] == "Level 01"
    assert P.level_of("2nd floor plan")["n"] == 2
    assert P.level_of("Ground floor")["n"] == 0
    assert P.level_of("Kellari")["n"] == -1
    assert P.level_of("1. krs pohjapiirros")["label"] == "1. krs"
    assert P.level_of("What is the total floor area?") is None
    assert P.building_of("SEN-DFE-XX-00-D-X-0201-Special_School_Plan_Level_00-A-C01.pdf") == "Special school"
    assert P.building_of("PRI-DFE-XX-00-D-X-0201-Primary_School_GA_Plan_Level_00-A-C01.pdf") == "Primary school"
    assert P.building_of("foundation_slab_plan_S-100F.png") == ""


def test_create_list_upload(cl):
    pid = _new(cl)
    assert len(pid) == 12
    _up(cl, pid, "House_Level_00.png", _plan(1))
    d = _up(cl, pid, "House_Level_01.png", _plan(2))
    p = d["project"]
    assert [s["level"]["label"] for s in p["sheets"]] == ["Level 00", "Level 01"]
    assert p["buildings"] == ["House"]
    assert cl.get(f"/api/projects/{pid}").json()["sheets"] == p["sheets"]
    # the same file again is not listed twice
    assert len(_up(cl, pid, "House_Level_01.png", _plan(2))["project"]["sheets"]) == 2


def test_zip_upload_and_guards(cl):
    pid = _new(cl)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("set/Barn_Level_00.png", _plan(3))
        z.writestr("set/Barn_Level_01.png", _plan(4))
        z.writestr("set/readme.txt", "not a drawing")
        z.writestr("__MACOSX/._Barn_Level_00.png", "junk")
    d = _up(cl, pid, "barn.zip", b.getvalue())
    assert len(d["uploads"]) == 2 and len(d["project"]["sheets"]) == 2
    assert cl.post(f"/api/projects/{pid}/upload?name=x.zip", content=b"not a zip").status_code == 422
    assert cl.get("/api/projects/../../etc").status_code == 404
    assert cl.get("/api/projects/zzzzzzzzzzzz").status_code == 404
    assert cl.get("/api/projects/0123456789ab").status_code == 404


def test_zip_bomb_refused(cl):
    pid = _new(cl)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("big.png", b"\0" * (12 * 1024 * 1024))
    assert cl.post(f"/api/projects/{pid}/upload?name=b.zip", content=b.getvalue()).status_code == 413


def test_file_cap(cl, monkeypatch):
    monkeypatch.setattr(P, "MAX_FILES", 1)
    pid = _new(cl)
    _up(cl, pid, "A_Level_00.png", _plan(5))
    assert cl.post(f"/api/projects/{pid}/upload?name=A_Level_01.png", content=_plan(6)).status_code == 413


@pytest.fixture()
def fake_run(monkeypatch):
    """Each floor answers from a table: doors per level, the hall only on level 00."""
    calls = []

    def run(s, question, request):
        calls.append((s["ref"], question))
        n = (s.get("level") or {}).get("n", 0)
        if "door" in question.lower():
            return {"answer": [12, 7][n], "confidence": 0.9, "method": "sheets-openings-cv", "type": "count",
                    "evidence": [{"kind": "box", "bbox": [0.1, 0.1, 0.2, 0.2], "label": "door 1"}]}
        if "hall" in question.lower():
            if n == 0:
                return {"answer": 245.0, "unit": "m²", "confidence": 0.7, "method": "sheets-rooms-area", "evidence": []}
            return {"answer": None, "method": "sheets-rooms-ask", "explanation": "I found no room named 'hall' on this "
                    "sheet. Rooms I can read: Library, Music Room. Which one do you mean, or should I total all rooms?"}
        return {"answer": None, "method": "none", "evidence": []}

    monkeypatch.setattr(P, "_run", run)
    return calls


def _two_floors(cl):
    pid = _new(cl)
    _up(cl, pid, "School_Level_00.png", _plan(7))
    p = _up(cl, pid, "School_Level_01.png", _plan(8))["project"]
    return pid, p["sheets"]


def test_ask_whole_building_sums_per_floor(cl, fake_run):
    pid, sheets = _two_floors(cl)
    r = cl.post(f"/api/projects/{pid}/ask", json={"question": "How many doors in the whole school?"}).json()
    assert r["answer"] == 19 and r["method"] == "project-sum"
    parts = r["project"]["parts"]
    assert [(x["label"], x["value"]) for x in parts] == [("Level 00", 12), ("Level 01", 7)]
    assert all(x["result"]["evidence"] for x in parts)  # each floor keeps its own marks
    assert all(q == "How many doors?" for _, q in fake_run)  # the scope words are not sent to the specialist


def test_ask_explicit_floor(cl, fake_run):
    pid, sheets = _two_floors(cl)
    r = cl.post(f"/api/projects/{pid}/ask", json={"question": "How many doors on Level 01?"}).json()
    assert r["answer"] == 7 and r["project"]["sheet"]["ref"] == sheets[1]["ref"] and not r["clarify"]


def test_ask_unclear_floor_clarifies_with_best_guess(cl, fake_run):
    pid, sheets = _two_floors(cl)
    r = cl.post(f"/api/projects/{pid}/ask", json={"question": "How many doors?", "sheet": sheets[1]["ref"]}).json()
    assert r["clarify"]["question"] == "Which floor?"
    assert r["best_guess"] and r["answer"] == 7  # the sheet being viewed
    labels = [o["label"] for o in r["clarify"]["options"]]
    assert labels == ["Level 00", "Level 01", "Whole building (sum)"]
    # one tap: the option's value is the question to ask next
    r2 = cl.post(f"/api/projects/{pid}/ask", json={"question": r["clarify"]["options"][0]["value"]}).json()
    assert r2["answer"] == 12 and not r2["clarify"]
    r3 = cl.post(f"/api/projects/{pid}/ask", json={"question": r["clarify"]["options"][2]["value"]}).json()
    assert r3["answer"] == 19 and r3["method"] == "project-sum"


def test_ask_room_found_on_one_floor(cl, fake_run):
    pid, sheets = _two_floors(cl)
    r = cl.post(f"/api/projects/{pid}/ask", json={"question": "What is the area of the hall?"}).json()
    assert r["answer"] == 245.0 and r["project"]["sheet"]["ref"] == sheets[0]["ref"]
    assert "only floor" in r["project"]["why"]


def test_buildings_never_mixed(cl, fake_run):
    pid = _new(cl)
    _up(cl, pid, "Primary_School_Level_00.png", _plan(9))
    _up(cl, pid, "Primary_School_Level_01.png", _plan(10))
    p = _up(cl, pid, "Special_School_Level_00.png", _plan(11))["project"]
    assert p["buildings"] == ["Primary school", "Special school"]
    r = cl.post(f"/api/projects/{pid}/ask", json={"question": "How many doors in the whole building?"}).json()
    assert r["clarify"]["question"] == "Which building?"
    assert len(r["project"]["parts"]) == 2  # the best guess sums one building only
    r2 = cl.post(f"/api/projects/{pid}/ask", json={"question": "How many doors in all buildings?"}).json()
    assert r2["answer"] == 12 + 7 + 12 and len(r2["project"]["parts"]) == 3
    r3 = cl.post(f"/api/projects/{pid}/ask", json={"question": "How many doors in the whole Special school?"}).json()
    assert r3["answer"] == 12 and not r3["clarify"]


def test_clarify_for_rooms_and_area():
    ask = {"answer": None, "method": "sheets-rooms-ask", "explanation": "I found no room named 'gym' on this sheet. "
           "Rooms I can read: Library, Main Hall, Store. Which one do you mean, or should I total all rooms?"}
    c = P.clarify_for(ask, "What is the area of the gym?")
    assert c["kind"] == "room" and {o["label"] for o in c["options"]} == {"Library", "Main Hall", "Store"}
    q, picks = P.prepare_question(c["options"][0]["value"])
    assert picks["room"] and q.startswith("What is the area of the ")
    two = {"answer": 60.0, "method": "sheets-rooms-area-sum", "evidence": [
        {"kind": "polygon", "label": "Main hall 40.0 m²", "value": 40.0},
        {"kind": "polygon", "label": "Sports hall 20.0 m²", "value": 20.0}]}
    c = P.clarify_for(two, "What is the area of the hall?")
    assert [o["label"] for o in c["options"]][:2] == ["Main hall", "Sports hall"]
    picked = P.postprocess(two, P.prepare_question(c["options"][1]["value"])[1])
    assert picked["answer"] == 20.0 and len(picked["evidence"]) == 1
    tot = {"answer": "Total 900 m² net over 30 rooms.", "value": 900.0, "method": "sheets-rooms-area-list"}
    c = P.clarify_for(tot, "What is the total floor area?")
    assert c["kind"] == "area"
    assert "gross" in P.prepare_question(c["options"][1]["value"])[0]
    assert P.clarify_for(tot, "What is the total net floor area?") is None


def test_single_upload_ask_carries_clarify(cl, monkeypatch):
    """/api/ask on one upload: the rooms specialist's "which room?" becomes a structured clarify."""
    d = cl.post("/api/upload?name=flat.png", content=_plan(12)).json()
    monkeypatch.setattr(S, "_run_router", lambda q, timeout=0: {
        "answer": None, "confidence": 0.0, "evidence": [], "method": "sheets-rooms-ask", "route": "sheets",
        "explanation": "I found no room named 'den' on this sheet. Rooms I can read: Kitchen, Bedroom. Which one do "
                       "you mean, or should I total all rooms?"})
    r = cl.post("/api/ask", json={"path": d["path"], "question": "What is the area of the den?"}).json()
    assert r["clarify"]["kind"] == "room"
    seen = {}
    monkeypatch.setattr(S, "_run_router", lambda q, timeout=0: seen.update(q=q["question"]) or {
        "answer": 12.0, "unit": "m²", "confidence": 0.7, "evidence": [], "method": "sheets-rooms-area"})
    r2 = cl.post("/api/ask", json={"path": d["path"], "question": r["clarify"]["options"][0]["value"]}).json()
    assert r2["answer"] == 12.0 and "(room:" not in seen["q"]
    assert json.dumps(r2)  # serialisable
