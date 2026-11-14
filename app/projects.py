"""Projects: several uploads (a building's floor plans, a few buildings, a drawing set) asked as one.

A project is a small JSON file (cache/projects/<id>.json) listing its uploads and every sheet page in them, with
the sheet id, title, floor / level and kind read off each one. Each file goes through the ordinary upload
(app/server.py: size limits, the memory gate, rate limits and the preparation all apply unchanged); a .zip is
unpacked member by member into the same upload path.

Questions on a project (POST /api/projects/<id>/ask):
  - a sheet id ("on A-101") or a level ("on Level 01", "2nd floor", "Kellari", "1. krs") picks that sheet;
  - "in the whole building" / "total ... of the school" asks every floor plan of the building and sums them, with
    the per-floor parts (each with its own marks) in the answer;
  - sheets of different buildings are never mixed unless the question asks for all buildings;
  - an ambiguous question (which floor, which room, closet doors, net or gross area) comes back with
    `clarify: {question, options: [{label, value}]}`: each option's value is the question with the choice
    appended, ready to ask again; a best-guess answer is still given when there is one (`best_guess: true`).

The same clarify for a single upload is added to /api/ask by `clarify_for` (rooms and areas; sheets of one file).
"""
from __future__ import annotations

import concurrent.futures as cf
import difflib
import json
import re
import secrets
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

PROJECTS = Path("cache/projects")
MAX_FILES = 20
MAX_PAGES = 300
MAX_PARTS = 12             # sheets asked for one whole-building answer
ZIP_MAX_TOTAL = 400 * 1024 * 1024  # uncompressed bytes of all members of one .zip
ZIP_MAX_RATIO = 200        # a member that inflates more than this is a zip bomb
_ID = re.compile(r"[0-9a-f]{12}")
_lock = threading.Lock()
_pool = cf.ThreadPoolExecutor(4, thread_name_prefix="project")
router = APIRouter()


def S():
    from app import server

    return server


# ---------------------------------------------------------------- floors and buildings read from titles / names

_ORD = {"ground": 0, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
        "eighth": 8, "ninth": 9, "tenth": 10}


def level_of(text: str) -> dict | None:
    """{"n": sort order, "label": as written} for the floor a title (or a question) names, else None.
    "Level 00", "L01", "2nd floor", "Ground floor", "Floor 3", "Basement", "Kellari", "1. krs", "kerros 2", "Roof"."""
    t = re.sub(r"[_]+", " ", text or "")
    m = re.search(r"\blevel\s*(-?\d{1,2})\b", t, re.I) or re.search(r"\blvl\.?\s*(-?\d{1,2})\b", t, re.I)
    if m:
        return {"n": int(m.group(1)), "label": f"Level {m.group(1)}"}
    m = re.search(r"\b(\d{1,2})\s*(?:st|nd|rd|th)\s+(?:floor|storey|story)\b", t, re.I)
    if m:
        return {"n": int(m.group(1)), "label": m.group(0).strip().capitalize()}
    m = re.search(r"\b(ground|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+(?:floor|storey|story)\b",
                  t, re.I)
    if m:
        return {"n": _ORD[m.group(1).lower()], "label": m.group(0).strip().capitalize()}
    m = re.search(r"\b(?:floor|storey|story)\s*(\d{1,2})\b", t, re.I)
    if m:
        return {"n": int(m.group(1)), "label": f"Floor {m.group(1)}"}
    m = re.search(r"\b(\d)\s*\.?\s*(?:krs|kerros)\b", t, re.I) or re.search(r"\bkerros\s*(\d)\b", t, re.I)
    if m:
        return {"n": int(m.group(1)), "label": f"{m.group(1)}. krs"}
    m = re.search(r"\b(basement|cellar|kellari\w*|lower ground)\b", t, re.I)
    if m:
        return {"n": -1, "label": m.group(1).capitalize()}
    m = re.search(r"\bL(\d{2})\b", t)
    if m:
        return {"n": int(m.group(1)), "label": f"Level {m.group(1)}"}
    m = re.search(r"\broof\s+(?:plan|level)\b", t, re.I)
    if m:
        return {"n": 99, "label": "Roof"}
    return None


_BSTOP = set("""plan plans ga general arrangement floor floors level levels lvl sheet sheets drawing drawings dwg layout
proposed existing the of and rev revision final issue copy scan scanned page krs kerros pohja pohjapiirros kellari
basement cellar ground first second third fourth fifth sixth roof lower upper hires screenshot png jpg jpeg pdf for
construction set architectural arch foundation slab piping mechanical electrical structural plumbing hvac reflected
ceiling elevation elevations section sections detail details site finish finishes furniture storey story view key
north south east west part area with new copy final tender planning landscape masterplan""".split())


