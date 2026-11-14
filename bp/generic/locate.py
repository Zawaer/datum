"""Every text-evidence box must sit on the text it cites.

`check(res, path)` runs over an answer's evidence after any solver: a box that quotes text it read (a value, a
table row, "label read: '...'") is compared with the words printed inside it, from the PDF's vector text layer or,
on a raster, from tesseract. A box whose region holds none of the cited characters is moved to where the page
words spell the value and its row label; if that fails too, its box is removed (`unlocated: True`) and the UI
lists the item as "not located on the drawing" instead of drawing a misplaced mark.
"""
from __future__ import annotations

import re
from functools import lru_cache

from bp.generic import text as T

QUOTE = re.compile(r"'(.+)'\s*$", re.S)
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
STOP = {"the", "and", "of", "see", "item", "read", "label", "row", "area", "room"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", s.lower().replace(",", ""))


@lru_cache(maxsize=16)
def _pdf_words(path: str, page: int) -> tuple:
    words, _ = T.pdf_words(path, page)
    return tuple((w.bbox, w.text) for w in words)


@lru_cache(maxsize=8)
def _raster_words(path: str) -> tuple:
    """tesseract words of a raster drawing (normalised boxes); () without tesseract."""
    import os
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("tesseract"):
        return ()
    im = T.render(path, 0, max_side=4000)
    if im is None:
        return ()
    W, H = im.size
    s = 2 if max(W, H) < 2200 else 1
    g = im.convert("L")
    if s != 1:
        g = g.resize((W * s, H * s))
    with tempfile.NamedTemporaryFile(suffix=".png") as tf:
        g.save(tf.name)
        try:
            out = subprocess.run(["tesseract", tf.name, "-", "--psm", "11", "tsv"], capture_output=True, text=True,
                                 timeout=60, env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout
        except subprocess.TimeoutExpired:
            return ()
    res = []
    for line in out.splitlines()[1:]:
        p = line.split("\t")
        if len(p) < 12 or not p[11].strip() or float(p[10]) < 20:
            continue
        x, y, w, h = (int(v) / s for v in p[6:10])
        res.append(((x / W, y / H, (x + w) / W, (y + h) / H), p[11].strip()))
    return tuple(res)


def page_words(path: str, page: int = 0) -> tuple:
    ext = path.rsplit(".", 1)[-1].lower()
    try:
        if ext in ("pdf", "svg"):
            return _pdf_words(path, int(page or 0))
        if ext in T.RASTER:
            return _raster_words(path)
    except Exception:  # noqa: BLE001  (a damaged file: nothing to check against)
        return ()
    return ()


def needles(e: dict) -> tuple[list[str], list[str]]:
    """(value strings, label tokens) the box must show: the number it contributes (a sum's value, a read
    number) and the significant words of the text it quotes."""
    lab = str(e.get("label") or "")
    m = QUOTE.search(lab)
    quoted = m.group(1) if m else ""
    if not m and e.get("kind") == "text" and re.search(r"\d", lab) and len(lab) <= 120:
        quoted = lab  # a vision reader's box labelled with what it read ("AREA 45.2 m²")
    vals = []
    v = e.get("value")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and not (v == 1 and e.get("kind") == "box"):
        vals.append(_norm(f"{v:g}" if isinstance(v, float) else str(v)))
    elif quoted:
        nums = NUM.findall(quoted)
        if len(nums) == 1:
            vals.append(_norm(nums[0]))
    toks = [t for t in re.findall(r"[A-Za-z][A-Za-z'.]{2,}", quoted) if t.lower().strip(".'") not in STOP]
    return vals, [_norm(t) for t in toks[:6] if _norm(t)]


def _inside(wb, bb, pad=0.002):
    cx, cy = (wb[0] + wb[2]) / 2, (wb[1] + wb[3]) / 2
    return bb[0] - pad <= cx <= bb[2] + pad and bb[1] - pad <= cy <= bb[3] + pad


def _has(words, s: str) -> bool:
    return any(s == _norm(t) or (len(s) > 2 and s in _norm(t)) or (s.replace(".", "") and _num_eq(s, t))
               for t in words)


def _num_eq(s: str, t: str) -> bool:
    try:
        return abs(float(s) - float(_norm(t).rstrip("."))) < 1e-9
    except ValueError:
        return False


def on_target(e: dict, words: tuple) -> bool | None:
    """None if there is nothing to check; else does the box contain the cited value (or most of its words)?"""
    vals, toks = needles(e)
    if not vals and not toks:
        return None
    inside = [t for wb, t in words if _inside(wb, e["bbox"])]
    if vals:
        return any(_has(inside, v) for v in vals)
    return sum(_has(inside, t) for t in toks) >= max(1, (len(toks) + 1) // 2)


def relocate(e: dict, words: tuple):
    """The box of the page words that spell the item's value on a line with its label words, or None
    (nothing matches, or several places match equally well)."""
    vals, toks = needles(e)
    key = vals or toks[:1]
    cands = [(wb, t) for wb, t in words if any(_has([t], k) for k in key)]
    scored = []
    for wb, _ in cands:
        h = wb[3] - wb[1]
        line = [(b, t) for b, t in words if abs((b[1] + b[3]) / 2 - (wb[1] + wb[3]) / 2) < 0.5 * h]
        hit = [(b, t) for b, t in line if any(_has([t], k) for k in toks)]
        scored.append((len({_norm(t) for _, t in hit}), T._union([wb] + [b for b, _ in hit])))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    top = scored[0][0]
    if (toks and top == 0 and len(scored) > 1) or (len(scored) > 1 and scored[1][0] == top):
        return None  # ambiguous: the value alone is printed in several places
    bb = scored[0][1]
    return [round(bb[0] - 0.001, 5), round(bb[1] - 0.001, 5), round(bb[2] + 0.001, 5), round(bb[3] + 0.001, 5)]


def tighten(e: dict, words: tuple):
    """A box over several lines for one value (a model citing neighbouring rows too) shrinks to the line inside it
    that prints the value; None when it already fits."""
    vals, _ = needles(e)
    bb = e["bbox"]
    inside = [(wb, t) for wb, t in words if _inside(wb, bb)]
    hit = [(wb, t) for wb, t in inside if any(_has([t], v) for v in vals)]
    if len(hit) != 1:
        return None
    wb = hit[0][0]
    h = wb[3] - wb[1]
    if bb[3] - bb[1] < 2.5 * h:
        return None
    cy = (wb[1] + wb[3]) / 2
    line = [b for b, _ in inside if abs((b[1] + b[3]) / 2 - cy) < 0.5 * h]
    u = T._union(line)
    py = (bb[3] - bb[1]) and 0.12 * h
    return [round(min(bb[0], u[0]), 5), round(u[1] - py, 5), round(max(bb[2], u[2]), 5), round(u[3] + py, 5)]


def check(res: dict, path_of) -> dict:
    """Verify (and fix) every text-evidence box of an answer. path_of(file) -> absolute path or None.
    Adds res["located"] = {"checked", "moved", "unlocated"}."""
    stats = {"checked": 0, "moved": 0, "unlocated": 0}
    for e in res.get("evidence") or []:
        if not e.get("bbox") or e.get("kind") not in ("text", "box", "cell"):
            continue
        if e.get("kind") == "box" and not QUOTE.search(str(e.get("label") or "")):
            continue  # a vision detection (a door symbol): no text to check
        p = path_of(e.get("file"))
        if not p:
            continue
        words = page_words(str(p), e.get("page") or 0)
        if not words:
            continue
        ok = on_target(e, words)
        if ok is None:
            continue
        stats["checked"] += 1
        if ok:
            nb = tighten(e, words)
            if nb is not None:
                e["bbox"], e["relocated"] = nb, True
                stats["moved"] += 1
            continue
        nb = relocate(e, words)
        if nb is not None:
            e["bbox"], e["relocated"] = nb, True
            stats["moved"] += 1
        else:
            e.pop("bbox", None)
            e["unlocated"] = True
            stats["unlocated"] += 1
    if stats["checked"]:
        res["located"] = stats
    return res
