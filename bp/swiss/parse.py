"""Parse a Swiss Dwellings floor (DXF twin of the PDF) into rooms, units and symbols.

The DXF puts every element class on its own layer (ROOM_OUTLINE, ROOM_TEXT, UNIT_OUTLINE,
DOOR, WINDOW, FIXTURE, WALL), in metres. So the answers are exact geometry, no vision needed.
Coordinates are also mapped onto the PDF page (normalised 0..1, origin top-left) so the UI
can draw evidence over the drawing the user actually asked about.
"""
from __future__ import annotations

import functools
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
import numpy as np
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

NUM_RE = re.compile(r"^[A-Z]?\d+(?:\.\d+)+$|^[A-Z]\d+$")
AREA_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*m²$")
UNIT_RE = re.compile(r"^(?:Whg\.|App\.|Wohnung|Appartement|Appartamento)\s*([A-Z]{1,2}\d*)$")

OUTDOOR = ("balkon", "balcon", "loggia", "terrass", "sitzplatz", "veranda", "aussen", "extérieur", "esterno",
           "dachterrasse", "patio", "garten", "jardin", "giardino")
SHAFT_VOID = ("schacht", "luftraum", "gaine", "vide", "cavedio", "vuoto", "void", "shaft")


@dataclass
class Room:
    poly: Polygon
    name: str | None = None
    number: str | None = None
    area_text: float | None = None
    unit: str | None = None

    @property
    def area(self) -> float:
        return self.area_text if self.area_text is not None else round(self.poly.area, 2)

    has_sanitary: bool = False

    @property
    def counts_as_room(self) -> bool:
        return bool(self.name) or self.has_sanitary

    @property
    def outdoor(self) -> bool:
        n = (self.name or "").lower()
        return any(k in n for k in OUTDOOR)

    @property
    def shaft_void(self) -> bool:
        n = (self.name or "").lower()
        return any(k in n for k in SHAFT_VOID)


@dataclass
class Symbol:
    kind: str
    geom: object  # shapely geometry (DXF coords)


@dataclass
class Floor:
    rooms: list[Room] = field(default_factory=list)
    units: dict[str, Polygon] = field(default_factory=dict)
    symbols: list[Symbol] = field(default_factory=list)
    texts: list[tuple[str, float, float]] = field(default_factory=list)
    to_page: tuple | None = None  # (ax, bx, ay, by): u = ax*x+bx, v = ay*y+by (normalised page coords)

    def norm_bbox(self, g, pad=0.0):
        x0, y0, x1, y1 = g.bounds
        ax, bx, ay, by = self.to_page
        u0, u1 = sorted((ax * (x0 - pad) + bx, ax * (x1 + pad) + bx))
        v0, v1 = sorted((ay * (y0 - pad) + by, ay * (y1 + pad) + by))
        return [round(u0, 5), round(v0, 5), round(u1, 5), round(v1, 5)]

    def norm_poly(self, poly):
        ax, bx, ay, by = self.to_page
        geom = poly if poly.geom_type == "Polygon" else max(poly.geoms, key=lambda p: p.area)
        return [[round(ax * x + bx, 5), round(ay * y + by, 5)] for x, y in geom.exterior.coords]


def _poly(e):
    pts = [p[:2] for p in e.get_points()]
    if len(pts) < 3:
        return None
    p = Polygon(pts)
    return p if p.is_valid else p.buffer(0)


def _geom(e):
    t = e.dxftype()
    if t == "CIRCLE":
        c = e.dxf.center
        return Point(c[0], c[1]).buffer(e.dxf.radius, 16)
    if t == "ARC":
        c, r = e.dxf.center, e.dxf.radius
        a0, a1 = math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)
        if a1 < a0:
            a1 += 2 * math.pi
        angs = np.linspace(a0, a1, 12)
        pts = [(c[0], c[1])] + [(c[0] + r * math.cos(a), c[1] + r * math.sin(a)) for a in angs]
        return Polygon(pts).buffer(0)
    if t == "LWPOLYLINE":
        pts = [p[:2] for p in e.get_points()]
        if len(pts) >= 3 and e.closed:
            return Polygon(pts).buffer(0)
        from shapely.geometry import LineString
        return LineString(pts) if len(pts) >= 2 else Point(pts[0])
    if t == "LINE":
        from shapely.geometry import LineString
        return LineString([e.dxf.start[:2], e.dxf.end[:2]])
    return None


