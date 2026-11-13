"""Frontier model calls through the Claude Code CLI (no tools, one turn), optionally with images.

Images are sent inline (stream-json input), so the model never needs a Read turn. The CLI reports
total_cost_usd at API list prices; every call is appended to cache/generic/spend.jsonl.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

CLI = os.environ.get("CLAUDE_CLI") or os.environ.get("CLAUDE_CODE_EXECPATH") or "claude"
SPEND_LOG = Path("cache/generic/spend.jsonl")
_lock = threading.Lock()


def _img_block(img) -> dict:
    b = io.BytesIO()
    img.convert("RGB").save(b, "PNG", optimize=True)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.b64encode(b.getvalue()).decode()}}


def ask(prompt: str, images=(), model: str = "haiku", system: str = "Reply with JSON only.",
        timeout: int = 300, tag: str = "") -> dict:
    """One-turn call. Returns {"text", "cost_usd", "latency_s"} (text '' on failure, plus "error")."""
    content = [_img_block(im) for im in images] + [{"type": "text", "text": prompt}]
    msg = {"type": "user", "message": {"role": "user", "content": content}}
    cmd = [CLI, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
           "--model", model, "--tools", "", "--system-prompt", system, "--strict-mcp-config",
           "--setting-sources", "", "--max-turns", "1"]
    t0 = time.time()
    res = {"text": "", "cost_usd": 0.0}
    try:
        with tempfile.TemporaryDirectory(prefix="bpgen_") as d:
            out = subprocess.run(cmd, input=json.dumps(msg) + "\n", capture_output=True, text=True,
                                 timeout=timeout, cwd=d)
        for line in out.stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "result":
                res = {"text": ev.get("result") or "", "cost_usd": float(ev.get("total_cost_usd") or 0.0)}
        if not res["text"]:
            res["error"] = (out.stderr or out.stdout)[-300:]
    except Exception as e:  # noqa: BLE001
        res["error"] = repr(e)[:300]
    res["latency_s"] = round(time.time() - t0, 2)
    with _lock:
        SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SPEND_LOG, "a") as f:
            f.write(json.dumps({"t": time.time(), "model": model, "tag": tag, "cost_usd": res["cost_usd"],
                                "latency_s": res["latency_s"], "n_img": len(images)}) + "\n")
    return res


def parse_json(text: str):
    """First JSON object (or array) in a model reply, tolerating ```json fences and trailing prose."""
    if not text:
        return None
    t = re.sub(r"```(?:json)?", "", text)
    for opener, closer in (("{", "}"), ("[", "]")):
        i = t.find(opener)
        while i >= 0:
            depth, instr, esc = 0, False, False
            for j in range(i, len(t)):
                c = t[j]
                if instr:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        instr = False
                    continue
                if c == '"':
                    instr = True
                elif c == opener:
                    depth += 1
                elif c == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(t[i:j + 1])
                        except json.JSONDecodeError:
                            break
            i = t.find(opener, i + 1)
    return None


def total_spend() -> float:
    if not SPEND_LOG.exists():
        return 0.0
    return sum(json.loads(l)["cost_usd"] for l in SPEND_LOG.read_text().splitlines() if l.strip())
