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

from bp import memgate
from bp.data import data_root, load_questions
from bp.router import Router, guess_type

# imported here, once, not lazily inside handlers: concurrent first imports of shapely from worker threads left it
# "partially initialized" (every later rooms / plan3d request 500ed, then the import lock hung the server)
import ezdxf  # noqa: E402,F401
import shapely.geometry  # noqa: E402,F401
import shapely.ops  # noqa: E402,F401

ROOT = data_root()
APP = Path(__file__).parent
STATIC = APP / "static"
RUNS = Path("runs")
UPLOADS = Path("cache/uploads")
app = FastAPI(title="Datum", docs_url=None, redoc_url=None, openapi_url=None)  # public: no API browser
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
# CubiCasa asks wait on one detector lock (CPU YOLO, ~1 s each on the demo VM): in the shared pool, a burst of them
# filled all 8 workers and a $0 Swiss/IFC ask queued behind them for 15 s. They get their own small lane instead
# (2 workers: the primary detector and the cross-check's second detector can still overlap).
_cc_pool = cf.ThreadPoolExecutor(2)

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
# rendering, word boxes, meshes, room schedules and 3D plans cost CPU but no money: a separate, more generous bucket
# (on whenever BP_RATE_LIMIT is), so a script can't pin the CPU and starve the asks
HEAVY_N = int(os.environ.get("BP_HEAVY_RATE_N", 0) or 0) or RATE_N * 20
_heavy_hits: dict[str, collections.deque] = collections.defaultdict(collections.deque)
_PRUNE_EVERY = 300
_last_prune = [0.0]


def client_key(request: Request) -> str:
    """The visitor's address as uvicorn resolved it (it reads X-Forwarded-For only from the trusted proxy, see
    --forwarded-allow-ips): a client-sent header can't pick its own bucket. IPv6 is keyed per /64."""
    import ipaddress

    host = request.client.host if request.client else "?"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _bucket(hits: dict, request: Request, n: int, window: float, msg: str, lock=_hits_lock):
    ip = client_key(request)
    now = time.time()
    with lock:
        if now - _last_prune[0] > _PRUNE_EVERY:  # forget visitors whose window has passed (bounded memory)
            _last_prune[0] = now
            for tab in (_hits, _heavy_hits, _fb_hits, _tts_hits, _free_hits):
                for k in [k for k, d in tab.items() if not d or d[-1] < now - max(window, RATE_S, FEEDBACK_S)]:
                    del tab[k]
        dq = hits[ip]
        while dq and dq[0] < now - window:
            dq.popleft()
        if len(dq) >= n:
            raise HTTPException(429, msg)
        dq.append(now)


def _rate_limit(request: Request):
    if not RATE_N:
        return
    _bucket(_hits, request, RATE_N, RATE_S, f"this public demo allows {RATE_N} questions per {RATE_S // 60} minutes "
                                            "per visitor; please try again in a few minutes")


# asks: every ask counts against a generous bucket (CPU); only asks that made a paid model call count against
# BP_RATE_LIMIT, so the tour and the $0 geometry/cached answers don't use up a visitor's questions
FREE_ASK_N = int(os.environ.get("BP_FREE_ASK_N", 0) or 0) or RATE_N * 10
_free_hits: dict[str, collections.deque] = collections.defaultdict(collections.deque)


def _ask_limit(request: Request):
    """Before an ask: refuse once the paid allowance is used up (the answer might need a paid call), and count the
    ask in the free bucket."""
    if not RATE_N:
        return
    ip, now = client_key(request), time.time()
    with _hits_lock:
        dq = _hits[ip]
        while dq and dq[0] < now - RATE_S:
            dq.popleft()
        full = len(dq) >= RATE_N
    if full:
        _rate_limit(request)  # raises the usual 429
    _bucket(_free_hits, request, FREE_ASK_N, RATE_S, f"this public demo allows {FREE_ASK_N} questions per "
                                                     f"{RATE_S // 60} minutes per visitor; please try again shortly")


def _ask_charge(request: Request, res: dict):
    """After an ask: a paid model call costs one of the visitor's BP_RATE_LIMIT questions."""
    if not RATE_N or not (res.get("cost_usd") or 0) > 0:
        return
    ip = client_key(request)
    with _hits_lock:
        _hits[ip].append(time.time())


def _heavy_limit(request: Request):
    if not RATE_N:
        return
    _bucket(_heavy_hits, request, HEAVY_N, RATE_S, "too many drawing requests from this visitor; please wait a minute")


# CPU-heavy work that one request can make expensive (upload preparation, IFC tessellation): at most 2 at a time.
# Memory is gated separately (bp/memgate.py): preparation, warm-ups, specialist answers and /api/walls take their
# estimated peak from one ~8 GB budget and queue while it is full; GET /api/queue tells the UI it is queued
_heavy_sem = threading.BoundedSemaphore(2)
HEAVY_WAIT_S = 600  # a job admitted by the memory gate waits this long for a CPU slot before giving up (503)


def _pixels_of(p: Path, page: int = 0) -> int:
    """Pixels a heavy job on this file decodes: a raster's own size (from its header), a PDF page as the sheet
    readers render it (~300 dpi, <= 9000 px), a raster's bigger full-size copy if it has one; 0 when unknown."""
    try:
        ext = p.suffix.lower()
        if ext == ".pdf":
            import pymupdf

            with pymupdf.open(p) as doc:
                r = doc[min(page, len(doc) - 1)].rect
            z = min(300 / 72, 9000 / max(r.width, r.height, 1))
            return int(r.width * z * r.height * z)
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif", ".heic", ".heif"):
            from PIL import Image

            n = 0
            for f in (p, p.with_name(p.name + ".full.png")):
                if f.is_file():
                    with Image.open(f) as im:
                        n = max(n, im.width * im.height)
            return n
    except Exception:  # noqa: BLE001  unreadable: the job itself reports that
        return 0
    return 0


@app.get("/api/queue")
def queue(key: str = "", rid: str = ""):
    """Is work for this upload (`key`, the folder in its path) or this pending upload (`rid`, sent with it) waiting
    for memory behind other uploads? The UI polls it while an upload or a question runs long."""
    tags = [t for t in (key[:12], f"rid:{rid[:40]}" if rid else "") if t]
    return memgate.status(tags)


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
    text = re.sub(r"""(["'`])/(api/|static/|results\b|how\b)""", lambda m: f"{m.group(1)}{ROOT_PATH}/{m.group(2)}", text)
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
        return "your upload: kept on this server; page images are sent to Claude Haiku to read it"
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
                                                         for s in _upload_suggestions(meta.get("kind"), meta.get("not_drawing"), meta.get("sheet_kind"),
                                                                                     f"{meta.get('sheet_title') or ''} {meta.get('name') or ''}")],
                **_upload_info(meta, path.split("/")[1])}
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

def _bytes_cache(max_bytes: int, maxsize: int = 256):
    """functools.lru_cache for a function returning bytes, bounded by their total size as well as by count (a page
    render of a big sheet is several MB: 128 of them were most of a GB)."""
    def deco(fn):
        mem: collections.OrderedDict = collections.OrderedDict()
        lock = threading.Lock()
        tot = [0]

        @functools.wraps(fn)
        def wrapper(*a):
            with lock:
                if a in mem:
                    mem.move_to_end(a)
                    return mem[a]
            v = fn(*a)
            with lock:
                if a not in mem and len(v) <= max_bytes // 4:
                    mem[a] = v
                    tot[0] += len(v)
                    while mem and (tot[0] > max_bytes or len(mem) > maxsize):
                        tot[0] -= len(mem.popitem(last=False)[1])
            return v

        def cache_clear():
            with lock:
                mem.clear()
                tot[0] = 0

        wrapper.cache_clear = cache_clear
        wrapper.cache_bytes = lambda: tot[0]
        return wrapper
    return deco


@_bytes_cache(192 << 20, maxsize=128)
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
    view = p.with_name(p.name + ".view.png")  # a big upload: its display copy (zoomed-in parts: /api/crop)
    return (view if view.exists() else p).read_bytes()


RENDER_DPI = (72, 100, 130, 160, 200, 220)  # snapped, so the lru cache can't be bypassed with dpi=101, 102, ...


@app.get("/api/render")
def render(request: Request, path: str, page: int = 0, dpi: int = 130):
    _heavy_limit(request)
    if not 0 <= page < 10_000:
        raise HTTPException(404, "no such page")
    dpi = min(RENDER_DPI, key=lambda d: abs(d - dpi))
    try:
        data = _render(path, page, dpi)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"render failed for {path!r} page {page}: {e!r}", flush=True)
        raise HTTPException(422, "could not render this page") from e
    mt = "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
    return Response(data, media_type=mt, headers={"Cache-Control": "max-age=3600"})


# ---- zoomed-in crops of big sheets: the viewer shows the display copy and, past its resolution, asks for the part in
# view at screen resolution, read from the full-size raster (decoded once, kept for the next crops) or the PDF itself
CROP_MAX_SIDE = 4096
CROP_PDF_DPI = 600           # a PDF page is cropped at most at this resolution
_CROP_SRC_BYTES = 400_000_000  # decoded full-size rasters kept in memory (PIL holds RGB at 4 bytes a pixel)
_crop_src: collections.OrderedDict = collections.OrderedDict()
_crop_lock = threading.Lock()


def _crop_source(path: str) -> Path:
    """The file a crop of `path` is read from: an upload's full-size copy if it has one. 404 unless viewable."""
    if "\x00" in path:
        raise HTTPException(404)
    p = resolve(path)
    if p.suffix.lower() not in VIEWABLE or not p.is_file():
        raise HTTPException(404)
    full = p.with_name(p.name + ".full.png")
    return full if full.is_file() else p


def _decoded(src: Path):
    """The decoded raster (L or RGB), cached by path + mtime; decoding a 139 MP PNG takes ~0.3 s and 139 MB."""
    from PIL import Image

    key = (str(src), src.stat().st_mtime_ns)
    with _crop_lock:
        if key in _crop_src:
            _crop_src.move_to_end(key)
            return _crop_src[key]
        im = Image.open(src)
        if im.width * im.height > REFUSE_PIXELS:  # a dataset file never prepared: same limit as uploads
            im.close()
            raise HTTPException(413, "image too large")
        im.load()
        im = im if im.mode in ("L", "RGB") else _flatten(im)
        _crop_src[key] = im
        while len(_crop_src) > 1 and sum(_im_bytes(x) for x in _crop_src.values()) > _CROP_SRC_BYTES:
            _crop_src.popitem(last=False)
        return im


def _im_bytes(im) -> int:
    return im.width * im.height * (1 if im.mode == "L" else 4)


def _source_size(path: str, page: int) -> tuple[int, int]:
    """Pixel size of the most detailed source a crop can read (PDF: the page at CROP_PDF_DPI)."""
    src = _crop_source(path)
    if src.suffix.lower() == ".pdf":
        import pymupdf

        with pymupdf.open(src) as doc:
            if not 0 <= page < len(doc):
                raise HTTPException(404, "no such page")
            r = doc[page].rect  # rotation applied: the page as shown
            return round(r.width / 72 * CROP_PDF_DPI), round(r.height / 72 * CROP_PDF_DPI)
    from PIL import Image

    with Image.open(src) as im:
        return im.size


@_bytes_cache(96 << 20, maxsize=48)
def _crop(path: str, page: int, box: tuple, w: int) -> bytes:
    import io

    x0, y0, x1, y1 = (v / 4096 for v in box)
    src = _crop_source(path)
    if src.suffix.lower() == ".pdf":
        import pymupdf

        with pymupdf.open(src) as doc:
            if not 0 <= page < len(doc):
                raise HTTPException(404, "no such page")
            pg = doc[page]
            r = pg.rect  # the page as shown (rotation applied); get_pixmap's clip is in these coordinates too
            vis = pymupdf.Rect(r.x0 + x0 * r.width, r.y0 + y0 * r.height, r.x0 + x1 * r.width, r.y0 + y1 * r.height)
            z = min(w / vis.width, CROP_PDF_DPI / 72, CROP_MAX_SIDE / vis.height)
            return pg.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=vis, alpha=False).tobytes("png")
    from PIL import Image

    im = _decoded(src)
    W, H = im.size
    b = (round(x0 * W), round(y0 * H), max(round(x0 * W) + 1, round(x1 * W)), max(round(y0 * H) + 1, round(y1 * H)))
    c = im.crop(b)
    w = min(w, c.width, CROP_MAX_SIDE * c.width // c.height or 1)  # never upscale: the browser does that as well
    h = max(1, round(c.height * w / c.width))
    if (w, h) != c.size:
        c = c.resize((w, h), Image.LANCZOS, reducing_gap=2.0)
    buf = io.BytesIO()
    c.save(buf, "PNG", compress_level=3)
    return buf.getvalue()


@app.get("/api/pageinfo")
def pageinfo(request: Request, path: str, page: int = 0):
    """{w, h}: the resolution /api/crop can reach for this page (the viewer asks for crops only past its display)."""
    _heavy_limit(request)
    if not 0 <= page < 10_000:
        raise HTTPException(404, "no such page")
    try:
        w, h = _source_size(path, page)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, "could not read this page") from e
    return {"w": w, "h": h}


