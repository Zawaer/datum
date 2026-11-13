"""Demo server: pick (or upload) a drawing, ask in any language, get the answer with its evidence.

    .venv/bin/python -m uvicorn app.server:app --host 0.0.0.0 --port 3123
"""
from __future__ import annotations

import collections
import concurrent.futures as cf
import datetime
import functools
import hashlib
import json
import os
import re
import threading
import time
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from bp.data import data_root, load_questions
from bp.router import Router, guess_type

ROOT = data_root()
APP = Path(__file__).parent
STATIC = APP / "static"
RUNS = Path("runs")
UPLOADS = Path("cache/uploads")
app = FastAPI(title="Blueprints that talk")
router = Router()

QUESTIONS = load_questions()
BY_PATH: dict[str, list] = collections.defaultdict(list)
for _q in QUESTIONS:
    BY_PATH[_q["path"]].append(_q)
VIEWABLE = (".png", ".jpg", ".jpeg", ".pdf")
SOURCES = ["swiss_dwellings", "cubicasa5k", "ifc_models", "ifc_bench", "opening_design"]
DRAWINGS: list[dict] = []
SOLVER_TIMEOUT_S = 120
FALLBACK_TIMEOUT_S = 75
_pool = cf.ThreadPoolExecutor(8)

# ---------------------------------------------------------------- public-demo settings (all off unless set)
# BP_ROOT_PATH       serve under a sub-path behind a proxy that strips it (e.g. Caddy handle_path): page and
#                    script URLs get the prefix, so the app works at https://host/<prefix>/
# BP_RATE_LIMIT      "<n>/<seconds>" asks + uploads per client IP (X-Forwarded-For from the proxy), e.g. 30/600
# BP_DAILY_USD_CAP   daily budget for paid model calls; BP_SPEND_LEDGER is the JSONL file the capped model CLI
#                    (deploy/claude-capped) appends {"day", "cost_usd"} to and refuses calls from once it's hit
ROOT_PATH = os.environ.get("BP_ROOT_PATH", "").rstrip("/")
_RL = os.environ.get("BP_RATE_LIMIT", "")
RATE_N, RATE_S = (int(x) for x in _RL.split("/")) if _RL else (0, 0)
DAILY_CAP = float(os.environ.get("BP_DAILY_USD_CAP", 0) or 0)
LEDGER = Path(os.environ["BP_SPEND_LEDGER"]) if os.environ.get("BP_SPEND_LEDGER") else None
_hits: dict[str, collections.deque] = collections.defaultdict(collections.deque)
_hits_lock = threading.Lock()


def _rate_limit(request: Request):
    if not RATE_N:
        return
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or \
        (request.client.host if request.client else "?")
    now = time.time()
    with _hits_lock:
        dq = _hits[ip]
        while dq and dq[0] < now - RATE_S:
            dq.popleft()
        if len(dq) >= RATE_N:
            raise HTTPException(429, f"this public demo allows {RATE_N} questions per {RATE_S // 60} minutes "
                                     "per visitor; please try again in a few minutes")
        dq.append(now)


def spent_today() -> float:
    if LEDGER is None or not LEDGER.exists():
        return 0.0
    day, tot = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"), 0.0
    for line in LEDGER.read_text().splitlines():
        try:
            r = json.loads(line)
            tot += float(r.get("cost_usd") or 0) if r.get("day") == day else 0.0
        except (ValueError, AttributeError):
            continue
    return tot


def _with_root(text: str) -> str:
    """Prefix root-relative app URLs in a page or script with BP_ROOT_PATH."""
    if not ROOT_PATH:
        return text
    text = re.sub(r"""(["'`])/(api/|static/|results\b)""", lambda m: f"{m.group(1)}{ROOT_PATH}/{m.group(2)}", text)
    text = text.replace('href="/"', f'href="{ROOT_PATH}/"')
    text = re.sub(r'<meta (?:property|name)="(?:og|twitter):[^>]*>\n?', "", text)  # no link previews of a private URL
    shim = (f'<meta name="robots" content="noindex, nofollow"><meta name="referrer" content="no-referrer">'
            f'<script>window.BP_ROOT={json.dumps(ROOT_PATH)};(f=>{{window.fetch=(u,o)=>f(typeof u==="string"'
            f'&&u.startsWith("/api/")?window.BP_ROOT+u:u,o)}})(window.fetch.bind(window));</script>')
    return text.replace("<head>", "<head>" + shim, 1)


# ---------------------------------------------------------------- helpers

