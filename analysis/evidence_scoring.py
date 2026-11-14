"""Evidence hit-rate: do our numbered evidence boxes land on the right objects?

    .venv/bin/python analysis/evidence_scoring.py [--run runs/router_full_test_v7.jsonl]

For every TEST-split count question whose answer comes with numbered boxes, we match the boxes
one-to-one to independent gold instances and report precision (boxes on a real instance of the asked
class), recall (gold instances covered) and "count right AND boxes right" (count correct and every box
matched, every instance boxed). Two match rules: IoU >= 0.5, and the looser box-centre-inside-gold-box.

Gold instances, by source:
- cubicasa5k: the CubiCasa5k SVG annotation of the drawing (cache/eval_gold/, test drawings only,
  extracted for this evaluation by analysis/extract_eval_gold.py; no training/tuning code reads it),
  counted with the gold definitions recovered on dev by train/cubicasa/check_gold.py
  (bp/cubicasa/classes.py COUNTS + svg_class, sauna = sauna rooms + stoves outside them).
- ifc_models plan PDFs: the IfcConvert SVG twin of the sheet; every <g class="... IfcDoor" data-guid>
  of the asked class is an instance (our own parser here: it also reads class="cut IfcWall").
- swiss_dwellings: an independent PDF-vector extraction (PyMuPDF get_drawings on the PDF, never the DXF
  our solver reads). Doors = the grey (0.27) 0.37-pt swing paths, one per door: equals the official
  count on 115/115 dev questions checked. Windows = groups of parallel equal-length black 0.37-pt
  segments (window glazing lines): matches the official count on only ~57 % of dev questions, so it is
  used only where it reproduces the official count ("gold-consistent"). Fixtures and apartments have no
  reliable PDF-only extraction and are not scored.

"gold-consistent" = the independent gold instance count equals the official dataset answer; we report
both all questions and that subset (on the rest the annotation and the question disagree).
"""
import argparse
import collections
import csv
import functools
import json
import math
import re
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from bp.data import data_root  # noqa: E402

EVAL_GOLD = ROOT / "cache/eval_gold"
# iou: IoU >= 0.5; centre: our box centre inside the gold box; mutual: either box's centre inside the other
# (for thin / fragmentary gold boxes: SVG fixture boundaries that cover only part of the symbol, Swiss window glazing lines)
RULES = ("iou", "centre", "mutual")


# ---------------------------------------------------------------- matching
def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def centre_in(p, g, pad=0.0):
    cx, cy = (p[0] + p[2]) / 2, (p[1] + p[3]) / 2
    return g[0] - pad <= cx <= g[2] + pad and g[1] - pad <= cy <= g[3] + pad


def match(pred, gold, rule):
    """Greedy one-to-one matching; returns number of matched pairs and best IoU per pred."""
    pairs = []
    for i, p in enumerate(pred):
        for j, g in enumerate(gold):
            v = iou(p, g)
            if rule == "iou" and v >= 0.5:
                pairs.append((-v, i, j))
            elif (rule == "centre" and centre_in(p, g)) or (rule == "mutual" and (centre_in(p, g) or centre_in(g, p))):
                d = math.hypot((p[0] + p[2] - g[0] - g[2]) / 2, (p[1] + p[3] - g[1] - g[3]) / 2)
                pairs.append((d - v, i, j))
    pairs.sort()
    ui, uj, n = set(), set(), 0
    for _, i, j in pairs:
        if i in ui or j in uj:
            continue
        ui.add(i)
        uj.add(j)
        n += 1
    return n