@app.get("/api/crop")
def crop(request: Request, path: str, x0: float, y0: float, x1: float, y1: float, w: int = 1024, page: int = 0):
    """PNG of the part [x0,y0,x1,y1] (normalised to the page as shown) of a drawing, `w` px wide (at most the source's
    own resolution and CROP_MAX_SIDE). Coordinates snap to a 1/4096 grid and w to 32 px, so crops cache."""
    _heavy_limit(request)
    if not 0 <= page < 10_000:
        raise HTTPException(404, "no such page")
    vals = (x0, y0, x1, y1)
    if not all(v == v and -1e-6 <= v <= 1 + 1e-6 for v in vals) or x1 <= x0 or y1 <= y0:
        raise HTTPException(400, "bad crop box")
    box = tuple(min(4096, max(0, round(v * 4096))) for v in vals)
    if box[2] <= box[0] or box[3] <= box[1]:
        raise HTTPException(400, "crop box too small")
    w = max(32, min(CROP_MAX_SIDE, round(w / 32) * 32))
    try:
        data = _crop(path, page, box, w)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"crop failed for {path!r} page {page}: {e!r}", flush=True)
        raise HTTPException(422, "could not crop this page") from e
    return Response(data, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@functools.lru_cache(maxsize=128)
def _words(path: str, page: int) -> tuple:
    p = resolve(path)
    if p.suffix.lower() != ".pdf" or not p.exists():
        return ()
    import pymupdf

    with pymupdf.open(p) as doc:
        if page >= len(doc):
            return ()
        pg = doc[page]
        W, H, m = pg.rect.width, pg.rect.height, pg.rotation_matrix
        out = []
        for w in pg.get_text("words")[:4000]:
            r = pymupdf.Rect(w[:4]) * m if pg.rotation else pymupdf.Rect(w[:4])
            out.append((round(r.x0 / W, 5), round(r.y0 / H, 5), round(r.x1 / W, 5), round(r.y1 / H, 5)))
        return tuple(out)


@app.get("/api/words")
def words(request: Request, path: str, page: int = 0):
    """Where the drawing's own printed text sits (normalised boxes), so evidence badges can stay off it."""
    _heavy_limit(request)
    if not 0 <= page < 10_000:
        return {"boxes": []}
    try:
        return {"boxes": _words(path, page)}
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001  (a scan, a damaged file: no text to avoid)
        return {"boxes": []}


@app.get("/api/mesh")
def mesh(request: Request, path: str):
    from app.mesh import mesh_bytes

    _heavy_limit(request)
    _known_drawing(path)
    ifc = ifc_for(path)
    if ifc is None:
        raise HTTPException(404, "no IFC model for this drawing")
    if not _heavy_sem.acquire(timeout=120):
        raise HTTPException(503, "the server is busy; please try again in a minute")
    try:
        data = mesh_bytes(ifc)
    except Exception as e:  # noqa: BLE001
        print(f"tessellation failed for {path!r}: {e!r}", flush=True)
        raise HTTPException(422, "could not tessellate the model") from e
    finally:
        _heavy_sem.release()
    return Response(data, media_type="application/json",
                    headers={"Content-Encoding": "gzip", "Cache-Control": "max-age=3600"})


_PLAN3D: dict[str, dict] = {}
_FIXTURE_H = {"toilet": 0.4, "washbasin": 0.85, "bathtub": 0.55, "shower": 0.04, "stove": 0.9, "sink": 0.9}


@app.get("/api/plan3d")
def plan3d(request: Request, path: str):
    """A Swiss plan's CAD twin as extrudable geometry (metres): wall footprints, door / window / fixture outlines,
    numbered rooms, and the DXF -> page transform so the client can place the answer's evidence in 3D."""
    _heavy_limit(request)
    if path not in BY_PATH or "swiss_dwellings/" not in path:  # the dataset index, never a client-built path
        raise HTTPException(404, "3D plans exist for the Swiss CAD plans only")
    if path in _PLAN3D:
        return _PLAN3D[path]
    dxf = resolve(path).with_suffix(".dxf")
    if not dxf.exists():
        raise HTTPException(404, "no CAD twin for this drawing")
    import ezdxf
    from shapely.ops import unary_union

    from bp.solvers.swiss import SwissSolver
    from bp.swiss.parse import _poly

    try:
        fl = SwissSolver().floor_for({"path": path})
        msp = ezdxf.readfile(str(dxf)).modelspace()
        walls = unary_union([g for g in (_poly(e) for e in msp.query('LWPOLYLINE[layer=="WALL"]')) if g is not None])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"could not read the CAD twin: {type(e).__name__}")
    if fl is None or not fl.to_page:
        raise HTTPException(404, "no CAD twin for this drawing")

    def ring(r):
        return [[round(x, 3), round(y, 3)] for x, y in list(r.coords)[:-1]]

    def polys(g):
        g = g.simplify(0.004)
        return [{"outer": ring(p.exterior), "holes": [ring(h) for h in p.interiors]}
                for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon" and p.area > 1e-3]

    syms = []
    for s in fl.symbols:
        if s.kind in ("door", "window") or s.kind in _FIXTURE_H:
            r = s.geom.minimum_rotated_rectangle
            if r.geom_type == "Polygon" and r.area > 1e-4:
                syms.append({"kind": s.kind, "pts": ring(r.exterior), "h": _FIXTURE_H.get(s.kind)})
    rooms = [{"number": r.number, "name": r.name or "", "area": round(r.area, 2), "unit": r.unit,
              "outdoor": bool(r.outdoor), "pts": ring(r.poly.exterior if r.poly.geom_type == "Polygon"
                                                       else max(r.poly.geoms, key=lambda p: p.area).exterior),
              "label": [round(c, 3) for c in r.label_pos] if r.label_pos else None}
             for r in fl.rooms if r.number and r.poly.area > 0.05]
    out = {"walls": polys(walls), "symbols": syms, "rooms": rooms, "to_page": list(fl.to_page),
           "bounds": [round(c, 3) for c in walls.bounds]}
    if len(_PLAN3D) >= 64:
        _PLAN3D.pop(next(iter(_PLAN3D)))
    _PLAN3D[path] = out
    return out


# ---- /api/walls: an uploaded plan's walls for the 3D view (bp/sheets/walls3d.py: rooms.py's wall mask, simplified to
# <= ~4,000 polygon edges, in page-normalised coordinates, with the scale and the doors / windows in the wall lines).
# Cached in memory and beside the prepared image (walls_p<page>.json); a result on a provisional scale (the upload's
# OCR still running) is served but not cached, so the next open gets the real one.
_WALLS: collections.OrderedDict = collections.OrderedDict()
_walls_locks: dict = {}


@app.get("/api/walls")
def walls(request: Request, path: str, page: int = 0):
    from bp.sheets import walls3d

    _heavy_limit(request)
    _known_drawing(path)
    if not path.startswith("uploads/") or not 0 <= page < 10_000:
        raise HTTPException(404, "3D walls are read from uploaded plans")
    p = resolve(path)
    if not p.is_file() or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".pdf"):
        raise HTTPException(404, "3D walls are read from raster or PDF plans")
    st = p.stat()
    key = (str(p), page, st.st_mtime_ns, st.st_size)
    if key in _WALLS:
        return _WALLS[key]
    cf_ = p.parent / f"walls_p{page}.json"
    with _hits_lock:
        lock = _walls_locks.setdefault(key, threading.Lock())
    with lock:  # one extraction per page, however many tabs ask at once
        if key in _WALLS:
            return _WALLS[key]
        out = None
        if cf_.is_file():
            try:
                c = json.loads(cf_.read_text())
                if c.get("version") == walls3d.VERSION and c.get("src") == [st.st_mtime_ns, st.st_size]:
                    out = c
            except (OSError, ValueError):
                out = None
        if out is None:
            with memgate.hold(memgate.cost(_pixels_of(p, page), "walls"), tag=memgate.tag_for(p),
                              label=f"walls {p.name}"):
                if not _heavy_sem.acquire(timeout=HEAVY_WAIT_S):
                    raise HTTPException(503, "the server is busy; please try again in a minute")
                try:
                    out, final = walls3d.for_upload(str(p.resolve()), page)
                except HTTPException:
                    raise
                except Exception as e:  # noqa: BLE001
                    print(f"walls failed for {path!r} page {page}: {e!r}", flush=True)
                    raise HTTPException(422, "could not read walls from this page") from e
                finally:
                    _heavy_sem.release()
            out["src"] = [st.st_mtime_ns, st.st_size]
            if not final:
                return out
            try:
                cf_.write_text(json.dumps(out))
            except OSError:
                pass
        _WALLS[key] = out
        while len(_WALLS) > 32:
            _WALLS.popitem(last=False)
        _walls_locks.pop(key, None)
    return out


def _known_drawing(path: str):
    """A dataset drawing from the index, or an upload's own folder: anything else is a 404."""
    if "\x00" in path or not (path in BY_PATH or re.fullmatch(r"uploads/[0-9a-f]{12}/[A-Za-z0-9._-]+", path)):
        raise HTTPException(404)


@app.get("/api/file")
def raw_file(path: str):
    if "\x00" in path:
        raise HTTPException(404)
    p = resolve(path)
    if not p.is_file():
        raise HTTPException(404)
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "max-age=3600"}
    if p.suffix.lower() in VIEWABLE:
        return FileResponse(p, headers=headers)
    # anything else (DXF, IFC, an SVG or other markup) is only ever downloaded, never rendered on our origin
    return FileResponse(p, media_type="application/octet-stream", filename=p.name,
                        headers={**headers, "Content-Security-Policy": "sandbox; default-src 'none'"},
                        content_disposition_type="attachment")


# ---------------------------------------------------------------- uploads

UPLOAD_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".dxf", ".ifc"}
# converted on upload (to PNG; multi-page TIFF and SVG to PDF), so every solver sees one of UPLOAD_EXT
CONVERT_EXT = {".webp", ".tif", ".tiff", ".bmp", ".gif", ".svg", ".heic", ".heif"}
REFUSE_EXT = {
    ".dwg": "DWG is a closed AutoCAD format: export the sheet to PDF or DXF (File > Export / Plot to PDF) and upload that",
    ".rvt": "Revit models can't be read directly: export to IFC (File > Export > IFC) or print the sheets to PDF",
    ".skp": "SketchUp models can't be read directly: export to IFC or a PDF of the plan",
    ".zip": "please upload one drawing file (PDF, image, DXF or IFC), not an archive",
    ".docx": "this looks like a text document, not a drawing: upload the drawing as PDF or an image",
    ".xlsx": "this looks like a spreadsheet, not a drawing: upload the drawing as PDF or an image",
}
MAX_UPLOAD = 200 * 1024 * 1024
MAX_PIXELS = 40_000_000      # phone photos of a sheet are rectified at most at this size (downscaled first)
REFUSE_PIXELS = 260_000_000  # decompression bombs (checked from the header, before any pixel is decoded)
# big drawings keep their resolution (a 14000 x 9902 px sheet at 1:100 needs it for its tags): a sheet without
# colour becomes 8-bit grayscale at full size (<= 260 MB decoded); a colour-coded one keeps RGB up to this many
# pixels (an ARCH D sheet at 300 dpi, 10200 x 6600, fits) and is downscaled above it, with a full-size grayscale
# copy kept beside it (<name>.full.png) for reading small text
WORK_RGB_PIXELS = 72_000_000
GRAY_ABOVE_PIXELS = 20_000_000  # a colourless RGB raster bigger than this is stored as grayscale (a third the RAM)
VIEW_SIDE = 6000             # the browser gets <name>.view.png (long side <= this); zoomed-in parts come from /api/crop
OCR_UPSCALE_BELOW = 4000     # a raster with a shorter long side also gets <name>.ocr.png, 2x Lanczos, for OCR
MAX_FRAMES = 50              # TIFF pages kept (a multi-page scan); the rest are dropped. GIF / WEBP: first frame only
FRAME_PIXEL_BUDGET = 100_000_000  # width x height x frames converted, at most (~300 MB of RGB)


def _pil_limits():
    """Set before any Image.open (also in _convert): PIL refuses images over this outright."""
    from PIL import Image

    import warnings

    Image.MAX_IMAGE_PIXELS = REFUSE_PIXELS // 2
    # between half the limit and the limit PIL only warns; uploads are checked against REFUSE_PIXELS explicitly
    warnings.simplefilter("ignore", Image.DecompressionBombWarning)
    try:  # iPhone photos (HEIC / HEIF) open like any other image; libheif applies their rotation on decode
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:
        CONVERT_EXT.difference_update({".heic", ".heif"})
        REFUSE_EXT.update({e: "HEIC photos can't be read on this server: share or save the photo as JPG and upload "
                              "that" for e in (".heic", ".heif")})


_pil_limits()
SHEET_TYPES = os.environ.get("BP_SHEETS", "1") == "1"  # sheet-type specialists for uploads (bp/sheets)
PREP_VERSION = 6             # bump to re-run the upload preparation on files already in cache/uploads
SHEET_CHECK = os.environ.get("BP_SHEET_CHECK", "1") == "1"


class UploadError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.msg = status, msg


def _upload_meta(path: str) -> dict:
    p = resolve(path)
    m = p.parent / "meta.json"
    return json.loads(m.read_text()) if m.exists() else {}


