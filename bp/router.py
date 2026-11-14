"""Router: send each question to the cheapest solver that can answer it exactly.

source/format -> specialised deterministic solver; if that abstains or is unsure, optionally fall back
to a frontier model (off by default: we'd rather say "not sure" than guess expensively).
"""
from __future__ import annotations

import os
import re

from bp.solvers import get_solver

ROUTES = {
    "swiss_dwellings": "swiss",
    "ifc_models": "ifc",
    "ifc_bench": "ifctext",  # free-text IFC questions: rules where validated, else Haiku on a cited fact sheet
    "cubicasa5k": "cubicasa",
    "opening_design": "generic",  # real US drawing sets: vector text + grounded vision
}

# uploads: app/server.py sets q["kind"] from the file (ifc / dxf / pdf-vector / pdf-raster / raster)
UPLOAD_ROUTES = {
    "ifc": "ifc",
    "dxf": "generic",
    "pdf-vector": "generic",
    "pdf-raster": "generic",
    "raster": "generic",
}
# when the upload route abstains, a second reader gets the question (route shown as "ifc -> ifctext")
UPLOAD_FALLBACK = {"ifc": "ifctext", "cubicasa": "generic"}
# symbols the CubiCasa detector was trained on: raster uploads that look like residential plans go to it first
CUBICASA_SYMBOLS = {"window", "door", "toilet", "sink", "shower_bath", "sauna"}

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
    def __init__(self, variant=None, fallback: str | None = None, min_conf: float = 0.5, crosscheck: bool | None = None):
        self.fallback_name = fallback or (variant if variant else None)
        self.min_conf = min_conf
        # second-method check (bp/crosscheck.py): on unless BP_CROSSCHECK=0 (eval.py sets it from --crosscheck)
        self.crosscheck = os.environ.get("BP_CROSSCHECK", "1") == "1" if crosscheck is None else crosscheck
        self._solvers = {}
        # free wording -> a supported template (bp/normalize.py), only when the solver could not parse the question
        self.normalize = os.environ.get("BP_NORMALIZE", "1") == "1"

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
            if q.get("kind") == "raster" and q.get("residential_plan") and q.get("type") == "count":
                from bp.cubicasa.questions import target

                if target(q["question"]) in CUBICASA_SYMBOLS:
                    return "cubicasa"
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

    def _normalized(self, s, q, name, res):
        from bp.normalize import normalize, understood

        if understood(name, q) and not res.get("unparsed"):
            return res, q
        nq = normalize(name, q)
        if not nq["question"]:
            res["cost_usd"] = res.get("cost_usd", 0.0) + nq["cost_usd"]
            res["normalize"] = {"question": None, "why": nq["why"], "cost_usd": nq["cost_usd"]}
            return res, q
        q2 = dict(q, question=nq["question"])
        t2 = guess_type(nq["question"])
        if t2 != "text":
            q2["type"] = t2
        res2 = self._run(s, q2, name)
        res2["cost_usd"] = res2.get("cost_usd", 0.0) + res.get("cost_usd", 0.0) + nq["cost_usd"]
        res2["normalized_question"] = nq["question"]
        res2["normalize"] = {"question": nq["question"], "cost_usd": nq["cost_usd"], "type": q2["type"]}
        res2["explanation"] = f"read as: {nq['question']} | " + (res2.get("explanation") or "")
        return res2, q2

    def __call__(self, q):
        q = dict(q)
        q.setdefault("type", guess_type(q["question"]))
        name = self.route_for(q)
        res = None
        if name and (s := self._get(name)):
            res = self._run(s, q, name)
            if res.get("answer") is None and self.normalize:
                res, q = self._normalized(s, q, name, res)  # q: the rewrite, if one was used
            fb_name = UPLOAD_FALLBACK.get(name) if q["source"] == "upload" else None
            # an unsure specialist (an IFC rule that did not fit, the CubiCasa detector on a plan unlike its
            # training data) hands over to the general reader; the more confident of the two answers is kept
            weak = res.get("answer") is None or (name in ("ifc", "cubicasa") and (res.get("confidence") or 0) < 0.3)
            if weak and fb_name and (fb := self._get(fb_name)):
                res2 = self._run(fb, q, fb_name)
                res2["cost_usd"] = res2.get("cost_usd", 0.0) + res.get("cost_usd", 0.0)
                res2["route"] = f"{name} -> {fb_name}"
                if (res2.get("answer") is not None and (res.get("answer") is None or (res2.get("confidence") or 0)
                                                         >= (res.get("confidence") or 0))) \
                        or str(res.get("method", "")).endswith("error"):
                    res = res2
        if (res is None or res.get("answer") is None or (res.get("confidence") or 0) < self.min_conf) \
                and self.fallback_name and (fb := self._get(self.fallback_name)):
            prev_cost = (res or {}).get("cost_usd", 0.0)
            res = self._run(fb, q, self.fallback_name)
            res["cost_usd"] = res.get("cost_usd", 0.0) + prev_cost
            res["route"] = f"{name or '-'} -> {self.fallback_name}"
        if res is None:
            res = {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": "none",
                   "explanation": "no solver for this drawing type yet", "route": "-"}
        if self.crosscheck:
            from bp.crosscheck import crosscheck

            res["crosscheck"] = cc = crosscheck(q, res)
            # Rule chosen on dev (runs/crosscheck_test.summary.md): on a conflict never switch answers; halve the
            # confidence so the UI flags it for a human (and the 0.5 threshold turns most raster conflicts into
            # "not sure"). Agreement is shown as "2 independent methods agree".
            if cc.get("status") == "conflict" and res.get("confidence") is not None:
                res["confidence_before_conflict"] = res["confidence"]
                res["confidence"] = round(res["confidence"] * 0.5, 4)
        return res
