"""Query helpers over an extracted model table (see bp.ifc.extract).

Measure definitions (checked against the dev-split gold answers of ifc_models):
  * counts           - elements of the IFC class *including subtypes* (IfcWall counts IfcWallStandardCase),
                       top-level only: parts aggregated into another element (IfcStair risers/treads,
                       IfcStairFlight, wall parts) are not counted. Spaces: every IfcSpace.
                       "on the floor plan of <storey>": elements contained in that IfcBuildingStorey
                       (spatial containment, walking up aggregation for parts/spaces).
  * room net area    - quantity NetFloorArea (BaseQuantities / Qto_SpaceBaseQuantities) when present,
                       else the projected footprint area of the space's Body geometry (equals NetFloorArea
                       where both exist; e.g. Esplanades has no quantity sets).
  * wall length      - quantity Length (wall axis length), else extent along the wall's local X axis.
  * wall side area   - quantity NetSideArea, else geometric side area (largest side, net of openings).
  * net volume       - quantity NetVolume, else GrossVolume, else geometric volume of the Body.
"""
from __future__ import annotations

import difflib
import functools
import re
import unicodedata

import ifcopenshell


@functools.lru_cache(maxsize=4096)
def isa(cls: str, base: str, schema: str = "IFC4") -> bool:
    if cls == base:
        return True
    try:
        s = ifcopenshell.schema_by_name(schema if schema in ("IFC2X3", "IFC4", "IFC4X3") else "IFC4")
        d = s.declaration_by_name(cls)
    except Exception:  # noqa: BLE001
        return False
    while d is not None:
        if d.name() == base:
            return True
        d = d.supertype()
    return False


def _schema(m):
    sc = (m["meta"].get("schema") or "IFC4").upper()
    if sc.startswith("IFC4X3"):
        return "IFC4X3"
    if sc.startswith("IFC2X3"):
        return "IFC2X3"
    return "IFC4"


def nkey(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).casefold()
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", "", s)


def storey_by_guid(m):
    return {s["guid"]: s for s in m["storeys"]}


def match_storey(m, name: str):
    """Return (storey, score) for a quoted storey name; score 1.0 = exact (normalised)."""
    if not name:
        return None, 0.0
    k = nkey(name)
    for s in m["storeys"]:
        if k and k in (nkey(s["name"]), nkey(s["long_name"])):
            return s, 1.0
    for s in m["storeys"]:
        combos = [f"{s['name']} {s['long_name'] or ''}", f"{s['long_name'] or ''} ({s['name']})",
                  f"{s['name']} ({s['long_name'] or ''})"]
        if any(nkey(c) == k for c in combos):
            return s, 1.0
    best, bs = None, 0.0
    for s in m["storeys"]:
        for c in (s["name"], s["long_name"]):
            if not c:
                continue
            r = difflib.SequenceMatcher(None, k, nkey(c)).ratio()
            if r > bs:
                best, bs = s, r
    return (best, bs) if bs >= 0.75 else (None, bs)


def space_labels(e):
    n, ln = e.get("name") or "", e.get("long_name") or ""
    out = []
    if ln and n:
        out += [f"{ln} ({n})", f"{n} ({ln})", f"{n} {ln}", f"{ln} {n}"]
    out += [x for x in (ln, n) if x]
    return out


def match_space(m, name: str, storey=None):
    """Spaces whose label matches; returns (list, score)."""
    k = nkey(name)
    cands = [e for e in m["elements"] if e["cls"] == "IfcSpace"]
    if storey is not None:
        on = [e for e in cands if e["storey"] == storey["guid"]]
        cands = on or cands
    exact = [e for e in cands if any(nkey(lb) == k for lb in space_labels(e))]
    if exact:
        # prefer the full "long (name)" label when both a full and a partial label hit
        full = [e for e in exact if nkey(space_labels(e)[0]) == k]
        return (full or exact), 1.0
    best, bs = None, 0.0
    for e in cands:
        for lb in space_labels(e):
            r = difflib.SequenceMatcher(None, k, nkey(lb)).ratio()
            if r > bs:
                best, bs = e, r
    return ([best], bs) if bs >= 0.8 else ([], bs)


def elements_of(m, classes, storey=None, top_level=True):
    sc = _schema(m)
    out = []
    for e in m["elements"]:
        if not any(isa(e["cls"], c, sc) for c in classes):
            continue
        if top_level and e["cls"] != "IfcSpace" and e.get("parent_cls") and isa(e["parent_cls"], "IfcElement", sc):
            continue
        if storey is not None and e["storey"] != storey["guid"]:
            continue
        out.append(e)
    return out


def sanitary(m, storey=None):
    """IfcSanitaryTerminal (IFC4) or IfcFlowTerminal typed by IfcSanitaryTerminalType (IFC2x3)."""
    sc = _schema(m)
    out = []
    for e in m["elements"]:
        if storey is not None and e["storey"] != storey["guid"]:
            continue
        if isa(e["cls"], "IfcSanitaryTerminal", sc) or (e.get("type_cls") or "").startswith("IfcSanitaryTerminal"):
            out.append(e)
    return out


def _q(e, *names):
    for n in names:
        v = e["qto"].get(n)
        if v is not None and v > 0:
            return v
    return None


def measure(e, what: str, gross: bool = False):
    """(value, source) for one element; source says which definition was used."""
    g = e.get("geo") or {}
    if what == "area_floor":
        names = ("GrossFloorArea", "NetFloorArea") if gross else ("NetFloorArea", "GrossFloorArea")
        v = _q(e, *names)
        if v is not None:
            return v, "qto"
        if g.get("footprint"):
            return g["footprint"], "geometry"
        return None, None
    if what == "area_side":
        v = _q(e, *(("GrossSideArea", "NetSideArea") if gross else ("NetSideArea", "GrossSideArea")))
        if v is not None:
            return v, "qto"
        if g.get("side"):
            return g["side"], "geometry"
        return None, None
    if what == "area":
        v = _q(e, *(("GrossArea", "NetArea", "Area") if gross else ("NetArea", "GrossArea", "Area")))
        if v is not None:
            return v, "qto"
        if g.get("top"):
            return g["top"], "geometry"
        return None, None
    if what == "volume":
        v = _q(e, *(("GrossVolume", "NetVolume") if gross else ("NetVolume", "GrossVolume", "Volume")))
        if v is not None:
            return v, "qto"
        if g.get("volume"):
            return g["volume"], "geometry"
        return None, None
    if what == "length":
        v = _q(e, "Length")
        if v is not None:
            return v, "qto"
        if g.get("len_x"):
            return g["len_x"], "geometry"
        return None, None
    return None, None


def label(e) -> str:
    nm = e.get("name") or ""
    if e["cls"] == "IfcSpace":
        ls = space_labels(e)
        nm = ls[0] if ls else nm
    t = e.get("type_name")
    s = f"{e['cls']} '{nm}'" if nm else e["cls"]
    if t and t != nm:
        s += f" [{t}]"
    return s
