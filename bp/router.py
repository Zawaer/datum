"""Router: send each question to the cheapest solver that can answer it exactly.

source/format -> specialised deterministic solver; if that abstains or is unsure, optionally fall back
to a frontier model (off by default: we'd rather say "not sure" than guess expensively).
"""
from __future__ import annotations

import re

from bp.solvers import get_solver

ROUTES = {
    "swiss_dwellings": "swiss",
    "ifc_models": "ifc",
    "ifc_bench": "ifctext",  # free-text IFC questions: rules where validated, else Haiku on a cited fact sheet
    "cubicasa5k": "cubicasa",
}

# uploads: app/server.py sets q["kind"] from the file (ifc / dxf / pdf-vector / pdf-raster / raster)
UPLOAD_ROUTES = {
    "ifc": "ifc",
    "dxf": "generic",
    "pdf-vector": "generic",
    "pdf-raster": "generic",
    "raster": "generic",
}

TYPE_PATTERNS = [
    ("count", r"how many|kuinka monta|montako|wie viele|combien|quant[ie]|hvor mange|mitu|hur många|hoeveel|ile"),
    ("volume", r"volume|volumen|tilavuus|rumfang|maht|m³|m3"),
    ("length", r"length|länge|pituus|longueur|lunghezza|længde|pikkus|\bm\b(?!²)"),
    ("area", r"area|fläche|pinta-ala|surface|superficie|areal|pind|m²|m2"),
]


def guess_type(question: str) -> str:
    ql = question.lower()
    for t, pat in TYPE_PATTERNS:
        if re.search(pat, ql):
            return t
    return "text"


class Router:
    def __init__(self, variant=None, fallback: str | None = None, min_conf: float = 0.5):
        self.fallback_name = fallback or (variant if variant else None)
        self.min_conf = min_conf
        self._solvers = {}

    def _get(self, name):
        if name not in self._solvers:
            try:
                self._solvers[name] = get_solver(name)
            except Exception as e:  # noqa: BLE001
                self._solvers[name] = e
        s = self._solvers[name]
        return None if isinstance(s, Exception) else s

    def route_for(self, q) -> str | None:
        if q["source"] == "upload":
            return UPLOAD_ROUTES.get(q.get("kind"))
        return ROUTES.get(q["source"])

    def _run(self, s, q, name):
        try:
            res = s(q)
        except Exception as e:  # noqa: BLE001  a crashing solver abstains, it never takes the router down
            res = {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": f"{name}-error",
                   "explanation": f"{name} solver failed: {type(e).__name__}: {str(e)[:200]}"}
        res["route"] = name
        return res

    def __call__(self, q):
        q = dict(q)
        q.setdefault("type", guess_type(q["question"]))
        name = self.route_for(q)
        res = None
        if name and (s := self._get(name)):
            res = self._run(s, q, name)
        if (res is None or res.get("answer") is None or (res.get("confidence") or 0) < self.min_conf) \
                and self.fallback_name and (fb := self._get(self.fallback_name)):
            prev_cost = (res or {}).get("cost_usd", 0.0)
            res = self._run(fb, q, self.fallback_name)
            res["cost_usd"] = res.get("cost_usd", 0.0) + prev_cost
            res["route"] = f"{name or '-'} -> {self.fallback_name}"
        if res is None:
            res = {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": "none",
                   "explanation": "no solver for this drawing type yet", "route": "-"}
        return res
