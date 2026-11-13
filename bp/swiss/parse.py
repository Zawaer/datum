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
# room fill greys on the PDF (stroke 0.54): 1.0 apartment room, 0.953 circulation / common / non-residential,
# 0.894 outdoor (balcony, loggia, terrace, garden; also unnamed ones), 0.812 rare (stairs / voids)
FILL_OUTDOOR = 0.894
FILL_COMMON = 0.953
SHAFT_VOID = ("schacht", "luftraum", "gaine", "vide", "cavedio", "vuoto", "void", "shaft")


@dataclass
class Room:
    poly: Polygon
    name: str | None = None
    number: str | None = None
    area_text: float | None = None
    unit: str | None = None
    label_pos: tuple | None = None  # DXF position of the room number (text centre)
    area_pos: tuple | None = None  # DXF position of the printed "x.xx m²" (if any)
    assigned: str = "contained"  # how the label found its outline: contained / nearest / shared / none
    fill: float | None = None  # grey of the room's fill on the PDF (1.0 white = room; see ROOM_FILLS)

    holes: list = field(default_factory=list)  # unlabelled outlines (shafts, columns) lying inside this room

    @property
    def area(self) -> float:
        """Printed area if the label has one (already net), else the outline minus the unlabelled
        outlines inside it (lift shaft in a stair hall, columns), which the answers exclude."""
        if self.area_text is not None:
            return self.area_text
        return round(self.poly.area - sum(h.area for h in self.holes), 2)

    has_sanitary: bool = False

    @property
    def counts_as_room(self) -> bool:
        return bool(self.name) or self.has_sanitary

    @property
    def outdoor(self) -> bool:
        n = (self.name or "").lower()
        return any(k in n for k in OUTDOOR) or self.fill == FILL_OUTDOOR

    @property
    def shaft_void(self) -> bool:
        n = (self.name or "").lower()
        return any(k in n for k in SHAFT_VOID)


@dataclass
class Symbol:
    kind: str
    geom: object  # shapely geometry (DXF coords)
    sure: bool = True  # False: signature seen rarely / ambiguous grouping -> lower the answer's confidence
    odd: bool = False  # "other" group with curves or circles: an unrecognised fixture rather than furniture


@dataclass
class Floor:
    rooms: list[Room] = field(default_factory=list)
    units: dict[str, Polygon] = field(default_factory=dict)
    symbols: list[Symbol] = field(default_factory=list)
    texts: list[tuple[str, float, float]] = field(default_factory=list)
    unit_labels: list[str] = field(default_factory=list)
    unit_by_distance: set = field(default_factory=set)
    unit_merged: set = field(default_factory=set)  # apartments made of several outlines
    n_unit_outlines: int = 0
    fit_rms: float | None = None  # rms residual of the DXF->page fit, in page units (0..1)
    pdf_words: list = field(default_factory=list)  # numeric words on the PDF: (text, u0, v0, u1, v1)
    to_page: tuple | None = None  # (ax, bx, ay, by): u = ax*x+bx, v = ay*y+by (normalised page coords)

    def norm_bbox(self, g, pad=0.0):
        x0, y0, x1, y1 = g.bounds
        ax, bx, ay, by = self.to_page
        u0, u1 = sorted((ax * (x0 - pad) + bx, ax * (x1 + pad) + bx))
        v0, v1 = sorted((ay * (y0 - pad) + by, ay * (y1 + pad) + by))
        return [round(u0, 5), round(v0, 5), round(u1, 5), round(v1, 5)]

    def norm_pt(self, x, y):
        ax, bx, ay, by = self.to_page
        return ax * x + bx, ay * y + by

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