def _baseline_per_q(field: str) -> dict:
    """Mean frontier cost / latency per question by source, from our own baseline run(s)."""
    out, n = collections.defaultdict(float), collections.Counter()
    for f in sorted(RUNS.glob("baseline_*.jsonl")):
        for line in open(f):
            try:
                r = json.loads(line)
                out[r["source"]] += float(r.get(field) or 0)
                n[r["source"]] += 1
            except (ValueError, KeyError):
                continue
    tot = sum(out.values()) / max(1, sum(n.values()))
    return {k: out[k] / n[k] for k in n} | {"_all": tot}


BASELINE_COST = _baseline_per_q("cost_usd")
BASELINE_LATENCY = _baseline_per_q("latency_s")


@functools.lru_cache(maxsize=256)
def credit_for(path: str) -> str:
    if path.startswith("uploads/"):
        return "your upload (stays on this server, not shared)"
    src = path.split("/")[1]
    lic = ROOT / "data" / src / "LICENSE.md"
    if not lic.exists():
        return ""
    name = Path(path).name
    stem = Path(path).stem.split("_plan-")[0]
    lines = lic.read_text().splitlines()
    for ln in lines:
        if name in ln or (stem and stem in ln):
            if ln.lstrip().startswith("|"):  # table row: | file | title | licence | credit | url |
                cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                if len(cells) >= 4:
                    return f"{cells[1]} · {cells[2]} · {cells[3]}"
                return " · ".join(c for c in cells[1:] if c)
            return ln.strip("-* ")
    for ln in lines:
        if ln.startswith("All files:"):
            return ln[len("All files:"):].strip()
    return f"see data/{src}/LICENSE.md"


def resolve(path: str) -> Path:
    """Client path -> file on disk (dataset or upload), refusing anything outside those roots."""
    if path.startswith("uploads/"):
        p = (UPLOADS / path[len("uploads/"):]).resolve()
        if not p.is_relative_to(UPLOADS.resolve()):
            raise HTTPException(404)
        return p
    p = (ROOT / path).resolve()
    if not p.is_relative_to(ROOT.resolve()):
        raise HTTPException(404)
    return p


def view_path(path: str) -> str | None:
    """The file we render for a drawing (IFC -> a rendered plan if there is one; DXF upload -> its PNG)."""
    p = resolve(path)
    if p.suffix.lower() in VIEWABLE:
        return path
    if path.startswith("uploads/"):
        if p.suffix.lower() == ".dxf" and (p.parent / (p.name + ".png")).exists():
            return path + ".png"
        return None
    for ext in (".pdf", ".png", ".jpg"):
        if p.with_suffix(ext).exists():
            return str(Path(path).with_suffix(ext))
    plans = sorted(p.parent.glob(p.stem + "_plan-*.pdf"))
    return str(plans[0].relative_to(ROOT.resolve())) if plans else None


def ifc_for(path: str) -> Path | None:
    p = resolve(path)
    if p.suffix.lower() == ".ifc":
        return p
    if path.startswith("uploads/"):
        return None
    model = p.parent / (p.stem.split("_plan-")[0] + ".ifc")
    return model if model.exists() else None


def _abstain(msg: str, **kw) -> dict:
    return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": "none",
            "explanation": msg, "route": "-", **kw}


# ---------------------------------------------------------------- drawings

def _build_drawings():
    for path, qs in BY_PATH.items():
        src = qs[0]["source"]
        if src not in SOURCES:
            continue
        DRAWINGS.append({"path": path, "source": src, "ext": qs[0]["ext"], "n": len(qs), "split": qs[0]["split"]})
    DRAWINGS.sort(key=lambda d: (SOURCES.index(d["source"]), d["split"] != "test", d["path"]))


_build_drawings()


@app.get("/api/drawings")
def drawings(source: str | None = None, q: str = "", offset: int = 0, limit: int = 80):
    """Paged drawing list (the full dataset has thousands); counts per source for the tabs."""
    counts = collections.Counter(d["source"] for d in DRAWINGS)
    sel = [d for d in DRAWINGS if (source is None or d["source"] == source) and q.lower() in d["path"].lower()]
    return {"counts": {s: counts[s] for s in SOURCES if counts[s]}, "total": len(sel),
            "items": sel[offset:offset + limit]}


@app.get("/api/questions")
def questions(path: str):
    if path.startswith("uploads/"):
        if not resolve(path).exists():
            raise HTTPException(404, "upload not found (uploads are cleared when the server is rebuilt)")
        meta = _upload_meta(path)
        return {"path": path, "view": view_path(path), "credit": credit_for(path), "has3d": ifc_for(path) is not None,
                "kind": meta.get("kind"), "questions": [{"question": s, "type": guess_type(s), "answer": None}
                                                         for s in _upload_suggestions(meta.get("kind"))]}
    qs = BY_PATH.get(path)
    if not qs:
        raise HTTPException(404)
    seen, out = set(), []
    for q in qs:  # dedupe identical question text
        if q["question"] in seen:
            continue
        seen.add(q["question"])
        out.append({"question": q["question"], "type": q["type"], "answer": q["answer"]})
    return {"path": path, "view": view_path(path), "credit": credit_for(path), "has3d": ifc_for(path) is not None,
            "source": qs[0]["source"], "split": qs[0]["split"], "questions": out[:120]}


