"""2D evidence for plan PDFs rendered from IFC.

The dataset's `<model>_plan-<level>.pdf` sheets come with an `.svg` twin written by IfcConvert, where every
element is a `<g class="IfcWall" data-guid="..."><path d="M x,y L ..."/></g>`. The PDF page is the SVG
viewBox at the same scale, so normalising the SVG coordinates by the viewBox gives page-relative boxes and
polygons for any GlobalId we want to show.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

_G = re.compile(r'<g\b[^>]*?class="(?:[^"]*\s)?(Ifc\w+)"[^>]*?data-guid="([^"]+)"[^>]*>(.*?)</g>', re.S)
_D = re.compile(r'\bd="([^"]+)"')
_TOK = re.compile(r"[MLHVCSQTAZmlhvcsqtaz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")
_NARGS = {"M": 2, "L": 2, "T": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "A": 7, "Z": 0}


def parse_path(d: str) -> list[list[tuple[float, float]]]:
    """Absolute/relative SVG path -> list of subpaths (vertex lists; arcs/curves contribute end points)."""
    toks = _TOK.findall(d)
    subs, cur = [], []
    x = y = 0.0
    cmd = None
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if cur:
                    subs.append(cur)
                    cur = []
                continue
        if cmd is None:
            i += 1
            continue
        n = _NARGS[cmd.upper()]
        args = toks[i:i + n]
        if len(args) < n or any(a.isalpha() for a in args):
            break
        a = [float(v) for v in args]
        i += n
        rel = cmd.islower()
        C = cmd.upper()
        if C == "H":
            x = a[0] + (x if rel else 0)
        elif C == "V":
            y = a[0] + (y if rel else 0)
        else:
            nx, ny = a[-2], a[-1]
            x, y = (x + nx, y + ny) if rel else (nx, ny)
        if C == "M":
            if cur:
                subs.append(cur)
            cur = [(x, y)]
            cmd = "l" if rel else "L"
        else:
            cur.append((x, y))
    if cur:
        subs.append(cur)
    return subs


_VB = re.compile(r'viewBox="([-\d.\s]+)"')


@functools.lru_cache(maxsize=32)
def load_svg(svg_path: str) -> dict:
    """guid -> {"cls", "bbox": [x0,y0,x1,y1] normalised, "polys": [[[x,y],...], ...]}"""
    p = Path(svg_path)
    if not p.exists():
        return {}
    s = p.read_text(errors="replace")
    m = _VB.search(s)
    if not m:
        return {}
    vx, vy, vw, vh = (float(v) for v in m.group(1).split())
    out = {}
    for cls, guid, body in _G.findall(s):
        polys = []
        for d in _D.findall(body):
            for sub in parse_path(d):
                polys.append([((x - vx) / vw, (y - vy) / vh) for x, y in sub])
        if not polys:
            continue
        rec = out.setdefault(guid, {"cls": cls, "polys": []})
        rec["polys"] += polys
    for rec in out.values():
        xs = [x for poly in rec["polys"] for x, _ in poly]
        ys = [y for poly in rec["polys"] for _, y in poly]
        rec["bbox"] = [round(min(xs), 5), round(min(ys), 5), round(max(xs), 5), round(max(ys), 5)]
    return out


def _area(poly) -> float:
    """Shoelace area of a ring (0 for open paths / lines)."""
    if len(poly) < 3:
        return 0.0
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]))) / 2


def _rings(polys):
    """-> (outer ring, holes): the largest ring, and the other closed rings lying inside its bounding box."""
    rings = [q for q in polys if len(q) >= 3]
    if not rings:
        return polys[0], []
    outer = max(rings, key=_area)
    x0, x1 = min(x for x, _ in outer), max(x for x, _ in outer)
    y0, y1 = min(y for _, y in outer), max(y for _, y in outer)
    holes = [q for q in rings if q is not outer and _area(q) > 1e-7
             and all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in q)]
    return outer, holes


def _r5(ring):
    return [[round(x, 5), round(y, 5)] for x, y in ring]


def svg_for(pdf_path: Path) -> Path:
    return pdf_path.with_suffix(".svg")


def evidence_2d(pdf_rel: str, pdf_abs: Path, items: list[dict], polygon: bool = False) -> list[dict]:
    """items: [{guid, label, value}] -> box/polygon evidence on the PDF for guids drawn on the sheet."""
    shapes = load_svg(str(svg_for(pdf_abs)))
    out = []
    for it in items:
        r = shapes.get(it["guid"])
        if r is None:
            continue
        if polygon:
            poly, holes = _rings(r["polys"])
            out.append({"kind": "polygon", "file": pdf_rel, "page": 0,
                        "points": _r5(poly), "holes": [_r5(h) for h in holes],
                        "label": it["label"], "value": it.get("value")})
        else:
            # counted elements are drawn with their real outline from the SVG twin (an L-shaped room or a wall run
            # is not its bounding rectangle); the bbox stays for zooming and badge placement
            n = sum(1 for o in out if o.get("counted")) + 1
            poly, holes = _rings(r["polys"])
            out.append({"kind": "polygon", "file": pdf_rel, "page": 0, "counted": True, "bbox": r["bbox"],
                        "points": _r5(poly), "holes": [_r5(h) for h in holes],
                        "label": f"{n}. {it['label']}", "value": None})
    return out


def guids_on_sheet(pdf_abs: Path) -> set:
    return set(load_svg(str(svg_for(pdf_abs))))
