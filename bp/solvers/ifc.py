"""Deterministic IFC solver: IfcOpenShell tables + multilingual keyword rules, no LLM, cost 0.

Answers ifc_models count/area/length/volume questions (on `<model>.ifc` or on plan PDFs rendered from it)
and ifc_bench free-text questions. Measure definitions: see bp/ifc/model.py. Rules were tuned on the dev
split of the preview dataset.
"""
from __future__ import annotations

import re
from pathlib import Path

from bp import compare as C
from bp.data import data_root
from bp.ifc import model as M
from bp.ifc.extract import load_model
from bp.ifc.plan2d import evidence_2d, guids_on_sheet
from bp.ifc.query import CLASSES, HERE_FLOOR, _first_class, parse
from bp.swiss import rooms as RK

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


# "the model 'X'", "the 'X' model", "Modell 'X'", "modelo «X»", "mudelis „X“", "modelul 'X'", ...
_MODEL_WORD = r"(?:model\w*|modèle\w*|mudel\w*|projec?t\w*|building|file)"


def _names_model(question: str, slot: str) -> bool:
    """Is this quoted name introduced as the model's (or project's) name rather than a storey?"""
    i = question.find(slot)
    if i < 0:
        return False
    before = question[max(0, i - 30):i].rstrip(" '\"«»„“”‘’")
    after = question[i + len(slot):i + len(slot) + 30].lstrip(" '\"«»„“”‘’")
    return bool(re.search(rf"\b{_MODEL_WORD}\s*$", before, re.I) or re.match(rf"{_MODEL_WORD}\b", after, re.I))


def _no_storey(m, name: str | None) -> str:
    names = [s["name"] or s["long_name"] for s in m["storeys"] if s["name"] or s["long_name"]]
    head = f"no storey named '{name}' in this model; " if name else ""
    return head + "storeys are: " + ", ".join(f"'{n}'" for n in names)


# a storey mentioned in words (not "floor plan" / "floor area"): only checked when nothing is quoted
_STOREY_WORD = (r"\b(?:storeys?|stor(?:y|ies)|levels?|floors?(?!\s*(?:plans?|areas?|space))|ground|basement|attic|"
                r"cellar|loft|mezzanine|geschoss\w*|etage\w*|kerro\w*)\b")


def _unquoted_storey(m, question: str):
    """A storey whose exact name appears in the question as a whole phrase (longest name wins)."""
    ql = question.casefold()
    best = None
    for st in m["storeys"]:
        for n in (st["name"], st["long_name"]):
            n = (n or "").strip()
            if len(n) < 2:
                continue
            if re.search(rf"(?<!\w){re.escape(n.casefold())}(?!\w)", ql) and (best is None or len(n) > best[1]):
                best = (st, len(n))
    return best[0] if best else None


def sheet_storey(m, qpath: str):
    """The storey a plan sheet `<model>_plan-NN-<storey>.pdf` shows (None for the .ifc or any other file).

    Read from the sheet's SVG twin title ("... — Plan: <storey>"), matched to the model's storeys; checked on all 71
    dataset plan sheets (every title matches a storey exactly). Fallback: the slug in the file name."""
    p = Path(qpath)
    if "_plan-" not in p.stem or p.suffix.lower() == ".ifc":
        return None
    svg = (data_root() / p).with_suffix(".svg")
    if svg.exists():
        from bp.crosscheck import svg_sheet

        title = svg_sheet(str(svg)).get("storey")
        st, sc = M.match_storey(m, title) if title else (None, 0.0)
        if st is not None and sc >= 1.0:
            return st
    mm = re.search(r"_plan-(\d+)-(.+)$", p.stem)
    if mm:
        slug = mm.group(2)
        hits = [s for s in m["storeys"] if re.sub(r"[^a-z0-9]+", "-", M.nkey(s["name"]).lower()).strip("-") == slug]
        if len(hits) == 1:
            return hits[0]
        idx = int(mm.group(1)) - 1
        if 0 <= idx < len(m["storeys"]) and len(hits) > 1 and m["storeys"][idx] in hits:
            return m["storeys"][idx]
    return None


def _here(m, q, pq):
    """Deictic scope -> (storey, None) for a plan sheet, (None, abstention) when it cannot be resolved, (None, None)
    when the question has none."""
    if not pq.get("here"):
        return None, None
    st = sheet_storey(m, q["path"])
    if st is not None:
        return st, None
    if pq.get("here_floor"):
        return None, {**_abstain("'this floor' needs a storey, and this file is the whole model: which storey? "
                                 + _no_storey(m, None)), "ask_storey": True}
    return None, None  # "here" on the model itself: the model


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ")