# ---------------------------------------------------------------- rendering

@functools.lru_cache(maxsize=128)
def _render(path: str, page: int, dpi: int) -> bytes:
    p = resolve(path)
    if not p.exists():
        raise HTTPException(404)
    if p.suffix.lower() == ".pdf":
        import pymupdf

        with pymupdf.open(p) as doc:
            if page >= len(doc):
                raise HTTPException(404, "no such page")
            pg = doc[page]
            # keep big sheets within a sane pixel budget
            w, h = pg.rect.width / 72 * dpi, pg.rect.height / 72 * dpi
            if w * h > 5000 * 5000:
                dpi = int(dpi * (5000 * 5000 / (w * h)) ** 0.5)
            return pg.get_pixmap(dpi=dpi).tobytes("png")
    return p.read_bytes()


@app.get("/api/render")
def render(path: str, page: int = 0, dpi: int = 130):
    try:
        data = _render(path, page, min(dpi, 220))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"could not render: {e}") from e
    mt = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    return Response(data, media_type=mt, headers={"Cache-Control": "max-age=3600"})


@app.get("/api/mesh")
def mesh(path: str):
    from app.mesh import mesh_bytes

    ifc = ifc_for(path)
    if ifc is None:
        raise HTTPException(404, "no IFC model for this drawing")
    try:
        data = mesh_bytes(ifc)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"could not tessellate the model: {e}") from e
    return Response(data, media_type="application/json",
                    headers={"Content-Encoding": "gzip", "Cache-Control": "max-age=3600"})


@app.get("/api/file")
def raw_file(path: str):
    p = resolve(path)
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


# ---------------------------------------------------------------- uploads

UPLOAD_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".dxf", ".ifc"}
MAX_UPLOAD = 200 * 1024 * 1024


def _upload_meta(path: str) -> dict:
    p = resolve(path)
    m = p.parent / "meta.json"
    return json.loads(m.read_text()) if m.exists() else {}


def _upload_suggestions(kind: str | None) -> list[str]:
    if kind == "ifc":
        return ["How many doors are in the model?", "How many windows are in the model?",
                "What is the total length of all walls, in metres?", "How many storeys does the building have?",
                "What is the total floor area of all spaces, in m²?"]
    return ["How many doors are shown on this floor plan?", "How many windows are shown on this floor plan?",
            "How many rooms are there?", "What is the total floor area, in m²?"]


def _classify(p: Path) -> str:
    ext = p.suffix.lower()
    if ext == ".ifc":
        return "ifc"
    if ext == ".dxf":
        return "dxf"
    if ext in (".png", ".jpg", ".jpeg"):
        return "raster"
    import pymupdf

    with pymupdf.open(p) as doc:
        pg = doc[0]
        vector = len(pg.get_drawings()) > 200 or len(pg.get_text("words")) > 30
    return "pdf-vector" if vector else "pdf-raster"


def _render_dxf(src: Path, out: Path):
    """DXF -> PNG of the modelspace extents, no margins, so evidence normalised to the extents lines up."""
    import ezdxf
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf import bbox
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    doc = ezdxf.readfile(src)
    msp = doc.modelspace()
    ext = bbox.extents(msp, fast=True)
    (x0, y0, _), (x1, y1, _) = ext.extmin, ext.extmax
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    scale = 2400 / max(w, h)
    fig = plt.figure(figsize=(w * scale / 100, h * scale / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(msp, finalize=False)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("auto")
    fig.patch.set_facecolor("white")
    fig.savefig(out, dpi=100, facecolor="white")
    plt.close(fig)
    meta = out.parent / "meta.json"
    m = json.loads(meta.read_text()) if meta.exists() else {}
    m["dxf_extents"] = [x0, y0, x1, y1]
    meta.write_text(json.dumps(m))


@app.post("/api/upload")
async def upload(request: Request, name: str):
    """Raw-body upload (no multipart dependency): POST /api/upload?name=plan.pdf with the file as body."""
    _rate_limit(request)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name)[-80:] or "drawing"
    ext = Path(safe).suffix.lower()
    if ext not in UPLOAD_EXT:
        raise HTTPException(415, f"unsupported file type {ext or '?'}: use PDF, PNG, JPG, DXF or IFC")
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty file")
    if len(body) > MAX_UPLOAD:
        raise HTTPException(413, "file too large (max 200 MB)")
    key = hashlib.sha1(body).hexdigest()[:12]
    d = UPLOADS / key
    d.mkdir(parents=True, exist_ok=True)
    p = d / safe
    if not p.exists():
        p.write_bytes(body)
    try:
        kind = _classify(p)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"could not read this file as {ext.lstrip('.').upper()}: it may be damaged or "
                                 f"not really a {ext.lstrip('.').upper()} ({type(e).__name__})") from e
    meta = d / "meta.json"
    m = json.loads(meta.read_text()) if meta.exists() else {}
    m.update({"name": safe, "kind": kind, "bytes": len(body), "uploaded": time.time()})
    meta.write_text(json.dumps(m))
    if kind == "dxf" and not (d / (safe + ".png")).exists():
        try:
            _render_dxf(p, d / (safe + ".png"))
        except Exception as e:  # noqa: BLE001
            m["render_error"] = repr(e)[:200]
            meta.write_text(json.dumps(m))
    path = f"uploads/{key}/{safe}"
    return {"path": path, "source": "upload", "ext": ext.lstrip("."), "kind": kind, "n": 0, "split": "upload",
            "view": view_path(path)}


