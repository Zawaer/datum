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


NEMOTRON = "nvidia/nemotron-3.5-super-vl-120b-a12b"
NV_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NV_PRICE_IN, NV_PRICE_OUT = 0.15, 0.47  # USD / 1M tokens, cheapest listed serverless partner


def _ask_nemotron(prompt, images, system, timeout):
    """NVIDIA's OpenAI-compatible endpoint; 429 / 5xx retried with backoff. Reasoning is stripped."""
    import urllib.error
    import urllib.request

    from bp.solvers.nemotron_vlm import _key

    content = []
    for im in images:
        b = io.BytesIO()
        im.convert("RGB").save(b, "PNG", optimize=True)
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()}})
    content.append({"type": "text", "text": prompt})
    body = {"model": NEMOTRON, "max_tokens": 12288, "temperature": 0.6, "top_p": 0.95,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
    req = urllib.request.Request(NV_URL, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {_key()}"})
    err = None
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                res = json.load(r)
            u = res.get("usage", {})
            text = (res.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            text = re.sub(r"(?s)<think>.*?</think>", "", text).strip()
            cost = (u.get("prompt_tokens", 0) * NV_PRICE_IN + u.get("completion_tokens", 0) * NV_PRICE_OUT) / 1e6
            return {"text": text, "cost_usd": cost}
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 8 * (attempt + 1)))
                continue
            break
        except Exception as e:  # noqa: BLE001
            err = repr(e)[:200]
            time.sleep(5)
    return {"text": "", "cost_usd": 0.0, "error": err}


def run_killable(cmd: list, stdin_text: str | None, timeout: float, **kw) -> subprocess.CompletedProcess:
    """subprocess.run, but the child gets its own session and the whole process group is killed on timeout:
    the CLI forks helpers, and a plain kill() left them running (and spending) after we gave up on the call."""
    import signal

    p = subprocess.Popen(cmd, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True, **kw)
    try:
        out, err = p.communicate(stdin_text, timeout=timeout)
    except BaseException:
        try:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.communicate()
        raise
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def ask(prompt: str, images=(), model: str = "haiku", system: str = "Reply with JSON only.",
        timeout: int = 600, tag: str = "") -> dict:
    """One-turn call. Returns {"text", "cost_usd", "latency_s"} (text '' on failure, plus "error").
    model: a Claude alias (via the Claude Code CLI) or "nemotron" (NVIDIA endpoint)."""
    if model.startswith("nemotron"):
        t0 = time.time()
        res = _ask_nemotron(prompt, images, system, timeout)
        res["latency_s"] = round(time.time() - t0, 2)
        _log(model, tag, res, len(images))
        return res
    content = [_img_block(im) for im in images] + [{"type": "text", "text": prompt}]
    msg = {"type": "user", "message": {"role": "user", "content": content}}
    cmd = [CLI, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
           "--model", model, "--tools", "", "--system-prompt", system, "--strict-mcp-config",
           "--setting-sources", "", "--max-turns", "1"]
    t0 = time.time()
    res = {"text": "", "cost_usd": 0.0}
    try:
        with tempfile.TemporaryDirectory(prefix="bpgen_") as d:
            out = run_killable(cmd, json.dumps(msg) + "\n", timeout, cwd=d)
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
    _log(model, tag, res, len(images))
    return res


def _log(model, tag, res, n_img):
    with _lock:
        SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SPEND_LOG, "a") as f:
            f.write(json.dumps({"t": time.time(), "model": model, "tag": tag, "cost_usd": res["cost_usd"],
                                "latency_s": res["latency_s"], "n_img": n_img, "error": res.get("error")}) + "\n")


def parse_json(text: str):
    """First JSON object (or array) in a model reply, tolerating ```json fences and trailing prose."""
    if not text:
        return None
    t = re.sub(r"```(?:json)?", "", text)
    pairs = [("{", "}"), ("[", "]")]
    if 0 <= t.find("[") < (t.find("{") if "{" in t else len(t)):
        pairs.reverse()  # a top-level list comes first
    for opener, closer in pairs:
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