def _plural(what: str) -> str:
    """CLASSES key -> the counted thing in words ('door' -> 'doors')."""
    return {"space": "rooms", "sanitary": "sanitary fixtures", "building_storey": "storeys", "stair": "stairs",
            "light": "light fixtures", "proxy": "proxy elements", "furniture": "furniture items"}.get(
        what, what.replace("_", " ") + "s")


class IfcSolver:
    def __init__(self, variant=None):
        self.variant = variant

    def __call__(self, q: dict) -> dict:
        rel, ifc = ifc_path_for(q["path"])
        if not ifc.exists():
            return _abstain(f"IFC model {rel} not available")
        m = load_model(ifc)
        # comparisons ("which room is the largest?"); no dataset question parses as one (bp/compare.py)
        cp = C.parse(q["question"]) if q.get("source") != "ifc_bench" else None
        if cp is not None:
            out = self._compare(m, q, cp, rel)
            if out.get("answer") is not None and q["path"].lower().endswith(".pdf"):
                items = [{"guid": g, "label": ev["label"], "value": ev.get("value")}
                         for ev in out["evidence"] if ev["kind"] == "ifc" for g in ev["guids"][:1]]
                out["evidence"] += evidence_2d(q["path"], data_root() / q["path"], items,
                                               polygon=out.pop("_spaces", False))
            out.pop("_spaces", None)
            return out
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
        unknown = []
        for s in slots:
            st, sc = M.match_storey(m, s)
            if st is not None and sc > sscore:
                storey, sscore = st, sc
            elif st is None and not _names_model(q["question"], s):
                unknown.append(s)
        here_note = ""
        if not slots:
            # typed questions name storeys without quotes: "doors on Level 1", "walls on the ground floor"
            storey = _unquoted_storey(m, q["question"])
            if storey is None:
                # "on this floor" asked on a plan sheet: that sheet's storey
                storey, ask = _here(m, q, pq)
                if ask:
                    return ask
                if storey is not None:
                    here_note = " (the storey of this plan sheet)"
            if storey is not None:
                sscore = 1.0
            elif re.search(_STOREY_WORD, pq["text"], re.I):
                return {**_abstain("the question names a storey I cannot find; " + _no_storey(m, None)),
                        "unparsed": True}  # the router may rewrite it with the storey names (bp/normalize.py)
        if storey is None and unknown:
            # a quoted name that is neither a storey of this model nor introduced as the model's name: answering
            # model-wide would silently ignore it ("doors on 'Level 99'" -> every door in the model)
            return _abstain(_no_storey(m, unknown[0]))
        what = pq["what"]
        if what is None:
            return _abstain("could not tell which element type the question is about")
        if what == "sanitary":
            els = M.sanitary(m, storey)
        else:
            els = M.elements_of(m, CLASSES[what][0], storey)
        scope = f"on storey '{storey['name']}'{here_note}" if storey else "in the model"
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
        here_note = ""
        if len(slots) >= 2:
            storey, sscore = M.match_storey(m, slots[-1])
            room = slots[0]
        elif len(slots) == 1:
            st, sc = M.match_storey(m, slots[0])
            if st is not None and (pq["total"] or sc == 1.0):
                storey, sscore = st, sc
            else:
                room = slots[0]
        if not slots:
            # unquoted, typed: "area of WC 414B-23-003-006 on 3. Level", "all rooms on the ground floor"
            storey = _unquoted_storey(m, q["question"])
            if storey is None:
                storey, ask = _here(m, q, pq)
                if ask:
                    return ask
                if storey is not None:
                    here_note = " (the storey of this plan sheet)"
            names_storey = storey is not None or re.search(_STOREY_WORD, pq["text"], re.I)
            # "floor area of this floor" means all its rooms, as "total" does
            if not (pq["total"] or here_note) or (names_storey and storey is None):
                return {**_abstain("could not tell which room or storey the question is about; " + _no_storey(m, None)),
                        "unparsed": True}
            sscore = 1.0 if storey is not None else 0.0
        if len(slots) >= 2 and storey is None:
            return _abstain(_no_storey(m, slots[-1]))
        if room is None:
            if storey is None:
                if slots:
                    return _abstain(_no_storey(m, slots[0]))
                els = M.elements_of(m, ["IfcSpace"])
            else:
                els = M.elements_of(m, ["IfcSpace"], storey)
            conf = 0.95 if sscore >= 1.0 or storey is None else 0.6
        else:
            els, rs = M.match_space(m, room, storey)
            if not els:
                # names containing an apostrophe break the quote parsing: 'IMMUNIZ'N ROOM (1D40)' on 'First Floor'
                mm = re.search(r"'(.+)'[^']+'([^']+)'", q["question"])
                if mm:
                    st2, sc2 = M.match_storey(m, mm.group(2))
                    els, rs = M.match_space(m, mm.group(1), st2)
                    if els:
                        storey = st2
            if not els:
                if pq["total"] and len(slots) == 1:
                    return _abstain(_no_storey(m, room))
                return _abstain(f"no room named '{room}'" + (f" on '{storey['name']}'" if storey else " in this model"))
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
        scope = f" on '{storey['name']}'{here_note}" if storey else ""
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

    # ------------------------------------------------------------------ comparisons (bp/compare.py)
    def _compare(self, m, q, cp, rel):
        """Rooms by net floor area (the measure of the room-area answers), storeys by their rooms' total area or by
        an element count (the count answers' containment rule)."""
        res = {"answer": None, "confidence": 0.0, "method": "ifc-compare", "cost_usd": 0.0, "evidence": [],
               "comparison": cp["op"]}
        by = M.storey_by_guid(m)
        spaces = M.elements_of(m, ["IfcSpace"])
        area = {}
        srcs = set()
        for e in spaces:
            v, src = M.measure(e, "area_floor")
            if v is not None:
                area[e["guid"]] = v
                srcs.add(src)
        conf = 0.95 if "geometry" not in srcs else 0.9

        def sname(st):
            return st["name"] or st["long_name"] or "?"

        def rname(e):
            st = by.get(e.get("storey"))
            return f"'{(M.space_labels(e) or [e.get('name') or e['guid']])[0]}'" + (f" on '{sname(st)}'" if st else "")

        def is_kind(e, kind):
            labs = M.space_labels(e)
            lab = re.sub(r"\s*\([^)]*\)\s*$", "", (e.get("long_name") or e.get("name") or "")).strip()
            toks = [lab] + re.split(r"[\s_/\-]+", lab)
            return any(RK.matches(kind, t) for t in toks if t) or bool(C.kind_of(" ".join(labs)) and
                                                                        C.kind_of(" ".join(labs))[0] == kind)

        def storey_in(text):
            """A storey named in the text (quoted or not), else None."""
            for sl in re.findall(r"'([^']+)'|\"([^\"]+)\"|«\s*([^»]+?)\s*»", text):
                name = next(x for x in sl if x)
                st, sc = M.match_storey(m, name)
                if st is not None and sc >= 1.0:
                    return st
            return _unquoted_storey(m, text)

        def done(answer, c, expl, els, valf, spaces_=True):
            return {**res, "answer": answer, "confidence": round(c, 3), "explanation": expl,
                    "evidence": self._ev_items(rel, els, valf), "_spaces": spaces_}

        def sheet_scope(text):
            """Storey a superlative is about: a named one, "this floor" / a plan sheet's own storey, else None."""
            st = storey_in(text)
            if st is not None:
                return st, ""
            sh = sheet_storey(m, q["path"])
            if sh is not None and not re.search(r"\b(?:building|model|house|whole|entire|geb(?:ä|a)ude|haus|"
                                                r"modell|b(?:â|a)timent|edificio|rakennu\w*|talo\w*|gebouw|"
                                                r"byggnad\w*|hela)\b", text):
                return sh, " (the storey of this plan sheet)"
            if re.search(HERE_FLOOR, text) and sh is None:
                return None, None
            return None, ""

        storey_word = rf"(?<!\w)(?:{C.STOREY})(?!\w)"
        cval = 1 if q.get("type") == "count" else None  # (a 1 on a text-typed answer would be drawn as "1 m²")
        if cp["op"] in ("max", "min"):
            best = max if cp["op"] == "max" else min
            word = ("largest" if cp["op"] == "max" else "smallest") if cp["measure"] == "area" else \
                ("most" if cp["op"] == "max" else "fewest")
            subj = cp["subject"]
            km = C.kind_of(subj)
            storeys = [s for s in m["storeys"]]
            if cp["measure"] == "count" or (re.search(storey_word, subj) and storey_in(subj) is None and km is None):
                # storeys compared: by an element count, or by their rooms' total net floor area
                if km is not None and cp["measure"] == "count" and not re.search(storey_word, subj):
                    return {**res, "explanation": "'most' / 'fewest' compares storeys in a model, e.g. 'which floor "
                            "has the most windows?'"}
                if cp["measure"] == "count":
                    what = _first_class(C._norm(cp["counted"]))
                    if what is None:
                        return {**res, "unparsed": True, "explanation": "could not tell what to count"}
                    if what == "sanitary":
                        per = {s["guid"]: M.sanitary(m, s) for s in storeys}
                    else:
                        per = {s["guid"]: M.elements_of(m, CLASSES[what][0], s) for s in storeys}
                    vals = {g: len(v) for g, v in per.items()}
                    unit, fmtv = _plural(what), str
                else:
                    per = {s["guid"]: [e for e in spaces if e.get("storey") == s["guid"] and e["guid"] in area]
                           for s in storeys}
                    vals = {g: round(sum(area[e["guid"]] for e in v), 2) for g, v in per.items()}
                    unit, fmtv = "m² of rooms", lambda v: f"{v:.2f}"
                if not storeys:
                    return {**res, "explanation": "no storeys in this model"}
                top = best(vals.values())
                win = [s for s in storeys if vals[s["guid"]] == top]
                expl = (f"{unit} per storey: " + ", ".join(f"'{sname(s)}' {fmtv(vals[s['guid']])}" for s in storeys)
                        + f"; {word}: " + " and ".join(f"'{sname(s)}'" for s in win))
                els = [e for s in win for e in per[s["guid"]]]
                ans = " and ".join(f"'{sname(s)}'" for s in win) + f" ({fmtv(top)} {unit})"
                return done(ans, conf if len(storeys) > 1 else 0.6, expl, els,
                            lambda e: round(area.get(e["guid"], 1), 4) if cp["measure"] == "area" else cval,
                            spaces_=cp["measure"] == "area" or what == "space")
            st, note = sheet_scope(subj)
            if note is None:
                return _abstain("'this floor' needs a storey, and this file is the whole model: which storey? "
                                + _no_storey(m, None), "ifc-compare")
            cands = [e for e in spaces if e["guid"] in area and (st is None or e.get("storey") == st["guid"])]
            kind = km[0] if km and km[0] != "room" else None
            if kind:
                cands = [e for e in cands if is_kind(e, kind)]
            desc = f"{RK.kind_name(kind)} spaces" if kind else "rooms (IfcSpace)"
            where = f" on '{sname(st)}'{note}" if st else " in the model"
            if not cands:
                return {**res, "explanation": f"no {desc}{where}"}
            top = best(area[e["guid"]] for e in cands)
            win = [e for e in cands if area[e["guid"]] == top]
            rest = sorted((e for e in cands if e not in win), key=lambda e: -area[e["guid"]] if cp["op"] == "max"
                          else area[e["guid"]])
            expl = (f"{word} of {len(cands)} {desc}{where} by net floor area: "
                    + " and ".join(f"{rname(e)} {area[e['guid']]:.2f} m²" for e in win))
            if rest:
                expl += "; next: " + ", ".join(f"{rname(e)} {area[e['guid']]:.2f} m²" for e in rest[:4])
            if st is not None and note:
                allc = [e for e in spaces if e["guid"] in area and (not kind or is_kind(e, kind))]
                tb = best(allc, key=lambda e: area[e["guid"]])
                if tb not in win:
                    expl += f" (in the whole model: {rname(tb)} {area[tb['guid']]:.2f} m²)"
            ans = " and ".join(rname(e) for e in win) + f" ({top:.2f} m²{' each' if len(win) > 1 else ''})"
            out = done(ans, conf, expl, win + rest, lambda e: round(area[e["guid"]], 4))
            for ev in out["evidence"][:len(win)] if len(cands) <= MAX_EVIDENCE else []:  # the winner(s) first, marked
                ev["label"] = f"{word}: {ev['label']}"
            return out

        # comparatives: two rooms, or two storeys
        def operand(text, count=False):
            st = storey_in(text)
            kmo = C.kind_of(text)
            sl = re.findall(r"'([^']+)'|\"([^\"]+)\"|«\s*([^»]+?)\s*»", text)
            names = [next(x for x in t if x) for t in sl]
            if count or (st is not None and not [n for n in names if M.match_storey(m, n)[0] is None]
                         and not (kmo and kmo[0] != "room")):
                return ("storey", st) if st is not None else ("error", "could not tell which storeys to compare")
            scope = st
            room = next((n for n in names if M.match_storey(m, n)[0] is None), None)
            if room is not None:
                els, rs = M.match_space(m, room, scope)
                if not els or rs < 1.0:
                    return "error", f"no room named '{room}'" + (f" on '{sname(scope)}'" if scope else "")
                return "room", els[0]
            # a room's own name typed without quotes ("is the cafeteria bigger than ..."): one space only
            pool = [e for e in spaces if scope is None or e.get("storey") == scope["guid"]]
            byname = [e for e in pool if any(len(x) >= 3 and re.search(rf"(?<!\w){re.escape(x.casefold())}(?!\w)",
                                                                      text) for x in (e.get("long_name"), e.get("name"))
                                             if x)]
            if len(byname) == 1:
                return "room", byname[0]
            if kmo and kmo[0] != "room":
                cands = [e for e in spaces if is_kind(e, kmo[0]) and (scope is None or e.get("storey") == scope["guid"])]
                if not cands:
                    return "error", f"no {RK.kind_name(kmo[0])} space" + (f" on '{sname(scope)}'" if scope else "")
                if len(cands) > 1:
                    return "error", (f"{len(cands)} {RK.kind_name(kmo[0])} spaces (" + ", ".join(rname(e) for e in
                                     cands[:8]) + "): name one in quotes")
                return "room", cands[0]
            return "error", "could not tell what to compare"

        a, b = operand(cp["left"], cp["measure"] == "count"), operand(cp["right"], cp["measure"] == "count")
        for x in (a, b):
            if x[0] == "error":
                return {**res, "unparsed": "could not tell" in x[1], "explanation": x[1]}
        if a[0] != b[0]:
            return {**res, "explanation": "compare two rooms or two storeys"}
        if a[1]["guid"] == b[1]["guid"]:
            return {**res, "explanation": "both sides of the comparison are the same"}
        if cp["measure"] == "count":
            what = _first_class(C._norm(cp["counted"]))
            if what is None:
                return {**res, "unparsed": True, "explanation": "could not tell what to count"}
            f = (lambda s: M.sanitary(m, s)) if what == "sanitary" else (lambda s: M.elements_of(m, CLASSES[what][0], s))
            ea, eb = f(a[1]), f(b[1])
            unit = _plural(what)
            na, nb, va, vb = f"'{sname(a[1])}'", f"'{sname(b[1])}'", len(ea), len(eb)
            els, valf, sp = ea + eb, (lambda e: cval), what == "space"
        elif a[0] == "storey":
            ea = [e for e in spaces if e.get("storey") == a[1]["guid"] and e["guid"] in area]
            eb = [e for e in spaces if e.get("storey") == b[1]["guid"] and e["guid"] in area]
            na, nb = f"'{sname(a[1])}'", f"'{sname(b[1])}'"
            va, vb = round(sum(area[e["guid"]] for e in ea), 2), round(sum(area[e["guid"]] for e in eb), 2)
            unit, els, valf, sp = "m²", ea + eb, (lambda e: round(area[e["guid"]], 4)), True
        else:
            if a[1]["guid"] not in area or b[1]["guid"] not in area:
                return {**res, "explanation": "no floor area for one of the rooms"}
            na, nb, va, vb = rname(a[1]), rname(b[1]), area[a[1]["guid"]], area[b[1]["guid"]]
            unit, els, valf, sp = "m²", [a[1], b[1]], (lambda e: round(area[e["guid"]], 4)), True
        expl, d = C.verdict_text(na, va, nb, vb, unit)
        if cp["op"] == "which2":
            if abs(d) < 1e-9:
                return done("equal", conf, expl, els, valf, sp)
            win = (na, va) if (d > 0) == (cp["dir"] > 0) else (nb, vb)
            return done(f"{win[0]} ({C.fmt(win[1], unit)})", conf, expl, els, valf, sp)
        if cp["op"] == "diff":
            ans = round(abs(d), 2) if cp["dir"] == 0 else round((1 if cp["dir"] > 0 else -1) * d, 2)
            if unit != "m²":
                ans = int(round(ans))
            neg, ans = ans < 0, C.typed(ans, unit, q.get("type"))
            return done(ans, conf, expl + (" (asked the other way round, so the difference is negative)"
                                           if neg else ""), els, valf, sp)
        if abs(d) < 1e-9:
            return done("no, they are equal", conf, expl, els, valf, sp)
        yes = d > 0 if cp["dir"] > 0 else d < 0
        if unit == "m²":
            ans = f"yes, by {C.fmt(abs(d), unit)}" if yes else \
                f"no, {na} is {'smaller' if cp['dir'] > 0 else 'larger'} by {C.fmt(abs(d), unit)}"
        else:
            ans = f"yes, by {C.fmt(abs(d), unit)}" if yes else \
                f"no, {na} has {C.fmt(abs(d), unit)} {'fewer' if cp['dir'] > 0 else 'more'}"
        return done(ans, conf, expl, els, valf, sp)