# ---------------------------------------------------------------- cubicasa gold
@functools.lru_cache(maxsize=2048)
def cc_instances(stem):
    from bp.cubicasa.classes import svg_class
    from bp.cubicasa.svg import parse
    f = EVAL_GOLD / "svg" / f"{stem}.svg"
    sizes = cc_sizes()
    if not f.exists() or stem not in sizes:
        return None
    sw, sh = sizes[stem]
    out = collections.defaultdict(list)
    for o in parse(f)["objects"]:
        c = svg_class(o)
        if c is None or o.get("bbox") is None:
            continue
        x0, y0, x1, y1 = o["bbox"]
        b = [max(0, x0 / sw), max(0, y0 / sh), min(1, x1 / sw), min(1, y1 / sh)]
        if b[2] - b[0] <= 0 or b[3] - b[1] <= 0:
            continue
        out[c].append(b)
    return dict(out)


@functools.lru_cache(maxsize=1)
def cc_sizes():
    p = EVAL_GOLD / "scaled_sizes.json"
    return json.loads(p.read_text()) if p.exists() else {}


def cc_gold(row):
    from bp.cubicasa.classes import COUNTS
    from bp.cubicasa.questions import target
    t = target(row["question"])
    inst = cc_instances(Path(row["path"]).stem)
    if t is None or inst is None:
        return None, None
    boxes = []
    for c in COUNTS[t]:
        boxes += [(c, b) for b in inst.get(c, [])]
    if t == "sauna":
        rooms = [b for c, b in boxes if c == "sauna_room"]
        boxes = [(c, b) for c, b in boxes if c == "sauna_room" or not any(centre_in(b, r) for r in rooms)]
    return t, [b for _, b in boxes]


# ---------------------------------------------------------------- ifc gold
IFC_CLASSES = [  # (target, regex over the question in any of the dataset languages, SVG classes)
    ("door", r"\bdoors?\b|Türen|porte\b|deuren|puertas|portes", ("IfcDoor",)),
    ("window", r"windows|Fenster|finestre|ramen|ventanas|fenêtres", ("IfcWindow",)),
    ("space", r"rooms|spaces|Räume|ruimtes|locali|stanze|vani|espacios|pièces|ambienti", ("IfcSpace",)),
    ("wall", r"walls|Wände|muri|wanden|muros|murs|pareti", ("IfcWall", "IfcWallStandardCase")),
    ("column", r"columns|Stützen|pilastri|colonne|kolommen|columnas|poteaux", ("IfcColumn",)),
    ("stair", r"stairs|Treppen|scale|trappen|escaleras|escaliers", ("IfcStair",)),
    ("beam", r"beams|Träger|travi|balken|vigas|poutres", ("IfcBeam",)),
    ("slab", r"slabs|Decken|solai|vloeren|losas|dalles", ("IfcSlab",)),
]
_G = re.compile(r'<g\b[^>]*?class="([^"]*)"[^>]*?data-guid="([^"]+)"[^>]*>(.*?)</g>', re.S)


@functools.lru_cache(maxsize=256)
def ifc_sheet(svg_path):
    from bp.ifc.plan2d import _D, _VB, parse_path
    p = Path(svg_path)
    if not p.exists():
        return None
    s = p.read_text(errors="replace")
    m = _VB.search(s)
    vx, vy, vw, vh = (float(v) for v in m.group(1).split())
    out = {}
    for cls, guid, body in _G.findall(s):
        ifc = next((t for t in cls.split() if t.startswith("Ifc")), None)
        if ifc is None:
            continue
        pts = [(x, y) for d in _D.findall(body) for sub in parse_path(d) for x, y in sub]
        if not pts:
            continue
        r = out.setdefault(guid, {"cls": ifc, "cut": "cut" in cls.split(), "pts": []})
        r["pts"] += pts
    for r in out.values():
        xs = [(x - vx) / vw for x, _ in r["pts"]]
        ys = [(y - vy) / vh for _, y in r["pts"]]
        r["bbox"] = [min(xs), min(ys), max(xs), max(ys)]
        del r["pts"]
    return out