def _upload_suggestions(kind: str | None, not_drawing=None, sheet_kind: str | None = None, hint: str = "") -> list[str]:
    if not_drawing:  # a photo or a document, not a plan: the solvers decline it, so suggesting counts would mislead
        return []
    if kind == "ifc":
        return ["How many doors are in the model?", "How many windows are in the model?",
                "What is the total length of all walls, in metres?", "How many storeys does the building have?",
                "What is the total floor area of all spaces, in m²?"]
    # a recognised sheet type (bp/sheets): the first three are what its specialist answers best
    if sheet_kind == "piping":
        return ["How many fuel pumps?", "What size is the suction header?", "How many check valves?",
                "Which sheets are referenced?"]
    if sheet_kind == "slab":
        return ["Slab area by type?", "How many pad footings?", "What is the slab thickness?"]
    if sheet_kind == "arch" and re.search(r"dormitor", hint, re.I):
        return ["Total dormitory area?", "Area of each colour zone?", "How many rooms?", "How many doors?"]
    if sheet_kind == "arch" and re.search(r"school|classroom|level[ _-]?0", hint, re.I):
        return ["How many doors?", "Baseboard length in the Library?", "How many rooms?", "What is the total floor area?"]
    if sheet_kind == "arch":
        return ["How many doors?", "What is the total floor area?", "How many rooms?", "How many windows?"]
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

    with pymupdf.open(p) as doc:  # vector if any of the first pages carries linework or text (a set's cover may not)
        for pg in list(doc)[:8]:
            if len(pg.get_text("words")) > 30 or len(pg.get_drawings()) > 200:  # text first: ~10x cheaper
                return "pdf-vector"
    return "pdf-raster"


def _flatten(im):
    """Any PIL mode -> 'L' or 'RGB' (transparency onto white, 16-bit scaled to 8, CMYK / palette / 1-bit expanded)."""
    from PIL import Image

    if im.mode in ("L", "RGB"):
        return im
    if im.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        import numpy as np

        a = np.asarray(im, dtype=np.float32)
        hi = float(a.max()) if a.size else 0.0
        return Image.fromarray(np.clip(a * (255.0 / hi if hi > 255 else 1.0), 0, 255).astype(np.uint8), "L")
    if im.mode == "1":
        return im.convert("L")
    if im.mode == "P" and "transparency" not in im.info:
        im = im.convert("RGB")
        return im
    if im.mode in ("LA", "La", "PA", "P", "RGBA", "RGBa"):
        gray = im.mode in ("LA", "La")
        im = im.convert("LA" if gray else "RGBA")
        bg = Image.new(im.mode, im.size, (255, 255) if gray else (255, 255, 255, 255))
        bg.alpha_composite(im)  # a drawing exported with a transparent background: white, not black
        return bg.convert("L" if gray else "RGB")
    return im.convert("RGB")  # CMYK, YCbCr, LAB, HSV


def _open_image(p: Path):
    """Image.open (lazy: header only), with PIL's own bomb check (when the limit is set) reported like ours."""
    from PIL import Image

    try:
        return Image.open(p)
    except Image.DecompressionBombError as e:
        m = re.search(r"\((\d+) pixels\)", str(e))
        n = int(m.group(1)) if m else 0
        raise UploadError(413, f"image is {n / 1e6:.0f} megapixels: too large to process (at most "
                               f"{REFUSE_PIXELS // 1_000_000} megapixels); export it at a lower resolution") from e


def _too_big(w: int, h: int):
    if w * h > REFUSE_PIXELS:
        raise UploadError(413, f"image is {w}x{h} px ({w * h / 1e6:.0f} megapixels): too large to process (at most "
                               f"{REFUSE_PIXELS // 1_000_000} megapixels); export it at a lower resolution")


