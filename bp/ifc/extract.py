"""Parse an IFC file once into plain-Python tables and cache them as a pickle.

`load_model(path)` returns a dict:
  meta:     schema, project/building/site names, header (application, description)
  storeys:  [{guid, name, long_name, elevation (m)}] sorted by elevation
  elements: [{guid, cls, name, long_name, obj_type, type_name, predef, storey, psets, qto, geo, mats}]

`qto` flattens the quantity sets (BaseQuantities / Qto_*) to {name: value} in SI units (m, m2, m3).
`geo` holds geometry-derived measures for the classes we measure (see GEO_CLASSES):
  footprint (m2, projected area on XY), volume (m3), side (m2, largest side area),
  len_x (m, extent along the element's local X axis = wall run), bbox (world xyz min/max, m).
"""
from __future__ import annotations

import hashlib
import multiprocessing
import os
import pickle
import re
import threading
import time
from pathlib import Path

import numpy as np

CACHE_DIR = Path(os.environ.get("BP_CACHE", "cache")) / "ifc"
CACHE_VERSION = 5

# classes whose geometry we evaluate (cost: a few seconds per model)
GEO_CLASSES = ["IfcSpace", "IfcWall", "IfcWallStandardCase", "IfcSlab", "IfcColumn", "IfcBeam",
               "IfcDoor", "IfcWindow", "IfcCovering", "IfcCurtainWall", "IfcRoof", "IfcStair", "IfcRailing",
               "IfcFooting", "IfcPlate", "IfcMember", "IfcRamp"]

SKIP_CLASSES = {"IfcOpeningElement", "IfcVirtualElement", "IfcDistributionPort", "IfcAnnotation", "IfcGrid",
                "IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcProject"}

MAX_PSET_PROPS = 60  # ArchiCAD dumps hundreds of GDL params per element; skip such sets
# ... but keep these keys even from oversized property sets
KEEP_KEYS = {"IsExternal", "LoadBearing", "FireRating", "Reference", "Status", "AcousticRating", "ThermalTransmittance"}


def _layers(e):
    out = []
    try:
        rep = getattr(e, "Representation", None)
        for r in (rep.Representations if rep else []):
            for la in getattr(r, "LayerAssignments", None) or []:
                if la.Name and la.Name not in out:
                    out.append(la.Name)
            for it in r.Items or []:
                for la in getattr(it, "LayerAssignments", None) or getattr(it, "LayerAssignment", None) or []:
                    if la.Name and la.Name not in out:
                        out.append(la.Name)
    except Exception:  # noqa: BLE001
        pass
    return out


def _cache_path(path: Path) -> Path:
    st = path.stat()
    h = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}|{CACHE_VERSION}".encode()).hexdigest()[:12]
    return CACHE_DIR / f"{path.stem}-{h}.pkl"


