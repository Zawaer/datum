"""Sheet ids and titles of every page of a multi-page drawing set, from the PDF's vector text (no rendering, no model).

A judge may upload a whole set (150+ sheets). At upload (app/server.py: _prep_pdf) each page's title block is read
from its text layer (~10 ms a page): the sheet id ("M-101A") is the largest sheet-id-looking word in the lower-right
title block, and the title is the biggest remaining text there once the lines printed on most pages (the project
name, the firm) are dropped. A question that names a sheet ("How many check valves on M-101A?") is then answered on
that page (`find`), and the UI's page picker lists the ids and titles.
"""
from __future__ import annotations

import re
from collections import Counter

# A-101, M-101A, S-100B, MH102, FA503, G-001, E1.01, A2.1: one to three letters, then digits
_ID = re.compile(r"^([A-Z]{1,3})[-.]?(\d{1,3}(?:\.\d{1,2})?[A-Z]?)$")
_LABELS = re.compile(r"\b(SHEET|SHT|DWG|DRAWING)\b\.?\s*(ID|NO|NUMBER|#)?\b", re.I)
_NOISE = re.compile(r"^(SHEET|ID|NO\.?|SCALE|DATE|DRAWN|CHECKED|APPROVED|REV(ISION)?|OF|PROJECT|TITLE|NTS|"
                    r"AS SHOWN|DESIGNED|BY|SUBMITTED)$", re.I)
MAX_PAGES = 600


def _lines(pg):
    """Text lines of a page as displayed (rotation applied): [(text, (x0, y0, x1, y1) normalised, size)]."""
    import pymupdf

    R = pg.rotation_matrix
    W, H = (pg.rect.width or 1), (pg.rect.height or 1)
    groups: dict = {}
    for x0, y0, x1, y1, t, b, ln, _ in pg.get_text("words"):
        groups.setdefault((b, ln), []).append((x0, y0, x1, y1, t))
    out = []
    for ws in groups.values():
        r = pymupdf.Rect(min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws), max(w[3] for w in ws))
        r = r * R
        r.normalize()
        # font size ~ the line's thickness: its height when it reads across, its width when it runs up the sheet
        # (read off the line's longest word, whose box is longer along the text than across it)
        lw = max(ws, key=lambda w: len(w[4]))
        size = min(lw[2] - lw[0], lw[3] - lw[1])
        out.append((" ".join(w[4] for w in ws), (r.x0 / W, r.y0 / H, r.x1 / W, r.y1 / H), size))
    return out


def _in_block(b) -> bool:
    """The title block: the lower-right corner, a right-hand strip or a bottom strip."""
    return (b[0] > 0.72 and b[1] > 0.55) or b[0] > 0.86 or b[1] > 0.88


def _sheet_id(lines) -> tuple[str, tuple | None]:
    """(sheet id, its box) or ("", None)."""
    best, bb, bs = "", None, 0.0
    labelled = [b for t, b, s in lines if _LABELS.search(t)]
    for t, b, s in lines:
        tt = t.strip().upper().replace(" ", "") if len(t) < 14 else ""
        m = _ID.match(tt)
        if not m or not _in_block(b):
            continue
        sc = s * (1.5 if any(abs(b[0] - lb[0]) < 0.06 and 0 <= b[1] - lb[1] < 0.08 for lb in labelled) else 1.0)
        if sc > bs:
            best, bb, bs = tt, b, sc
    return best, bb


def _near_id(b, sb, col: bool) -> bool:
    """In the title block cell around the sheet id: the column above it (a right-hand strip) or, when that column
    holds no title, the row to its left (a bottom strip)."""
    if sb is None:
        return _in_block(b)
    if col:
        return b[0] >= sb[0] - 0.02 and b[1] >= sb[1] - 0.35
    return b[1] >= sb[1] - 0.1 and b[0] >= sb[0] - 0.3