def _convert(p: Path) -> Path:
    """webp / tif / bmp / gif / svg -> png or pdf next to it (the original stays as the 'original' copy)."""
    ext = p.suffix.lower()
    if ext == ".svg":
        import pymupdf

        try:
            with pymupdf.open(p) as doc:
                out = p.with_suffix(".pdf")
                out.write_bytes(doc.convert_to_pdf())
                return out
        except Exception as e:  # noqa: BLE001
            raise UploadError(422, f"could not read this SVG ({type(e).__name__}): export it as PDF or PNG") from e
    from PIL import Image, ImageSequence

    try:
        with _open_image(p) as im:
            _too_big(im.width, im.height)  # from the header: nothing decoded yet
            n = min(getattr(im, "n_frames", 1) or 1, MAX_FRAMES) if ext in (".tif", ".tiff") else 1
            if n > 1 and im.width * im.height * n > FRAME_PIXEL_BUDGET:  # one big frame is fine, many are not
                n = max(1, FRAME_PIXEL_BUDGET // max(1, im.width * im.height))
            frames = []
            # frame by frame, stopping at n: never decode the frames we would drop
            for _, f in zip(range(n), ImageSequence.Iterator(im)):
                _too_big(f.width, f.height)  # a TIFF's later pages can be bigger than its first
                frames.append(_flatten(f.copy() if f.mode in ("L", "RGB") else f))
    except UploadError:
        raise
    except Exception as e:  # noqa: BLE001
        raise UploadError(422, f"could not read this {ext.lstrip('.').upper()} image: it may be damaged "
                               f"({type(e).__name__})") from e
    if len(frames) > 1 and ext in (".tif", ".tiff"):  # a multi-page scan: keep its pages
        out = p.with_suffix(".pdf")
        frames[0].save(out, save_all=True, append_images=frames[1:], resolution=200)
        return out
    if ext in (".heic", ".heif"):  # a phone photo: a JPEG like the camera would have saved (orientation applied)
        out = p.with_suffix(".jpg")
        frames[0].save(out, "JPEG", quality=92)
        return out
    out = p.with_suffix(".png")
    frames[0].save(out, compress_level=1 if frames[0].width * frames[0].height > GRAY_ABOVE_PIXELS else 6)
    return out


def _colourful(im) -> bool:
    """Does an RGB image carry colour (a colour-coded zone plan) rather than gray linework? Read off a ~1000 px copy."""
    import numpy as np

    k = max(1, max(im.size) // 1000)
    a = np.asarray(im.reduce(k) if k > 1 else im, dtype=np.int16)
    chroma = a.max(axis=2) - a.min(axis=2)
    return float((chroma > 40).mean()) > 0.001


def _shrink(im, pixels: int):
    """Lanczos downscale to ~`pixels`, in bands of rows (resize's `box`), so a 260 MP sheet needs no full-width
    intermediate copy (PIL keeps RGB at 4 bytes a pixel: one would be ~600 MB)."""
    from PIL import Image

    s = (pixels / (im.width * im.height)) ** 0.5
    ow, oh = max(1, round(im.width * s)), max(1, round(im.height * s))
    out = Image.new(im.mode, (ow, oh))
    fy = im.height / oh
    for y in range(0, oh, 512):
        y1 = min(oh, y + 512)
        out.paste(im.resize((ow, y1 - y), Image.LANCZOS, box=(0, y * fy, im.width, y1 * fy)), (0, y))
    return out


def _save_png(im, out: Path):
    im.save(out, "PNG", compress_level=1 if im.width * im.height > GRAY_ABOVE_PIXELS else 6)


def _prep_raster(p: Path, m: dict):
    """Validate, honour EXIF rotation, rectify phone photos of sheets, normalise the pixel format (in place).
    Big drawings keep their full resolution. Peak memory is the decoded image plus a quarter (PIL holds RGB at 4 bytes
    a pixel): ~1.3 GB for a 260 MP colour sheet, ~0.4 GB for 139 MP of grayscale; only one >100 MP decode at a time."""
    full = p.with_name(p.name + ".full.png")
    try:
        im0 = _open_image(p)  # lazy: only the header is read here
    except UploadError:
        raise
    except Exception as e:  # noqa: BLE001
        raise UploadError(422, f"could not read this image: it may be damaged or not really a "
                               f"{p.suffix.lstrip('.').upper()} ({type(e).__name__})") from e
    with im0:
        W0, H0 = im0.size
        _too_big(W0, H0)
    if W0 * H0 <= BIG_PIXELS:
        return _prep_raster_decoded(p, m, full)
    with _big_sem:  # one huge decode at a time (~1 GB for 260 MP of RGB), whatever the other prep slot is doing
        return _prep_raster_decoded(p, m, full)


BIG_PIXELS = 100_000_000
_big_sem = threading.BoundedSemaphore(1)


def _prep_raster_decoded(p: Path, m: dict, full: Path):
    from PIL import Image, ImageOps

    try:
        im0 = Image.open(p)
        try:
            W0, H0 = im0.size
            _too_big(W0, H0)
            im0.load()  # a single-frame PNG / JPEG closes its file once decoded; the pixels stay usable
        except BaseException:
            im0.close()
            raise
        turned = changed = im0.getexif().get(0x0112, 1) not in (0, 1)  # EXIF orientation: browsers apply it, PIL not
        im = ImageOps.exif_transpose(im0) if changed else im0
        if im.mode not in ("L", "RGB"):
            im, changed = _flatten(im), True
        if im is not im0:
            im0.close()
    except UploadError:
        raise
    except Exception as e:  # noqa: BLE001
        raise UploadError(422, f"could not read this image: it may be damaged or not really a "
                               f"{p.suffix.lstrip('.').upper()} ({type(e).__name__})") from e
    if turned:
        m["notes"].append("turned to match the photo's orientation tag")
    colour = im.mode == "RGB" and _colourful(im)
    if im.mode == "RGB" and not colour and im.width * im.height > GRAY_ABOVE_PIXELS:
        im, changed = im.convert("L"), True
    # a phone photo of a sheet: flatten it (detection runs on a small copy, so a big flat scan costs ~nothing)
    try:
        from bp.generic.rectify import rectify

        if im.width * im.height <= MAX_PIXELS:
            flat, info = rectify(im)
        else:
            flat, info = rectify(im.reduce(max(1, max(im.size) // 1600)))
            if flat is not None:  # a huge photo: rectify a MAX_PIXELS copy (a photo has no detail beyond that)
                m["notes"].append(f"downscaled from {im.width}x{im.height} px")
                flat, info = rectify(_shrink(im, MAX_PIXELS))
    except Exception as e:  # noqa: BLE001
        flat, info = None, {"why": f"rectify failed: {type(e).__name__}"}
    if flat is not None:
        im, changed, colour = flat, True, flat.mode == "RGB"
        m["rectified"] = info
        m["notes"].append("rectified from your photo: perspective flattened and shadows evened out")
    elif colour and im.width * im.height > WORK_RGB_PIXELS:
        _save_png(im.convert("L"), full)
        m["full"] = {"file": full.name, "w": im.width, "h": im.height}
        m["notes"].append(f"colour copy downscaled from {im.width}x{im.height} px (full size kept in grayscale "
                          "for small text)")
        im, changed = _shrink(im, WORK_RGB_PIXELS), True
    if changed:
        _save_raster(im, p)
    m["image_w"], m["image_h"], m["colour"] = im.width, im.height, bool(colour)


def _raster_copies(p: Path, m: dict):
    """After the working file is final (rectified, turned): the browser's display copy (<name>.view.png, long side
    <= VIEW_SIDE) for a big sheet, or the OCR copy (<name>.ocr.png, 2x Lanczos) for a small one."""
    from PIL import Image

    with Image.open(p) as im:
        side = max(im.size)
        if side <= VIEW_SIDE and side >= OCR_UPSCALE_BELOW:
            return
        im.load()
        if side > VIEW_SIDE:
            s = VIEW_SIDE / side
            v = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS,
                          reducing_gap=3.0)
            v.save(p.with_name(p.name + ".view.png"), "PNG", compress_level=3)
        else:
            im.resize((im.width * 2, im.height * 2), Image.LANCZOS).save(p.with_name(p.name + ".ocr.png"), "PNG",
                                                                        compress_level=3)


def _save_raster(im, p: Path):
    if p.suffix.lower() in (".jpg", ".jpeg"):
        (im if im.mode in ("L", "RGB") else im.convert("RGB")).save(p, "JPEG", quality=92)
    else:
        _save_png(im, p)


def _prep_pdf(p: Path, m: dict):
    import pymupdf

    try:
        doc = pymupdf.open(p)
    except Exception as e:  # noqa: BLE001
        raise UploadError(422, f"could not open this PDF: it may be damaged ({type(e).__name__})") from e
    with doc:
        if doc.needs_pass:
            raise UploadError(422, "this PDF is password-protected: remove the password and upload it again")
        if doc.page_count == 0:
            raise UploadError(422, "this PDF has no pages")
        try:
            doc[0].get_pixmap(matrix=pymupdf.Matrix(0.2, 0.2))
        except Exception as e:  # noqa: BLE001
            raise UploadError(422, f"could not render this PDF's first page: it may be damaged "
                                   f"({type(e).__name__})") from e
        m["n_pages"] = doc.page_count
        if doc.is_repaired:
            m["notes"].append("the PDF was damaged and has been repaired; some content may be missing")
    if m["n_pages"] > 1:  # a drawing set: each page's sheet id and title from its text layer (~15 ms a page, no render)
        try:
            from bp.generic import sheetindex

            m["page_index"] = sheetindex.index(str(p))
        except Exception as e:  # noqa: BLE001
            print(f"sheet index failed for {p}: {e!r}", flush=True)


def _prep_dxf(p: Path, m: dict):
    import ezdxf

    try:
        doc = ezdxf.readfile(p)
    except Exception:  # noqa: BLE001
        try:
            from ezdxf import recover

            doc, auditor = recover.readfile(p)
            doc.saveas(p)  # the solvers read it with readfile()
            m["notes"].append("the DXF had errors and was repaired on upload")
        except Exception as e:  # noqa: BLE001
            raise UploadError(422, f"could not read this DXF: it may be damaged or a binary/newer variant; try "
                                   f"exporting it again as ASCII DXF ({type(e).__name__})") from e
    if not len(doc.modelspace()):
        raise UploadError(422, "this DXF has no drawing entities in model space (is the drawing in a paper-space "
                               "layout only? export the layout to PDF and upload that)")


def _prep_ifc(p: Path, m: dict):
    head = p.open("rb").read(4096).decode("latin-1", "replace")
    if "ISO-10303-21" not in head or "IFC" not in head.upper().split("FILE_SCHEMA", 1)[-1][:200]:
        raise UploadError(422, "this is not an IFC (STEP) file: export the model as IFC 2x3 or IFC4 and upload that")
    try:
        import ifcopenshell

        f = ifcopenshell.open(str(p))
        m["ifc_schema"] = f.schema
    except Exception as e:  # noqa: BLE001
        raise UploadError(422, f"could not read this IFC file: it may be damaged ({type(e).__name__})") from e


def _turn_pages(p: Path, kind: str, sheets: dict, m: dict):
    """Pages the sheet check found sideways are turned upright in the stored file (rasters and PDFs)."""
    turns = {x["page"]: x["turn"] for x in sheets.get("pages") or [] if x.get("turn")}
    if not turns:
        return
    if kind == "raster":
        from PIL import Image

        op = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}
        t = turns.get(0, 0) % 360
        if t not in op:
            return
        full = p.with_name(p.name + ".full.png")
        for f in (p, full) if full.exists() else (p,):  # the full-size copy turns with the working file
            with Image.open(f) as im:
                im.load()
                im = im.transpose(op[t])
            _save_raster(im, f)
            if f is p and "image_w" in m:
                m["image_w"], m["image_h"] = im.width, im.height
            elif f is not p and m.get("full"):
                m["full"].update(w=im.width, h=im.height)
    elif kind.startswith("pdf"):
        import pymupdf

        with pymupdf.open(p) as doc:
            for i, t in turns.items():
                doc[i].set_rotation((doc[i].rotation + t) % 360)
            tmp = p.with_name(p.name + ".tmp")
            doc.save(tmp, garbage=1)
        tmp.replace(p)
    else:
        return
    m["notes"].append("turned " + ", ".join(f"page {i + 1} by {t}°" if len(turns) > 1 or kind != "raster"
                                           else f"{t}° clockwise" for i, t in turns.items())
                      + " so its text reads upright")


def _prepare(d: Path, p: Path, m: dict) -> tuple[Path, str]:
    """Validate and normalise one uploaded file (runs once per distinct file). Returns (working file, kind)."""
    import filecmp
    import shutil

    m["notes"] = []
    ext = p.suffix.lower()
    orig = d / ("original" + ext)
    keep_orig = ext != ".svg"  # an SVG is active content: never kept or served as itself, only its PDF
    if keep_orig and not orig.exists():
        shutil.copyfile(p, orig)
    for pat in ("*.full.png", "*.view.png", "*.ocr.png", "sheet_meta_p*.json", "sheet_p*.png"):
        for f in d.glob(pat):  # left by an earlier preparation of the same file (PREP_VERSION bump)
            if f not in (p, orig):
                f.unlink(missing_ok=True)
    if ext in CONVERT_EXT:
        p2 = _convert(p)
        m["notes"].append(f"converted from {ext.lstrip('.').upper()} to {p2.suffix.lstrip('.').upper()}")
        p.unlink()
        p = p2
    kind = {".ifc": "ifc", ".dxf": "dxf"}.get(p.suffix.lower(), "raster" if p.suffix.lower() != ".pdf" else "pdf")
    if kind == "raster":
        _prep_raster(p, m)
    elif kind == "pdf":
        _prep_pdf(p, m)
    elif kind == "dxf":
        _prep_dxf(p, m)
    else:
        _prep_ifc(p, m)
    kind = _classify(p)
    if kind == "dxf" and not (d / (p.name + ".png")).exists():
        try:
            _render_dxf(p, d / (p.name + ".png"))
            m["dxf_extents"] = json.loads((d / "meta.json").read_text()).get("dxf_extents") \
                if (d / "meta.json").exists() else None
        except Exception as e:  # noqa: BLE001
            print(f"DXF render failed for {p}: {e!r}", flush=True)
            m["render_error"] = type(e).__name__
    check_file = d / (p.name + ".png") if kind == "dxf" else p
    if SHEET_CHECK and kind != "ifc" and check_file.exists() and not (DAILY_CAP and spent_today() >= DAILY_CAP):
        from bp.generic import sheets

        # a drawing set whose title blocks name every sheet: those are drawings, and their titles are read already
        # (no 16-page contact sheet for a model to look at: ~11 s and a model call saved on a 150-page set)
        sh = _set_sheets(m) if kind == "pdf-vector" and _is_set(m) else sheets.check(str(check_file.resolve()))
        m["sheets"] = sh
        m["sheet_cost_usd"] = sh.get("cost_usd", 0.0)
        if kind != "dxf":
            _turn_pages(p, "raster" if kind == "raster" else "pdf", sh, m)
        if sheets.not_a_drawing(sh):
            m["not_drawing"] = sheets.not_a_drawing(sh)
    if kind == "raster":
        _raster_copies(p, m)
    if _is_set(m):  # each sheet of a set is classified when a question first lands on it (_page_sheet_kind)
        m["sheet_kind"] = None
    elif SHEET_TYPES and kind in ("raster", "pdf-vector", "pdf-raster") and not m.get("not_drawing") \
            and not (DAILY_CAP and spent_today() >= DAILY_CAP):
        # what kind of sheet page 0 is (architectural / slab / piping plan: bp/sheets), one cheap Haiku call; the
        # router offers questions on it to that specialist first
        try:
            from bp import sheets as sheet_types

            sm = sheet_types.build_meta(str(p.resolve()), 0, cache_dir=d)
            m["sheet_kind"] = sm.get("kind")
            m["sheet_title"] = sm.get("title")
            m["sheet_scale"] = sm.get("scale") or ""
            m["sheet_units"] = sm.get("units") or "unknown"
            m["sheet_low_res"] = bool(sm.get("low_res"))
            m["sheet_cost_usd"] = m.get("sheet_cost_usd", 0.0) + (sm.get("cost_usd") or 0.0)
            sheet_types.warm_upload(sm)  # OCR / the specialist's own reading start now, in the background
        except Exception as e:  # noqa: BLE001
            print(f"sheet type check failed for {p}: {e!r}", flush=True)
    if not keep_orig:
        pass
    elif p.exists() and orig.exists() and filecmp.cmp(orig, p, shallow=False):  # streamed, any size
        (d / ("original" + ext)).unlink()  # nothing changed: no second copy
    else:
        m["original"] = "original" + ext
    return p, kind


def _is_set(m: dict) -> bool:
    """A drawing set: 3+ pages, most with a sheet id in their title block (bp/generic/sheetindex.py)."""
    idx = m.get("page_index") or []
    return len(idx) >= 3 and sum(bool(x.get("sheet_id")) for x in idx) >= 0.6 * len(idx)


def _set_sheets(m: dict) -> dict:
    """The page check's answer for a drawing set, from its title blocks: every page a drawing, upright, titled."""
    from bp.generic import sheetindex

    return {"n_pages": m.get("n_pages") or len(m["page_index"]), "cost_usd": 0.0, "source": "title blocks",
            "pages": [{"page": x["page"], "kind": "", "drawing": True, "turn": 0, "title": sheetindex.label(x),
                       "residential_plan": False} for x in m["page_index"]]}


def _set_suggestions(idx: list[dict]) -> list[str]:
    """Example questions on a drawing set, each naming a sheet of the kind its specialist reads best."""
    out = []
    for pat, q in ((r"\bPIPING PLAN\b", "How many check valves on {}?"), (r"\bSLAB PLAN\b", "Slab area by type on {}?"),
                   (r"\bFLOOR PLAN\b", "How many doors on {}?")):
        x = next((x for x in idx if x.get("sheet_id") and re.search(pat, x.get("title") or "", re.I)), None)
        if x:
            out.append(q.format(x["sheet_id"]))
    return out


def _render_dxf(src: Path, out: Path):
    """DXF -> PNG of the modelspace extents, no margins, so evidence normalised to the extents lines up."""
    import ezdxf
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf import bbox
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import Configuration, ImagePolicy
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
    # IMAGE entities reference files by path: drawing them would read files on this server, so they become outlines
    Frontend(RenderContext(doc), MatplotlibBackend(ax),
             config=Configuration(image_policy=ImagePolicy.RECT)).draw_layout(msp, finalize=False)
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
async def upload(request: Request, name: str, rid: str = ""):
    """Raw-body upload (no multipart dependency): POST /api/upload?name=plan.pdf with the file as body.
    The file is validated and normalised once (see _prepare): damaged files get a clear 4xx, phone photos are
    rectified, sideways scans turned, huge images downscaled, and every page gets a one-line description."""
    from starlette.concurrency import run_in_threadpool

    _rate_limit(request)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name)[-80:] or "drawing"
    if safe.startswith("original."):
        safe = "file_" + safe
    ext = Path(safe).suffix.lower()
    if ext in REFUSE_EXT:
        raise HTTPException(415, REFUSE_EXT[ext])
    if ext not in UPLOAD_EXT | CONVERT_EXT:
        raise HTTPException(415, f"unsupported file type {ext or '?'}: use PDF, PNG, JPG, DXF or IFC "
                                 "(WEBP, TIFF, BMP, GIF, SVG and HEIC are converted)")
    try:
        if int(request.headers.get("content-length") or 0) > MAX_UPLOAD:
            raise HTTPException(413, "file too large (max 200 MB)")
    except ValueError:
        raise HTTPException(400, "bad Content-Length") from None
    # stream to a temp file with a running size check (never the whole body in memory)
    import tempfile

    UPLOADS.mkdir(parents=True, exist_ok=True)
    sha, size = hashlib.sha1(), 0
    tmp = Path(tempfile.mkstemp(dir=UPLOADS, prefix=".incoming_")[1])
    try:
        with open(tmp, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "file too large (max 200 MB)")
                sha.update(chunk)
                fh.write(chunk)
        if not size:
            raise HTTPException(400, "empty file")
        key = sha.hexdigest()[:12]
        d = UPLOADS / key
        d.mkdir(parents=True, exist_ok=True)
        meta = d / "meta.json"
        m = json.loads(meta.read_text()) if meta.exists() else {}
        prepared = m.get("prep") == PREP_VERSION and m.get("name") and (d / m["name"]).exists()
        if not prepared:
            p = d / safe
            tmp.replace(p)
    finally:
        tmp.unlink(missing_ok=True)
    if prepared:
        safe, kind = m["name"], m["kind"]  # the same file again: prepared already
    else:
        def _prepare_limited(d, p, m):
            # memory first (queued, shown in the UI as "Queued behind other uploads…"), then one of 2 CPU slots
            tag = f"rid:{rid[:40]}" if rid else d.name
            with memgate.hold(memgate.cost(_pixels_of(p), "prep"), tag=tag, label=f"prep {p.name}"):
                if not _heavy_sem.acquire(timeout=HEAVY_WAIT_S):
                    raise UploadError(503, "the server is busy preparing other uploads; please try again in a minute")
                try:
                    return _prepare(d, p, m)
                finally:
                    _heavy_sem.release()

        try:
            p, kind = await run_in_threadpool(_prepare_limited, d, p, m)
        except UploadError as e:
            raise HTTPException(e.status, e.msg) from e
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            raise HTTPException(422, f"could not read this file as {ext.lstrip('.').upper()}: it may be damaged or "
                                     f"not really a {ext.lstrip('.').upper()} ({type(e).__name__})") from e
        safe = p.name
        m.update({"name": safe, "kind": kind, "bytes": size, "uploaded": time.time(), "prep": PREP_VERSION})
        meta.write_text(json.dumps(m))
    path = f"uploads/{key}/{safe}"
    _gpu_warm(m)
    return {"path": path, "source": "upload", "ext": Path(safe).suffix.lstrip("."), "kind": kind, "n": 0,
            "split": "upload", "view": view_path(path), **_upload_info(m, key)}


def _upload_info(m: dict, key: str) -> dict:
    """What the UI shows about an upload: notes, pages (with what each one is), not-a-drawing warning."""
    sh = m.get("sheets") or {}
    titles = {str(x["page"]): f"{x.get('kind', '')}: {x.get('title', '')}".strip(": ") for x in sh.get("pages") or []}
    idx = m.get("page_index") or []
    for x in idx:  # a drawing set: the sheet id and title printed in each page's title block
        if x.get("sheet_id"):
            titles[str(x["page"])] = " · ".join(s for s in (x["sheet_id"], x.get("title")) if s)
    out = {"notes": m.get("notes") or [], "pages": m.get("n_pages") or sh.get("n_pages") or 1,
           "page_titles": titles,
           "sheet_ids": {str(x["page"]): x["sheet_id"] for x in idx if x.get("sheet_id")},
           "drawing_pages": [x["page"] for x in sh.get("pages") or [] if x.get("drawing")],
           "not_drawing": m.get("not_drawing"),
           "original": f"uploads/{key}/{m['original']}" if m.get("original") else None,
           **_sheet_info(m, key)}
    if _is_set(m) and not out["suggested"] and not m.get("not_drawing"):
        out["suggested"] = _set_suggestions(idx)
    return out


SHEET_LABEL = {"arch": "Architectural plan", "slab": "Slab plan", "piping": "Piping plan"}


def _sheet_info(m: dict, key: str) -> dict:
    """The sheet type the upload was recognised as (bp/sheets), for the UI's chip, and its three tailored examples."""
    kind = m.get("sheet_kind")
    if kind not in SHEET_LABEL:
        return {"sheet_kind": None, "suggested": []}
    scale, units, low = m.get("sheet_scale"), m.get("sheet_units"), m.get("sheet_low_res")
    if scale is None or units is None or low is None:  # not kept in meta.json: read them from the sheet meta cache
        try:
            sm = json.loads((UPLOADS / key / "sheet_meta_p0.json").read_text())
        except (OSError, ValueError):
            sm = {}
        scale = (sm.get("scale") or "") if scale is None else scale
        units = (sm.get("units") or "unknown") if units is None else units
        low = bool(sm.get("low_res")) if low is None else low
    sug = _upload_suggestions(m.get("kind"), m.get("not_drawing"), kind, f"{m.get('sheet_title') or ''} {m.get('name') or ''}")
    return {"sheet_kind": kind, "sheet_label": SHEET_LABEL[kind], "sheet_title": m.get("sheet_title") or "",
            "sheet_scale": scale, "sheet_units": units, "sheet_low_res": low, "suggested": sug[:3]}


# ---------------------------------------------------------------- ask

class Ask(BaseModel):
    path: str
    question: str
    page: int | None = None  # uploads: the page the user picked (0-based); None = let the reader pick


# a sheet specialist's first question may take up to ~62 s (bp/sheets ANSWER_MAX_S; it waits for the upload's
# warm-up) and the generic reader then still needs its own ~30 s when the specialist abstains
UPLOAD_TIMEOUT_S = float(os.environ.get("BP_UPLOAD_TIMEOUT_S", "100"))
# words of typical questions: a typed "how mnay windws" is read as "how many windows" (shown as "read as: ...")
_VOCAB = set("""how many much what which where who is are the this that there on in of shown drawn plan floor
drawing sheet page number total area height width length ceiling dimensions scale architect title date revision
window windows door doors toilet toilets room rooms bedroom bedrooms bathroom bathrooms kitchen kitchens sauna saunas
sink sinks shower showers bathtub bathtubs stair stairs staircase staircases storey storeys floors level levels
balcony balconies wall walls column columns parking spaces space elevator lift corridor living dining garage
closet closets office offices show shows does have has with and for from all each any can see find list name
names labelled labeled marked count give tell please whats into than then them they their these those
dorm dorms dormitory dormitories baseboard baseboards skirting slab slabs piping pipe pipes valve valves classroom
classrooms hall library meters metres linear footage square feet wing wings circulation trench trenches""".split())


def _fix_typos(question: str) -> str:
    import difflib

    def fix(m):
        w = m.group(0)
        lw = w.lower()
        if len(lw) < 3 or lw in _VOCAB or lw.rstrip("s") in _VOCAB or lw + "s" in _VOCAB or not lw.isalpha():
            return w
        c = difflib.get_close_matches(lw, _VOCAB, n=1, cutoff=0.75)
        if not c or abs(len(c[0]) - len(lw)) > 1 or c[0][0] != lw[0]:
            return w
        return c[0].capitalize() if w[0].isupper() else c[0]

    return re.sub(r"[A-Za-z]+", fix, question)


def _upload_question(req: Ask) -> dict:
    p = resolve(req.path)
    if not p.exists():
        raise HTTPException(404, "upload not found (uploads are cleared when the server is rebuilt)")
    meta = _upload_meta(req.path)
    view = view_path(req.path)
    question = _fix_typos(req.question)
    sh = meta.get("sheets") or {}
    n_pages = meta.get("n_pages") or sh.get("n_pages") or 1
    page = req.page if req.page is not None and 0 <= req.page < n_pages else None
    page_why = None
    if n_pages > 1 and meta.get("page_index"):  # a drawing set: a sheet id in the question picks its page
        from bp.generic import sheetindex

        named = sheetindex.find(question, meta["page_index"])
        if named is not None and named < n_pages:
            sid = meta["page_index"][named]["sheet_id"]
            page, page_why = named, f"sheet {sid}, page {named + 1} of {n_pages} (named in the question)"
    from bp.generic.sheets import page_info

    info = page_info(sh, page or 0) or {}
    # a page of a set (or one the user is viewing): its own sheet type, classified on first use
    page_kind = _page_sheet_kind(p, meta, page) if n_pages > 1 and page is not None and \
        (page or not meta.get("sheet_kind")) else None
    if SHEET_TYPES and "sheet_kind" not in meta and meta.get("kind") in ("raster", "pdf-vector", "pdf-raster") \
            and not meta.get("not_drawing") and not (DAILY_CAP and spent_today() >= DAILY_CAP):
        try:  # an upload prepared before sheet types existed (or with BP_SHEETS=0): classify it now, once
            from bp import sheets as sheet_types

            sm = sheet_types.build_meta(str(p.resolve()), 0, cache_dir=p.parent)
            meta["sheet_kind"], meta["sheet_title"] = sm.get("kind"), sm.get("title")
            mf = p.parent / "meta.json"
            mf.write_text(json.dumps({**json.loads(mf.read_text()), "sheet_kind": meta["sheet_kind"],
                                      "sheet_title": meta["sheet_title"]}))
        except Exception as e:  # noqa: BLE001
            print(f"sheet type check failed for {p}: {e!r}", flush=True)
    return {"path": str(p), "question": question, "type": guess_type(question), "unit": None,
            "source": "upload", "ext": p.suffix.lower().lstrip("."), "kind": meta.get("kind"), "id": None,
            "split": "upload", "answer": None, "view": str(resolve(view)) if view else "",
            "dxf_extents": meta.get("dxf_extents"), "page": page, "sheets": sh, "n_pages": n_pages,
            "residential_plan": bool(info.get("residential_plan")) and n_pages == 1,
            "sheet_kind": meta.get("sheet_kind") if (n_pages == 1 or (page == 0 and not page_kind)) else page_kind,
            "page_why": page_why, "typo_fixed": question if question != req.question else None}


def _page_sheet_kind(p: Path, meta: dict, page: int) -> str | None:
    """Sheet type of one page of a drawing set (bp/sheets), classified the first time a question is asked on it:
    that page alone is rendered (the specialist reads the same render), and the kind is kept in meta.json."""
    known = (meta.get("page_kinds") or {}).get(str(page))
    if known is not None or not SHEET_TYPES or meta.get("kind") not in ("pdf-vector", "pdf-raster") \
            or meta.get("not_drawing") or (DAILY_CAP and spent_today() >= DAILY_CAP):
        return known or None
    try:
        from bp import sheets as sheet_types

        sm = sheet_types.build_meta(str(p.resolve()), page, cache_dir=p.parent)
        kind = sm.get("kind") or ""
        mf = p.parent / "meta.json"
        with _meta_write_lock:
            cur = json.loads(mf.read_text()) if mf.exists() else {}
            cur.setdefault("page_kinds", {})[str(page)] = kind
            mf.write_text(json.dumps(cur))
        meta.setdefault("page_kinds", {})[str(page)] = kind
        return kind or None
    except Exception as e:  # noqa: BLE001
        print(f"sheet type check failed for {p} page {page}: {e!r}", flush=True)
        return None


_meta_write_lock = threading.Lock()


# sources whose specialist answers exactly from a CAD/BIM twin: a typed question it cannot read is never handed
# to the general (vision) reader, whose answers vary between asks
EXACT_SOURCES = {"swiss_dwellings", "ifc_models"}
FB_CACHE = Path("cache/typed_fallback.jsonl")
_fb_lock = threading.Lock()
_fb_mem: dict | None = None


def _fb_cache_get(key: str) -> dict | None:
    """A general-reader answer to a typed question on a dataset drawing, from an earlier ask (cost $0 now)."""
    global _fb_mem
    with _fb_lock:
        if _fb_mem is None:
            _fb_mem = {}
            if FB_CACHE.exists():
                for line in FB_CACHE.read_text().splitlines():
                    try:
                        r = json.loads(line)
                        _fb_mem[r["k"]] = r["res"]
                    except (json.JSONDecodeError, KeyError):
                        pass
        hit = _fb_mem.get(key)
    return None if hit is None else {**json.loads(json.dumps(hit)), "cost_usd": 0.0, "cached": True}


def _fb_cache_put(key: str, res: dict):
    try:
        rec = json.loads(json.dumps(res, default=str))
    except (TypeError, ValueError):
        return
    with _fb_lock:
        if _fb_mem is not None:
            _fb_mem[key] = rec
        FB_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(FB_CACHE, "a") as f:
            f.write(json.dumps({"k": key, "res": rec}, ensure_ascii=False) + "\n")


def _run_router(q: dict, timeout: float = SOLVER_TIMEOUT_S) -> dict:
    try:
        fut = (_cc_pool if router.route_for(q) == "cubicasa" else _pool).submit(router, q)
        res = fut.result(timeout=timeout)
    except cf.TimeoutError:
        return _abstain(f"the solver took longer than {timeout:.0f} s (the GPU may be busy), so we stopped "
                        "waiting rather than guess; try again in a minute",
                        method="timeout", error="timeout")
    except Exception as e:  # noqa: BLE001  never 500 on a solver bug: abstain and say why
        traceback.print_exc()
        return _abstain("the solver hit an internal error on this question, so it abstains rather than guess",
                        method="error", error="internal error")
    if not isinstance(res, dict):
        return _abstain("the solver returned nothing usable", method="error")
    if res.get("answer") is None and str(res.get("method", "")).endswith("error"):
        # solver-internal failures (e.g. model weights being swapped) read as stack traces: keep them out of the UI
        # and out of the response (logged here instead)
        print(f"solver error ({res.get('method')}): {str(res.get('explanation'))[:500]}", flush=True)
        res["error"] = "internal error"
        res["explanation"] = ("the solver hit an internal error on this question (a model may be updating), "
                              "so it abstains rather than guess; try again in a minute")
    return res


def _upload_honesty(res: dict, q: dict):
    """Uploads have no track record: a very unsure answer becomes an abstention (its candidate marks stay
    visible), the page that was read is reported, and a typo fix is shown as the question we read."""
    if q.get("typo_fixed") and not res.get("normalized_question"):
        res["normalized_question"] = q["typo_fixed"]
        res["explanation"] = f"read as: {q['typo_fixed']} | " + (res.get("explanation") or "")
    if res.get("answer") is not None and (res.get("confidence") or 0) < 0.3:
        res["explanation"] = (f"best guess {res['answer']!s:.60}, but the evidence was too weak to give it as an answer "
                              f"(confidence {100 * (res.get('confidence') or 0):.0f} %); the marks show what was found | "
                              + (res.get("explanation") or ""))
        res["tentative_answer"], res["answer"] = res["answer"], None
    res["pages"] = q.get("n_pages") or 1
    if res.get("page") is None:
        pg = [e.get("page", 0) for e in res.get("evidence") or [] if e.get("bbox")]
        res["page"] = max(set(pg), key=pg.count) if pg else (q.get("page") or 0)


def _counted_noun(res: dict, question: str) -> str | None:
    """The thing a generic vision count boxed ("toilet"), from its target, for rows the solver labelled 'item'."""
    m = re.search(r"x '([^']+)' boxed", str(res.get("explanation") or ""))
    t = m.group(1) if m else re.sub(r"(?i)^\s*how many\s+", "", question or "")
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.split(r"(?i)\s+(?:are|is|in|on|of|drawn|shown|can|do|does|there|symbols?|in plan view)\b|[?,.]", t)[0]
    words = t.strip().split()
    if not words or len(words) > 4:
        return None
    w = " ".join(words).lower()
    if w.endswith("ies"):
        w = w[:-3] + "y"
    elif w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    return w or None


def _name_items(res: dict, question: str):
    ev = [e for e in res.get("evidence") or [] if re.fullmatch(r"item \d+", str(e.get("label") or ""))]
    if not ev:
        return
    noun = _counted_noun(res, question)
    if noun and noun != "item":
        for e in ev:
            e["label"] = noun + " " + e["label"].split()[-1]


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


def _locate_evidence(res: dict, client_path: str):
    from bp.generic import locate

    view = view_path(client_path) or client_path

    def path_of(f):
        try:
            p = resolve(f or view)
        except HTTPException:
            return None
        return p if p.exists() else None

    locate.check(res, path_of)


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


_READ_AS = re.compile(r"^(read as: [^|]*\| ?)+")


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
    nz = res.get("normalize") or {}
    if nz:  # the solver did not follow the wording, so a small LLM tried to rephrase it (bp/normalize.py)
        paid_nz = float(nz.get("cost_usd") or 0) > 0
        if paid_nz:  # then "no model call" on the solver step would contradict the cost line
            for x in why:
                x["why"] = re.sub(r"(,| \(runs locally,)? no model call\)?",
                                  lambda mm: " (runs locally)" if "(" in mm.group(0) else "", x["why"])
        why.append({"solver": "normalize", "why": (
            f"the solver did not follow the wording, so a small LLM rephrased it as \"{nz['question']}\" and the "
            "solver ran again on that" if nz.get("question") else
            "the solver did not follow the wording, so a small LLM tried to rephrase it into one the solver handles; "
            "it found none" + (f" ({str(nz['why'])[:160]})" if nz.get("why") else ""))
            + ("" if paid_nz else "; reused from an earlier identical question, so no new call")})
    expl = _READ_AS.sub("", res.get("explanation") or "")  # the rewrite is shown as "read as" under the question
    read: list[str] = []
    m = str(res.get("method") or "")
    files = collections.Counter(Path(e["file"]).name for e in ev if e.get("file"))
    kinds = collections.Counter(e.get("kind") for e in ev)
    if m.startswith("swiss"):
        read.append(f"CAD twin of {Path(q.get('path', '')).name}: " + expl)
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
        read.append(expl)
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


CUBI_RULE = {  # the dataset's own definitions (bp/cubicasa/questions.py templates), one line each
    "door": "Counts doorways fitted with a door leaf; open doorways without a leaf are excluded.",
    "window": "Counts each window symbol on the plan once.",
    "sink": "Kitchen sinks and wash basins together; a double-bowl sink counts as one.",
    "shower_bath": "Showers and bathtubs together, one per fixture.",
    "toilet": "Counts toilet bowls (WC seats), not WC rooms.",
    "bathroom": "Bathrooms and washrooms (KH, KPH, PH, PESUH, SH); separate WC rooms are excluded.",
    "wc_room": "Separate WC rooms only; bathrooms with a toilet are excluded.",
    "sauna": "A sauna room, or a sauna stove outside any sauna room, counts as one sauna.",
    "kitchen": "Kitchens, kitchenettes, open kitchens and utility kitchens all count.",
    "bedroom": "Rooms marked as bedrooms (MH, makuuhuone).",
    "balcony": "Balconies (parveke), glazed balconies included.",
    "floor": "Counts the storeys drawn on the sheet.",
}
IFC_MEASURE = {"length": "Length", "area": "NetSideArea / NetFloorArea", "volume": "NetVolume"}


def rule_for(res: dict, q: dict) -> str | None:
    """One sentence: what was counted or summed, and what was left out."""
    if res.get("answer") is None:
        return None
    m, ql, expl = str(res.get("method") or ""), (q.get("question") or "").lower(), res.get("explanation") or ""
    if m.endswith("-compare") or res.get("comparison"):  # before the per-source rules: their wording is for one value
        if m.startswith("ifc"):
            return ("Compared from the IFC model: each candidate's value is read as for a normal count or quantity "
                    "answer; the largest / smallest or the difference is shown with its arithmetic.")
        if m.startswith("swiss"):
            return ("Compared from the CAD geometry: each candidate's value is read as for a normal area or count "
                    "answer; the largest / smallest or the difference is shown with its arithmetic.")
        return ("Each candidate's value is read as for a normal answer; the largest / smallest or the difference "
                "is shown with its arithmetic.")
    if m.startswith("cubicasa"):
        try:
            from bp.cubicasa.questions import target

            return CUBI_RULE.get(target(q.get("question") or ""))
        except Exception:  # noqa: BLE001
            return None
    if m.startswith("swiss"):
        lay = re.search(r"on layer (\w+)", expl)
        if q.get("type") == "count":
            if lay:
                both = " Interior and entrance doors together." if "door" in expl.lower() else ""
                return f"One per symbol on CAD layer {lay.group(1)}.{both}"
            if "apartment" in expl.lower() or "apartments" in ql:
                return "One per labelled apartment (residential unit) on the floor."
            return "Rooms whose label matches the question, read from the CAD room polygons."
        ex = _READ_AS.sub("", expl)
        if re.match(r"room \S+ ", ex):  # one room, even when the question names its apartment ("Küche in Wohnung A")
            return "Net floor area of the room polygon in the CAD file."
        if re.match(r"\d+ rooms labelled ", ex):
            return "Sum of the net floor areas of the room polygons with that label in the CAD file."
        if re.search(r"apartment|wohnung|appartement|appartamento|lejlighed|asunto", ql) or "apartment" in expl.lower():
            return ("Sum of the apartment's room polygons (net area); balconies, loggias, terraces and other outdoor "
                    "spaces are excluded.")
        if re.search(r"all numbered|alle nummerierten|tous les|tutti i", ql):
            return "All numbered indoor rooms; balconies, loggias, terraces, outdoor spaces, shafts and voids excluded."
        return "Net floor area of the room polygon(s) in the CAD file."
    if m.startswith("ifc-count"):
        st = re.search(r"storey '([^']+)'", expl)
        cls = re.search(r"(Ifc\w+)", expl)
        what = cls.group(1) if cls else "matching IFC"
        return f"One per {what} element" + (f" on storey '{st.group(1)}'" if st else " in the whole model") + "."
    if m.startswith(("ifc-sum", "ifc-area")):
        srcs = m.split("-")[-1].split("+")
        src = "the model's own base quantities (Qto_*)" if srcs == ["qto"] else \
            "the model's base quantities (Qto_*), measured from geometry where an element has none"
        if m.startswith("ifc-area"):
            return f"Net floor area of each space (IfcSpace) from {src}."
        meas = IFC_MEASURE.get(q.get("type"), "quantity")
        cls = re.search(r"(Ifc\w+)", expl)
        st = re.search(r"storey '([^']+)'", expl)
        return (f"Sum of each {cls.group(1) if cls else 'element'}'s {meas}" + (f" on storey '{st.group(1)}'" if st else "")
                + f", from {src}.")
    if m.startswith("ifctext"):
        return "Composed only from the cited fact lines of the model; anything not in the facts is left out."
    if m.startswith("generic-ground"):
        return "A vision model boxed every instance it counted, and a second pass re-checked the count."
    if m.startswith("generic-text"):
        return "Read from the drawing's own text; the text it used is boxed."
    return None


def frontier_for(ids: list) -> list:
    tab = frontier_table()
    for i in ids:
        if i is not None and str(i) in tab:
            return tab[str(i)]
    return []


@app.post("/api/ask")
def ask(req: Ask, request: Request):
    _ask_limit(request)
    picks, asked = {}, req.question
    if req.path.startswith("uploads/"):
        from app import projects  # a clarify pick ("(room: Library)") is read here, not matched as words

        sq, picks = projects.prepare_question(req.question)
        if picks:
            req = Ask(path=req.path, question=sq, page=req.page)
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
    res = _run_router(q, UPLOAD_TIMEOUT_S if q["source"] == "upload" else SOLVER_TIMEOUT_S)
    if q.get("kind") == "dxf" and res.get("method") == "generic-none" and q.get("view", "").endswith(".png"):
        # the vision pass cannot render a DXF itself: give it the PNG we rendered from the same extents
        res2 = _run_router({**q, "path": q["view"], "ext": "png", "kind": "raster"},
                           max(20.0, UPLOAD_TIMEOUT_S - (time.time() - t0)))
        if res2.get("answer") is not None:
            res = res2
    if known is None and q["source"] in EXACT_SOURCES and res.get("answer") is None \
            and res.get("method") not in ("timeout", "error"):
        # an exact CAD/BIM solver exists for this drawing: its honest abstention (with the plan's labels or the
        # model's storeys) beats a vision guess that changes from one ask to the next. A name the drawing does not
        # have (res["not_found"]) already says so plainly, with the names it does have
        if not res.get("not_found"):
            res["explanation"] = (res.get("explanation") or "not recognised") + \
                " (nothing was guessed: this drawing has an exact CAD/BIM twin, so the general vision reader is not used)"
    elif known is None and q["source"] != "upload" and res.get("answer") is None and q["ext"] in ("pdf", "png", "jpg") \
            and res.get("method") not in ("timeout", "error"):
        # a free-typed question the specialist does not recognise: let the general drawing reader try it,
        # exactly as for an upload (text layer first, then grounded vision), instead of a bare abstention.
        # Cached per (drawing, question) so asking again gives the same answer.
        why = res.get("explanation") or "not recognised"
        fb_key = hashlib.sha1(f"{req.path}\x00{' '.join(req.question.casefold().split())}".encode()).hexdigest()
        fb = _fb_cache_get(fb_key)
        if fb is None:
            fb = _run_router({**q, "source": "upload", "kind": "pdf-vector" if q["ext"] == "pdf" else "raster"},
                             timeout=FALLBACK_TIMEOUT_S)
            fb["route"] = f"{res.get('route', '-')} -> {fb.get('route', 'generic')}"
            fb["cost_usd"] = (fb.get("cost_usd") or 0.0) + (res.get("cost_usd") or 0.0)
            if fb.get("method") not in ("timeout", "error"):
                _fb_cache_put(fb_key, fb)
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
    _ask_charge(request, res)
    res["latency_s"] = round(time.time() - t0, 3)
    res["type"] = q["type"]
    res["source"] = q["source"]
    res["gold"] = known["answer"] if known else None
    res["baseline_cost_usd"] = BASELINE_COST.get(q["source"], BASELINE_COST.get("_all", 0.0))
    res["baseline_latency_s"] = BASELINE_LATENCY.get(q["source"], BASELINE_LATENCY.get("_all", 0.0))
    try:
        _name_items(res, q.get("question") or "")
    except Exception:  # noqa: BLE001  a nicer label never breaks an answer
        traceback.print_exc()
    if q["source"] == "upload":
        _fix_upload_evidence(res, q, req.path)
        _upload_honesty(res, q)
        _gpu_second_pending(res, q, req.path)
    try:  # every text-evidence box on the text it cites: moved there, or dropped as "not located"
        _locate_evidence(res, req.path)
    except Exception:  # noqa: BLE001  a check never breaks an answer
        traceback.print_exc()
    res.pop("raw", None)
    if res.get("error") not in (None, "timeout", "internal error"):  # raw exception / CLI text: log, don't return
        print(f"ask error ({res.get('method')}): {str(res['error'])[:500]}", flush=True)
        res["error"] = "internal error"
    try:
        res["question_id"] = known["id"] if known else None
        res["calibration"] = calibration_for(res)
        if q["source"] == "upload" and res["calibration"] and res["calibration"].get("measured"):
            # the track record is from clean dataset drawings; an upload (a photo, another drawing style) is not
            # that population, so the UI says "no track record yet" instead of borrowing the number
            res["calibration_dataset"] = res["calibration"]
            res["calibration"] = {**res["calibration"], "measured": False}
        res["trace"] = trace_for(res, q)
        res["rule"] = rule_for(res, q)
        res["frontier"] = frontier_for([x["id"] for x in same]) if known else []
    except Exception:  # noqa: BLE001  the extras never break an answer
        traceback.print_exc()
    if q["source"] == "upload":
        try:  # an ambiguous question (which room, closet doors, net or gross): a structured follow-up (app/projects.py)
            from app import projects

            res = projects.postprocess(res, picks)
            res["clarify"] = projects.clarify_for(res, asked, req.path, res.get("page") or 0)
        except Exception:  # noqa: BLE001  a follow-up never breaks an answer
            traceback.print_exc()
    try:
        res["speak_id"] = _speak_remember(res, req.question)
    except Exception:  # noqa: BLE001  nor does the spoken version
        traceback.print_exc()
    try:
        return JSONResponse(json.loads(json.dumps(res, default=str)))
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return _abstain("could not serialise the answer", method="error")


# ---------------------------------------------------------------- on-demand GPU for the live second opinion
# bp/vlm/gpu_power.py: with BP_GPU_HOOK_URL set the VLM box is started when a raster plan is uploaded and stopped
# after BP_GPU_IDLE_MIN idle minutes. An upload's answer never waits for it: the answer carries
# "second_pending": {"key", "eta_s"} and the UI polls GET /api/upload_second/{key}, which computes the live second
# opinion once the box is ready. Without a hook nothing here changes behaviour (the box is always on, or off).

_gpu_pending: collections.OrderedDict = collections.OrderedDict()  # key -> {q, primary, client_path, status, cc}
_gpu_pending_lock = threading.Lock()
GPU_PENDING_MAX = 500


def _gpu():
    from bp.vlm.gpu_power import get_power

    return get_power()


def _gpu_warm(m: dict):
    """Upload of a single-page raster residential plan: start the box now (it boots while the user types)."""
    try:
        sh = m.get("sheets") or {}
        pages = sh.get("pages") or []
        if os.environ.get("BP_VLM_URL") and m.get("kind") == "raster" and (m.get("n_pages") or sh.get("n_pages") or 1) == 1 \
                and any(x.get("residential_plan") for x in pages) and _gpu().hooked:
            _gpu().ensure_started()
    except Exception:  # noqa: BLE001  warming never breaks an upload
        traceback.print_exc()


def _gpu_second_pending(res: dict, q: dict, client_path: str):
    """An upload answer that would have had a live VLM second opinion if the box were up: start it (non-blocking)
    and tell the UI where to poll for that opinion."""
    try:
        from bp.crosscheck import VLM_METHOD, _vlm_upload_ok

        cc = res.get("crosscheck")
        if res.get("answer") is None or cc is None or not _vlm_upload_ok(q):
            return
        if ((cc.get("second") or {}).get("method")) == VLM_METHOD:
            return  # already has it (the box was ready)
        pw = _gpu()
        if not pw.hooked:
            return
        st = pw.ensure_started()
        if st not in ("starting", "ready"):
            return  # refused (daily cap) or the hook is failing: the answer simply has no live second opinion
        key = hashlib.sha1(f"{client_path}\x00{q.get('question')}".encode()).hexdigest()[:16]
        prim = {k: res.get(k) for k in ("answer", "method", "confidence")}
        with _gpu_pending_lock:
            if key not in _gpu_pending or _gpu_pending[key]["status"] == "unavailable":
                _gpu_pending[key] = {"q": dict(q), "primary": prim, "client_path": client_path, "status": "warming",
                                     "cc": None, "t": time.time()}
            _gpu_pending.move_to_end(key)
            while len(_gpu_pending) > GPU_PENDING_MAX:
                _gpu_pending.popitem(last=False)
        res["second_pending"] = {"key": key, "eta_s": round(pw.eta_s()), "state": st}
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def _gpu_compute(key: str):
    with _gpu_pending_lock:
        p = _gpu_pending.get(key)
    if p is None:
        return
    try:
        from bp.crosscheck import VLM_METHOD, crosscheck

        cc = crosscheck(p["q"], p["primary"])
        sec = cc.get("second") or {}
        if sec.get("method") != VLM_METHOD:
            p["status"] = "unavailable"
            return
        _fix_upload_evidence(sec, p["q"], p["client_path"])
        p["cc"], p["status"] = json.loads(json.dumps(cc, default=str)), "ready"
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        p["status"] = "unavailable"


@app.get("/api/gpu")
def gpu_status():
    """{state: off|starting|ready, eta_s, spent_today, cap_usd, hooked, ...} of the live-VLM box."""
    try:
        return _gpu().status()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return {"state": "off", "eta_s": None, "spent_today": None, "hooked": False}


@app.get("/api/upload_second/{key}")
def upload_second(key: str):
    """Poll for the live second opinion of an upload answer that carried second_pending.
    {"status": "warming", "eta_s"} | {"status": "computing"} | {"status": "ready", "crosscheck", "confidence"} |
    {"status": "unavailable"} (the box was refused / failed to boot / gave no answer: show nothing)."""
    if not re.fullmatch(r"[0-9a-f]{16}", key):
        raise HTTPException(404, "unknown key")
    with _gpu_pending_lock:
        p = _gpu_pending.get(key)
    if p is None:
        raise HTTPException(404, "unknown key")
    if p["status"] == "ready":
        cc, conf = p["cc"], p["primary"].get("confidence")
        if cc.get("status") == "conflict" and conf is not None:  # the router's rule: a conflict halves confidence
            conf = round(conf * 0.5, 4)
        return {"status": "ready", "crosscheck": cc, "confidence": conf}
    if p["status"] in ("computing", "unavailable"):
        return {"status": p["status"]}
    pw = _gpu()
    st = pw.state()
    if st == "off":
        st = pw.ensure_started()  # a failed start is retried (the hook call is rate-limited inside)
        if st == "refused" or time.time() - p["t"] > pw.boot_max_s:
            p["status"] = "unavailable"
            return {"status": "unavailable"}
    if st == "ready":
        with _gpu_pending_lock:
            if p["status"] != "warming":
                return {"status": p["status"]}
            p["status"] = "computing"
        threading.Thread(target=_gpu_compute, args=(key,), daemon=True).start()
        return {"status": "computing"}
    return {"status": "warming", "eta_s": round(pw.eta_s())}


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


def _feedback_limit(request: Request):
    _bucket(_fb_hits, request, FEEDBACK_N, FEEDBACK_S,
            "too many corrections from this visitor; please try again later", lock=_hits_lock)


@app.post("/api/feedback")
def feedback(fb: Feedback, request: Request):
    """A visitor's correction (items dropped / added on the drawing) -> one JSON line in cache/corrections.jsonl,
    to be reviewed and folded into the next training run. No IP, no upload file name, no free-form notes."""
    _feedback_limit(request)
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


SIGNOFFS = Path("cache/signoffs.jsonl")


class Signoff(BaseModel):
    path: str
    question: str
    question_id: int | None = None
    answer: float | str | None = None
    corrected_answer: float | None = None
    method: str | None = None
    confidence: float | None = None
    initials: str
    session: str | None = None


@app.post("/api/signoff")
def signoff(so: Signoff, request: Request):
    """A reviewer marked an answer as checked -> one line in cache/signoffs.jsonl (initials as typed, no IP)."""
    _feedback_limit(request)
    if so.path.startswith("uploads/"):
        path = "/".join(so.path.split("/")[:2])
    elif so.path in BY_PATH:
        path = so.path
    else:
        raise HTTPException(404, "unknown drawing")
    who = re.sub(r"[\x00-\x1f]", "", so.initials).strip()[:40]
    if not who:
        raise HTTPException(400, "initials required")
    row = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "path": path,
           "question_id": so.question_id, "question": so.question[:500],
           "answer": so.answer if not isinstance(so.answer, str) else so.answer[:500],
           "corrected_answer": so.corrected_answer, "method": (so.method or "")[:60], "confidence": so.confidence,
           "initials": who, "session": re.sub(r"[^A-Za-z0-9]", "", so.session or "")[:16] or None}
    SIGNOFFS.parent.mkdir(parents=True, exist_ok=True)
    with _fb_lock, open(SIGNOFFS, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True}


# ---------------------------------------------------------------- room schedule (heat-map + takeoff sheet)

@app.get("/api/rooms")
def rooms(request: Request, path: str):
    """Every numbered room of a Swiss plan (apartment, net area, outline on the page) and the symbol counts, read
    from the CAD twin the solver uses: the heat-map and the printable takeoff sheet. $0, no model call."""
    _heavy_limit(request)
    if path not in BY_PATH or "swiss_dwellings/" not in path:  # the dataset index, never a client-built path
        raise HTTPException(404, "room schedules exist for the Swiss CAD plans only")
    from bp.solvers.swiss import FILL_COMMON, SwissSolver
    try:
        fl = SwissSolver().floor_for({"path": path})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"could not read the CAD twin: {type(e).__name__}")
    if fl is None or not fl.to_page:
        raise HTTPException(404, "no CAD twin for this drawing")
    out = []
    for r in fl.rooms:
        if not r.number or r.poly.area <= 0:
            continue
        out.append({"number": r.number, "name": r.name or "", "unit": r.unit, "area": round(r.area, 2),
                    "outdoor": bool(r.outdoor), "shaft": bool(r.shaft_void), "common": r.fill == FILL_COMMON,
                    "points": fl.norm_poly(r.poly)})
    out.sort(key=lambda r: (r["unit"] or "~", r["number"]))
    counts = collections.Counter(s.kind for s in fl.symbols if s.kind != "other")
    return {"path": path, "rooms": out, "units": sorted(fl.unit_labels), "counts": dict(counts), "credit": credit_for(path)}


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
    for name in ("overall", "by_source_type", "by_language", "selective_by_family"):
        f = Path("analysis/out") / f"{name}.csv"
        if f.exists():
            with open(f, newline="") as fh:
                out[name] = list(csv.DictReader(fh))
    return out