def building_of(name: str, title: str = "") -> str:
    """A building name from a file name (else its title), with codes, levels and sheet words dropped:
    "SEN-DFE-XX-00-D-X-0201-Special_School_Plan_Level_00-A-C01.pdf" -> "Special school"; "" when nothing is left."""
    for src in (Path(name).stem, title or ""):
        src = re.sub(r"([a-z])([A-Z])", r"\1 \2", src)
        toks = [w for w in re.findall(r"[A-Za-z]+", src)
                if len(w) > 2 and not (w.isupper() and len(w) <= 4) and w.lower() not in _BSTOP]
        if toks:
            return " ".join(toks[:4]).lower().capitalize()
    return ""


def kind_of_title(title: str) -> str | None:
    t = (title or "").upper()
    if re.search(r"PIPING|MECHANICAL|PLUMBING", t):
        return "piping"
    if re.search(r"SLAB|FOUNDATION", t):
        return "slab"
    if re.search(r"FLOOR PLAN|GA PLAN|SCHOOL PLAN|\bLEVEL\b|\bFLOOR\b|POHJA|KRS", t):
        return "arch"
    return None


# ---------------------------------------------------------------- storage

def _file(pid: str) -> Path:
    if not _ID.fullmatch(pid or ""):
        raise HTTPException(404, "unknown project")
    return PROJECTS / f"{pid}.json"


def load(pid: str) -> dict:
    f = _file(pid)
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        raise HTTPException(404, "unknown project (projects are cleared when the server is rebuilt)") from None


def _save(p: dict):
    PROJECTS.mkdir(parents=True, exist_ok=True)
    f = _file(p["id"])
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(p))
    tmp.replace(f)


def _buildings(p: dict):
    """Sheets with no building name join the project's only named building, if it has exactly one."""
    named = sorted({s["building_raw"] for s in p["sheets"] if s.get("building_raw")})
    for s in p["sheets"]:
        if s.get("building_fixed"):
            continue
        s["building"] = s.get("building_raw") or (named[0] if len(named) == 1 else "Unnamed building")


def _sheets_of(d: dict, name: str) -> list[dict]:
    """The sheets of one prepared upload (server.upload's answer)."""
    srv = S()
    key = d["path"].split("/")[1]
    try:
        meta = srv._upload_meta(d["path"])
    except Exception:  # noqa: BLE001
        meta = {}
    n = int(d.get("pages") or 1)
    idx = {x["page"]: x for x in meta.get("page_index") or []}
    is_set = srv._is_set(meta)
    drawing = set(d.get("drawing_pages") or [])
    out = []
    for pg in range(n):
        x = idx.get(pg) or {}
        sid = (x.get("sheet_id") or "") if is_set else ""
        if n > 1:
            title = x.get("title") or (d.get("page_titles") or {}).get(str(pg)) or f"Page {pg + 1}"
        else:
            title = d.get("sheet_title") or ""
        kind = ((meta.get("page_kinds") or {}).get(str(pg)) or kind_of_title(title)) if n > 1 else \
            (d.get("sheet_kind") or kind_of_title(title))
        lv = level_of(title) or (level_of(name) if n == 1 else None)
        if not sid:
            m = re.search(r"\b([A-Z]{1,2}-\d{3}[A-Z]?)\b", f"{title} {Path(name).stem}")
            sid = m.group(1) if m else ""
        out.append({"ref": f"{key}:{pg}", "path": d["path"], "page": pg, "pages": n, "file": name,
                    "sheet_id": sid, "title": title.strip()[:90], "level": lv, "kind": kind or None,
                    "building_raw": building_of(name, title) if n == 1 else building_of(name),
                    "view": d.get("view"), "not_drawing": bool(d.get("not_drawing")),
                    "drawing": (pg in drawing) if drawing else True})
    return out


def _add(pid: str, d: dict, name: str) -> dict:
    with _lock:
        p = load(pid)
        if any(f["path"] == d["path"] for f in p["files"]):
            return p
        if len(p["files"]) >= MAX_FILES:
            raise HTTPException(413, f"a project holds at most {MAX_FILES} files")
        new = _sheets_of(d, name)
        if len(p["sheets"]) + len(new) > MAX_PAGES:
            raise HTTPException(413, f"a project holds at most {MAX_PAGES} pages; this file would make it "
                                     f"{len(p['sheets']) + len(new)}")
        p["files"].append({"path": d["path"], "name": name, "pages": len(new), "kind": d.get("kind")})
        p["sheets"].extend(new)
        _buildings(p)
        p["updated"] = time.time()
        _save(p)
        return p