def _clean(v):
    """Make IFC attribute values picklable plain Python."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if hasattr(v, "wrappedValue"):
        return _clean(v.wrappedValue)
    return str(v)


def _storey_of(e, ue, cache):
    seen = []
    cur = e
    for _ in range(8):
        if cur is None:
            break
        if cur.id() in cache:
            r = cache[cur.id()]
            break
        if cur.is_a("IfcBuildingStorey"):
            r = cur
            break
        seen.append(cur.id())
        nxt = ue.get_container(cur)
        if nxt is None:
            nxt = ue.get_aggregate(cur)
        if nxt is None and cur.is_a("IfcElement"):
            # fillings (doors/windows) sit in an opening that voids a wall
            fills = getattr(cur, "FillsVoids", None)
            if fills:
                op = fills[0].RelatingOpeningElement
                vo = getattr(op, "VoidsElements", None)
                if vo:
                    nxt = vo[0].RelatingBuildingElement
        cur = nxt
    else:
        r = None
    if cur is None:
        r = None
    for i in seen:
        cache[i] = r
    return r


def _materials(e, ue):
    try:
        m = ue.get_material(e, should_skip_usage=True)
    except Exception:  # noqa: BLE001
        return []
    if m is None:
        return []
    out = []
    t = m.is_a()
    try:
        if t == "IfcMaterial":
            out.append((m.Name, None))
        elif t == "IfcMaterialLayerSet":
            for layer in m.MaterialLayers:
                out.append((layer.Material.Name if layer.Material else None, layer.LayerThickness))
        elif t == "IfcMaterialLayerSetUsage":
            for layer in m.ForLayerSet.MaterialLayers:
                out.append((layer.Material.Name if layer.Material else None, layer.LayerThickness))
        elif t == "IfcMaterialList":
            for x in m.Materials:
                out.append((x.Name, None))
        elif t == "IfcMaterialConstituentSet":
            for c in m.MaterialConstituents or []:
                out.append((c.Material.Name if c.Material else c.Name, None))
        elif t == "IfcMaterialProfileSet":
            for p in m.MaterialProfiles or []:
                out.append((p.Material.Name if p.Material else p.Name, None))
        elif t == "IfcMaterialProfileSetUsage":
            for p in m.ForProfileSet.MaterialProfiles or []:
                out.append((p.Material.Name if p.Material else p.Name, None))
    except Exception:  # noqa: BLE001
        pass
    return out


_QTO_SI = {"length": 1.0}


def _geometry(path: str, guids: set, unit_scale: float, threads: int):
    import ifcopenshell
    import ifcopenshell.geom as G
    import ifcopenshell.util.shape as us

    f = ifcopenshell.open(path)
    s = G.settings()
    try:
        s.set("use-world-coords", False)
    except Exception:  # noqa: BLE001
        pass
    elems = [e for c in GEO_CLASSES for e in f.by_type(c, include_subtypes=False) if e.GlobalId in guids]
    out = {}
    if not elems:
        return out
    it = G.iterator(s, f, threads, include=elems)
    if not it.initialize():
        return out
    while True:
        sh = it.get()
        try:
            g = sh.geometry
            v = np.asarray(g.verts, dtype=float).reshape(-1, 3)
            m = np.asarray(sh.transformation.matrix, dtype=float).reshape(4, 4).T  # column-major -> row
            if len(v):
                w = (np.c_[v, np.ones(len(v))] @ m.T)[:, :3]
                rec = {
                    "footprint": float(us.get_footprint_area(g)),
                    "volume": float(us.get_volume(g)),
                    "len_x": float(v[:, 0].max() - v[:, 0].min()),
                    "len_y": float(v[:, 1].max() - v[:, 1].min()),
                    "len_z": float(v[:, 2].max() - v[:, 2].min()),
                    "bbox": [w.min(0).tolist(), w.max(0).tolist()],
                    "xdir": m[:3, 0].tolist(),
                }
                try:
                    rec["side"] = float(us.get_side_area(g, axis="Y"))
                except Exception:  # noqa: BLE001
                    pass
                try:
                    rec["top"] = float(us.get_top_area(g))
                except Exception:  # noqa: BLE001
                    pass
                out[sh.guid] = rec
        except Exception:  # noqa: BLE001
            pass
        if not it.next():
            break
    return out


def extract(path: str, geometry: bool = True, threads: int = 4) -> dict:
    import ifcopenshell
    import ifcopenshell.util.element as ue
    import ifcopenshell.util.unit as uu

    t0 = time.time()
    f = ifcopenshell.open(path)
    try:
        ls = uu.calculate_unit_scale(f)  # file length unit -> metres
    except Exception:  # noqa: BLE001
        ls = 1.0

    try:
        as_ = uu.calculate_unit_scale(f, "AREAUNIT")
    except Exception:  # noqa: BLE001
        as_ = 1.0
    try:
        vs_ = uu.calculate_unit_scale(f, "VOLUMEUNIT")
    except Exception:  # noqa: BLE001
        vs_ = 1.0

    meta = {"schema": f.schema, "path": path}
    try:
        fn = f.header.file_name
        meta["header"] = {
            "name": fn.name, "time": fn.time_stamp, "author": list(fn.author or []),
            "organization": list(fn.organization or []), "preprocessor": fn.preprocessor_version,
            "application": fn.originating_system, "authorization": fn.authorization,
            "description": list(f.header.file_description.description or []),
        }
    except Exception:  # noqa: BLE001
        meta["header"] = {}
    for cls in ("IfcProject", "IfcSite", "IfcBuilding"):
        xs = f.by_type(cls)
        meta[cls] = [{"guid": x.GlobalId, "name": x.Name, "long_name": getattr(x, "LongName", None),
                      "description": x.Description, "obj_type": getattr(x, "ObjectType", None),
                      "psets": _psets(x, ue)}
                     for x in xs]
    try:
        apps = f.by_type("IfcApplication")
        meta["applications"] = [{"name": a.ApplicationFullName, "version": a.Version,
                                 "developer": a.ApplicationDeveloper.Name if a.ApplicationDeveloper else None}
                                for a in apps]
    except Exception:  # noqa: BLE001
        meta["applications"] = []
    meta["length_scale"] = ls

    storeys = []
    for s in f.by_type("IfcBuildingStorey"):
        storeys.append({"guid": s.GlobalId, "name": s.Name, "long_name": s.LongName,
                        "elevation": (s.Elevation or 0.0) * ls if s.Elevation is not None else None,
                        "psets": _psets(s, ue)})
    storeys.sort(key=lambda s: (s["elevation"] is None, s["elevation"] or 0))

    cache = {}
    elements = []
    for e in f.by_type("IfcProduct"):
        cls = e.is_a()
        if cls in SKIP_CLASSES:
            continue
        st = _storey_of(e, ue, cache)
        typ = ue.get_type(e)
        ps_all = ue.get_psets(e)
        qnames = set(ue.get_psets(e, qtos_only=True))
        if typ is not None:
            tps = ue.get_psets(typ)
        else:
            tps = {}
        psets, qto = {}, {}
        for name, props in ps_all.items():
            props = {k: v for k, v in props.items() if k != "id"}
            if name in qnames or _is_qto(name, props):
                for k, v in props.items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        qto.setdefault(k, _qto_si(k, v, ls, as_, vs_))
                        qto[f"{name}.{k}"] = _qto_si(k, v, ls, as_, vs_)
            elif len(props) <= MAX_PSET_PROPS:
                psets[name or "?"] = {k: _clean(v) for k, v in props.items()}
            else:
                keep = {k: _clean(v) for k, v in props.items() if k in KEEP_KEYS}
                if keep:
                    psets[name or "?"] = keep
        tpsets = {}
        for name, props in tps.items():
            props = {k: v for k, v in props.items() if k != "id"}
            if len(props) <= MAX_PSET_PROPS and not _is_qto(name, props):
                tpsets[name] = {k: _clean(v) for k, v in props.items()}
        attrs = {}
        for a in ("OverallWidth", "OverallHeight", "PredefinedType", "Tag", "CompositionType"):
            if hasattr(e, a):
                try:
                    v = getattr(e, a)
                except Exception:  # noqa: BLE001
                    v = None
                if v is not None:
                    attrs[a] = _clean(v) * ls if a.startswith("Overall") else _clean(v)
        sys_names = []
        try:
            for rel in getattr(e, "HasAssignments", []) or []:
                if rel.is_a("IfcRelAssignsToGroup") and rel.RelatingGroup.is_a("IfcSystem"):
                    sys_names.append(rel.RelatingGroup.Name)
        except Exception:  # noqa: BLE001
            pass
        agg = ue.get_aggregate(e)
        elements.append({
            "guid": e.GlobalId, "cls": cls, "name": e.Name, "long_name": getattr(e, "LongName", None),
            "description": e.Description, "obj_type": getattr(e, "ObjectType", None),
            "type_name": typ.Name if typ is not None else None,
            "type_cls": typ.is_a() if typ is not None else None,
            "predef": _clean(ue.get_predefined_type(e)),
            "storey": st.GlobalId if st is not None else None,
            "parent": agg.GlobalId if agg is not None else None,
            "parent_cls": agg.is_a() if agg is not None else None,
            "psets": psets, "tpsets": tpsets, "qto": qto, "attrs": attrs, "systems": sys_names,
            "mats": _materials(e, ue), "layers": _layers(e), "geo": None,
        })

    systems = []
    for sy in f.by_type("IfcSystem"):
        if sy.is_a("IfcZone"):
            continue
        members = []
        for rel in getattr(sy, "IsGroupedBy", []) or []:
            members += [o.GlobalId for o in rel.RelatedObjects]
        systems.append({"guid": sy.GlobalId, "cls": sy.is_a(), "name": sy.Name, "description": sy.Description,
                        "obj_type": getattr(sy, "ObjectType", None),
                        "predef": _clean(getattr(sy, "PredefinedType", None)), "members": members})
    zones = []
    for z in f.by_type("IfcZone"):
        members = []
        for rel in getattr(z, "IsGroupedBy", []) or []:
            members += [o.GlobalId for o in rel.RelatedObjects]
        zones.append({"guid": z.GlobalId, "name": z.Name, "long_name": getattr(z, "LongName", None),
                      "description": z.Description, "obj_type": z.ObjectType, "members": members})
    t1 = time.time()
    if geometry:
        gguids = {e["guid"] for e in elements if e["cls"] in GEO_CLASSES}
        del f
        geo = _geometry(path, gguids, ls, threads)
        for e in elements:
            g = geo.get(e["guid"])
            if g is not None:
                e["geo"] = g
    meta["timing"] = {"parse": round(t1 - t0, 2), "geometry": round(time.time() - t1, 2)}
    return {"meta": meta, "storeys": storeys, "elements": elements, "systems": systems, "zones": zones}


def _is_qto(name: str, props: dict) -> bool:
    name = name or ""
    return name.startswith("Qto_") or name in ("BaseQuantities", "ArchiCADQuantities") or "quantit" in name.lower()


def _qto_si(k: str, v: float, ls: float, as_: float, vs_: float) -> float:
    kl = k.lower()
    if "area" in kl:
        return v * as_
    if "volume" in kl:
        return v * vs_
    if any(w in kl for w in ("length", "width", "height", "depth", "perimeter", "thickness")):
        return v * ls
    return v


def _psets(x, ue):
    out = {}
    try:
        for name, props in ue.get_psets(x).items():
            props = {k: _clean(v) for k, v in props.items() if k != "id"}
            if len(props) <= MAX_PSET_PROPS:
                out[name] = props
    except Exception:  # noqa: BLE001
        pass
    return out


_MEM: dict = {}
_LOCKS: dict = {}
_LOCK = threading.Lock()


def load_model(path: str | Path, geometry: bool = True) -> dict:
    """Extract once per file (pickle cache under cache/ifc/), memoised in-process."""
    path = Path(path)
    key = str(path.resolve())
    if key in _MEM:
        return _MEM[key]
    with _LOCK:
        lk = _LOCKS.setdefault(key, threading.Lock())
    with lk:
        if key in _MEM:
            return _MEM[key]
        return _load(path, key, geometry)


def _load(path: Path, key: str, geometry: bool) -> dict:
    cp = _cache_path(path)
    if cp.exists():
        with open(cp, "rb") as fh:
            m = pickle.load(fh)
    else:
        m = extract(str(path), geometry=geometry)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = cp.with_suffix(f".tmp{os.getpid()}")
        with open(tmp, "wb") as fh:
            pickle.dump(m, fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, cp)
    _MEM[key] = m
    return m


if __name__ == "__main__":
    import sys

    for p in sys.argv[1:]:
        t = time.time()
        m = load_model(p)
        print(p, len(m["elements"]), m["meta"].get("timing"), f"{time.time() - t:.1f}s")
