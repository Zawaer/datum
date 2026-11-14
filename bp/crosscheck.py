"""Cross-check: confirm an answer with a second, independent method.

    crosscheck(q, primary_result) -> {"status": "agree" | "conflict" | "single",
                                      "second": {"answer", "method", "evidence", "independence"} | None,
                                      "note": "..."}

The primary solvers read the most exact source available (the DXF twin of a Swiss PDF, the IFC model,
one YOLO detector on a CubiCasa PNG). The second method reads something else, so a mistake in one
parse is unlikely to repeat in the other:

- swiss_dwellings  (primary: DXF layers)  ->  the PDF itself: room labels / numbers / printed m² from the
  text layer, room areas from the PDF fill polygons (geometry, scaled by the printed 1:n), apartments from
  the unit labels and the red unit outlines, doors / windows / fixtures from the PDF vector symbols.
  Independence: medium-high. Same underlying dataset geometry, but a different file, a different
  renderer and a parser that never sees the DXF.
- ifc_models  (primary: IFC model)  ->  the SVG twin of the plan sheet (elements with their GUIDs, drawn
  per storey). Independence: medium. The sheet was rendered from the same model, so it catches
  query / filtering / storey-matching mistakes, not modelling errors.
- cubicasa5k  (primary: YOLO11s detector)  ->  a second, separately trained detector (YOLO11m at 1280 px;
  weights $BP_XCHECK_CC_WEIGHTS, default cache/crosscheck/cc_second_m1280.pt = a copy of
  cache/cubicasa/runs/m1280/weights/best.pt taken at epoch ~19 of that run) with its own count thresholds
  tuned on dev (train/crosscheck_tune_cc.py). Independence: low (same public training annotations). If that
  model is ever folded into the primary's ensemble, this check stops being independent: pick another one.
  A quick Tesseract try on the room labels (mh, kt, wc) at native resolution read none of them (not pursued).

Measured on test: runs/crosscheck_test.summary.md (analysis/crosscheck_report.py).

Never raises: any failure is "single". Results are cached per drawing.
"""
from __future__ import annotations

import functools
import math
import os
import re
import threading
import unicodedata
from pathlib import Path

from bp.data import data_root

# --------------------------------------------------------------------------------------------------
# agreement


AREA_TOL = 0.02  # same tolerance as the official scoring; geometry vs printed m² gets its own (dev-tuned)


def _num(x):
    try:
        return None if x is None or isinstance(x, bool) else float(x)
    except (TypeError, ValueError):
        return None


def agrees(qtype, a, b, tol=AREA_TOL):
    a, b = _num(a), _num(b)
    if a is None or b is None:
        return None
    if qtype == "count":
        return round(a) == round(b)
    if a == b:
        return True
    return abs(a - b) / max(abs(a), abs(b), 1e-9) <= tol


def _norm(s):
    return unicodedata.normalize("NFKC", s or "").strip().lower()


# --------------------------------------------------------------------------------------------------
# swiss_dwellings: read the PDF only

NUM_RE = re.compile(r"^[A-Z]?\d+(?:\.\d+)+$|^[A-Z]\d+$")
AREA_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*m²$")
UNIT_RE = re.compile(r"^(?:Whg\.|App\.|Wohnung|Appartement|Appartamento)\s*([A-Z]{1,2}\d*)$")
OUTDOOR_KW = ("balkon", "balcon", "loggia", "terrass", "sitzplatz", "veranda", "aussen", "extérieur", "esterno",
              "dachterrasse", "patio", "garten", "jardin", "giardino")
SHAFT_KW = ("schacht", "luftraum", "gaine", "vide", "cavedio", "vuoto", "void", "shaft")
G_ROOM, G_COMMON, G_OUTDOOR = 1.0, 0.953, 0.894
# window symbols read from the PDF vectors matched the DXF count on only 86 % of dev window questions (thick
# walls without glazing lines, rotated plans): too weak to call a conflict, so window counts stay "single".
SWISS_WINDOWS = os.environ.get("BP_XCHECK_SWISS_WINDOWS") == "1"
UNIT_RED = (0.69, 0.227, 0.18)


def _close(c, ref, tol=0.01):
    return c is not None and len(c) >= 3 and all(abs(a - b) <= tol for a, b in zip(c, ref))


