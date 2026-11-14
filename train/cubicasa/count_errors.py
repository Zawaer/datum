"""Window/door count error analysis on DEV-val drawings (cached detections vs. annotated boxes).

    .venv/bin/python train/cubicasa/count_errors.py --dets cache/cubicasa/rules_dev/dets_v4.json [--cls window]

For every drawing: kept detections (tuned threshold, tuned size) are matched one-to-one to gold boxes
(YOLO labels made from the SVG). Each count error is explained by: split (two of our boxes inside one gold
box), merge (one of our boxes covering 2+ gold boxes), fp (unmatched box), fn (unmatched gold), per style.
"""
import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bp.cubicasa.classes import NAMES  # noqa: E402


def gold_boxes(stem, data="cache/yolo_cc"):
    out = collections.defaultdict(list)
    for ln in (Path(data) / "labels" / "val" / f"{stem}.txt").read_text().split("\n"):
        if ln.strip():
            c, x, y, w, h = ln.split()[:5]
            x, y, w, h = map(float, (x, y, w, h))
            out[NAMES[int(c)]].append([x - w / 2, y - h / 2, x + w / 2, y + h / 2])
    return out


def inter(a, b):
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    return iw * ih if iw > 0 and ih > 0 else 0.0


def area(a):
    return max(1e-12, (a[2] - a[0]) * (a[3] - a[1]))


def iou(a, b):
    i = inter(a, b)
    return i / (area(a) + area(b) - i)


def centre_in(a, b):
    cx, cy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    return b[0] <= cx <= b[2] and b[1] <= cy <= b[3]


def match(pred, gold):
    """Greedy one-to-one by IoU, then by either-centre. Returns (pairs, unmatched pred idx, unmatched gold idx)."""
    cand = []
    for i, p in enumerate(pred):
        for j, g in enumerate(gold):
            v = iou(p, g)
            if v > 0.3 or centre_in(p, g) or centre_in(g, p):
                cand.append((-(v + (0.5 if centre_in(p, g) else 0)), i, j))
    cand.sort()
    up, ug, pairs = set(range(len(pred))), set(range(len(gold))), []
    for _, i, j in cand:
        if i in up and j in ug:
            up.discard(i)
            ug.discard(j)
            pairs.append((i, j))
    return pairs, up, ug


def explain(pred, gold):
    pairs, up, ug = match(pred, gold)
    cat = collections.Counter()
    for i in up:  # extra box of ours
        p = pred[i]
        hits = [j for j in range(len(gold)) if inter(p, gold[j]) > 0.3 * area(p)]
        cat["split" if hits else "fp"] += 1
    for j in ug:
        g = gold[j]
        hits = [i for i in range(len(pred)) if inter(pred[i], g) > 0.3 * area(g)]
        cat["merge" if hits else "fn"] += 1
    return cat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets", required=True)
    ap.add_argument("--weights", default="cache/cubicasa/weights/best.pt")
    ap.add_argument("--cls", nargs="+", default=["window", "door"])
    a = ap.parse_args()
    th = json.loads(Path(a.weights).with_name("thresholds.json").read_text())
    D = json.loads(Path(a.dets).read_text())
    for c in a.cls:
        mode = th["_cls_imgsz"][c]
        tot, right, cats = collections.Counter(), collections.Counter(), collections.Counter()
        err = collections.Counter()
        for stem, d in sorted(D.items()):
            st = stem.rsplit("-", 1)[0]
            pred = [b for n, s, b in d["dets"][mode] if n == c and s >= th[c]]
            gold = gold_boxes(stem)[c]
            tot[st] += 1
            ok = len(pred) == len(gold)
            right[st] += ok
            e = explain(pred, gold)
            cats.update(e)
            if not ok:
                err[st] += 1
                key = "+".join(sorted(k for k in e)) or "?"
                cats["img:" + key] += 1
        print(f"== {c} mode {mode} th {th[c]}")
        for st in tot:
            print(f"  {st:28s} {right[st]}/{tot[st]} = {right[st] / tot[st]:.1%}")
        print("  totals", sum(right.values()), "/", sum(tot.values()))
        print("  instance-level", {k: v for k, v in cats.items() if not k.startswith("img:")})
        print("  wrong images by error mix", sorted(((v, k) for k, v in cats.items() if k.startswith("img:")), reverse=True))


if __name__ == "__main__":
    main()


def render(stem, pred, gold, out, data="cache/yolo_cc", crop=None):
    """Overlay: gold green, ours red (score), saved downscaled to <= 1600 px."""
    from PIL import Image, ImageDraw

    im = Image.open(Path(data) / "images" / "val" / f"{stem}.png").convert("RGB")
    W, H = im.size
    dr = ImageDraw.Draw(im)
    lw = max(2, W // 800)
    for k, g in enumerate(gold):  # gold: inset, alternating green / blue so adjacent instances are visible
        dr.rectangle([g[0] * W + 1, g[1] * H + 1, g[2] * W - 1, g[3] * H - 1], outline=[(0, 180, 0), (0, 90, 255)][k % 2],
                     width=lw)
    for s, b in pred:  # ours: outset, red, score below
        dr.rectangle([b[0] * W - 4, b[1] * H - 4, b[2] * W + 4, b[3] * H + 4], outline=(230, 0, 0), width=1)
        dr.text((b[0] * W, b[3] * H + 5), f"{s:.2f}", fill=(230, 0, 0))
    if crop:
        im = im.crop([int(crop[0] * W), int(crop[1] * H), int(crop[2] * W), int(crop[3] * H)])
    sc = 1600 / max(im.size)
    im = im.resize((int(im.size[0] * sc), int(im.size[1] * sc)))
    im.save(out)
