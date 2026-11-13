"""Open-model baseline: NVIDIA Nemotron 3.5 Super VL (124B open weights) given the drawing and the question.

Same system prompt and answer format as the Claude and Gemini baselines. The model takes images, so PDF
pages are rendered to PNG (long side <= 2048 px). IFC files are not images: those questions abstain and
count as wrong. Called through NVIDIA's OpenAI-compatible endpoint; the free endpoint costs us $0, so
cost_usd is priced at the cheapest listed serverless partner rate for comparability
($0.15 / 1M input, $0.47 / 1M output, CoreWeave on build.nvidia.com, checked Sat 14.11.2026).
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from bp.data import data_root
from bp.solvers.claude_vlm import SYSTEM

URL = "https://integrate.api.nvidia.com/v1/chat/completions"
PRICE_IN, PRICE_OUT = 0.15, 0.47  # USD per 1M tokens
MAX_SIDE = 2048


def _key() -> str:
    k = os.environ.get("NVIDIA_API_KEY")
    f = Path(__file__).resolve().parents[2].joinpath("data/secrets/nvidia.env")
    if not k and f.exists():
        for line in f.read_text().splitlines():
            if line.startswith("NVIDIA_API_KEY="):
                k = line.split("=", 1)[1].strip()
    if not k:
        raise RuntimeError("NVIDIA_API_KEY not set")
    return k


def _png(src: Path) -> bytes:
    import io

    from PIL import Image

    if src.suffix.lower() == ".pdf":
        import pymupdf

        with pymupdf.open(src) as doc:
            page = doc[0]
            zoom = MAX_SIDE / max(page.rect.width, page.rect.height)
            return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
    im = Image.open(src).convert("RGB")
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class NemotronSolver:
    def __init__(self, variant=None):
        self.model = variant or "nvidia/nemotron-3.5-super-vl-120b-a12b"
        self.root = data_root()
        self.key = _key()

    def __call__(self, q):
        src = self.root / q["path"]
        base = {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": "nemotron-3.5-vl"}
        if src.suffix.lower() not in (".pdf", ".png", ".jpg", ".jpeg"):
            return {**base, "error": f"{src.suffix} is not an image"}
        img = base64.b64encode(_png(src)).decode()
        body = {"model": self.model, "max_tokens": 16384, "temperature": 0.6, "top_p": 0.95, "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}},
                {"type": "text", "text": f"Question: {q['question']}"}]}]}
        req = urllib.request.Request(URL, json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        res, err = None, None
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req, timeout=900) as r:
                    res = json.load(r)
                break
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}"
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(15 * (attempt + 1))
                    continue
                break
            except Exception as e:  # noqa: BLE001
                err = repr(e)[:200]
                time.sleep(10)
        if res is None:
            return {**base, "error": err}
        u = res.get("usage", {})
        cost = (u.get("prompt_tokens", 0) * PRICE_IN + u.get("completion_tokens", 0) * PRICE_OUT) / 1e6
        text = (res.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        m = re.findall(r"ANSWER:\s*(.+)", text)
        ans = m[-1].strip() if m else (text.strip().splitlines()[-1] if text.strip() else None)
        return {**base, "answer": ans, "confidence": 0.5, "cost_usd": cost, "raw": text[-1500:]}
