"""Compact, citable fact sheet of one IFC model, built from the cached extraction (bp.ifc.extract).

`build(m, rel)` -> list of blocks {"key", "title", "tags", "lines": [(fid|None, text)], "guids": {fid: [...]}}.
Every data line has a fact id (f1, f2, ...) and the GlobalIds it was computed from, so an answer that
cites "f12" can light up exactly those elements. `render(blocks, question, budget)` picks the blocks
relevant to a question (always: project, levels, class counts) and renders them as plain text.
"""
from __future__ import annotations

import collections
import re

from bp.ifc import bench as B
from bp.ifc import model as M

SKIP = {"IfcOpeningElement", "IfcVirtualElement", "IfcDistributionPort", "IfcAnnotation", "IfcGrid",
        "IfcSpace", "IfcBuildingElementPart", "IfcGeographicElement"}

# question keywords -> block tags
TOPICS = [
    (r"room|space|area|floor|level|storey|unit|apartment|office|kitchen|toilet|bath|bed|ceiling height|tall|"
     r"largest|smallest|biggest|function|occup|capacity|zone", {"spaces", "levels"}),
    (r"elevation|height|level|storey|floor", {"levels"}),
    (r"wall|partition|fa[cç]ade|exterior|interior|load.?bearing|structur|thick", {"IfcWall", "IfcCurtainWall"}),
    (r"door|opening|entrance|exit|fire", {"IfcDoor"}),
    (r"window|glaz|opening|fire", {"IfcWindow"}),
    (r"slab|floor|roof|concrete|landing|thick", {"IfcSlab", "IfcRoof"}),
    (r"column|pillar|structur|load", {"IfcColumn"}),
    (r"beam|structur|span", {"IfcBeam", "IfcMember"}),
    (r"stair|vertical|circulation|elevator|lift|ramp|escalator|railing", {"IfcStair", "IfcRamp", "IfcRailing",
                                                                        "IfcTransportElement", "IfcStairFlight"}),
    (r"furni|desk|chair|table|sofa|bed|cabinet|equipment", {"IfcFurnishingElement", "IfcFurniture"}),
    (r"sanitar|toilet|wc|basin|sink|shower|urinal|bath|plumb", {"IfcSanitaryTerminal", "IfcFlowTerminal"}),
    (r"cover|ceiling|finish|cladding|floor(?:ing)? material", {"IfcCovering"}),
    (r"material|made of|composition|concrete|steel|timber|wood|carbon", {"materials"}),
    (r"foundation|footing|pile", {"IfcFooting", "IfcPile"}),
    (r"pipe|piping|plumb|water|drain|heating|valve|pump|tank|fitting", {"mep", "systems"}),
    (r"duct|vent|air|hvac|damper|fan|terminal|heat recovery|filter", {"mep", "systems"}),
    (r"electr|light|lamp|luminaire|cable|conduit|switch|outlet|socket|junction|panel|board|communication|"
     r"data|alarm|sensor|detector|device|appliance", {"mep", "systems"}),
    (r"mep|system|service|heating|cooling|boiler|radiator|heater", {"mep", "systems"}),
    (r"software|application|standard|schema|author|organi[sz]ation|created|project|building|site|address|"
     r"location|situated|type of building|building type|purpose|use", {"project"}),
    (r"type|kind|categor|breakdown|quantit|count|how many|number", {"counts"}),
    (r"proxy|element|object|component|misc", {"other"}),
]

MAX_TYPES = 150  # type lines per class
HARD_CAP = 40000  # the best-matching blocks may grow the sheet up to this many characters

MEP_BASES = ["IfcDistributionElement", "IfcFlowSegment", "IfcFlowFitting", "IfcFlowTerminal", "IfcFlowController",
             "IfcEnergyConversionDevice", "IfcFlowMovingDevice", "IfcFlowStorageDevice", "IfcFlowTreatmentDevice",
             "IfcDistributionControlElement"]


def _num(x, nd=2):
    if x is None:
        return None
    s = f"{x:,.{nd}f}".replace(",", " ")
    return s.rstrip("0").rstrip(".") if "." in s else s


