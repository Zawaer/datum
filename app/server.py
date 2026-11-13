"""Demo server: pick a drawing, ask in any language, get the answer with its evidence.

    .venv/bin/python -m uvicorn app.server:app --host 0.0.0.0 --port 3123
"""
from __future__ import annotations

import collections
import functools
import io
import json
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from bp.data import data_root, load_questions
from bp.router import Router, guess_type

ROOT = data_root()
STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Blueprints that talk")
router = Router()

QUESTIONS = load_questions()
BY_PATH: dict[str, list] = collections.defaultdict(list)
for _q in QUESTIONS:
    BY_PATH[_q["path"]].append(_q)
VIEWABLE = (".png", ".jpg", ".jpeg", ".pdf")


def _baseline_cost_per_q() -> dict:
    """Mean frontier cost per question by source, from our own baseline run."""
    out, n = collections.defaultdict(float), collections.Counter()
    for f in sorted(Path("runs").glob("baseline_*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            out[r["source"]] += r["cost_usd"]
            n[r["source"]] += 1
    tot = sum(out.values()) / max(1, sum(n.values()))
    return {k: out[k] / n[k] for k in n} | {"_all": tot}


BASELINE_COST = _baseline_cost_per_q()


@functools.lru_cache(maxsize=64)
def credit_for(path: str) -> str:
    src = path.split("/")[1]
    lic = ROOT / "data" / src / "LICENSE.md"
    if not lic.exists():
        return ""
    name = Path(path).name
    stem = Path(path).stem.split("_plan-")[0]
    lines = lic.read_text().splitlines()
    for ln in lines:
        if name in ln or (stem and stem in ln):
            return ln.strip("-* ")
    for ln in lines:
        if ln.startswith("All files:"):
            return ln[len("All files:"):].strip()
    return f"see data/{src}/LICENSE.md"


def view_path(path: str) -> str | None:
    """The file we render for a question's drawing (IFC -> a rendered plan if there is one)."""
    p = ROOT / path
    if p.suffix.lower() in VIEWABLE:
        return path
    for ext in (".pdf", ".png", ".jpg"):
        if p.with_suffix(ext).exists():
            return str(Path(path).with_suffix(ext))
    plans = sorted(p.parent.glob(p.stem + "_plan-*.pdf"))
    return str(plans[0].relative_to(ROOT)) if plans else None


@app.get("/api/drawings")
def drawings():
    out = []
    for path, qs in BY_PATH.items():
        src = qs[0]["source"]
        if src not in ("swiss_dwellings", "cubicasa5k", "ifc_models", "ifc_bench"):
            continue
        out.append({"path": path, "source": src, "ext": qs[0]["ext"], "n": len(qs), "split": qs[0]["split"],
                    "view": view_path(path)})
    order = {"swiss_dwellings": 0, "cubicasa5k": 1, "ifc_models": 2, "ifc_bench": 3}
    out.sort(key=lambda d: (order[d["source"]], d["split"] != "test", d["path"]))
    return out


@app.get("/api/questions")
def questions(path: str):
    qs = BY_PATH.get(path)
    if not qs:
        raise HTTPException(404)
    return {"path": path, "view": view_path(path), "credit": credit_for(path),
            "questions": [{"question": q["question"], "type": q["type"], "answer": q["answer"]} for q in qs]}


@functools.lru_cache(maxsize=128)
def _render(path: str, page: int, dpi: int) -> bytes:
    p = ROOT / path
    if not p.resolve().is_relative_to(ROOT.resolve()) or not p.exists():
        raise HTTPException(404)
    if p.suffix.lower() == ".pdf":
        import pymupdf

        with pymupdf.open(p) as doc:
            return doc[page].get_pixmap(dpi=dpi).tobytes("png")
    return p.read_bytes()


@app.get("/api/render")
def render(path: str, page: int = 0, dpi: int = 130):
    data = _render(path, page, min(dpi, 220))
    mt = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    return Response(data, media_type=mt, headers={"Cache-Control": "max-age=3600"})


@app.get("/api/file")
def raw_file(path: str):
    p = (ROOT / path).resolve()
    if not p.is_relative_to(ROOT.resolve()) or not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


class Ask(BaseModel):
    path: str
    question: str


@app.post("/api/ask")
def ask(req: Ask):
    qs = BY_PATH.get(req.path)
    if not qs:
        raise HTTPException(404, "unknown drawing")
    known = next((q for q in qs if q["question"].strip() == req.question.strip()), None)
    q = dict(known) if known else {**qs[0], "question": req.question, "type": guess_type(req.question),
                                    "answer": None, "id": None}
    t0 = time.time()
    res = router(q)
    res["latency_s"] = round(time.time() - t0, 3)
    res["type"] = q["type"]
    res["gold"] = known["answer"] if known else None
    res["baseline_cost_usd"] = BASELINE_COST.get(q["source"], BASELINE_COST.get("_all", 0.0))
    res.pop("raw", None)
    return res


@app.get("/api/stats")
def stats():
    """Latest eval summaries for the scoreboard panel."""
    out = {}
    for f in sorted(Path("runs").glob("*_test*.summary.md")):
        txt = f.read_text()
        m = re.search(r"\| \*\*ALL\*\* \| (\d+) \| (\d+)% \| ([\d.]+)% \| [^|]+ \| ([\d.]+) \|", txt)
        if m:
            out[f.name.replace(".summary.md", "")] = {"n": int(m.group(1)), "accuracy": float(m.group(3)),
                                                      "usd_per_1k": float(m.group(4))}
    return out


@app.get("/")
def index():
    return HTMLResponse((STATIC / "index.html").read_text())


@app.get("/static/{name}")
def static(name: str):
    p = (STATIC / name).resolve()
    if not p.is_relative_to(STATIC.resolve()) or not p.exists():
        raise HTTPException(404)
    return FileResponse(p)