@app.get("/api/calibration")
def calibration():
    """Per-method calibration table (what each confidence band meant on the held-out test split)."""
    return CALIB


@app.get("/api/stats")
def stats():
    """Headline numbers (ALL row) of every test-split run."""
    out = {}
    for r in results()["runs"]:
        allrow = next((x for x in r["sections"].get("By type", []) if x["group"] == "ALL"), None)
        if allrow and r["split"] == "test":
            out[r["name"]] = {"n": allrow["n"], "accuracy": allrow["accuracy"], "usd_per_1k": allrow["usd_per_1k"]}
    return out


# ---------------------------------------------------------------- ask by voice: ElevenLabs speech-to-text (Scribe)
# The browser records the question (MediaRecorder: webm/opus, ogg/opus or Safari's mp4/aac) and posts the raw audio
# here; we forward it to ElevenLabs and return only the text. The audio is never stored. Without a key the endpoint
# answers 503 and the page falls back to the browser's own speech recognition (or hides the mic).
# ELEVENLABS_API_KEY      from the environment, else data/secrets/elevenlabs.env
# BP_STT_DAILY_USD_CAP    daily budget for transcription (default $2); spend is logged per call to BP_STT_LEDGER
# BP_STT_USD_PER_HOUR     price per audio hour (ElevenLabs lists Scribe at $0.22-0.40/h by plan; 0.40 = worst case)
STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
STT_MODEL = os.environ.get("BP_STT_MODEL", "scribe_v2")
STT_USD_PER_S = float(os.environ.get("BP_STT_USD_PER_HOUR", 0.40) or 0.40) / 3600
STT_DAILY_CAP = float(os.environ.get("BP_STT_DAILY_USD_CAP", 2) or 0)
STT_LEDGER = Path(os.environ.get("BP_STT_LEDGER", "cache/stt_spend.jsonl"))
STT_MAX_BYTES, STT_MAX_S, STT_TIMEOUT_S = 2 * 1024 * 1024, 60, 20
_stt_lock = threading.Lock()


