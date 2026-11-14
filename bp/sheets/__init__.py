"""Sheet-type specialists for uploaded drawings (registry + contract).

Final judging uploads unseen, complex sheets (architectural plans, structural slab plans, piping plans).
Each upload is classified once (`classify`), and a question on it is first offered to the module that
claims the sheet type; the existing generic path (text layer + grounded vision) runs when the module
abstains (returns None, or an answer of None).

Contract for a module `bp/sheets/<name>.py`:

    def detect(meta) -> float          # 0..1: how sure this sheet is my type
    def answer(path, question, meta) -> dict | None

`meta` (built once per upload by `build_meta`, cached by the caller):
    {"text":  page text (PDF text layer, or OCR / vision read of the title block; may be ""),
     "title": title-block text if found (sheet title + number, e.g. "FOUNDATION AND SLAB PLAN S-100F"),
     "kind":  sheet kind from the classifier ("arch" | "slab" | "piping" | "other"),
     "image": path of a PNG/JPG render of the page (full resolution, page 0 unless "page" says otherwise),
     "page":  page index the image is of,
     "w", "h": image size in px,
     ...}   modules may add their own cached keys under their own name (meta["slab"] = {...}).

`answer` returns the usual solver result (docs/EVIDENCE.md):
    {"answer": number | str | None, "confidence": 0..1, "method": "sheets-<name>-<path>",
     "cost_usd": float, "explanation": "one line, show the arithmetic",
     "evidence": [{"kind": "box" | "polygon" | "text", "page": 0, "bbox": [x0,y0,x1,y1] | "points": [[x,y],..],
                   "label": "...", "value": <contribution or None>}, ...]}   # coords normalised 0..1 to the image
`file` in evidence items is filled in by the caller when missing. Return None (or answer None) to abstain
and let the generic path answer. Never raise for an ordinary "can't do this" (exceptions are caught and
logged as an abstention anyway).
"""
from __future__ import annotations

import importlib
import logging

log = logging.getLogger(__name__)

MODULES = ["arch", "slab", "piping"]  # bp/sheets/<name>.py; a missing/broken module is skipped
MIN_DETECT = 0.5  # a module answers only when it claims the sheet at least this strongly


def _load(name):
    try:
        return importlib.import_module(f"bp.sheets.{name}")
    except Exception as e:  # noqa: BLE001
        log.warning("sheet module %s unavailable: %s", name, e)
        return None


def modules():
    return [(n, m) for n in MODULES if (m := _load(n)) is not None]


def scores(meta) -> dict:
    out = {}
    for n, m in modules():
        try:
            out[n] = float(m.detect(meta) or 0.0)
        except Exception as e:  # noqa: BLE001
            log.warning("detect %s failed: %s", n, e)
            out[n] = 0.0
    return out


def best(meta):
    """(name, module, score) of the module that claims this sheet, or (None, None, 0)."""
    sc = scores(meta)
    if not sc:
        return None, None, 0.0
    n = max(sc, key=sc.get)
    if sc[n] < MIN_DETECT:
        return None, None, sc[n]
    return n, _load(n), sc[n]


def answer(path, question, meta):
    """Ask the best module; None when no module claims the sheet or it abstains."""
    n, m, s = best(meta)
    if m is None:
        return None
    try:
        res = m.answer(path, question, meta)
    except Exception as e:  # noqa: BLE001
        log.exception("sheet module %s failed", n)
        return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0,
                "method": f"sheets-{n}-error", "explanation": f"{n} module failed: {type(e).__name__}: {str(e)[:200]}"}
    if res is not None:
        res.setdefault("method", f"sheets-{n}")
        res["sheet_type"] = n
        res["sheet_score"] = round(s, 3)
    return res
