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
    "ifc_bench": "ifc",
    "cubicasa5k": "cubicasa",
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
            except (ImportError, ModuleNotFoundError, FileNotFoundError) as e:
                self._solvers[name] = e
        s = self._solvers[name]
        return None if isinstance(s, Exception) else s

    def __call__(self, q):
        q = dict(q)
        q.setdefault("type", guess_type(q["question"]))
        name = ROUTES.get(q["source"])
        res = None
        if name and (s := self._get(name)):
            res = s(q)
            res["route"] = name
        if (res is None or res.get("answer") is None or (res.get("confidence") or 0) < self.min_conf) \
                and self.fallback_name and (fb := self._get(self.fallback_name)):
            prev_cost = (res or {}).get("cost_usd", 0.0)
            res = fb(q)
            res["cost_usd"] = res.get("cost_usd", 0.0) + prev_cost
            res["route"] = f"{name or '-'} -> {self.fallback_name}"
        if res is None:
            res = {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": "none",
                   "explanation": "no solver for this drawing type yet", "route": "-"}
        return res
