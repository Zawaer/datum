"""Build the grounded-counting SFT dataset for the VLM (dev-split drawings only).

    .venv/bin/python train/vlm/build_dataset.py                    # everything -> cache/vlm/
    .venv/bin/python train/vlm/build_dataset.py --measure          # small-instance table per pixel budget
    .venv/bin/python train/vlm/build_dataset.py --overlays 6       # also draw targets on a few images

Sources
- cubicasa5k count questions (en + fi): per-instance boxes from the public CubiCasa5K SVG annotations
  (cache/cc5k/cubicasa5k/<folder>/<id>/model.svg), classified with the other agent's rules
  (bp/cubicasa/classes.py, checked against the gold answers by train/cubicasa/check_gold.py).
- swiss_dwellings count questions (en/de/fr/it) asked on the PDF, posed on the PNG twin (same A3 page at
  150 dpi, so normalised page coordinates are PNG coordinates): instances from the exact DXF parser via
  the Swiss solver's own evidence (bp.solvers.swiss), so labels and counts follow the solver's rules.

Consistency filter: an example is kept only if the number of annotated instances equals the gold answer.

Leakage: every drawing with bp.data.split_of(path) == "test" is skipped before anything is read, and
every written example is asserted to be dev. A fixed ~10 % of dev drawings (md5 of the stem, the same rule
as the YOLO validation split in train/cubicasa/make_yolo.py) is held out as val.jsonl.

Output (cache/vlm/): train.jsonl, val.jsonl, stats.json, img/<source>/<stem>.png (resized to the model's
pixel budget, see bp/vlm/format.py). Each line:
    {"id", "image": "img/...png", "question", "answer": <target JSON str>, "gold", "source", "target",
     "lang", "path", "n_items"}
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bp.cubicasa.classes import svg_class  # noqa: E402
from bp.cubicasa.questions import target as cc_target  # noqa: E402
from bp.data import data_root, load_questions, split_of  # noqa: E402
from bp.vlm.format import budget_for, prepare_image, target_json, target_size  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
CC_SRC = ROOT / "cache/cc5k/cubicasa5k"
OUT = ROOT / "cache/vlm"

# cubicasa question target -> (svg_class names counted, label shown per item)
CC_LABEL = {"window": "window", "door": "door", "toilet": "toilet", "sink": "sink", "shower": "shower",
            "bathtub": "bathtub", "sauna_room": "sauna", "sauna_stove": "sauna stove", "bedroom": "bedroom",
            "kitchen": "kitchen", "bathroom": "bathroom", "wc_room": "WC room", "balcony": "balcony",
            "floor": "floor"}
SYMBOLS = {"window", "door", "toilet", "sink", "shower", "bathtub", "sauna_stove", "washbasin"}


def is_val(stem: str) -> bool:
    """Same rule as train/cubicasa/make_yolo.py, so the VLM and YOLO validation drawings coincide."""
    return int(hashlib.md5(stem.encode()).hexdigest()[:8], 16) % 10 == 0


def lang_of(q: str) -> str:
    ql = q.lower()
    if any(w in ql for w in ("kuinka", "montako", "pohjapiirus")):
        return "fi"
    if any(w in ql for w in ("wie viele", "räume", "grundriss")):
        return "de"
    if any(w in ql for w in ("combien", "pièces", " plan ?")):
        return "fr"
    if any(w in ql for w in ("quant", "pianta", "locali")):
        return "it"
    return "en"


# ---------------------------------------------------------------- cubicasa ------------------------
def cc_objects(stem: str):
    """[(svg_class, normalised bbox)] for one CubiCasa drawing, in our PNG's frame (F1_original)."""
    assert split_of(f"data/cubicasa5k/{stem}.png") == "dev", stem  # leakage guard
    from bp.cubicasa.svg import parse

    folder, num = stem.rsplit("-", 1)
    d = CC_SRC / folder / num
    orig, scaled, svg = d / "F1_original.png", d / "F1_scaled.png", d / "model.svg"
    if not (orig.exists() and scaled.exists() and svg.exists()) or svg.stat().st_size == 0:
        return stem, None
    W, H = Image.open(orig).size
    sw, sh = Image.open(scaled).size
    sx, sy = W / sw, H / sh
    try:
        objs = parse(svg)["objects"]
    except Exception:  # noqa: BLE001
        return stem, None
    out = []
    for o in objs:
        c = svg_class(o)
        if c is None or o.get("bbox") is None:
            continue
        x0, y0, x1, y1 = o["bbox"]
        x0, x1 = max(0, x0 * sx), min(W, x1 * sx)
        y0, y1 = max(0, y0 * sy), min(H, y1 * sy)
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        out.append((c, [x0 / W, y0 / H, x1 / W, y1 / H]))
    return stem, out


