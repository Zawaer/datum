"""Run the grounded-counting VLM on one drawing: local HF model (+ LoRA) or a remote OpenAI-compatible server.

Environment
- BP_VLM_URL       e.g. http://gpu-host:8000/v1 : use a vLLM / OpenAI-compatible server (no local GPU needed)
- BP_VLM_SERVED    model name on that server (default "blueprints", the LoRA name in the README's vllm command)
- BP_VLM_KEY       bearer token for the server, if it wants one (BP_VLM_API_KEY is read too)
- BP_VLM_TIMEOUT   seconds per remote request (default 300; the live second opinion uses its own, shorter one)
- BP_VLM_MODEL     base model for local inference (default: the adapter's base, else Qwen/Qwen3-VL-8B-Instruct)
- BP_VLM_ADAPTER   LoRA adapter directory (train/vlm/train.py output) for local inference
- BP_VLM_4BIT=1    load the local base in 4-bit (bitsandbytes), for small GPUs
- BP_VLM_MAX_NEW   max new tokens (default 2048)

    from bp.vlm.infer import get_runner
    r = get_runner().ask(pil_image, "How many windows ...?", source="cubicasa5k")
    r -> {"text", "parsed": {"items", "count", "ok"}, "confidence", "seconds", "backend"}
"""
from __future__ import annotations

import base64
import io
import json
import os
import threading
import time
import urllib.request
from pathlib import Path

from PIL import Image

from bp.vlm.format import (SYSTEM, budget_for, decision_confidence, is_paligemma, messages, pali_decision_confidence,
                           parse_output, parse_paligemma, prepare_image, user_text)

DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"


class LocalRunner:
    backend = "local"

    def __init__(self, model: str | None = None, adapter: str | None = None, load_4bit: bool | None = None,
                 device: str | None = None):
        self.adapter = adapter if adapter is not None else os.environ.get("BP_VLM_ADAPTER") or None
        base = model or os.environ.get("BP_VLM_MODEL")
        if not base and self.adapter and (Path(self.adapter) / "adapter_config.json").exists():
            base = json.loads((Path(self.adapter) / "adapter_config.json").read_text()).get("base_model_name_or_path")
        self.model_name = base or DEFAULT_MODEL
        self.load_4bit = load_4bit if load_4bit is not None else os.environ.get("BP_VLM_4BIT") == "1"
        self.device = device
        self.max_new = int(os.environ.get("BP_VLM_MAX_NEW", 2048))
        self._lock = threading.Lock()
        self._model = None

    def load(self):
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        kw = {"dtype": torch.bfloat16}
        if self.load_4bit:
            from transformers import BitsAndBytesConfig

            kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                           bnb_4bit_compute_dtype=torch.bfloat16)
        dev = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        kw["device_map"] = dev
        m = AutoModelForImageTextToText.from_pretrained(self.model_name, **kw)
        if self.adapter:
            from peft import PeftModel

            m = PeftModel.from_pretrained(m, self.adapter)
        m.eval()
        self.processor = AutoProcessor.from_pretrained(self.adapter or self.model_name)
        self._model = m

    def ask(self, image: Image.Image, question: str, source: str | None = None, prepared: bool = False) -> dict:
        import torch

        self.load()
        img = image if prepared else prepare_image(image, budget_for(source))
        pali = is_paligemma(self.model_name)
        with self._lock:
            t0 = time.time()
            if pali:  # prefix = question; the processor adds the image tokens and resizes to its fixed square
                inputs = self.processor(text="<image>" + user_text(question), images=img.convert("RGB"),
                                        return_tensors="pt")
                inputs = inputs.to(self._model.device)
                inputs["pixel_values"] = inputs["pixel_values"].to(self._model.dtype)
            else:
                inputs = self.processor.apply_chat_template(messages(question, img), tokenize=True,
                                                            add_generation_prompt=True, return_dict=True,
                                                            return_tensors="pt")
                inputs = inputs.to(self._model.device)
            with torch.inference_mode():
                out = self._model.generate(**inputs, max_new_tokens=self.max_new, do_sample=False,
                                           output_scores=True, return_dict_in_generate=True)
            seq = out.sequences[0, inputs["input_ids"].shape[1]:]
            scores = self._model.compute_transition_scores(out.sequences, out.scores, normalize_logits=True)[0]
            tok = self.processor.tokenizer
            if pali:  # <loc> tokens must survive decoding; keep <eos> as the stop decision
                toks = [(tok.decode([int(t)]), float(s)) for t, s in zip(seq, scores) if int(t) != tok.pad_token_id]
                text = tok.decode(seq, skip_special_tokens=False).replace("<eos>", "").replace("<pad>", "").strip()
                parsed, conf = parse_paligemma(text), pali_decision_confidence(toks)
            else:
                toks = [(tok.decode([int(t)]), float(s)) for t, s in zip(seq, scores) if int(t) not in tok.all_special_ids]
                text = tok.decode(seq, skip_special_tokens=True)
                parsed, conf = parse_output(text), decision_confidence(toks)
            dt = time.time() - t0
        return {"text": text, "parsed": parsed, "confidence": conf,
                "seconds": round(dt, 2), "backend": f"local:{self.model_name}" + (f"+{self.adapter}" if self.adapter else ""),
                "n_in": int(inputs["input_ids"].shape[1]), "n_out": len(seq)}