def _rings(d):
    """Sub-paths of a PyMuPDF drawing as point lists (a new ring starts where the pen jumps)."""
    rings, cur, last = [], [], None
    for it in d["items"]:
        op = it[0]
        if op == "re":
            r = it[1]
            rings.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)])
            last = None
            continue
        if op == "qu":
            q = it[1]
            rings.append([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)])
            last = None
            continue
        p0, p1 = it[1], it[-1]
        if last is None or abs(p0.x - last[0]) > 0.05 or abs(p0.y - last[1]) > 0.05:
            if len(cur) >= 3:
                rings.append(cur)
            cur = [(p0.x, p0.y)]
        if op == "c":  # sample the bezier coarsely: area error is negligible at plan scale
            a, b, c_, e = it[1], it[2], it[3], it[4]
            for t in (0.25, 0.5, 0.75):
                s = 1 - t
                cur.append((s ** 3 * a.x + 3 * s * s * t * b.x + 3 * s * t * t * c_.x + t ** 3 * e.x,
                            s ** 3 * a.y + 3 * s * s * t * b.y + 3 * s * t * t * c_.y + t ** 3 * e.y))
        cur.append((p1.x, p1.y))
        last = (p1.x, p1.y)
    if len(cur) >= 3:
        rings.append(cur)
    return rings


def _even_odd(rings):
    """Polygon of a filled path: the largest ring minus the rings inside it (shafts drawn as holes)."""
    from shapely.geometry import Polygon

    polys = []
    for r in rings:
        p = Polygon(r)
        if not p.is_valid:
            p = p.buffer(0)
        if p.area > 0:
            polys.append(p)
    if not polys:
        return None
    polys.sort(key=lambda p: -p.area)
    out = polys[0]
    for p in polys[1:]:
        if out.buffer(0.1).contains(p):
            out = out.difference(p)
        else:
            out = out.union(p)
    return out