# ---------------------------------------------------------------- ask

class Ask(BaseModel):
    path: str
    question: str


def _upload_question(req: Ask) -> dict:
    p = resolve(req.path)
    if not p.exists():
        raise HTTPException(404, "upload not found (uploads are cleared when the server is rebuilt)")
    meta = _upload_meta(req.path)
    view = view_path(req.path)
    return {"path": str(p), "question": req.question, "type": guess_type(req.question), "unit": None,
            "source": "upload", "ext": p.suffix.lower().lstrip("."), "kind": meta.get("kind"), "id": None,
            "split": "upload", "answer": None, "view": str(resolve(view)) if view else "",
            "dxf_extents": meta.get("dxf_extents")}


def _run_router(q: dict, timeout: float = SOLVER_TIMEOUT_S) -> dict:
    try:
        fut = _pool.submit(router, q)
        res = fut.result(timeout=timeout)
    except cf.TimeoutError:
        return _abstain(f"the solver took longer than {timeout:.0f} s (the GPU may be busy), so we stopped "
                        "waiting rather than guess; try again in a minute",
                        method="timeout", error="timeout")
    except Exception as e:  # noqa: BLE001  never 500 on a solver bug: abstain and say why
        traceback.print_exc()
        return _abstain("the solver hit an internal error on this question, so it abstains rather than guess",
                        method="error", error=repr(e)[:300])
    if not isinstance(res, dict):
        return _abstain("the solver returned nothing usable", method="error")
    if res.get("answer") is None and str(res.get("method", "")).endswith("error"):
        # solver-internal failures (e.g. model weights being swapped) read as stack traces: keep them out of the UI
        res["error"] = res.get("explanation")
        res["explanation"] = ("the solver hit an internal error on this question (a model may be updating), "
                              "so it abstains rather than guess; try again in a minute")
    return res


def _fix_upload_evidence(res: dict, q: dict, client_path: str):
    """Solvers see absolute upload paths; the browser knows them as uploads/<key>/<name>."""
    base = str(resolve(client_path).parent)
    view = view_path(client_path)
    for e in res.get("evidence") or []:
        f = e.get("file")
        if not f:
            continue
        if f.startswith(base):
            e["file"] = "uploads/" + str(Path(f).relative_to(UPLOADS.resolve()))
        if e["file"] == client_path and view and view != client_path and e.get("kind") != "ifc":
            e["file"] = view


# ---------------------------------------------------------------- honest confidence, "why" trace, frontier answers

from app.calibration import BINS as CAL_BINS, build_frontier, family as cal_family  # noqa: E402

_CAL_FILE = APP / "calibration.json"
CALIB = json.loads(_CAL_FILE.read_text()) if _CAL_FILE.exists() else {"families": {}, "min_n": 200}
_frontier = {"key": None, "data": {}}
_frontier_lock = threading.Lock()


def frontier_table() -> dict:
    """Per-question frontier answers: live from runs/ when the full baseline runs are here (runs still being
    written are picked up as they grow), else the committed app/frontier.json (public bundle)."""
    files = sorted(RUNS.glob("baseline_*_full400*.jsonl"))
    key = tuple((f.name, f.stat().st_mtime) for f in files)
    with _frontier_lock:
        if _frontier["key"] != key:
            data = build_frontier(RUNS) if files else {}
            if not data and (APP / "frontier.json").exists():
                data = json.loads((APP / "frontier.json").read_text())
            _frontier.update(key=key, data=data)
        return _frontier["data"]