def _classify_fixture(members) -> tuple[str, bool]:
    """members: list of (dxftype, n_points, radius, geom) inside one fixture outline.

    Returns (kind, sure). Signatures surveyed over every dev drawing:
      4 (2..8) circles r 0.08 -> stove;  5-vertex tray + drain r~0.045 -> shower;
      curve >= 60 pts -> bathtub;  48-pt curve + small circle -> washbasin;  48-pt curve (+ line) -> WC;
      only straight lines -> stairs / kitchen / furniture."""
    circles = [r for t, n, r, g in members if t == "CIRCLE"]
    n_burner = sum(1 for r in circles if abs(r - 0.08) < 0.02)
    big_curves = [n for t, n, r, g in members if t == "LWPOLYLINE" and n >= 20]
    lines = sum(1 for t, n, r, g in members if t == "LWPOLYLINE" and n == 2)
    drain = sum(1 for r in circles if 0.038 <= r <= 0.055)
    tray = sum(1 for t, n, r, g in members if t == "LWPOLYLINE" and n == 5)
    if n_burner >= 2:
        return "stove", True
    if drain and tray:
        return "shower", True
    if big_curves:
        nmax = max(big_curves)
        if nmax >= 60:
            return "bathtub", len(big_curves) == 1
        basin = [r for r in circles if r < 0.07 or 0.09 < r < 0.15]
        if basin:
            # usual drain r 0.013..0.041; larger (0.05, 0.1: double basin) seen rarely
            return "washbasin", len(big_curves) == 1 and max(basin) < 0.045
        return "toilet", lines >= 1 and len(big_curves) == 1
    if not lines and not tray and len(circles) == 1 and 0.02 <= circles[0] <= 0.03:
        # a lone tub drain in its own outline next to a bathtub (seen on dev: gold counts it as a tub)
        return "bathtub", False
    if lines >= 6:
        return "stairs", True
    return "other", True


def _fixture_groups(entities):
    """Group FIXTURE primitives into one group per fixture.

    Every fixture symbol is drawn inside its own closed 4-vertex outline rectangle (verified on all dev
    drawings: no primitive falls outside one), so each primitive goes to the smallest rectangle containing
    it. Touching fixtures (WC next to washbasin next to bathtub) therefore stay separate. Primitives outside
    every rectangle fall back to connected components."""
    items = []
    for e in entities:
        g = _geom(e)
        if g is None:
            continue
        t = e.dxftype()
        n = len(e.get_points()) if t == "LWPOLYLINE" else 0
        r = e.dxf.radius if t == "CIRCLE" else 0.0
        closed = bool(e.closed) if t == "LWPOLYLINE" else False
        items.append((t, n, r, g, closed))
    if not items:
        return []
    rects = [i for i, it in enumerate(items) if it[0] == "LWPOLYLINE" and it[1] == 4 and it[4] and it[3].area > 1e-4]
    rset = set(rects)
    rbuf = {i: items[i][3].buffer(0.01) for i in rects}
    members = {i: [] for i in rects}
    loose = []

    def sig(it):
        return (it[0], min(it[1], 20), round(it[2], 2) if it[2] >= 0.07 else 0)

    # big curves first so they claim their own rectangle; when outlines overlap (WC tucked into a
    # bathtub's rectangle, duplicated outlines) a primitive prefers a rectangle that holds all of it,
    # then one without a primitive of the same kind yet, then the smallest.
    order = sorted((j for j in range(len(items)) if j not in rset), key=lambda j: -items[j][1])
    for j in order:
        it = items[j]
        g = it[3]
        pt = g.interpolate(0.5, normalized=True) if g.geom_type == "LineString" else g.representative_point()
        c = [i for i in rects if rbuf[i].contains(g)] or [i for i in rects if rbuf[i].contains(pt)]
        if c:
            s0 = sig(it)
            best = min(c, key=lambda i: (sum(1 for k in members[i] if sig(items[k]) == s0), items[i][3].area))
            members[best].append(j)
        else:
            loose.append(j)
    groups = [(items[i][3], [items[i][:4]] + [items[j][:4] for j in members[i]]) for i in rects]
    if loose:
        u = unary_union([items[j][3].buffer(0.01) for j in loose])
        for p in (list(u.geoms) if hasattr(u, "geoms") else [u]):
            groups.append((p, [items[j][:4] for j in loose if p.intersects(items[j][3].representative_point())]))
    return groups


def _components(geoms, tol):
    if not geoms:
        return []
    u = unary_union([g.buffer(tol) for g in geoms])
    return list(u.geoms) if hasattr(u, "geoms") else [u]


