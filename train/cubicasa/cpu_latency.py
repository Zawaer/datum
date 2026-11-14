"""CPU latency of one detector config per drawing, as on the demo VM (4 vCPU): no GPU, N torch threads.
    CUDA_VISIBLE_DEVICES= .venv/bin/python train/cubicasa/cpu_latency.py --weights W.pt --mode f1280 --threads 4
"""
import argparse
import os
import statistics
import time
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--mode", default="f1280")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--n", type=int, default=12)
    a = ap.parse_args()
    import torch

    torch.set_num_threads(a.threads)
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from bp.cubicasa.infer import load, predict

    m = load(a.weights)
    imgs = sorted(Path("cache/yolo_cc/images/val").glob("*.png"))[: a.n + 1]
    predict(m, str(imgs[0]), a.mode)  # warm-up
    ts = []
    for p in imgs[1:]:
        t = time.time()
        predict(m, str(p), a.mode)
        ts.append(time.time() - t)
    print(f"{a.weights} mode={a.mode} threads={a.threads}: median {statistics.median(ts):.2f} s, "
          f"max {max(ts):.2f} s per drawing (n={len(ts)})")


if __name__ == "__main__":
    main()
