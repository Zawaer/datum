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


def build_mesh(ifc_path: Path) -> dict:
    import ifcopenshell
    import ifcopenshell.geom

    f = ifcopenshell.open(str(ifc_path))
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    it = ifcopenshell.geom.iterator(s, f, min(6, multiprocessing.cpu_count()))
    pos, idx, elems = [], [], []
    nverts = 0
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
                    elems.append({"guid": el.GlobalId, "type": t, "name": getattr(el, "Name", None) or "",
                                  "start": int(sum(len(i) for i in idx)),
                                  "count": int(len(fc))})
                    pos.append(v)
                    idx.append(fc + nverts)
                    nverts += len(v)
            if not it.next():
                break
    P = np.concatenate(pos) if pos else np.zeros((0, 3), np.float32)
    I = np.concatenate(idx) if idx else np.zeros(0, np.uint32)
    # IFC is Z-up; three.js is Y-up
    P = P[:, [0, 2, 1]] * np.array([1, 1, -1], np.float32)
    return {"elements": elems,
            "positions": base64.b64encode(P.astype(np.float32).tobytes()).decode(),
            "indices": base64.b64encode(I.astype(np.uint32).tobytes()).decode()}


def mesh_bytes(ifc_path: Path) -> bytes:
    """gzipped JSON, cached on disk by file content hash."""
    CACHE.mkdir(parents=True, exist_ok=True)
    st = ifc_path.stat()
    key = hashlib.sha1(f"{ifc_path}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:16]
    out = CACHE / f"{ifc_path.stem}-{key}.json.gz"
    if not out.exists():
        data = json.dumps(build_mesh(ifc_path)).encode()
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(data, 5))
        tmp.rename(out)
    return out.read_bytes()