def _inside(b, r, pad=0.01):
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return r[0] - pad <= cx <= r[2] + pad and r[1] - pad <= cy <= r[3] + pad


def cc_items(objs, t):
    """Items counted for question target t, following bp/cubicasa/classes.py + the solver's sauna rule."""
    from bp.cubicasa.classes import COUNTS

    kept = [(c, b) for c, b in objs if c in COUNTS[t]]
    if t == "sauna":
        rooms = [b for c, b in kept if c == "sauna_room"]
        kept = [(c, b) for c, b in kept if c == "sauna_room" or not any(_inside(b, r) for r in rooms)]
    return [(CC_LABEL[c], b) for c, b in kept]


# ---------------------------------------------------------------- swiss ---------------------------
def swiss_items(args):
    """All kept examples of one Swiss drawing: [(question dict, items)] plus per-drawing notes."""
    png, qs = args
    assert split_of(png) == "dev", png  # leakage guard
    from bp.solvers.swiss import SwissSolver

    s = SwissSolver()
    out, notes = [], collections.Counter()
    try:
        fl = s.floor_for({"path": png})
    except Exception:  # noqa: BLE001
        return png, [], {"parse_error": len(qs)}
    if fl is None or not fl.to_page:
        return png, [], {"no_page_mapping": len(qs)}
    if fl.fit_rms is not None and fl.fit_rms > 0.004:
        return png, [], {"loose_page_mapping": len(qs)}
    letters = sorted(fl.units)
    for q in qs:
        r = s({**q, "path": png})
        if r.get("answer") is None:
            notes["unanswered"] += 1
            continue
        if r["answer"] != round(float(q["answer"])):
            notes["solver!=gold"] += 1
            continue
        items = []
        for e in r["evidence"]:
            if e["kind"] == "box":
                lab = e["label"].rsplit(" ", 1)[0]
                if lab == "apartment":
                    lab = f"apartment {letters[len(items)]}" if len(items) < len(letters) else lab
                items.append((lab, e["bbox"]))
            elif e["kind"] == "polygon":
                p = np.asarray(e["points"])
                lab = e["label"].split(": ", 1)[-1]
                items.append((lab, [p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()]))
        if len(items) != r["answer"]:
            notes["evidence!=answer"] += 1
            continue
        out.append((q, items))
    return png, out, dict(notes)


# ---------------------------------------------------------------- images --------------------------
def save_image(args):
    src, dst, budget = args
    dst = Path(dst)
    if dst.exists():
        return str(dst), Image.open(dst).size
    dst.parent.mkdir(parents=True, exist_ok=True)
    img = prepare_image(Image.open(src), budget)
    tmp = dst.with_suffix(".tmp.png")
    img.save(tmp, optimize=False, compress_level=3)
    tmp.rename(dst)
    return str(dst), img.size


def overlay(ex, out_dir, base=OUT):
    img = Image.open(base / ex["image"]).convert("RGB")
    W, H = img.size
    d = ImageDraw.Draw(img)
    for i, it in enumerate(json.loads(ex["answer"])["items"], 1):
        x0, y0, x1, y1 = (v / 1000 for v in it["bbox_2d"])
        d.rectangle([x0 * W, y0 * H, x1 * W, y1 * H], outline=(230, 0, 0), width=2)
        d.text((x0 * W + 2, y0 * H + 1), f"{i} {it['label']}", fill=(0, 0, 200))
    d.text((5, 5), f"{ex['question'][:110]}  gold={ex['gold']}", fill=(0, 130, 0))
    f = out_dir / f"{ex['source']}_{ex['target']}_{Path(ex['image']).stem}.png"
    img.save(f)
    return f


