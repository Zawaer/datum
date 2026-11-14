"""What is on each page of an uploaded file: one cheap vision call on a contact sheet of the pages.

Used for real-world uploads (bp/solvers/generic.py, app/server.py):
- is the page a construction drawing at all (a text document or a holiday photo must not get "0 doors")?
- which pages are drawings, and what each one shows (to pick the page a question is about in a set)?
- is it turned sideways (scans and phone photos often are)?
- does it look like a residential floor plan of the kind the CubiCasa detector was trained on?

One haiku call (~$0.002) per upload; the result is stored in the upload's meta.json.
"""
from __future__ import annotations

import re

from bp.generic import llm, text as T

MAX_PAGES = 16  # thumbnails on one contact sheet
KINDS = ("floor plan", "site plan", "elevation", "section", "detail", "schedule / table sheet", "cover / index sheet",
         "3d render of a plan", "text document", "photo", "other")

PROMPT = """{intro}
For each page, reply with what it is. JSON only:
{{"pages": [{{"page": <number>, "kind": one of {kinds},
  "drawing": true if it is an architectural / construction / engineering drawing, plan, sheet or schedule, or a
             photo / scan / screenshot of one; false for text documents, forms, ordinary photos, charts, blank pages,
  "upright": true if most of the text and labels on the page read normally (left to right); false if the page is
             turned sideways or upside down,
  "turn": 0, 90, 180 or 270 (clockwise degrees that would make most text read normally; 0 if upright),
  "title": "<the sheet title or what it shows, at most 8 words>",
  "residential_plan": true if it is a floor plan of one flat or house (walls, door swings, window symbols,
             room names) of the real-estate brochure kind, false otherwise}}]}}"""