class SwissPdf:
    """Everything the cross-check needs from one Swiss PDF, in page points (origin top-left)."""

    def __init__(self, pdf_path: str):
        import pymupdf
        from shapely.geometry import Point, Polygon

        with pymupdf.open(pdf_path) as doc:
            page = doc[0]
            self.W, self.H = page.rect.width, page.rect.height
            spans = []
            for blk in page.get_text("dict")["blocks"]:
                for ln in blk.get("lines", []):
                    for s in ln["spans"]:
                        t = s["text"].strip()
                        if t:
                            spans.append((t, tuple(s["bbox"]), "Bold" in s["font"], s["size"]))
            drawings = page.get_drawings()
            words = page.get_text("words")
        text = " ".join(w[4] for w in words)
        m = re.search(r"\b1\s*:\s*(\d{2,4})\b", text)
        self.m_per_pt = int(m.group(1)) * 0.0254 / 72 if m else None
        leg = [w[1] for w in words if w[4] in ("Legende", "Légende", "Legenda", "Legend")]
        self.legend_top = min(leg) - 2 if leg else self.H + 1
        self.spans = spans

        # ---- room label blocks: bold number, name just above, printed area just below
        def cx(b):
            return (b[0] + b[2]) / 2

        self.rooms = []
        for t, b, bold, size in spans:
            if not (bold and NUM_RE.match(t)) or b[1] > self.legend_top:
                continue
            near = [(t2, b2) for t2, b2, bold2, s2 in spans if not bold2 and abs(cx(b2) - cx(b)) < 0.6 * size
                    and b2 != b]
            above = sorted((b[1] - b2[3], t2) for t2, b2 in near if -0.5 < b[1] - b2[3] < 0.8 * size)
            below = sorted((b2[1] - b[3], t2) for t2, b2 in near if -0.5 < b2[1] - b[3] < 0.8 * size)
            name = next((t2 for _, t2 in above if not AREA_RE.match(t2) and not NUM_RE.match(t2)), None)
            area = next((float(AREA_RE.match(t2).group(1)) for _, t2 in below if AREA_RE.match(t2)), None)
            self.rooms.append({"number": t, "name": name, "printed": area, "pt": (cx(b), (b[1] + b[3]) / 2),
                               "bbox": b, "fill": None, "grey": None, "geom": None})
        self.unit_labels = {}
        for t, b, bold, size in spans:
            m = UNIT_RE.match(t)
            if bold and m and b[1] < self.legend_top:
                self.unit_labels.setdefault(m.group(1), (cx(b), (b[1] + b[3]) / 2))

        # ---- room fills (stroke 0.541; fill grey = area type), unit outlines (red), symbols
        fills, units, doors, rects, small = [], [], [], [], []
        for d in drawings:
            r = d["rect"]
            if r.y0 > self.legend_top:
                continue
            col, fill, w = d.get("color"), d.get("fill"), d.get("width") or 0
            if d["type"] == "fs" and _close(col, (0.541,) * 3) and fill:
                p = _even_odd(_rings(d))
                if p is not None and p.area > 0:
                    fills.append((p, round(sum(fill) / 3, 3)))
            elif d["type"] == "s" and _close(col, UNIT_RED, 0.02) and len(d["items"]) >= 3:
                rr = _rings(d)
                if rr:
                    p = Polygon(max(rr, key=len)).buffer(0)
                    if p.area > 0:
                        units.append(p)
            elif d["type"] == "s" and _close(col, (0.267,) * 3) and abs(w - 0.37) < 0.03 \
                    and len(d["items"]) == 1 and d["items"][0][0] == "qu":
                doors.append(r)  # one door frame quad per door (single / double / sliding)
            elif d["type"] == "fs" and _close(col, (0.0,) * 3) and _close(fill, (1.0,) * 3) \
                    and abs(w - 0.51) < 0.03 and (len(d["items"]) == 4 and all(i[0] == "l" for i in d["items"])
                                                  or len(d["items"]) == 1 and d["items"][0][0] == "re"):
                rects.append((r, Polygon(_rings(d)[0]).buffer(0)))  # window outline, or a fixture's outline
            elif d["type"] == "s":
                it = d["items"][0]
                ends = ((it[1].x, it[1].y), (it[2].x, it[2].y)) if len(d["items"]) == 1 and it[0] == "l" else None
                small.append((r, w, "".join(i[0] for i in d["items"]), len(d["items"]), col, ends))
        self.fills = fills
        for rm in self.rooms:
            pt = Point(rm["pt"])
            c = [(p.area, p, g) for p, g in fills if p.contains(pt)]
            if c:
                a, p, g = min(c, key=lambda x: x[0])
                rm["fill"], rm["grey"] = p, g
                if self.m_per_pt:
                    rm["geom"] = round(a * self.m_per_pt ** 2, 2)
        self.units = {}
        for letter, (x, y) in self.unit_labels.items():
            pt = Point(x, y)
            c = [p for p in units if p.buffer(1.0).contains(pt)]
            if not c and units:
                c = [min(units, key=lambda p: p.distance(pt))]
                if c[0].distance(pt) > 40:
                    c = []
            if c:
                self.units[letter] = min(c, key=lambda p: p.area)
        self.doors = doors
        self.windows, self.fixtures = [], []
        for R, P in rects:
            inner = [s for s in small if R.x0 - 0.3 <= s[0].x0 and s[0].x1 <= R.x1 + 0.3
                     and R.y0 - 0.3 <= s[0].y0 and s[0].y1 <= R.y1 + 0.3]
            content = [s[:5] for s in inner if abs(s[1] - 0.51) < 0.03]
            # windows: a thin rectangle (in a wall, any rotation) holding glazing lines along its length
            mrr = P.minimum_rotated_rectangle
            xy = list(mrr.exterior.coords) if mrr.geom_type == "Polygon" else []
            sides = sorted(math.dist(xy[i], xy[i + 1]) for i in range(2)) if len(xy) >= 3 else [0, 0]
            Pb = P.buffer(0.4)
            glazing = [s for s in inner if s[5] and abs(s[1] - 0.37) < 0.03 and math.dist(*s[5]) >= 0.8 * sides[1]
                       and all(Pb.contains(Point(e)) for e in s[5])]
            in_poly = [s for s in content if P.contains(Point((s[0].x0 + s[0].x1) / 2, (s[0].y0 + s[0].y1) / 2))]
            thin = sides[0] * (self.m_per_pt or 0.0353) <= 0.8
            if glazing and thin and not in_poly:
                self.windows.append(R)
            elif content:
                self.fixtures.append((R, self._fixture_kind(content)))

    def _fixture_kind(self, content):
        """Classify a fixture outline's contents (rendered from the same symbols the DXF holds)."""
        k = self.m_per_pt or 0.0254 / 72 * 100
        curves = [n for r, w, ops, n, col in content if set(ops) == {"l"} and n >= 20]
        circles = [max(r.width, r.height) / 2 * k for r, w, ops, n, col in content if set(ops) == {"c"}]
        quads = sum(1 for r, w, ops, n, col in content if ops in ("qu", "llll"))
        lines = sum(1 for r, w, ops, n, col in content if ops == "l")
        n_burner = sum(1 for rad in circles if abs(rad - 0.08) < 0.025)
        drain = sum(1 for rad in circles if 0.03 <= rad <= 0.06)
        if n_burner >= 2:
            return "stove"
        if quads and drain and not curves:
            return "shower"
        if curves:
            if max(curves) >= 59:
                return "bathtub"
            if circles:
                return "washbasin"
            return "toilet"
        return "other"

    def scale_ok(self):
        return self.m_per_pt is not None

    def norm(self, b):
        return [round(b[0] / self.W, 5), round(b[1] / self.H, 5), round(b[2] / self.W, 5), round(b[3] / self.H, 5)]


