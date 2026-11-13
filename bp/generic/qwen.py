"""Local open VLM (Qwen3-VL Instruct) for grounded answers: boxes in 0..1000 relative coords.

Loaded lazily, once per process, 4-bit NF4 by default so it fits beside another GPU job
(~3.5 GB VRAM for the 4B model at ~1.6 MP inputs). All calls are serialised by a lock;
gpu_seconds is accumulated so the solver can report GPU time per question.

env: GENERIC_VLM (HF id, default Qwen/Qwen3-VL-4B-Instruct), GENERIC_VLM_QUANT (nf4|bf16),
HF_HOME defaults to cache/hf.
"""
from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("HF_HOME", os.path.abspath("cache/hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

MODEL_ID = os.environ.get("GENERIC_VLM", "Qwen/Qwen3-VL-4B-Instruct")
QUANT = os.environ.get("GENERIC_VLM_QUANT", "nf4")

_lock = threading.Lock()
_state: dict = {}


def load():
    if "model" in _state:
        return _state["model"], _state["proc"]
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    kw = {"dtype": torch.bfloat16, "device_map": "cuda:0"}
    if QUANT == "nf4":
        from transformers import BitsAndBytesConfig

        kw["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True, llm_int8_skip_modules=["visual", "lm_head"])
    model = AutoModelForImageTextToText.from_pretrained(MODEL_ID, **kw).eval()
    proc = AutoProcessor.from_pretrained(MODEL_ID)
    _state.update(model=model, proc=proc, gpu_s=0.0)
    return model, proc


def generate(prompt: str, images=(), max_new_tokens: int = 1024, max_pixels: int = 1600 * 1600) -> tuple[str, float]:
    """(reply text, gpu seconds). images: PIL images placed before the prompt."""
    import torch

    with _lock:
        model, proc = load()
        content = [{"type": "image", "image": im} for im in images] + [{"type": "text", "text": prompt}]
        msgs = [{"role": "user", "content": content}]
        ip = getattr(proc, "image_processor", None)
        if ip is not None:  # pixel budget per image (dynamic resolution)
            if hasattr(ip, "size") and isinstance(ip.size, dict):
                ip.size = {**ip.size, "longest_edge": max_pixels}
            if hasattr(ip, "max_pixels"):
                ip.max_pixels = max_pixels
        inputs = proc.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                          return_dict=True, return_tensors="pt").to(model.device)
        t0 = time.time()
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                                 repetition_penalty=1.05)
        torch.cuda.synchronize()
        dt = time.time() - t0
        _state["gpu_s"] += dt
        text = proc.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]
        del inputs, out
        return text, dt


def vram_gb() -> float:
    import torch

    return torch.cuda.max_memory_allocated() / 1e9 if torch.cuda.is_available() else 0.0
