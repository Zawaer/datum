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
# each CLI call is a ~220 MB process: a piping sheet's tile reads started 16 at once, and four sheets read in parallel
# put several GB of them next to the server. At most this many run at a time (the rest wait their turn)
MAX_PROCS = int(os.environ.get("BP_LLM_MAX_PROCS", "8") or 8)
_procs = threading.BoundedSemaphore(MAX_PROCS)


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


# ------------------------------------------------------------------------------------------ Messages API directly
# With ANTHROPIC_API_KEY set (the public demo), Claude calls go straight to the Messages API through the SDK instead of
# one ~220 MB Claude Code process each: on the 4-core demo VM eight CLI processes at once turned a ~6 s tile read into
# 10-23 s (a piping sheet's 15-tile read took ~44 s; over HTTP the same wave takes ~8-14 s). BP_LLM_HTTP=0 forces the
# CLI. The CLI wrapper's daily cap (deploy/claude-capped) is enforced here the same way, on the same ledger.
API_MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
# USD per 1M tokens (input, output); cache writes 1.25x input, cache reads 0.1x
API_PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}
API_ATTEMPT_S = float(os.environ.get("BP_LLM_ATTEMPT_S", "25") or 25)  # one attempt; one retry after it
API_MAX_TOKENS = int(os.environ.get("BP_LLM_MAX_TOKENS", "4096") or 4096)
_api_sem = threading.BoundedSemaphore(int(os.environ.get("BP_LLM_MAX_HTTP", "24") or 24))
_client = None


def _use_api(model: str) -> bool:
    return (bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("BP_LLM_HTTP", "1") != "0"
            and model in API_MODELS)


def _paid_calls_off() -> bool:
    """CLAUDE_CLI=/bin/false is how cache warming (deploy/warm.py) turns paid calls off: honoured over HTTP too."""
    return os.path.basename(CLI) == "false"


def _api_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(max_retries=0)  # retries are ours: one, after a short per-attempt timeout
    return _client


def _ledger_reserve(model: str):
    """claude-capped's check-and-reserve, under the same lock file. Returns (refusal message | None, reservation id)."""
    led = os.environ.get("BP_SPEND_LEDGER")
    if not led:
        return None, None
    import datetime
    import fcntl

    allowed = set(filter(None, os.environ.get("BP_ALLOWED_MODELS", "haiku,sonnet").split(",")))
    if allowed and model not in allowed:
        return f"model {model} is not allowed on the public demo", None
    cap = float(os.environ.get("BP_DAILY_USD_CAP", "5") or 5)
    reserve = float(os.environ.get("BP_RESERVE_USD", "0.05") or 0.05)
    day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(led) or ".", exist_ok=True)
    with open(led + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        tot = 0.0
        try:
            with open(led) as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        tot += float(r.get("cost_usd") or 0) if r.get("day") == day else 0.0
                    except (ValueError, AttributeError):
                        continue
        except FileNotFoundError:
            pass
        if tot >= cap:
            return f"daily model budget of ${cap:g} reached", None
        rid = f"{os.getpid()}-{time.time_ns()}"
        _ledger_write(led, {"day": day, "cost_usd": reserve, "reserve": rid})
    return None, (rid, day, reserve)


def _ledger_write(led, rec):
    import fcntl

    with open(led, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps({"t": round(time.time()), **rec}) + "\n")


def _cost(mid: str, u) -> float:
    pin, pout = API_PRICES.get(mid, API_PRICES["claude-sonnet-5-5"])
    cin = getattr(u, "cache_creation_input_tokens", 0) or 0
    crd = getattr(u, "cache_read_input_tokens", 0) or 0
    return ((u.input_tokens or 0) * pin + cin * pin * 1.25 + crd * pin * 0.1 + (u.output_tokens or 0) * pout) / 1e6


def _ask_api(prompt, images, model, system, timeout, think) -> dict:
    """One Messages API call: per-attempt timeout API_ATTEMPT_S (capped by the caller's timeout), one retry on a
    timeout / connection error / 429 / 5xx. think: False turns thinking off, an effort name ("low") sets that effort
    (the piping tile transcription: ~2x faster, same answers on M-101A in 3 of 3 runs, where thinking off missed a
    check valve once), None leaves the model's default, as the CLI ran it."""
    import anthropic

    if _paid_calls_off():
        return {"text": "", "cost_usd": 0.0, "error": "paid model calls are disabled"}
    refusal, rsv = _ledger_reserve(model)
    if refusal:
        return {"text": "", "cost_usd": 0.0, "error": refusal}
    mid = API_MODELS[model]
    content = [_img_block(im) for im in images] + [{"type": "text", "text": prompt}]
    kw = {"thinking": {"type": "disabled"}} if think is False else \
        {"output_config": {"effort": think}} if isinstance(think, str) else {}
    res, cost, deadline = {"text": "", "cost_usd": 0.0}, 0.0, time.monotonic() + timeout
    per_try = API_ATTEMPT_S if model == "haiku" else max(API_ATTEMPT_S, 90.0)  # longer Sonnet answers
    try:
        for attempt in range(2):
            left = deadline - time.monotonic()
            if left < 2:
                res["error"] = res.get("error") or "timeout"
                break
            try:
                with _api_sem:
                    r = _api_client().with_options(timeout=min(per_try, left)).messages.create(
                        model=mid, max_tokens=API_MAX_TOKENS, system=system,
                        messages=[{"role": "user", "content": content}], **kw)
                cost += _cost(mid, r.usage)
                res = {"text": "".join(b.text for b in r.content if b.type == "text"), "cost_usd": cost}
                if not res["text"]:
                    res["error"] = f"empty reply (stop_reason {r.stop_reason})"
                break
            except (anthropic.APITimeoutError, anthropic.APIConnectionError, anthropic.RateLimitError,
                    anthropic.InternalServerError) as e:
                res = {"text": "", "cost_usd": cost, "error": f"{type(e).__name__} (attempt {attempt + 1})"}
            except anthropic.APIStatusError as e:  # 400 / 401 / 403 / 404: retrying will not help
                res = {"text": "", "cost_usd": cost, "error": f"HTTP {e.status_code}: {str(e.message)[:200]}"}
                break
    finally:
        if rsv:
            rid, day, reserve = rsv
            _ledger_write(os.environ["BP_SPEND_LEDGER"], {"day": day, "cost_usd": round(cost - reserve, 6),
                                                          "correct": rid})
    return res


def ask(prompt: str, images=(), model: str = "haiku", system: str = "Reply with JSON only.",
        timeout: int = 600, tag: str = "", think: bool | str | None = None) -> dict:
    """One-turn call. Returns {"text", "cost_usd", "latency_s"} (text '' on failure, plus "error").
    model: a Claude alias (Messages API when ANTHROPIC_API_KEY is set, else the Claude Code CLI) or "nemotron"
    (NVIDIA endpoint). think (Messages API path only): False = no extended thinking, "low" / "medium" / ... = that
    effort, None = the model's default (as the CLI runs it)."""
    if model.startswith("nemotron"):
        t0 = time.time()
        res = _ask_nemotron(prompt, images, system, timeout)
        res["latency_s"] = round(time.time() - t0, 2)
        _log(model, tag, res, len(images))
        return res
    if _use_api(model):
        t0 = time.time()
        try:
            res = _ask_api(prompt, images, model, system, timeout, think)
        except Exception as e:  # noqa: BLE001  never worse than a failed call
            res = {"text": "", "cost_usd": 0.0, "error": repr(e)[:300]}
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
        with _procs, tempfile.TemporaryDirectory(prefix="bpgen_") as d:
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
