"""Raster floor-plan solver for cubicasa5k questions (Finnish real-estate plans, PNG).

One YOLO detector (trained on public CubiCasa5k annotations, never on our test drawings: see
train/cubicasa/README.md) finds countable symbols (windows, doors, toilets, sinks, showers, bathtubs,
sauna stoves) and typed rooms / storeys (bedroom, kitchen, bathroom, WC room, balcony, floor) in the
PNG. The question template picks the classes to count; every counted detection becomes a numbered
evidence box. Inference sees only the PNG: no annotation lookup.

variant: optional weights path (default $CUBICASA_WEIGHTS or cache/cubicasa/weights/best.pt).
"""
import collections
import json
import math
import os
import threading
from pathlib import Path

from bp.cubicasa.classes import COUNTS
from bp.cubicasa.questions import LABEL, target
from bp.data import data_root

DEFAULT_WEIGHTS = "cache/cubicasa/weights/best.pt"


def _inside(b, r, pad=0.01):
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return r[0] - pad <= cx <= r[2] + pad and r[1] - pad <= cy <= r[3] + pad


class CubicasaSolver:
    def __init__(self, variant=None, weights=None):
        self.weights = weights or variant or os.environ.get("CUBICASA_WEIGHTS") or DEFAULT_WEIGHTS
        tf = Path(self.weights).with_name("thresholds.json")
        self.thresh = json.loads(tf.read_text()) if tf.exists() else {}
        self.imgsz = int(self.thresh.pop("_imgsz", 1024))
        self.cls_imgsz = self.thresh.pop("_cls_imgsz", {})
        self._model = None
        self._lock = threading.Lock()
        self._cache = collections.OrderedDict()

    # -- detection -------------------------------------------------------------------------------
    def _load(self):
        if self._model is None:
            from ultralytics import YOLO

            self._model = YOLO(self.weights)
        return self._model

    def detect(self, path: str, imgsz: int | None = None):
        """All detections (conf >= 0.05) for one image at one inference size:
        list of (cls_name, conf, [x0, y0, x1, y1] normalised), sorted top-to-bottom."""
        imgsz = imgsz or self.imgsz
        key = (path, imgsz)
        with self._lock:  # the model is not thread-safe; one predict at a time
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            m = self._load()
            img = str(data_root() / path) if not Path(path).is_absolute() else path
            r = m.predict(img, imgsz=imgsz, conf=0.05, iou=0.5, verbose=False, max_det=600)[0]
            out = [(r.names[int(c)], float(s), [round(v, 5) for v in b])
                   for b, c, s in zip(r.boxes.xyxyn.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist())]
            out.sort(key=lambda d: (d[2][1], d[2][0]))
            self._cache[key] = out
            if len(self._cache) > 4096:
                self._cache.popitem(last=False)
            return out

    def detections(self, path: str, classes):
        """Detections of the given classes, each class taken at its tuned inference size."""
        out = []
        for c in classes:
            out += [d for d in self.detect(path, int(self.cls_imgsz.get(c, self.imgsz))) if d[0] == c]
        return sorted(out, key=lambda d: (d[2][1], d[2][0]))

    def th(self, cls: str) -> float:
        return float(self.thresh.get(cls, 0.4))

    # -- answer ----------------------------------------------------------------------------------
    def __call__(self, q):
        t = target(q["question"])
        if t is None:
            return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0,
                    "method": "cubicasa-yolo", "explanation": "question template not recognised"}
        classes = COUNTS[t]
        dets = self.detections(q["path"], classes)
        kept = [d for d in dets if d[1] >= self.th(d[0])]
        if t == "sauna":  # a sauna = a sauna room, or a stove not inside a detected sauna room
            rooms = [d[2] for d in kept if d[0] == "sauna_room"]
            kept = [d for d in kept if d[0] == "sauna_room" or not any(_inside(d[2], r) for r in rooms)]
        # confidence: probability that every kept detection is real and every rejected one is not,
        # treating the detector score as a rough probability around the class threshold.
        logp = 0.0
        for name, s, _ in dets:
            th = self.th(name)
            p = 1 / (1 + math.exp(-(s - th) * 12))  # ~0.5 at threshold, saturates quickly
            logp += math.log(max(p, 1 - p))
        conf = round(math.exp(logp), 3)
        label = LABEL[t]
        ev = [{"kind": "box", "file": q["path"], "page": 0, "bbox": b, "label": f"{label} {i}" + (f" ({name.replace('_', ' ')})" if len(classes) > 1 else ""),
               "value": 1, "score": round(s, 3)} for i, (name, s, b) in enumerate(kept, 1)]
        return {
            "answer": len(kept),
            "confidence": conf,
            "method": "cubicasa-yolo",
            "cost_usd": 0.0,
            "explanation": f"{len(kept)} {label}{'' if len(kept) == 1 else 's'} detected"
                           + (f" ({', '.join(classes)})" if len(classes) > 1 else ""),
            "evidence": ev,
        }