def calibration_for(res: dict) -> dict | None:
    """What this confidence has meant on the held-out test split, for answers made the same way."""
    if res.get("answer") is None:
        return None
    f = cal_family(res.get("method"))
    fam = CALIB["families"].get(f) if f else None
    if not fam:
        return {"measured": False}
    c = float(res.get("confidence") or 0)
    lo = next(b for b in CAL_BINS if c >= b)
    hi = next((b for b in reversed(CAL_BINS) if b > lo), 1.0)
    b = fam["bins"].get(str(lo))
    if b and b["n"] >= CALIB.get("min_n", 200):
        n, right, scope = b["n"], b["right"], "bin"
    else:
        n, right, scope = fam["n"] - fam.get("abstained", 0), fam["right"], "family"
    return {"measured": True, "family": f, "label": fam["label"], "scope": scope, "lo": lo, "hi": hi,
            "n": n, "right": right, "family_n": fam["n"], "family_right": fam["right"], "split": CALIB.get("split")}


ROUTE_WHY = {
    "swiss": "Swiss Dwellings plans come with the CAD file (DXF) they were drawn from, so the router sends the "
             "question to the CAD-layer solver: exact geometry, no model call",
    "ifc": "the drawing is a plan of an IFC (BIM) model, so the router queries the model itself: every element "
           "and quantity is read, not guessed",
    "ifctext": "a free-text question about an IFC model: a validated rule answers where one exists, otherwise a "
               "small LLM answers from a fact sheet extracted from the model and must cite the fact ids it used",
    "cubicasa": "a raster floor plan with no CAD behind it, so the router sends it to the plan-symbol detector "
                "we trained on the CubiCasa training split (runs locally, no model call)",
    "generic": "no specialist solver covers this file, so the general drawing reader takes it: the PDF text "
               "layer first, then a vision model that must box what it counts",
}
UPLOAD_KIND = {"ifc": "an IFC model", "dxf": "a DXF drawing", "pdf-vector": "a vector PDF",
               "pdf-raster": "a scanned PDF", "raster": "an image"}


def _short(v: float) -> str:
    return f"{v:.0f}" if abs(v - round(v)) < 1e-9 else f"{v:.2f}"


def trace_for(res: dict, q: dict) -> dict:
    """The "why this answer" panel: route and why, what was read, the arithmetic, cost and time."""
    ev = res.get("evidence") or []
    route = [r for r in str(res.get("route") or "-").split(" -> ") if r and r != "-"]
    why = []
    for i, r in enumerate(route):
        w = ROUTE_WHY.get(r, f"solver '{r}'")
        if i == 0 and q.get("source") == "upload":
            w = f"your upload is {UPLOAD_KIND.get(q.get('kind'), 'a file')}, so " + w.split(", so ", 1)[-1]
        if i > 0:
            w = "the first solver passed, so " + w.split(", so ", 1)[-1]
        why.append({"solver": r, "why": w})
    read: list[str] = []
    m = str(res.get("method") or "")
    files = collections.Counter(Path(e["file"]).name for e in ev if e.get("file"))
    kinds = collections.Counter(e.get("kind") for e in ev)
    if m.startswith("swiss"):
        read.append(f"CAD twin of {Path(q.get('path', '')).name}: " + (res.get("explanation") or ""))
    elif m.startswith("ifc") and not m.startswith("ifctext"):
        ifc = next((e["file"] for e in ev if e.get("kind") == "ifc"), None)
        if ifc:
            read.append(f"IFC model {Path(ifc).name}")
        cls = collections.Counter(re.match(r"(Ifc\w+)", e.get("label") or "").group(1) for e in ev
                                  if e.get("kind") == "ifc" and re.match(r"Ifc\w+", e.get("label") or ""))
        if cls:
            read.append("elements: " + ", ".join(f"{n} × {c}" for c, n in cls.most_common()))
        st = re.search(r"storey '([^']+)'", res.get("explanation") or "")
        if st:
            read.append(f"storey: {st.group(1)}")
        srcs = m.split("-")[-1] if m.startswith(("ifc-sum", "ifc-area")) else ""
        if srcs:
            read.append("quantities: " + " + ".join({"qto": "the model's own quantity sets (Qto_*)",
                                                       "geometry": "measured from the element geometry",
                                                       "prop": "element properties"}.get(x, x)
                                                      for x in srcs.split("+")))
    elif m.startswith("ifctext") or m.startswith("ifc-text"):
        cited = res.get("facts_cited") or [re.match(r"\[(f\d+)\]", e.get("label") or "").group(1) for e in ev
                                           if re.match(r"\[(f\d+)\]", e.get("label") or "")]
        if cited:
            read.append("cited facts: " + ", ".join(dict.fromkeys(cited)))
        read.append(res.get("explanation") or "")
    elif m.startswith("cubicasa"):
        try:
            from bp.cubicasa.classes import COUNTS
            from bp.cubicasa.questions import target

            t = target(q.get("question") or "")
            cs = router._solvers.get("cubicasa")
            th = getattr(cs, "thresh", {}) if cs is not None and not isinstance(cs, Exception) else {}
            if t:
                read.append("detector classes: " + ", ".join(
                    f"{c.replace('_', ' ')} (kept above score {th[c]:.2f})" if c in th else c.replace("_", " ")
                    for c in COUNTS.get(t, [])))
        except Exception:  # noqa: BLE001
            pass
        sc = [e["score"] for e in ev if e.get("score") is not None]
        if sc:
            read.append(f"{len(sc)} boxes kept, detector scores {min(sc):.2f}–{max(sc):.2f}")
        if m.endswith("+prior"):
            read.append("weak detections: the count also weighs how common each count is for this question")
    else:
        if files:
            read.append("read: " + ", ".join(files))
        if kinds:
            read.append("evidence: " + ", ".join(f"{n} {k}" for k, n in kinds.items()))
    # the arithmetic: the evidence values that add up to the answer
    arith = None
    a = res.get("answer")
    if isinstance(a, (int, float)) and not isinstance(a, bool) and ev:
        groups = [[e for e in ev if e.get("kind") in ("box", "polygon")], [e for e in ev if e.get("kind") == "ifc"]]
        best = None
        for g in groups:
            vals = [float(e["value"]) if e.get("value") is not None else 1.0 for e in g]
            if vals and (best is None or abs(sum(vals) - a) < abs(sum(best) - a)):
                best = vals
        if best:
            tot = sum(best)
            ok = abs(tot - a) <= max(0.011, 0.001 * abs(a))
            if all(v == 1 for v in best):
                expr = f"{len(best)} items, 1 each"
            else:
                shown = [_short(v) for v in best[:10]]
                expr = " + ".join(shown) + (f" + … ({len(best) - 10} more)" if len(best) > 10 else "")
            arith = {"expr": expr, "total": round(tot, 3), "n": len(best), "matches": ok}
    paid = float(res.get("cost_usd") or 0) > 0
    llm = m.startswith(("ifctext", "generic")) or "llm" in m
    return {"route": why, "read": [r for r in read if r], "arith": arith, "method": m,
            "model_call": "paid model call" if paid else ("local model, no paid call" if llm or m.startswith("cubicasa")
                                                         else "no model call")}


