"""Stub of the vLLM server for testing the live second opinion without a GPU (deploy/vlm/README.md).

    .venv/bin/python deploy/vlm/stub_server.py [--port 18000] [--key K] [--delay S]

OpenAI-compatible /v1/models and /v1/chat/completions. A chat request is answered with the model's recorded
reply to the same question on a drawing of the same
(resized) size from cache/vlm/demo_secondopinion{,_raw}.jsonl (the precomputed answers), or,
for a question it has never seen, with the recorded reply to the first question about the same thing
(bp.cubicasa.questions.target), so an upload gets a plausible answer. Checks the bearer key when --key is given
and refuses requests without exactly one image. --delay sleeps before answering (timeout tests).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def load():
    raw = {}
    for line in open(REPO / "cache/vlm/demo_secondopinion_raw.jsonl", encoding="utf-8"):
        r = json.loads(line)
        raw[r["id"]] = r["text"]
    by_q, by_target, sizes = {}, {}, {}
    from PIL import Image

    from bp.cubicasa.questions import target
    from bp.data import data_root
    from bp.vlm.format import budget_for, target_size

    for line in open(REPO / "cache/vlm/demo_secondopinion.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r["id"] in raw:
            if r["path"] not in sizes:  # the size the client resizes this drawing to: tells drawings apart
                try:
                    with Image.open(data_root() / r["path"]) as im:
                        b = budget_for("cubicasa5k")
                        sizes[r["path"]] = target_size(*im.size, b[1], min_pixels=b[0])
                except OSError:
                    sizes[r["path"]] = None
            by_q.setdefault((r["question"].strip(), sizes[r["path"]]), raw[r["id"]])
            t = target(r["question"])
            if t:
                by_target.setdefault(t, raw[r["id"]])
    return by_q, by_target, target


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18000)
    ap.add_argument("--key")
    ap.add_argument("--delay", type=float, default=0.0)
    ap.add_argument("--served", default="bpvlm")
    a = ap.parse_args()
    by_q, by_target, target = load()
    log = []

    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _authed(self):
            if a.key and self.headers.get("Authorization") != f"Bearer {a.key}":
                self._send(401, {"error": "bad key"})
                return False
            return True

        def do_GET(self):
            if not self._authed():
                return
            if self.path.rstrip("/") == "/v1/models":
                return self._send(200, {"object": "list", "data": [{"id": "Qwen/Qwen3-VL-8B-Instruct"},
                                                                   {"id": a.served}]})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authed():
                return
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            if body.get("model") != a.served:
                return self._send(404, {"error": f"model {body.get('model')!r} not served"})
            user = next(m for m in body["messages"] if m["role"] == "user")["content"]
            imgs = [c for c in user if c.get("type") == "image_url"]
            q = next((c["text"] for c in user if c.get("type") == "text"), "")
            if len(imgs) != 1:
                return self._send(400, {"error": "need exactly one image"})
            import base64
            import io

            from PIL import Image

            url = imgs[0]["image_url"]["url"]
            size = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size
            text = by_q.get((q.strip(), size)) or by_target.get(target(q) or "") or '{"items": [], "count": 0}'
            print(json.dumps({"q": q[:80], "image": size, "recorded": (q.strip(), size) in by_q,
                              "replayed": text[:60]}), flush=True)
            time.sleep(a.delay)
            self._send(200, {"id": "stub", "object": "chat.completion", "model": a.served,
                             "choices": [{"index": 0, "finish_reason": "stop", "logprobs": None,
                                          "message": {"role": "assistant", "content": text}}],
                             "usage": {"prompt_tokens": 0, "completion_tokens": 0}})

        def log_message(self, *args):
            pass

    print(f"stub VLM on 0.0.0.0:{a.port} ({len(by_q)} recorded questions)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
