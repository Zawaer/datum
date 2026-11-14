"""Evaluate the VLM (zero-shot base or base+LoRA, local or remote) on held-out dev-val questions.

    python train/vlm/eval_vlm.py --n 100                                   # base model zero-shot, local
    BP_VLM_ADAPTER=cache/vlm/runs/x/final python train/vlm/eval_vlm.py --n 400
    BP_VLM_URL=http://host:8000/v1 python train/vlm/eval_vlm.py --n 1000    # vLLM server

Metrics: JSON parse rate, exact count accuracy (overall / per source / per target), mean |error|, and box
quality against the annotation boxes: precision / recall of predicted boxes whose centre falls in an
unmatched gold box (one-to-one, greedy), and the same at IoU >= 0.5.
Rows: cache/vlm/val.jsonl, sampled stratified by (source, target) with a fixed seed.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bp.data import split_of  # noqa: E402
from bp.vlm.format import parse_output  # noqa: E402


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


def match(pred, gold, how):
    used, tp = set(), 0
    for p in pred:
        best, bj = 0, None
        for j, g in enumerate(gold):
            if j in used:
                continue
            if how == "center":
                cx, cy = (p[0] + p[2]) / 2, (p[1] + p[3]) / 2
                s = 1.0 if g[0] <= cx <= g[2] and g[1] <= cy <= g[3] else 0.0
            else:
                s = iou(p, g) if iou(p, g) >= 0.5 else 0.0
            if s > best:
                best, bj = s, j
        if bj is not None:
            used.add(bj)
            tp += 1
    return tp


def sample(rows, n, seed):
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["source"], r["target"])].append(r)
    rng = random.Random(seed)
    for v in by.values():
        rng.shuffle(v)
    out, keys = [], sorted(by)
    while len(out) < n and any(by.values()):
        for k in keys:
            if by[k] and len(out) < n:
                out.append(by[k].pop())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "cache/vlm"))
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model", default=None, help="local base model (default env / adapter base)")
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--load-4bit", action="store_true")
    ap.add_argument("--device", default=None)
    ap.add_argument("--out", default=None, help="per-question results JSONL")
    ap.add_argument("--file", default="val.jsonl", help="rows file under --data")
    ap.add_argument("--allow-test", action="store_true",
                    help="inference-only run on held-out test rows (no gold boxes; never used for training)")
    ap.add_argument("--in-order", action="store_true", help="keep file order (no stratified sampling)")
    ap.add_argument("--shard", default="0/1", help="i/n: evaluate every n-th row starting at i")
    a = ap.parse_args()

    from bp.vlm.infer import LocalRunner, get_runner

    data = Path(a.data)
    rows = [json.loads(line) for line in open(data / a.file)]
    rows = rows[: a.n] if a.in_order else sample(rows, a.n, a.seed)
    si, sn = map(int, a.shard.split("/"))
    rows = rows[si::sn]
    if a.model or a.adapter or a.load_4bit or a.device:
        runner = LocalRunner(model=a.model, adapter=a.adapter, load_4bit=a.load_4bit or None, device=a.device)
    else:
        runner = get_runner()
    out = open(a.out, "w") if a.out else None
    res = []
    t0 = time.time()
    for i, r in enumerate(rows):
        assert a.allow_test or split_of(r["path"]) == "dev"
        img = Image.open(data / r["image"]).convert("RGB")
        try:
            o = runner.ask(img, r["question"], source=r["source"], prepared=True)
        except Exception as e:  # noqa: BLE001
            o = {"text": f"ERROR {e!r}", "parsed": parse_output(""), "confidence": None, "seconds": 0}
        p = o["parsed"]
        gold_items = [it["bbox_2d"] for it in json.loads(r["answer"])["items"]] if r.get("answer") else []
        gold = [[v / 1000 for v in b] for b in gold_items]
        pred = [b for _, b in p["items"]]
        n_pred = len(pred) if p["items"] or p["count"] is None else p["count"]
        rec = {"id": r["id"], "source": r["source"], "target": r["target"], "lang": r["lang"], "gold": r["gold"],
               "pred": n_pred, "ok": p["ok"], "n_boxes": len(pred), "conf": o["confidence"],
               "tp_center": match(pred, gold, "center"), "tp_iou": match(pred, gold, "iou"), "n_gold": len(gold),
               "seconds": o["seconds"], "text": o["text"][:2000]}
        res.append(rec)
        if out:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
        print(f"[{i + 1}/{len(rows)}] {r['source'][:5]}:{r['target']:<12} gold {r['gold']:>3} pred {n_pred:>3} "
              f"ok={p['ok']} conf={o['confidence'] if o['confidence'] is None else round(o['confidence'], 3)} "
              f"{o['seconds']}s", flush=True)
    summary = summarize(res)
    summary["wall_seconds"] = round(time.time() - t0, 1)
    summary["backend"] = getattr(runner, "backend", "?") + ":" + str(getattr(runner, "model_name", getattr(runner, "model", "")))
    print(json.dumps(summary, indent=1))
    if a.out:
        Path(a.out).with_suffix(".summary.json").write_text(json.dumps(summary, indent=1))


def summarize(res):
    def agg(rs):
        n = len(rs)
        tp_c, tp_i = sum(r["tp_center"] for r in rs), sum(r["tp_iou"] for r in rs)
        npred, ngold = sum(r["n_boxes"] for r in rs), sum(r["n_gold"] for r in rs)
        return {"n": n, "count_acc": round(sum(r["pred"] == r["gold"] for r in rs) / max(1, n), 3),
                "mae": round(sum(abs(r["pred"] - r["gold"]) for r in rs) / max(1, n), 2),
                "json_ok": round(sum(r["ok"] for r in rs) / max(1, n), 3),
                "box_P_center": round(tp_c / max(1, npred), 3), "box_R_center": round(tp_c / max(1, ngold), 3),
                "box_P_iou50": round(tp_i / max(1, npred), 3), "box_R_iou50": round(tp_i / max(1, ngold), 3),
                "sec_per_q": round(sum(r["seconds"] for r in rs) / max(1, n), 2)}

    s = {"all": agg(res)}
    for key in ("source", "target", "lang"):
        g = collections.defaultdict(list)
        for r in res:
            g[(r["source"][:5] + ":" + r[key]) if key == "target" else r[key]].append(r)
        s[f"by_{key}"] = {k: agg(v) for k, v in sorted(g.items())}
    return s


if __name__ == "__main__":
    main()