class RemoteRunner:
    """OpenAI-compatible chat completions (vLLM `vllm serve ... --enable-lora --lora-modules blueprints=...`)."""
    backend = "remote"

    def __init__(self, url: str | None = None, model: str | None = None, key: str | None = None,
                 timeout: float | None = None):
        self.url = (url or os.environ["BP_VLM_URL"]).rstrip("/")
        if not self.url.endswith("/chat/completions"):
            self.url += "/chat/completions"
        self.model = model or os.environ.get("BP_VLM_SERVED", "blueprints")
        self.key = key or os.environ.get("BP_VLM_KEY") or os.environ.get("BP_VLM_API_KEY")
        self.timeout = timeout or float(os.environ.get("BP_VLM_TIMEOUT", 300) or 300)
        self.max_new = int(os.environ.get("BP_VLM_MAX_NEW", 2048))

    def ask(self, image: Image.Image, question: str, source: str | None = None, prepared: bool = False) -> dict:
        img = image if prepared else prepare_image(image, budget_for(source))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        body = {"model": self.model, "temperature": 0, "max_tokens": self.max_new, "logprobs": True,
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}},
                                                          {"type": "text", "text": user_text(question)}]}]}
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {self.key}"} if self.key else {})})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            res = json.loads(r.read())
        dt = time.time() - t0
        ch = res["choices"][0]
        text = ch["message"]["content"] or ""
        lp = (ch.get("logprobs") or {}).get("content") or []
        toks = [(t["token"], t["logprob"]) for t in lp]
        u = res.get("usage") or {}
        conf = decision_confidence(toks) if toks else ch.get("confidence")  # deploy/vlm/hf_server.py sends its own
        return {"text": text, "parsed": parse_output(text), "confidence": conf,
                "seconds": round(dt, 2), "backend": f"remote:{self.model}", "n_in": u.get("prompt_tokens"),
                "n_out": u.get("completion_tokens")}


_RUNNER = None
_RUNNER_LOCK = threading.Lock()


def get_runner(**kw):
    """Remote if BP_VLM_URL is set, else local; one shared instance per process."""
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is None or kw:
            r = RemoteRunner() if os.environ.get("BP_VLM_URL") and not kw else LocalRunner(**kw)
            if kw:
                return r
            _RUNNER = r
        return _RUNNER


def load_drawing(path: Path) -> Image.Image | None:
    """PIL image of a drawing: PNG/JPG directly, PDF page 0 rendered at 150 dpi (the Swiss PNGs' resolution)."""
    ext = path.suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"):
        return Image.open(path)
    if ext == ".pdf":
        import pymupdf

        with pymupdf.open(path) as doc:
            pix = doc[0].get_pixmap(dpi=150)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return None
