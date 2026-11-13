"""Detector inference shared by the solver and the tuning script.

mode "1024" = whole image letterboxed to 1024 px. mode "t1024" = the same, plus, for images much
larger than that, overlapping tiles at near-native resolution, merged with the whole-image pass so
small symbols (windows, shower drains) on big scans are not lost to downscaling.
"""
import math

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def _merge(dets, iou_th=0.5, contain_th=0.7):
    """Greedy per-class suppression by IoU or containment (a tile-edge fragment inside a full box)."""
    out = []
    for c in {d[0] for d in dets}:
        ds = sorted((d for d in dets if d[0] == c), key=lambda d: -d[1])
        keep = []
        for d in ds:
            b = d[2]
            ab = max(1e-12, (b[2] - b[0]) * (b[3] - b[1]))
            ok = True
            for k in keep:
                kb = k[2]
                iw = min(b[2], kb[2]) - max(b[0], kb[0])
                ih = min(b[3], kb[3]) - max(b[1], kb[1])
                if iw <= 0 or ih <= 0:
                    continue
                inter = iw * ih
                ak = (kb[2] - kb[0]) * (kb[3] - kb[1])
                if inter / (ab + ak - inter) > iou_th or inter / min(ab, ak) > contain_th:
                    ok = False
                    break
            if ok:
                keep.append(d)
        out += keep
    return out


def _parse(r, x0=0, y0=0, sx=1.0, sy=1.0, W=1, H=1):
    res = []
    for b, c, s in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
        res.append((r.names[int(c)], float(s), [(b[0] + x0) / W, (b[1] + y0) / H, (b[2] + x0) / W, (b[3] + y0) / H]))
    return res


def predict(model, path, mode, tile_classes=None, conf=0.05):
    """Detections [(cls, score, [x0, y0, x1, y1] normalised)] for one image path."""
    tiled = str(mode).startswith("t")
    imgsz = int(str(mode).lstrip("t"))
    r = model.predict(path, imgsz=imgsz, conf=conf, iou=0.5, verbose=False, max_det=600)[0]
    H, W = r.orig_shape
    dets = _parse(r, W=W, H=H)
    if not tiled or max(W, H) < 1.6 * imgsz:
        return dets
    img = np.asarray(Image.open(path).convert("RGB"))[:, :, ::-1]  # BGR like cv2
    tile = int(imgsz * 1.25)
    nx, ny = max(1, math.ceil((W - tile * 0.2) / (tile * 0.8))), max(1, math.ceil((H - tile * 0.2) / (tile * 0.8)))
    xs = [0] if nx == 1 else np.linspace(0, max(0, W - tile), nx).astype(int).tolist()
    ys = [0] if ny == 1 else np.linspace(0, max(0, H - tile), ny).astype(int).tolist()
    crops, offs = [], []
    for y in ys:
        for x in xs:
            crops.append(np.ascontiguousarray(img[y:y + tile, x:x + tile]))
            offs.append((x, y))
    tdets = []
    for i in range(0, len(crops), 4):
        for rr, (x, y) in zip(model.predict(crops[i:i + 4], imgsz=imgsz, conf=conf, iou=0.5, verbose=False,
                                            max_det=600), offs[i:i + 4]):
            for d in _parse(rr, x, y, W=W, H=H):
                if tile_classes is None or d[0] in tile_classes:
                    tdets.append(d)
    return _merge([d for d in dets] + tdets)


SYMBOLS = {"window", "door", "doorway", "toilet", "sink", "shower", "bathtub", "sauna_stove"}
