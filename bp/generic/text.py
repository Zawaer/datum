"""Text with positions from any drawing, grouped into layout segments an LLM can cite by id.

Vector PDF / SVG: PyMuPDF words (rotated pages handled: boxes are in *rendered* page coords).
DXF: ezdxf TEXT / MTEXT / ATTRIB, normalised to the drawing extents (y flipped, origin top-left).
Raster: no text layer (the VLM path reads it).

A *segment* is a run of words on one baseline with no large gap: a table row fragment, a label,
a note line. Cells inside a segment are joined with ' | ' where the gap is wider than a space,
so schedules keep their columns. All boxes are normalised to 0..1 of the rendered page.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

RASTER = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif", "webp"}


@dataclass
class Word:
    bbox: tuple  # normalised x0, y0, x1, y1
    text: str
    vertical: bool = False


@dataclass
class Segment:
    id: int
    page: int
    bbox: tuple
    cells: list = field(default_factory=list)  # list of (text, bbox)
    row: int = -1  # baseline row (segments of one table row share it)

    @property
    def text(self) -> str:
        return " | ".join(c[0] for c in self.cells)


def _union(bbs):
    return (min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs))


# ---------------------------------------------------------------------------------------- words
def pdf_words(path: str, page: int) -> tuple[list[Word], tuple[float, float]]:
    import pymupdf

    doc = pymupdf.open(path)
    pg = doc[page]
    m = pg.rotation_matrix
    W, H = pg.rect.width, pg.rect.height  # rendered (rotated) size
    out = []
    for x0, y0, x1, y1, t, *_ in pg.get_text("words"):
        r = pymupdf.Rect(x0, y0, x1, y1) * m
        r.normalize()
        b = (r.x0 / W, r.y0 / H, r.x1 / W, r.y1 / H)
        out.append(Word(b, t))
    # words whose box is taller than wide (and longer than 2 chars) run vertically on the page
    for w in out:
        bw, bh = (w.bbox[2] - w.bbox[0]) * W, (w.bbox[3] - w.bbox[1]) * H
        w.vertical = len(w.text) > 2 and bh > 1.5 * bw
    return out, (W, H)


def dxf_words(path: str) -> tuple[list[Word], tuple[float, float]]:
    import ezdxf
    from ezdxf import bbox as ebbox

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    raw = []
    for e in msp.query("TEXT MTEXT ATTRIB INSERT"):
        items = [e]
        if e.dxftype() == "INSERT":
            items = list(e.attribs)
        for t in items:
            try:
                if t.dxftype() == "MTEXT":
                    txt, h = t.plain_text(), t.dxf.char_height
                else:
                    txt, h = t.dxf.text, t.dxf.height
                p = t.dxf.insert
            except Exception:  # noqa: BLE001
                continue
            txt = re.sub(r"\s+", " ", txt or "").strip()
            if txt:
                raw.append((p.x, p.y, h or 1.0, txt))
    if not raw:
        return [], (1.0, 1.0)
    try:
        ext = ebbox.extents(msp, fast=True)
        x0, y0, x1, y1 = ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y
    except Exception:  # noqa: BLE001
        x0 = min(r[0] for r in raw); y0 = min(r[1] for r in raw)
        x1 = max(r[0] for r in raw); y1 = max(r[1] for r in raw)
    W, H = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    out = []
    for x, y, h, txt in raw:
        w = 0.6 * h * len(txt)
        out.append(Word(((x - x0) / W, (y1 - y - h) / H, (x + w - x0) / W, (y1 - y) / H), txt))
    return out, (W, H)


# ------------------------------------------------------------------------------------- segments
def segments(words: list[Word], page: int = 0, start_id: int = 0, aspect: float = 1.0) -> list[Segment]:
    """Group words into baseline runs. aspect = page width / height (gaps are measured in x units)."""
    horiz = [w for w in words if not w.vertical]
    segs: list[Segment] = []
    rows: list[list[Word]] = []
    for w in sorted(horiz, key=lambda w: ((w.bbox[1] + w.bbox[3]) / 2, w.bbox[0])):
        cy, h = (w.bbox[1] + w.bbox[3]) / 2, w.bbox[3] - w.bbox[1]
        for row in reversed(rows[-12:]):
            r0 = row[0]
            rcy, rh = (r0.bbox[1] + r0.bbox[3]) / 2, r0.bbox[3] - r0.bbox[1]
            if abs(cy - rcy) < 0.35 * min(h, rh) and 0.6 < h / max(rh, 1e-9) < 1.67:
                row.append(w)
                break
        else:
            rows.append([w])
    for ri, row in enumerate(rows):
        row.sort(key=lambda w: w.bbox[0])
        h = sorted(w.bbox[3] - w.bbox[1] for w in row)[len(row) // 2] / aspect  # height in x units
        cur: list[list[Word]] = [[row[0]]]
        runs = [cur]
        for a, b in zip(row, row[1:]):
            gap = b.bbox[0] - a.bbox[2]
            if gap > 4.0 * h:  # a new segment (another table / another label)
                cur = [[b]]
                runs.append(cur)
            elif gap > 0.6 * h:  # a new cell
                cur.append([b])
            else:
                cur[-1].append(b)
        for run in runs:
            cells = [(" ".join(w.text for w in c), _union([w.bbox for w in c])) for c in run]
            segs.append(Segment(0, page, _union([c[1] for c in cells]), cells, ri))
    for w in words:
        if w.vertical:
            segs.append(Segment(0, page, w.bbox, [(w.text, w.bbox)], -1))
    # reading order: rows top to bottom, segments left to right; vertical words last
    rank = {}
    for s in segs:
        if s.row >= 0:
            r = rank.setdefault(s.row, s.bbox[1])
            rank[s.row] = min(r, s.bbox[1])
    segs.sort(key=lambda s: (s.row < 0, rank.get(s.row, s.bbox[1]), s.row, s.bbox[0]))
    for i, s in enumerate(segs):
        s.id = start_id + i
    return segs


# ---------------------------------------------------------------------------------------- pages
@lru_cache(maxsize=64)
def n_pages(path: str) -> int:
    ext = path.rsplit(".", 1)[-1].lower()
    if ext in ("pdf", "svg"):
        import pymupdf

        return len(pymupdf.open(path))
    return 1


@lru_cache(maxsize=32)
def layout(path: str, page: int = 0) -> tuple[list[Segment], float]:
    """(segments, aspect) of one page; empty for rasters."""
    ext = path.rsplit(".", 1)[-1].lower()
    if ext in RASTER:
        return [], 1.0
    if ext == "dxf":
        words, (W, H) = dxf_words(path)
    else:
        words, (W, H) = pdf_words(path, page)
    return segments(words, page, aspect=W / H), W / H


def page_text_score(path: str, page: int, query_tokens: set[str]) -> float:
    import pymupdf

    t = pymupdf.open(path)[page].get_text().lower()
    toks = set(re.findall(r"[a-z0-9][a-z0-9.\-]+", t))
    return len(query_tokens & toks)


def pick_pages(path: str, question: str, k: int = 2) -> list[int]:
    n = n_pages(path)
    if n == 1:
        return [0]
    q = set(re.findall(r"[a-z0-9][a-z0-9.\-]+", question.lower()))
    scores = sorted(((page_text_score(path, p, q), -p) for p in range(n)), reverse=True)
    return [-p for _, p in scores[:k]]


def render(path: str, page: int = 0, max_side: int = 2048):
    """PIL image of one page, longest side <= max_side (rasters are only ever downscaled)."""
    from PIL import Image

    ext = path.rsplit(".", 1)[-1].lower()
    if ext in RASTER:
        im = Image.open(path)
        im.load()
        if im.mode not in ("L", "RGB"):
            im = im.convert("RGB")
        if max(im.size) > max_side:  # shrink before going RGB: a 139 MP grayscale sheet never becomes 417 MB
            s = max_side / max(im.size)
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS, reducing_gap=3.0)
        return im.convert("RGB")
    if ext == "dxf":
        return None  # no page render for DXF here; the UI renders it from the same extents
    import pymupdf

    pg = pymupdf.open(path)[page]
    zoom = max_side / max(pg.rect.width, pg.rect.height)
    pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def relevant(segs: list[Segment], question: str, budget_chars: int) -> list[Segment]:
    """All segments if they fit, else the best-matching ones plus their vertical neighbourhood
    (rows of the same table), in reading order."""
    total = sum(len(s.text) + 8 for s in segs)
    if total <= budget_chars:
        return segs
    qt = {t for t in re.findall(r"[a-z0-9][a-z0-9.\-']*", question.lower()) if len(t) > 1}
    stop = {"the", "of", "on", "in", "is", "are", "how", "many", "what", "which", "this", "drawings", "sheet",
            "and", "for", "with", "does", "do", "a", "an", "to", "by", "be", "there", "drawn", "shown"}
    qt -= stop
    def score(s):
        st = set(re.findall(r"[a-z0-9][a-z0-9.\-']*", s.text.lower()))
        return len(qt & st)
    hits = [s for s in segs if score(s) > 0]
    hits.sort(key=score, reverse=True)
    chosen: dict[int, Segment] = {}
    used = 0
    # grow a column window under / around each hit: tables continue below their header
    for h in hits:
        for s in segs:
            if s.id in chosen:
                continue
            ov = min(s.bbox[2], h.bbox[2] + 0.15) - max(s.bbox[0], h.bbox[0] - 0.15)
            if ov > 0 and -0.03 < s.bbox[1] - h.bbox[1] < 0.35:
                chosen[s.id] = s
                used += len(s.text) + 8
            if used > budget_chars:
                break
        if used > budget_chars:
            break
    return sorted(chosen.values(), key=lambda s: s.id)


def to_prompt(segs: list[Segment]) -> str:
    """One line per baseline row: 'y=12.3: [id]@x text  [id]@x text ...' (x, y in % of the page),
    so the model sees whole table rows and can cite the segments it used."""
    lines, cur, key = [], [], None
    for s in segs:
        k = (s.page, s.row) if s.row >= 0 else (s.page, "v", s.id)
        if k != key and cur:
            lines.append(cur)
            cur = []
        key = k
        cur.append(s)
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        y = min(s.bbox[1] for s in ln) * 100
        pg = f"p{ln[0].page} " if ln[0].page else ""
        vert = " (vertical)" if ln[0].row < 0 else ""
        out.append(f"{pg}y={y:.1f}{vert}: " + "   ".join(f"[{s.id}]@{s.bbox[0] * 100:.0f} {s.text}" for s in ln))
    return "\n".join(out)


def numbers_in(text: str) -> list[float]:
    out = []
    for m in re.findall(r"-?\d[\d,]*(?:\.\d+)?", text):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def value_in_text(v, text: str) -> bool:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return False
    return any(math.isclose(v, n, rel_tol=1e-6, abs_tol=1e-6) for n in numbers_in(text))
