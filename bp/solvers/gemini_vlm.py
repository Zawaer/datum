"""Frontier baseline #2: Google Gemini given the drawing file and the question, nothing else.

Same system prompt and answer format as the Claude baseline (bp/solvers/claude_vlm.py). The drawing is sent
inline (PDF / PNG / JPG). IFC models (tens of MB of STEP text) do not fit the request, so .ifc questions
abstain and count as wrong, exactly like an unanswered question.

Cost is computed from the API's usageMetadata at list price (prompts < 200k tokens):
gemini-3.1-pro-preview $2 / 1M input, $12 / 1M output incl. thinking tokens
(https://ai.google.dev/gemini-api/docs/pricing, checked Sat 14.11.2026).
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

PRICES = {  # USD per 1M tokens: (input, output)
    "gemini-3.1-pro-preview": (2.0, 12.0),
}
MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _key() -> str:
    k = os.environ.get("GEMINI_API_KEY")
    if not k:
        f = Path(__file__).resolve().parents[2].joinpath("data/secrets/gemini.env")
        if f.exists():
            for line in f.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    k = line.split("=", 1)[1].strip()
    if not k:
        raise RuntimeError("GEMINI_API_KEY not set")
    return k


class GeminiSolver:
    def __init__(self, variant=None):
        self.model = variant or "gemini-3.1-pro-preview"
        self.root = data_root()
        self.key = _key()

    def __call__(self, q):
        src = self.root / q["path"]
        ext = src.suffix.lower()
        base = {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": 0.0, "method": self.model}
        if ext not in MIME:
            return {**base, "error": f"{ext} not sendable inline"}
        body = {
            "system_instruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [
                {"inline_data": {"mime_type": MIME[ext], "data": base64.b64encode(src.read_bytes()).decode()}},
                {"text": f"Question: {q['question']}"},
            ]}],
        }
        req = urllib.request.Request(API.format(model=self.model), json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "x-goog-api-key": self.key})
        res, err = None, None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    res = json.load(r)
                break
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}"
                if e.code in (429, 500, 503):
                    time.sleep(10 * (attempt + 1))
                    continue
                break
            except Exception as e:  # noqa: BLE001
                err = repr(e)[:200]
                time.sleep(5)
        if res is None:
            return {**base, "error": err}
        um = res.get("usageMetadata", {})
        pin, pout = PRICES.get(self.model, (0.0, 0.0))
        cost = (um.get("promptTokenCount", 0) * pin
                + (um.get("candidatesTokenCount", 0) + um.get("thoughtsTokenCount", 0)) * pout) / 1e6
        parts = (res.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        m = re.findall(r"ANSWER:\s*(.+)", text)
        ans = m[-1].strip() if m else (text.strip().splitlines()[-1] if text.strip() else None)
        return {**base, "answer": ans, "confidence": 0.5, "cost_usd": cost, "raw": text[-1500:]}