def _classify_fixture(members) -> str:
    """members: list of (dxftype, n_points, radius, geom). Signatures found on dev drawings."""
    n_burner = sum(1 for t, n, r, g in members if t == "CIRCLE" and abs(r - 0.08) < 0.02)
    small_circ = sum(1 for t, n, r, g in members if t == "CIRCLE" and r < 0.05)
    big_curves = [n for t, n, r, g in members if t == "LWPOLYLINE" and n >= 20]
    lines = sum(1 for t, n, r, g in members if t == "LWPOLYLINE" and n == 2)
    drain = sum(1 for t, n, r, g in members if t == "CIRCLE" and 0.038 <= r <= 0.055)
    tray = sum(1 for t, n, r, g in members if t == "LWPOLYLINE" and n == 5)
    if n_burner >= 2:
        return "stove"
    if drain and tray:
        return "shower"  # square tray (5-vertex outline) + drain circle r~0.045
    if big_curves:
        nmax = max(big_curves)
        if nmax >= 60:
            return "bathtub"
        if small_circ:
            return "washbasin"
        if lines:
            return "toilet"
        return "curve?"
    if lines >= 6:
        return "stairs"
    return "other"


def _fixture_groups(entities):
    items = []
    for e in entities:
        g = _geom(e)
        if g is None:
            continue
        n = len(e.get_points()) if e.dxftype() == "LWPOLYLINE" else 0
        r = e.dxf.radius if e.dxftype() == "CIRCLE" else 0.0
        items.append((e.dxftype(), n, r, g))
    if not items:
        return []
    u = unary_union([it[3].buffer(0.01) for it in items])
    parts = list(u.geoms) if hasattr(u, "geoms") else [u]
    groups = []
    for p in parts:
        mem = [it for it in items if p.intersects(it[3].representative_point())]
        groups.append((p, mem))
    return groups


def _components(geoms, tol):
    if not geoms:
        return []
    u = unary_union([g.buffer(tol) for g in geoms])
    return list(u.geoms) if hasattr(u, "geoms") else [u]


def _fit_page_transform(dxf_texts, pdf_path):
    """Fit u = ax*x + bx, v = ay*y + by from texts present in both the DXF and the PDF."""
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        page = doc[0]
        W, H = page.rect.width, page.rect.height
        words = page.get_text("words")
    pdf_pos: dict[str, list] = {}
    for x0, y0, x1, y1, w, *_ in words:
        pdf_pos.setdefault(w, []).append((x0, y0, x1, y1))
    xs, us, ys, vs = [], [], [], []
    for t, x, y in dxf_texts:
        if NUM_RE.match(t) and len(pdf_pos.get(t, [])) == 1:
            x0, y0, x1, y1 = pdf_pos[t][0]
            # DXF insert is the text's baseline-left or middle: fit against both left and bottom
            xs.append(x); us.append(((x0 + x1) / 2) / W)
            ys.append(y); vs.append(((y0 + y1) / 2) / H)
    if len(xs) < 3:
        return None
    ax, bx = np.polyfit(xs, us, 1)
    ay, by = np.polyfit(ys, vs, 1)
    return float(ax), float(bx), float(ay), float(by)