def frontier_for(ids: list) -> list:
    tab = frontier_table()
    for i in ids:
        if i is not None and str(i) in tab:
            return tab[str(i)]
    return []


@app.post("/api/ask")
def ask(req: Ask, request: Request):
    _rate_limit(request)
    if req.path.startswith("uploads/"):
        q, known, same = _upload_question(req), None, []
    else:
        qs = BY_PATH.get(req.path)
        if not qs:
            raise HTTPException(404, "unknown drawing")
        same = [x for x in qs if x["question"].strip() == req.question.strip()]
        known = same[0] if same else None
        q = dict(known) if known else {**qs[0], "question": req.question, "type": guess_type(req.question),
                                        "answer": None, "id": None}
    t0 = time.time()
    res = _run_router(q)
    if q.get("kind") == "dxf" and res.get("method") == "generic-none" and q.get("view", "").endswith(".png"):
        # the vision pass cannot render a DXF itself: give it the PNG we rendered from the same extents
        res2 = _run_router({**q, "path": q["view"], "ext": "png", "kind": "raster"})
        if res2.get("answer") is not None:
            res = res2
    if known is None and q["source"] != "upload" and res.get("answer") is None and q["ext"] in ("pdf", "png", "jpg") \
            and res.get("method") not in ("timeout", "error"):
        # a free-typed question the specialist does not recognise: let the general drawing reader try it,
        # exactly as for an upload (text layer first, then grounded vision), instead of a bare abstention
        why = res.get("explanation") or "not recognised"
        fb = _run_router({**q, "source": "upload", "kind": "pdf-vector" if q["ext"] == "pdf" else "raster"},
                         timeout=FALLBACK_TIMEOUT_S)
        fb["route"] = f"{res.get('route', '-')} -> {fb.get('route', 'generic')}"
        fb["cost_usd"] = (fb.get("cost_usd") or 0.0) + (res.get("cost_usd") or 0.0)
        if fb.get("answer") is not None:
            fb["explanation"] = f"the specialist solver passed ({why}), so the general drawing reader answered: " + \
                (fb.get("explanation") or "")
        elif fb.get("method") == "timeout":
            fb["explanation"] = (f"the specialist solver passed ({why}) and the general drawing reader timed out after "
                                 f"{FALLBACK_TIMEOUT_S} s (its GPU is probably busy); nothing was guessed")
        else:
            fb["explanation"] = f"the specialist solver passed ({why}) and the general reader found no answer either: " + \
                (fb.get("explanation") or "")
        res = fb
    if DAILY_CAP and res.get("answer") is None and spent_today() >= DAILY_CAP:
        res["explanation"] = (f"this public demo's daily budget for paid model calls (${DAILY_CAP:.0f}) is used up, "
                              "so questions that need a frontier model abstain until tomorrow (UTC); the $0 "
                              "solvers for Swiss, CubiCasa and IFC drawings still answer. "
                              + (res.get("explanation") or ""))
        res["budget_exhausted"] = True
    if q["source"] == "upload" and res.get("route") == "-" and res.get("answer") is None and res.get("method") == "none":
        res["explanation"] = (f"uploads of this kind ({q.get('kind')}) are not routed to a solver yet; "
                              "nothing was guessed")
    res["latency_s"] = round(time.time() - t0, 3)
    res["type"] = q["type"]
    res["source"] = q["source"]
    res["gold"] = known["answer"] if known else None
    res["baseline_cost_usd"] = BASELINE_COST.get(q["source"], BASELINE_COST.get("_all", 0.0))
    res["baseline_latency_s"] = BASELINE_LATENCY.get(q["source"], BASELINE_LATENCY.get("_all", 0.0))
    if q["source"] == "upload":
        _fix_upload_evidence(res, q, req.path)
    res.pop("raw", None)
    try:
        res["question_id"] = known["id"] if known else None
        res["calibration"] = calibration_for(res)
        res["trace"] = trace_for(res, q)
        res["frontier"] = frontier_for([x["id"] for x in same]) if known else []
    except Exception:  # noqa: BLE001  the extras never break an answer
        traceback.print_exc()
    try:
        return JSONResponse(json.loads(json.dumps(res, default=str)))
    except Exception as e:  # noqa: BLE001
        return _abstain(f"could not serialise the answer: {e}", method="error")