@functools.lru_cache(maxsize=128)
def swiss_pdf(pdf_path: str) -> SwissPdf:
    return SwissPdf(pdf_path)


def _room_key(num):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", num)]


def swiss_second(q):
    """Second answer for a Swiss Dwellings question, from the PDF alone. Returns dict or None."""
    from bp.solvers.swiss import parse_question

    intent = parse_question(q["question"], q.get("type"))
    pdf = (data_root() / q["path"]).with_suffix(".pdf")
    if intent is None or not pdf.exists():
        return None
    sp = swiss_pdf(str(pdf))
    rel = str(Path(q["path"]).with_suffix(".pdf"))
    ext = Path(q["path"]).suffix.lower()
    page_file = q["path"] if ext in (".pdf", ".png") else rel
    W, H = sp.W, sp.H

    def nb(R):
        return [round(R.x0 / W, 5), round(R.y0 / H, 5), round(R.x1 / W, 5), round(R.y1 / H, 5)]

    def room_poly(rm, value, label):
        p = rm["fill"]
        if p is None:
            return {"kind": "text", "file": page_file, "page": 0, "bbox": nb_t(rm["bbox"]), "label": label}
        g = p if p.geom_type == "Polygon" else max(p.geoms, key=lambda x: x.area)
        return {"kind": "polygon", "file": page_file, "page": 0, "label": label, "value": value,
                "points": [[round(x / W, 5), round(y / H, 5)] for x, y in g.exterior.coords]}

    def nb_t(b):
        return [round(b[0] / W, 5), round(b[1] / H, 5), round(b[2] / W, 5), round(b[3] / H, 5)]

    def geom_area(rms, what):
        """Sum of PDF-geometry areas (fill polygon x scale^2); None if any room has no fill."""
        if not sp.scale_ok() or any(r["geom"] is None for r in rms):
            return None
        tot = round(sum(r["geom"] for r in rms), 2)
        ev = [room_poly(r, r["geom"], f"{r['number']} {r['name'] or ''}: {r['geom']:.2f} m² (PDF outline)")
              for r in rms]
        terms = " + ".join(f"{r['geom']:.2f}" for r in rms) or "0"
        return {"answer": tot, "method": "swiss-pdf-geometry", "evidence": ev,
                "explanation": f"{what}: {terms} = {tot:.2f} m², "
                               f"measured on the PDF room outlines at 1:{round(sp.m_per_pt * 72 / 0.0254)}"}

    kind = intent[0]
    if kind == "count_symbol":
        what = intent[1]
        if what == "apartment":
            letters = sorted(sp.unit_labels)
            ev = [{"kind": "text", "file": page_file, "page": 0, "label": f"apartment {i}: unit label '{L}'",
                   "bbox": nb_t((x - 8, y - 3, x + 8, y + 3))} for i, (L, (x, y)) in enumerate(
                       sorted(sp.unit_labels.items()), 1)]
            return {"answer": len(letters), "method": "swiss-pdf-text", "evidence": ev,
                    "explanation": f"{len(letters)} unit labels in the PDF text ({', '.join(letters)})"}
        if what == "door":
            items = sp.doors
            src = "door frame symbols in the PDF vectors"
        elif what == "window":
            if not SWISS_WINDOWS:
                return None
            items = sp.windows
            src = "window symbols (wall rectangle + glazing lines) in the PDF vectors"
        else:
            items = [R for R, k in sp.fixtures if k == what]
            src = f"{what} symbols in the PDF vectors (classified by drawn shape)"
        items = sorted(items, key=lambda R: (round(R.y0), R.x0))
        ev = [{"kind": "box", "file": page_file, "page": 0, "bbox": nb(R), "label": f"{what} {i} (PDF)", "value": 1}
              for i, R in enumerate(items, 1)]
        return {"answer": len(items), "method": "swiss-pdf-vectors", "evidence": ev,
                "explanation": f"{len(items)} {src}"}
    if kind == "count_label":
        label = _norm(intent[1])
        if not label:
            return None
        hits = sorted((r for r in sp.rooms if _norm(r["name"]) == label), key=lambda r: _room_key(r["number"]))
        ev = [{"kind": "text", "file": page_file, "page": 0, "bbox": nb_t(r["bbox"]),
               "label": f"room {i}: {r['number']} {r['name']} (PDF text)"} for i, r in enumerate(hits, 1)]
        return {"answer": len(hits), "method": "swiss-pdf-text", "evidence": ev,
                "explanation": f"{len(hits)} room labels '{intent[1]}' in the PDF text"}
    if kind == "area_room":
        hits = [r for r in sp.rooms if r["number"] == intent[1]]
        if len(hits) != 1:
            return None
        return geom_area(hits, f"room {intent[1]}")
    if kind == "area_label":
        label = _norm(intent[1])
        hits = [r for r in sp.rooms if _norm(r["name"]) == label]
        if not hits:
            return None
        return geom_area(hits, f"rooms labelled '{intent[1]}'")

    def indoor(r):
        n = _norm(r["name"])
        return r["grey"] != G_OUTDOOR and not any(k in n for k in OUTDOOR_KW) and not any(k in n for k in SHAFT_KW)

    if kind == "area_numbered":
        hits = [r for r in sp.rooms if indoor(r)]
        return geom_area(hits, "numbered indoor rooms")
    if kind == "area_apartment":
        from shapely.geometry import Point

        up = sp.units.get(intent[1])
        if up is None:
            return None
        hits = [r for r in sp.rooms if indoor(r) and r["grey"] != G_COMMON and up.buffer(0.5).contains(Point(r["pt"]))]
        return geom_area(hits, f"apartment {intent[1]}")
    return None