def public(p: dict) -> dict:
    sheets = sorted(p["sheets"], key=lambda s: (s["building"], (s["level"] or {}).get("n", 50), s["file"], s["page"]))
    return {"id": p["id"], "name": p.get("name") or "", "files": p["files"], "sheets": sheets,
            "buildings": sorted({s["building"] for s in p["sheets"]}),
            "limits": {"files": MAX_FILES, "pages": MAX_PAGES}}


# ---------------------------------------------------------------- endpoints: create, list, upload

class NewProject(BaseModel):
    name: str = ""


@router.post("/api/projects")
def create(body: NewProject, request: Request):
    S()._heavy_limit(request)
    pid = secrets.token_hex(6)
    p = {"id": pid, "name": re.sub(r"[^\w .,'()-]+", "", body.name)[:80], "created": time.time(), "files": [],
         "sheets": []}
    with _lock:
        _save(p)
    return public(p)


@router.get("/api/projects/{pid}")
def get(pid: str):
    return public(load(pid))


class _Member:
    """One .zip member handed to the ordinary upload as if it were its own request body."""

    def __init__(self, request: Request, zf: zipfile.ZipFile, info: zipfile.ZipInfo):
        self.client, self._zf, self._info = request.client, zf, info
        self.headers = {"content-length": str(info.file_size)}

    async def stream(self):
        with self._zf.open(self._info) as fh:
            while chunk := fh.read(1 << 20):
                yield chunk


def _zip_members(zf: zipfile.ZipFile, room: int) -> list[zipfile.ZipInfo]:
    srv = S()
    ok_ext = srv.UPLOAD_EXT | srv.CONVERT_EXT
    out, total = [], 0
    for i in zf.infolist():
        nm = i.filename.replace("\\", "/")
        base = nm.rsplit("/", 1)[-1]
        if i.is_dir() or "__MACOSX" in nm or base.startswith(".") or not base:
            continue
        if Path(base).suffix.lower() not in ok_ext:
            continue  # readmes, nested archives, CAD formats we can't read: skipped, listed in "skipped"
        if i.file_size > srv.MAX_UPLOAD or (i.compress_size and i.file_size / i.compress_size > ZIP_MAX_RATIO
                                            and i.file_size > 10 * 1024 * 1024):
            raise HTTPException(413, f"{base} in the archive is too large once unpacked")
        total += i.file_size
        if total > ZIP_MAX_TOTAL:
            raise HTTPException(413, f"the archive unpacks to more than {ZIP_MAX_TOTAL // 2 ** 20} MB")
        out.append(i)
    if not out:
        raise HTTPException(415, "the archive holds no drawings (PDF, image, DXF or IFC)")
    if len(out) > room:
        raise HTTPException(413, f"the archive holds {len(out)} drawings; this project has room for {room} more "
                                 f"(at most {MAX_FILES} files)")
    return out