# ---------------------------------------------------------------- corrections become training data

CORRECTIONS = Path("cache/corrections.jsonl")
FEEDBACK_N, FEEDBACK_S = 60, 600  # per visitor, always on (independent of BP_RATE_LIMIT)
_fb_hits: dict[str, collections.deque] = collections.defaultdict(collections.deque)
_fb_lock = threading.Lock()


class Feedback(BaseModel):
    path: str
    question: str
    question_id: int | None = None
    type: str | None = None
    method: str | None = None
    original_answer: float | str | None = None
    corrected_answer: float | None = None
    removed: list[dict] = []
    added: list[dict] = []
    session: str | None = None
    tour: bool = False


def _clean_item(e: dict) -> dict:
    """Keep only geometry and labels: what a retraining job needs, nothing about the visitor."""
    out = {}
    if isinstance(e.get("kind"), str):
        out["kind"] = e["kind"][:16]
    if isinstance(e.get("label"), str):
        out["label"] = e["label"][:160]
    if isinstance(e.get("value"), (int, float)):
        out["value"] = float(e["value"])
    if isinstance(e.get("score"), (int, float)):
        out["score"] = float(e["score"])
    if isinstance(e.get("page"), int):
        out["page"] = e["page"]
    b = e.get("bbox")
    if isinstance(b, list) and len(b) == 4 and all(isinstance(x, (int, float)) for x in b):
        out["bbox"] = [round(float(x), 5) for x in b]
    pts = e.get("points")
    if isinstance(pts, list) and len(pts) <= 400:
        out["points"] = [[round(float(x), 5) for x in pt[:2]] for pt in pts
                         if isinstance(pt, list) and all(isinstance(x, (int, float)) for x in pt[:2])]
    g = e.get("guids")
    if isinstance(g, list):
        out["guids"] = [str(x)[:40] for x in g[:50]]
    return out