# --------------------------------------------------------------------------------------------------
# ifc_models: read the SVG twins of the plan sheets only (never the IFC file)

_SVG_G = re.compile(r'<g\b([^>]*\bdata-guid="[^>]*)>(.*?)</g>', re.S)
_ATTR = re.compile(r'([\w-]+)="([^"]*)"')
_SVG_D = re.compile(r'\bd="([^"]+)"')
_SVG_TITLE = re.compile(r'font-weight="bold">[^<]*?(?:—|-)\s*[^<:]*:\s*([^<]+)')
_SVG_SCALE = re.compile(r">[^<]*?\b1\s*:\s*(\d{2,4})\b")

# which SVG classes count as the question's element class (IfcConvert writes the entity name)
IFC_KIND_CLASSES = {
    "wall": ("IfcWall", "IfcWallStandardCase", "IfcWallElementedCase"),
    "door": ("IfcDoor", "IfcDoorStandardCase"),
    "window": ("IfcWindow", "IfcWindowStandardCase"),
    "column": ("IfcColumn", "IfcColumnStandardCase"),
    "space": ("IfcSpace",),
}
# (kind, scope) pairs whose sheet count matched the model on >= 95 % of dev questions. Walls (split into
# parts / layers on the sheet), stairs (drawn as flights or not cut) and model-wide windows (not every
# window is cut at 1.2 m) are not comparable, so those stay "single" rather than raising false conflicts.
IFC_COUNT_OK = {("door", "sheet"), ("door", "model"), ("column", "sheet"), ("column", "model"),
                ("space", "sheet"), ("space", "model"), ("window", "sheet")}