def _stt_key() -> str:
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"].strip()
    for f in (Path("data/secrets/elevenlabs.env"), APP.parent / "data/secrets/elevenlabs.env"):
        try:
            for line in f.read_text().splitlines():
                k, _, v = line.partition("=")
                if k.strip() == "ELEVENLABS_API_KEY" and v.strip():
                    return v.strip().strip("'\"")
        except OSError:
            continue
    return ""


def _stt_spent_today() -> float:
    day, tot = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"), 0.0
    try:
        lines = STT_LEDGER.read_text().splitlines()
    except OSError:
        return 0.0
    for line in lines:
        try:
            r = json.loads(line)
            tot += float(r.get("cost_usd") or 0) if r.get("day") == day else 0.0
        except (ValueError, AttributeError):
            continue
    return tot


def _stt_audio_kind(body: bytes) -> str | None:
    """Sniff the container from its magic bytes (never trust the Content-Type alone)."""
    if body[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if body[:4] == b"OggS":
        return "ogg"
    if body[4:8] == b"ftyp":
        return "mp4"
    return None


def _stt_call(audio: bytes, kind: str, lang: str | None, key: str) -> dict:
    """POST the audio to ElevenLabs as multipart/form-data (stdlib only: the demo image has no HTTP client)."""
    import urllib.error
    import urllib.request
    import uuid

    b = uuid.uuid4().hex
    fields = {"model_id": STT_MODEL, "tag_audio_events": "false", "timestamps_granularity": "none"}
    if lang:
        fields["language_code"] = lang
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    mime = {"webm": "audio/webm", "ogg": "audio/ogg", "mp4": "audio/mp4"}[kind]
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="question.{kind}"\r\n'
                 f'Content-Type: {mime}\r\n\r\n'.encode() + audio + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(STT_URL, data=b"".join(parts), method="POST", headers={
        "xi-api-key": key, "Content-Type": f"multipart/form-data; boundary={b}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=STT_TIMEOUT_S) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        print(f"[stt] ElevenLabs HTTP {e.code}: {detail}", flush=True)
        if e.code == 429:
            raise HTTPException(429, "the speech-to-text service is busy; please try again in a moment or type")
        raise HTTPException(502, "speech-to-text failed; please type the question instead")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[stt] ElevenLabs unreachable: {type(e).__name__}", flush=True)
        raise HTTPException(504, "speech-to-text timed out; please try again or type the question")


@app.get("/api/transcribe")
def transcribe_info():
    """Whether server-side speech-to-text is on (the page then records audio instead of using the browser's)."""
    if not _stt_key():
        return {"available": False}
    return {"available": True, "provider": "ElevenLabs", "max_s": STT_MAX_S,
            "over_cap": bool(STT_DAILY_CAP) and _stt_spent_today() >= STT_DAILY_CAP}


@app.post("/api/transcribe")
async def transcribe(request: Request, lang: str = "", secs: float = 0.0):
    """Raw-body audio upload: POST /api/transcribe?lang=fi&secs=3.2 with the recording as body -> {text, language}.
    `lang` is a hint (ISO-639-1, or a BCP-47 tag like fi-FI); empty = detect. `secs` is the recorded length."""
    from starlette.concurrency import run_in_threadpool

    key = _stt_key()
    if not key:
        raise HTTPException(503, "voice transcription is not configured on this server")
    _rate_limit(request)
    if secs > STT_MAX_S:
        raise HTTPException(413, f"recording too long (max {STT_MAX_S} s)")
    if int(request.headers.get("content-length") or 0) > STT_MAX_BYTES:
        raise HTTPException(413, "recording too large (max 2 MB)")
    body = await request.body()
    if len(body) > STT_MAX_BYTES:
        raise HTTPException(413, "recording too large (max 2 MB)")
    if len(body) < 200:
        raise HTTPException(400, "empty recording")
    kind = _stt_audio_kind(body)
    if kind is None:
        raise HTTPException(415, "unsupported audio: send webm/opus, ogg/opus or mp4 from MediaRecorder")
    code = lang.strip().split("-")[0].lower()
    code = code if re.fullmatch(r"[a-z]{2,3}", code) else None
    est = max(secs, 1.0) * STT_USD_PER_S
    if STT_DAILY_CAP and _stt_spent_today() + est > STT_DAILY_CAP:  # at most a few cents can slip past in parallel
        raise HTTPException(429, "voice input has used up today's budget on this public demo; "
                                     "please type the question (it works just as well)")
    t0 = time.time()
    r = await run_in_threadpool(_stt_call, body, kind, code, key)
    dur = float(r.get("audio_duration_secs") or 0) or max(secs, 1.0)
    cost = round(dur * STT_USD_PER_S, 8)
    rec = {"day": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"), "ts": round(time.time(), 1),
           "model": STT_MODEL, "audio_s": round(dur, 2), "bytes": len(body), "kind": kind, "lang_hint": code,
           "language": r.get("language_code"), "latency_s": round(time.time() - t0, 2), "cost_usd": cost}
    with _stt_lock:
        STT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with STT_LEDGER.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    text = re.sub(r"\s*\((?:[^()]{1,40})\)\s*", " ", r.get("text") or "").strip()  # drop any "(laughter)" tags
    return {"text": text, "language": r.get("language_code"), "language_probability": r.get("language_probability"),
            "audio_s": round(dur, 2)}



# ---------------------------------------------------------------- spoken answers: ElevenLabs text-to-speech
# Each /api/ask answer gets a `speak_id`; POST /api/speak {id, lang} turns that answer into one short sentence in the
# question's language (app/speak.py builds it from the stored answer: the browser never sends text, so this is not a
# free TTS service) and returns it as audio/mpeg. Audio is cached in memory by text; every paid call is logged.
# ELEVENLABS_TTS_API_KEY  a separate key for TTS if set (environment or data/secrets/elevenlabs.env), else the STT key
# BP_TTS_VOICE / BP_TTS_MODEL   stock voice id (default "George", calm narrator) and model (Flash v2.5: ~100 ms,
#                               32 languages incl. fi/sv/nl, $0.04 per 1K characters on the ElevenLabs API price list)
# BP_TTS_DAILY_USD_CAP    daily budget (default $2); BP_TTS_LEDGER the JSONL spend log; BP_TTS_RATE "<n>/<s>" per IP
# A key without the text_to_speech permission answers 401/403 "missing_permissions": the feature then reports
# available:false and is re-checked every BP_TTS_RECHECK_S (180 s), so enabling it lights the button up, no restart.
TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format={fmt}"
TTS_VOICE = os.environ.get("BP_TTS_VOICE", "JBFqnCBsd6RMkjVDRZzb")
TTS_MODEL = os.environ.get("BP_TTS_MODEL", "eleven_flash_v2_5")
TTS_FORMAT = os.environ.get("BP_TTS_FORMAT", "mp3_44100_64")
TTS_USD_PER_CHAR = float(os.environ.get("BP_TTS_USD_PER_1K_CHARS", 0.04) or 0.04) / 1000
TTS_DAILY_CAP = float(os.environ.get("BP_TTS_DAILY_USD_CAP", 2) or 0)
TTS_LEDGER = Path(os.environ.get("BP_TTS_LEDGER", "cache/tts_spend.jsonl"))
_TTS_RL = os.environ.get("BP_TTS_RATE", "") or "20/600"
TTS_RATE_N, TTS_RATE_S = (int(x) for x in _TTS_RL.split("/"))
TTS_TIMEOUT_S, TTS_MAX_CHARS, TTS_RECHECK_S = 15, 300, float(os.environ.get("BP_TTS_RECHECK_S", 180) or 180)
_tts_lock = threading.Lock()
_tts_hits: dict[str, collections.deque] = collections.defaultdict(collections.deque)
_tts_state = {"ok": None, "checked": 0.0, "key": ""}  # ok: None = not checked yet, False = key lacks TTS permission
_tts_audio: collections.OrderedDict[str, bytes] = collections.OrderedDict()  # sha1(voice, model, lang, text) -> mp3
_speak_answers: collections.OrderedDict[str, dict] = collections.OrderedDict()  # speak_id -> what the answer was
TTS_CACHE_N, SPEAK_ANSWERS_N = 300, 5000


class TTSUnavailable(Exception):
    pass


def _tts_key() -> str:
    if os.environ.get("ELEVENLABS_TTS_API_KEY"):
        return os.environ["ELEVENLABS_TTS_API_KEY"].strip()
    for f in (Path("data/secrets/elevenlabs.env"), APP.parent / "data/secrets/elevenlabs.env"):
        try:
            for line in f.read_text().splitlines():
                k, _, v = line.partition("=")
                if k.strip() == "ELEVENLABS_TTS_API_KEY" and v.strip():
                    return v.strip().strip("'\"")
        except OSError:
            continue
    return _stt_key()


def _speak_remember(res: dict, question: str, lang_hint: str | None = None) -> str:
    """Keep what /api/speak needs to say this answer; the id is the only thing the browser sends back."""
    from app.speak import detect_lang, norm_lang

    sid = os.urandom(8).hex()
    rec = {"question": (question or "")[:500], "answer": res.get("answer"), "type": res.get("type"),
           "method": res.get("method"), "crosscheck": {"status": (res.get("crosscheck") or {}).get("status")},
           "lang": norm_lang(lang_hint) or detect_lang(question)}
    c = res.get("calibration") or {}
    rec["calibration"] = {"measured": c.get("measured"), "right": c.get("right"), "n": c.get("n")}
    if isinstance(rec["answer"], str):
        rec["answer"] = rec["answer"][:2000]
    with _tts_lock:
        _speak_answers[sid] = rec
        while len(_speak_answers) > SPEAK_ANSWERS_N:
            _speak_answers.popitem(last=False)
    return sid


def _tts_spent_today() -> float:
    day, tot = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"), 0.0
    try:
        lines = TTS_LEDGER.read_text().splitlines()
    except OSError:
        return 0.0
    for line in lines:
        try:
            r = json.loads(line)
            tot += float(r.get("cost_usd") or 0) if r.get("day") == day else 0.0
        except (ValueError, AttributeError):
            continue
    return tot


def _tts_log(text: str, lang: str, latency: float, kind: str = "speak"):
    rec = {"day": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"), "ts": round(time.time(), 1),
           "kind": kind, "model": TTS_MODEL, "voice": TTS_VOICE, "lang": lang, "chars": len(text),
           "latency_s": round(latency, 2), "cost_usd": round(len(text) * TTS_USD_PER_CHAR, 8)}
    with _tts_lock:
        TTS_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with TTS_LEDGER.open("a") as f:
            f.write(json.dumps(rec) + "\n")


def _tts_call(text: str, lang: str, key: str) -> bytes:
    """POST the sentence to ElevenLabs; raise TTSUnavailable when the key is not allowed to use text-to-speech."""
    import urllib.error
    import urllib.request

    body = json.dumps({"text": text, "model_id": TTS_MODEL, "language_code": lang}).encode()
    req = urllib.request.Request(TTS_URL.format(voice=TTS_VOICE, fmt=TTS_FORMAT), data=body, method="POST", headers={
        "xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=TTS_TIMEOUT_S) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        print(f"[tts] ElevenLabs HTTP {e.code}: {detail}", flush=True)
        if e.code in (401, 403):
            raise TTSUnavailable(detail)
        if e.code == 429:
            raise HTTPException(429, "the text-to-speech service is busy; please try again in a moment")
        raise HTTPException(502, "text-to-speech failed")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[tts] ElevenLabs unreachable: {type(e).__name__}", flush=True)
        raise HTTPException(504, "text-to-speech timed out")


def _tts_mark(key: str, ok: bool):
    _tts_state.update(ok=ok, checked=time.time(), key=hashlib.sha1(key.encode()).hexdigest())


def _tts_ok(probe: bool = True) -> bool:
    """Is text-to-speech usable with the current key? A new key, or a refusal older than TTS_RECHECK_S, is probed
    once with a two-character sentence (a fraction of a cent, logged like any other call)."""
    key = _tts_key()
    if not key:
        return False
    st = _tts_state
    if st["key"] and st["key"] != hashlib.sha1(key.encode()).hexdigest():
        st["ok"] = None  # the key in the file changed: forget what the old one could do
    stale = st["ok"] is None or (st["ok"] is False and time.time() - st["checked"] > TTS_RECHECK_S)
    if stale and probe and _tts_probe_lock.acquire(blocking=False):
        try:
            t0 = time.time()
            _tts_call("OK.", "en", key)
            _tts_log("OK.", "en", time.time() - t0, kind="probe")
            _tts_mark(key, True)
        except TTSUnavailable:
            _tts_mark(key, False)
        except HTTPException:
            pass  # busy / unreachable: not a verdict on the key, try again next time
        finally:
            _tts_probe_lock.release()
    return st["ok"] is not False


_tts_probe_lock = threading.Lock()


class Speak(BaseModel):
    id: str
    lang: str | None = None


@app.get("/api/speak")
def speak_info():
    """Whether spoken answers are on (the page shows the "Read aloud" button and speaks voice questions' answers)."""
    if not _tts_ok():
        return {"available": False}
    return {"available": True, "provider": "ElevenLabs", "over_cap": bool(TTS_DAILY_CAP) and
            _tts_spent_today() >= TTS_DAILY_CAP, "recheck_s": TTS_RECHECK_S}


@app.post("/api/speak")
def speak(req: Speak, request: Request):
    """{id: the answer's speak_id, lang: optional ISO code} -> audio/mpeg of one short sentence about that answer."""
    import urllib.parse

    from app.speak import norm_lang, sentence

    _heavy_limit(request)
    if not re.fullmatch(r"[0-9a-f]{16}", req.id or ""):
        raise HTTPException(400, "bad answer id")
    with _tts_lock:
        rec = _speak_answers.get(req.id)
    if rec is None:
        raise HTTPException(404, "that answer is no longer on the server; ask again to hear it")
    lang = norm_lang(req.lang) or rec["lang"]
    text = sentence(rec, lang)[:TTS_MAX_CHARS]
    ck = hashlib.sha1(f"{TTS_VOICE}\x00{TTS_MODEL}\x00{TTS_FORMAT}\x00{lang}\x00{text}".encode()).hexdigest()
    hdr = {"Cache-Control": "private, max-age=3600", "X-Speak-Lang": lang,
           "X-Speak-Text": urllib.parse.quote(text, safe=" ,.;:!?'-%")}
    with _tts_lock:
        audio = _tts_audio.get(ck)
        if audio is not None:
            _tts_audio.move_to_end(ck)
    if audio is not None:
        return Response(audio, media_type="audio/mpeg", headers={**hdr, "X-Speak-Cache": "hit"})
    key = _tts_key()
    if not key or not _tts_ok(probe=False):
        raise HTTPException(503, "spoken answers are not available on this server")
    _bucket(_tts_hits, request, TTS_RATE_N, TTS_RATE_S, "too many spoken answers for this visitor; "
                                                         "please wait a few minutes")
    if TTS_DAILY_CAP and _tts_spent_today() + len(text) * TTS_USD_PER_CHAR > TTS_DAILY_CAP:
        raise HTTPException(429, "spoken answers have used up today's budget on this public demo")
    t0 = time.time()
    try:
        audio = _tts_call(text, lang, key)
    except TTSUnavailable:
        _tts_mark(key, False)
        raise HTTPException(503, "spoken answers are not available on this server")
    _tts_mark(key, True)
    _tts_log(text, lang, time.time() - t0)
    if len(audio) < 100:
        raise HTTPException(502, "text-to-speech returned no audio")
    with _tts_lock:
        _tts_audio[ck] = audio
        while len(_tts_audio) > TTS_CACHE_N:
            _tts_audio.popitem(last=False)
    return Response(audio, media_type="audio/mpeg", headers={**hdr, "X-Speak-Cache": "miss"})

from app import projects as _projects  # noqa: E402  projects: several uploads asked as one (app/projects.py)

_projects.install(app)

# ---------------------------------------------------------------- pages

@app.api_route("/", methods=["GET", "HEAD"])
def index():
    return HTMLResponse(_with_root((STATIC / "index.html").read_text()))


@app.api_route("/results", methods=["GET", "HEAD"])
def results_page():
    return HTMLResponse(_with_root((STATIC / "results.html").read_text()))


@app.api_route("/how", methods=["GET", "HEAD"])
def how_page():
    return HTMLResponse(_with_root((STATIC / "how.html").read_text()))


@app.api_route("/static/{name}", methods=["GET", "HEAD"])
def static(name: str, request: Request):
    p = (STATIC / name).resolve()
    if not p.is_relative_to(STATIC.resolve()) or not p.exists():
        raise HTTPException(404)
    if ROOT_PATH and p.suffix in (".js", ".html"):
        # rewritten per request, so no file ETag: hash the bytes we send and let no-cache revalidate with a 304
        body = _with_root(p.read_text()).encode()
        etag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
        hdr = {"Cache-Control": "no-cache", "ETag": etag}
        inm = request.headers.get("if-none-match", "")
        if etag in [t.strip().removeprefix("W/") for t in inm.split(",")]:
            return Response(status_code=304, headers=hdr)
        mt = "text/javascript" if p.suffix == ".js" else "text/html"
        return Response(body, media_type=mt, headers=hdr)
    return FileResponse(p, headers={"Cache-Control": "no-cache"})
