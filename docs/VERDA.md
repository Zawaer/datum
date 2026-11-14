# Verda tech track: Blueprints That Talk

Drafts for the Verda track entry (Junction 2026, Stoa challenge "Make Blueprints Talk"). Every number is in
the facts table below with its source. Placeholders: `<DEMO_URL>`, `<REPO_URL>` (nothing is public yet).

## 1. Track summary (submission form)

Blueprints That Talk answers questions about construction drawings and BIM models and shows where on the
drawing each answer came from. On all 25,420 held-out test questions it is right 90.0 % of the time, at
$0.013 per 1,000 questions in API fees; Claude Sonnet 5.5 given the same CAD/IFC files gets 69.8 % at $25.76
per 1,000.

We used Verda for two things. First, overnight GPU iteration: two H100 80GB machines ran side by side for
about eight hours (14.9 GPU-hours, about $77). One fine-tuned Qwen3-VL-8B with LoRA on dev-split drawings
only, so it answers counting questions with one box per counted item; the other tried a Gemma-family
alternative (PaliGemma 2, 52 % on dev, not shipped) and ran zero-shot evaluations. The fine-tuned model went
from 42.6 % zero-shot to 76 % on dev and 73.0 % on a 1,000-question test sample (74.9 % on all 16,496
Finnish-plan test questions). On its own it is weaker than our detector (85.1 %), so we ship it as an
independent second opinion: when the two agree (73.8 % of those questions) the answer is right 94.9 % of the
time; when they disagree we lower confidence instead of guessing.

Second, cheap always-on hosting: the public demo runs on a Verda CPU.4V.16G VM (Docker + Caddy) at $0.048
per hour, about $1.15 a day. The detector was trained on a local RTX 4070.

Demo: `<DEMO_URL>` · Code: `<REPO_URL>`

## 2. Discord post

Blueprints That Talk (Stoa track) on Verda: two H100s overnight, 14.9 GPU-hours, about $77. We LoRA
fine-tuned Qwen3-VL-8B to count symbols on floor plans with one box per item: 42.6 % zero-shot to 76 % on dev drawings,
73.0 % on held-out test questions. It is weaker than our detector, so it ships as a second opinion: when both agree,
answers are 94.9 % right. A PaliGemma 2 attempt reached 52 % and stayed out. The demo lives on a Verda
CPU.4V.16G VM for $0.048/h. Whole system: 90.0 % on 25,420 test questions at $0.013 per 1,000.
Demo: `<DEMO_URL>` · Code: `<REPO_URL>`

## 3. Facts and sources

| claim | value | source |
|---|---|---|
| Headline accuracy, all held-out test questions | 90.0 % [89.7–90.4] on 25,420 | `README.md` l.6–7, `docs/RESULTS.md`, `runs/router_full_test_v7` |
| Our API cost | $0.013 per 1,000 questions | `docs/COSTS.md`, `README.md` |
| Claude Sonnet 5.5 + same CAD/IFC files | 69.8 % [60.9–78.4], $25.76 per 1,000 (re-weighted 400-question sample) | `README.md` l.40, `docs/RESULTS.md` l.41, `docs/COSTS.md` |
| VLM training machine | 1x H100 80GB `stoa-h100`, 8.0 h × $5.19/h = $41.61 | `docs/COSTS.md`, `analysis/infra.json` |
| Second H100 (PaliGemma 2 + zero-shot evals) | 1x H100 80GB `stoa-h100-b`, 6.9 h × $5.189/h = $35.72 | `docs/COSTS.md`, `analysis/infra.json` |
| Total Verda GPU | 14.9 GPU-h, $77.33, both overnight 13–14 Nov (20:14 / 21:22 to 04:15 UTC) | `analysis/infra.json`, `docs/STATUS.md` |
| Model | Qwen3-VL-8B-Instruct + LoRA r32, flash-attn2, dev-split drawings only | `train/vlm/README.md` |
| Zero-shot → r2 → r3 (dev-val) | 42.6 % → 62 % → 76 % | `train/vlm/README.md` (Results) |
| r3 alone, 1,000-question test sample | 73.0 % (CubiCasa 73.8 %, Swiss 72.2 %) | `runs/vlm_q3vl8b_r3_test1000.summary.md` |
| r3 alone, all CubiCasa test questions | 74.9 % on 16,496 | `runs/vlm_r3_cubicasa_test_full.summary.md` |
| Detector alone on the same questions (flip TTA) | 85.1 % | `runs/crosscheck_vlm_test_v7.summary.md` |
| Agreement share / accuracy on agreement | 73.8 % (12,178 q) / 94.9 % | `runs/crosscheck_vlm_test_v7.summary.md` |
| On conflict: detector / VLM right | 57.3 % / 18.6 % (so never switch to the VLM's answer) | `runs/crosscheck_vlm_test_v7.summary.md` |
| Second-opinion inference cost | $0.16 per 1,000 (16,496 q in 31 min on one H100) | `runs/vlm_r3_cubicasa_test_full.summary.md`, `train/vlm/README.md` |
| PaliGemma 2 3B-896 + LoRA | 52 % on dev-val, not shipped | `train/vlm/README.md`, `docs/STATUS.md` |
| Demo hosting | Verda CPU.4V.16G, Docker (app + Caddy, automatic HTTPS), $0.048/h; serves the VLM's precomputed answers, no GPU | `docs/COSTS.md`, `analysis/infra.json`, `deploy/README.md` |
| Detector training | YOLO11m on a local RTX 4070, 1–2 h per run, ~5 GPU-h total | `docs/COSTS.md`, `docs/STATUS.md`, `train/cubicasa/README.md` |
| Total build cost (all providers) | $174.81 | `docs/COSTS.md` |

Notes: "73.8 % of raster questions" means the CubiCasa (raster floor-plan) test questions. The $77 covers both
H100s; the Qwen run itself was the $41.61 machine. No Verda track description is in the repo; check the
Junction platform for required fields before submitting.
