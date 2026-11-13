"""ifc_bench: free-text answers built from the extracted IFC tables.

Intent rules (English keyword regexes, the IFC-Bench questions are English) pick one of ~30 report
generators; each produces a short structured text plus the IFC elements it is based on as evidence.
Questions that the model cannot answer (live loads, warranties, embodied carbon, ...) get an honest
"not available in the BIM model" answer with low confidence.
"""
from __future__ import annotations

import collections
import re

from bp.ifc import model as M

NA = "This information is not available in the BIM model."


# ---------------------------------------------------------------- helpers
def _sc(m):
    return M._schema(m)


def of(m, *classes, top=True):
    return M.elements_of(m, list(classes), top_level=top)


def tname(e) -> str:
    """Human type label of an element: its name unless that is an instance id, else its type."""
    n = (e.get("name") or "").strip()
    if e["cls"].startswith("IfcSlab") and n:
        return re.sub(r":\d+$", "", n)
    t = (e.get("type_name") or "").strip()
    n2 = re.sub(r":\d+$", "", n)
    if n2 and not re.search(r"[-_ ]?\d{3,}$", n2) and not re.fullmatch(r"\d+", n2):
        return n2
    if t:
        return re.sub(r":\d+$", "", t)
    return n2 or "Unknown Type"


def prop(e, key):
    for d in (e.get("psets") or {}, e.get("tpsets") or {}):
        for ps in d.values():
            if key in ps and ps[key] not in (None, ""):
                return ps[key]
    return None


_EXT_LAYER = r"au(?:ß|ss)enw|exterior|external|ytterveg+er|outer wall|fassade|fa[cç]ade|fasade|ulkosein|v(?:ä|a)lissein"
_INT_LAYER = r"innenw|interior|internal|innerveg|inner wall|partition|zwischenw|v(?:æ|a)gge?|sein|vegg|wand|wall"


def is_external(e):
    """Pset *Common.IsExternal, else the CAD layer name (Außenwände / A23_Yttervegger ...)."""
    v = prop(e, "IsExternal")
    if isinstance(v, str):
        v = v.lower() in ("true", "yes", "1", ".t.")
    if v is not None:
        return v
    lay = " ".join(e.get("layers") or [])
    if not lay:
        return None
    if re.search(_EXT_LAYER, lay, re.I):
        return True
    if re.search(_INT_LAYER, lay, re.I):
        return False
    return None


def storeys(m):
    return [s for s in m["storeys"]]


def storey_name(m, guid):
    for s in m["storeys"]:
        if s["guid"] == guid:
            return s["name"]
    return "Unassigned"


def area(e):
    v, _ = M.measure(e, "area_floor")
    return v or 0.0


def spaces(m, storey=None):
    return [e for e in M.elements_of(m, ["IfcSpace"]) if storey is None or e["storey"] == storey["guid"]]


def r1(x):
    return f"{x:.1f}"


def pct(a, b):
    return f"{100.0 * a / b:.1f}%" if b else "0.0%"


def ev(rel, els, valf=lambda e: None, limit=400):
    out = []
    if len(els) > limit:
        groups = collections.defaultdict(list)
        for e in els:
            groups[(e["cls"], tname(e))].append(e)
        for (c, t), g in groups.items():
            out.append({"kind": "ifc", "file": rel, "guids": [e["guid"] for e in g], "label": f"{c} '{t}' x{len(g)}",
                        "value": len(g)})
        return out
    for e in els:
        out.append({"kind": "ifc", "file": rel, "guids": [e["guid"]], "label": M.label(e), "value": valf(e)})
    return out


def find_storey(m, text: str):
    """Resolve 'ground floor', 'level 2', 'basement', 'attic', or a storey name in the question."""
    t = text.lower()
    sts = [s for s in m["storeys"] if s["elevation"] is not None] or m["storeys"]
    # explicit storey names
    best = None
    for s in m["storeys"]:
        for n in (s["name"], s["long_name"]):
            if n and len(n) > 1 and re.search(rf"(?<!\w){re.escape(n.lower())}(?!\w)", t):
                if best is None or len(n) > best[1]:
                    best = (s, len(n))
    if best:
        return best[0]
    with_spaces = [s for s in sts if spaces(m, s)] or sts
    if not with_spaces:
        return None
    base = r"basement|keller|kjeller|k(?:æ|a)lder|cellar|souterrain|^ug\b|^b\d|underground|kelder|sous-sol|kellari"
    below = [i for i, s in enumerate(with_spaces) if re.search(base, f"{s['name']} {s['long_name'] or ''}", re.I)]
    if below and below[-1] + 1 < len(with_spaces):
        ground_i = below[-1] + 1
    else:
        ground_i = min(range(len(with_spaces)), key=lambda i: abs(with_spaces[i]["elevation"] or 0))
    if re.search(r"basement|underground|cellar|keller", t):
        return with_spaces[below[-1]] if below else with_spaces[0]
    if re.search(r"attic|roof level|top floor|dach", t):
        return with_spaces[-1]
    if re.search(r"ground (?:floor|level)", t):
        return with_spaces[ground_i]
    words = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
    mm = re.search(r"(first|second|third|fourth|fifth) (?:floor|level|storey)", t)
    n = words[mm.group(1)] if mm else None
    mm2 = re.search(r"(?:level|floor|storey) (\d+)", t)
    if mm2:
        n = int(mm2.group(1))
        if n == 0:
            return with_spaces[ground_i]
    if n is not None:
        i = ground_i + n
        if 0 <= i < len(with_spaces):
            return with_spaces[i]
    return None


def out(text, conf, method, evidence=None):
    return {"answer": text, "confidence": conf, "method": f"ifc-text-{method}", "cost_usd": 0.0,
            "explanation": text.splitlines()[0][:160] if text else "", "evidence": evidence or []}


# ---------------------------------------------------------------- generators
_USE = [("Office Building", r"b(?:ü|ue)ro|office|kontor|toimisto|workspace|meeting|besprechung"),
        ("Residential Building", r"wohn|bedroom|living|elutuba|magamis|apartment|bolig|sove|kitchen|k(?:ö|o)(?:ö|o)k"),
        ("Educational Building", r"classroom|klasse|seminar|lecture|auditor|undervisning"),
        ("Library", r"library|bibliot|boksamling"), ("Healthcare Building", r"patient|clinic|treatment|exam")]


def _guess_use(m):
    names = " ".join((e.get("long_name") or e.get("name") or "") for e in spaces(m)).lower()
    best = max(_USE, key=lambda u: len(re.findall(u[1], names)))
    return best[0] if re.search(best[1], names) else None


def g_building_info(m, q, rel):
    p = (m["meta"].get("IfcProject") or [{}])[0]
    b = (m["meta"].get("IfcBuilding") or [{}])[0]
    s = (m["meta"].get("IfcSite") or [{}])[0]
    use = b.get("obj_type") or _guess_use(m)
    t = q["question"].lower()
    n = len(m["storeys"])
    if re.search(r"type", t) and not re.search(r"project information|where|location|site", t):
        lines = [f"Building Type: {use or 'Not defined'}", f"   Building Name: {b.get('name') or 'Not defined'}",
                 f"   Total Levels: {n} floors"]
        return out("\n".join(lines), 0.5, "info")
    lines = ["Building Information:", f"   - Project Name: {p.get('name') or 'Not defined'}",
             f"   - Building Name: {b.get('name') or 'Not defined'}"]
    if b.get("long_name"):
        lines.append(f"   - Building Long Name: {b['long_name']}")
    lines.append(f"   - Building Usage/Occupancy: {use or 'Not defined in the IFC model'}")
    lines.append(f"   - Site/Location: {s.get('name') or 'Not defined'}")
    lines.append(f"   - Number of Levels: {n} storeys")
    return out("\n".join(lines), 0.5, "info")


