# Grounded-counting VLM (Qwen3-VL + LoRA)

A small open vision-language model fine-tuned to answer counting questions about floor plans with **one box
per counted instance plus the count**, as JSON, so every answer arrives with numbered box evidence
(`docs/EVIDENCE.md`). Solver: `vlm` (`bp/solvers/vlm.py`); inference: `bp/vlm/infer.py`; prompt / image
budget / output format shared by training and inference: `bp/vlm/format.py`.

```json
{"items": [{"label": "window", "bbox_2d": [412, 88, 455, 97]}, ...], "count": 7}
```

Coordinates are integers 0..1000 relative to image width / height (Qwen3-VL's native grounding convention).

## Model

**Qwen3-VL-8B-Instruct** (Apache-2.0). Chosen over Qwen2.5-VL-7B because Qwen3-VL grounds in relative
0..1000 coordinates (no dependence on the resize, maps 1:1 to our normalised evidence), is stronger on
documents / OCR (room labels), and has first-class support in transformers 5.x, PEFT, TRL and vLLM. The
newer Qwen3.5 small models (9B / 4B) were considered: their hybrid Gated-DeltaNet layers need extra kernels
(an issue on ROCm and for LoRA tooling) and they think by default; `--model Qwen/Qwen3.5-9B` should work with
the same scripts but is untested. The 2B / 4B Qwen3-VL variants are good for smoke tests and cheap serving.

## Data (`train/vlm/build_dataset.py`)

Dev-split drawings only: test drawings (`bp.data.split_of(path) == "test"`) are dropped before anything is
read, and every written / loaded row is asserted to be dev. ~10 % of dev drawings (md5 rule shared with the
YOLO validation split) form `val.jsonl`.

- **cubicasa5k** (en + fi): per-instance boxes from the public CubiCasa5K SVG annotations, classified with
  `bp/cubicasa/classes.py` (rules checked against gold by `train/cubicasa/check_gold.py`). Kept only when the
  annotated count equals the gold answer: 68,812 / 69,018 questions (99.7 %); the losses are mostly glazed
  balconies (142).
- **swiss_dwellings** (en / de / fr / it): questions asked on the PDF, posed on the PNG twin (same A3 page at
  150 dpi, so normalised page coordinates are PNG coordinates; overlays checked); instances from the exact DXF
  parser through the Swiss solver's own evidence. 19,988 / 19,988 kept.

| split | examples | drawings | cubicasa / swiss | en / fi / de / fr / it | mean visual tokens |
|---|---|---|---|---|---|
| train | 80,362 | 4,229 | 62,438 / 17,924 | 40,181 / 31,219 / 5,926 / 2,181 / 855 | 1,563 |
| val | 8,430 | 448 | 6,374 / 2,056 | 4,215 / 3,187 / 732 / 251 / 45 | 1,612 |

By default `train.py` keeps one language variant per (drawing, question) (`--no-dedup` keeps all): 38,533
training examples, ~73 M tokens per epoch.

**Resolution.** Images are pre-resized to the model's 32 px grid so the processor never resizes again
(`bp.vlm.format.BUDGET`). `--measure` prints, per budget, the share of symbol instances (WC, sink, door,
window, ...) whose size (sqrt of box area) falls below N px:

| source | min / max pixels | visual tokens | < 8 px | < 12 px | < 16 px |
|---|---|---|---|---|---|
| cubicasa5k | native (no upscale), max 1280² | 709 | 2.6 % | 7.6 % | 15.8 % |
| cubicasa5k | **upscale to ≥ 1024², max 1280²** | 1,142 | 1.3 % | 2.7 % | 6.0 % |
| swiss | max 1280² | 1,551 | 3.6 % | 18.6 % | 35.8 % |
| swiss | **max 1792²** | 3,102 | 0.0 % | 5.3 % | 16.6 % |
| swiss | max 2048² | 4,028 | 0.0 % | 2.1 % | 11.1 % |

No tiling: a count has to be made on the whole plan, and tiles would split symbols and double count.

```bash
.venv/bin/python train/vlm/build_dataset.py --overlays 4   # -> cache/vlm/{train,val}.jsonl, img/, stats.json, overlays/
```

## Remote GPU (fresh Ubuntu + NVIDIA VM)

```bash
H=root@<vm-ip>
ssh $H mkdir -p /root/bp-vlm/cache/vlm
rsync -az --relative bp/__init__.py bp/data.py bp/vlm train/vlm $H:/root/bp-vlm/
rsync -az cache/vlm/train.jsonl cache/vlm/val.jsonl cache/vlm/stats.json cache/vlm/img $H:/root/bp-vlm/cache/vlm/  # 2.2 GB, dev only
ssh $H 'bash /root/bp-vlm/train/vlm/setup_remote.sh Qwen/Qwen3-VL-8B-Instruct'   # venv, pinned deps, vLLM, weights

# train (tmux so it survives the ssh session; mkdir first or the log redirect fails)
ssh $H 'cd /root/bp-vlm && mkdir -p cache/vlm/runs && tmux new -d -s train "HF_HOME=cache/hf .venv/bin/python \
  train/vlm/train.py --model Qwen/Qwen3-VL-8B-Instruct --out cache/vlm/runs/q3vl8b --epochs 1 --batch 4 \
  --grad-accum 4 --max-len 12288 --attn kernels-community/flash-attn2 --save-steps 200 --eval-steps 200 \
  --max-val 100 > cache/vlm/runs/q3vl8b.log 2>&1"'

# evaluate the adapter on held-out dev-val questions
ssh $H 'cd /root/bp-vlm && HF_HOME=cache/hf .venv/bin/python train/vlm/eval_vlm.py --n 400 \
  --adapter cache/vlm/runs/q3vl8b/final --out cache/vlm/eval_q3vl8b.jsonl'

# serve base + adapter (OpenAI-compatible) for the app / router
ssh $H 'cd /root/bp-vlm && tmux new -d -s serve "HF_HOME=cache/hf .venv-vllm/bin/vllm serve Qwen/Qwen3-VL-8B-Instruct \
  --enable-lora --lora-modules blueprints=cache/vlm/runs/q3vl8b/final --max-lora-rank 32 \
  --max-model-len 8192 --limit-mm-per-prompt.image 1 --host 0.0.0.0 --port 8000"'
# then locally: BP_VLM_URL=http://<host>:8000/v1 .venv/bin/python eval.py --solver vlm ...

# pull checkpoints back
rsync -az $H:/root/bp-vlm/cache/vlm/runs/ cache/vlm/runs/
```

Local inference instead: `BP_VLM_ADAPTER=cache/vlm/runs/q3vl8b/final` (base model read from the adapter
config; `BP_VLM_4BIT=1` for small GPUs).

**Slurm / ROCm cluster** (best effort, untested end to end): `train/vlm/slurm_rocm.sbatch`, one node,
torchrun over its GPUs, bf16 LoRA with sdpa attention (no bitsandbytes / flash-attn needed).

Notes from the first H100 runs: `--attn kernels-community/flash-attn2` (prebuilt kernel from the `kernels`
package) is ~2.3x faster than `sdpa`; batch 1 is slower, not faster. A few Swiss examples with long item lists
reach ~6.6 k tokens, hence `--max-len 12288`. Memory at batch 4 with gradient checkpointing: ~39 GB.

## Cost

Measured on 1x H100 80GB (Qwen3-VL-8B, LoRA r32, batch 4 x accum 4, flash-attn2, grad checkpointing):
~7.5 s per optimizer step of 16 examples (~2 examples/s, ~4 k tokens/s). One deduplicated epoch is 38.5 k
examples = 2,409 steps = **~5 GPU-hours (~$26 at $5.19/h)**; all language variants (80 k examples) would be
~10.5 GPU-hours. Qwen3-VL-4B should be roughly 2x faster.