def _sheet(path: str, pages: list[int]):
    """Contact sheet image of the given pages (numbered), or one page image."""
    from PIL import Image, ImageDraw

    if len(pages) == 1:
        return T.render(path, pages[0], max_side=1280)
    cols = 4 if len(pages) > 6 else 3 if len(pages) > 4 else 2
    rows = -(-len(pages) // cols)
    cell = 1500 // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), "white")
    d = ImageDraw.Draw(sheet)
    for i, p in enumerate(pages):
        im = T.render(path, p, max_side=cell - 12)
        x, y = (i % cols) * cell, (i // cols) * cell
        if im is not None:
            sheet.paste(im, (x + 6 + (cell - 12 - im.width) // 2, y + 6 + (cell - 12 - im.height) // 2))
        d.rectangle([x + 1, y + 1, x + cell - 2, y + cell - 2], outline=(150, 150, 150), width=2)
        d.rectangle([x + 2, y + 2, x + 60, y + 40], fill=(220, 0, 0))
        d.text((x + 12, y + 8), str(p + 1), fill="white", font_size=26)
    return sheet


def check(path: str, model: str = "haiku") -> dict:
    """{"n_pages", "pages": [{page (0-based), kind, drawing, turn, title, residential_plan}], "cost_usd"}.
    Never raises: on any failure it returns what it has with "error" set (callers treat unknown as 'maybe')."""
    out = {"n_pages": 1, "pages": [], "cost_usd": 0.0}
    try:
        n = T.n_pages(path)
        out["n_pages"] = n
        pages = list(range(min(n, MAX_PAGES)))
        img = _sheet(path, pages)
        if img is None:
            out["error"] = "no page image"
            return out
        intro = ("This is the only page of a file a user uploaded to a construction-drawing Q&A tool." if n == 1 else
                 f"These are pages 1-{len(pages)} of a {n}-page file a user uploaded to a construction-drawing Q&A "
                 "tool, each numbered in its red top-left label.")
        r = llm.ask(PROMPT.format(intro=intro, kinds=" | ".join(f'"{k}"' for k in KINDS)), [img], model=model,
                    tag="sheets", timeout=60)
        out["cost_usd"] = r["cost_usd"]
        d = llm.parse_json(r["text"])
        items = d.get("pages") if isinstance(d, dict) else d if isinstance(d, list) else None
        if not isinstance(items, list):
            out["error"] = (r.get("error") or "unparsed reply")[:200]
            return out
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                p = int(it.get("page", 0)) - 1
            except (TypeError, ValueError):
                continue
            if not 0 <= p < len(pages) or any(x["page"] == p for x in out["pages"]):
                continue
            turn = it.get("turn") if it.get("upright") is False else 0
            try:
                turn = int(turn) % 360 if int(turn) in (0, 90, 180, 270) else 0
            except (TypeError, ValueError):
                turn = 0
            out["pages"].append({"page": p, "kind": str(it.get("kind") or "other")[:40],
                                 "drawing": it.get("drawing") is not False, "turn": turn,
                                 "title": str(it.get("title") or "")[:80],
                                 "residential_plan": it.get("residential_plan") is True})
        out["pages"].sort(key=lambda x: x["page"])
        for p in out["pages"]:
            if p["turn"] in (90, 270) and p["residential_plan"]:
                # brochure plans often letter half their rooms vertically: "sideways" is a style there, and the
                # symbol detector and the VLM count just as well either way, so they are left as drawn
                p["turn"] = 0
            if p["turn"] and p["drawing"]:  # the model sees *that* a page is sideways reliably, not which way
                p["turn"], c = _which_turn(path, p["page"], model)
                out["cost_usd"] += c
    except Exception as e:  # noqa: BLE001  never block an upload on this check
        out["error"] = f"{type(e).__name__}: {str(e)[:160]}"
    return out


def _which_turn(path: str, page: int, model: str) -> tuple[int, float]:
    """(clockwise turn that makes the page's text read normally, cost): the page as it is and turned three ways
    (A-D). Plans often carry some vertical labels, so "as it is" stays a choice and wins ties."""
    from PIL import Image, ImageDraw

    im = T.render(path, page, max_side=800)
    turns = (0, 90, 270, 180)
    views = [im.rotate(-t, expand=True) for t in turns]
    cell = max(max(v.size) for v in views)
    sheet = Image.new("RGB", (cell * 2, cell * 2 + 100), "white")
    d = ImageDraw.Draw(sheet)
    for i, v in enumerate(views):
        x, y = (i % 2) * cell, (i // 2) * (cell + 50)
        sheet.paste(v, (x + (cell - v.width) // 2, y + 50 + (cell - v.height) // 2))
        d.text((x + cell // 2 - 10, y + 8), "ABCD"[i], fill=(220, 0, 0), font_size=34)
    r = llm.ask('The same drawing is shown four times (A, B, C, D), turned different ways. In which one do the '
                'title block, notes and most room labels read normally, left to right and not upside down? Some '
                'labels on plans are always vertical; judge by the majority and the longest texts. Reply JSON only: '
                '{"upright": "A" | "B" | "C" | "D"}', [sheet], model=model, tag="sheets-turn", timeout=60)
    d = llm.parse_json(r["text"])
    pick = str(d.get("upright", "")).strip().upper() if isinstance(d, dict) else ""
    return (turns["ABCD".index(pick)] if pick in ("A", "B", "C", "D") else 0), r["cost_usd"]


def page_info(sheets: dict | None, page: int) -> dict | None:
    for p in (sheets or {}).get("pages") or []:
        if p.get("page") == page:
            return p
    return None


def not_a_drawing(sheets: dict | None) -> str | None:
    """'a text document' etc. when the check says no page is a drawing; None if any page is (or unknown)."""
    ps = (sheets or {}).get("pages") or []
    if not ps or any(p.get("drawing") for p in ps):
        return None
    kinds = sorted({p.get("kind") or "other" for p in ps})
    return " / ".join(kinds)


_STOP = {"the", "of", "on", "in", "is", "are", "how", "many", "what", "which", "this", "that", "and", "for", "with",
         "does", "do", "an", "to", "by", "be", "there", "shown", "drawn", "total", "all", "plan", "drawing", "sheet",
         "page", "floor", "number"}


def _toks(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9][a-z0-9.\-]+", s.lower()) if t not in _STOP}


_picked: dict = {}


def _ask_page(path: str, question: str, cands: list[int], model: str = "haiku") -> int | None:
    """One cheap vision call: which of these pages answers the question? (cached per file + question)"""
    key = (path, question)
    if key in _picked:
        return _picked[key]
    img = _sheet(path, cands[:MAX_PAGES]) if len(cands) > 1 else None
    if img is None:
        return None
    r = llm.ask(f'These are pages of one drawing file, each numbered in its red top-left label. A user asks: '
                f'"{question}". Which single page should be looked at to answer it? Reply JSON only: '
                '{"page": <number>}', [img], model=model, tag="sheets-pick", timeout=60)
    d = llm.parse_json(r["text"])
    try:
        p = int(d.get("page")) - 1 if isinstance(d, dict) else None
    except (TypeError, ValueError):
        p = None
    _picked[key] = p if p in cands[:MAX_PAGES] else None
    return _picked[key]


def pick_page(path: str, question: str, sheets: dict | None, qtype: str | None = None) -> tuple[int, str]:
    """Best page of a multi-page file for a question that needs the picture (vision path).
    (page, why). Scores: words of the question on the page (text layer + checked title), then drawing pages,
    then floor plans for counts of drawn things."""
    n = T.n_pages(path)
    if n <= 1:
        return 0, ""
    qt = _toks(question)
    best, why = None, ""
    doc = None
    if path.lower().endswith(".pdf"):
        try:
            import pymupdf

            doc = pymupdf.open(path)
        except Exception:  # noqa: BLE001
            doc = None
    for p in range(min(n, 400)):
        info = page_info(sheets, p) or {}
        if info and not info.get("drawing"):
            continue
        txt = info.get("title", "")
        try:
            if doc is not None:
                txt += " " + doc[p].get_text()
        except Exception:  # noqa: BLE001
            pass
        title_hits = len(qt & _toks(info.get("title", "")))
        hits = len(qt & _toks(txt))
        plan = 1 if "plan" in (info.get("kind") or "") else 0
        score = (title_hits * 3 + hits, plan if qtype == "count" else 0, 1 if info else 0, -p)
        if best is None or score > best[0]:
            best = (score, p)
            why = (f"page {p + 1} of {n}" + (f" ({info['title']})" if info.get("title") else "")
                   + (" matches the question's words" if score[0] else " is the first drawing page"
                      if info else ""))
    cands = [p for p in range(min(n, MAX_PAGES)) if (page_info(sheets, p) or {}).get("drawing", True)]
    if best and best[0][0] == 0 and len(cands) > 1:  # no words decide: let a model look at the pages
        try:
            p = _ask_page(path, question, cands)
        except Exception:  # noqa: BLE001
            p = None
        if p is not None:
            info = page_info(sheets, p) or {}
            return p, f"page {p + 1} of {n}" + (f" ({info['title']})" if info.get("title") else "") + \
                " (picked by looking at all pages)"
    return (best[1], why) if best else (0, f"page 1 of {n}")