def g_software(m, q, rel):
    h = m["meta"].get("header") or {}
    lines = ["Modeling Standards:", f"   - IFC Schema: {m['meta'].get('schema')}"]
    for d in h.get("description") or []:
        if d.lower().startswith(("viewdefinition", "exchangerequirement")):
            lines.append(f"   - {d}")
    lines.append("")
    lines.append("   Originating Application:")
    for a in m["meta"].get("applications") or []:
        lines.append(f"   - Software: {a['name']} {a['version'] or ''}".rstrip())
        if a.get("developer"):
            lines.append(f"   - Developer: {a['developer']}")
    if h.get("application"):
        lines.append(f"   - {h['application']}")
    if h.get("preprocessor"):
        lines.append(f"   - Preprocessor: {h['preprocessor']}")
    if h.get("time"):
        lines.append(f"   - Time Stamp: {h['time']}")
    return out("\n".join(lines), 0.6, "software")


def g_space_by_level(m, q, rel):
    sp = spaces(m)
    tot = sum(area(e) for e in sp)
    if re.search(r"number of levels", q["question"], re.I) and not re.search(r"program|breakdown", q["question"], re.I):
        fp = g_footprint(m, q, rel)
        gross = sum((M.measure(e, "area_floor", gross=True)[0] or 0) for e in sp)
        lines = ["Building Scale:", f"   - Number of Levels: {len(m['storeys'])}"]
        if fp:
            lines.append(f"   - Building Footprint Area: {fp['answer'].split(': ')[1].split(' (')[0]}")
        lines += [f"   - Total Floor Area: {r1(gross or tot)} sq m", f"   - Total Rooms/Spaces: {len(sp)}"]
        return out("\n".join(lines), 0.5, "scale", ev(rel, sp, lambda e: round(area(e), 2)))
    lines = ["Building Spatial Layout Overview:", f"   Total Building Levels: {len(m['storeys'])} storeys",
             f"   Total Spaces: {len(sp)} spaces across all levels", f"   Total Floor Area: {r1(tot)} sq m", "",
             "   Space Distribution by Level:"]
    for s in m["storeys"]:
        ss = spaces(m, s)
        if ss:
            a = sum(area(e) for e in ss)
            lines.append(f"   - {s['name']}: {len(ss)} spaces, {r1(a)} sq m ({pct(a, tot)})")
    return out("\n".join(lines), 0.6, "space-by-level", ev(rel, sp, lambda e: round(area(e), 2)))


def g_net_area_by_level(m, q, rel):
    sp = spaces(m)
    tot = sum(area(e) for e in sp)
    lines = [f"Total Net Floor Area: {r1(tot)} sq m", "", "   Net Floor Area by Level:"]
    for s in m["storeys"]:
        ss = spaces(m, s)
        if ss:
            a = sum(area(e) for e in ss)
            lines.append(f"   - {s['name']}: {r1(a)} sq m ({pct(a, tot)})")
    if sp:
        lines.append(f"\n   - Average space size: {r1(tot / len(sp))} sq m")
    return out("\n".join(lines), 0.6, "net-area", ev(rel, sp, lambda e: round(area(e), 2)))


def g_gross_area(m, q, rel):
    sl = [e for e in of(m, "IfcSlab") if (e.get("predef") or "").upper() in ("FLOOR", "BASESLAB", "NOTDEFINED", "")]
    sp = spaces(m)
    lines = ["Gross Floor Area by Level:"]
    tot = 0.0
    for s in m["storeys"]:
        a = sum((M.measure(e, "area_floor", gross=True)[0] or 0) for e in spaces(m, s))
        if a:
            lines.append(f"   - {s['name']}: {r1(a)} sq m")
            tot += a
    lines.insert(1, f"   Total Gross Floor Area: {r1(tot)} sq m")
    return out("\n".join(lines), 0.4, "gross-area", ev(rel, sp, lambda e: None))


def g_spaces_on_level(m, q, rel):
    st = find_storey(m, q["question"])
    if st is None:
        return None
    ss = sorted(spaces(m, st), key=lambda e: -area(e))
    tot = sum(area(e) for e in ss)
    grouped = re.search(r"function|group", q["question"], re.I)
    lvl = _level_word(m, st)
    lines = [f"{lvl} ({st['name']}): {len(ss)} spaces", f"   Total Area: {r1(tot)} sq m", ""]
    if grouped:
        g = collections.defaultdict(list)
        for e in ss:
            g[e.get("long_name") or e.get("name") or "Unnamed"].append(e)
        lines.append(f"   {lvl} Spaces by Function:")
        lines.append("")
        for k in sorted(g):
            lines.append(f"   {k}:")
            for e in sorted(g[k], key=lambda e: e.get("name") or ""):
                lines.append(f"     - {e.get('name')}: {r1(area(e))} sq m")
            lines.append("")
    else:
        for e in ss:
            if e.get("long_name"):
                lines.append(f"   - {e.get('long_name')} ({e.get('name')}): {r1(area(e))} sq m")
            else:
                lines.append(f"   - {e.get('name')}: {r1(area(e))} sq m")
    return out("\n".join(lines).rstrip(), 0.6, "spaces-on-level", ev(rel, ss, lambda e: round(area(e), 2)))


def _level_word(m, st):
    sts = [s for s in m["storeys"] if spaces(m, s)]
    if st not in sts:
        return "Level"
    g = sts.index(find_storey(m, "ground floor")) if find_storey(m, "ground floor") in sts else 0
    i = sts.index(st) - g
    if i < 0:
        return "Basement Level"
    if i == 0:
        return "Ground Level"
    if i == len(sts) - g - 1 and re.search(r"dach|attic|roof|loft|ullakko|katus", st["name"], re.I):
        return "Attic Level"
    return {1: "First Level", 2: "Second Level", 3: "Third Level", 4: "Fourth Level"}.get(i, f"Level {i}")


def g_all_spaces(m, q, rel):
    lines = []
    allsp = []
    for s in m["storeys"]:
        ss = sorted(spaces(m, s), key=lambda e: -area(e))
        if not ss:
            continue
        allsp += ss
        lines.append(f"{s['name']}:")
        for e in ss:
            nm = f"{e.get('long_name')} ({e.get('name')})" if e.get("long_name") else e.get("name")
            lines.append(f"   - {nm}: {r1(area(e))} sq m")
        lines.append("")
    return out("\n".join(lines).rstrip(), 0.5, "all-spaces", ev(rel, allsp, lambda e: round(area(e), 2)))


def g_room_names(m, q, rel):
    ss = spaces(m)
    names = sorted({e.get("name") or "" for e in ss})
    lines = ["The names of the rooms in the building are:"] + [f"- {n}" for n in names]
    return out("\n".join(lines), 0.5, "room-names", ev(rel, ss))


def g_levels(m, q, rel):
    sts = [s for s in m["storeys"] if s["elevation"] is not None]
    t = q["question"].lower()
    if re.search(r"elevation", t) and not re.search(r"height", t):
        lines = ["Building Level Elevations:"] + [f"   - {s['name']}: {s['elevation']:.2f} m above ground" for s in sts]
        return out("\n".join(lines), 0.6, "levels")
    lines = ["Building Level Information:"]
    for i, s in enumerate(sts):
        lines.append(f"   - {s['name']}:")
        lines.append(f"     Elevation: {r1(s['elevation'])} m")
        if i + 1 < len(sts):
            lines.append(f"     Height: {r1(sts[i + 1]['elevation'] - s['elevation'])} m")
        if i > 0 and re.search(r"floor.to.floor", t):
            lines.append(f"     Floor-to-floor height from {sts[i - 1]['name']}: "
                         f"{r1(s['elevation'] - sts[i - 1]['elevation'])} m")
    return out("\n".join(lines), 0.6, "levels")


