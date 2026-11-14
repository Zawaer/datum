"""Router: send each question to the cheapest solver that can answer it exactly.

source/format -> specialised deterministic solver; if that abstains or is unsure, optionally fall back
to a frontier model (off by default: we'd rather say "not sure" than guess expensively).
"""
from __future__ import annotations

import os
import re
import threading
import time

from bp.solvers import get_solver

ROUTES = {
    "swiss_dwellings": "swiss",
    "ifc_models": "ifc",
    "ifc_bench": "ifctext",  # free-text IFC questions: rules where validated, else Haiku on a cited fact sheet
    "cubicasa5k": "cubicasa",
    "opening_design": "generic",  # real US drawing sets: vector text + grounded vision
}

LOAD_RETRY_S = 30.0  # a solver that failed to load is retried after this long, not on every question

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
    ("count", r"how many|kuinka monta|montako|wie viele|combien|quant[ie]|hvor mange|mitu|hur många|hoeveel|ile|"
              r"\bcount\b|\bnumber of\b|\banzahl\b|\bnombre de\b|\bnumero d|lukumäärä|\baantal\b|\bantal\b|\bliczba\b"),
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
        self._load_errors = {}  # solver name -> why it could not be built (reported on the answer)
        self._lock = threading.Lock()
        self._locks = {}
        # free wording -> a supported template (bp/normalize.py), only when the solver could not parse the question
        self.normalize = os.environ.get("BP_NORMALIZE", "1") == "1"

    def _get(self, name):
        # one router serves many threads (eval.py --jobs, the demo server): build each solver once under a lock,
        # so a thread never sees another's half-finished import, and keep a failure as a reported error that is
        # retried after LOAD_RETRY_S instead of silently disabling a route for the rest of the run
        s = self._solvers.get(name)
        if s is not None:
            return s
        with self._lock:
            lock = self._locks.setdefault(name, threading.Lock())
        with lock:  # per solver: loading a slow one (detector weights) never blocks the others
            if name in self._solvers:
                return self._solvers[name]
            err = self._load_errors.get(name)
            if err and time.monotonic() - err[1] < LOAD_RETRY_S:
                return None
            try:
                self._solvers[name] = get_solver(name)
                self._load_errors.pop(name, None)
                return self._solvers[name]
            except Exception as e:  # noqa: BLE001
                self._load_errors[name] = (f"{type(e).__name__}: {str(e)[:200]}", time.monotonic())
                return None

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
                   "explanation": f"{name} solver failed: {type(e).__name__}: {str(e)[:200]}",
                   "error": f"{type(e).__name__}: {str(e)[:200]}"}
        res["route"] = name
        return res

    def _multi(self, q, parts):
        subs = [(noun, self(dict(q, question=sq, type="count"))) for noun, sq in parts]
        got = [(n, r) for n, r in subs if r.get("answer") is not None]
        res = {"answer": ", ".join(f"{r['answer']} {n}" if r.get("answer") is not None else f"{n}: not sure"
                                   for n, r in subs) if got else None,
               "confidence": min((r.get("confidence") or 0) for _, r in subs),
               "evidence": [e for _, r in subs for e in (r.get("evidence") or [])],
               "cost_usd": sum(float(r.get("cost_usd") or 0) for _, r in subs),
               "method": "multi:" + "+".join(str(r.get("method")) for _, r in subs),
               "route": subs[0][1].get("route"), "parts": [{"question": sq, **{k: r.get(k) for k in (
                   "answer", "confidence", "method", "explanation")}} for (_, sq), (_, r) in zip(parts, subs)],
               "explanation": " || ".join(f"{sq} -> {r.get('explanation') or ''}" for (_, sq), (_, r)
                                          in zip(parts, subs))}
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
        if self.normalize and q["source"] != "ifc_bench" and q["source"] != "upload":
            # typed wordings no dataset question uses (bp/normalize.py): "how many doors and windows?" is asked
            # as two questions; "... in square feet" on a metric drawing is asked in m² and converted
            from bp.normalize import METRIC_ROUTES, split_multi, to_feet, unit_request

            if parts := split_multi(q["question"]):
                return self._multi(q, parts)
            if name in METRIC_ROUTES:
                bare, feet = unit_request(q["question"])
                if feet:
                    r = self(dict(q, question=bare, type=guess_type(bare) if q["type"] == "text" else q["type"]))
                    r["asked_unit"] = "ft"
                    return to_feet(r, guess_type(bare) if q["type"] == "text" else q["type"])
        res = None
        if name and (s := self._get(name)):
            res = self._run(s, q, name)
            if self.normalize and (res.get("answer") is None or (
                    name == "ifc" and q["source"] != "ifc_bench" and res.get("method") == "ifc-text-na")):
                # (an IFC-model question no numeric rule read falls to the text rules, which say "not
                # available"; that is a parse failure, so the normaliser gets it; its NONE keeps the answer)
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
        if res is None and name and name in self._load_errors:
            res = {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": f"{name}-error",
                   "explanation": f"the {name} solver could not be loaded", "route": name,
                   "error": f"load {name}: {self._load_errors[name][0]}"}
        if res is None:
            res = {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": "none",
                   "explanation": "no solver for this drawing type yet", "route": "-"}
        if self.crosscheck and res.get("comparison"):
            # a comparison (bp/compare.py) is computed from two or more of the solver's own readings; the second
            # methods answer one count or area, which would be read against the difference or the yes/no
            res["crosscheck"] = {"status": "single", "second": None,
                                 "note": "no second method for comparisons (each compared value is the same reading "
                                         "the area / count answers use)"}
        elif self.crosscheck:
            from bp.crosscheck import crosscheck

            res["crosscheck"] = cc = crosscheck(q, res)
            # Rule chosen on dev (runs/crosscheck_test.summary.md): on a conflict never switch answers; halve the
            # confidence so the UI flags it for a human (and the 0.5 threshold turns most raster conflicts into
            # "not sure"). Agreement is shown as "2 independent methods agree".
            if cc.get("status") == "conflict" and res.get("confidence") is not None:
                res["confidence_before_conflict"] = res["confidence"]
                res["confidence"] = round(res["confidence"] * 0.5, 4)
        return res
