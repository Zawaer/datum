"""Choose the window-unit rule (train/cubicasa/window_units.py) on DEV-val drawings, from cached detections.

    .venv/bin/python train/cubicasa/units_dev.py --dets cache/cubicasa/rules_dev/dets_v4.json

Counted window boxes (tuned size and threshold, or a lower threshold) each add 1 + [P(>=2 units) > tau2]
+ [P(3 units) > tau3]. Prints exact-count accuracy per style for a grid of (threshold, tau2, tau3).
"""
import argparse
import collections
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rules_dev import golds  # noqa: E402  (same folder)
from window_units import unit_probs  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets", required=True)
    ap.add_argument("--weights", default="cache/cubicasa/weights/best.pt")
    ap.add_argument("--model", default="cache/cubicasa/window_units/model.pt")
    ap.add_argument("--val-dir", default="cache/yolo_cc/images/val")
    a = ap.parse_args()
    th = json.loads(Path(a.weights).with_name("thresholds.json").read_text())
    mode, t0 = th["_cls_imgsz"]["window"], th["window"]
    D = json.loads(Path(a.dets).read_text())
    G = golds(D, "window")
    P = {}
    for s, d in D.items():
        ds = [x for x in d["dets"][mode] if x[0] == "window" and x[1] >= 0.2]
        P[s] = [(x[1], p) for x, p in zip(ds, unit_probs(str(Path(a.val_dir) / f"{s}.png"), [x[2] for x in ds], a.model))]
    res = []
    for t, t2, t3 in itertools.product([t0 - 0.075, t0 - 0.05, t0 - 0.025, t0, t0 + 0.025, t0 + 0.05],
                                       [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01], [0.5, 0.7, 0.9, 1.01]):
        by, n = collections.Counter(), collections.Counter()
        for s, bs in P.items():
            k = sum(1 + (p[1] + p[2] > t2) + (p[2] > t3) for sc, p in bs if sc >= t)
            st = s.rsplit("-", 1)[0]
            by[st] += k == G[s][0]
            n[st] += 1
        res.append((sum(by.values()) / sum(n.values()), round(t, 3), t2, t3, {k: f"{by[k]}/{n[k]}" for k in sorted(n)}))
    base = [r for r in res if r[1] == round(t0, 3) and r[2] > 1 and r[3] > 1][0]
    print("baseline (no units):", base)
    for r in sorted(res, key=lambda r: -r[0])[:20]:
        print(r)


if __name__ == "__main__":
    main()
