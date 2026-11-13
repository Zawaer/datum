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

_G = re.compile(r'<g\b[^>]*?class="(Ifc\w+)"[^>]*?data-guid="([^"]+)"[^>]*>(.*?)</g>', re.S)
_D = re.compile(r'\bd="([^"]+)"')
_PT = re.compile(r"(-?\d+(?:\.\d+)?(?:e-?\d+)?)[ ,](-?\d+(?:\.\d+)?(?:e-?\d+)?)")
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
            for sub in re.split(r"(?=M)", d):
                pts = [((float(x) - vx) / vw, (float(y) - vy) / vh) for x, y in _PT.findall(sub)]
                if pts:
                    polys.append(pts)
        if not polys:
            continue
        rec = out.setdefault(guid, {"cls": cls, "polys": []})
        rec["polys"] += polys
    for rec in out.values():
        xs = [x for poly in rec["polys"] for x, _ in poly]
        ys = [y for poly in rec["polys"] for _, y in poly]
        rec["bbox"] = [round(min(xs), 5), round(min(ys), 5), round(max(xs), 5), round(max(ys), 5)]
    return out


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
            poly = max(r["polys"], key=len)
            out.append({"kind": "polygon", "file": pdf_rel, "page": 0,
                        "points": [[round(x, 5), round(y, 5)] for x, y in poly],
                        "label": it["label"], "value": it.get("value")})
        else:
            out.append({"kind": "box", "file": pdf_rel, "page": 0, "bbox": r["bbox"],
                        "label": it["label"], "value": None})
    return out


def guids_on_sheet(pdf_abs: Path) -> set:
    return set(load_svg(str(svg_for(pdf_abs))))