@app.post("/api/feedback")
def feedback(fb: Feedback, request: Request):
    """A visitor's correction (items dropped / added on the drawing) -> one JSON line in cache/corrections.jsonl,
    to be reviewed and folded into the next training run. No IP, no upload file name, no free-form notes."""
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or \
        (request.client.host if request.client else "?")
    now = time.time()
    with _fb_lock:
        dq = _fb_hits[ip]
        while dq and dq[0] < now - FEEDBACK_S:
            dq.popleft()
        if len(dq) >= FEEDBACK_N:
            raise HTTPException(429, "too many corrections from this visitor; please try again later")
        dq.append(now)
    if fb.path.startswith("uploads/"):
        path = "/".join(fb.path.split("/")[:2])  # uploads/<content hash>: the file name may be personal
    elif fb.path in BY_PATH:
        path = fb.path
    else:
        raise HTTPException(404, "unknown drawing")
    if len(fb.removed) + len(fb.added) > 500:
        raise HTTPException(413, "too many items")
    row = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "path": path, "question_id": fb.question_id, "question": fb.question[:500],
           "type": (fb.type or "")[:16], "method": (fb.method or "")[:60],
           "original_answer": fb.original_answer if not isinstance(fb.original_answer, str)
           else fb.original_answer[:500],
           "corrected_answer": fb.corrected_answer,
           "removed": [_clean_item(e) for e in fb.removed], "added": [_clean_item(e) for e in fb.added],
           "session": re.sub(r"[^A-Za-z0-9]", "", fb.session or "")[:16] or None, "tour": bool(fb.tour)}
    CORRECTIONS.parent.mkdir(parents=True, exist_ok=True)
    with _fb_lock, open(CORRECTIONS, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True}


# ---------------------------------------------------------------- tour

@app.get("/api/tour")
def tour():
    steps = json.loads((APP / "tour.json").read_text())
    return [s for s in steps if s.get("path", "").startswith("uploads/") or s.get("path") in BY_PATH]


# ---------------------------------------------------------------- results

ROW = re.compile(r"^\| (.+?) \| (\d+) \| (\d+)% \| ([\d.]+)% \| ([\d.]+%|-) \| ([\d.]+) \| ([\d.]+) \|$")


def parse_summary(f: Path) -> dict:
    txt = f.read_text()
    head = re.search(r"solver `([^`]+)`, split `([^`]+)`, n=(\d+)(.*)", txt)
    out = {"name": f.name.replace(".summary.md", ""), "solver": head.group(1) if head else "?",
           "split": head.group(2) if head else "?", "n": int(head.group(3)) if head else 0,
           "note": head.group(4).strip(", ") if head else "", "mtime": f.stat().st_mtime, "sections": {}}
    sec = None
    for ln in txt.splitlines():
        if ln.startswith("## "):
            sec = ln[3:].strip()
            out["sections"][sec] = []
            continue
        m = ROW.match(ln.strip())
        if m and sec:
            g = m.group(1).replace("**", "")
            out["sections"][sec].append({"group": g, "n": int(m.group(2)), "answered": int(m.group(3)),
                                         "accuracy": float(m.group(4)),
                                         "precision": None if m.group(5) == "-" else float(m.group(5)[:-1]),
                                         "usd_per_1k": float(m.group(6)), "s_per_q": float(m.group(7))})
    return out


def family(solver: str) -> str:
    s = solver.split("@")[0]
    if s == "prior":
        return "prior"
    if s in ("claude", "baseline"):
        return "frontier"
    return "ours"


@app.get("/api/results")
def results():
    runs = []
    for f in sorted(RUNS.glob("*.summary.md")):
        try:
            r = parse_summary(f)
        except Exception:  # noqa: BLE001
            continue
        r["family"] = family(r["solver"])
        runs.append(r)
    return {"runs": runs}


@app.get("/api/analysis")
def analysis():
    """Headline tables from analysis/out (full test split for ours and the prior; full-set 400-question frontier
    baselines re-weighted to the test mix), so the scoreboard shows the same numbers as the README."""
    import csv

    out = {}
    for name in ("overall", "by_source_type", "by_language"):
        f = Path("analysis/out") / f"{name}.csv"
        if f.exists():
            with open(f, newline="") as fh:
                out[name] = list(csv.DictReader(fh))
    return out


@app.get("/api/stats")
def stats():
    """Headline numbers (ALL row) of every test-split run."""
    out = {}
    for r in results()["runs"]:
        allrow = next((x for x in r["sections"].get("By type", []) if x["group"] == "ALL"), None)
        if allrow and r["split"] == "test":
            out[r["name"]] = {"n": allrow["n"], "accuracy": allrow["accuracy"], "usd_per_1k": allrow["usd_per_1k"]}
    return out


# ---------------------------------------------------------------- pages

@app.get("/")
def index():
    return HTMLResponse(_with_root((STATIC / "index.html").read_text()))


@app.get("/results")
def results_page():
    return HTMLResponse(_with_root((STATIC / "results.html").read_text()))


@app.get("/static/{name}")
def static(name: str):
    p = (STATIC / name).resolve()
    if not p.is_relative_to(STATIC.resolve()) or not p.exists():
        raise HTTPException(404)
    if ROOT_PATH and p.suffix in (".js", ".html"):
        mt = "text/javascript" if p.suffix == ".js" else "text/html"
        return Response(_with_root(p.read_text()), media_type=mt, headers={"Cache-Control": "no-cache"})
    return FileResponse(p, headers={"Cache-Control": "no-cache"})