def _thick_mm(e):
    if e["cls"].startswith("IfcWall"):
        t = B._wall_thickness(e)
        return round(t * 1000) if t else None
    if e["cls"].startswith("IfcSlab") or e["cls"].startswith("IfcRoof") or e["cls"].startswith("IfcCovering"):
        t = B._slab_thk(e)
        return round(t) if t else None
    return None


def _boolprop(e, key):
    v = B.prop(e, key)
    if isinstance(v, str):
        v = {"true": True, ".t.": True, "yes": True, "false": False, ".f.": False, "no": False}.get(v.lower(), v)
    return v


def _fmt_counter(c: collections.Counter, n=6):
    items = c.most_common()
    s = ", ".join(f"{k}: {v}" for k, v in items[:n])
    if len(items) > n:
        s += f", +{len(items) - n} more"
    return s


class Sheet:
    def __init__(self):
        self.blocks = []
        self.n = 0

    def block(self, key, title, tags):
        b = {"key": key, "title": title, "tags": set(tags) | {key}, "lines": [], "guids": {}}
        self.blocks.append(b)
        return b

    def line(self, b, text, guids=None):
        if guids:
            self.n += 1
            fid = f"f{self.n}"
            b["lines"].append((fid, text))
            b["guids"][fid] = list(guids)
        else:
            b["lines"].append((None, text))