@functools.lru_cache(maxsize=256)
def svg_sheet(svg_path: str) -> dict:
    """{"storey": title storey name, "scale": n (1:n), "els": {guid: {"cls", "name", "rings"}}}; rings in mm on paper."""
    from bp.ifc.plan2d import parse_path

    s = Path(svg_path).read_text(errors="replace")
    t = _SVG_TITLE.search(s)
    sc = _SVG_SCALE.search(s)
    els = {}
    for attrs, body in _SVG_G.findall(s):
        a = dict(_ATTR.findall(attrs))
        guid = a.get("data-guid")
        cls = (a.get("class") or "").split()
        cls = next((c for c in cls if c.startswith("Ifc")), None)
        if not guid or not cls:
            continue
        rings = [sub for d in _SVG_D.findall(body) for sub in parse_path(d)]
        rec = els.setdefault(guid, {"cls": cls, "name": a.get("data-name") or "", "rings": []})
        rec["rings"] += rings
    return {"storey": t.group(1).strip() if t else None, "scale": int(sc.group(1)) if sc else None, "els": els,
            "vb": [float(v) for v in re.search(r'viewBox="([-\d.\s]+)"', s).group(1).split()]}


def _ifc_sheets(qpath: str) -> list[Path]:
    p = data_root() / qpath
    stem = re.split(r"_(?:plan|elevation|section)-", p.stem)[0]
    return sorted(p.parent.glob(f"{glob_escape(stem)}_plan-*.svg"))


def glob_escape(s):
    return re.sub(r"([*?\[])", r"[\1]", s)


def _nkey(s):
    s = unicodedata.normalize("NFKC", s or "").casefold()
    return re.sub(r"[\s._\-]+", "", s)


def _ring_area(r):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1]))) / 2


def _space_poly_area(rings):
    """Even-odd area of an IfcSpace footprint drawn as one or more rings (paper mm²)."""
    rings = [r for r in rings if len(r) >= 3]
    if not rings:
        return 0.0
    rings.sort(key=_ring_area, reverse=True)
    return max(0.0, _ring_area(rings[0]) - sum(_ring_area(r) for r in rings[1:]))


