"""Detector inference shared by the solver and the tuning script.

mode "1024" = whole image letterboxed to 1024 px; "a1024" = with ultralytics test-time augmentation. mode "t1024" = the same, plus, for images much
larger than that, overlapping tiles at near-native resolution, merged with the whole-image pass so
small symbols (windows, shower drains) on big scans are not lost to downscaling.
mode "f1280" = flip test-time augmentation: the image as is, mirrored left-right, upside down and both
(the detector was trained with both flips), boxes mapped back and merged by weighted box fusion
(fused score = sum of the cluster's scores / 4, so a symbol seen in only one view is down-weighted).
Chosen on dev-val drawings by train/cubicasa/tta_dev.py; costs 4 passes.
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


def _iou(a, b):
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    i = iw * ih
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i)


def wbf(view_dets, thr=0.55, skip=0.05):
    """Weighted box fusion of per-view detections [[(cls, score, box)], ...] -> [(cls, score, box)]:
    same-class boxes with IoU >= thr to a cluster's fused box join it; fused box = score-weighted mean,
    fused score = sum of the (at most n_views best) member scores / n_views."""
    n = len(view_dets)
    allb = sorted((d for v in view_dets for d in v if d[1] >= skip), key=lambda d: -d[1])
    out = []
    for c in sorted({d[0] for d in allb}):
        clusters = []  # [fused box, members]
        for d in (x for x in allb if x[0] == c):
            best, bj = thr, None
            for j, (fb, _) in enumerate(clusters):
                o = _iou(d[2], fb)
                if o >= best:
                    best, bj = o, j
            if bj is None:
                clusters.append([list(d[2]), [d]])
            else:
                ms = clusters[bj][1]
                ms.append(d)
                w = sum(m[1] for m in ms)
                clusters[bj][0] = [sum(m[1] * m[2][k] for m in ms) / w for k in range(4)]
        for fb, ms in clusters:
            out.append((c, sum(sorted((m[1] for m in ms), reverse=True)[:n]) / n, fb))
    return out


# flip views: image op, and the inverse map of a normalised box predicted on the flipped image
FLIPS = [
    (lambda a: a, lambda b: b),
    (lambda a: a[:, ::-1], lambda b: [1 - b[2], b[1], 1 - b[0], b[3]]),
    (lambda a: a[::-1], lambda b: [b[0], 1 - b[3], b[2], 1 - b[1]]),
    (lambda a: a[::-1, ::-1], lambda b: [1 - b[2], 1 - b[3], 1 - b[0], 1 - b[1]]),
]


def _predict_flips(model, path, imgsz, conf, iou, views_only=False):
    img = np.asarray(Image.open(path).convert("RGB"))[:, :, ::-1]  # BGR like cv2
    views = []
    for op, inv in FLIPS:
        r = model.predict(np.ascontiguousarray(op(img)), imgsz=imgsz, conf=conf, iou=iou, verbose=False,
                          max_det=600)[0]
        H, W = r.orig_shape
        views.append([(r.names[int(c)], float(s), inv([b[0] / W, b[1] / H, b[2] / W, b[3] / H]))
                      for b, c, s in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist())])
    return views if views_only else wbf(views)


def load(weights):
    """A YOLO model, or a list of them for an ensemble: weights may be a .txt file listing member .pt paths
    (relative to the .txt), whose detections are merged per class (highest score wins; in flip mode all
    members' views go through one weighted box fusion). RT-DETR checkpoints get ultralytics' RTDETR wrapper."""
    from pathlib import Path

    from ultralytics import YOLO

    def one(p):
        m = YOLO(p)
        if type(m.model).__name__ == "RTDETRDetectionModel":  # needs RT-DETR's own predictor / postprocess
            from ultralytics import RTDETR

            m = RTDETR(p)
        return m

    w = Path(weights)
    if w.suffix == ".txt":
        return [one(str((w.parent / ln.strip()).resolve())) for ln in w.read_text().split("\n") if ln.strip()]
    return one(str(w))


def predict(model, path, mode, tile_classes=None, conf=0.05, iou=0.5):
    """Detections [(cls, score, [x0, y0, x1, y1] normalised)] for one image path (iou = the detector's NMS IoU)."""
    if isinstance(model, list) and str(mode).startswith("f"):  # ensemble + flips: one WBF over all views
        imgsz = int(str(mode).lstrip("f"))
        return wbf([v for m in model for v in _predict_flips(m, path, imgsz, conf, iou, views_only=True)])
    if isinstance(model, list):
        return _merge([d for m in model for d in predict(m, path, mode, tile_classes, conf, iou)])
    tiled = str(mode).startswith("t")
    aug = str(mode).startswith("a")
    imgsz = int(str(mode).lstrip("taf"))
    if str(mode).startswith("f"):
        return _predict_flips(model, path, imgsz, conf, iou)
    r = model.predict(path, imgsz=imgsz, conf=conf, iou=iou, verbose=False, max_det=600, augment=aug)[0]
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
        for rr, (x, y) in zip(model.predict(crops[i:i + 4], imgsz=imgsz, conf=conf, iou=iou, verbose=False,
                                            max_det=600), offs[i:i + 4]):
            for d in _parse(rr, x, y, W=W, H=H):
                if tile_classes is None or d[0] in tile_classes:
                    tdets.append(d)
    return _merge([d for d in dets] + tdets)


SYMBOLS = {"window", "door", "doorway", "toilet", "sink", "shower", "bathtub", "sauna_stove"}
