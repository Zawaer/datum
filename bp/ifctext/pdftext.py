"""Free-text questions on vector PDFs (opening_design schedules): text layer -> cheap LLM -> cited boxes.

The page's words are grouped into layout segments with ids (bp.generic.text); the model answers in a
short phrase from those segments only and lists the ids it read; each cited segment becomes a `text`
evidence box on the page.
"""
from __future__ import annotations

import hashlib
import json
import re

from bp.data import data_root
from bp.generic import text as T
from bp.ifctext.llm import ask
from bp.solvers.ifctext import CACHE

SYSTEM = """You read construction drawing sheets (schedules, legends, notes) from their text layer. The text \
is given one baseline row per line as "y=<% from top>: [id]@<x %> text   [id]@<x %> text ..."; table columns \
are separated by " | " inside a segment, and a table row is spread over the segments on one line.

Answer the question from this text only. Reply in two lines:
ANSWER: <short answer, as written on the sheet, e.g. 5'-10 3/8" or "B3 (aluminium sliding door)"; when the \
question asks what a code means, give the code and its meaning from the legend; when it asks for several \
values give all of them>
SEGS: <ids of the segments the answer was read from, comma separated: the table cells and the legend entries>"""

VERSION = "p1"


def answer_pdf(q: dict, model: str = "haiku", budget: int = 40000) -> dict:
    path = str(data_root() / q["path"])
    pages = T.pick_pages(path, q["question"], k=1)
    segs, nid = [], 0
    for p in pages:
        ss, _ = T.layout(path, p)
        for s in ss:
            segs.append(T.Segment(nid, s.page, s.bbox, s.cells, s.row))
            nid += 1
    if sum(len(s.text) for s in segs) < 40:
        return {"answer": None, "confidence": 0.0, "method": "pdftext", "cost_usd": 0.0, "evidence": [],
                "explanation": "no text layer"}
    shown = T.relevant(segs, q["question"], budget)
    prompt = f"SHEET TEXT:\n{T.to_prompt(shown)}\n\nQUESTION: {q['question']}"
    key = hashlib.sha1(json.dumps([VERSION, model, SYSTEM, prompt]).encode()).hexdigest()
    f = CACHE / f"{key[:2]}/{key}.json"
    if f.exists():
        res = json.loads(f.read_text())
        res["cost_usd"] = 0.0
    else:
        res = ask(prompt, SYSTEM, model, tag="pdftext")
        if not res.get("error"):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(res))
    txt = res.get("text") or ""
    m = re.search(r"ANSWER:\s*(.+)", txt)
    ans = m.group(1).strip() if m else (txt.strip().splitlines() or [None])[0]
    ids = [int(x) for x in re.findall(r"\d+", (re.search(r"SEGS:\s*(.*)", txt) or [None, ""])[1] or "")]
    by = {s.id: s for s in segs}
    ev = []
    for i in dict.fromkeys(ids):
        s = by.get(i)
        if s is None:
            continue
        ev.append({"kind": "text", "file": q["path"], "page": s.page, "bbox": [round(x, 5) for x in s.bbox],
                   "label": f"read: '{s.text[:80]}'"})
    return {"answer": ans, "confidence": 0.6 if ev else 0.3, "method": f"pdftext-{model}",
            "cost_usd": res.get("cost_usd", 0.0), "evidence": ev,
            "explanation": f"{model} read the answer from {len(ev)} text segments of the sheet"}