def build(m: dict) -> list[dict]:
    B._prep(m)
    S = Sheet()
    sbyg = {s["guid"]: s for s in m["storeys"]}
    sname = {s["guid"]: s["name"] for s in m["storeys"]}
    meta = m["meta"]

    # ---- project / building / file
    b = S.block("project", "PROJECT, BUILDING, SITE, FILE", ["project"])
    hdr = meta.get("header") or {}
    apps = meta.get("applications") or []
    S.line(b, f"IFC schema: {meta.get('schema')}; file description: "
              + "; ".join(d for d in (hdr.get("description") or []) if "ViewDefinition" in d)[:200])
    app = ", ".join(f"{a.get('name')} {a.get('version') or ''} by {a.get('developer')}".strip() for a in apps)
    S.line(b, f"Authoring application: {app}; originating system: {hdr.get('application')}; "
              f"preprocessor: {hdr.get('preprocessor')}; timestamp: {hdr.get('time')}; "
              f"author: {', '.join(x for x in hdr.get('author') or [] if x)}; "
              f"organization: {', '.join(x for x in hdr.get('organization') or [] if x)}")
    for cls in ("IfcProject", "IfcSite", "IfcBuilding"):
        for x in meta.get(cls) or []:
            parts = [f"{cls[3:]}: name '{x.get('name')}'"]
            for k in ("long_name", "description", "obj_type"):
                if x.get(k):
                    parts.append(f"{k} '{x[k]}'")
            ps = []
            for pn, props in (x.get("psets") or {}).items():
                if len(props) > 25:
                    continue
                for k, v in props.items():
                    if v not in (None, "", 0, 0.0) and not isinstance(v, (list, dict)) and f"{k}={v}" not in ps:
                        ps.append(f"{k}={v}")
            if ps:
                parts.append("properties: " + "; ".join(ps[:25]))
            S.line(b, "; ".join(parts), [x["guid"]])
    use = B._guess_use(m)
    if use:
        S.line(b, f"Likely building use (from room names): {use}")

    # ---- levels
    b = S.block("levels", "LEVELS (IfcBuildingStorey, sorted by elevation)", ["levels"])
    sts = m["storeys"]
    for i, s in enumerate(sts):
        sp = B.spaces(m, s)
        n_el = sum(1 for e in m["elements"] if e["storey"] == s["guid"])
        q = (s.get("psets") or {}).get("BaseQuantities") or {}
        parts = [f"Level '{s['name']}'" + (f" (long name '{s['long_name']}')" if s.get("long_name")
                                           and not str(s["long_name"]).startswith("ACID") else ""),
                 f"elevation {_num(s['elevation'], 3)} m" if s["elevation"] is not None else "elevation unknown"]
        if i + 1 < len(sts) and s["elevation"] is not None and sts[i + 1]["elevation"] is not None:
            parts.append(f"floor-to-floor to '{sts[i + 1]['name']}' {_num(sts[i + 1]['elevation'] - s['elevation'], 3)} m")
        for k in ("GrossHeight", "NetHeight", "GrossFloorArea", "NetFloorArea"):
            if q.get(k):
                parts.append(f"{k} {_num(q[k])}")
        parts.append(f"{len(sp)} spaces, space area {_num(sum(B.area(e) for e in sp), 1)} m2, {n_el} elements")
        S.line(b, "; ".join(parts), [s["guid"]])

    # ---- class counts
    b = S.block("counts", "ELEMENT COUNTS BY IFC CLASS (whole model; per level)", ["counts"])
    bycls = collections.defaultdict(list)
    for e in m["elements"]:
        if e["cls"] in SKIP:
            continue
        if e.get("parent_cls") and e["parent_cls"] == e["cls"]:
            continue
        bycls[e["cls"]].append(e)
    for cls, els in sorted(bycls.items(), key=lambda kv: -len(kv[1])):
        per = collections.Counter(sname.get(e["storey"], "unassigned") for e in els)
        S.line(b, f"{cls}: {len(els)}" + (f" (by level: {_fmt_counter(per, 8)})" if len(per) > 1 or
                                           "unassigned" not in per else ""), [e["guid"] for e in els])
    nsp = len(B.spaces(m))
    S.line(b, f"IfcSpace: {nsp}", [e["guid"] for e in B.spaces(m)] or None)

    # ---- types per class
    sc = M._schema(m)
    for cls, els in sorted(bycls.items(), key=lambda kv: -len(kv[1])):
        is_mep = any(M.isa(cls, base, sc) for base in MEP_BASES)
        tags = {cls, "mep"} if is_mep else {cls}
        for base in ("IfcWall", "IfcSlab", "IfcDoor", "IfcWindow", "IfcColumn", "IfcBeam", "IfcCovering",
                     "IfcFurnishingElement", "IfcStair", "IfcRailing", "IfcFlowTerminal"):
            if M.isa(cls, base, sc):
                tags.add(base)
        if is_mep or cls == "IfcBuildingElementProxy":
            tags.add("other")
        b = S.block(f"types:{cls}", f"{cls} TYPES ({len(els)} elements)", tags)
        groups = collections.defaultdict(list)
        for e in els:
            groups[B.tname(e)].append(e)
        for k, g in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:MAX_TYPES]:
            parts = [f"{cls} type '{k}': {len(g)}"]
            tc = {e.get('type_name') for e in g if e.get('type_name') and e.get('type_name') != k}
            if tc and len(tc) <= 3:
                parts.append("IFC type " + " / ".join(sorted(tc)))
            pre = collections.Counter(str(e.get("predef")) for e in g if e.get("predef") not in (None, "NOTDEFINED",
                                                                                                    "USERDEFINED"))
            if pre:
                parts.append("predefined " + _fmt_counter(pre, 3))
            per = collections.Counter(sname.get(e["storey"], "unassigned") for e in g)
            if len(per) > 1:
                parts.append("by level " + _fmt_counter(per, 6))
            elif per:
                parts.append(f"level {next(iter(per))}")
            th = collections.Counter(_thick_mm(e) for e in g if _thick_mm(e))
            if th:
                parts.append("thickness mm " + _fmt_counter(th, 3))
            for meas, unit, lab in (("length", "m", "total length"), ("area_side", "m2", "total side area"),
                                    ("volume", "m3", "total volume")):
                if meas == "area_side" and not cls.startswith("IfcWall"):
                    continue
                vals = [M.measure(e, meas)[0] for e in g]
                vals = [v for v in vals if v]
                if vals and (meas != "length" or cls.startswith(("IfcWall", "IfcBeam", "IfcPipe", "IfcDuct",
                                                                 "IfcCable", "IfcFlowSegment", "IfcMember",
                                                                 "IfcRailing", "IfcColumn", "IfcPile"))):
                    parts.append(f"{lab} {_num(sum(vals), 2)} {unit}")
            if cls.startswith(("IfcSlab", "IfcRoof", "IfcCovering")):
                ar = [M.measure(e, "area")[0] or M.measure(e, "area_floor")[0] for e in g]
                ar = [v for v in ar if v]
                if ar:
                    parts.append(f"total area {_num(sum(ar), 2)} m2")
            if cls.startswith(("IfcDoor", "IfcWindow")):
                dims = collections.Counter(
                    f"{round((e['attrs'].get('OverallWidth') or 0) * 1000)}x{round((e['attrs'].get('OverallHeight') or 0) * 1000)}"
                    for e in g if e["attrs"].get("OverallWidth"))
                if dims:
                    parts.append("W x H mm " + _fmt_counter(dims, 4))
            if cls.startswith(("IfcColumn", "IfcBeam", "IfcMember")):
                d = collections.Counter(B._profile_dims(e) for e in g if B._profile_dims(e))
                if d:
                    parts.append("section " + _fmt_counter(d, 3))
            for key, lab in (("IsExternal", "external"), ("LoadBearing", "load-bearing")):
                v = collections.Counter((B.is_external(e) if key == "IsExternal" else _boolprop(e, key)) for e in g)
                v.pop(None, None)
                if v:
                    parts.append(f"{lab} " + _fmt_counter(collections.Counter({str(a): n for a, n in v.items()}), 3))
            fr = collections.Counter(str(B.prop(e, "FireRating")) for e in g if B.prop(e, "FireRating"))
            if fr:
                parts.append("fire rating " + _fmt_counter(fr, 3))
            mats = collections.Counter()
            for e in g:
                ms = [f"{n} {round(t * 1000) if t and t < 5 else round(t) if t else ''}".strip()
                      for n, t in e.get("mats") or [] if n]
                if ms:
                    mats[" + ".join(ms[:6])] += 1
            if mats:
                parts.append("materials " + _fmt_counter(mats, 2))
            names = sorted({re.sub(r":\d+$", "", (e.get("name") or "").strip()) for e in g} - {"", k})
            if names and len(names) <= 15 and not all(re.fullmatch(r"[\d\W_]+", n) for n in names):
                parts.append("instance names " + ", ".join(names))
            sy = collections.Counter(s for e in g for s in (e.get("systems") or []))
            if sy:
                parts.append("systems " + _fmt_counter(sy, 3))
            S.line(b, "; ".join(parts), [e["guid"] for e in g])
        if len(groups) > MAX_TYPES:
            S.line(b, f"... {len(groups) - MAX_TYPES} more {cls} types")

    # ---- spaces
    b = S.block("spaces", "SPACES BY LEVEL (number | name | net floor area | height | other)", ["spaces"])
    for s in sts + [None]:
        sp = [e for e in B.spaces(m) if (e["storey"] == s["guid"] if s else e["storey"] not in sbyg)]
        if not sp:
            continue
        S.line(b, f"Level '{s['name'] if s else 'unassigned'}': {len(sp)} spaces, total {_num(sum(B.area(e) for e in sp), 2)} m2",
               [e["guid"] for e in sp])
        for e in sorted(sp, key=lambda e: str(e.get("name"))):
            parts = [f"  space '{e.get('name')}'"]
            if e.get("long_name"):
                parts.append(f"'{e['long_name']}'")
            a = B.area(e)
            if a:
                parts.append(f"{_num(a, 2)} m2")
            h = B._height(e)
            if h:
                parts.append(f"h {_num(h, 2)} m")
            for key in ("Category", "OccupancyType", "Reference"):
                v = B.prop(e, key)
                if v:
                    parts.append(f"{key} {v}")
            if e.get("obj_type"):
                parts.append(f"type {e['obj_type']}")
            S.line(b, " | ".join(parts), [e["guid"]])

    # ---- materials
    b = S.block("materials", "MATERIALS (material: element count by class)", ["materials"])
    mat = collections.defaultdict(lambda: collections.defaultdict(list))
    for e in m["elements"]:
        for n, _t in e.get("mats") or []:
            if n:
                mat[n][e["cls"]].append(e["guid"])
    for n, d in sorted(mat.items(), key=lambda kv: -sum(len(v) for v in kv[1].values()))[:60]:
        S.line(b, f"{n}: " + ", ".join(f"{c} {len(v)}" for c, v in sorted(d.items(), key=lambda kv: -len(kv[1]))),
               [g for v in d.values() for g in v])

    # ---- systems / zones
    if m.get("systems") or m.get("zones"):
        b = S.block("systems", "SYSTEMS AND ZONES", ["systems", "mep"])
        for sy in m.get("systems") or []:
            mem = sy.get("members") or []
            S.line(b, f"{sy['cls']} '{sy.get('name')}'" + (f" ({sy.get('obj_type')})" if sy.get("obj_type") else "")
                   + (f" predefined {sy.get('predef')}" if sy.get("predef") else "") + f": {len(mem)} members",
                   [x if isinstance(x, str) else x.get("guid") for x in mem] or [sy["guid"]])
        for z in m.get("zones") or []:
            mem = z.get("members") or []
            S.line(b, f"IfcZone '{z.get('name')}'" + (f" '{z.get('long_name')}'" if z.get("long_name") else "")
                   + f": {len(mem)} members", [x if isinstance(x, str) else x.get("guid") for x in mem] or [z["guid"]])
    return S.blocks


