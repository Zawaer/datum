"""Fine-tuned open VLM (Qwen3-VL + LoRA, train/vlm/) for grounded counting on raster plans.

The model answers with one box per counted instance plus the count (bp/vlm/format.py), so every answer
comes with numbered box evidence. Runs locally (BP_VLM_ADAPTER, optional BP_VLM_4BIT) or against a GPU
server (BP_VLM_URL, vLLM / OpenAI-compatible); see bp/vlm/infer.py.

variant: optional LoRA adapter dir (local) — `vlm@cache/vlm/runs/x/final`.

Confidence: product of the probabilities of the tokens where the model decided "another item" vs
"end of list" (bp.vlm.format.decision_confidence); halved when the reply was not clean JSON or its
`count` disagrees with the listed boxes (the answer is always the number of boxes, so the evidence adds up).
Cost: local compute is 0; for a remote server, seconds x BP_VLM_USD_PER_HOUR / 3600 (default 0).
"""
from __future__ import annotations

import os
from pathlib import Path

from bp.data import data_root
from bp.vlm.infer import get_runner, load_drawing

IMG_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp")


class VlmSolver:
    def __init__(self, variant=None):
        self.root = data_root()
        self.runner = get_runner(adapter=variant) if variant else get_runner()
        self.usd_per_hour = float(os.environ.get("BP_VLM_USD_PER_HOUR", 0) or 0)

    def image_for(self, path: str):
        """(dataset-relative file the evidence refers to, PIL image). PDFs use their PNG twin if present."""
        p = self.root / path
        if p.suffix.lower() == ".pdf":
            twin = p.with_suffix(".png")
            if twin.exists():
                return str(Path(path).with_suffix(".png")), load_drawing(twin)
            return path, load_drawing(p)  # page 0 at 150 dpi: normalised coords are page coords
        if p.suffix.lower() in IMG_EXT:
            return path, load_drawing(p)
        return path, None

    def __call__(self, q):
        base = {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0,
                "method": f"vlm-{self.runner.backend}"}
        if q.get("type") not in (None, "count"):
            return {**base, "explanation": "VLM is trained for counting questions only"}
        try:
            file, img = self.image_for(q["path"])
        except Exception as e:  # noqa: BLE001
            return {**base, "explanation": f"could not open drawing: {type(e).__name__}"}
        if img is None:
            return {**base, "explanation": "not a raster/PDF drawing"}
        try:
            r = self.runner.ask(img, q["question"], source=q.get("source"))
        except Exception as e:  # noqa: BLE001  e.g. server down: let the router fall back
            return {**base, "explanation": f"VLM call failed: {type(e).__name__}: {str(e)[:120]}"}
        p = r["parsed"]
        items = p["items"]
        n = len(items)
        conf = r["confidence"] if r["confidence"] is not None else 0.5
        notes = []
        if not p["ok"]:
            conf *= 0.5
            notes.append("reply was not clean JSON")
        if p.get("n_raw", n) > n:  # the model looped on the same box(es): its count is unreliable
            conf *= 0.2
            notes.append(f"repetition loop ({p['n_raw'] - n} repeated boxes dropped)")
        if p["count"] is not None and p["count"] != n:
            conf *= 0.5
            notes.append(f"model said count {p['count']} but listed {n} boxes")
        ev = [{"kind": "box", "file": file, "page": 0, "bbox": [round(v, 5) for v in b],
               "label": f"{lab or 'item'} {i}", "value": 1} for i, (lab, b) in enumerate(items, 1)]
        kinds = sorted({lab for lab, _ in items if lab})
        expl = f"{n} item{'' if n == 1 else 's'} found by the VLM" + (f" ({', '.join(kinds[:4])})" if kinds else "")
        if notes:
            expl += " [" + "; ".join(notes) + "]"
        cost = r["seconds"] * self.usd_per_hour / 3600 if self.runner.backend == "remote" else 0.0
        return {**base, "answer": n, "confidence": round(min(1.0, conf), 3), "evidence": ev, "explanation": expl,
                "cost_usd": round(cost, 6), "seconds": r["seconds"], "raw": r["text"][-1500:]}
