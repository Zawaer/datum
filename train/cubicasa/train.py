"""Fine-tune a YOLO11 detector on the CubiCasa5k labels built by make_yolo.py.

    .venv/bin/python train/cubicasa/train.py --model yolo11s.pt --imgsz 1024 --epochs 60 --name cc_s1024
"""
import argparse
import os
from pathlib import Path

import numpy as np
import torch
from multiprocessing.reduction import ForkingPickler
from ultralytics import YOLO


def _tensor_by_value(t):
    return torch.from_numpy, (np.ascontiguousarray(t.numpy()),)


# Docker's default /dev/shm is 64 MB, too small for torch's shared-memory tensor passing between
# dataloader workers. Send batches through the worker pipe by value instead.
if os.path.getsize("/dev/shm") is not None and os.statvfs("/dev/shm").f_blocks * os.statvfs("/dev/shm").f_frsize < 1 << 30:
    ForkingPickler.register(torch.Tensor, _tensor_by_value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="cache/yolo_cc/data.yaml")
    ap.add_argument("--model", default="yolo11s.pt", help="name or path; resolved inside cache/cubicasa")
    ap.add_argument("--imgsz", type=int, default=1024)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--name", default="cc")
    a = ap.parse_args()
    root = Path(__file__).resolve().parents[2]
    data = str(Path(a.data).resolve())
    work = root / "cache" / "cubicasa"
    work.mkdir(parents=True, exist_ok=True)
    os.chdir(work)  # ultralytics drops helper downloads (AMP check weights) in the cwd
    m = YOLO(a.model if Path(a.model).exists() else a.model)
    m.train(data=data, imgsz=a.imgsz, epochs=a.epochs, batch=a.batch, workers=a.workers,
            project=str(work / "runs"), name=a.name, exist_ok=True, cache=False,
            # plans come in any orientation (some upside down, text rotated): flip both ways
            fliplr=0.5, flipud=0.5, degrees=0.0, mosaic=1.0, close_mosaic=10, scale=0.5,
            max_det=600, patience=20, plots=True, amp=True)


if __name__ == "__main__":
    main()
