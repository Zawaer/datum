"""Check a live VLM server against the precomputed second opinion (same drawings, same questions).

    BP_VLM_URL=... BP_VLM_KEY=... .venv/bin/python deploy/vlm/check.py [--n 3] [--file cache/vlm/demo_secondopinion.jsonl]

Picks n test-split CubiCasa questions (spread over targets) from the precomputed file, asks each live through
bp.vlm.live (the demo's client, cache bypassed) and prints: precomputed vs live count, mean box IoU of the
matched boxes, confidence, latency. Greedy decoding on the same weights should give the same count and
near-identical boxes; small drift is expected across vLLM versions / GPUs (bf16 kernels differ).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--file", default="cache/vlm/demo_secondopinion.jsonl")
    a = ap.parse_args()
    from bp.cubicasa.questions import target
    from bp.data import data_root
    from bp.vlm import live

    print("health:", live.health())
    rows, seen = [], set()
    for line in open(a.file, encoding="utf-8"):
        r = json.loads(line)
        v = r.get("vlm") or {}
        t = target(r["question"])
        if r.get("split") == "test" and v.get("answer") is not None and r["question"].isascii() \
                and t not in {x[0] for x in seen} and r["path"] not in {x[1] for x in seen}:
            seen.add((t, r["path"]))
            rows.append(r)
        if len(rows) >= a.n:
            break
    lat, same = [], 0
    for r in rows:
        live._cache.clear()
        t0 = time.time()
        res = live.live_second_opinion(data_root() / r["path"], r["question"], file=r["path"])
        dt = time.time() - t0
        pre = r["vlm"]
        if res is None:
            print(f"{r['path']}  {target(r['question'])}: NO ANSWER ({live.last_error})")
            continue
        lat.append(dt)
        pb = [e["bbox"] for e in pre["evidence"]]
        lb = [e["bbox"] for e in res["evidence"]]
        ious = [max((iou(b, c) for c in lb), default=0.0) for b in pb]
        same += res["answer"] == pre["answer"]
        print(f"{r['path']}  {target(r['question'])}: precomputed {pre['answer']} (conf {pre['confidence']}) | "
              f"live {res['answer']} (conf {res['confidence']}) | box IoU mean "
              f"{statistics.mean(ious) if ious else 1.0:.3f} | {dt:.2f} s")
    if lat:
        print(f"same count {same}/{len(rows)}; latency mean {statistics.mean(lat):.2f} s, max {max(lat):.2f} s "
              f"(server {os.environ.get('BP_VLM_URL')})")


if __name__ == "__main__":
    main()
