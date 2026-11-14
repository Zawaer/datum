"""bp.sheets: the upload's warm-up runs once, and a question asked while it runs waits for it instead of redoing it."""
import threading
import time
import types

from bp import sheets


def _fake_module(calls):
    m = types.SimpleNamespace()
    m.detect = lambda meta: 1.0
    gate = threading.Event()

    def warm(meta):
        calls.append("warm")
        gate.wait(5)
        meta["_fake_read"] = 42

    def answer(path, question, meta):
        calls.append("answer")
        return {"answer": meta.get("_fake_read"), "confidence": 0.9, "evidence": []}

    m.warm, m.answer = warm, answer
    return m, gate


def test_answer_waits_for_inflight_warm(monkeypatch, tmp_path):
    calls = []
    mod, gate = _fake_module(calls)
    monkeypatch.setattr(sheets, "modules", lambda: [("piping", mod)])
    monkeypatch.setattr(sheets, "_load", lambda n: mod)
    meta = {"path": str(tmp_path / "a.png"), "page": 0}
    f1 = sheets.warm_upload(meta)
    assert sheets.warm_upload(meta) is f1  # one warm-up per sheet page
    threading.Timer(0.3, gate.set).start()
    t = time.time()
    res = sheets.answer(meta["path"], "how many?", meta)
    assert res["answer"] == 42 and res["method"] == "sheets-piping"
    assert calls == ["warm", "answer"] and time.time() - t >= 0.25


def test_answer_times_out_while_warm_runs(monkeypatch, tmp_path):
    calls = []
    mod, gate = _fake_module(calls)
    monkeypatch.setattr(sheets, "modules", lambda: [("piping", mod)])
    monkeypatch.setattr(sheets, "_load", lambda n: mod)
    monkeypatch.setattr(sheets, "ANSWER_TIMEOUT_S", 0.2)
    meta = {"path": str(tmp_path / "b.png"), "page": 0}
    sheets.warm_upload(meta)
    res = sheets.answer(meta["path"], "how many?", meta)
    gate.set()
    assert res["answer"] is None and res["method"] == "sheets-piping-timeout"
    assert calls == ["warm"]  # the module was not started a second time next to the warm-up