@router.post("/api/projects/{pid}/upload")
async def upload(pid: str, request: Request, name: str, rid: str = ""):
    """Raw-body upload into a project: one drawing (exactly as POST /api/upload) or a .zip of drawings."""
    srv = S()
    p = load(pid)
    room = MAX_FILES - len(p["files"])
    if room <= 0:
        raise HTTPException(413, f"a project holds at most {MAX_FILES} files")
    if Path(name).suffix.lower() != ".zip":
        d = await srv.upload(request, name, rid)
        p = _add(pid, d, Path(name).name)
        return {"uploads": [d], "skipped": [], "project": public(p)}
    srv._rate_limit(request)
    try:
        if int(request.headers.get("content-length") or 0) > srv.MAX_UPLOAD:
            raise HTTPException(413, "file too large (max 200 MB)")
    except ValueError:
        raise HTTPException(400, "bad Content-Length") from None
    srv.UPLOADS.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkstemp(dir=srv.UPLOADS, prefix=".incoming_zip_")[1])
    ups, skipped = [], []
    try:
        size = 0
        with open(tmp, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > srv.MAX_UPLOAD:
                    raise HTTPException(413, "file too large (max 200 MB)")
                fh.write(chunk)
        try:
            zf = zipfile.ZipFile(tmp)
        except zipfile.BadZipFile:
            raise HTTPException(422, "could not open this .zip: it may be damaged") from None
        with zf:
            for info in _zip_members(zf, room):
                base = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
                try:
                    d = await srv.upload(_Member(request, zf, info), base, rid)
                except HTTPException as e:
                    skipped.append({"name": base, "why": str(e.detail)})
                    continue
                try:
                    p = _add(pid, d, base)
                except HTTPException as e:
                    skipped.append({"name": base, "why": str(e.detail)})
                    break
                ups.append(d)
    finally:
        tmp.unlink(missing_ok=True)
    return {"uploads": ups, "skipped": skipped, "project": public(load(pid))}


class SheetFix(BaseModel):
    ref: str
    building: str | None = None
    level: str | None = None


@router.post("/api/projects/{pid}/sheet")
def fix_sheet(pid: str, body: SheetFix):
    """The judge corrects what was read off a sheet: its building or its floor."""
    with _lock:
        p = load(pid)
        s = next((s for s in p["sheets"] if s["ref"] == body.ref), None)
        if s is None:
            raise HTTPException(404, "unknown sheet")
        if body.building is not None and body.building.strip():
            s["building"], s["building_fixed"] = body.building.strip()[:60], True
        if body.level is not None:
            s["level"] = level_of(body.level) or ({"n": 50, "label": body.level.strip()[:30]}
                                                  if body.level.strip() else None)
        _save(p)
    return public(p)


# ---------------------------------------------------------------- asking a project

class ProjectAsk(BaseModel):
    question: str
    sheet: str | None = None  # the sheet the judge is looking at (ref): the best guess when the question is unclear


WHOLE = re.compile(r"\b(whole|entire|all (?:the )?(?:floors|levels|storeys|stories|plans)|every (?:floor|level|storey)|"
                   r"each (?:floor|level)|per (?:floor|level)|building total)\b|\b(?:in|of|for|across)\s+the\s+"
                   r"(?:building|school|house|project|hospital|office|block|dormitory|dorm)\b", re.I)
ALL_BUILDINGS = re.compile(r"\b(all|both|every|each) (?:the )?buildings\b|\b(?:whole|entire) project\b|"
                           r"\bacross (?:the )?(?:project|buildings)\b", re.I)
_SCOPE_STRIP = [
    r"\b(?:in|of|for|across|on)\s+(?:all\s+)?(?:the\s+)?(?:whole|entire)\s+[a-z]+\b",
    r"\b(?:in|of|for|across)\s+the\s+(?:building|school|house|project|hospital|office|block|dormitory|dorm)\b",
    r"\b(?:on|in|across|for)\s+(?:all|every|each)\s+(?:the\s+)?(?:floors?|levels?|storeys?|stories|plans?)\b",
    r"\b(?:all|every|each|per)\s+(?:floors?|levels?|storeys?)\b", r"\bbuilding total\b",
    r"\b(?:in|across|for)\s+(?:all|both|every|each)\s+(?:the\s+)?buildings\b",
    r"\b(?:on|in|at|for)\s+(?:the\s+)?(?:level|lvl\.?)\s*-?\d{1,2}\b", r"\b(?:level|lvl\.?)\s*-?\d{1,2}\b",
    r"\b(?:on|in|at|for)\s+the\s+(?:\d{1,2}(?:st|nd|rd|th)|ground|first|second|third|fourth|fifth|top)\s+"
    r"(?:floor|storey|story)\b",
    r"\b(?:\d{1,2}(?:st|nd|rd|th)|ground|first|second|third|fourth|fifth)\s+(?:floor|storey|story)\b",
    r"\b(?:on|in|at)\s+(?:the\s+)?(?:basement|cellar|kellari\w*)\b", r"\b\d\s*\.?\s*(?:krs|kerros)\w*\b",
]
# appended by a clarify option; read back here, never sent to a specialist as words to match
_PICK = re.compile(r"\s*\((room|closets|area|building|sheet): ([^)]*)\)", re.I)


def _picks(q: str) -> tuple[str, dict]:
    picks = {m.group(1).lower(): m.group(2).strip() for m in _PICK.finditer(q)}
    return _PICK.sub("", q).strip(), picks


def strip_scope(q: str, names: list[str] = ()) -> str:
    out = q
    for rx in _SCOPE_STRIP:
        out = re.sub(rx, " ", out, flags=re.I)
    for nm in names:
        if nm:
            out = re.sub(r"\b(?:in|of|for|at)\s+(?:the\s+)?" + re.escape(nm) + r"\b", " ", out, flags=re.I)
    out = re.sub(r"\s+([?.,!])", r"\1", re.sub(r"\s{2,}", " ", out)).strip()
    return out or q


def _plan_sheets(sheets: list[dict]) -> list[dict]:
    """Floor plans: architectural sheets (or unclassified ones) that are drawings; with levels known on some,
    only those with a level (a site plan or a detail sheet is not a floor)."""
    s = [x for x in sheets if x["drawing"] and not x["not_drawing"] and x.get("kind") in (None, "arch")]
    if sum(1 for x in s if x.get("level")) >= 2:
        s = [x for x in s if x.get("level")]
    return sorted(s, key=lambda x: ((x.get("level") or {}).get("n", 50), x["file"], x["page"]))


def label(s: dict) -> str:
    lv = (s.get("level") or {}).get("label")
    return " · ".join(x for x in (lv, s.get("sheet_id")) if x) or s.get("title") or s["file"]


def _num(r: dict):
    a = r.get("answer")
    if isinstance(a, bool):
        return None
    if isinstance(a, (int, float)):
        return float(a)
    v = r.get("value")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _run(s: dict, question: str, request: Request) -> dict:
    srv = S()
    req = srv.Ask(path=s["path"], question=question, page=s["page"] if s["pages"] > 1 else None)
    try:
        resp = srv.ask(req, request)
        r = json.loads(resp.body) if hasattr(resp, "body") else dict(resp)
    except HTTPException as e:
        r = {"answer": None, "confidence": 0.0, "evidence": [], "method": "error", "explanation": str(e.detail)}
    r["question"] = question
    return r


def _part(s: dict, r: dict) -> dict:
    return {"ref": s["ref"], "label": label(s), "title": s["title"], "sheet_id": s["sheet_id"],
            "level": (s.get("level") or {}).get("label"), "path": s["path"], "page": s["page"], "view": s.get("view"),
            "pages": s["pages"], "answer": r.get("answer"), "value": _num(r), "unit": r.get("unit"),
            "method": r.get("method"), "result": r}


def _found(r: dict) -> bool:
    return r.get("answer") is not None and r.get("method") != "sheets-rooms-ask" and not r.get("not_found")


def _opt(label_: str, question: str, suffix: str) -> dict:
    return {"label": label_, "value": f"{question.rstrip()} {suffix}".strip()}


def _room_labels(r: dict) -> list[str]:
    labs = []
    for e in r.get("evidence") or []:
        if e.get("kind") == "polygon" and e.get("label"):
            lb = re.sub(r"\s+[\d.,]+\s*m²$", "", str(e["label"])).strip()
            if lb and lb != "unlabelled" and lb not in labs:
                labs.append(lb)
    return labs


def _pick_room(r: dict, room: str) -> dict:
    """Keep only the rooms named `room` (a clarify pick) in a multi-room area answer."""
    ev = [e for e in r.get("evidence") or [] if e.get("kind") != "polygon"
          or re.sub(r"\s+[\d.,]+\s*m²$", "", str(e.get("label") or "")).strip().lower() == room.lower()]
    vals = [e["value"] for e in ev if e.get("kind") == "polygon" and isinstance(e.get("value"), (int, float))]
    if not vals:
        return r
    tot = round(sum(vals), 1)
    return {**r, "answer": tot, "evidence": ev, "method": "sheets-rooms-area",
            "explanation": f"{room} (picked): " + " + ".join(f"{v:.1f}" for v in vals) + f" = {tot} m²; "
                           + str(r.get("explanation") or "").split("; ", 1)[-1]}


CLOSET = re.compile(r"\b(closets?|wardrobes?|walk-?in|w\.?i\.?c\.?|komero|vaatehuone|linen)\b", re.I)


def _sheet_text(path: str, page: int) -> str:
    try:
        srv = S()
        p = srv.resolve(path)
        if p.suffix.lower() != ".pdf":
            return ""
        from bp.sheets import _pdf_text

        return _pdf_text(str(p), page) or ""
    except Exception:  # noqa: BLE001
        return ""


def clarify_for(r: dict, question: str, path: str | None = None, page: int = 0) -> dict | None:
    """A follow-up question when the answer depends on something the question left open (room, closets, net or
    gross); None when the question is clear. Options carry the full question to ask next."""
    q, picks = _picks(question)
    ql = q.lower()
    m = str(r.get("method") or "")
    if m == "sheets-rooms-ask" and "room" not in picks:
        mm = re.search(r"Rooms I can read: (.*?)\. Which one", str(r.get("explanation") or ""))
        names = [n.strip() for n in (mm.group(1).split(",") if mm else []) if n.strip() and n.strip() != "none"]
        if names:
            try:
                from bp.sheets.rooms import query_words

                qw = " ".join(query_words(q))
            except Exception:  # noqa: BLE001
                qw = ""
            names.sort(key=lambda n: -difflib.SequenceMatcher(None, qw, n.lower()).ratio())
            return {"question": "Which room do you mean?", "kind": "room",
                    "options": [_opt(n, question, f"(room: {n})") for n in names[:6]]}
    if m == "sheets-rooms-area-sum" and "room" not in picks:
        labs = _room_labels(r)
        if len(labs) > 1:
            return {"question": "Several rooms match. Which one?", "kind": "room",
                    "options": [_opt(lb, question, f"(room: {lb})") for lb in labs[:6]]
                    + [_opt(f"All {len(labs)} together", question, "(room: all)")]}
    if r.get("answer") is not None and re.search(r"\bdoors?\b", ql) and not CLOSET.search(ql) \
            and "closets" not in picks and path:
        txt = _sheet_text(path, page)
        if CLOSET.search(txt):
            return {"question": "Count closet doors too? Left out by default.", "kind": "closets",
                    "options": [_opt("Leave closet doors out", question, "(closets: without closet doors)"),
                                _opt("Count closet doors", question, "(closets: with closet doors)")]}
    if r.get("answer") is not None and re.search(r"\barea\b", ql) and re.search(r"\b(total|floor area|building)\b", ql) \
            and not re.search(r"\b(net|gross|footprint|usable|internal)\b", ql) and "area" not in picks \
            and str(m).startswith("sheets-rooms"):
        try:
            from bp.sheets.rooms import query_words

            if query_words(q):
                return None
        except Exception:  # noqa: BLE001
            pass
        return {"question": "Net or gross floor area?", "kind": "area",
                "options": [_opt("Net (sum of rooms)", question, "(area: net)"),
                            _opt("Gross (outside of the walls)", question, "(area: gross)")]}
    return None


def _apply_picks(q: str, picks: dict) -> str:
    """The specialist's wording of a clarify pick."""
    if picks.get("area") == "gross":
        q = re.sub(r"\?$", "", q) + " (gross footprint)?"
    elif picks.get("area") == "net":
        q = re.sub(r"\?$", "", q) + " (net)?"
    if picks.get("room") and picks["room"] != "all":
        try:
            from bp.sheets.rooms import intent as room_intent
            it = room_intent(q)
        except Exception:  # noqa: BLE001
            it = "area"
        q = f"Baseboard length in the {picks['room']}?" if it == "baseboard" else f"What is the area of the {picks['room']}?"
    return q


def prepare_question(raw: str) -> tuple[str, dict]:
    """(what the specialist is asked, the clarify picks) for a question that may carry picks."""
    q, picks = _picks(raw)
    return _apply_picks(q, picks), picks


def postprocess(r: dict, picks: dict) -> dict:
    if picks.get("room") and picks["room"] != "all" and r.get("method") == "sheets-rooms-area-sum":
        r = _pick_room(r, picks["room"])
    if picks.get("closets") and r.get("answer") is not None:
        r = dict(r)
        keep = picks["closets"].startswith("with ")
        r["explanation"] = (f"you asked for closet doors to be {'counted' if keep else 'left out'}; the door reader does "
                            "not tell closet doors apart yet, so check the marks on closets"
                            + ("" if keep else " and untick any to drop them") + " | "
                            + str(r.get("explanation") or ""))
    return r


def _which(sheets: list[dict], question: str, kind: str) -> dict:
    opts = [_opt(label(s), question, f"(sheet: {s['ref']})") for s in sheets[:8]]
    if kind == "floor":
        opts.append(_opt("Whole building (sum)", question, "(sheet: all)"))
    return {"question": "Which floor?" if kind == "floor" else "Which sheet?", "kind": kind, "options": opts}


@router.post("/api/projects/{pid}/ask")
def ask(pid: str, body: ProjectAsk, request: Request):
    srv = S()
    p = load(pid)
    if not p["sheets"]:
        raise HTTPException(400, "this project has no sheets yet: upload a drawing first")
    t0 = time.time()
    raw = srv._fix_typos(body.question.strip())[:500]
    q, picks = _picks(raw)
    sheets = p["sheets"]
    by_ref = {s["ref"]: s for s in sheets}
    current = by_ref.get(body.sheet or "")
    buildings = sorted({s["building"] for s in sheets})
    named_b = [b for b in buildings if b and b.lower() in q.lower()]
    if picks.get("building") and picks["building"] in buildings:
        named_b = [picks["building"]]
    all_b = bool(ALL_BUILDINGS.search(q)) or picks.get("building") == "all"
    clean = _apply_picks(strip_scope(q, buildings), picks)
    plans = _plan_sheets(sheets)
    scope_note = ""

    # 1. an explicit sheet: a clarify pick, a sheet id, or a level
    chosen: list[dict] = []
    if picks.get("sheet") and picks["sheet"] in by_ref:
        chosen = [by_ref[picks["sheet"]]]
        scope_note = f"{label(chosen[0])} (picked)"
    whole = bool(WHOLE.search(q)) or picks.get("sheet") == "all" or all_b
    if not chosen and not picks.get("sheet"):
        from bp.generic import sheetindex

        idx = [{"page": i, "sheet_id": s["sheet_id"]} for i, s in enumerate(sheets) if s["sheet_id"]]
        hit = sheetindex.find(q, idx)
        if hit is not None:
            chosen = [sheets[hit]]
            scope_note = f"sheet {sheets[hit]['sheet_id']} (named in the question)"
        else:
            lv = level_of(q)
            if lv:
                pool = [s for s in (plans or sheets) if (s.get("level") or {}).get("n") == lv["n"]] or \
                       [s for s in sheets if (s.get("level") or {}).get("n") == lv["n"]]
                if named_b:
                    pool = [s for s in pool if s["building"] in named_b]
                chosen = pool
                scope_note = f"{lv['label']} (named in the question)"
                if not pool:
                    have = ", ".join(sorted({label(s) for s in plans})) or "none"
                    return _reply({"answer": None, "confidence": 0.0, "evidence": [], "method": "project-none",
                                   "explanation": f"no sheet in this project is {lv['label']}; the floors it has: {have}",
                                   "not_found": {"what": lv["label"], "options": [
                                       {"label": label(s), "question": f"{clean.rstrip('?')} on {label(s)}?"}
                                       for s in plans[:6]]}}, q, raw, p, t0)
    if len(chosen) > 1:  # the same level in two buildings: which one?
        bs = sorted({s["building"] for s in chosen})
        if len(bs) > 1:
            best = _run(chosen[0], clean, request)
            return _reply(best, q, raw, p, t0, sheet=chosen[0], best_guess=True, clarify={
                "question": "Which building?", "kind": "building",
                "options": [_opt(b, raw, f"(building: {b})") for b in bs]}, note=f"{label(chosen[0])} of {chosen[0]['building']}")
        chosen = chosen[:1]
    if chosen and not whole:
        s = chosen[0]
        r = postprocess(_run(s, clean, request), picks)
        return _reply(r, q, raw, p, t0, sheet=s, note=scope_note, clarify=clarify_for(r, raw, s["path"], s["page"]))

    # 2. the whole building (or every building, when asked)
    if whole:
        bset = buildings if all_b else named_b or ([current["building"]] if current and len(buildings) > 1 else buildings)
        if len(bset) > 1 and not all_b:
            guess_b = bset[0]
            return _whole(p, plans, [guess_b], clean, raw, q, picks, request, t0, best_guess=True, clarify={
                "question": "Which building?", "kind": "building",
                "options": [_opt(b, raw, f"(building: {b})") for b in bset] + [_opt("All buildings", raw, "(building: all)")]})
        return _whole(p, plans, bset, clean, raw, q, picks, request, t0)

    # 3. nothing named: one floor plan, a room to look for, or ask which floor
    pool = [s for s in plans if not named_b or s["building"] in named_b]
    if current and len(buildings) > 1 and not named_b:
        pool = [s for s in pool if s["building"] == current["building"]] or pool
    if not pool:
        pool = [current] if current else sheets[:1]
    if len(pool) == 1:
        s = pool[0]
        r = postprocess(_run(s, clean, request), picks)
        return _reply(r, q, raw, p, t0, sheet=s, clarify=clarify_for(r, raw, s["path"], s["page"]),
                      note="the only floor plan" if len(sheets) > 1 else "")
    try:
        from bp.sheets.rooms import intent as room_intent, query_words
        roomq = bool(room_intent(clean)) and bool(query_words(clean))
    except Exception:  # noqa: BLE001
        roomq = False
    guess = current if current in pool else pool[0]
    if roomq:  # "the area of the hall": look for it on every floor, answer where it is
        rs = list(_pool.map(lambda s: (s, _run(s, clean, request)), pool[:MAX_PARTS]))
        hits = [(s, r) for s, r in rs if _found(r)]
        if len(hits) == 1:
            s, r = hits[0]
            r = postprocess(r, picks)
            others = ", ".join(label(x) for x, _ in rs if x is not s)
            return _reply(r, q, raw, p, t0, sheet=s, note=f"{label(s)}, the only floor where it was found"
                          + (f" (looked on {others} too)" if others else ""),
                          clarify=clarify_for(r, raw, s["path"], s["page"]))
        if len(hits) > 1:
            s, r = next(((s, r) for s, r in hits if s is guess), hits[0])
            r = postprocess(r, picks)
            return _reply(r, q, raw, p, t0, sheet=s, best_guess=True, note=f"{label(s)} (found on {len(hits)} floors)",
                          clarify=_which([x for x, _ in hits], raw, "floor"))
        s, r = next(((s, r) for s, r in rs if s is guess), rs[0])
        return _reply(r, q, raw, p, t0, sheet=s, note=f"not found on any of the {len(rs)} floors",
                      clarify=clarify_for(r, raw, s["path"], s["page"]))
    r = postprocess(_run(guess, clean, request), picks)
    return _reply(r, q, raw, p, t0, sheet=guess, best_guess=r.get("answer") is not None,
                  note=f"{label(guess)} ({'the sheet you are viewing' if guess is current else 'the first floor plan'})",
                  clarify=_which(pool, raw, "floor"))


def _whole(p, plans, bset, clean, raw, q, picks, request, t0, best_guess=False, clarify=None):
    parts_s = [s for s in plans if s["building"] in bset][:MAX_PARTS]
    if not parts_s:
        raise HTTPException(400, "no floor plans found in this project")
    rs = list(_pool.map(lambda s: (s, postprocess(_run(s, clean, request), picks)), parts_s))
    parts = [_part(s, r) for s, r in rs]
    units = {x["unit"] or "" for x in parts if x["value"] is not None}
    vals = [x["value"] for x in parts]
    t = S().guess_type(clean)
    summable = t in ("count", "area", "length") or all(isinstance(x["answer"], (int, float)) for x in parts)
    who = " + ".join(bset) if len(bset) > 1 else bset[0]
    res = {"answer": None, "confidence": 0.0, "evidence": [], "method": "project-sum", "cost_usd": 0.0,
           "unit": next(iter(units)) if len(units) == 1 else None, "type": t}
    res["cost_usd"] = round(sum((r.get("cost_usd") or 0.0) for _, r in rs), 4)
    if summable and parts and all(v is not None for v in vals) and len(units) <= 1:
        tot = sum(vals)
        res["answer"] = int(tot) if t == "count" and float(tot).is_integer() else round(tot, 1)
        res["confidence"] = round(min((r.get("confidence") or 0.0) for _, r in rs), 2)
        res["explanation"] = f"{who}: " + " + ".join(f"{x['label']} {x['value']:g}" for x in parts) + \
            f" = {res['answer']:g}" + (f" {res['unit']}" if res["unit"] else "") + \
            f" ({len(parts)} floor plans, each read on its own sheet; open a floor to see its marks)"
    else:
        miss = [x["label"] for x in parts if x["value"] is None]
        res["tentative_answer"] = sum(v for v in vals if v is not None) if any(v is not None for v in vals) else None
        res["explanation"] = (f"{who}: no total, because " + (f"{', '.join(miss)} could not be read"
                              if miss else "the floors' answers are not numbers that add up")
                              + "; each floor's own answer is listed")
    clar = clarify
    if clar is None and parts:
        c0 = clarify_for(rs[0][1], raw, rs[0][0]["path"], rs[0][0]["page"])
        if c0 and c0.get("kind") in ("closets", "area"):
            clar = c0
    out = {**res, "project": {"id": p["id"], "scope": "project" if len(bset) > 1 else "building",
                              "building": who, "parts": parts, "sheet": None,
                              "why": f"summed over every floor plan of {who}"},
           "clarify": clar, "best_guess": bool(best_guess and res["answer"] is not None),
           "question": raw, "latency_s": round(time.time() - t0, 3), "source": "upload"}
    return JSONResponse(json.loads(json.dumps(out, default=str)))


def _reply(r, q, raw, p, t0, sheet=None, best_guess=False, clarify=None, note=""):
    out = dict(r)
    out["question"] = raw
    out["project"] = {"id": p["id"], "scope": "sheet", "sheet": sheet and {k: sheet.get(k) for k in (
        "ref", "path", "page", "pages", "view", "sheet_id", "title", "level", "building", "file")},
        "label": label(sheet) if sheet else "", "parts": [], "why": note}
    out["clarify"] = clarify
    out["best_guess"] = bool(best_guess and clarify and r.get("answer") is not None)
    out["latency_s"] = round(time.time() - t0, 3)
    return JSONResponse(json.loads(json.dumps(out, default=str)))


def install(app):
    app.include_router(router)
