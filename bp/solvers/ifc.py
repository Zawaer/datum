"""Deterministic IFC solver: IfcOpenShell tables + multilingual keyword rules, no LLM, cost 0.

Answers ifc_models count/area/length/volume questions (on `<model>.ifc` or on plan PDFs rendered from it)
and ifc_bench free-text questions. Measure definitions: see bp/ifc/model.py. Rules were tuned on the dev
split of the preview dataset.
"""
from __future__ import annotations

import re
from pathlib import Path

from bp.data import data_root
from bp.ifc import model as M
from bp.ifc.extract import load_model
from bp.ifc.plan2d import evidence_2d, guids_on_sheet
from bp.ifc.query import CLASSES, parse

MAX_EVIDENCE = 400


def ifc_path_for(qpath: str) -> tuple[str, Path]:
    """Dataset-relative + absolute path of the IFC model a question is about."""
    p = Path(qpath)
    if p.suffix.lower() != ".ifc":
        stem = re.split(r"_(?:plan|elevation|section)-", p.stem)[0]
        p = p.with_name(stem + ".ifc")
        if not (data_root() / p).exists():
            # fall back to the longest model stem that prefixes the drawing name
            d = data_root() / p.parent
            cands = [f for f in d.glob("*.ifc") if Path(qpath).stem.startswith(f.stem)]
            if cands:
                p = p.with_name(max(cands, key=lambda f: len(f.stem)).name)
    return str(p), data_root() / p


def _abstain(why: str, method: str = "ifc") -> dict:
    return {"answer": None, "confidence": 0.0, "method": method, "cost_usd": 0.0, "explanation": why,
            "evidence": []}


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ")