def g_largest_room(m, q, rel):
    ss = spaces(m)
    if not ss:
        return None
    e = max(ss, key=area)
    lines = [f"Largest Room: {e.get('name')}", f"   Function: {e.get('long_name') or '-'}",
             f"   Area: {r1(area(e))} sq m", f"   Level: {storey_name(m, e['storey'])}"]
    h = _height(e)
    if h:
        lines.append(f"   Height: {h:.2f} m")
    return out("\n".join(lines), 0.7, "largest-room", ev(rel, [e], lambda e: round(area(e), 2)))


def _height(e):
    for k in ("FinishCeilingHeight", "Height", "ClearHeight"):
        v = e["qto"].get(k)
        if v:
            return v
    g = e.get("geo") or {}
    return g.get("len_z")


def g_ceiling_heights(m, q, rel):
    ss = [e for e in spaces(m) if _height(e)]
    if not ss:
        return out(NA, 0.3, "heights")
    low = re.search(r"lowest|smallest|minimum", q["question"], re.I)
    ss.sort(key=lambda e: _height(e), reverse=not low)
    hs = {round(_height(e), 2) for e in ss}
    if len(hs) == 1:
        return out(f"All rooms have a ceiling height of {hs.pop():.2f} m.", 0.6, "heights", ev(rel, ss))
    top = ss[:5]
    lines = [f"Rooms with {'lowest' if low else 'highest'} ceiling height:"]
    for i, e in enumerate(top, 1):
        lines.append(f"   {i}. {e.get('name')} ({e.get('long_name') or '-'})")
        lines.append(f"      Height: {_height(e):.2f} m, Level: {storey_name(m, e['storey'])}")
    return out("\n".join(lines), 0.5, "heights", ev(rel, top, lambda e: round(_height(e), 2)))


def g_room_height(m, q, rel):
    mm = re.search(r"room ([\w.\-]+)", q["question"], re.I)
    if not mm:
        return None
    sp = [e for e in spaces(m) if (e.get("name") or "").lower() == mm.group(1).lower()]
    if not sp or not _height(sp[0]):
        return None
    return out(f"The height of the ceiling in room {sp[0]['name']} is {_height(sp[0]):.2f} m.", 0.6, "room-height",
               ev(rel, sp[:1], lambda e: round(_height(e), 2)))


_KIND_WORD = {"IfcDoor": "doors", "IfcWindow": "windows", "IfcWall": "walls", "IfcColumn": "columns",
              "IfcBeam": "beams", "IfcStair": "stair(s)", "IfcRailing": "railing(s)", "IfcCovering": "coverings",
              "IfcFurnishingElement": "items", "IfcCurtainWall": "curtain walls", "IfcSlab": "slab(s)",
              "IfcMember": "members", "IfcPlate": "plates", "IfcRoof": "roofs", "IfcRamp": "ramps"}


def _label(c):
    return {"IfcDoor": "Door", "IfcWindow": "Window", "IfcWall": "Wall", "IfcColumn": "Column", "IfcBeam": "Beam",
            "IfcStair": "Stair", "IfcRailing": "Railing", "IfcCovering": "Covering",
            "IfcFurnishingElement": "Furniture", "IfcCurtainWall": "Curtain Wall", "IfcSlab": "Slab"}.get(c, c[3:])


def type_breakdown(m, q, rel, cls, scope=None):
    els = of(m, cls)
    if scope == "ext":
        els = [e for e in els if is_external(e) is True]
    elif scope == "int":
        els = [e for e in els if is_external(e) is False]
    lab = _label(cls)
    word = _KIND_WORD.get(cls, "elements")
    pre = {"ext": "Exterior ", "int": "Interior "}.get(scope, "")
    if not els:
        if scope and not [e for e in of(m, cls) if is_external(e) is not None]:
            return out(f"Exterior/interior classification (IsExternal) is not available for {lab.lower()}s in this "
                       f"model.", 0.4, "types")
        return out(f"No {pre}{lab} elements found in the model.\n   Total {pre}{lab}s: 0", 0.6, "types")
    c = collections.Counter(tname(e) for e in els)
    lines = [f"Total {pre}{lab}s: {len(els)}", "", f"   {pre}{lab} Types and Quantities:"]
    for k, n in c.most_common():
        lines.append(f"   - {k}: {n} {word} ({pct(n, len(els))})")
    if re.search(r"floor|level|distribution by floor", q["question"], re.I) and cls in ("IfcWindow", "IfcDoor",
                                                                                         "IfcFurnishingElement"):
        lines.append("")
        lines.append("   Distribution by Floor:")
        for s in m["storeys"]:
            n = sum(1 for e in els if e["storey"] == s["guid"])
            if n:
                lines.append(f"   - {s['name']}: {n} {word}")
    if cls in ("IfcWindow", "IfcDoor") and re.search(r"siz|dimension|width|height", q["question"], re.I):
        lines.append("")
        lines.append("   Sizes:")
        for k in c:
            ws = sorted({(round((e['attrs'].get('OverallWidth') or 0) * 1000), round((e['attrs'].get('OverallHeight')
                                                                                       or 0) * 1000))
                         for e in els if tname(e) == k})
            lines.append(f"   - {k}: " + ", ".join(f"{w}x{h}mm" for w, h in ws))
    return out("\n".join(lines), 0.6, "types", ev(rel, els, lambda e: 1))


def _width(e):
    w = e["attrs"].get("OverallWidth") or e["qto"].get("Width")
    return w


def g_door_window_width(m, q, rel, cls):
    els = [e for e in of(m, cls) if _width(e)]
    word = "Door" if cls == "IfcDoor" else "Window"
    if not els:
        return out(f"{word} width data is not available in this model.", 0.4, "width")
    t = q["question"].lower()
    els.sort(key=lambda e: -_width(e))
    ws = [_width(e) * 1000 for e in els]
    avg = sum(ws) / len(ws)
    if re.search(r"narrow|smallest|minimum", t) and not re.search(r"average|range", t):
        e = els[-1]
        return out(f"Smallest {word} Width:\n   {_width(e):.1f} m - {tname(e)}", 0.6, "width",
                   ev(rel, [e], lambda e: _width(e)))
    mm = re.search(r"\b(two|three|five|\d+)\b (?:doors|windows|largest|widest)", t)
    nmap = {"two": 2, "three": 3, "five": 5}
    if re.search(r"top 5|five", t):
        n = 5
    elif mm:
        n = nmap.get(mm.group(1)) or int(mm.group(1)) if mm.group(1).isdigit() or mm.group(1) in nmap else 1
    elif re.search(r"average", t):
        n = 0
    else:
        n = 1
    lines = []
    if n == 1:
        e = els[0]
        if not re.search(r"average|range|statistic", t):
            return out(f"Largest {word} Width:\n   {_width(e):.1f} m - {tname(e)}", 0.6, "width",
                       ev(rel, [e], lambda e: _width(e)))
        lines.append(f"Largest {word} Width:\n   {_width(e):.1f} m - {tname(e)}")
    elif n > 1 and re.search(r"which (?:two|three|\d+) ", t):
        lines = [f"The {mm.group(1) if mm else n} {word.lower()}s with the greatest widths in the building are:", ""]
        for i, e in enumerate(els[:n], 1):
            lines.append(f'{i}. "{e.get("name")}" - Width: {_width(e):.1f} m')
        return out("\n".join(lines), 0.6, "width", ev(rel, els[:n], lambda e: round(_width(e), 3)))
    elif n > 1:
        lines.append(f"Top {n} Largest {word} Widths:")
        for i, e in enumerate(els[:n], 1):
            lines.append(f"   {i}. {_width(e) * 1000:.0f} mm - {tname(e)}")
    lines.append("")
    lines.append(f"   {word} Width Statistics:")
    lines.append(f"   - Width range: {min(ws):.0f} - {max(ws):.0f} mm")
    lines.append(f"   - Average width: {avg:.0f} mm")
    lines.append(f"   - Maximum width: {max(ws):.0f} mm")
    lines.append(f"   - Minimum width: {min(ws):.0f} mm")
    return out("\n".join(lines), 0.5, "width", ev(rel, els[:max(n, 1)], lambda e: round(_width(e), 3)))


