"""Fallback server for the live VLM when vLLM misbehaves on a GPU: plain transformers + PEFT behind the same
OpenAI-compatible API (/v1/models, /v1/chat/completions), so the client (bp/vlm/live.py) does not change.

    VLLM_API_KEY=... python deploy/vlm/hf_server.py --adapter /opt/bp-vlm/adapter [--host 127.0.0.1] [--port 8000]

Inference is bp.vlm.infer.LocalRunner (the repo's own local path: same prompt, greedy, bf16, LoRA on top), one
request at a time (a lock), so throughput is ~1 ask at a time; enough for live uploads in the demo. Chosen
on 2026-11-14 because vLLM 0.33.0 produced garbage tokens (even for the base model, eager, any attention
backend) on an RTX PRO 6000 Blackwell in confidential-compute mode, while transformers answered correctly.

The client already sends the image resized to the training budget, so the runner is called with prepared=True.
The runner computes the decision confidence itself (same function as the client applies to vLLM's logprobs)
and returns it as choices[0].confidence, which bp.vlm.infer.RemoteRunner reads when there are no logprobs.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    ap.add_argument("--served", default="bpvlm")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    key = os.environ.get("VLLM_API_KEY")

    import torch
    from PIL import Image

    from bp.vlm import infer
    from bp.vlm.format import parse_output

    runner = infer.LocalRunner(model=a.model, adapter=a.adapter, device="cuda")
    runner.load()
    print(f"loaded {a.model} + {a.adapter} on {torch.cuda.get_device_name(0)}", flush=True)

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _authed(self):
            if key and self.headers.get("Authorization") != f"Bearer {key}":
                self._send(401, {"error": "unauthorized"})
                return False
            return True

        def do_GET(self):
            if self.path.rstrip("/") == "/health":
                return self._send(200, {"ok": True})
            if not self._authed():
                return
            if self.path.rstrip("/") == "/v1/models":
                return self._send(200, {"object": "list", "data": [{"id": a.model}, {"id": a.served}]})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authed():
                return
            if self.path.rstrip("/") != "/v1/chat/completions":
                return self._send(404, {"error": "not found"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if body.get("model") != a.served:
                    return self._send(404, {"error": f"model {body.get('model')!r} not served"})
                user = next(m for m in body["messages"] if m["role"] == "user")["content"]
                imgs = [c for c in user if c.get("type") == "image_url"]
                q = next((c["text"] for c in user if c.get("type") == "text"), "")
                if len(imgs) != 1 or not q:
                    return self._send(400, {"error": "need one image and one question"})
                img = Image.open(io.BytesIO(base64.b64decode(imgs[0]["image_url"]["url"].split(",", 1)[1])))
                img.load()
                runner.max_new = int(body.get("max_tokens") or 2048)
                t0 = time.time()
                r = runner.ask(img.convert("RGB"), q, prepared=True)
                print(json.dumps({"q": q[:60], "size": img.size, "n_in": r["n_in"], "n_out": r["n_out"],
                                  "s": round(time.time() - t0, 2)}), flush=True)
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": f"{type(e).__name__}: {str(e)[:200]}"})
            conf = r["confidence"]
            text = r["text"]
            self._send(200, {"id": "hf", "object": "chat.completion", "model": a.served,
                             "choices": [{"index": 0, "finish_reason": "stop",
                                          "message": {"role": "assistant", "content": text},
                                          "confidence": conf}],
                             "usage": {"prompt_tokens": r["n_in"], "completion_tokens": r["n_out"]},
                             "parsed_ok": parse_output(text)["ok"]})

        def log_message(self, *args):
            pass

    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
