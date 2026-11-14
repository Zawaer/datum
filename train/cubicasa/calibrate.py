"""Calibrate detection scores and pick a counting rule per question template, on DEV data only.

    .venv/bin/python train/cubicasa/calibrate.py --weights cache/cubicasa/weights/best.pt

1. On the YOLO validation drawings (dev split, never trained on), match detections to annotated boxes
   and fit p(real | score) = sigmoid(a + b logit(score)) per class, plus the mean number of annotated
   objects with no detection at all (lambda, the Poisson miss rate).
2. Template answer distributions ("priors") from dev questions on the TRAINING drawings.
3. For each template, choose among: threshold counting, posterior mode with prior weight w in
   {0, 0.5, 1}, by exact-count accuracy on the dev questions of the validation drawings.
Writes calib.json next to the weights.
"""
import argparse
import collections
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bp.cubicasa.classes import COUNTS, NAMES  # noqa: E402
from bp.cubicasa.questions import target  # noqa: E402
from bp.data import load_questions  # noqa: E402
from bp.solvers.cubicasa import CubicasaSolver  # noqa: E402


def iou(a, b):
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    i = iw * ih
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i)


def fit_logistic(scores, ys, iters=3000, lr=0.5):
    if len(set(ys)) < 2:
        return [0.0, 1.0]
    x = np.log(np.clip(scores, 1e-4, 1 - 1e-4) / (1 - np.clip(scores, 1e-4, 1 - 1e-4)))
    y = np.asarray(ys, float)
    a, b = 0.0, 1.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(a + b * x)))
        g = p - y
        a -= lr * g.mean()
        b -= lr * (g * x).mean()
    return [float(a), float(b)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="cache/cubicasa/weights/best.pt")
    ap.add_argument("--data", default="cache/yolo_cc")
    ap.add_argument("--prior-exclude", default=None,
                    help="also keep these drawings' questions out of the priors (a val dir; for fold-wise CV on a subset)")
    a = ap.parse_args()
    out = Path(a.weights).with_name("calib.json")
    if out.exists():
        out.unlink()  # start from threshold rules
    s = CubicasaSolver(weights=a.weights)
    val = sorted((Path(a.data) / "images" / "val").glob("*.png"))
    vstems = {p.stem for p in val}
    xstems = {p.stem for p in Path(a.prior_exclude).glob("*.png")} if a.prior_exclude else set()

    # 1. per-class calibration
    sc, ys, miss = collections.defaultdict(list), collections.defaultdict(list), collections.Counter()
    dets_by = {}
    for p in val:
        gt = collections.defaultdict(list)
        for line in (Path(a.data) / "labels" / "val" / f"{p.stem}.txt").read_text().split("\n"):
            if line.strip():
                c, x, y, w, h = line.split()
                x, y, w, h = map(float, (x, y, w, h))
                gt[NAMES[int(c)]].append([x - w / 2, y - h / 2, x + w / 2, y + h / 2])
        dets_by[p.stem] = s.detections(str(p.resolve()), NAMES)
        for c in NAMES:
            ds = sorted((d for d in dets_by[p.stem] if d[0] == c), key=lambda d: -d[1])
            used = set()
            for d in ds:
                best, bj = 0.0, None
                for j, g in enumerate(gt[c]):
                    if j not in used and iou(d[2], g) > best:
                        best, bj = iou(d[2], g), j
                ok = best >= 0.4
                if ok:
                    used.add(bj)
                sc[c].append(d[1])
                ys[c].append(int(ok))
            miss[c] += len(gt[c]) - len(used)
    classes = {}
    for c in NAMES:
        classes[c] = {"ab": fit_logistic(np.array(sc[c]), ys[c]), "lam": miss[c] / len(val)}
        print(f"{c:12s} dets={len(sc[c])} tp={sum(ys[c])} ab={classes[c]['ab'][0]:.2f},{classes[c]['ab'][1]:.2f} "
              f"lam={classes[c]['lam']:.3f}")

    # 2. priors from dev questions on training drawings (English twin only, one per drawing+template)
    qs = [q for q in load_questions() if q["source"] == "cubicasa5k" and q["split"] == "dev"]
    pri = collections.defaultdict(collections.Counter)
    for q in qs:
        if Path(q["path"]).stem not in vstems | xstems and q["question"].startswith("How"):
            pri[target(q["question"])][str(round(float(q["answer"])))] += 1
    priors = {t: {k: v / sum(c.values()) for k, v in c.items()} for t, c in pri.items()}

    # 3. rule per template on dev questions of validation drawings
    s.calib = {"classes": classes, "priors": priors, "templates": {}}
    vq = [q for q in qs if Path(q["path"]).stem in vstems and q["question"].startswith("How")]
    rules = ([{"method": "threshold", "w": w} for w in (0.0, 0.5, 1.0)]
             + [{"method": "posterior", "w": w} for w in (0.0, 0.5, 1.0)] + [{"method": "prior", "w": 1.0}])
    templates, lines = {}, []
    for t in COUNTS:
        tq = [q for q in vq if target(q["question"]) == t]
        res = []
        for r in rules:
            outs = [s.decide(t, [d for d in dets_by[Path(q["path"]).stem] if d[0] in COUNTS[t]], r) for q in tq]
            acc = np.mean([o[0] == round(float(q["answer"])) for o, q in zip(outs, tq)])
            hi = [(o, q) for o, q in zip(outs, tq) if o[1] >= 0.95]
            hacc = np.mean([o[0] == round(float(q["answer"])) for o, q in hi]) if hi else float("nan")
            brier = np.mean([(o[1] - (o[0] == round(float(q["answer"])))) ** 2 for o, q in zip(outs, tq)])
            res.append((acc, r, len(hi) / max(1, len(tq)), hacc, brier))
        # answer rule: keep plain threshold counting unless another rule is clearly better (>= 1.5 pt)
        thr = res[0][0]
        best_ans = max(res, key=lambda x: x[0])
        method = best_ans[1]["method"] if best_ans[0] >= thr + 0.015 else "threshold"
        # confidence: the prior weight whose confidences are best calibrated (Brier score) for that rule
        cands = [x for x in res if x[1]["method"] == method] if method != "prior" else [x for x in res if x[1]["method"] == "prior"]
        best = min(cands, key=lambda x: x[4])
        templates[t] = best[1]
        lines.append(f"{t:12s} n={len(tq)} " + "  ".join(
            f"{r['method'][:4]}{r.get('w', '')}={acc:.1%} (B{br:.3f}, c>=.95 {cov:.0%} at {hacc:.0%})"
            for acc, r, cov, hacc, br in res) + f"  -> {best[1]}")
    out.write_text(json.dumps({"classes": classes, "priors": priors, "templates": templates}, indent=1))
    print("\n".join(lines) + f"\nwrote {out}")


if __name__ == "__main__":
    main()