def _wall_thickness(e):
    w = e["qto"].get("Width") or e["qto"].get("Thickness")
    if w:
        return w
    lay = [t for _, t in e.get("mats") or [] if t]
    if lay:
        s = sum(lay)
        return s if s < 5 else s / 1000.0
    g = e.get("geo") or {}
    return g.get("len_y")


def g_wall_thickness(m, q, rel):
    els = of(m, "IfcWall")
    if re.search(r"external|exterior|outer|outside", q["question"], re.I):
        ext = [e for e in els if is_external(e)]
        els = ext or els
    by = collections.defaultdict(list)
    for e in els:
        th = _wall_thickness(e)
        if th:
            by[tname(e)].append(round(th * 1000))
    if not by:
        return out("Wall thickness data is not available in this model.", 0.3, "thickness")
    allv = [v for vs in by.values() for v in vs]
    if re.search(r"external|exterior", q["question"], re.I) and len(set(allv)) <= 2:
        c = collections.Counter(allv).most_common(1)[0][0]
        return out(f"The thickness of the external walls is {c} mm.", 0.5, "thickness", ev(rel, els))
    lines = ["Wall Thicknesses by Type:", f"   - Thickness range: {min(allv)} - {max(allv)} mm", ""]
    for k, vs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"   - {k}: " + ", ".join(f"{v}mm" for v in sorted(set(vs))) + f" ({len(vs)} walls)")
    return out("\n".join(lines), 0.5, "thickness", ev(rel, els, lambda e: None))


def g_materials(m, q, rel, cls="IfcWall", scope=None):
    els = of(m, cls)
    if scope == "ext":
        els = [e for e in els if is_external(e) is True]
    elif scope == "int":
        els = [e for e in els if is_external(e) is False]
    by = {}
    cnt = collections.Counter()
    mats_all = collections.Counter()
    for e in els:
        k = tname(e)
        cnt[k] += 1
        if e.get("mats") and k not in by:
            seen, uniq = set(), []
            for mn, th in e["mats"]:
                if (mn, th) not in seen:
                    seen.add((mn, th))
                    uniq.append((mn, th))
            by[k] = uniq
        for mn, _ in e.get("mats") or []:
            if mn:
                mats_all[mn] += 1
    pre = {"ext": "Exterior ", "int": "Interior "}.get(scope, "")
    word = _label(cls)
    if not mats_all:
        return out(f"No material information found for {pre.lower()}{word.lower()}s in this model.", 0.4, "materials")
    lines = [f"Total Unique Materials in {pre}{word}s: {len(mats_all)}", f"   {pre}{word} Types with Material Data: "
             f"{len(by)}", "", f"   {pre}{word} Materials and Usage:"]
    for mn, n in mats_all.most_common():
        lines.append(f"   - {mn}: {n} {word.lower()}s")
    lines.append("")
    lines.append(f"   {pre}{word} Type Material Compositions:")
    for k, mats in sorted(by.items(), key=lambda kv: -cnt[kv[0]]):
        lines.append(f"   {k} ({cnt[k]} {word.lower()}s):")
        tot = 0
        for mn, th in mats:
            if th:
                thm = th if th > 5 else th * 1000
                tot += thm
                lines.append(f"     - {mn}: {thm:.0f}mm")
            else:
                lines.append(f"     - {mn}")
        if tot:
            lines.append(f"     Total thickness: {tot:.0f}mm")
    return out("\n".join(lines), 0.5, "materials", ev(rel, els, lambda e: None))


def g_load_bearing(m, q, rel):
    els = of(m, "IfcWall")
    lb = [prop(e, "LoadBearing") for e in els]
    known = [v for v in lb if v is not None]
    if not known:
        return out("Load-bearing classification data is not available in this model.", 0.5, "loadbearing")
    yes = [e for e, v in zip(els, lb) if v is True or str(v).lower() == "true"]
    no = len(known) - len(yes)
    lines = [f"Total Walls: {len(els)}", f"   - Load-bearing walls: {len(yes)} ({pct(len(yes), len(els))})",
             f"   - Non-load-bearing walls: {no} ({pct(no, len(els))})"]
    if len(known) < len(els):
        lines.append(f"   - Unknown: {len(els) - len(known)}")
    c = collections.Counter(tname(e) for e in yes)
    if c:
        lines.append("")
        lines.append("   Load-bearing walls by type:")
        for k, n in c.most_common():
            lines.append(f"   - {k}: {n} walls")
    return out("\n".join(lines), 0.5, "loadbearing", ev(rel, yes, lambda e: 1))


def g_wall_length(m, q, rel):
    t = q["question"].lower()
    els = of(m, "IfcWall")
    parts = []
    want_ext = re.search(r"exterior|external|outside|outer", t)
    want_int = re.search(r"interior|internal|inside|inner", t)
    res = []
    for scope, flag in (("Exterior", True), ("Interior", False)):
        if (scope == "Exterior" and want_ext) or (scope == "Interior" and want_int) or not (want_ext or want_int):
            sel = [e for e in els if is_external(e) is flag]
            vals = [e["qto"].get("Length") for e in sel]  # quantity sets only, as IFC-Bench does
            vals = [v for v in vals if v]
            if not sel or not vals:
                return out("Wall length data is not available in this model.", 0.5, "wall-length")
            tot = sum(vals)
            res += sel
            parts.append(f"Total {scope} wall length is {r1(tot)} m.")
    return out("\n".join(parts), 0.5, "wall-length", ev(rel, res, lambda e: round(M.measure(e, "length")[0] or 0,
                                                                                    3)))


def g_furniture(m, q, rel):
    els = of(m, "IfcFurnishingElement")
    t = q["question"]
    room = re.search(r"in (?:the )?(.+?) on the (\w+ (?:floor|level))", t, re.I)
    if room:
        st = find_storey(m, room.group(2))
        kw = room.group(1).lower().replace("room", "").strip()
        sps = [e for e in spaces(m, st) if kw.split()[0] in (e.get("long_name") or "").lower()] if st and kw else []
        if sps:
            # furniture whose bbox centre lies inside a matched space's bbox
            inside = [e for e in els if any(_inside(e, s) for s in sps)]
            if inside:
                els = inside
    if not els:
        return out("No furniture elements found in the model.\n   Total Furniture Elements: 0", 0.6, "furniture")
    c = collections.Counter(tname(e) for e in els)
    lines = [f"Total Furniture Elements: {len(els)}", "", "   Furniture Types and Quantities:"]
    for k, n in c.most_common():
        lines.append(f"   - {k}: {n} items")
    if re.search(r"floor|level", t, re.I) and not room:
        lines.append("")
        lines.append("   Distribution by Floor:")
        for s in m["storeys"]:
            n = sum(1 for e in els if e["storey"] == s["guid"])
            if n:
                lines.append(f"   - {s['name']}: {n} items")
    return out("\n".join(lines), 0.5, "furniture", ev(rel, els, lambda e: 1))


def _inside(e, s):
    a, b = (e.get("geo") or {}).get("bbox"), (s.get("geo") or {}).get("bbox")
    if not a or not b:
        return False
    cx, cy = (a[0][0] + a[1][0]) / 2, (a[0][1] + a[1][1]) / 2
    return b[0][0] <= cx <= b[1][0] and b[0][1] <= cy <= b[1][1]