class IfcSolver:
    def __init__(self, variant=None):
        self.variant = variant

    def __call__(self, q: dict) -> dict:
        rel, ifc = ifc_path_for(q["path"])
        if not ifc.exists():
            return _abstain(f"IFC model {rel} not available")
        m = load_model(ifc)
        if q.get("type") in ("text", "other") or q.get("source") == "ifc_bench":
            from bp.ifc.bench import answer_text

            out = answer_text(m, q, rel)
            out.setdefault("cost_usd", 0.0)
            return out
        pq = parse(q)
        try:
            out = self._numeric(m, q, pq, rel)
        except Exception as ex:  # noqa: BLE001
            return _abstain(f"error: {type(ex).__name__}: {ex}")
        if out.get("answer") is not None and q["path"].lower().endswith(".pdf"):
            pdf_abs = data_root() / q["path"]
            items = [{"guid": g, "label": ev["label"], "value": ev.get("value")}
                     for ev in out["evidence"] if ev["kind"] == "ifc" for g in ev["guids"][:1]]
            out["evidence"] += evidence_2d(q["path"], pdf_abs, items, polygon=pq["kind"] == "room_area")
        return out

    # ------------------------------------------------------------------ numeric
    def _numeric(self, m, q, pq, rel):
        slots = pq["slots"]
        storey, sscore = None, 0.0
        if pq["kind"] == "room_area":
            return self._room_area(m, q, pq, rel)
        for s in slots:
            st, sc = M.match_storey(m, s)
            if st is not None and sc > sscore:
                storey, sscore = st, sc
        if slots and storey is None and pq["kind"] != "count":
            pass  # model-wide measure question naming the model
        what = pq["what"]
        if what is None:
            return _abstain("could not tell which element type the question is about")
        if what == "sanitary":
            els = M.sanitary(m, storey)
        else:
            els = M.elements_of(m, CLASSES[what][0], storey)
        scope = f"on storey '{storey['name']}'" if storey else "in the model"
        conf = 0.95 if (storey is None or sscore == 1.0) else 0.6
        if storey is None and slots:
            conf = 0.9  # slot is presumably the model name
        if pq["kind"] == "count":
            n = len(els)
            ev = self._ev_items(rel, els, lambda e: 1)
            return {"answer": n, "confidence": conf, "method": "ifc-count", "cost_usd": 0.0,
                    "explanation": f"{n} {CLASSES[what][0][0]} elements {scope} (IFC spatial containment)",
                    "evidence": ev}
        meas = pq["measure"]
        vals, srcs, missing = {}, set(), 0
        for e in els:
            v, src = M.measure(e, meas, pq["gross"])
            if v is None:
                missing += 1
                continue
            vals[e["guid"]] = v
            srcs.add(src)
        if not vals:
            return _abstain(f"no {meas} values for {what} {scope}")
        tot = round(sum(vals.values()), 3)
        if missing:
            conf *= 0.7
        if "geometry" in srcs:
            conf *= 0.85
        unit = {"length": "m", "volume": "m³"}.get(meas, "m²")
        used = [e for e in els if e["guid"] in vals]
        ev = self._ev_items(rel, used, lambda e: round(vals[e["guid"]], 4))
        return {"answer": tot, "confidence": round(conf, 3), "method": f"ifc-sum-{'+'.join(sorted(srcs))}",
                "cost_usd": 0.0,
                "explanation": f"sum of {meas.replace('_', ' ')} over {len(used)} {CLASSES[what][0][0]} {scope} "
                               f"({'+'.join(sorted(srcs))}) = {_fmt(tot)} {unit}",
                "evidence": ev}

    def _room_area(self, m, q, pq, rel):
        slots = pq["slots"]
        storey, room = None, None
        sscore = 0.0
        if len(slots) >= 2:
            storey, sscore = M.match_storey(m, slots[-1])
            room = slots[0]
        elif len(slots) == 1:
            st, sc = M.match_storey(m, slots[0])
            if st is not None and (pq["total"] or sc == 1.0):
                storey, sscore = st, sc
            else:
                room = slots[0]
        if room is None:
            if storey is None:
                if slots:
                    return _abstain("storey not found")
                els = M.elements_of(m, ["IfcSpace"])
            else:
                els = M.elements_of(m, ["IfcSpace"], storey)
            conf = 0.95 if sscore >= 1.0 or storey is None else 0.6
        else:
            els, rs = M.match_space(m, room, storey)
            if not els:
                return _abstain(f"room '{room}' not found")
            conf = 0.95 if rs >= 1.0 else 0.5
            if len(els) > 1:
                conf *= 0.6
                els = els[:1]
        vals, srcs = {}, set()
        for e in els:
            v, src = M.measure(e, "area_floor", pq["gross"])
            if v is not None:
                vals[e["guid"]] = v
                srcs.add(src)
        if not vals:
            return _abstain("no floor area for the matched spaces")
        tot = round(sum(vals.values()), 3)
        if "geometry" in srcs:
            conf *= 0.95
        used = [e for e in els if e["guid"] in vals]
        ev = self._ev_items(rel, used, lambda e: round(vals[e["guid"]], 4))
        what = f"room {M.label(used[0])}" if room else f"{len(used)} spaces"
        scope = f" on '{storey['name']}'" if storey else ""
        return {"answer": tot, "confidence": round(conf, 3), "method": f"ifc-area-{'+'.join(sorted(srcs))}",
                "cost_usd": 0.0,
                "explanation": f"net floor area of {what}{scope} ({'+'.join(sorted(srcs))}) = {_fmt(tot)} m²",
                "evidence": ev}

    @staticmethod
    def _ev_items(rel, els, valf):
        if len(els) <= MAX_EVIDENCE:
            return [{"kind": "ifc", "file": rel, "guids": [e["guid"]], "label": M.label(e), "value": valf(e)}
                    for e in els]
        groups = {}
        for e in els:
            k = (e["cls"], e.get("type_name") or e.get("name") or "")
            groups.setdefault(k, []).append(e)
        return [{"kind": "ifc", "file": rel, "guids": [e["guid"] for e in g],
                 "label": f"{k[0]} '{k[1]}' x{len(g)}", "value": round(sum(valf(e) for e in g), 4)}
                for k, g in groups.items()]