def _topics(question: str) -> set:
    t = question.lower()
    out = set()
    for rx, tags in TOPICS:
        if re.search(rx, t):
            out |= tags
    return out


ALWAYS = ("project", "levels", "counts")


def _focus(lines, focus):
    """Move the lines of the focused level sections ("Level 'X': ...", then indented lines) to the front."""
    if not focus:
        return lines
    head, rest, cur = [], [], None
    for ln in lines:
        t = ln[1]
        if not t.startswith("  "):
            mm = re.match(r"Level '(.*)':", t)
            cur = mm and mm.group(1) in focus
        (head if cur else rest).append(ln)
    return head + rest


def render(blocks: list[dict], question: str, budget: int = 14000, focus=None) -> tuple[str, list[dict]]:
    """Text of the relevant blocks within ~budget characters; returns (text, used blocks).
    focus: level names the question is about (their space lists are kept first when a block is cut)."""
    topics = _topics(question)
    ql = question.lower()

    def rel(b):
        if b["key"] in ALWAYS:
            return 100
        s = len(b["tags"] & topics) * 10
        # a type/name mentioned verbatim in the question
        for _, txt in b["lines"][:200]:
            mm = re.search(r"type '([^']{4,})'|space '([^']+)' '([^']{4,})'", txt)
            if mm and any(x and x.lower() in ql for x in mm.groups()):
                s += 5
                break
        return s

    ranked = sorted(blocks, key=lambda b: -rel(b))
    top = max((rel(b) for b in blocks if b["key"] not in ALWAYS), default=0)
    used, out, size = [], [], 0
    for b in ranked:
        r = rel(b)
        if r <= 0 and size > budget * 0.3:
            break
        lines = [f"[{fid}] {t}" if fid else t for fid, t in _focus(b["lines"], focus)]
        text = f"## {b['title']}\n" + "\n".join(lines)
        room = (max(budget, HARD_CAP) if top > 0 and r == top else budget) - size
        if len(text) > room:
            if r < 10 or room < 600:
                continue
            keep, n = [], len(b["title"]) + 4
            for ln in lines:
                if n + len(ln) > room - 80:
                    break
                keep.append(ln)
                n += len(ln) + 1
            text = f"## {b['title']}\n" + "\n".join(keep) + f"\n... ({len(lines) - len(keep)} more lines omitted)"
        out.append(text)
        used.append(b)
        size += len(text)
    return "\n\n".join(out), used
