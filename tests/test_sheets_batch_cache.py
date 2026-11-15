"""The sheet cache under a burst of uploads (bp/sheets/__init__.py, rooms.py) and rooms by their use on coarse rasters
(rooms.typed_room / typed_count): packed label maps, readings kept beside the upload, the trim order, the neck split.
Fast: synthetic arrays, no OCR, no model calls (llm.ask is patched)."""
import json

import numpy as np
import pytest
from PIL import Image

from bp import sheets
from bp.sheets import rooms as R


@pytest.fixture(autouse=True)
def _no_model_calls(monkeypatch):
    import bp.generic.llm as llm

    monkeypatch.setattr(llm, "ask", lambda *a, **k: {"text": "", "cost_usd": 0.0})


def test_packed_label_map_roundtrip_and_small():
    lab = np.zeros((1200, 1600), np.int32)
    for i in range(1, 400):
        y, x = (i * 37) % 1100, (i * 53) % 1500
        lab[y:y + 60, x:x + 90] = i
    p = R.pack_lab(lab)
    assert p.nbytes < lab.nbytes / 20
    a = R.lab_of({"_lab": {"lab": p}})
    assert a.dtype == np.uint16 and np.array_equal(a, lab)
    big = lab.copy()
    big[0, 0] = 70000  # past uint16: kept as int32
    assert R.pack_lab(big).unpack().dtype == np.int32
    assert R.lab_of({"lab": lab}) is lab  # an unpacked map (tests, old callers) passes through
    assert sheets._nbytes({"_rooms_seg": {"_lab": {"lab": p}}}) < 1 << 20


def test_disk_cache_only_in_upload_folders(tmp_path, monkeypatch):
    img = tmp_path / "plan.png"
    Image.new("L", (40, 30), 255).save(img)
    assert not sheets.disk_cache_ok(str(img))  # a source drawing / fixture folder: nothing written beside it
    (tmp_path / "sheet_meta_p0.json").write_text("{}")
    assert sheets.disk_cache_ok(str(img))
    monkeypatch.setenv("BP_SHEET_DISK_CACHE", "0")
    assert not sheets.disk_cache_ok(str(img))


def test_ocr_words_reload_from_beside_the_upload(tmp_path):
    img = tmp_path / "plan.png"
    Image.new("L", (40, 30), 255).save(img)
    (tmp_path / "sheet_meta_p0.json").write_text("{}")
    meta = {"image": str(img)}
    calls = []

    def run():
        calls.append(1)
        return [{"text": "Kitchen", "conf": 90.0, "bbox": [0.1, 0.1, 0.2, 0.2]}]

    assert sheets._ocr_disk(meta, "None|1.0|11", run)[0]["text"] == "Kitchen"
    assert sheets._ocr_disk(meta, "None|1.0|11", run)[0]["text"] == "Kitchen"
    assert len(calls) == 1  # the second read came from the file
    assert sheets._ocr_disk(meta, "None|2.0|11", lambda: []) == []  # another signature; empty results not kept
    assert len(list(tmp_path.glob("*.ocr_*.json"))) == 1


def test_segmentation_persisted_and_reloaded(tmp_path):
    img = tmp_path / "plan.png"
    Image.new("L", (40, 30), 255).save(img)
    (tmp_path / "sheet_meta_p0.json").write_text("{}")
    meta = {"image": str(img), "path": str(img)}
    import threading

    lab = np.zeros((30, 40), np.int32)
    lab[5:20, 5:30] = 3
    seg = {"rooms": [{"id": 3, "label": "Kitchen", "label_source": "vision", "area_m2": 9.0}], "_crop_read": True,
           "_crop_lock": threading.Lock(), "_lab": {"lab": R.pack_lab(lab), "f": 1.0}}
    R.persist(meta, seg)
    got = R._cached(dict(meta))  # a fresh meta (the old one was dropped from memory): reloaded, not segmented
    assert got["rooms"][0]["label"] == "Kitchen" and got["_crop_read"] and "_crop_lock" not in got
    assert np.array_equal(R.lab_of(got), lab)


def test_trim_drops_heavy_metas_first_and_keeps_warming(monkeypatch):
    import concurrent.futures as cf

    monkeypatch.setattr(sheets, "META_MEM_BYTES", 30 << 20)
    saved = dict(sheets._meta_mem)
    sheets._meta_mem.clear()
    try:
        big = lambda: {"_rooms_seg": {"x": np.zeros(20 << 20, np.uint8)}}  # noqa: E731
        sheets._meta_mem[("a", 0)] = {"path": "a", "page": 0}  # oldest, tiny
        sheets._meta_mem[("b", 0)] = {"path": "b", "page": 0, **big()}  # heavy, its warm-up still running
        sheets._meta_mem[("c", 0)] = {"path": "c", "page": 0, **big()}  # heavy
        sheets._meta_mem[("d", 0)] = {"path": "d", "page": 0}  # newest
        f = cf.Future()
        with sheets._warm_lock:
            sheets._warm_jobs[sheets._warm_key(sheets._meta_mem[("b", 0)])] = f
        sheets._trim_meta_mem()
        assert set(sheets._meta_mem) == {("a", 0), ("b", 0), ("d", 0)}
    finally:
        with sheets._warm_lock:
            sheets._warm_jobs.pop(sheets._warm_key({"path": "b", "page": 0}), None)
        sheets._meta_mem.clear()
        sheets._meta_mem.update(saved)