def _sanitary(m):
    return M.sanitary(m)


def _san_kind(e):
    s = " ".join(str(x or "") for x in (e.get("predef"), e.get("name"), e.get("type_name"), e.get("obj_type"))).lower()
    for k, rx in (("Toilets", r"toilet|wc|closet|klosett"), ("Urinals", r"urinal"), ("Showers", r"shower|dusj|dusch"),
                  ("Bathtubs", r"bath"), ("Basins", r"basin|lavatory|washbasin|servant|vask"),
                  ("Sinks", r"sink|kitchen|kjøkken"), ("Bidets", r"bidet")):
        if re.search(rx, s):
            return k
    return "Other"


def g_sanitary(m, q, rel):
    els = _sanitary(m)
    if not els:
        return out("No Sanitary fixtures were found in this model.", 0.6, "sanitary")
    c = collections.Counter(_san_kind(e) for e in els)
    types = collections.Counter(tname(e) for e in els)
    lines = [f"Total Sanitary Terminals: {len(els)}", f"   Total Sanitary Terminal Types: {len(types)}", "",
             "   Sanitary Equipment Types:"]
    for k, n in c.most_common():
        lines.append(f"   - {k}: {n} item(s)")
    lines.append("")
    for k, n in types.most_common():
        lines.append(f"   - {k}: {n}")
    return out("\n".join(lines), 0.5, "sanitary", ev(rel, els, lambda e: 1))


def g_toilets(m, q, rel):
    st = find_storey(m, q["question"])
    ss = [e for e in spaces(m, st) if re.search(r"\bwc|toilet|restroom|bad\b|bath|dusj|wc/", (e.get("long_name") or
                                                                                           e.get("name") or "").lower())]
    lines = [f"Toilet/WC spaces on {('floor ' + st['name']) if st else 'all floors'}: {len(ss)}", ""]
    for e in ss:
        lines.append(f"   - {e.get('name')}: {e.get('long_name') or ''} ({r1(area(e))} sq m)")
    return out("\n".join(lines), 0.4, "toilets", ev(rel, ss, lambda e: 1))


def g_slab_volume(m, q, rel):
    els = [e for e in of(m, "IfcSlab") if (e.get("predef") or "").upper() not in ("ROOF",)]
    vals = {e["guid"]: M.measure(e, "volume")[0] for e in els}
    vs = [v for v in vals.values() if v]
    if not vs:
        return out("Slab volume data is not available in this model.", 0.3, "slab-volume")
    lines = ["Floor Slabs Analysis:", f"   - Total floor slabs: {len(els)}",
             f"   - Total floor slab volume: {sum(vs):.2f} cu m", f"   - Volume range: {min(vs):.2f} cu m to "
             f"{max(vs):.2f} cu m"]
    if re.search(r"type|breakdown", q["question"], re.I):
        lines.append("")
        lines.append("   Floor Slab Breakdown:")
        for e in els[:60]:
            v = vals[e["guid"]] or 0
            a, _ = M.measure(e, "area")
            lines.append(f"   - {e.get('name') or tname(e)}:")
            lines.append(f"     Volume: {v:.2f} cu m")
            if a:
                lines.append(f"     Area: {r1(a)} sq m")
                lines.append(f"     Calculated Thickness: {v / a * 1000:.0f} mm")
    return out("\n".join(lines), 0.5, "slab-volume", ev(rel, els, lambda e: round(vals[e["guid"]] or 0, 3)))


def _slab_thk(e):
    w = e["qto"].get("Width") or e["qto"].get("Depth") or e["qto"].get("Thickness")
    if w:
        return w * 1000
    lay = [t for _, t in e.get("mats") or [] if t]
    if lay:
        s = sum(lay)
        return s if s > 5 else s * 1000
    g = e.get("geo") or {}
    return (g.get("len_z") or 0) * 1000 or None


def g_slab_types(m, q, rel):
    els = of(m, "IfcSlab")
    if not els:
        return out("No slab elements found in the model.", 0.5, "slab-types")
    roof = [e for e in els if (e.get("predef") or "").upper() == "ROOF"]
    floor = [e for e in els if e not in roof]
    lines = ["Slab Type Overview:", f"   - Floor slabs: {len(floor)}", f"   - Roof slabs: {len(roof)}",
             f"   - Total slabs: {len(els)}", ""]
    for name, grp in (("FLOOR", floor), ("ROOF", roof)):
        if not grp:
            continue
        lines.append(f"   {name} Slabs:")
        by = collections.defaultdict(list)
        for e in grp:
            by[tname(e)].append(e)
        for k, g in sorted(by.items(), key=lambda kv: -len(kv[1])):
            th = sorted({round(_slab_thk(e)) for e in g if _slab_thk(e)})
            ths = ", ".join(f"{t}mm" for t in th)
            lines.append(f"   - {k}: {len(g)} slab(s) ({pct(len(g), len(els))})" + (f", Thickness: {ths}" if ths else ""))
        lines.append("")
    return out("\n".join(lines).rstrip(), 0.5, "slab-types", ev(rel, els, lambda e: 1))


def g_structural(m, q, rel):
    beams, cols = of(m, "IfcBeam"), of(m, "IfcColumn")
    slabs = of(m, "IfcSlab")
    roof = [e for e in slabs if (e.get("predef") or "").upper() == "ROOF"]
    foot, memb = of(m, "IfcFooting"), of(m, "IfcMember")
    walls = of(m, "IfcWall")
    lbw = [e for e in walls if str(prop(e, "LoadBearing")).lower() == "true"]
    tot = len(beams) + len(cols) + len(slabs) + len(foot) + len(memb)
    lines = ["Structural Elements Summary:", f"   - Beams: {len(beams)} elements", f"   - Columns: {len(cols)} elements",
             f"   - Floor slabs: {len(slabs) - len(roof)} elements", f"   - Roof slabs: {len(roof)} elements",
             f"   - Foundations: {len(foot)} elements", f"   - Structural members: {len(memb)} elements",
             f"   - Load-bearing walls: {len(lbw)} elements", "", f"   Total Structural Elements: {tot}"]
    return out("\n".join(lines), 0.5, "structural", ev(rel, beams + cols + slabs + foot, lambda e: 1))


def _profile_dims(e):
    q = e["qto"]
    g = e.get("geo") or {}
    w = q.get("Width") or None
    d = q.get("Depth") or q.get("Height") if e["cls"] != "IfcColumn" else q.get("Depth")
    if not w and g:
        dims = sorted([g.get("len_x") or 0, g.get("len_y") or 0])
        if dims[0]:
            return f"{dims[1] * 1000:.0f}×{dims[0] * 1000:.0f}mm"
    if w and d:
        return f"{w * 1000:.0f}×{d * 1000:.0f}mm"
    if w:
        return f"{w * 1000:.0f}mm"
    return None


def g_column_dims(m, q, rel, cls="IfcColumn"):
    els = of(m, cls)
    word = _label(cls).lower()
    if not els:
        return out(f"No {word} elements found in the model.", 0.5, "dims")
    by = collections.defaultdict(list)
    for e in els:
        by[tname(e)].append(e)
    lines = [f"{_label(cls)} Dimensions by Type:", ""]
    for k, g in sorted(by.items()):
        lines.append(f"   {k}: {len(g)} {word}(s)")
        c = collections.Counter(_profile_dims(e) or "unknown size" for e in g)
        for d, n in c.most_common():
            lines.append(f"     - {d} ({n} {word}s)")
        lines.append("")
    return out("\n".join(lines).rstrip(), 0.4, "dims", ev(rel, els, lambda e: 1))


