"""POST/GET /api/transcribe (ask by voice) with a stubbed ElevenLabs call: no network, no key, no spend."""
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # fastapi.testclient needs it

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.server as S  # noqa: E402

WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 4000
OGG = b"OggS" + b"\x00" * 4000


@pytest.fixture
def stt(monkeypatch, tmp_path):
    calls = []

    def fake(audio, kind, lang, key):
        calls.append({"bytes": len(audio), "kind": kind, "lang": lang, "key": key})
        return {"text": "How many doors are on this floor plan? (laughter)", "language_code": "eng",
                "language_probability": 0.99, "audio_duration_secs": 3.0}

    monkeypatch.setattr(S, "_stt_call", fake)
    monkeypatch.setattr(S, "_stt_key", lambda: "test-key")
    monkeypatch.setattr(S, "STT_DAILY_CAP", 2.0)
    monkeypatch.setattr(S, "STT_LEDGER", tmp_path / "stt_spend.jsonl")
    monkeypatch.setattr(S, "RATE_N", 0)
    return TestClient(S.app), calls


def test_info_and_ok(stt):
    c, calls = stt
    assert c.get("/api/transcribe").json()["available"] is True
    r = c.post("/api/transcribe?lang=fi-FI&secs=3", content=WEBM, headers={"content-type": "audio/webm"})
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "How many doors are on this floor plan?" and r.json()["language"] == "eng"
    assert calls == [{"bytes": len(WEBM), "kind": "webm", "lang": "fi", "key": "test-key"}]
    rec = json.loads(S.STT_LEDGER.read_text().splitlines()[0])
    assert rec["audio_s"] == 3.0 and rec["cost_usd"] == pytest.approx(3 * S.STT_USD_PER_S, abs=1e-7)
    r = c.post("/api/transcribe?lang=auto&secs=2", content=OGG)  # no / bogus hint -> detect
    assert r.status_code == 200 and calls[-1]["lang"] is None and calls[-1]["kind"] == "ogg"


def test_rejects(stt):
    c, calls = stt
    assert c.post("/api/transcribe?secs=3", content=b"RIFF" + b"\x00" * 4000).status_code == 415
    assert c.post("/api/transcribe?secs=3", content=b"").status_code == 400
    assert c.post("/api/transcribe?secs=3", content=WEBM[:4] + b"\x00" * (S.STT_MAX_BYTES + 1)).status_code == 413
    assert c.post("/api/transcribe?secs=61", content=WEBM).status_code == 413
    assert calls == []


def test_no_key(stt, monkeypatch):
    c, calls = stt
    monkeypatch.setattr(S, "_stt_key", lambda: "")
    assert c.get("/api/transcribe").json() == {"available": False}
    assert c.post("/api/transcribe?secs=3", content=WEBM).status_code == 503 and calls == []


def test_daily_cap(stt, monkeypatch):
    c, calls = stt
    monkeypatch.setattr(S, "STT_DAILY_CAP", 9 * S.STT_USD_PER_S)  # budget for 9 s of audio
    assert c.post("/api/transcribe?secs=3", content=WEBM).status_code == 200
    assert c.post("/api/transcribe?secs=3", content=WEBM).status_code == 200
    r = c.post("/api/transcribe?secs=5", content=WEBM)
    assert r.status_code == 429 and "budget" in r.json()["detail"] and len(calls) == 2
    assert c.get("/api/transcribe").json()["over_cap"] is False  # 6 s spent < 9 s: still on for short clips


def test_rate_limit_and_upstream_error(stt, monkeypatch):
    c, calls = stt
    monkeypatch.setattr(S, "RATE_N", 1)
    monkeypatch.setattr(S, "RATE_S", 600)
    monkeypatch.setattr(S, "_hits", type(S._hits)(S._hits.default_factory))
    assert c.post("/api/transcribe?secs=1", content=WEBM).status_code == 200
    assert c.post("/api/transcribe?secs=1", content=WEBM).status_code == 429
    monkeypatch.setattr(S, "RATE_N", 0)

    def boom(*a):
        raise HTTPException(504, "speech-to-text timed out; please try again or type the question")
    monkeypatch.setattr(S, "_stt_call", boom)
    assert c.post("/api/transcribe?secs=1", content=WEBM).status_code == 504