def _title(lines, boiler: set, sid: str, sb) -> str:
    def ok(t, b, col):
        t = t.strip()
        return bool(_near_id(b, sb, col) and t and t.upper() not in boiler and t.upper().replace(" ", "") != sid
                    and not _NOISE.match(t) and not _LABELS.fullmatch(t)
                    # real words, not outlined lettering read as "(l)ZLU": a 4-letter word, mostly letters
                    and re.search(r"[A-Za-z]{4,}", t) and len(re.sub(r"[^A-Za-z ]", "", t)) >= 0.75 * len(t))

    cands = [(t.strip(), b, s) for t, b, s in lines if ok(t, b, True)] or \
        [(t.strip(), b, s) for t, b, s in lines if ok(t, b, False)]
    if not cands:
        return ""
    top = max(s for _, _, s in cands)
    if sb is None:  # no sheet id to anchor on: only text that clearly stands out from the page's
        body = sorted(s for _, _, s in lines)
        if top < body[len(body) // 2] * 1.4:
            return ""
    big = [c for c in cands if c[2] >= top * 0.8]
    # reading order: lines running up the sheet (a rotated strip) left to right, others top to bottom
    big.sort(key=lambda c: (c[1][0], -c[1][3]) if (c[1][3] - c[1][1]) > (c[1][2] - c[1][0]) else
             (round(c[1][1], 2), c[1][0]))
    words, seen = [], set()
    for t, _, _ in big:
        if t.upper() not in seen:
            seen.add(t.upper())
            words.append(t)
    return re.sub(r"\s+", " ", " ".join(words))[:80]


def index(path: str) -> list[dict]:
    """[{"page", "sheet_id", "title"}] for every page (ids/titles "" where none was found). [] for non-PDFs."""
    if not str(path).lower().endswith(".pdf"):
        return []
    import pymupdf

    with pymupdf.open(path) as doc:
        n = min(doc.page_count, MAX_PAGES)
        per = []
        for i in range(n):
            try:
                per.append(_lines(doc[i]))
            except Exception:  # noqa: BLE001  one bad page never spoils the index
                per.append([])
    # lines printed in the title block of most pages are the set's own (project name, firm, "SHEET ID")
    cnt = Counter()
    for ls in per:
        cnt.update({t.strip().upper() for t, b, s in ls if _in_block(b)})
    boiler = {t for t, c in cnt.items() if n >= 3 and c >= max(3, 0.3 * n)}
    out = []
    for i, ls in enumerate(per):
        sid, sb = _sheet_id(ls)
        out.append({"page": i, "sheet_id": sid, "title": _title(ls, boiler, sid, sb)})
    ids = Counter(x["sheet_id"] for x in out if x["sheet_id"])
    for x in out:  # an id on many pages is a reference, not each page's own
        if x["sheet_id"] and ids[x["sheet_id"]] > 2:
            x["sheet_id"] = ""
    return out


def _canon(s: str) -> str:
    return re.sub(r"[^A-Z0-9.]", "", s.upper())


def find(question: str, idx: list[dict] | None) -> int | None:
    """The page whose sheet id the question names ("on M-101A", "sheet m101a"), or None."""
    if not idx or not question:
        return None
    by = {}
    for x in idx:
        if x.get("sheet_id"):
            by.setdefault(_canon(x["sheet_id"]), x["page"])
    if not by:
        return None
    toks = re.findall(r"\b[A-Za-z]{1,3}[-. ]?\d{1,3}(?:\.\d{1,2})?[A-Za-z]?\b", question)
    for t in sorted(toks, key=len, reverse=True):
        c = _canon(t)
        for k in (c, c.replace(".", "")):
            if k in by:
                return by[k]
        if c.replace(".", "") in {k.replace(".", "") for k in by}:
            return next(p for k, p in by.items() if k.replace(".", "") == c.replace(".", ""))
    return None


def label(x: dict) -> str:
    return " · ".join(s for s in (x.get("sheet_id"), x.get("title")) if s)
