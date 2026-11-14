"""Facts the cached extraction (bp.ifc.extract) does not keep, read once per model straight from the IFC file.

`extras(path)` -> {"site": [...], "address": [...], "points": {guid: [x, y, z]}, "in_space": {guid: space guid}}
  site      IfcSite RefLatitude / RefLongitude / RefElevation / LandTitleNumber (decoded to degrees)
  address   IfcPostalAddress of the site / building
  points    world insertion point (m) of furniture, terminals and other equipment (for room containment)
  in_space  elements explicitly contained in an IfcSpace (IfcRelContainedInSpatialStructure)
Cached as JSON under cache/ifctext_extras/ (keyed by path, size and mtime).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

CACHE = Path(os.environ.get("BP_CACHE", "cache")) / "ifctext_extras"
VERSION = 2
# equipment that sits inside a room (not segments/fittings/structure)
CONTENT_BASES = ("IfcFurnishingElement", "IfcFlowTerminal", "IfcEnergyConversionDevice", "IfcFlowController",
                 "IfcDistributionControlElement", "IfcFlowMovingDevice", "IfcFlowStorageDevice",
                 "IfcFlowTreatmentDevice", "IfcTransportElement", "IfcBuildingElementProxy")
_MEM: dict = {}
_LOCK = threading.Lock()


def _dms(v):
    if not v:
        return None
    v = list(v)
    sign = -1 if any(x < 0 for x in v) else 1
    v = [abs(x) for x in v] + [0] * (4 - len(v))
    deg = v[0] + v[1] / 60 + (v[2] + v[3] / 1e6) / 3600
    sec = v[2] + v[3] / 1e6
    return {"deg": round(sign * deg, 6), "text": f"{'-' if sign < 0 else ''}{v[0]}° {v[1]}' {round(sec, 4)}\""}


def _addr(a):
    if a is None:
        return None
    parts = []
    for k in ("AddressLines", "PostalBox", "Town", "Region", "PostalCode", "Country"):
        x = getattr(a, k, None)
        if isinstance(x, (list, tuple)):
            parts += [str(y) for y in x if y]
        elif x:
            parts.append(str(x))
    return ", ".join(parts) or None


def _compute(path: str) -> dict:
    import ifcopenshell
    import ifcopenshell.util.placement as up
    import ifcopenshell.util.unit as uu

    f = ifcopenshell.open(path)
    try:
        ls = uu.calculate_unit_scale(f)
    except Exception:  # noqa: BLE001
        ls = 1.0
    out = {"site": [], "address": [], "points": {}, "in_space": {}}
    for s in f.by_type("IfcSite"):
        d = {"guid": s.GlobalId, "name": s.Name}
        lat, lon = _dms(getattr(s, "RefLatitude", None)), _dms(getattr(s, "RefLongitude", None))
        if lat:
            d["lat"] = lat
        if lon:
            d["lon"] = lon
        if getattr(s, "RefElevation", None) is not None:
            d["elevation"] = round(s.RefElevation * ls, 3)
        if getattr(s, "LandTitleNumber", None):
            d["land_title"] = s.LandTitleNumber
        a = _addr(getattr(s, "SiteAddress", None))
        if a:
            out["address"].append({"guid": s.GlobalId, "of": "Site", "text": a})
        out["site"].append(d)
    for b in f.by_type("IfcBuilding"):
        a = _addr(getattr(b, "BuildingAddress", None))
        if a:
            out["address"].append({"guid": b.GlobalId, "of": "Building", "text": a})
    for rel in f.by_type("IfcRelContainedInSpatialStructure"):
        st = rel.RelatingStructure
        if st is not None and st.is_a("IfcSpace"):
            for e in rel.RelatedElements or []:
                out["in_space"][e.GlobalId] = st.GlobalId
    # distribution ports and their connections (network connectivity)
    try:
        ports = f.by_type("IfcDistributionPort")
    except RuntimeError:
        ports = []
    if ports:
        connected = set()
        for rel in f.by_type("IfcRelConnectsPorts"):
            for p in (rel.RelatingPort, rel.RelatedPort):
                if p is not None:
                    connected.add(p.id())
        owners = set()
        for rel in f.by_type("IfcRelConnectsPortToElement"):
            if rel.RelatedElement is not None:
                owners.add(rel.RelatedElement.id())
        try:
            for rel in f.by_type("IfcRelNests"):
                if any(o.is_a("IfcDistributionPort") for o in rel.RelatedObjects or []):
                    owners.add(rel.RelatingObject.id())
        except RuntimeError:
            pass
        flows = {}
        for p in ports:
            fd = str(getattr(p, "FlowDirection", None) or "NOTDEFINED")
            flows[fd] = flows.get(fd, 0) + 1
        out["ports"] = {"total": len(ports), "connected": len([p for p in ports if p.id() in connected]),
                        "connections": len(f.by_type("IfcRelConnectsPorts")), "elements_with_ports": len(owners),
                        "flow_direction": flows}
    for base in CONTENT_BASES:
        try:
            xs = f.by_type(base)
        except RuntimeError:
            continue
        for e in xs:
            if e.GlobalId in out["points"] or getattr(e, "ObjectPlacement", None) is None:
                continue
            try:
                mt = up.get_local_placement(e.ObjectPlacement)
                out["points"][e.GlobalId] = [round(float(mt[i][3]) * ls, 3) for i in range(3)]
            except Exception:  # noqa: BLE001
                pass
    return out


def extras(path) -> dict:
    p = Path(path)
    key = str(p.resolve())
    if key in _MEM:
        return _MEM[key]
    with _LOCK:
        if key in _MEM:
            return _MEM[key]
        st = p.stat()
        h = hashlib.sha1(f"{key}|{st.st_size}|{int(st.st_mtime)}|{VERSION}".encode()).hexdigest()[:12]
        cf = CACHE / f"{p.stem}-{h}.json"
        if cf.exists():
            r = json.loads(cf.read_text())
        else:
            try:
                r = _compute(str(p))
            except Exception as e:  # noqa: BLE001
                r = {"site": [], "address": [], "points": {}, "in_space": {}, "error": repr(e)[:200]}
            CACHE.mkdir(parents=True, exist_ok=True)
            cf.write_text(json.dumps(r, ensure_ascii=False))
        _MEM[key] = r
        return r
