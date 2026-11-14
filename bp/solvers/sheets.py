"""Upload solver for sheet types with a specialist (bp/sheets): architectural plans, slab plans, piping plans.

The router sends an upload here when its one-off classification (app/server.py: _prepare -> bp.sheets.build_meta)
names a sheet type a module claims; an abstention (None answer) goes on to the generic reader (bp/router.py).
"""
from __future__ import annotations

from pathlib import Path

from bp import sheets


class SheetsSolver:
    def __init__(self, variant=None):
        self.variant = variant

    def __call__(self, q):
        path = q["path"]
        page = q.get("page") or 0
        meta = sheets.build_meta(path, page, cache_dir=Path(path).parent,
                                 do_classify=True)
        res = sheets.answer(path, q["question"], meta)
        if res is None:
            return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": "sheets-none",
                    "explanation": f"no {meta.get('kind') or 'sheet'} specialist answer for this question"}
        for e in res.get("evidence") or []:
            e.setdefault("file", path)
            e.setdefault("page", page)
        res.setdefault("cost_usd", 0.0)
        res.setdefault("evidence", [])
        return res
