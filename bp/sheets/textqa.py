"""Questions answered from the words printed on a raster sheet (tables, schedules, notes, dimension strings).

The sheet is OCR'd once (tesseract, bp.sheets.ocr_words; cached in meta) and its lines are listed with ids and
positions; Claude Haiku answers by citing line ids (like the generic text path, bp/solvers/generic.py), and sums
are recomputed here from the values it read, so every number in the answer is a text box on the drawing.
"""
from __future__ import annotations

import re

from bp import sheets

PROMPT = """Question about a construction drawing: {question}
Below are the text lines read (OCR) from the sheet, one per line: "[id] (x%, y%) text". OCR may garble a few
characters (e.g. "2911" for "2,911", "O" for "0"). Tables print one row per line: label then value.

{lines}

Answer from these lines only. Reply with JSON:
{{"op": "read" | "sum" | "count" | "none",
  "items": [{{"ids": [<line ids>], "value": <number as printed, or the text read>, "what": "<row label>"}}],
  "answer": <final answer, a number for read/sum/count of numbers, else short text as printed>,
  "unit": "<unit as printed, e.g. SF, m2, mm, or ''>",
  "confidence": "high" | "medium" | "low", "explanation": "<one line>"}}
Rules:
- "read": the answer is printed (a table cell, a total row, a note, a dimension): cite the line(s) it is on.
  Prefer a printed TOTAL row over adding rows yourself when the question asks for that total.
- "sum": the question asks for a total that is not printed: one item per number added (value = that number).
- "count": one item per counted line.
- "none": the text does not answer it (e.g. the question is about drawn symbols, or a room not listed).
"""


def _layout(meta, scale):
    words = sheets.ocr_words(meta, scale=scale, min_conf=20)
    lines = sheets.ocr_lines(words)
    lines = [ln for ln in lines if re.search(r"[A-Za-z0-9]{2,}", ln["text"])]
    return lines


def answer(meta, question: str, model: str = "haiku", max_lines: int = 700) -> dict | None:
    from bp.generic import llm

    scale = 2.0 if max(meta.get("w", 0), meta.get("h", 0)) < 3000 else 1.0
    lines = meta.get("_lines")
    if lines is None:
        lines = meta["_lines"] = _layout(meta, scale)
    if not lines:
        return None
    use = lines[:max_lines]
    txt = "\n".join(f"[{i}] ({100 * ln['bbox'][0]:.0f}%, {100 * ln['bbox'][1]:.0f}%) {ln['text']}"
                    for i, ln in enumerate(use))
    r = llm.ask(PROMPT.format(question=question, lines=txt), model=model, tag="sheets-textqa", timeout=90)
    d = llm.parse_json(r["text"]) or {}
    cost = r.get("cost_usd", 0.0)
    if not isinstance(d, dict) or d.get("op") in (None, "none") or d.get("answer") in (None, ""):
        return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": cost, "method": "sheets-text-none",
                "explanation": (d.get("explanation") if isinstance(d, dict) else None) or "not in the sheet's text"}
    ev, vals = [], []
    for it in d.get("items") or []:
        ids = [i for i in it.get("ids") or [] if isinstance(i, int) and 0 <= i < len(use)]
        if not ids:
            continue
        bb = [min(use[i]["bbox"][0] for i in ids), min(use[i]["bbox"][1] for i in ids),
              max(use[i]["bbox"][2] for i in ids), max(use[i]["bbox"][3] for i in ids)]
        v = it.get("value")
        vals.append(_num(v))
        ev.append({"kind": "text", "bbox": [bb[0] - 0.002, bb[1] - 0.002, bb[2] + 0.002, bb[3] + 0.002],
                   "label": f"read: '{' '.join(use[i]['text'] for i in ids)[:80]}'",
                   "value": _num(v) if d["op"] in ("sum", "count") else None})
    ans = d.get("answer")
    unit = (d.get("unit") or "").strip()
    expl = d.get("explanation") or ""
    if d["op"] == "sum" and vals and all(v is not None for v in vals):
        s = sum(vals)
        ans = int(s) if abs(s - round(s)) < 1e-9 else round(s, 2)
        expl = " + ".join(f"{_fmt(v)}" for v in vals) + f" = {_fmt(s)}" + (f" {unit}" if unit else "") + \
            (f" ({expl})" if expl else "")
    elif d["op"] == "count":
        ans = len(ev)
    if isinstance(ans, str) and unit and re.fullmatch(r"[\d,.\s]+", ans):
        ans = _num(ans)
    conf = {"high": 0.8, "medium": 0.6, "low": 0.3}.get(d.get("confidence"), 0.5)
    if not ev:
        conf *= 0.5
    # every number in a read answer should be on a cited line (OCR-checked), else it is a guess
    if d["op"] == "read" and ev and _num(ans) is not None:
        cited = " ".join(e["label"] for e in ev).replace(",", "")
        if not re.search(re.escape(f"{_num(ans):g}"), cited):
            conf *= 0.6
    shown = f"{_fmt(ans)} {unit}".strip() if isinstance(ans, (int, float)) else ans
    if isinstance(ans, (int, float)) and unit and unit.lower() not in ("m2", "m²", "sq m", "m", "sqm"):
        ans = f"{_fmt(ans):,} {unit}" if isinstance(_fmt(ans), int) else f"{ans} {unit}"  # the UI assumes m² for numbers
    return {"answer": ans if not isinstance(ans, (int, float)) else _fmt(ans), "unit": unit,
            "display": shown, "confidence": round(conf, 3), "evidence": ev, "cost_usd": cost,
            "method": f"sheets-text-{d['op']}", "explanation": f"read from the sheet's printed text: {expl}"}


def _num(x):
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(x))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _fmt(v):
    if isinstance(v, float) and abs(v - round(v)) < 1e-9:
        return int(round(v))
    return v