def ifc_second(q):
    """Second answer for an ifc_models question from the SVG plan sheets. Returns dict or None."""
    from bp.ifc.query import parse

    pq = parse(q)
    sheets = _ifc_sheets(q["path"])
    if not sheets:
        return None
    by_storey = {}
    for f in sheets:
        sh = svg_sheet(str(f))
        if sh["storey"]:
            by_storey.setdefault(_nkey(sh["storey"]), (f, sh))
    slots = pq["slots"]
    sheet = None
    for s in slots:
        if _nkey(s) in by_storey:
            sheet = by_storey[_nkey(s)]
    rel = lambda f: str(f.relative_to(data_root())).replace(".svg", ".pdf")  # noqa: E731

    def box(f, sh, guid, label, value=None):
        vx, vy, vw, vh = sh["vb"]
        pts = [p for r in sh["els"][guid]["rings"] for p in r] or [(vx, vy)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return {"kind": "box", "file": rel(f), "page": 0, "label": label, "value": value,
                "bbox": [round((min(xs) - vx) / vw, 5), round((min(ys) - vy) / vh, 5),
                         round((max(xs) - vx) / vw, 5), round((max(ys) - vy) / vh, 5)]}

    if pq["kind"] == "count":
        classes = IFC_KIND_CLASSES.get(pq["what"])
        if not classes:
            return None
        if (pq["what"], "sheet" if sheet is not None else "model") not in IFC_COUNT_OK:
            return None
        if sheet is not None:
            f, sh = sheet
            hits = [(f, sh, g) for g, e in sh["els"].items() if e["cls"] in classes]
            scope = f"plan sheet '{sh['storey']}'"
        elif slots:  # model-wide: union over every plan sheet of the model
            seen, hits = set(), []
            for f in sheets:
                sh = svg_sheet(str(f))
                for g, e in sh["els"].items():
                    if e["cls"] in classes and g not in seen:
                        seen.add(g)
                        hits.append((f, sh, g))
            scope = f"all {len(sheets)} plan sheets"
        else:
            return None
        ev = [box(f, sh, g, f"{i}. {sh['els'][g]['cls']}", 1) for i, (f, sh, g) in enumerate(hits[:200], 1)]
        return {"answer": len(hits), "method": "ifc-svg-sheet",
                "explanation": f"{len(hits)} {pq['what']} elements drawn on {scope} (SVG twin, by GUID)",
                "evidence": ev}
    if pq["kind"] == "room_area" and sheet is not None:
        f, sh = sheet
        if not sh["scale"]:
            return None
        k = (sh["scale"] / 1000.0) ** 2  # paper mm² -> m²
        spaces = {g: e for g, e in sh["els"].items() if e["cls"] == "IfcSpace"}
        room = next((s for s in slots if _nkey(s) not in by_storey), None)
        if room is None:
            if not pq.get("total"):
                return None
            hits = list(spaces)
        else:
            m = re.search(r"\(([^()]*)\)\s*$", room)
            keys = {_nkey(room)} | ({_nkey(m.group(1))} if m else set())
            hits = [g for g, e in spaces.items() if _nkey(e["name"]) in keys]
            if len(hits) != 1:
                return None
        vals = {g: _space_poly_area(spaces[g]["rings"]) * k for g in hits}
        tot = round(sum(vals.values()), 2)
        ev = [box(f, sh, g, f"IfcSpace {spaces[g]['name']}", round(v, 2)) for g, v in vals.items()]
        return {"answer": tot, "method": "ifc-svg-footprint",
                "explanation": f"footprint of {len(hits)} IfcSpace outline(s) on plan sheet '{sh['storey']}' "
                               f"at 1:{sh['scale']} = {tot:.2f} m²",
                "evidence": ev}
    return None


# --------------------------------------------------------------------------------------------------
# cubicasa5k: a second, separately trained detector (and its own dev-tuned count thresholds)

CC_SECOND_WEIGHTS = os.environ.get("BP_XCHECK_CC_WEIGHTS", "cache/crosscheck/cc_second_m1280.pt")
CC_SECOND_IMGSZ = 1280
CC_DET_CACHE = Path(__file__).resolve().parents[1] / "cache" / "crosscheck" / "cc_dets"
CC_THRESH_FILE = Path(__file__).resolve().parents[1] / "cache" / "crosscheck" / "cc_second_thresholds.json"
_cc_model, _cc_lock = None, threading.Lock()


def cc_second_dets(path: str):
    """All detections (cls, score, [x0, y0, x1, y1] normalised) of the second detector, cached on disk."""
    import json

    global _cc_model
    f = CC_DET_CACHE / (Path(path).stem + ".json")
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        pass
    if not Path(CC_SECOND_WEIGHTS).exists():
        return None
    from bp.cubicasa.infer import predict

    with _cc_lock:
        if _cc_model is None:
            from ultralytics import YOLO

            _cc_model = YOLO(CC_SECOND_WEIGHTS)
        img = str(data_root() / path) if not Path(path).is_absolute() else path
        dets = [(n, round(s, 4), [round(v, 5) for v in b]) for n, s, b in predict(_cc_model, img, CC_SECOND_IMGSZ)]
    CC_DET_CACHE.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(dets))
    os.replace(tmp, f)
    return dets


def _cc_inside(b, r, pad=0.01):
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return r[0] - pad <= cx <= r[2] + pad and r[1] - pad <= cy <= r[3] + pad


def cc_count(t, dets, th):
    """Count for template t from second-detector detections at threshold th (one per template)."""
    from bp.cubicasa.classes import COUNTS

    kept = [d for d in dets if d[0] in COUNTS[t] and d[1] >= th]
    if t == "sauna":  # a sauna = a sauna room, or a stove outside every detected sauna room
        rooms = [d[2] for d in kept if d[0] == "sauna_room"]
        kept = [d for d in kept if d[0] == "sauna_room" or not any(_cc_inside(d[2], r) for r in rooms)]
    return kept


# tuned by train/crosscheck_tune_cc.py on dev questions over the YOLO-validation drawings (never test)
CC_THRESH_DEFAULT = {"balcony": 0.375, "bathroom": 0.35, "bedroom": 0.425, "door": 0.425, "floor": 0.525,
                     "kitchen": 0.25, "sauna": 0.5, "shower_bath": 0.075, "sink": 0.325, "toilet": 0.35,
                     "wc_room": 0.15, "window": 0.4}


@functools.lru_cache(maxsize=1)
def cc_thresholds():
    import json

    try:
        return json.loads(CC_THRESH_FILE.read_text())
    except (OSError, ValueError):
        return dict(CC_THRESH_DEFAULT)


