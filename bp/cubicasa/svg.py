"""Parse a CubiCasa5k `model.svg` into labelled objects (training-label generation only).

The solver never calls this at inference: it only sees the PNG. We use it offline to turn the public
CubiCasa5k annotations into detector labels and to check how the question gold counts were defined.

Each object: {"cls": "Window Regular", "name": "MH" (room label, rooms only), "floor": i,
              "bbox": [x0, y0, x1, y1] in SVG units, "poly": [[x, y], ...]}.
"""
import re

import numpy as np
from lxml import etree
from svgelements import Path

_NUM = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _matrix(t: str | None) -> np.ndarray:
    m = np.eye(3)
    if not t:
        return m
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", t):
        a = [float(x) for x in _NUM.findall(args)]
        if name == "matrix" and len(a) == 6:
            n = np.array([[a[0], a[2], a[4]], [a[1], a[3], a[5]], [0, 0, 1]])
        elif name == "translate":
            n = np.array([[1, 0, a[0]], [0, 1, a[1] if len(a) > 1 else 0], [0, 0, 1]])
        elif name == "scale":
            n = np.diag([a[0], a[1] if len(a) > 1 else a[0], 1])
        elif name == "rotate":
            r = np.deg2rad(a[0])
            n = np.array([[np.cos(r), -np.sin(r), 0], [np.sin(r), np.cos(r), 0], [0, 0, 1]])
            if len(a) == 3:
                c = np.array([[1, 0, a[1]], [0, 1, a[2]], [0, 0, 1]])
                n = c @ n @ np.linalg.inv(c)
        else:
            continue
        m = m @ n
    return m


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _shape_points(el) -> np.ndarray | None:
    t = _local(el.tag)
    if t in ("polygon", "polyline"):
        a = [float(x) for x in _NUM.findall(el.get("points", ""))]
        return np.array(a[: len(a) // 2 * 2]).reshape(-1, 2) if len(a) >= 4 else None
    if t == "rect":
        x, y = float(el.get("x", 0)), float(el.get("y", 0))
        w, h = float(el.get("width", 0)), float(el.get("height", 0))
        return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])
    if t == "line":
        return np.array([[float(el.get("x1", 0)), float(el.get("y1", 0))],
                         [float(el.get("x2", 0)), float(el.get("y2", 0))]])
    if t == "path" and el.get("d"):
        try:
            bb = Path(el.get("d")).bbox()
        except Exception:  # noqa: BLE001
            return None
        if bb is None:
            return None
        x0, y0, x1, y1 = bb
        return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    if t in ("circle", "ellipse"):
        cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
        rx = float(el.get("r", el.get("rx", 0)))
        ry = float(el.get("r", el.get("ry", 0)))
        return np.array([[cx - rx, cy - ry], [cx + rx, cy + ry]])
    return None


def _apply(m, pts):
    p = np.c_[pts, np.ones(len(pts))] @ m.T
    return p[:, :2]


def _collect(el, m, skip_classes=("Dimension", "SpaceDimensionsLabel", "Name", "Direction",
                                    "SelectionControls", "TextLabel")):
    """All shape points under el (in global coords), skipping annotation helpers."""
    out = []
    for c in el:
        t = _local(c.tag)
        cls = c.get("class", "") or ""
        if cls.split(" ")[0] in skip_classes or "display: none" in (c.get("style") or ""):
            continue
        cm = m @ _matrix(c.get("transform"))
        if t == "g":
            out += _collect(c, cm, skip_classes)
        else:
            p = _shape_points(c)
            if p is not None:
                out.append(_apply(cm, p))
    return out


def _first_poly(el, m):
    for c in el:
        if _local(c.tag) == "polygon":
            return _apply(m @ _matrix(c.get("transform")), _shape_points(c))
    return None


def _boundary(el, m):
    for c in el:
        if _local(c.tag) == "g" and (c.get("class") or "") == "BoundaryPolygon":
            cm = m @ _matrix(c.get("transform"))
            for d in c:
                p = _shape_points(d)
                if p is not None:
                    return _apply(cm @ _matrix(d.get("transform")), p)
    return None


def _room_name(el):
    for t in el.iter():
        if _local(t.tag) == "g" and "NameLabel" in (t.get("class") or ""):
            return " ".join("".join(x.itertext()).strip() for x in t if _local(x.tag) == "text").strip()
    return ""


def parse(svg_path):
    root = etree.parse(str(svg_path), etree.XMLParser(huge_tree=True, recover=True)).getroot()
    W, H = float(root.get("width", 0) or 0), float(root.get("height", 0) or 0)
    objs = []
    floor_i = [-1]

    def walk(el, m):
        for c in el:
            if _local(c.tag) != "g":
                continue
            cls = (c.get("class") or "").strip()
            cm = m @ _matrix(c.get("transform"))
            if cls == "Floor":
                floor_i[0] += 1
                objs.append({"cls": "Floor", "floor": floor_i[0], "poly": None, "bbox": None, "el": c, "m": cm})
                walk(c, cm)
                continue
            head = cls.split(" ")[0]
            if head == "Space":
                p = _first_poly(c, cm)
                if p is not None:
                    objs.append({"cls": cls, "name": _room_name(c), "floor": floor_i[0], "poly": p})
                walk(c, cm)  # spaces may contain nothing else, but be safe
                continue
            if head in ("Window", "Door"):
                pts = _collect(c, cm)
                if pts:
                    allp = np.vstack(pts)
                    objs.append({"cls": cls, "floor": floor_i[0], "poly": _first_poly(c, cm),
                                 "pts": allp})
                continue
            if head == "FixedFurniture" or head == "Stairs" or head == "Railing":
                p = _boundary(c, cm)
                if p is None:
                    pts = _collect(c, cm)
                    p = np.vstack(pts) if pts else None
                if p is not None:
                    objs.append({"cls": cls, "floor": floor_i[0], "poly": p})
                continue
            walk(c, cm)

    walk(root, np.eye(3))
    for o in objs:
        if o["cls"] == "Floor":
            pts = _collect(o.pop("el"), o.pop("m"), skip_classes=("Dimension", "SpaceDimensionsLabel", "Name",
                                                                  "Direction", "SelectionControls", "TextLabel"))
            if pts:
                a = np.vstack(pts)
                o["bbox"] = [*a.min(0), *a.max(0)]
            continue
        a = o.get("pts") if o.get("pts") is not None else o["poly"]
        o["bbox"] = [float(a[:, 0].min()), float(a[:, 1].min()), float(a[:, 0].max()), float(a[:, 1].max())]
        o.pop("pts", None)
    return {"width": W, "height": H, "objects": objs}
