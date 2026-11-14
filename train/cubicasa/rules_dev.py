"""Tune wall-run counting rules (bp/cubicasa/counting.py select_runs) on DEV-val drawings from cached detections.

    .venv/bin/python train/cubicasa/rules_dev.py --dets cache/cubicasa/rules_dev/dets_v4_iou90.json --cls window

Gold count per drawing = the dev question answer (dev questions exist for most val drawings), else the
annotated box count. Prints exact-count accuracy per style for plain threshold counting and the best rules.
"""
import argparse
import collections
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bp.cubicasa.counting import select_runs  # noqa: E402
from bp.cubicasa.questions import target  # noqa: E402
from bp.data import load_questions  # noqa: E402
from count_errors import gold_boxes  # noqa: E402  (same folder)


def golds(stems, cls):
    q = {}
    for x in load_questions():
        if x["source"] == "cubicasa5k" and x["split"] == "dev" and target(x["question"]) == cls:
            q[Path(x["path"]).stem] = round(float(x["answer"]))
    return {s: (q[s], True) if s in q else (len(gold_boxes(s)[cls]), False) for s in stems}


def score(D, G, cls, mode, fn, only_q=False):
    ok, n, by = 0, 0, collections.defaultdict(lambda: [0, 0])
    for s, d in D.items():
        g, isq = G[s]
        if only_q and not isq:
            continue
        k = len(fn([x for x in d["dets"][mode] if x[0] == cls]))
        st = s.rsplit("-", 1)[0]
        by[st][0] += k == g
        by[st][1] += 1
        ok += k == g
        n += 1
    return ok / n, {k: f"{v[0]}/{v[1]}" for k, v in sorted(by.items())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets", required=True)
    ap.add_argument("--base", default="cache/cubicasa/rules_dev/dets_v4.json", help="iou 0.5 detections")
    ap.add_argument("--weights", default="cache/cubicasa/weights/best.pt")
    ap.add_argument("--cls", default="window")
    ap.add_argument("--modes", nargs="+", default=["1024", "1280"])
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    th = json.loads(Path(a.weights).with_name("thresholds.json").read_text())
    D = json.loads(Path(a.dets).read_text())
    B = json.loads(Path(a.base).read_text())
    G = golds(D, a.cls)
    print(f"{len(D)} drawings, {sum(v[1] for v in G.values())} with a dev question")
    t0 = th[a.cls]
    for md in a.modes:
        for t in (t0 - 0.05, t0, t0 + 0.05):
            print(f"base iou.5 {md} th {t:.3f}", *score(B, G, a.cls, md, lambda ds: [x for x in ds if x[1] >= t]))
    res = []
    for md in a.modes:
        for t_min, t_w, ovl, al in itertools.product([0.05, 0.1, 0.2], [0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45],
                                                     [0.1, 0.25, 0.5], [0.3, 0.5]):
            if t_min > t_w:
                continue
            acc, by = score(D, G, a.cls, md, lambda ds: select_runs(ds, t_min, t_w, ovl, al))
            res.append((acc, md, t_min, t_w, ovl, al, by))
    res.sort(key=lambda r: -r[0])
    for r in res[:a.top]:
        print(f"{r[0]:.3f} mode {r[1]} t_min {r[2]} t_w {r[3]} ovl {r[4]} align {r[5]} {r[6]}")


if __name__ == "__main__":
    main()
