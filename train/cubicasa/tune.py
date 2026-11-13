"""Pick a per-class score threshold that maximises exact-count accuracy on the YOLO validation drawings
(dev split only), and write it next to the weights as thresholds.json.

    .venv/bin/python train/cubicasa/tune.py --weights cache/cubicasa/runs/cc/weights/best.pt --imgsz 1024
"""
import argparse
import collections
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bp.cubicasa.classes import NAMES  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--data", default="cache/yolo_cc")
    ap.add_argument("--imgsz", type=int, default=1024)
    ap.add_argument("--out", help="thresholds.json path (default: next to weights)")
    a = ap.parse_args()
    from ultralytics import YOLO

    m = YOLO(a.weights)
    imgs = sorted((Path(a.data) / "images" / "val").glob("*.png"))
    preds, gold = {}, {}
    for i in range(0, len(imgs), 16):
        batch = imgs[i:i + 16]
        for p, r in zip(batch, m.predict([str(x) for x in batch], imgsz=a.imgsz, conf=0.05, iou=0.5,
                                         verbose=False, max_det=600)):
            preds[p.stem] = list(zip([r.names[int(c)] for c in r.boxes.cls.tolist()], r.boxes.conf.tolist()))
    for p in imgs:
        lab = (Path(a.data) / "labels" / "val" / f"{p.stem}.txt").read_text().split("\n")
        gold[p.stem] = collections.Counter(NAMES[int(x.split()[0])] for x in lab if x.strip())
    th = {"_imgsz": a.imgsz}
    report = []
    for c in NAMES:
        best = (-1, 0.5)
        for t in np.arange(0.1, 0.91, 0.025):
            acc = np.mean([sum(1 for n, s in preds[k] if n == c and s >= t) == gold[k][c] for k in preds])
            if acc > best[0] + 1e-9:
                best = (acc, float(round(t, 3)))
        th[c] = best[1]
        acc05 = np.mean([sum(1 for n, s in preds[k] if n == c and s >= 0.5) == gold[k][c] for k in preds])
        report.append(f"{c:12s} th={best[1]:.3f} exact-count acc={best[0]:.1%} (at 0.5: {acc05:.1%}) "
                      f"n_obj={sum(g[c] for g in gold.values())}")
    out = Path(a.out) if a.out else Path(a.weights).with_name("thresholds.json")
    out.write_text(json.dumps(th, indent=1))
    print(f"{len(imgs)} val images\n" + "\n".join(report) + f"\nwrote {out}")


if __name__ == "__main__":
    main()