def cubicasa_second(q):
    from bp.cubicasa.questions import LABEL, target

    t = target(q["question"])
    th = cc_thresholds().get(t) if t else None
    if th is None:
        return None
    dets = cc_second_dets(q["path"])
    if dets is None:
        return None
    kept = cc_count(t, dets, th)
    ev = [{"kind": "box", "file": q["path"], "page": 0, "bbox": b, "label": f"{LABEL[t]} {i} (2nd detector)",
           "value": 1, "score": s} for i, (n, s, b) in enumerate(kept, 1)]
    return {"answer": len(kept), "method": "cubicasa-yolo11m-2nd",
            "explanation": f"{len(kept)} {LABEL[t]}{'' if len(kept) == 1 else 's'} found by a second, separately "
                           f"trained detector (YOLO11m at {CC_SECOND_IMGSZ} px)",
            "evidence": ev}


def _precompute_cc(paths):
    for i, p in enumerate(paths):
        cc_second_dets(p)
        if i % 50 == 0:
            print(f"  {i}/{len(paths)}", flush=True)


# --------------------------------------------------------------------------------------------------
# dispatcher

SECOND = {"swiss_dwellings": swiss_second, "ifc_models": ifc_second, "cubicasa5k": cubicasa_second}
INDEPENDENCE = {
    "swiss_dwellings": "medium-high: the PDF itself (text layer + vector paths), never the DXF the primary reads; "
                       "both are renderings of the same dataset geometry",
    "ifc_models": "medium: the SVG twin of the plan sheet (elements by GUID, footprints); rendered from the "
                  "same IFC, so it catches query / storey / filter mistakes, not modelling errors",
    "cubicasa5k": "low: a separately trained detector (YOLO11m vs the primary's YOLO11s) on the same public "
                  "annotations; errors can be correlated",
}
_cache: dict = {}
_cache_lock = threading.Lock()


def _single(note, second=None):
    return {"status": "single", "second": second, "note": note}


def crosscheck(q, primary) -> dict:
    """Second-method check of a primary result. Never raises."""
    try:
        src = q.get("source")
        fn = SECOND.get(src)
        if fn is None or q.get("type") not in ("count", "area"):
            return _single("no second method for this kind of question")
        key = (q.get("path"), q.get("question"))
        with _cache_lock:
            sec = _cache.get(key, ...)
        if sec is ...:
            sec = fn(q)
            with _cache_lock:
                if len(_cache) > 20000:
                    _cache.clear()
                _cache[key] = sec
        if sec is None or sec.get("answer") is None:
            return _single("no independent second reading available for this question")
        sec = {**sec, "independence": INDEPENDENCE[src]}
        pa = (primary or {}).get("answer")
        if pa is None:
            return _single(f"primary abstained; {sec['method']} reads {sec['answer']}", sec)
        ok = agrees(q["type"], pa, sec["answer"])
        if ok is None:
            return _single("answers not comparable", sec)
        if ok:
            return {"status": "agree", "second": sec,
                    "note": f"2 methods agree: {(primary or {}).get('method', 'primary')} = {pa}, "
                            f"{sec['method']} = {sec['answer']}"}
        return {"status": "conflict", "second": sec,
                "note": f"conflict: {(primary or {}).get('method', 'primary')} says {pa}, {sec['method']} says "
                        f"{sec['answer']}; see the marks of both"}
    except Exception as e:  # noqa: BLE001  a cross-check must never take an answer down
        return _single(f"cross-check failed: {type(e).__name__}: {str(e)[:120]}")


if __name__ == "__main__":  # python -m bp.crosscheck precompute-cc {dev-val|test}
    import sys

    from bp.data import load_questions

    if sys.argv[1:2] == ["precompute-cc"]:
        part = sys.argv[2]
        qs = [q for q in load_questions() if q["source"] == "cubicasa5k"]
        if part == "test":
            paths = sorted({q["path"] for q in qs if q["split"] == "test"})
        else:
            val = {p.stem for p in Path("cache/yolo_cc/images/val").glob("*.png")}
            paths = sorted({q["path"] for q in qs if q["split"] == "dev" and Path(q["path"]).stem in val})
        print(len(paths), "images")
        _precompute_cc(paths)
