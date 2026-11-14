"""Spoken answers (POST/GET /api/speak, app/speak.py) with a stubbed ElevenLabs call: no network, no key, no spend.
Also: HEAD on the page/static routes, and the ask rate limit that only counts paid answers."""
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # fastapi.testclient needs it

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.server as S  # noqa: E402
from app import speak as SP  # noqa: E402

MP3 = b"ID3" + b"\x00" * 2000


def _fresh(d):
    return type(d)(d.default_factory)


@pytest.fixture
def tts(monkeypatch, tmp_path):
    calls = []

    def fake(text, lang, key):
        calls.append({"text": text, "lang": lang, "key": key})
        return MP3

    monkeypatch.setattr(S, "_tts_call", fake)
    monkeypatch.setattr(S, "_tts_key", lambda: "test-key")
    monkeypatch.setattr(S, "TTS_DAILY_CAP", 2.0)
    monkeypatch.setattr(S, "TTS_LEDGER", tmp_path / "tts_spend.jsonl")
    monkeypatch.setattr(S, "RATE_N", 0)
    monkeypatch.setattr(S, "_tts_state", {"ok": None, "checked": 0.0, "key": ""})
    monkeypatch.setattr(S, "_tts_audio", type(S._tts_audio)())
    monkeypatch.setattr(S, "_tts_hits", _fresh(S._tts_hits))
    return TestClient(S.app), calls


def _answer(question="How many doors are there?", answer=20, typ="count", method="swiss-count", calib=None):
    return S._speak_remember({"answer": answer, "type": typ, "method": method,
                              "calibration": calib or {"measured": True, "right": 1999, "n": 2000}}, question)


def test_info_probe_success_cache_ledger(tts):
    c, calls = tts
    assert c.get("/api/speak").json()["available"] is True
    assert calls == [{"text": "OK.", "lang": "en", "key": "test-key"}]  # one tiny probe for a key not seen yet
    sid = _answer()
    r = c.post("/api/speak", json={"id": sid})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == MP3
    assert r.headers["x-speak-cache"] == "miss" and r.headers["x-speak-lang"] == "en"
    assert calls[-1]["text"] == "20 doors. Verified by geometry, right 99.95 percent of the time on similar drawings."
    r = c.post("/api/speak", json={"id": sid})  # same sentence: from memory, no second call
    assert r.headers["x-speak-cache"] == "hit" and len(calls) == 2
    rows = [json.loads(x) for x in S.TTS_LEDGER.read_text().splitlines()]
    assert [x["kind"] for x in rows] == ["probe", "speak"]
    assert rows[1]["chars"] == len(calls[-1]["text"]) and rows[1]["cost_usd"] == pytest.approx(
        len(calls[-1]["text"]) * S.TTS_USD_PER_CHAR)
    assert c.get("/api/speak").json()["available"] is True and len(calls) == 2  # no re-probe once it worked


def test_language_and_override(tts):
    c, calls = tts
    sid = _answer("Kuinka monta ovea tässä pohjapiirroksessa on?")
    assert c.post("/api/speak", json={"id": sid}).headers["x-speak-lang"] == "fi"
    assert calls[-1] == {"text": "20 ovea. Varmistettu geometriasta, vastaavissa piirustuksissa oikein yli 99 "
                                 "prosentissa tapauksista.", "lang": "fi", "key": "test-key"}
    c.post("/api/speak", json={"id": sid, "lang": "deu"})  # Scribe's ISO-639-3 code from a voice question
    assert calls[-1]["lang"] == "de" and calls[-1]["text"].startswith("20. Durch Geometrie")


def test_only_known_answers(tts):
    c, calls = tts
    assert c.post("/api/speak", json={"id": "say anything you like"}).status_code == 400
    assert c.post("/api/speak", json={"id": "0123456789abcdef"}).status_code == 404
    assert c.post("/api/speak", json={"text": "free TTS please"}).status_code == 422
    assert calls == []


def test_daily_cap(tts, monkeypatch):
    c, calls = tts
    monkeypatch.setattr(S, "_tts_state", {"ok": True, "checked": 0.0, "key": ""})
    monkeypatch.setattr(S, "TTS_DAILY_CAP", 150 * S.TTS_USD_PER_CHAR)  # room for about one sentence
    assert c.post("/api/speak", json={"id": _answer()}).status_code == 200
    r = c.post("/api/speak", json={"id": _answer(answer=21)})
    assert r.status_code == 429 and "budget" in r.json()["detail"] and len(calls) == 1
    assert c.get("/api/speak").json()["over_cap"] is False  # under the cap, though not by a sentence
    monkeypatch.setattr(S, "TTS_DAILY_CAP", 50 * S.TTS_USD_PER_CHAR)
    assert c.get("/api/speak").json()["over_cap"] is True


def test_rate_limit(tts, monkeypatch):
    c, calls = tts
    monkeypatch.setattr(S, "_tts_state", {"ok": True, "checked": 0.0, "key": ""})
    monkeypatch.setattr(S, "TTS_RATE_N", 2)
    sids = [_answer(answer=n) for n in (3, 4, 5)]
    assert [c.post("/api/speak", json={"id": s}).status_code for s in sids] == [200, 200, 429]
    assert c.post("/api/speak", json={"id": sids[0]}).status_code == 200  # cached: costs nothing, not limited
    assert len(calls) == 2


