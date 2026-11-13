"""Tessellate an IFC model once (IfcOpenShell geometry iterator) into one compact mesh blob
the browser renders with three.js. Elements keep their GlobalId so evidence can light them up."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import multiprocessing
from pathlib import Path

import numpy as np

CACHE = Path("cache/mesh")
SKIP = {"IfcOpeningElement", "IfcVirtualElement", "IfcAnnotation", "IfcGrid"}


VERSION = 2


def storey_of(el):
    """The building storey an element (or a space / an aggregated part) belongs to, or None."""
    import ifcopenshell.util.element as ue

    for _ in range(8):
        if el is None or el.is_a("IfcBuildingStorey"):
            return el
        el = ue.get_container(el) or ue.get_aggregate(el)
    return None


def build_mesh(ifc_path: Path) -> dict:
    import ifcopenshell
    import ifcopenshell.geom

    f = ifcopenshell.open(str(ifc_path))
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    it = ifcopenshell.geom.iterator(s, f, min(6, multiprocessing.cpu_count()))
    pos, idx, elems = [], [], []
    nverts = 0
    storeys = {}  # storey id -> index into the storey list
    if it.initialize():
        while True:
            shape = it.get()
            el = f.by_id(shape.id)
            t = el.is_a()
            if t not in SKIP:
                g = shape.geometry
                v = np.asarray(g.verts, dtype=np.float32).reshape(-1, 3)
                fc = np.asarray(g.faces, dtype=np.uint32).reshape(-1)
                if len(v) and len(fc):
                    st = storey_of(el)
                    if st is not None and st.id() not in storeys:
                        storeys[st.id()] = (len(storeys), st)
                    elems.append({"guid": el.GlobalId, "type": t, "name": getattr(el, "Name", None) or "",
                                  "start": int(sum(len(i) for i in idx)),
                                  "count": int(len(fc)),
                                  "storey": storeys[st.id()][0] if st is not None else -1,
                                  "zmin": round(float(v[:, 2].min()), 3), "zmax": round(float(v[:, 2].max()), 3)})
                    pos.append(v)
                    idx.append(fc + nverts)
                    nverts += len(v)
            if not it.next():
                break
    P = np.concatenate(pos) if pos else np.zeros((0, 3), np.float32)
    I = np.concatenate(idx) if idx else np.zeros(0, np.uint32)
    # IFC is Z-up; three.js is Y-up
    P = P[:, [0, 2, 1]] * np.array([1, 1, -1], np.float32)
    # storey floor level: its placement in world coordinates (what the geometry uses); fall back to the low
    # end of its elements' bottoms
    import ifcopenshell.util.placement as up
    import ifcopenshell.util.unit as uu

    scale = uu.calculate_unit_scale(f)
    st_list = []
    for i, st in sorted(storeys.values(), key=lambda x: x[0]):
        zs = sorted(e["zmin"] for e in elems if e["storey"] == i)
        try:
            z = float(up.get_local_placement(st.ObjectPlacement)[2][3]) * scale
        except Exception:  # noqa: BLE001
            z = zs[len(zs) // 10] if zs else 0.0
        st_list.append({"name": st.Name or f"storey {i + 1}", "z": round(z, 3), "n": len(zs)})
    order = sorted(range(len(st_list)), key=lambda i: st_list[i]["z"])
    remap = {old: new for new, old in enumerate(order)}
    for e in elems:
        e["storey"] = remap.get(e["storey"], -1)
    st_list = [st_list[i] for i in order]
    return {"elements": elems, "storeys": st_list,
            "positions": base64.b64encode(P.astype(np.float32).tobytes()).decode(),
            "indices": base64.b64encode(I.astype(np.uint32).tobytes()).decode()}


def mesh_bytes(ifc_path: Path) -> bytes:
    """gzipped JSON, cached on disk by file content hash."""
    CACHE.mkdir(parents=True, exist_ok=True)
    st = ifc_path.stat()
    key = hashlib.sha1(f"v{VERSION}|{ifc_path}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:16]
    out = CACHE / f"{ifc_path.stem}-{key}.json.gz"
    if not out.exists():
        data = json.dumps(build_mesh(ifc_path)).encode()
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(data, 5))
        tmp.rename(out)
    return out.read_bytes()
