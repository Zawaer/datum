"""Cache raw detections under test-time transforms (flips, rotations) on the dev-val drawings, for offline
fusion / counting experiments (train/cubicasa/tta_dev.py). Boxes are mapped back to the original image.

    .venv/bin/python train/cubicasa/tta_dump.py --weights cache/cubicasa/weights/best.pt --modes 1024 1280 \
        --tf id h v hv t --out cache/cubicasa/tta/v4.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
Image.MAX_IMAGE_PIXELS = None

# transform name -> (image op, inverse op on a normalised box [x0, y0, x1, y1] in transformed coords)
TF = {
    "id": (lambda a: a, lambda b: b),
    "h": (lambda a: a[:, ::-1], lambda b: [1 - b[2], b[1], 1 - b[0], b[3]]),
    "v": (lambda a: a[::-1], lambda b: [b[0], 1 - b[3], b[2], 1 - b[1]]),
    "hv": (lambda a: a[::-1, ::-1], lambda b: [1 - b[2], 1 - b[3], 1 - b[0], 1 - b[1]]),
    "t": (lambda a: a.transpose(1, 0, 2), lambda b: [b[1], b[0], b[3], b[2]]),  # transpose (x<->y)
    "r90": (lambda a: np.rot90(a, 1), lambda b: [1 - b[3], b[0], 1 - b[1], b[2]]),  # ccw rotation
}


def run(model, img, mode, tf, conf=0.05, iou=0.5):
    op, inv = TF[tf]
    a = np.ascontiguousarray(op(img))
    r = model.predict(a, imgsz=int(mode), conf=conf, iou=iou, verbose=False, max_det=600)[0]
    H, W = r.orig_shape
    out = []
    for b, c, s in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
        nb = inv([b[0] / W, b[1] / H, b[2] / W, b[3] / H])
        out.append((r.names[int(c)], round(float(s), 4), [round(v, 5) for v in nb]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="cache/cubicasa/weights/best.pt")
    ap.add_argument("--val-dir", default="cache/yolo_cc/images/val")
    ap.add_argument("--modes", nargs="+", default=["1024", "1280"])
    ap.add_argument("--tf", nargs="+", default=["id", "h", "v", "hv"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--device", default=None)
    a = ap.parse_args()
    from ultralytics import YOLO

    m = YOLO(a.weights)
    if a.device:
        m.to(a.device)
    out = Path(a.out)
    res = json.loads(out.read_text()) if out.exists() else {}
    imgs = sorted(Path(a.val_dir).glob("*.png"))
    t0 = time.time()
    for i, p in enumerate(imgs):
        img = np.asarray(Image.open(p).convert("RGB"))[:, :, ::-1]  # BGR like cv2
        d = res.setdefault(p.stem, {})
        for md in a.modes:
            for tf in a.tf:
                k = f"{md}_{tf}"
                if k not in d:
                    d[k] = run(m, img, md, tf)
        if i % 50 == 0:
            print(i, len(imgs), f"{time.time() - t0:.0f}s", flush=True)
            out.write_text(json.dumps(res))
    out.write_text(json.dumps(res))


if __name__ == "__main__":
    main()