def _pdf_room_fills(page):
    """Room fills on the PDF page: closed paths stroked mid-grey (0.54) whose fill grey encodes the area
    type (white = room; grey tones = shafts, voids, outdoor, ...). Returns [(Polygon in normalised page
    coords, fill grey)]."""
    W, H = page.rect.width, page.rect.height
    out = []
    for d in page.get_drawings():
        col, fill = d.get("color"), d.get("fill")
        if d.get("type") != "fs" or not col or not fill or abs(col[0] - 0.541) > 0.01:
            continue
        pts = []
        for it in d["items"]:
            if it[0] == "l":
                pts += [it[1], it[2]]
            elif it[0] == "re":
                r = it[1]
                pts += [r.tl, r.tr, r.br, r.bl]
            elif it[0] == "qu":
                q = it[1]
                pts += [q.ul, q.ur, q.lr, q.ll]
            elif it[0] == "c":
                pts += [it[1], it[4]]
        if len(pts) < 3:
            continue
        poly = Polygon([(p.x / W, p.y / H) for p in pts])
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.area > 0:
            out.append((poly, round(float(sum(fill)) / 3, 3)))
    return out


def _fit_page_transform(dxf_texts, page):
    """Fit u = ax*x + bx, v = ay*y + by from texts present in both the DXF and the PDF."""
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
        return None, None
    xs, us, ys, vs = map(np.asarray, (xs, us, ys, vs))
    ax, bx = np.polyfit(xs, us, 1)
    ay, by = np.polyfit(ys, vs, 1)
    # one refit without gross outliers (a number reused as e.g. a dimension elsewhere)
    res = np.hypot(ax * xs + bx - us, ay * ys + by - vs)
    keep = res < max(3 * np.median(res), 0.002)
    if keep.sum() >= 3 and not keep.all():
        ax, bx = np.polyfit(xs[keep], us[keep], 1)
        ay, by = np.polyfit(ys[keep], vs[keep], 1)
        res = np.hypot(ax * xs + bx - us, ay * ys + by - vs)[keep]
    return (float(ax), float(bx), float(ay), float(by)), float(np.sqrt(np.mean(res ** 2)))


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
        area_pos = next(((x, y - d) for d, t2 in below if AREA_RE.match(t2)), None)
        labels.append((t, name, area, Point(x, y), area_pos))

    polys = [p for p in (_poly(e) for e in msp.query('LWPOLYLINE[layer=="ROOM_OUTLINE"]')) if p is not None
             and p.area > 1e-4]
    used = {}
    for num, name, area, pt, area_pos in labels:
        # smallest outline holding the label; slivers (door reveals, 0.002 m²) whose edge the label sits on
        # count too, otherwise their number would take the big neighbouring room twice
        cands = [i for i, p in enumerate(polys) if p.contains(pt) or p.distance(pt) < 0.02]
        how = "contained"
        if not cands:
            d = [(p.distance(pt), i) for i, p in enumerate(polys)]
            d = [x for x in d if x[0] < 1.0]
            cands = [min(d)[1]] if d else []
            how = "nearest"
        if cands:
            i = min(cands, key=lambda i: polys[i].area)  # innermost
            used.setdefault(i, []).append(len(fl.rooms))
            fl.rooms.append(Room(polys[i], name, num, area, assigned=how, label_pos=(pt.x, pt.y), area_pos=area_pos))
        else:
            fl.rooms.append(Room(Point(pt).buffer(0.3), name, num, area, assigned="none", label_pos=(pt.x, pt.y),
                                 area_pos=area_pos))
    for i, idx in used.items():
        if len(idx) > 1:
            for k in idx:
                fl.rooms[k].assigned = "shared"
    free = [p for i, p in enumerate(polys) if i not in used]
    for p in free:
        fl.rooms.append(Room(p))  # unlabelled region (shaft, void, ...)
    # unlabelled outlines inside a labelled room (lift shaft in a stair hall, a column, a duct) are holes:
    # outermost ones only (a lift drawn inside the shaft outline is not subtracted twice)
    for r in fl.rooms:
        if not r.number:
            continue
        inner = [p for p in free if p.area < 0.98 * r.poly.area and r.poly.buffer(0.02).contains(p)]
        r.holes = [p for p in inner if not any(q is not p and q.area > p.area and q.buffer(0.02).contains(p)
                                               for q in inner)]

    # ---- units (apartments)
    unit_polys = [p for p in (_poly(e) for e in msp.query('LWPOLYLINE[layer=="UNIT_OUTLINE"]')) if p is not None]
    unit_labels = [(UNIT_RE.match(t).group(1), Point(x, y)) for t, x, y, h in texts if UNIT_RE.match(t)]
    # labels inside an outline take the smallest one holding them; a label printed outside every
    # outline (seen on dev, e.g. in the stair hall) takes the nearest outline nobody claimed.
    fl.unit_labels = sorted({letter for letter, pt in unit_labels})
    fl.unit_by_distance = set()
    claimed = set()
    pending = []
    for letter, pt in unit_labels:
        cands = [i for i, p in enumerate(unit_polys) if p.buffer(0.05).contains(pt) and i not in claimed]
        if cands:
            i = min(cands, key=lambda i: unit_polys[i].area)
            fl.units[letter] = unit_polys[i]
            claimed.add(i)
        else:
            pending.append((letter, pt))
    for letter, pt in pending:
        d = sorted((unit_polys[i].distance(pt), i) for i in range(len(unit_polys)) if i not in claimed)
        if d and d[0][0] < 3.0:
            fl.units[letter] = unit_polys[d[0][1]]
            claimed.add(d[0][1])
            fl.unit_by_distance.add(letter)
    # an apartment can be drawn as several outlines with one label (a room across the stair hall, a
    # split-level part): unlabelled outlines holding apartment rooms (white fill on the PDF) join the
    # nearest labelled apartment. Rooms are attached after the PDF fills are known (_attach_rooms_to_units).
    fl.n_unit_outlines = len(unit_polys)
    fl._spare_unit_polys = [unit_polys[i] for i in range(len(unit_polys)) if i not in claimed]

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
        kind, sure = _classify_fixture(mem)
        odd = kind == "other" and any(t == "CIRCLE" or (t == "LWPOLYLINE" and n > 5) for t, n, r, g in mem)
        fl.symbols.append(Symbol(kind, comp, sure, odd))

    # numbered rooms printed without a name: bathrooms/WCs drawn with fixtures count as rooms,
    # empty ones are shafts. Verified against dev apartment totals.
    sanitary = [s.geom for s in fl.symbols if s.kind in ("toilet", "washbasin", "bathtub", "shower")]
    for r in fl.rooms:
        if r.number and not r.name:
            r.has_sanitary = any(r.poly.intersects(g.centroid) for g in sanitary)

    if pdf_path and Path(pdf_path).exists():
        import pymupdf

        with pymupdf.open(pdf_path) as doc:
            page = doc[0]
            fl.to_page, fl.fit_rms = _fit_page_transform(fl.texts, page)
            W, H = page.rect.width, page.rect.height
            fl.pdf_words = [(w, x0 / W, y0 / H, x1 / W, y1 / H) for x0, y0, x1, y1, w, *_ in page.get_text("words")
                            if re.match(r"^\d+(?:\.\d+)?$", w)]
            fills = _pdf_room_fills(page) if fl.to_page else []
        if fills:
            ax, bx, ay, by = fl.to_page
            for r in fl.rooms:
                pt = r.poly.representative_point()
                q = Point(ax * pt.x + bx, ay * pt.y + by)
                c = [(P.area, g) for P, g in fills if P.contains(q)]
                if c:
                    r.fill = min(c)[1]
    _attach_rooms_to_units(fl)
    return fl


def _attach_rooms_to_units(fl):
    def owner(r, polys):
        for letter, up in polys.items():
            if r.poly.intersection(up).area > 0.5 * r.poly.area:
                return letter
        return None

    for up in fl._spare_unit_polys:
        inside = [r for r in fl.rooms if r.number and r.poly.intersection(up).area > 0.5 * r.poly.area]
        if not fl.units or not inside or not all(r.fill == 1.0 for r in inside) or up.area > 40:
            continue
        # a whole unlabelled flat (kitchen, bath) is a separate unit the plan just doesn't name; only
        # a detached room or two without fixtures belongs to a labelled neighbour (2 dev cases)
        if any(up.contains(s.geom.centroid) for s in fl.symbols if s.kind not in ("door", "window", "other")):
            continue
        letter = min(fl.units, key=lambda k: fl.units[k].distance(up))
        if fl.units[letter].distance(up) < 5.0:
            fl.units[letter] = unary_union([fl.units[letter], up])
            fl.unit_merged.add(letter)
    del fl._spare_unit_polys
    for r in fl.rooms:
        r.unit = owner(r, fl.units)
