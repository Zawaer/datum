"""Raster floor-plan solver for cubicasa5k questions (Finnish real-estate plans, PNG).

One YOLO detector (trained on public CubiCasa5k annotations, never on our test drawings: see
train/cubicasa/README.md) finds countable symbols (windows, doors, toilets, sinks, showers, bathtubs,
sauna stoves) and typed rooms / storeys (bedroom, kitchen, bathroom, WC room, balcony, floor) in the
PNG. The question template picks the classes to count; every counted detection becomes a numbered
evidence box. Inference sees only the PNG: no annotation lookup.

variant: optional weights path, or a .txt listing several for an ensemble (default $CUBICASA_WEIGHTS or cache/cubicasa/weights/best.pt).
"""
import collections
import json
import math
import os
import threading
from pathlib import Path

from bp.cubicasa.classes import COUNTS
from bp.cubicasa.counting import calib_p, posterior
from bp.cubicasa.infer import SYMBOLS, load, predict
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
        cf = Path(self.weights).with_name("calib.json")
        self.calib = json.loads(cf.read_text()) if cf.exists() else {}
        self.imgsz = str(self.thresh.pop("_imgsz", 1024))
        self.cls_imgsz = self.thresh.pop("_cls_imgsz", {})
        self._model = None
        self._lock = threading.Lock()
        self._cache = collections.OrderedDict()

    # -- detection -------------------------------------------------------------------------------
    def _load(self):
        if self._model is None:
            self._model = load(self.weights)
        return self._model

    def detect(self, path: str, imgsz: str | int | None = None):
        """All detections (conf >= 0.05) for one image at one inference size:
        list of (cls_name, conf, [x0, y0, x1, y1] normalised), sorted top-to-bottom."""
        imgsz = str(imgsz or self.imgsz)
        key = (path, imgsz)
        with self._lock:  # the model is not thread-safe; one predict at a time
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            m = self._load()
            img = str(data_root() / path) if not Path(path).is_absolute() else path
            out = [(n, sc, [round(v, 5) for v in b]) for n, sc, b in predict(m, img, imgsz, tile_classes=SYMBOLS)]
            out.sort(key=lambda d: (d[2][1], d[2][0]))
            self._cache[key] = out
            if len(self._cache) > 4096:
                self._cache.popitem(last=False)
            return out

    def detections(self, path: str, classes):
        """Detections of the given classes, each class taken at its tuned inference size."""
        out = []
        for c in classes:
            out += [d for d in self.detect(path, self.cls_imgsz.get(c, self.imgsz)) if d[0] == c]
        return sorted(out, key=lambda d: (d[2][1], d[2][0]))

    def th(self, cls: str) -> float:
        return float(self.thresh.get(cls, 0.4))

    # -- answer ----------------------------------------------------------------------------------
    def decide(self, t, dets, rule=None):
        """(answer, confidence, kept detections, how) for template t from its class detections.

        rule {"method": "threshold"} counts detections over the tuned per-class thresholds.
        rule {"method": "posterior", "w": w} takes the mode of the count distribution implied by the
        calibrated detection probabilities, a Poisson term for missed objects and the template's dev
        answer distribution ** w (bp/cubicasa/counting.py)."""
        rule = rule or self.calib.get("templates", {}).get(t) or {"method": "threshold"}
        if t == "sauna":  # a sauna = a sauna room, or a stove not inside a detected sauna room
            rooms = [d[2] for d in dets if d[0] == "sauna_room" and d[1] >= self.th("sauna_room")]
            dets = [d for d in dets if d[0] == "sauna_room" or not any(_inside(d[2], r) for r in rooms)]
        if not self.calib.get("classes"):  # uncalibrated weights: plain threshold counting
            kept = [d for d in dets if d[1] >= self.th(d[0])]
            logp = 0.0
            for name, sc, _ in dets:
                p = 1 / (1 + math.exp(-(sc - self.th(name)) * 12))
                logp += math.log(max(p, 1 - p))
            return len(kept), math.exp(logp), kept, "detected"
        cc = self.calib["classes"]
        ps = [calib_p(sc, cc[n]["ab"]) for n, sc, _ in dets]
        lam = sum(cc[n]["lam"] for n in set(COUNTS[t]) if n in cc)
        prior = self.calib.get("priors", {}).get(t)
        post = posterior(ps, lam, prior, rule.get("w", 0.0))
        if rule["method"] == "threshold":
            k = sum(1 for d in dets if d[1] >= self.th(d[0]))
        elif rule["method"] == "prior":
            k = int(max(prior, key=prior.get))
        else:
            k = max(range(len(post)), key=post.__getitem__)
        k = min(k, len(post) - 1)
        kept = sorted(dets, key=lambda d: -d[1])[:k]  # the k most likely detections are the evidence
        kept.sort(key=lambda d: (d[2][1], d[2][0]))
        how = "detected" if len(kept) == k and all(d[1] >= self.th(d[0]) for d in kept) else "estimated"
        return k, post[k], kept, how

    def __call__(self, q):
        t = target(q["question"])
        if t is None:
            return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0,
                    "method": "cubicasa-yolo", "explanation": "question template not recognised"}
        classes = COUNTS[t]
        k, conf, kept, how = self.decide(t, self.detections(q["path"], classes))
        label = LABEL[t]
        ev = [{"kind": "box", "file": q["path"], "page": 0, "bbox": b,
               "label": f"{label} {i}" + (f" ({name.replace('_', ' ')})" if len(classes) > 1 else ""),
               "value": 1, "score": round(sc, 3)} for i, (name, sc, b) in enumerate(kept, 1)]
        expl = f"{len(kept)} {label}{'' if len(kept) == 1 else 's'} detected"
        if how == "estimated":
            expl = (f"{k} {label}{'' if k == 1 else 's'}: weak detections combined with how common each count is"
                    f" ({len(kept)} box{'' if len(kept) == 1 else 'es'} shown)")
        return {
            "answer": k,
            "confidence": round(conf, 3),
            "method": "cubicasa-yolo" if how == "detected" else "cubicasa-yolo+prior",
            "cost_usd": 0.0,
            "explanation": expl,
            "evidence": ev,
        }