def g_fire(m, q, rel, cls):
    els = of(m, cls)
    word = "door" if cls == "IfcDoor" else "window"
    fr = [e for e in els if prop(e, "FireRating")]
    if not fr:
        return out(f"No {word} types have fire rating information in this model.", 0.6, "fire")
    c = collections.Counter((tname(e), str(prop(e, "FireRating"))) for e in fr)
    lines = [f"{len(fr)} of {len(els)} {word}s have fire rating information:", ""]
    for (k, r), n in c.most_common():
        lines.append(f"   - {k}: {r} ({n} {word}s)")
    return out("\n".join(lines), 0.5, "fire", ev(rel, fr, lambda e: 1))


_MEP_CLASSES = ["IfcFlowTerminal", "IfcFlowSegment", "IfcFlowFitting", "IfcFlowController", "IfcFlowMovingDevice",
                "IfcFlowStorageDevice", "IfcFlowTreatmentDevice", "IfcEnergyConversionDevice",
                "IfcDistributionControlElement", "IfcDistributionFlowElement"]


def _mep(m):
    sc = _sc(m)
    return [e for e in m["elements"] if any(M.isa(e["cls"], c, sc) for c in _MEP_CLASSES)]


def _mep_system(e):
    if e.get("systems"):
        return e["systems"][0]
    tc = (e.get("type_cls") or "")
    s = f"{e['cls']} {tc} {e.get('name') or ''} {e.get('type_name') or ''}".lower()
    for k, rx in (("Plumbing", r"sanitary|pipe|valve|tap|plumb|water|wc|toilet|basin|drain|waste"),
                  ("Ventilation", r"duct|air|vent|diffuser|fan|grille"),
                  ("Electrical", r"light|lamp|electric|outlet|socket|switch|cable|luminaire"),
                  ("Heating", r"heat|radiator|boiler|space ?heater"), ("Cooling", r"cool|chiller")):
        if re.search(rx, s):
            return k
    return "Other"


def g_mep(m, q, rel):
    els = _mep(m)
    t = q["question"].lower()
    if not els and not m.get("systems") and re.search(r"\bmep\b", t):
        return out("No explicit MEP systems found in this model.", 0.6, "mep")
    for kw, rx in (("heating", r"heat|radiator|boiler"), ("cooling", r"cool|chiller"),
                   ("electrical", r"light|lamp|electric|outlet|switch|luminaire|cable"),
                   ("lighting", r"light|lamp|luminaire")):
        if re.search(rf"\b{kw}", t) and not re.search(r"all mep|mep systems|by system", t):
            sel = [e for e in els if re.search(rx, f"{e['cls']} {e.get('type_cls') or ''} {e.get('name') or ''} "
                                                   f"{e.get('type_name') or ''} {' '.join(e.get('systems') or [])}",
                                               re.I)]
            if not sel:
                return out(f"No explicit {kw} system components found.", 0.5, "mep")
            c = collections.Counter(tname(e) for e in sel)
            lines = [f"{kw.capitalize()} components: {len(sel)}", ""] + [f"   - {k}: {n}" for k, n in c.most_common()]
            return out("\n".join(lines), 0.4, "mep", ev(rel, sel, lambda e: 1))
    by = collections.defaultdict(list)
    for e in els:
        by[_mep_system(e)].append(e)
    lines = ["MEP Components by System Type:"]
    for k, g in sorted(by.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"   - {k}: {len(g)} components")
        for c, n in collections.Counter(e["cls"] for e in g).most_common():
            lines.append(f"      - {c}: {n} components")
    if m.get("systems"):
        lines.append("")
        lines.append(f"   Defined IfcSystems: {len(m['systems'])}")
        for s in m["systems"][:30]:
            lines.append(f"   - {s['name']}: {len(s['members'])} elements")
    if re.search(r"floor|level", t):
        st = find_storey(m, q["question"])
        if st is not None:
            els2 = [e for e in els if e["storey"] == st["guid"]]
            lines.append("")
            lines.append(f"   On {st['name']}: {len(els2)} components")
            for c, n in collections.Counter(_mep_system(e) for e in els2).most_common():
                lines.append(f"   - {c}: {n}")
        else:
            lines.append("")
            lines.append("   Distribution by Floor:")
            for s in m["storeys"]:
                n = sum(1 for e in els if e["storey"] == s["guid"])
                if n:
                    lines.append(f"   - {s['name']}: {n} components")
    return out("\n".join(lines), 0.4, "mep", ev(rel, els, lambda e: 1))


def g_pipes(m, q, rel):
    sc = _sc(m)
    pipes = [e for e in m["elements"] if M.isa(e["cls"], "IfcPipeSegment", sc) or M.isa(e["cls"], "IfcPipeFitting", sc)
             or (e.get("type_cls") or "").startswith(("IfcPipeSegment", "IfcPipeFitting"))]
    ducts = [e for e in m["elements"] if M.isa(e["cls"], "IfcDuctSegment", sc)
             or (e.get("type_cls") or "").startswith("IfcDuctSegment")]
    t = q["question"].lower()
    if not pipes and not ducts:
        return out("No Pipe Segment or Pipe Fitting elements found in this model.", 0.6, "pipes")
    lines = []
    for nm, grp in (("Pipe", pipes), ("Duct", ducts)):
        if not grp:
            continue
        tot = sum((M.measure(e, "length")[0] or 0) for e in grp)
        lines.append(f"Total {nm} elements: {len(grp)}, total length: {r1(tot)} m")
        for k, n in collections.Counter(tname(e) for e in grp).most_common(20):
            lines.append(f"   - {k}: {n}")
    return out("\n".join(lines), 0.4, "pipes", ev(rel, pipes + ducts, lambda e: 1))


def g_coverings(m, q, rel):
    els = of(m, "IfcCovering")
    t = q["question"].lower()
    if "ceiling" in t:
        ceil = [e for e in els if (e.get("predef") or "").upper() == "CEILING"]
        slabs = [e for e in of(m, "IfcSlab") if re.search(r"himling|ceiling|decke|dekke", tname(e), re.I)]
        roof = [e for e in of(m, "IfcSlab") if (e.get("predef") or "").upper() == "ROOF"]
        sel = ceil + slabs
        mats = collections.Counter(mn for e in (sel or roof) for mn, _ in e.get("mats") or [] if mn)
        lines = [f"Ceiling Elements Found: {len(sel) or len(roof)}", f"   - Ceiling coverings: {len(ceil)}",
                 f"   - Ceiling slabs: {len(slabs)}", f"   - Roof slabs (potential ceilings): {len(roof)}", "",
                 "   Ceiling Materials:"]
        for mn, n in mats.most_common():
            lines.append(f"   - {mn} ({n} elements)")
        if not mats:
            lines.append("   - No material information")
        return out("\n".join(lines), 0.4, "ceilings", ev(rel, sel or roof, lambda e: 1))
    if not els:
        return out("Total Coverings: 0\n   No Covering elements found in the model.", 0.6, "coverings")
    c = collections.Counter((e.get("predef") or "NOTDEFINED", tname(e)) for e in els)
    lines = [f"Total Coverings: {len(els)}", "", "   Covering Types:"]
    for (p, k), n in c.most_common():
        lines.append(f"   - {k} ({p}): {n} elements")
    return out("\n".join(lines), 0.5, "coverings", ev(rel, els, lambda e: 1))


def g_count_simple(m, q, rel, cls, word):
    els = of(m, cls)
    t = q["question"].lower()
    if cls == "IfcDoor" and re.search(r"interior|internal", t):
        els = [e for e in els if is_external(e) is False] or els
    return out(f"There are {len(els)} {word} in this building.", 0.5, "count", ev(rel, els, lambda e: 1))


