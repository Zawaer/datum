"""LoRA (or full) SFT of a Qwen-VL model for grounded counting on floor plans.

Single GPU / single node (CUDA or ROCm):
    python train/vlm/train.py --data cache/vlm --out cache/vlm/runs/q3vl8b
    torchrun --nproc_per_node 8 train/vlm/train.py --data cache/vlm --out cache/vlm/runs/q3vl8b
Smoke test (tiny, 4-bit, a few steps):
    python train/vlm/train.py --model Qwen/Qwen3-VL-2B-Instruct --load-4bit --max-steps 4 --max-train 16 \
        --max-val 4 --batch 1 --grad-accum 1 --out cache/vlm/runs/smoke

Data: cache/vlm/{train,val}.jsonl from train/vlm/build_dataset.py (image paths relative to --data). Every
row is asserted to come from a dev-split drawing. The loss is on the assistant reply only.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bp.data import split_of  # noqa: E402
from bp.vlm.format import messages  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
LLM_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def est_len(r) -> int:
    """Sequence length estimate: visual tokens (32x32 px each) + system/question + reply."""
    w, h = r["image_size"]
    return int(w * h / 1024 + 230 + len(r["answer"]) / 3.2)


def load_rows(f: Path, n: int, seed: int, balance: int = 0, dedup: bool = False):
    rows = [json.loads(line) for line in open(f)]
    for r in rows:
        assert split_of(r["path"]) == "dev", f"test drawing in training data: {r['path']}"  # leakage rule
        r["length"] = est_len(r)
    random.Random(seed).shuffle(rows)
    if dedup:  # en/fi (de/fr/it) variants of one question share the reply: keep one, language picked at random
        seen = set()
        rows = [r for r in rows if (r["path"], r["answer"]) not in seen and not seen.add((r["path"], r["answer"]))]
    if balance:  # cap examples per (source, target): keeps rare classes and Swiss from being drowned
        seen, keep = {}, []
        for r in rows:
            k = (r["source"], r["target"])
            if seen.get(k, 0) < balance:
                keep.append(r)
                seen[k] = seen.get(k, 0) + 1
        rows = keep
    return rows[:n] if n else rows


class Collator:
    """Messages -> chat template -> processor; labels masked to the assistant reply (+ its end token)."""

    def __init__(self, processor, data_dir: Path, max_len: int):
        self.p = processor
        self.dir = data_dir
        self.max_len = max_len
        tok = processor.tokenizer
        self.start = tok.encode("<|im_start|>assistant\n", add_special_tokens=False)
        self.pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id

    def __call__(self, rows):
        texts, images = [], []
        for r in rows:
            img = Image.open(self.dir / r["image"]).convert("RGB")  # already on the model grid
            texts.append(self.p.apply_chat_template(messages(r["question"], img, r["answer"]), tokenize=False))
            images.append(img)
        b = self.p(text=texts, images=images, return_tensors="pt", padding=True, padding_side="right")
        ids = b["input_ids"]
        labels = torch.full_like(ids, -100)
        n = len(self.start)
        for i in range(ids.shape[0]):
            row = ids[i].tolist()
            pos = max(j for j in range(len(row) - n + 1) if row[j:j + n] == self.start) + n
            end = int(b["attention_mask"][i].sum())
            labels[i, pos:end] = ids[i, pos:end]
        b["labels"] = labels
        if ids.shape[1] > self.max_len:
            raise ValueError(f"sequence of {ids.shape[1]} tokens > --max-len {self.max_len}; raise it "
                             "(cutting would drop image tokens)")
        return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    ap.add_argument("--data", default=str(ROOT / "cache/vlm"))
    ap.add_argument("--out", default=str(ROOT / "cache/vlm/runs/q3vl8b"))
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--max-train", type=int, default=0, help="subsample the training set (0 = all)")
    ap.add_argument("--balance", type=int, default=0, help="cap train examples per (source, target)")
    ap.add_argument("--no-dedup", action="store_true", help="keep every language variant of a question")
    ap.add_argument("--max-val", type=int, default=400)
    ap.add_argument("--batch", type=int, default=4, help="per-device batch size")
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--lora-r", type=int, default=32)
    ap.add_argument("--lora-alpha", type=int, default=64)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--tune-vision", action="store_true", help="also LoRA the vision tower + merger")
    ap.add_argument("--full", action="store_true", help="full fine-tune of the language model (no LoRA)")
    ap.add_argument("--load-4bit", action="store_true", help="QLoRA (bitsandbytes; CUDA only)")
    ap.add_argument("--max-len", type=int, default=6144)
    ap.add_argument("--attn", default=os.environ.get("BP_ATTN", "sdpa"), help="sdpa | flash_attention_2 | eager")
    ap.add_argument("--no-gc", action="store_true", help="no gradient checkpointing (faster, more memory)")
    ap.add_argument("--eval-steps", type=int, default=500)
    ap.add_argument("--save-steps", type=int, default=500)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cpu", action="store_true", help="debug on CPU (bf16)")
    ap.add_argument("--report-to", default="none")
    a = ap.parse_args()

    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForImageTextToText, AutoProcessor
    from trl import SFTConfig, SFTTrainer

    data = Path(a.data)
    train_rows = load_rows(data / "train.jsonl", a.max_train, a.seed, a.balance, not a.no_dedup)
    val_rows = load_rows(data / "val.jsonl", a.max_val, a.seed, dedup=True) if a.max_val else []
    print(f"train {len(train_rows)} ({sum(r['length'] for r in train_rows) / 1e6:.1f}M tokens est.)  "
          f"val {len(val_rows)}", flush=True)

    processor = AutoProcessor.from_pretrained(a.model)
    kw = {"dtype": torch.bfloat16, "attn_implementation": a.attn}
    if a.load_4bit:
        from transformers import BitsAndBytesConfig

        kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                       bnb_4bit_compute_dtype=torch.bfloat16,
                                                       bnb_4bit_use_double_quant=True)
    if a.cpu:
        kw["device_map"] = "cpu"
    elif a.load_4bit or int(os.environ.get("WORLD_SIZE", 1)) == 1:
        kw["device_map"] = {"": int(os.environ.get("LOCAL_RANK", 0))}
    model = AutoModelForImageTextToText.from_pretrained(a.model, **kw)
    model.config.use_cache = False

    if a.full:
        for n, p in model.named_parameters():
            p.requires_grad = "visual" not in n or a.tune_vision
    else:
        if a.load_4bit:
            model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=not a.no_gc)
        # language-model linears by name; vision blocks (qkv / proj / mlp.linear_fc*) only with --tune-vision
        targets = [n for n, m in model.named_modules() if isinstance(m, torch.nn.Linear) or "Linear" in type(m).__name__]
        lm = [n for n in targets if "visual" not in n and n.split(".")[-1] in LLM_TARGETS]
        vis = [n for n in targets if "visual" in n and n.split(".")[-1] in ("qkv", "proj", "linear_fc1", "linear_fc2")]
        cfg = LoraConfig(r=a.lora_r, lora_alpha=a.lora_alpha, lora_dropout=a.lora_dropout, bias="none",
                         target_modules=lm + (vis if a.tune_vision else []), task_type="CAUSAL_LM")
        model = get_peft_model(model, cfg)
        model.print_trainable_parameters()

    from datasets import Dataset

    cfg = SFTConfig(
        output_dir=a.out, num_train_epochs=a.epochs, max_steps=a.max_steps,
        per_device_train_batch_size=a.batch, per_device_eval_batch_size=a.batch,
        gradient_accumulation_steps=a.grad_accum, learning_rate=a.lr, lr_scheduler_type="cosine",
        warmup_steps=0.03, weight_decay=0.0, bf16=not a.cpu, logging_steps=5,
        eval_strategy="steps" if val_rows else "no", eval_steps=a.eval_steps, save_strategy="steps",
        save_steps=a.save_steps, save_total_limit=3, gradient_checkpointing=not a.no_gc,
        gradient_checkpointing_kwargs={"use_reentrant": False}, dataloader_num_workers=a.workers,
        remove_unused_columns=False, dataset_kwargs={"skip_prepare_dataset": True}, max_length=None,
        train_sampling_strategy="group_by_length", length_column_name="length",  # less padding
        report_to=a.report_to, seed=a.seed, use_cpu=a.cpu, ddp_find_unused_parameters=False,
    )
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=Dataset.from_list(train_rows),
                         eval_dataset=Dataset.from_list(val_rows) if val_rows else None,
                         data_collator=Collator(processor, data, a.max_len), processing_class=processor)
    trainer.train(resume_from_checkpoint=any(Path(a.out).glob("checkpoint-*")) or None)
    final = Path(a.out) / "final"
    trainer.save_model(str(final))
    processor.save_pretrained(str(final))
    (final / "train_args.json").write_text(json.dumps(vars(a), indent=1))
    print("saved", final, flush=True)


if __name__ == "__main__":
    main()
