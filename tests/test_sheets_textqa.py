"""bp/sheets/textqa.py: the model's reading is cached with the upload, so the same question on the same file
gives the same answer without a second call."""
from bp.generic import llm
from bp.sheets import textqa


def test_reading_cached_per_upload(tmp_path, monkeypatch):
    img = tmp_path / "sheet.png"
    img.write_bytes(b"x")
    lines = [{"text": "TOTAL FIRST FLOOR = 28,770 SF", "bbox": [0.7, 0.6, 0.9, 0.61]}]
    meta = {"image": str(img), "w": 2000, "h": 1400, "_lines": lines}
    calls = []

    def fake(prompt, **kw):
        calls.append(prompt)
        return {"text": '{"op": "read", "items": [{"ids": [0], "value": "28,770", "what": "total"}], '
                        '"answer": 28770, "unit": "SF", "confidence": "high", "explanation": "printed"}',
                "cost_usd": 0.001}

    monkeypatch.setattr(llm, "ask", fake)
    a = textqa.answer(meta, "What is the total first floor area?")
    b = textqa.answer(dict(meta), "What is the total first floor area?")
    assert a["answer"] == b["answer"] and len(calls) == 1