def g_bedrooms(m, q, rel, kw, word):
    ss = [e for e in spaces(m) if re.search(kw, f"{e.get('long_name') or ''} {e.get('name') or ''}", re.I)]
    return out(f"There are {len(ss)} {word} in the building.", 0.4, "rooms-kw", ev(rel, ss, lambda e: 1))


def g_door_by_guid(m, q, rel):
    mm = re.search(r"\b([0-9A-Za-z_$]{22})\b", q["question"])
    if not mm:
        return None
    e = next((x for x in m["elements"] if x["guid"] == mm.group(1)), None)
    if e is None:
        return None
    w = _width(e)
    if w and "width" in q["question"].lower():
        return out(f"The width of the {_label(e['cls']).lower()} with uuid {e['guid']} is {w:.2f} m.", 0.7, "guid",
                   ev(rel, [e], lambda e: round(w, 3)))
    return None


def g_vertical(m, q, rel):
    st, ra = of(m, "IfcStair"), of(m, "IfcRamp")
    tr = of(m, "IfcTransportElement")
    rl = of(m, "IfcRailing")
    lines = ["Vertical Circulation Elements:", f"   - Stairs: {len(st)}", f"   - Ramps: {len(ra)}",
             f"   - Elevators/Transport elements: {len(tr)}", f"   - Escalators: 0", f"   - Railings: {len(rl)}", ""]
    for k, n in collections.Counter(tname(e) for e in st).most_common():
        lines.append(f"   - {k}: {n} stair(s)")
    return out("\n".join(lines), 0.4, "vertical", ev(rel, st + ra + tr, lambda e: 1))


def g_space_function(m, q, rel):
    sp = spaces(m)
    tot = sum(area(e) for e in sp)
    g = collections.defaultdict(list)
    for e in sp:
        g[e.get("long_name") or e.get("name") or "Unnamed"].append(e)
    lines = ["Building Space Utilization Analysis:", f"   Total Functions: {len(g)}", f"   Total Area: {r1(tot)} sq m",
             "", "   Space Utilization by Function:"]
    for k, es in sorted(g.items(), key=lambda kv: -sum(area(e) for e in kv[1]))[:20]:
        a = sum(area(e) for e in es)
        lines.append(f"   - {k}: {r1(a)} sq m ({pct(a, tot)} of building), Spaces: {len(es)}")
    return out("\n".join(lines), 0.4, "functions", ev(rel, sp, lambda e: round(area(e), 2)))


def g_footprint(m, q, rel):
    sts = [s for s in m["storeys"] if spaces(m, s)]
    if not sts:
        return None
    best = max(sts, key=lambda s: sum((M.measure(e, "area_floor", gross=True)[0] or 0) for e in spaces(m, s)))
    a = sum((M.measure(e, "area_floor", gross=True)[0] or 0) for e in spaces(m, best))
    return out(f"Building Footprint Area: {r1(a)} sq m (largest storey: {best['name']})", 0.3, "footprint")


def g_facade(m, q, rel):
    ext = [e for e in of(m, "IfcWall") if is_external(e)]
    cw = of(m, "IfcCurtainWall")
    a = sum((M.measure(e, "area_side", gross=True)[0] or 0) for e in ext + cw)
    if not a:
        return out(NA, 0.2, "facade")
    return out(f"The total facade surface area is approximately {r1(a)} sq m ({len(ext)} exterior walls, "
               f"{len(cw)} curtain walls).", 0.3, "facade", ev(rel, ext + cw, lambda e: None))


def find_space(m, text):
    """Space named in free text: by number (e.g. 'room 01.014', 'A203') or by long name ('staff room')."""
    t = text.lower()
    st = find_storey(m, text) if re.search(r"floor|level|storey|etg|geschoss", t) else None
    cands = spaces(m, st) or spaces(m)
    best, bl = None, 0
    for e in cands:
        for n in (e.get("name"), e.get("long_name")):
            n = (n or "").strip().lower()
            if len(n) >= 3 and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", t) and len(n) > bl:
                best, bl = e, len(n)
    if best is None:
        # partial: words of a long name, e.g. 'staff room' ~ 'Personalrom' fails, 'Open-plan office' ~ 'Open-plan office 1'
        for e in cands:
            ln = (e.get("long_name") or "").lower()
            core = re.sub(r"\s*\d+$", "", ln)
            if len(core) >= 4 and core in t and len(core) > bl:
                best, bl = e, len(core)
    return best


def _in_space(m, sp, classes):
    els = []
    for c in classes:
        els += of(m, c)
    return [e for e in els if _inside(e, sp) and (e["storey"] == sp["storey"] or not e["storey"])]


def g_things_in_room(m, q, rel):
    sp = find_space(m, q["question"])
    if sp is None:
        return None
    t = q["question"].lower()
    if "sanitary" in t:
        els = [e for e in M.sanitary(m) if _inside(e, sp) and e["storey"] == sp["storey"]]
        lines = [f"Room {sp.get('name')} found:", f"   - Function: {sp.get('long_name') or '-'}",
                 f"   - Area: {r1(area(sp))} sq m", f"   - Level: {storey_name(m, sp['storey'])}", "",
                 "   Available sanitary equipment:"]
        for k, n in collections.Counter(_san_kind(e).rstrip("s") for e in els).most_common():
            lines.append(f"     - {k} ({n} item{'s' if n > 1 else ''})")
        return out("\n".join(lines), 0.4, "room-sanitary", ev(rel, [sp] + els, lambda e: 1))
    els = _in_space(m, sp, ["IfcFurnishingElement"])
    lines = [f"{sp.get('long_name') or sp.get('name')} ({sp.get('name')}, {storey_name(m, sp['storey'])}):",
             f"   - Total furniture items: {len(els)}", "", "   Furniture breakdown:"]
    for k, n in collections.Counter(tname(e) for e in els).most_common():
        lines.append(f"   - {k}: {n} item(s)")
    return out("\n".join(lines), 0.4, "room-furniture", ev(rel, [sp] + els, lambda e: 1))


_ROOM_KW = [("restroom", r"\bwc\b|toilet|restroom|lavatory|bad\b|dusj|wc/"), ("toilet", r"\bwc\b|toilet|restroom|wc/"),
            ("bathroom", r"bath|bad\b|dusj|shower"), ("bedroom", r"bed|schlaf|sove|makuu|magamis"),
            ("individual office", r"individual office|einzelb(?:ü|u)ro"),
            ("office", r"office|b(?:ü|u)ro|kontor|toimisto"), ("meeting", r"meeting|besprechung|m(?:ø|o)te"),
            ("kitchen", r"kitchen|k(?:ü|u)che|kj(?:ø|o)kken|keittiö"), ("storage", r"storage|lager|depot|abstell"),
            ("corridor", r"corridor|flur|korridor|gang")]