def test_unavailable_then_recheck(tts, monkeypatch):
    c, calls = tts

    def refuse(text, lang, key):
        calls.append(text)
        raise S.TTSUnavailable('{"status": "missing_permissions"}')

    monkeypatch.setattr(S, "_tts_call", refuse)
    assert c.get("/api/speak").json() == {"available": False}
    assert c.get("/api/speak").json() == {"available": False} and len(calls) == 1  # not re-probed right away
    assert c.post("/api/speak", json={"id": _answer()}).status_code == 503 and len(calls) == 1
    # permission granted later: after TTS_RECHECK_S the next check probes again and the feature comes back
    monkeypatch.setattr(S, "_tts_call", lambda text, lang, key: calls.append(text) or MP3)
    S._tts_state["checked"] -= S.TTS_RECHECK_S + 1
    assert c.get("/api/speak").json()["available"] is True and len(calls) == 2
    assert c.post("/api/speak", json={"id": _answer()}).status_code == 200


def test_upstream_errors_keep_feature(tts, monkeypatch):
    c, calls = tts
    monkeypatch.setattr(S, "_tts_state", {"ok": True, "checked": 0.0, "key": ""})

    def busy(*a):
        raise HTTPException(504, "text-to-speech timed out")
    monkeypatch.setattr(S, "_tts_call", busy)
    assert c.post("/api/speak", json={"id": _answer()}).status_code == 504
    assert c.get("/api/speak").json()["available"] is True


def test_no_key(tts, monkeypatch):
    c, calls = tts
    monkeypatch.setattr(S, "_tts_key", lambda: "")
    assert c.get("/api/speak").json() == {"available": False}
    assert c.post("/api/speak", json={"id": _answer()}).status_code == 503 and calls == []


# ---------------------------------------------------------------- the sentences
@pytest.mark.parametrize("q,lang,start", [
    ("How many windows are shown on this floor plan?", "en", "7 windows."),
    ("Kuinka monta ikkunaa tässä pohjapiirroksessa on?", "fi", "7 ikkunaa."),
    ("Wie viele Fenster gibt es auf diesem Grundriss?", "de", "7 Fenster."),
    ("Combien de fenêtres y a-t-il sur ce plan ?", "fr", "7 fenêtres."),
    ("Quante finestre ci sono nella pianta?", "it", "7 finestre."),
    ("Hoeveel ramen zijn er op deze plattegrond?", "nl", "7 ramen."),
    ("Hur många fönster finns det på ritningen?", "sv", "7 fönster."),
])
def test_sentence_languages(q, lang, start):
    assert SP.detect_lang(q) == lang
    s = SP.sentence({"question": q, "answer": 7, "type": "count", "method": "cubicasa-yolo"}, lang)
    assert s.startswith(start) and len(s) < 150


def test_sentence_kinds():
    area = SP.sentence({"answer": 15.47, "type": "area", "method": "swiss-area"}, "de")
    assert area == "15,47 Quadratmeter. Durch Geometrie geprüft."
    assert SP.sentence({"answer": None, "type": "count"}, "fi") == "En ole varma, joten en arvaa."
    one = SP.sentence({"question": "How many doors?", "answer": 1, "type": "count", "method": "swiss"}, "en")
    assert one.startswith("1. ")  # no plural noun after one
    txt = SP.sentence({"answer": "**Anna Virtanen**, Helsinki. Drawn in 2019 by [x](https://e.vil)\n- more",
                       "type": "text", "method": "generic-text"}, "en")
    assert txt == "Anna Virtanen, Helsinki. Answered by an AI model; check the marks on the drawing."
    long = SP.sentence({"answer": "word " * 200, "type": "text", "method": "generic-text"}, "en")
    assert len(long) < S.TTS_MAX_CHARS
    cc = SP.sentence({"answer": 5, "type": "count", "method": "swiss", "crosscheck": {"status": "conflict"}}, "en")
    assert "disagree" in cc


# ---------------------------------------------------------------- HEAD on pages, and the ask limit
@pytest.mark.parametrize("url", ["/", "/results", "/static/app.js"])
def test_head(url):
    r = TestClient(S.app).head(url)
    assert r.status_code == 200 and r.content == b""


def test_ask_limit_counts_only_paid(monkeypatch):
    c = TestClient(S.app)
    path = next(iter(S.BY_PATH))
    cost = {"usd": 0.0}
    monkeypatch.setattr(S, "_run_router", lambda q, timeout=0: {
        "answer": 3, "confidence": 0.9, "evidence": [], "method": "swiss-count", "cost_usd": cost["usd"], "route": "x"})
    monkeypatch.setattr(S, "RATE_N", 2)
    monkeypatch.setattr(S, "RATE_S", 600)
    monkeypatch.setattr(S, "FREE_ASK_N", 7)
    monkeypatch.setattr(S, "_hits", _fresh(S._hits))
    monkeypatch.setattr(S, "_free_hits", _fresh(S._free_hits))
    q = S.BY_PATH[path][0]["question"]
    ask = lambda: c.post("/api/ask", json={"path": path, "question": q}).status_code  # noqa: E731
    assert [ask() for _ in range(4)] == [200] * 4  # $0 answers: the tour does not use up the questions
    cost["usd"] = 0.01
    assert [ask(), ask(), ask()] == [200, 200, 429]  # two paid answers, then the paid limit
    cost["usd"] = 0.0
    monkeypatch.setattr(S, "_hits", _fresh(S._hits))
    assert [ask(), ask()] == [200, 429]  # the free allowance (7) still bounds CPU
