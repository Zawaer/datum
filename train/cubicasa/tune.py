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

    return {p.stem: [(n, s, b) for n, s, b in predict(m, str(p), mode, tile_classes=SYMBOLS)] for p in imgs}


def tune_on_questions(preds, stems, th):
    """Per template, the inference size and per-class threshold(s) that maximise exact-count accuracy on the dev
    questions of these drawings (same counting as the solver's threshold rule, incl. the sauna rule)."""
    from bp.cubicasa.classes import COUNTS
    from bp.cubicasa.questions import target
    from bp.data import load_questions

    qs = collections.defaultdict(list)
    for q in load_questions():
        st = Path(q["path"]).stem
        if q["source"] == "cubicasa5k" and q["split"] == "dev" and st in stems and (t := target(q["question"])):
            qs[t].append((st, round(float(q["answer"]))))
    grid = [float(round(t, 3)) for t in np.arange(0.1, 0.91, 0.025)]

    def count(ds, t, tt):
        if t == "sauna":
            rooms = [d[2] for d in ds if d[0] == "sauna_room" and d[1] >= tt["sauna_room"]]
            ds = [d for d in ds if d[0] == "sauna_room" or not any(
                r[0] - .01 <= (d[2][0] + d[2][2]) / 2 <= r[2] + .01 and r[1] - .01 <= (d[2][1] + d[2][3]) / 2 <= r[3] + .01
                for r in rooms)]
        return sum(1 for d in ds if d[0] in tt and d[1] >= tt[d[0]])

    report = []
    for t, cs in COUNTS.items():
        cands = [{cs[0]: x} for x in grid] if len(cs) == 1 else [{cs[0]: x, cs[1]: y} for x in grid[::2] for y in grid[::2]]
        best = None
        for sz, pr in preds.items():
            for tt in cands:
                acc = float(np.mean([count([d for d in pr[st] if d[0] in cs], t, tt) == g for st, g in qs[t]]))
                key = (acc, -sum(abs(v - 0.4) for v in tt.values()))
                if best is None or key > best[0]:
                    best = (key, sz, tt)
        (acc, _), sz, tt = best
        for c, v in tt.items():
            th[c] = v
            th["_cls_imgsz"][c] = sz
        report.append(f"{t:12s} imgsz={sz} th={tt} dev-question acc={acc:.1%} (n={len(qs[t])})")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--data", default="cache/yolo_cc")
    ap.add_argument("--imgsz", nargs="+", default=["1024"], help="modes: 1024, 1280, t1024 (tiled) ...")
    ap.add_argument("--out", help="thresholds.json path (default: next to weights)")
    ap.add_argument("--target", choices=["labels", "questions"], default="labels",
                    help="maximise exact counts of annotated boxes per class (default), or the dev questions' answers "
                         "per template (classes no template counts keep the label-tuned values)")
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
        return float(np.mean([sum(1 for n, s, _ in pr[k] if n == c and s >= t) == gold[k][c] for k in pr]))

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
    if a.target == "questions":
        report += tune_on_questions(preds, {p.stem for p in imgs}, th)
    out = Path(a.out) if a.out else Path(a.weights).with_name("thresholds.json")
    out.write_text(json.dumps(th, indent=1))
    print(f"{len(imgs)} val images\n" + "\n".join(report) + f"\nwrote {out}")


if __name__ == "__main__":
    main()