def g_room_kind(m, q, rel):
    t = q["question"].lower()
    kind = next(((k, rx) for k, rx in _ROOM_KW if k in t), None)
    if kind is None:
        return None
    k, rx = kind
    st = find_storey(m, q["question"]) if re.search(r"floor|level|storey", t) and "each floor" not in t else None
    ss = [e for e in spaces(m, st) if re.search(rx, f"{e.get('long_name') or ''} {e.get('name') or ''}", re.I)]
    if k == "office" and "individual" not in t:
        ss = [e for e in ss if not re.search(r"elevat|shaft|stair", e.get("long_name") or "", re.I)]
    tot = sum(area(e) for e in ss)
    title = k.capitalize() + ("s" if not k.endswith("s") else "")
    if "each floor" in t or "per floor" in t or "by floor" in t:
        lines = [f"{title} by Floor:", ""]
        for s_ in m["storeys"]:
            g = [e for e in ss if e["storey"] == s_["guid"]]
            if g:
                lines += [f"   {s_['name']}:", f"   - {title}: {len(g)}", f"   - Total area: {sum(area(e) for e in g):.2f} sq m", ""]
        lines.append(f"   Total {k}s in building: {len(ss)}")
        return out("\n".join(lines), 0.4, "room-kind", ev(rel, ss, lambda e: round(area(e), 2)))
    where = f" on {st['name']}" if st else ""
    lines = [f"{title}{where}:", f"   - Total {k} spaces: {len(ss)}", f"   - Total {k} area: {tot:.2f} sq m", ""]
    if "type" in t:
        g = collections.defaultdict(list)
        for e in ss:
            g[re.sub(r"\s*\d+$", "", e.get("long_name") or e.get("name") or "")].append(e)
        for name, es in sorted(g.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"   - {name}s: {len(es)}")
            for e in es:
                lines.append(f"     • {e.get('long_name') or e.get('name')} ({storey_name(m, e['storey'])}): {area(e):.2f} sq m")
            lines.append("")
    else:
        lines.append(f"   {title} spaces:")
        for e in ss:
            lines.append(f"   - {e.get('long_name') or e.get('name')}: {area(e):.2f} sq m")
    return out("\n".join(lines).rstrip(), 0.4, "room-kind", ev(rel, ss, lambda e: round(area(e), 2)))


_NA_TOPICS = (r"warranty|solar heat gain|glazing|thermal bridge|air.?tightness|live load|skirting|energy efficiency|"
              r"maintenance|voltage|capacit|embodied carbon|recycl|lifespan|life span|emergency|escape route|"
              r"accessib|doorknob|vapou?r barrier|electrical loads?")


def g_na(m, q, rel):
    return out(NA, 0.3, "na")


# ---------------------------------------------------------------- router
def _rules():
    T = type_breakdown
    return [
        (r"\b[0-9A-Za-z_$]{22}\b", g_door_by_guid),
        (_NA_TOPICS, g_na),
        (r"(?:furniture|sanitary).* in (?:the )?(?:room )?\S", g_things_in_room),
        (r"restroom|toilet .* on|office (?:spaces|rooms)|bedrooms? on|meeting rooms", g_room_kind),
        (r"software|application|modell?ing standard|ifc standard|ifc schema", g_software),
        (r"project information|building'?s type|type of building|building name|site location|where is it situated|"
         r"type and its function", g_building_info),
        (r"load.?bearing|structural walls", g_load_bearing),
        (r"fire.?rat\w* .*door|door.* fire.?rat", lambda m, q, r: g_fire(m, q, r, "IfcDoor")),
        (r"fire.?rat\w* .*window|window.* fire.?rat", lambda m, q, r: g_fire(m, q, r, "IfcWindow")),
        (r"(?:length|long).*(?:wall)|wall.*length", g_wall_length),
        (r"thickness.*wall|wall.*thickness", g_wall_thickness),
        (r"material.*(?:exterior|external|outer|outside) wall|(?:exterior|external|outer|outside) wall.*material",
         lambda m, q, r: g_materials(m, q, r, "IfcWall", "ext")),
        (r"material.*(?:interior|internal|inner|inside) wall|(?:interior|internal|inner|inside) wall.*material",
         lambda m, q, r: g_materials(m, q, r, "IfcWall", "int")),
        (r"material.*wall|wall.*material", lambda m, q, r: g_materials(m, q, r, "IfcWall")),
        (r"height of the ceiling in room", g_room_height),
        (r"ceiling.*(?:height|tall)|(?:height|tall|lowest).*ceiling", g_ceiling_heights),
        (r"ceiling materials?|material.*ceiling|coverings?", None),
        (r"curtain wall", lambda m, q, r: T(m, q, r, "IfcCurtainWall")),
        (r"(?:exterior|external|outer|outside).*wall|wall.*(?:exterior|external|outer|outside)",
         lambda m, q, r: T(m, q, r, "IfcWall", "ext")),
        (r"(?:interior|internal|inner|inside).*wall|wall.*(?:interior|internal|inner|inside)",
         lambda m, q, r: T(m, q, r, "IfcWall", "int")),
        (r"wall types?|types? of walls|walls? (?:are|is) used|kinds? of walls", lambda m, q, r: T(m, q, r, "IfcWall")),
        (r"door.*width|width.*door|widest door|narrowest door", lambda m, q, r: g_door_window_width(m, q, r, "IfcDoor")),
        (r"window.*width|width.*window|widest window|narrowest window",
         lambda m, q, r: g_door_window_width(m, q, r, "IfcWindow")),
        (r"interior doors", lambda m, q, r: g_count_simple(m, q, r, "IfcDoor", "interior doors")),
        (r"\bdoor", lambda m, q, r: T(m, q, r, "IfcDoor")),
        (r"\bwindow", lambda m, q, r: T(m, q, r, "IfcWindow")),
        (r"vertical circulation|elevator", g_vertical),
        (r"\bstair", lambda m, q, r: T(m, q, r, "IfcStair")),
        (r"railing", lambda m, q, r: T(m, q, r, "IfcRailing")),
        (r"volume.*slab|slab.*volume|concrete volume", g_slab_volume),
        (r"slab", g_slab_types),
        (r"column.*(?:size|dimension)|(?:size|dimension).*column", g_column_dims),
        (r"beam.*(?:size|dimension|span)|(?:size|dimension|span).*beam",
         lambda m, q, r: g_column_dims(m, q, r, "IfcBeam")),
        (r"\bcolumn", lambda m, q, r: T(m, q, r, "IfcColumn")),
        (r"\bbeam", lambda m, q, r: T(m, q, r, "IfcBeam")),
        (r"structural members?", lambda m, q, r: T(m, q, r, "IfcMember")),
        (r"structural|structure", g_structural),
        (r"toilets? .*(?:floor|level)|how many toilets", g_toilets),
        (r"sanitary", g_sanitary),
        (r"furniture", g_furniture),
        (r"pipe|piping|duct", g_pipes),
        (r"\bmep\b|heating|cooling|electrical|lighting|hvac|plumbing", g_mep),
        (r"largest room|biggest room|largest space|room.*(?:largest|biggest)", g_largest_room),
        (r"height of the ceiling in room|ceiling .*room [\w.]+", g_room_height),
        (r"bedrooms?", lambda m, q, r: g_bedrooms(m, q, r, r"bed|schlaf|sove|makuu", "bedrooms")),
        (r"bathrooms?", lambda m, q, r: g_bedrooms(m, q, r, r"bath|bad|wc|toilet", "bathrooms")),
        (r"names of all the rooms|list of (?:each|all) room", g_room_names),
        (r"spaces? (?:are )?on|spaces in the|spaces on|space breakdown of the|breakdown of the .*(?:floor|level)",
         g_spaces_on_level),
        (r"utili[sz]|by function", g_space_function),
        (r"space breakdown for all|complete space breakdown|breakdown by level, with individual", g_all_spaces),
        (r"space (?:distribution|breakdown)|by level|number of levels|total spaces", g_space_by_level),
        (r"net (?:usable )?floor area", g_net_area_by_level),
        (r"gross (?:floor )?area", g_gross_area),
        (r"elevation|heights? of each level|floor.to.floor|level heights|heights of the levels", g_levels),
        (r"footprint", g_footprint),
        (r"fa[cç]ade", g_facade),
    ]


def answer_text(m, q, rel):
    t = q["question"]
    for rx, fn in _rules():
        if re.search(rx, t, re.I):
            if fn is None:
                fn = g_coverings
            try:
                r = fn(m, q, rel)
            except Exception:  # noqa: BLE001
                r = None
            if r is not None:
                return r
    return {"answer": NA, "confidence": 0.15, "method": "ifc-text-na", "cost_usd": 0.0,
            "explanation": "no rule matched; the model does not hold this information explicitly", "evidence": []}
