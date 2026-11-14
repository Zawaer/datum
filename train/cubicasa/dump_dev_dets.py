"""Cache raw detections (conf >= 0.05, every class) on the dev-val drawings, for offline counting-rule work.

    CUDA_VISIBLE_DEVICES= .venv/bin/python train/cubicasa/dump_dev_dets.py --weights cache/cubicasa/weights/best.pt \
        --modes 1024 1280 --out cache/cubicasa/rules_dev/dets_v4.json
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="cache/cubicasa/weights/best.pt")
    ap.add_argument("--val-dir", default="cache/yolo_cc/images/val")
    ap.add_argument("--modes", nargs="+", default=["1024", "1280"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--iou", type=float, default=0.5, help="detector NMS IoU")
    ap.add_argument("--classes", nargs="*", help="keep only these classes")
    a = ap.parse_args()
    from bp.cubicasa.infer import SYMBOLS, load, predict

    m = load(a.weights)
    out = Path(a.out)
    res = json.loads(out.read_text()) if out.exists() else {}
    imgs = sorted(Path(a.val_dir).glob("*.png"))
    for i, p in enumerate(imgs):
        if p.stem in res:
            continue
        W, H = Image.open(p).size
        res[p.stem] = {"W": W, "H": H, "dets": {md: [(n, round(s, 4), [round(v, 5) for v in b])
                                                     for n, s, b in predict(m, str(p), md, tile_classes=SYMBOLS, iou=a.iou)
                                                     if not a.classes or n in a.classes]
                                                for md in a.modes}}
        if i % 25 == 0:
            print(i, len(imgs), flush=True)
            out.write_text(json.dumps(res))
    out.write_text(json.dumps(res))


if __name__ == "__main__":
    main()