# ---------------------------------------------------------------- main ----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-items", type=int, default=120, help="drop examples with more instances (reply length)")
    ap.add_argument("--no-swiss", action="store_true")
    ap.add_argument("--limit-drawings", type=int, default=0, help="debug: only the first N drawings per source")
    ap.add_argument("--measure", action="store_true", help="print the small-instance table and exit")
    ap.add_argument("--overlays", type=int, default=0, help="draw targets on N random examples per source")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    root = data_root()

    qs = [q for q in load_questions() if q["type"] == "count" and q["source"] in ("cubicasa5k", "swiss_dwellings")]
    n_test = sum(q["split"] == "test" for q in qs)
    qs = [q for q in qs if q["split"] == "dev"]  # leakage rule: test drawings never read
    stats = {"skipped_test_questions": n_test, "sources": {}}
    examples = []
    cc_objs = {}

    # -- cubicasa
    cc_q = collections.defaultdict(list)
    for q in qs:
        if q["source"] == "cubicasa5k":
            cc_q[Path(q["path"]).stem].append(q)
    stems = sorted(cc_q)[: a.limit_drawings or None]
    cache_f = out / "cc_objects.json"
    if cache_f.exists():
        cc_objs = json.loads(cache_f.read_text())
    todo = [s for s in stems if s not in cc_objs]
    if todo:
        with ProcessPoolExecutor(a.workers) as ex:
            for stem, objs in ex.map(cc_objects, todo, chunksize=16):
                cc_objs[stem] = objs
        cache_f.write_text(json.dumps(cc_objs))
    st = collections.Counter()
    for stem in stems:
        objs = cc_objs.get(stem)
        for q in cc_q[stem]:
            st["questions"] += 1
            t = cc_target(q["question"])
            if objs is None:
                st["no_annotation"] += 1
                continue
            if t is None:
                st["template_unknown"] += 1
                continue
            items = cc_items([(c, b) for c, b in objs], t)
            if len(items) != round(float(q["answer"])):
                st["annotation!=gold"] += 1
                st[f"mismatch:{t}"] += 1
                continue
            examples.append((q, t, items))
            st["kept"] += 1
    stats["sources"]["cubicasa5k"] = dict(st)

    # -- swiss
    if not a.no_swiss:
        sw_q = collections.defaultdict(list)
        for q in qs:
            if q["source"] == "swiss_dwellings":
                png = str(Path(q["path"]).with_suffix(".png"))
                if (root / png).exists():
                    sw_q[png].append(q)
        pngs = sorted(sw_q)[: a.limit_drawings or None]
        st = collections.Counter(questions=sum(len(sw_q[p]) for p in pngs),
                                 questions_without_png=sum(q["source"] == "swiss_dwellings" for q in qs)
                                 - sum(len(v) for v in sw_q.values()))
        from bp.solvers.swiss import parse_question

        with ProcessPoolExecutor(a.workers) as ex:
            for png, kept, notes in ex.map(swiss_items, [(p, sw_q[p]) for p in pngs], chunksize=2):
                st.update(notes)
                for q, items in kept:
                    intent = parse_question(q["question"], "count")
                    t = intent[1] if intent[0] == "count_symbol" else "room_label"
                    examples.append(({**q, "path": png}, t, items))
                    st["kept"] += 1
        stats["sources"]["swiss_dwellings"] = dict(st)

    # -- measure small instances at candidate budgets
    if a.measure:
        measure(examples, root)
        return

    # -- images
    jobs = {}
    for q, t, items in examples:
        src = q["source"]
        dst = out / "img" / src / (Path(q["path"]).stem + ".png")
        jobs[q["path"]] = (str(root / q["path"]), str(dst), budget_for(src))
    sizes = {}
    with ProcessPoolExecutor(a.workers) as ex:
        for (path, job), (dst, size) in zip(jobs.items(), ex.map(save_image, jobs.values(), chunksize=8)):
            sizes[path] = size

    # -- write
    n_dropped_long = 0
    rows = {"train": [], "val": []}
    for q, t, items in examples:
        assert split_of(q["path"]) == "dev", q["path"]  # leakage rule
        if len(items) > a.max_items:
            n_dropped_long += 1
            continue
        stem = Path(q["path"]).stem
        row = {"id": q["id"], "image": f"img/{q['source']}/{stem}.png", "question": q["question"],
               "answer": target_json(items), "gold": round(float(q["answer"])), "source": q["source"],
               "target": t, "lang": lang_of(q["question"]), "path": q["path"], "n_items": len(items),
               "image_size": sizes[q["path"]]}
        rows["val" if is_val(stem) else "train"].append(row)
    rng = np.random.default_rng(0)
    for part, rs in rows.items():
        rng.shuffle(rs)
        with open(out / f"{part}.jsonl", "w") as f:
            for r in rs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # -- stats
    def tab(rs, key):
        return dict(sorted(collections.Counter(key(r) for r in rs).items(), key=lambda kv: -kv[1]))

    stats["dropped_too_many_items"] = n_dropped_long
    for part, rs in rows.items():
        vis = sum(r["image_size"][0] * r["image_size"][1] / 1024 for r in rs)
        ans = sum(len(r["answer"]) / 3.2 for r in rs)  # ~3.2 chars per token for this JSON (measured)
        stats[part] = {"examples": len(rs), "drawings": len({r["path"] for r in rs}),
                       "by_source": tab(rs, lambda r: r["source"]), "by_lang": tab(rs, lambda r: r["lang"]),
                       "by_target": tab(rs, lambda r: f"{r['source'][:5]}:{r['target']}"),
                       "visual_tokens_mean": round(vis / max(1, len(rs))),
                       "answer_tokens_mean_est": round(ans / max(1, len(rs))),
                       "items_mean": round(sum(r["n_items"] for r in rs) / max(1, len(rs)), 2)}
    for s, d in stats["sources"].items():
        d["survival"] = round(d.get("kept", 0) / max(1, d["questions"]), 4)
    (out / "stats.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False))
    print(json.dumps(stats, indent=1, ensure_ascii=False))

    if a.overlays:
        od = out / "overlays"
        od.mkdir(exist_ok=True)
        allr = rows["train"] + rows["val"]
        for src in ("cubicasa5k", "swiss_dwellings"):
            rs = [r for r in allr if r["source"] == src and r["n_items"] > 0]
            for i in rng.choice(len(rs), min(a.overlays, len(rs)), replace=False) if rs else []:
                print("overlay", overlay(rs[i], od, out))


def measure(examples, root):
    """Fraction of symbol instances whose shorter box side falls under N px after the resize."""
    budgets = [(m, b) for m in (256 ** 2, 1024 ** 2) for b in (1024 ** 2, 1280 ** 2, 1536 ** 2, 1792 ** 2, 2048 ** 2)]
    seen = set()
    by_src = collections.defaultdict(list)  # (src) -> [(w_px_native, h_px_native, W, H)]
    for q, t, items in examples:
        key = (q["path"], t)
        if key in seen:
            continue
        seen.add(key)
        W, H = Image.open(root / q["path"]).size
        for lab, b in items:
            if lab.split(" ")[0] in SYMBOLS or lab in ("sauna stove",):
                by_src[q["source"]].append(((b[2] - b[0]) * W, (b[3] - b[1]) * H, W, H))
    for src, rows in by_src.items():
        a = np.asarray(rows)
        print(f"\n{src}: {len(a)} symbol instances; native size median "
              f"{np.median(np.sqrt(a[:, 0] * a[:, 1])):.0f} px")
        print(f"{'min':>6} {'max':>6} {'vis.tok':>8} " + " ".join(f"<{n:>2}px" for n in (8, 12, 16, 24)))
        for mn, bud in budgets:
            s = []
            toks = []
            for w, h, W, H in a:
                tw, th = target_size(int(W), int(H), bud, min_pixels=mn)
                s.append(np.sqrt(w * tw / W * h * th / H))
                toks.append(tw * th / 1024)
            s = np.asarray(s)
            print(f"{int(mn ** 0.5):>4}^2 {int(bud ** 0.5):>4}^2 {np.mean(toks):>8.0f} " +
                  " ".join(f"{np.mean(s < n):6.1%}" for n in (8, 12, 16, 24)))


if __name__ == "__main__":
    main()