def test_type_match_and_count_phrase():
    assert R.type_match("Library", "library") == 2
    assert R.type_match("Library", "library / meeting room") == 1
    assert R.type_match("secondary classrooms", "classroom (practical/studio)") == 2
    assert R.type_match("Kitchen", "classroom") == 0
    assert R.type_match("Multi-Purpose Hall", "servery / dining") == 0  # a dining room is not "the hall" here
    assert R.type_match("WCs", "WC") == 2
    assert R.count_phrase("How many secondary classrooms are on this level?") == "secondary classrooms"
    assert R.count_phrase("Number of group rooms?") == "group rooms"


def _merged_seg():
    """Work-resolution label map (WORK_PPM px/m, f=1): room 5 = a 7.7 x 3.4 m room and a 3.5 x 3.6 m room joined
    through a 1 m opening; room 6 a plain 5 x 5 m room."""
    m = lambda v: int(round(v * R.WORK_PPM))  # noqa: E731
    lab = np.zeros((m(12), m(16)), np.int32)
    lab[m(5):m(8.4), m(1):m(8.7)] = 5  # the library
    lab[m(1.2):m(4.8), m(1):m(4.5)] = 5  # the group room above
    lab[m(4.8):m(5), m(3):m(4)] = 5  # 1 m doorway between them
    lab[m(1):m(6), m(10):m(15)] = 6
    rooms = []
    for i in (5, 6):
        ys, xs = np.nonzero(lab == i)
        rooms.append({"id": i, "bbox": [xs.min(), ys.min(), xs.max() + 1, ys.max() + 1], "label": "",
                      "area_m2": round(len(xs) / R.WORK_PPM ** 2, 2), "doors": []})
    return {"rooms": rooms, "_lab": {"lab": R.pack_lab(lab), "f": 1.0, "src_ppm": R.WORK_PPM, "W": lab.shape[1],
                                     "H": lab.shape[0]}, "px_per_m": R.WORK_PPM}


def test_neck_split_parts():
    seg = _merged_seg()
    parts = R._parts(seg, seg["rooms"][0])
    areas = sorted(p["area_m2"] for p in parts)
    assert len(parts) == 2
    assert areas[0] == pytest.approx(3.5 * 3.6, rel=0.08) and areas[1] == pytest.approx(7.7 * 3.4, rel=0.08)
    assert all(any(d.get("opening") for d in p["doors"]) for p in parts)  # the opening is not baseboard
    assert R._parts(seg, seg["rooms"][1]) == []  # a plain room has no neck


def test_typed_room_by_survey_crop_and_elimination(tmp_path, monkeypatch):
    import bp.generic.llm as llm

    seg = _merged_seg()
    seg["rooms"].append({"id": 7, "bbox": [800, 50, 950, 200], "label": "", "area_m2": 9.0, "doors": []})
    img = tmp_path / "plan.png"
    Image.new("L", (800, 600), 255).save(img)
    meta = {"image": str(img)}
    survey = {"1": {"type": "library / meeting room", "confidence": "medium"},
              "2": {"type": "kitchen", "confidence": "high"}, "3": {"type": "store", "confidence": "low"}}

    def ask(prompt, images=(), **k):
        if "numbered in red" in prompt:
            return {"text": json.dumps(survey), "cost_usd": 0.02}
        n = len(images)
        if n == 1 and "5.0 x 5.0" in prompt:  # the kitchen's own crop
            return {"text": '{"1": {"type": "kitchen", "confidence": "medium"}}', "cost_usd": 0.01}
        if n == 1:  # the merged room's crop: furniture of two rooms
            return {"text": '{"1": {"type": "meeting room", "confidence": "medium"}}', "cost_usd": 0.01}
        # its two parts: the small one reads surely as a group room, the large one is unsure
        small = "room 1: 13" in prompt
        reply = {"1": {"type": "group room", "confidence": "medium"}, "2": {"type": "dining", "confidence": "low"}} \
            if small else {"1": {"type": "dining", "confidence": "low"}, "2": {"type": "group room", "confidence": "medium"}}
        return {"text": json.dumps(reply), "cost_usd": 0.01}

    monkeypatch.setattr(llm, "ask", ask)
    room, why = R.typed_room(meta, seg, "Kitchen")
    assert room["id"] == 6 and room.get("identified_verified")
    room, why = R.typed_room(meta, seg, "Library")
    assert room["part_of"] == 5 and room["area_m2"] == pytest.approx(7.7 * 3.4, rel=0.08) and "group room" in why
    assert room["baseboard_m"] < room["perimeter_m"]
    assert R.typed_room(meta, seg, "Music Room")[0] is None  # nothing reads as one: ask back
