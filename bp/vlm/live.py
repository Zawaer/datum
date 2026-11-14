"""Live second opinion from the fine-tuned VLM (Qwen3-VL-8B + LoRA r3 checkpoint-2200) on a vLLM server.

    live_second_opinion(image_path, question) -> {"answer", "confidence", "evidence", "explanation", "seconds"} | None

Same prompt, image budget and output parsing as the eval runs that produced the precomputed answers
(bp.vlm.infer.RemoteRunner + bp.vlm.format, read through bp.solvers.vlm.answer_from_reply), so a live answer
has the shape of a precomputed one: the count plus one normalised box per counted item.

Environment (all optional; unset -> None, the caller keeps its current behaviour)
- BP_VLM_URL       https://<gpu-host>.sslip.io/v1   (deploy/vlm/serve.sh: Caddy TLS in front of vLLM)
- BP_VLM_KEY       bearer token (data/secrets/vlm.env, written by serve.sh; never committed)
- BP_VLM_SERVED    LoRA name on the server (default "bpvlm", as registered by deploy/vlm/serve.sh)
- BP_VLM_LIVE_TIMEOUT  hard limit per ask in seconds (default 20)
- BP_VLM_LIVE_RETRY    after a failed call, skip the server for this many seconds (default 60), so a dead
                       box costs one timeout per minute, not one per question

Never raises. Successful replies are cached in memory per (image file, mtime, question).
"""
from __future__ import annotations

import collections
import os
import threading
import time
from pathlib import Path

_cache: collections.OrderedDict = collections.OrderedDict()
_CACHE_MAX = 2000
_lock = threading.Lock()
_down_until = 0.0
_inflight = threading.BoundedSemaphore(int(os.environ.get("BP_VLM_LIVE_STREAMS", 8) or 8))
last_error: str | None = None  # for the health line / debugging; never shown to users


def enabled() -> bool:
    return bool(os.environ.get("BP_VLM_URL"))


def _timeout() -> float:
    return float(os.environ.get("BP_VLM_LIVE_TIMEOUT", 20) or 20)


def _fail(msg: str):
    global _down_until, last_error
    last_error = msg[:200]
    _down_until = time.monotonic() + float(os.environ.get("BP_VLM_LIVE_RETRY", 60) or 60)
    return None


def live_second_opinion(image_path, question: str, source: str = "cubicasa5k", file: str | None = None):
    """Ask the served model to count `question` on the drawing at `image_path` (PNG/JPG, or PDF page 0).

    source: image budget key (bp.vlm.format.BUDGET); CubiCasa-like residential plans use "cubicasa5k".
    file: the drawing path the evidence boxes should refer to (default: image_path as given).
    Returns None when the server is not configured, down, slow, or the drawing cannot be read."""
    if not enabled() or not question:
        return None
    p = Path(image_path)
    try:
        key = (str(p.resolve()), p.stat().st_mtime_ns, question.strip(), source)
    except OSError:
        return None
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            hit = _cache[key]
            return {**hit, "evidence": [dict(e, file=file or str(image_path)) for e in hit["evidence"]]}
    if time.monotonic() < _down_until:
        return None
    if not _inflight.acquire(timeout=1.0):  # the server is saturated by other asks: skip, do not queue
        return None
    # The slot is released by the worker thread when its request has really ended (not when we stop waiting),
    # so the semaphore bounds the work in flight; the request's own socket timeout ends a stuck worker.
    started = False
    try:
        from bp.solvers.vlm import answer_from_reply
        from bp.vlm.infer import RemoteRunner, load_drawing

        try:
            img = load_drawing(p)
        except Exception:  # noqa: BLE001
            return None
        if img is None:
            return None
        t = _timeout()
        runner = RemoteRunner(model=os.environ.get("BP_VLM_SERVED", "bpvlm"), timeout=t)
        box: dict = {}

        def call():
            try:
                box["r"] = runner.ask(img, question, source=source)
            except Exception as e:  # noqa: BLE001
                box["e"] = f"{type(e).__name__}: {str(e)[:150]}"
            finally:
                _inflight.release()

        th = threading.Thread(target=call, daemon=True)
        th.start()
        started = True
        th.join(t)  # hard deadline: urllib's timeout is per socket operation, not per request
        if th.is_alive():
            return _fail(f"timeout after {t:.0f} s")
        if "e" in box:
            return _fail(box["e"])
        r = box["r"]
        out = answer_from_reply(r, file or str(image_path))
        out["seconds"] = r.get("seconds")
        with _lock:
            _cache[key] = out
            while len(_cache) > _CACHE_MAX:
                _cache.popitem(last=False)
        return out
    except Exception as e:  # noqa: BLE001  never take the cross-check down
        return _fail(f"{type(e).__name__}: {str(e)[:150]}")
    finally:
        if not started:
            _inflight.release()

def health(timeout: float = 3.0) -> str:
    """'ok' | 'off' | 'down: ...' from GET <BP_VLM_URL>/models (served model names checked)."""
    import json
    import urllib.request

    if not enabled():
        return "off"
    url = os.environ["BP_VLM_URL"].rstrip("/") + "/models"
    k = os.environ.get("BP_VLM_KEY") or os.environ.get("BP_VLM_API_KEY")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {k}"} if k else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ids = [m.get("id") for m in json.loads(r.read()).get("data", [])]
    except Exception as e:  # noqa: BLE001
        return f"down: {type(e).__name__}"
    want = os.environ.get("BP_VLM_SERVED", "bpvlm")
    return "ok" if want in ids else f"down: model {want!r} not served ({', '.join(map(str, ids))})"


if __name__ == "__main__":  # python -m bp.vlm.live [image question]   health check / one ask
    import json
    import sys

    print("health:", health())
    if len(sys.argv) >= 3:
        res = live_second_opinion(sys.argv[1], sys.argv[2])
        print(json.dumps(res, ensure_ascii=False)[:2000] if res else f"no answer ({last_error})")
