"""Raster floor-plan solver for cubicasa5k questions (Finnish real-estate plans, PNG).

One YOLO detector (trained on public CubiCasa5k annotations, never on our test drawings: see
train/cubicasa/README.md) finds countable symbols (windows, doors, toilets, sinks, showers, bathtubs,
sauna stoves) and typed rooms / storeys (bedroom, kitchen, bathroom, WC room, balcony, floor) in the
PNG. The question template picks the classes to count; every counted detection becomes a numbered
evidence box. Inference sees only the PNG: no annotation lookup.

variant: optional weights path (default $CUBICASA_WEIGHTS or cache/cubicasa/weights/best.pt).
"""
import json
import math
import os
import threading
from pathlib import Path

from bp.cubicasa.classes import COUNTS
from bp.cubicasa.questions import LABEL, target
from bp.data import data_root

DEFAULT_WEIGHTS = "cache/cubicasa/weights/best.pt"
DEFAULT_THRESH = "cache/cubicasa/weights/thresholds.json"


class CubicasaSolver:
    def __init__(self, variant=None, weights=None):
        self.weights = weights or variant or os.environ.get("CUBICASA_WEIGHTS") or DEFAULT_WEIGHTS
        tf = Path(self.weights).with_name("thresholds.json")
        self.thresh = json.loads(tf.read_text()) if tf.exists() else {}
        self.imgsz = int(self.thresh.pop("_imgsz", 1024)) if self.thresh else 1024
        self._model = None
        self._lock = threading.Lock()
        self._cache = {}

    # -- detection -------------------------------------------------------------------------------
    def _load(self):
        if self._model is None:
            from ultralytics import YOLO

            self._model = YOLO(self.weights)
        return self._model

    def detect(self, path: str):
        """All detections (conf >= 0.05) for one image: list of (cls_name, conf, [x0,y0,x1,y1] norm)."""
        if path in self._cache:
            return self._cache[path]
        with self._lock:
            if path in self._cache:
                return self._cache[path]
            m = self._load()
            img = str(data_root() / path) if not Path(path).is_absolute() else path
            r = m.predict(img, imgsz=self.imgsz, conf=0.05, iou=0.5, verbose=False, max_det=600)[0]
            names = r.names
            out = []
            for b, c, s in zip(r.boxes.xyxyn.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
                out.append((names[int(c)], float(s), [round(v, 5) for v in b]))
            out.sort(key=lambda d: (d[2][1], d[2][0]))
            self._cache[path] = out
            return out

    def th(self, cls: str) -> float:
        return float(self.thresh.get(cls, 0.4))

    # -- answer ----------------------------------------------------------------------------------
    def __call__(self, q):
        t = target(q["question"])
        if t is None:
            return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0,
                    "method": "cubicasa-yolo", "explanation": "question template not recognised"}
        classes = COUNTS[t]
        dets = [d for d in self.detect(q["path"]) if d[0] in classes]
        kept = [d for d in dets if d[1] >= self.th(d[0])]
        # confidence: probability that every kept detection is real and every rejected one is not,
        # treating the detector score as a rough probability around the class threshold.
        logp = 0.0
        for name, s, _ in dets:
            th = self.th(name)
            p = 1 / (1 + math.exp(-(s - th) * 12))  # ~0.5 at threshold, saturates quickly
            logp += math.log(max(p, 1 - p))
        conf = round(math.exp(logp), 3)
        label = LABEL[t]
        ev = [{"kind": "box", "file": q["path"], "page": 0, "bbox": b, "label": f"{label} {i}",
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
