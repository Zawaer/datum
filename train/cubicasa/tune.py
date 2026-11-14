"""Pick, per class, the inference size and score threshold that maximise exact-count accuracy on the
YOLO validation drawings (dev split only), and write them next to the weights as thresholds.json.

    .venv/bin/python train/cubicasa/tune.py --weights cache/cubicasa/runs/cc/weights/best.pt --imgsz 1024 t1024

thresholds.json: {"_imgsz": default mode, "_cls_imgsz": {class: mode}, class: threshold, ...}
"""
import argparse
import collections
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bp.cubicasa.classes import NAMES  # noqa: E402


def predict_all(m, imgs, mode):
    from bp.cubicasa.infer import SYMBOLS, predict

    return {p.stem: [(n, s) for n, s, _ in predict(m, str(p), mode, tile_classes=SYMBOLS)] for p in imgs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--data", default="cache/yolo_cc")
    ap.add_argument("--imgsz", nargs="+", default=["1024"], help="modes: 1024, 1280, t1024 (tiled) ...")
    ap.add_argument("--out", help="thresholds.json path (default: next to weights)")
    a = ap.parse_args()
    from bp.cubicasa.infer import load

    m = load(a.weights)
    imgs = sorted((Path(a.data) / "images" / "val").glob("*.png"))
    gold = {}
    for p in imgs:
        lab = (Path(a.data) / "labels" / "val" / f"{p.stem}.txt").read_text().split("\n")
        gold[p.stem] = collections.Counter(NAMES[int(x.split()[0])] for x in lab if x.strip())
    preds = {sz: predict_all(m, imgs, sz) for sz in a.imgsz}

    def acc(pr, c, t):
        return float(np.mean([sum(1 for n, s in pr[k] if n == c and s >= t) == gold[k][c] for k in pr]))

    th = {"_imgsz": a.imgsz[0], "_cls_imgsz": {}}
    report = []
    for c in NAMES:
        best = (-1, 0.5, a.imgsz[0])
        per = []
        for sz in a.imgsz:
            b = max(((acc(preds[sz], c, t), -abs(t - 0.4), float(round(t, 3))) for t in np.arange(0.1, 0.91, 0.025)))
            per.append(f"{sz}:{b[0]:.1%}")
            if b[0] > best[0] + 1e-9:
                best = (b[0], b[2], sz)
        th[c] = best[1]
        th["_cls_imgsz"][c] = best[2]
        report.append(f"{c:12s} imgsz={best[2]} th={best[1]:.3f} exact-count acc={best[0]:.1%} [{' '.join(per)}] "
                      f"n_obj={sum(g[c] for g in gold.values())}")
    out = Path(a.out) if a.out else Path(a.weights).with_name("thresholds.json")
    out.write_text(json.dumps(th, indent=1))
    print(f"{len(imgs)} val images\n" + "\n".join(report) + f"\nwrote {out}")


if __name__ == "__main__":
    main()
