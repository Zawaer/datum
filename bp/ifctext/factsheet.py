"""Compact, citable fact sheet of one IFC model, built from the cached extraction (bp.ifc.extract).

`build(m, rel)` -> list of blocks {"key", "title", "tags", "lines": [(fid|None, text)], "guids": {fid: [...]}}.
Every data line has a fact id (f1, f2, ...) and the GlobalIds it was computed from, so an answer that
cites "f12" can light up exactly those elements. `render(blocks, question, budget)` picks the blocks
relevant to a question (always: project, levels, class counts) and renders them as plain text.

v4 additions: site latitude/longitude and addresses (bp.ifctext.extras reads them from the IFC file), IFC2x3 MEP
classes split by kind of type entity (IfcFlowTerminal / WasteTerminal ...), type labels from the IFC type name
when the instance name is a code, ROOM CONTENTS (which furniture / terminals / equipment sit in which space),
phases, port connectivity, segment lengths from the Length property, layer thicknesses scaled by the file unit,
gross space areas, a per-kind summary of large system lists, and question-aware ranking of type blocks by kind.
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
    (r"pipe|piping|plumb|water|drain|heating|valve|pump|tank|fitting", {"mep"}),
    (r"duct|vent|air|hvac|damper|fan|terminal|heat recovery|filter", {"mep"}),
    (r"electr|light|lamp|luminaire|cable|conduit|switch|outlet|socket|junction|panel|board|communication|"
     r"data|alarm|sensor|detector|device|appliance|meter|measur|accessor|boiler|radiator|heater|equipment", {"mep"}),
    (r"mep|system|service|cooling|boiler", {"mep", "systems"}),
    (r"connect|port\b|ports\b|network|integrat", {"ports"}),
    (r"phas|renovat|existing|demoli|new construction|\bstatus\b", {"phases"}),
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


def _thick_mm(e, ls=None):
    """Thickness in mm: material layer sum (layer thicknesses are in file length units), else quantities,
    else the geometry extent (walls: across, slabs/coverings: vertical)."""
    wall = e["cls"].startswith("IfcWall")
    if not wall and not e["cls"].startswith(("IfcSlab", "IfcRoof", "IfcCovering")):
        return None
    lay = [t for _, t in e.get("mats") or [] if t]
    if lay and ls:
        return round(sum(lay) * ls * 1000)
    if wall:
        t = B._wall_thickness(e)
        return round(t * 1000) if t else None
    t = B._slab_thk(e)
    return round(t) if t else None


def _pset_len(e, ls):
    """Length property of a segment (Revit 'Dimensions' / Pset_*Segment 'Length', in file units) in m."""
    if not e["cls"].startswith(("IfcFlowSegment", "IfcPipe", "IfcDuct", "IfcCable")):
        return None
    for ps in (e.get("psets") or {}).values():
        for k in ("Length", "Länge", "Lengte"):
            v = ps.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                return v * ls
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


def _extras(m) -> dict:
    from bp.ifctext.extras import extras

    p = (m.get("meta") or {}).get("path")
    if not p:
        return {}
    try:
        return extras(p)
    except Exception:  # noqa: BLE001
        return {}


def _kind(e) -> str | None:
    """Specific kind of a generic IFC2x3 MEP element from its type entity (IfcFlowTerminal typed by
    IfcWasteTerminalType -> 'WasteTerminal'); None when the class already says it."""
    tc = e.get("type_cls") or ""
    if not tc.endswith("Type") and not tc.endswith("Style"):
        return None
    k = re.sub(r"(Type|Style)$", "", tc[3:])
    if not k or e["cls"][3:].startswith(k) or k in ("Building Element Proxy", "BuildingElementProxy"):
        return None
    return k


def _words(camel: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", camel).lower()


def _label(e) -> str:
    """Type label for grouping: B.tname, but the IFC type name when the instance name is a code ('[L]QQC')."""
    t = B.tname(e)
    tn = (e.get("type_name") or "").strip()
    if tn and tn != t and (re.match(r"^\[\w\]", t) or not re.search(r"[A-Za-z]{3}", t)):
        return re.sub(r":\d+$", "", tn)
    return t


_CODE = re.compile(r"^\[\w\]")


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
    ls = meta.get("length_scale") or 1.0

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
    ex = _extras(m)
    for x in ex.get("site") or []:
        parts = []
        if x.get("lat"):
            parts.append(f"latitude {x['lat']['text']} ({x['lat']['deg']})")
        if x.get("lon"):
            parts.append(f"longitude {x['lon']['text']} ({x['lon']['deg']})")
        if x.get("elevation") is not None:
            parts.append(f"reference elevation {_num(x['elevation'], 3)} m")
        if x.get("land_title"):
            parts.append(f"land title number {x['land_title']}")
        if parts:
            S.line(b, f"Site '{x.get('name')}' location (IfcSite RefLatitude/RefLongitude): " + "; ".join(parts),
                   [x["guid"]])
    for x in ex.get("address") or []:
        S.line(b, f"{x['of']} postal address: {x['text']}", [x["guid"]])
    pt = ex.get("ports")
    if pt:
        b2 = S.block("ports", "DISTRIBUTION NETWORK CONNECTIVITY (IfcDistributionPort)", ["ports", "mep"])
        n, c, el = pt["total"], pt["connected"], pt["elements_with_ports"]
        S.line(b2, f"Distribution ports: {n} total; connected (in an IfcRelConnectsPorts): {c} "
                   f"({_num(100 * c / n, 1)} %); unconnected: {n - c}; port connections: {pt['connections']}; "
                   f"elements with ports: {el}" + (f" ({_num(n / el, 2)} ports per element)" if el else "")
               + "; flow direction " + ", ".join(f"{k}: {v}" for k, v in pt["flow_direction"].items()),
               [x["guid"] for x in meta.get("IfcProject") or []] or None)
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
        kinds = collections.Counter(_kind(e) or "-" for e in els)
        ks = ""
        if len(kinds) > 1 or "-" not in kinds:
            ks = " (kinds by IFC type entity: " + ", ".join(f"{'other' if k == '-' else k}: {n}"
                                                             for k, n in kinds.most_common()) + ")"
        S.line(b, f"{cls}: {len(els)}" + ks + (f" (by level: {_fmt_counter(per, 8)})" if len(per) > 1 or
                                                "unassigned" not in per else ""), [e["guid"] for e in els])
    nsp = len(B.spaces(m))
    S.line(b, f"IfcSpace: {nsp}", [e["guid"] for e in B.spaces(m)] or None)

    # ---- types per class
    sc = M._schema(m)
    split = []
    for cls, els in bycls.items():
        kinds = collections.defaultdict(list)
        for e in els:
            kinds[_kind(e)].append(e)
        if len(kinds) > 1 and any(M.isa(cls, base, sc) for base in MEP_BASES):
            split += [(cls, k, g) for k, g in kinds.items()]  # IfcFlowTerminal -> WasteTerminal, SanitaryTerminal..
        else:
            split.append((cls, None if len(kinds) > 1 else next(iter(kinds)), els))
    for cls, kind, els in sorted(split, key=lambda x: -len(x[2])):
        is_mep = any(M.isa(cls, base, sc) for base in MEP_BASES)
        tags = {cls, "mep"} if is_mep else {cls}
        for base in ("IfcWall", "IfcSlab", "IfcDoor", "IfcWindow", "IfcColumn", "IfcBeam", "IfcCovering",
                     "IfcFurnishingElement", "IfcStair", "IfcRailing", "IfcFlowTerminal"):
            if M.isa(cls, base, sc):
                tags.add(base)
        if is_mep or cls == "IfcBuildingElementProxy":
            tags.add("other")
        if kind and kind.startswith("SanitaryTerminal"):
            tags.add("IfcSanitaryTerminal")
        kw = f" / {kind}" if kind else ""
        b = S.block(f"types:{cls}{kw}", f"{cls}{kw} TYPES ({len(els)} elements)", tags)
        b["kind"] = (_words(cls[3:]) + " " + (_words(kind) if kind else "")).strip()
        groups = collections.defaultdict(list)
        for e in els:
            groups[_label(e)].append(e)
        for k, g in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:MAX_TYPES]:
            parts = [f"{cls}{kw} type '{k}': {len(g)}"]
            ot = collections.Counter(re.sub(r":\d+$", "", e["obj_type"]) for e in g if e.get("obj_type"))
            ot = {x for x in ot if x != k and len(x) > len(k) and not re.fullmatch(r"[\d\W_]+", x)}
            if ot and len(ot) <= 3:
                parts.append("object type " + " / ".join(f"'{x}'" for x in sorted(ot)))
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
            th = collections.Counter(_thick_mm(e, ls) for e in g if _thick_mm(e, ls))
            if th:
                parts.append("thickness mm " + _fmt_counter(th, 3))
            for meas, unit, lab in (("length", "m", "total length"), ("area_side", "m2", "total side area"),
                                    ("volume", "m3", "total volume")):
                if meas == "area_side" and not cls.startswith("IfcWall"):
                    continue
                vals = [M.measure(e, meas)[0] or (_pset_len(e, ls) if meas == "length" else None) for e in g]
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
                ms = [f"{n} {round(t * ls * 1000, 1 if t * ls < 0.01 else None) if t else ''}".strip()
                      for n, t in e.get("mats") or [] if n]
                if ms:
                    mats[" + ".join(ms[:10])] += 1
            if mats:
                parts.append("materials (layer thickness mm) " + _fmt_counter(mats, 3))
            names = sorted({re.sub(r":\d+$", "", (e.get("name") or "").strip()) for e in g} - {"", k})
            if names and len(names) <= 15 and not all(re.fullmatch(r"[\d\W_]+", n) for n in names):
                parts.append("instance names " + ", ".join(names))
            sy = collections.Counter(s for e in g for s in (e.get("systems") or []))
            if sy:
                parts.append("systems " + _fmt_counter(sy, 3))
            S.line(b, "; ".join(parts), [e["guid"] for e in g])
        if len(groups) > MAX_TYPES:
            S.line(b, f"... {len(groups) - MAX_TYPES} more {cls}{kw} types")

    # ---- spaces
    b = S.block("spaces", "SPACES BY LEVEL (number | name | net floor area | height | other)", ["spaces"])
    for s in sts + [None]:
        sp = [e for e in B.spaces(m) if (e["storey"] == s["guid"] if s else e["storey"] not in sbyg)]
        if not sp:
            continue
        gross = sum(M.measure(e, "area_floor", gross=True)[0] or 0 for e in sp)
        net = sum(B.area(e) for e in sp)
        S.line(b, f"Level '{s['name'] if s else 'unassigned'}': {len(sp)} spaces, total {_num(net, 2)} m2"
               + (f" (gross {_num(gross, 2)} m2)" if abs(gross - net) > 0.05 else ""), [e["guid"] for e in sp])
        for e in sorted(sp, key=lambda e: str(e.get("name"))):
            parts = [f"  space '{e.get('name')}'"]
            if e.get("long_name"):
                parts.append(f"'{e['long_name']}'")
            a = B.area(e)
            if a:
                parts.append(f"{_num(a, 2)} m2")
            ga = M.measure(e, "area_floor", gross=True)[0]
            if ga and a and abs(ga - a) > 0.01:
                parts.append(f"gross {_num(ga, 2)} m2")
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

    # ---- room contents: furniture / terminals / equipment located in each space
    _contents(S, m, sname)

    # ---- phases (Revit 'Phase Created' / 'Phase Demolished', IFC Status)
    ph = collections.defaultdict(lambda: collections.defaultdict(list))
    for e in m["elements"]:
        if e["cls"] in SKIP:
            continue
        for ps in (e.get("psets") or {}).values():
            for k, v in ps.items():
                if v not in (None, "") and re.search(r"phase|^status$|bauphase|renovation|umbau", k, re.I):
                    ph[k][str(v)].append(e)
    if ph:
        b = S.block("phases", "PHASES / STATUS (property: value: element count by class)", ["phases"])
        for k, d in ph.items():
            for v, els in sorted(d.items(), key=lambda kv: -len(kv[1])):
                c = collections.Counter(e["cls"] for e in els)
                S.line(b, f"{k} = '{v}': {len(els)} elements ({_fmt_counter(c, 8)})", [e["guid"] for e in els])

    # ---- systems / zones
    if m.get("systems") or m.get("zones"):
        b = S.block("systems", "SYSTEMS AND ZONES", ["systems"])
        sy_all = m.get("systems") or []
        if len(sy_all) > 30:  # many systems: summary by kind first
            grp = collections.defaultdict(list)
            for sy in sy_all:
                grp[(sy["cls"], sy.get("obj_type") or re.sub(r"[\s_-]*\d+$", "", sy.get("name") or ""))].append(sy)
            for (c, k), g in sorted(grp.items(), key=lambda kv: -len(kv[1])):
                mem = [x if isinstance(x, str) else x.get("guid") for sy in g for x in sy.get("members") or []]
                S.line(b, f"{c} kind '{k}': {len(g)} systems, {len(mem)} members in total", mem or [sy["guid"] for sy in g])
        for sy in sy_all:
            mem = sy.get("members") or []
            S.line(b, f"{sy['cls']} '{sy.get('name')}'" + (f" ({sy.get('obj_type')})" if sy.get("obj_type") else "")
                   + (f" predefined {sy.get('predef')}" if sy.get("predef") else "") + f": {len(mem)} members",
                   [x if isinstance(x, str) else x.get("guid") for x in mem] or [sy["guid"]])
        for z in m.get("zones") or []:
            mem = z.get("members") or []
            S.line(b, f"IfcZone '{z.get('name')}'" + (f" '{z.get('long_name')}'" if z.get("long_name") else "")
                   + f": {len(mem)} members", [x if isinstance(x, str) else x.get("guid") for x in mem] or [z["guid"]])
    return S.blocks


CONTENT_BASES = ("IfcFurnishingElement", "IfcFlowTerminal", "IfcEnergyConversionDevice", "IfcFlowController",
                 "IfcDistributionControlElement", "IfcFlowMovingDevice", "IfcFlowStorageDevice",
                 "IfcFlowTreatmentDevice", "IfcTransportElement", "IfcBuildingElementProxy", "IfcElectricAppliance")


def _contents(S, m, sname):
    """Which furniture / terminals / equipment sit in which space: explicit IfcSpace containment, else the
    element's position (bbox centre or insertion point) inside the space's bounding box (smallest wins)."""
    sps = [e for e in B.spaces(m) if (e.get("geo") or {}).get("bbox")]
    ex = _extras(m)
    inside = ex.get("in_space") or {}
    pts = ex.get("points") or {}
    if not sps and not inside:
        return
    sc = M._schema(m)
    byg = {e["guid"]: e for e in B.spaces(m)}
    where = collections.defaultdict(list)
    for e in m["elements"]:
        if not any(M.isa(e["cls"], c, sc) for c in CONTENT_BASES):
            continue
        sp = byg.get(inside.get(e["guid"]))
        if sp is None:
            bb = (e.get("geo") or {}).get("bbox")
            if bb:
                p = ((bb[0][0] + bb[1][0]) / 2, (bb[0][1] + bb[1][1]) / 2, bb[0][2] + 0.05)
            elif e["guid"] in pts:
                p = pts[e["guid"]]
            else:
                continue
            best = None
            for s in sps:
                a, b2 = s["geo"]["bbox"]
                if a[0] - 0.05 <= p[0] <= b2[0] + 0.05 and a[1] - 0.05 <= p[1] <= b2[1] + 0.05 and \
                        a[2] - 0.5 <= p[2] <= b2[2] + 0.05:
                    ar = (b2[0] - a[0]) * (b2[1] - a[1])
                    if best is None or ar < best[0]:
                        best = (ar, s)
            sp = best[1] if best else None
        if sp is not None:
            where[sp["guid"]].append(e)
    if not where:
        return
    b = S.block("contents", "ROOM CONTENTS (furniture, sanitary, MEP terminals and equipment located in each space: "
                "explicit IfcSpace containment or position inside the space)", ["contents"])
    for s in sorted((byg[g] for g in where), key=lambda s: (sname.get(s["storey"], ""), str(s.get("name")))):
        els = where[s["guid"]]
        c = collections.Counter(f"{e['cls']}{'/' + _kind(e) if _kind(e) else ''} '{_label(e)}'" for e in els)
        S.line(b, f"  space '{s.get('name')}'" + (f" '{s['long_name']}'" if s.get("long_name") else "")
               + f" (level {sname.get(s['storey'], '?')}): " + ", ".join(f"{k}: {n}" for k, n in c.most_common()),
               [s["guid"]] + [e["guid"] for e in els])


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


# question words -> words of IFC kinds they mean (matched against the "kind" of a types block)
SYN = {"pipe accessor": "valve flow controller", "accessor": "valve flow controller", "fixture": "sanitary terminal",
       "toilet": "sanitary terminal", "basin": "sanitary terminal", "sink": "sanitary terminal",
       "shower": "sanitary terminal", "light": "light fixture lamp", "lamp": "light fixture lamp",
       "luminaire": "light fixture lamp", "radiator": "space heater", "heater": "space heater boiler",
       "boiler": "boiler", "measur": "flow meter", "meter": "flow meter", "fan": "fan", "pump": "pump",
       "damper": "damper", "valve": "valve", "tank": "tank", "heat recovery": "air to air heat recovery",
       "heat exchanger": "heat exchanger air to air heat recovery", "air terminal": "air terminal",
       "diffuser": "air terminal", "grille": "air terminal", "drain": "waste terminal", "waste": "waste terminal",
       "sensor": "sensor", "detector": "sensor alarm", "smoke": "sensor alarm", "alarm": "alarm",
       "switch": "switching device", "socket": "outlet", "outlet": "outlet", "receptacle": "outlet",
       "panel": "electric distribution point", "electrical": "electric", "filter": "filter",
       "sanitary": "sanitary terminal", "pipe fitting": "pipe fitting", "duct fitting": "duct fitting",
       "fitting": "fitting", "pipe": "pipe segment", "duct": "duct segment", "cable": "cable",
       "thermostat": "unitary control element sensor", "insulation": "covering", "appliance": "electric appliance",
       "elevator": "transport", "lift": "transport", "furniture": "furnishing",
       "mechanical": "unitary equipment air to air heat recovery fan pump boiler chiller"}
GENERIC = {"flow", "element", "device", "controller", "distribution", "control", "segment", "type", "building",
           "terminal", "fitting", "energy", "conversion", "proxy", "moving", "storage", "treatment", "standard",
           "case", "electric", "flow terminal"}
STOP = {"which", "what", "there", "their", "these", "those", "with", "including", "types", "building", "model",
        "total", "number", "different", "breakdown", "quantities", "quantity", "counts", "count", "level", "levels",
        "where", "located", "provide", "could", "would", "about", "present", "used", "installed", "available",
        "respective", "distributed", "distribution", "across", "each", "floor", "floors", "storey"}
ROOMQ = re.compile(r"\b(?:in|inside) (?:the |each |every |which )?[\w\- ]{0,25}?\b(?:room|space|bathroom|kitchen|office|toilet|wc)s?\b|which (?:rooms|spaces)|"
                   r"where (?:are|is)|located|location of|per (?:room|space)|each (?:room|space)|serve each space|"
                   r"\broom \w*\d|\bin room\b", re.I)


CONTENTQ = re.compile(r"furni|equipment|sanitar|fixture|terminal|items?\b|toilets?\b|\bwc|basin|sink|shower|urinal|"
                      r"radiator|heater|boiler|thermostat|detector|sensor|alarm|panel|valve|light|lamp|outlet|socket|"
                      r"\bmep\b|install|appliance|device|desk|chair|table|bed\b|cabinet|wardrobe|fridge|refrigerator|"
                      r"oven|cooktop|dishwasher|scann|machine|unit\b|extinguish|sprinkler|diffuser|grille", re.I)


def _kind_score(b, ql: str) -> int:
    kind = b.get("kind")
    if not kind:
        return 0
    q = re.sub(r"(\w{3,}?)(?:ies)\b", r"\1y", ql)
    q = re.sub(r"(\w{3,}?)s\b", r"\1", q)
    kw = kind.split()
    best = 0
    # the specific part of the kind ("waste terminal" of "flow terminal waste terminal")
    for n in (3, 2):
        for i in range(len(kw) - n + 1):
            ph = " ".join(kw[i:i + n])
            if ph not in ("flow terminal", "distribution element", "flow controller") and ph in q:
                best = max(best, 25 if n == 2 else 30)
    hits = [w for w in SYN if re.search(rf"\b{w}", q)]
    hits = [w for w in hits if not any(w != h and w in h for h in hits)]  # "pipe accessor" beats "pipe"
    for h in hits:
        if " " in h:
            q = q.replace(h, " ")
    for w in hits:
        tgt = SYN[w]
        if True:
            tw = tgt.split()
            if " ".join(tw) in kind:
                best = max(best, 20)
            elif any(x in kw and x not in GENERIC for x in tw):
                best = max(best, 12)
    for x in kw:
        if x not in GENERIC and len(x) > 3 and re.search(rf"\b{x}", q):
            best = max(best, 10)
    return best


def render(blocks: list[dict], question: str, budget: int = 14000, focus=None, space=None) -> tuple[str, list[dict]]:
    """Text of the relevant blocks within ~budget characters; returns (text, used blocks).
    focus: level names the question is about (their space lists are kept first when a block is cut);
    space: name of a space the question is about (its lines go first)."""
    topics = _topics(question)
    ql = question.lower()
    roomq = bool(ROOMQ.search(question)) or space is not None
    contentq = bool(CONTENTQ.search(question))
    qwords = {w for w in re.findall(r"[a-zà-ÿ]{5,}", ql) if w not in STOP}

    def rel(b):
        if b["key"] in ALWAYS:
            return 100
        s = len(b["tags"] & topics) * 10
        if b["key"].startswith("types:"):
            s += _kind_score(b, ql)
        if b["key"] == "contents" and roomq and contentq:
            s += 35
        if b["key"] == "spaces" and space is not None:
            s += 20
        # a type/name mentioned verbatim in the question
        for _, txt in b["lines"][:200]:
            mm = re.search(r"type '([^']{4,})'|space '([^']+)' '([^']{4,})'", txt)
            if mm and any(x and x.lower() in ql for x in mm.groups()):
                s += 5
                break
        if qwords and b["key"].startswith("types:"):
            blob = " ".join(t for _, t in b["lines"][:150]).lower()
            s += min(9, 3 * sum(1 for w in qwords if w in blob))
        return s

    def foc(lines):
        lines = _focus(lines, focus)
        if space:
            key = f"space '{space}'".lower()
            hit = [ln for ln in lines if key in ln[1].lower()]
            lines = hit + [ln for ln in lines if ln not in hit]
        return lines

    scores = {id(b): rel(b) for b in blocks}
    ranked = sorted(blocks, key=lambda b: -scores[id(b)])
    top = max((scores[id(b)] for b in blocks if b["key"] not in ALWAYS), default=0)
    used, out, size = [], [], 0
    for b in ranked:
        r = scores[id(b)]
        if r <= 0 and size > budget * 0.3:
            break
        lines = [f"[{fid}] {t}" if fid else t for fid, t in foc(b["lines"])]
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
