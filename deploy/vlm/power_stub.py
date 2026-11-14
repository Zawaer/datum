"""Stub of the infra side's GPU power hook (deploy/vlm/POWER.md), plus a VLM that is only up while "booted".

    .venv/bin/python deploy/vlm/power_stub.py [--port 18761] [--secret S] [--key K] [--boot 8] [--count 3]

- POST /hook  {"action": "start" | "stop" | "status"}, "Authorization: Bearer <secret>" -> {"state", "eta_s"}
  (the contract in POWER.md: idempotent, 401 on a bad secret, 400 on an unknown action, 429 above 10 calls/min)
- GET  /v1/models, POST /v1/chat/completions: an OpenAI-compatible VLM that answers only `--boot` seconds after a
  start and until the next stop (503 otherwise, like a box that is still booting or gone). Each chat reply lists
  `--count` boxes in the model's JSON format, so an upload gets a deterministic second opinion.
- GET  /_calls: every hook call so far (for tests; no auth).

For tests, `make_server(...)` returns the ThreadingHTTPServer (with `.calls` and `.power`) without serving it.
Never touches a real GPU.
"""
from __future__ import annotations

import argparse
import collections
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Power:
    def __init__(self, boot_s: float):
        self.boot_s = boot_s
        self.started_at: float | None = None

    def state(self) -> str:
        if self.started_at is None:
            return "stopped"
        return "running" if time.time() - self.started_at >= self.boot_s else "starting"

    def eta(self) -> int:
        if self.started_at is None:
            return int(self.boot_s)
        return int(max(0, self.boot_s - (time.time() - self.started_at)))


def make_server(port: int = 0, secret: str = "stub-secret", key: str | None = None, boot_s: float = 8.0,
                count: int = 3, served: str = "bpvlm", rate_per_min: int = 10) -> ThreadingHTTPServer:
    power = Power(boot_s)
    calls: list[dict] = []
    recent: collections.deque = collections.deque()
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _vlm_ok(self):
            if key and self.headers.get("Authorization") != f"Bearer {key}":
                self._send(401, {"error": "bad key"})
                return False
            if power.state() != "running":
                self._send(503, {"error": "booting" if power.started_at else "stopped"})
                return False
            return True

        def do_GET(self):
            path = self.path.rstrip("/")
            if path == "/_calls":
                return self._send(200, {"calls": calls, "state": power.state()})
            if path == "/v1/models":
                if self._vlm_ok():
                    self._send(200, {"object": "list", "data": [{"id": "Qwen/Qwen3-VL-8B-Instruct"}, {"id": served}]})
                return
            self._send(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            path = self.path.rstrip("/")
            if path == "/hook":
                return self._hook(raw)
            if path == "/v1/chat/completions":
                if not self._vlm_ok():
                    return
                boxes = [{"label": "item", "bbox_2d": [100 + 120 * i, 100, 180 + 120 * i, 180]} for i in range(count)]
                text = json.dumps({"items": boxes, "count": count})
                return self._send(200, {"id": "stub", "object": "chat.completion", "model": served,
                                        "choices": [{"index": 0, "finish_reason": "stop", "logprobs": None,
                                                     "message": {"role": "assistant", "content": text}}],
                                        "usage": {"prompt_tokens": 0, "completion_tokens": 0}})
            self._send(404, {"error": "not found"})

        def _hook(self, raw: bytes):
            if self.headers.get("Authorization") != f"Bearer {secret}":
                return self._send(401, {"error": "bad secret"})
            now = time.time()
            with lock:
                while recent and now - recent[0] > 60:
                    recent.popleft()
                if len(recent) >= rate_per_min:
                    self.send_response(429)
                    self.send_header("Retry-After", "60")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                recent.append(now)
            try:
                action = json.loads(raw or b"{}").get("action")
            except (ValueError, AttributeError):
                action = None
            if action not in ("start", "stop", "status"):
                return self._send(400, {"error": "action must be start, stop or status"})
            with lock:
                calls.append({"action": action, "ts": now})
                if action == "start" and power.started_at is None:
                    power.started_at = now
                elif action == "stop":
                    power.started_at = None
            st = power.state()
            print(json.dumps({"hook": action, "state": st}), flush=True)
            self._send(202 if action == "start" and st == "starting" else 200,
                       {"state": st, "eta_s": power.eta() if st == "starting" else 0})

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    srv.calls, srv.power = calls, power
    return srv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18761)
    ap.add_argument("--secret", default="stub-secret")
    ap.add_argument("--key")
    ap.add_argument("--boot", type=float, default=8.0, help="seconds from start to a healthy VLM")
    ap.add_argument("--count", type=int, default=3, help="boxes in every chat reply")
    ap.add_argument("--served", default="bpvlm")
    a = ap.parse_args()
    srv = make_server(a.port, a.secret, a.key, a.boot, a.count, a.served)
    print(f"power stub on 0.0.0.0:{a.port}: hook /hook, VLM /v1 (boot {a.boot:g} s)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