@functools.lru_cache(maxsize=256)
def parse_floor(dxf_path: str, pdf_path: str | None = None) -> Floor:
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    fl = Floor()

    texts = [(e.dxf.text.strip(), e.dxf.insert[0], e.dxf.insert[1], e.dxf.height)
             for e in msp.query('TEXT[layer=="ROOM_TEXT"]')]
    fl.texts = [(t, x, y) for t, x, y, h in texts]

    # ---- room label blocks: number anchor, name directly above, area directly below (same x)
    labels = []
    for t, x, y, h in texts:
        if not NUM_RE.match(t):
            continue
        same_col = [(t2, y2) for t2, x2, y2, h2 in texts if abs(x2 - x) < 1e-3 and (t2, y2) != (t, y)]
        above = sorted([(y2 - y, t2) for t2, y2 in same_col if 0 < y2 - y < 3 * h])
        below = sorted([(y - y2, t2) for t2, y2 in same_col if 0 < y - y2 < 3 * h])
        name = next((t2 for d, t2 in above if not NUM_RE.match(t2) and not AREA_RE.match(t2)
                     and not UNIT_RE.match(t2)), None)
        area = next((float(AREA_RE.match(t2).group(1)) for d, t2 in below if AREA_RE.match(t2)), None)
        labels.append((t, name, area, Point(x, y)))

    polys = [p for p in (_poly(e) for e in msp.query('LWPOLYLINE[layer=="ROOM_OUTLINE"]')) if p is not None
             and p.area > 0.05]
    used = set()
    for num, name, area, pt in labels:
        cands = [i for i, p in enumerate(polys) if p.contains(pt)]
        if not cands:
            d = [(p.distance(pt), i) for i, p in enumerate(polys)]
            d = [x for x in d if x[0] < 1.0]
            cands = [min(d)[1]] if d else []
        if cands:
            i = min(cands, key=lambda i: polys[i].area)  # innermost
            used.add(i)
            fl.rooms.append(Room(polys[i], name, num, area))
        else:
            fl.rooms.append(Room(Point(pt).buffer(0.3), name, num, area))
    for i, p in enumerate(polys):
        if i not in used:
            fl.rooms.append(Room(p))  # unlabelled region (shaft, void, ...)

    # ---- units (apartments)
    unit_polys = [p for p in (_poly(e) for e in msp.query('LWPOLYLINE[layer=="UNIT_OUTLINE"]')) if p is not None]
    unit_labels = [(UNIT_RE.match(t).group(1), Point(x, y)) for t, x, y, h in texts if UNIT_RE.match(t)]
    for letter, pt in unit_labels:
        cands = [p for p in unit_polys if p.buffer(0.05).contains(pt)]
        if cands:
            fl.units[letter] = min(cands, key=lambda p: p.area)
    for r in fl.rooms:
        for letter, up in fl.units.items():
            if r.poly.intersection(up).area > 0.5 * r.poly.area:
                r.unit = letter
    fl.n_unit_outlines = len(unit_polys)

    # ---- doors: every door (single or double leaf, swing or sliding) has exactly one 5-vertex
    # frame polyline on layer DOOR; arcs and leaf lines are decoration. Verified on dev: matches gold.
    for e in msp.query('LWPOLYLINE[layer=="DOOR"]'):
        pts = [p[:2] for p in e.get_points()]
        if len(pts) == 5:
            fl.symbols.append(Symbol("door", Polygon(pts).buffer(0) if Polygon(pts).area > 1e-4 else
                                     unary_union([_geom(e)]).envelope))

    # ---- windows: one closed 4-vertex rectangle per window (+ glazing lines)
    for e in msp.query('LWPOLYLINE[layer=="WINDOW"]'):
        pts = [p[:2] for p in e.get_points()]
        if len(pts) == 4 and e.closed:
            fl.symbols.append(Symbol("window", Polygon(pts)))

    # ---- fixtures
    for comp, mem in _fixture_groups(list(msp.query('*[layer=="FIXTURE"]'))):
        fl.symbols.append(Symbol(_classify_fixture(mem), comp))

    # numbered rooms printed without a name: bathrooms/WCs drawn with fixtures count as rooms,
    # empty ones are shafts. Verified against dev apartment totals.
    sanitary = [s.geom for s in fl.symbols if s.kind in ("toilet", "washbasin", "bathtub", "shower")]
    for r in fl.rooms:
        if r.number and not r.name:
            r.has_sanitary = any(r.poly.intersects(g.centroid) for g in sanitary)

    if pdf_path and Path(pdf_path).exists():
        fl.to_page = _fit_page_transform(fl.texts, pdf_path)
    return fl