def ifc_gold(row):
    q = row["question"]
    tgt = next(((t, cl) for t, rx, cl in IFC_CLASSES if re.search(rx, q, re.I)), None)
    if tgt is None:
        return None, None
    sheet = ifc_sheet(str((data_root() / row["path"]).with_suffix(".svg")))
    if sheet is None:
        return None, None
    return tgt[0], [r["bbox"] for r in sheet.values() if r["cls"] in tgt[1]]


def ifc_scope(q):
    return "model-wide (sheet subset)" if re.search(r"in the model|enthält das Modell|nel modello|bevat het model|"
                                                    r"en el modelo|dans le modèle|numero di \w+ nel modello", q) \
        else "this sheet"


# ---------------------------------------------------------------- swiss gold (PDF vectors only)
def _sig(d):
    c = tuple(round(x, 2) for x in d["color"]) if d.get("color") else None
    f = tuple(round(x, 2) for x in d["fill"]) if d.get("fill") else None
    return c, f, round(d.get("width") or 0, 2)


def _win_groups(segs, D=6.0):
    n = len(segs)
    par = list(range(n))

    def f(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    info = []
    for a, b in segs:
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1e-9
        info.append((a, b, L, math.atan2(dy, dx) % math.pi, (dx / L, dy / L)))
    for i in range(n):
        a, b, L, ang, u = info[i]
        for j in range(i + 1, n):
            a2, b2, L2, ang2, _ = info[j]
            da = abs(ang - ang2)
            if min(da, math.pi - da) > 0.05 or abs(L - L2) > 0.1 * max(L, L2):
                continue
            vx = (a2[0] + b2[0] - a[0] - b[0]) / 2
            vy = (a2[1] + b2[1] - a[1] - b[1]) / 2
            if abs(vx * u[0] + vy * u[1]) < 0.15 * L and abs(-vx * u[1] + vy * u[0]) <= D:
                par[f(i)] = f(j)
    g = collections.defaultdict(list)
    for i in range(n):
        g[f(i)].append(i)
    out = []
    for v in g.values():
        if len(v) < 2:
            continue
        xs = [c for i in v for c in (segs[i][0][0], segs[i][1][0])]
        ys = [c for i in v for c in (segs[i][0][1], segs[i][1][1])]
        out.append([min(xs), min(ys), max(xs), max(ys)])
    return out


@functools.lru_cache(maxsize=512)
def swiss_page(pdf_path):
    import fitz
    pg = fitz.open(pdf_path)[0]
    W, H = pg.rect.width, pg.rect.height
    dr = pg.get_drawings()
    doors = [[d["rect"].x0 / W, d["rect"].y0 / H, d["rect"].x1 / W, d["rect"].y1 / H]
             for d in dr if _sig(d) == ((0.27, 0.27, 0.27), None, 0.37)]
    segs = [(tuple(d["items"][0][1]), tuple(d["items"][0][2])) for d in dr
            if _sig(d) == ((0.0, 0.0, 0.0), None, 0.37) and len(d["items"]) == 1 and d["items"][0][0] == "l"]
    wins = [[b[0] / W, b[1] / H, b[2] / W, b[3] / H] for b in _win_groups(segs)]
    return {"door": doors, "window": wins}


def swiss_gold(row):
    q = row["question"]
    if q.startswith(("How many doors", "Wie viele Türen")):
        t = "door"
    elif q.startswith(("How many windows", "Wie viele Fenster")):
        t = "window"
    else:
        return None, None
    return t, swiss_page(str(data_root() / row["path"]))[t]


# ---------------------------------------------------------------- driver
def score_row(row):
    pred = [e["bbox"] for e in row.get("evidence", []) if e.get("kind") == "box"]
    src = row["source"]
    if src == "cubicasa5k":
        t, gold = cc_gold(row)
        scope = "drawing"
    elif src == "ifc_models" and row["ext"] == "pdf":
        t, gold = ifc_gold(row)
        scope = ifc_scope(row["question"])
    elif src == "swiss_dwellings":
        t, gold = swiss_gold(row)
        scope = "drawing"
    else:
        return None
    if gold is None:
        return None
    try:
        g_off = round(float(row["gold"]))
    except (TypeError, ValueError):
        g_off = None
    out = {"id": row["id"], "source": src, "target": t, "scope": scope, "lang": row["lang"], "path": row["path"],
           "method": row["method"], "count_correct": bool(row["correct"]), "pred_answer": row["pred"],
           "official": g_off, "n_pred": len(pred), "n_gold": len(gold),
           "gold_consistent": g_off is not None and len(gold) == g_off}
    for rule in RULES:
        out[f"tp_{rule}"] = match(pred, gold, rule)
    if scope.startswith("model-wide"):  # answer covers the whole model; boxes only this sheet
        out["count_correct"] = bool(row["correct"])
    return out


def _work(rows):
    return [s for s in (score_row(r) for r in rows) if s is not None]


def agg(rows, rule):
    n = len(rows)
    np_ = sum(r["n_pred"] for r in rows)
    ng = sum(r["n_gold"] for r in rows)
    tp = sum(r[f"tp_{rule}"] for r in rows)
    boxed = [r for r in rows if r["n_pred"] > 0]

    def both(r):
        return r["count_correct"] and r[f"tp_{rule}"] == r["n_pred"] == r["n_gold"]

    def boxes_ok(r):
        return r[f"tp_{rule}"] == r["n_pred"] == r["n_gold"]
    return {
        "questions": n, "with_boxes": len(boxed), "pred_boxes": np_, "gold_instances": ng,
        "precision": round(tp / np_, 4) if np_ else None, "recall": round(tp / ng, 4) if ng else None,
        "count_correct": round(sum(r["count_correct"] for r in rows) / n, 4) if n else None,
        "boxes_exact": round(sum(boxes_ok(r) for r in rows) / n, 4) if n else None,
        "count_and_boxes_right": round(sum(both(r) for r in rows) / n, 4) if n else None,
        "of_count_right_boxes_right": round(sum(both(r) for r in rows) / max(1, sum(r["count_correct"] for r in rows)), 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/router_full_test_v7.jsonl")
    ap.add_argument("--out", default="analysis/out/evidence_hitrate.csv")
    ap.add_argument("--rows-out", default="runs/evidence_hitrate_rows.jsonl")
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(ROOT / a.run)]
    rows = [r for r in rows if r["type"] == "count" and r["source"] in ("cubicasa5k", "ifc_models", "swiss_dwellings")]
    # chunk by drawing so caches are reused
    by = collections.defaultdict(list)
    for r in rows:
        by[r["path"]].append(r)
    keys = sorted(by)
    chunks = [[r for k in keys[i::a.jobs * 4] for r in by[k]] for i in range(a.jobs * 4)]
    scored = []
    with ProcessPoolExecutor(a.jobs) as ex:
        for part in ex.map(_work, chunks):
            scored += part
    scored.sort(key=lambda r: r["id"])
    with open(ROOT / a.rows_out, "w") as f:
        for s in scored:
            f.write(json.dumps(s) + "\n")
    groups = collections.defaultdict(list)
    for s in scored:
        groups[(s["source"], s["scope"], s["target"])].append(s)
        groups[(s["source"], s["scope"], "ALL")].append(s)
    lines = []
    for (src, scope, t), g in sorted(groups.items()):
        for subset, gg in (("all", g), ("gold-consistent", [r for r in g if r["gold_consistent"]])):
            if not gg:
                continue
            for rule in RULES:
                lines.append({"source": src, "scope": scope, "target": t, "subset": subset, "match": rule,
                              **agg(gg, rule)})
    Path(ROOT / a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(ROOT / a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(lines[0]))
        w.writeheader()
        w.writerows(lines)
    print(f"scored {len(scored)} questions -> {a.out}, rows -> {a.rows_out}")
    for ln in lines:
        if ln["target"] == "ALL":
            print(ln)


if __name__ == "__main__":
    main()
