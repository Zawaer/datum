# Verda tech track: Blueprints That Talk

Texts for the Verda Compute Track entry (Junction 2026, Stoa challenge "Make Blueprints Talk"); the same texts are in
[SIDE-CHALLENGES.md](SIDE-CHALLENGES.md). Every number is in the facts table below with its source. Placeholders:
`<DEMO_URL>`, `<REPO_URL>`, `<RESULT>` (outcome of the Sat 14.11 sweep), `<SWEEP_COST>` (its GPU-hours and $, add
the machines to `analysis/infra.json` and re-run `analysis/costs.py`).

## 1. Track summary (submission form, ≤ 300 words)

Blueprints That Talk answers questions about construction drawings and BIM models, with the proof drawn on
the plan. On all 25,420 held-out test questions it is right 90.0 % of the time at $0.013 per 1,000 questions in
API fees; Claude Sonnet 5.5 given the same CAD/IFC files gets 69.8 % at $25.76 per 1,000.

Verda ran four parts of it:

1. **Overnight fine-tune, 2× H100 80GB.** 14.9 GPU-hours, $77.33. One
   LoRA-tuned Qwen3-VL-8B on dev drawings to count symbols with one box per item: 42.6 %
   zero-shot to 76 % on dev, 74.9 % on all 16,496 Finnish-plan test questions. The other tried PaliGemma 2
   (52 %, not shipped). The model is weaker than our detector (85.1 %), so it ships as an independent second
   opinion: when both agree (73.8 %), answers are 94.9 % right.
2. **Today's sweep, 2× H100.** A bigger detector and detector-vs-VLM arbitration, selected by whole-pipeline
   cross-validation on dev drawings. <RESULT>
3. **Live serving, RTX PRO 6000 96GB ($2.89/h).** The fine-tuned model checks users' own uploaded plans. It runs
   on demand: an upload starts the GPU, it stops when idle, and a daily cap bounds the bill. 96 GB holds the 8B
   model at a little over half the H100 rate.
4. **Public demo, CPU.4V.16G VM** (Docker + Caddy), $0.048/h: numeric answers need no GPU.

Verda so far: $99.83 of our $196.68 build cost, plus the sweep (<SWEEP_COST>).

**How it scales.** Per 1,000 questions we pay $0.013 in API fees plus about $0.006 of local compute; the VLM
second opinion adds $0.16 per 1,000 on one H100 (16,496 questions in 31 minutes). Next step: serve the model from Verda's autoscaling
serverless containers (scale to zero, scale with load) and run re-checks of a whole drawing set, every revision, as batch jobs.

Demo: `<DEMO_URL>` · Code: `<REPO_URL>`

## 2. Discord post (≤ 120 words)

Blueprints That Talk (Stoa "Make Blueprints Talk") on Verda. Two H100s overnight (14.9 GPU-h, $77.33):
we LoRA-tuned Qwen3-VL-8B to count symbols on floor plans with one box per item, 42.6 % zero-shot to 76 % on
dev. It ships as a second opinion to our detector: when both agree, answers are 94.9 % right. Today 2× H100
swept a bigger detector plus VLM arbitration: <RESULT>. An RTX PRO 6000 serves the model live on users'
uploads, started on upload, stopped when idle, capped daily. The demo runs on a CPU VM for $0.048/h. Whole
system: 90.0 % on 25,420 test questions at $0.013 per 1,000.
Demo: `<DEMO_URL>` · Code: `<REPO_URL>`

## 3. Facts and sources

| claim | value | source |
|---|---|---|
| Headline accuracy, all held-out test questions | 90.0 % [89.7–90.4] on 25,420 | `README.md`, `docs/RESULTS.md`, `runs/router_full_test_v7` |
| Our API cost | $0.013 per 1,000 questions (+ ~$0.006 local compute) | `docs/COSTS.md`, `README.md` |
| Claude Sonnet 5.5 + same CAD/IFC files | 69.8 % [60.9–78.4], $25.76 per 1,000 (re-weighted 400-question sample) | `README.md`, `docs/RESULTS.md`, `docs/COSTS.md` |
| VLM training machine | 1x H100 80GB `stoa-h100`, 8.0 h × $5.19/h = $41.61 | `docs/COSTS.md`, `analysis/infra.json` |
| Second H100 (PaliGemma 2 + zero-shot evals) | 1x H100 80GB `stoa-h100-b`, 6.9 h × $5.189/h = $35.72 | `docs/COSTS.md`, `analysis/infra.json` |
| Overnight H100 total | 14.9 GPU-h, $77.33, 13–14 Nov (20:14 / 21:22 to 04:15 UTC) | `analysis/infra.json` |
| Model | Qwen3-VL-8B-Instruct + LoRA r32, flash-attn2, dev-split drawings only | `train/vlm/README.md` |
| Zero-shot → r2 → r3 (dev-val) | 42.6 % → 62 % → 76 % | `train/vlm/README.md` (Results) |
| r3 alone, 1,000-question test sample | 73.0 % | `README.md`, `runs/vlm_q3vl8b_r3c2200_test1000.summary.md` |
| r3 alone, all CubiCasa (Finnish-plan) test questions | 74.9 % on 16,496 | `runs/vlm_r3_cubicasa_test_full.summary.md` |
| Detector alone on the same questions (flip TTA) | 85.1 % | `README.md`, `runs/crosscheck_vlm_test_v7.summary.md` |
| Agreement share / accuracy on agreement | 73.8 % / 94.9 % | `runs/crosscheck_vlm_test_v7.summary.md` |
| On conflict: detector / VLM right | 57.3 % / 18.6 % (so never switch to the VLM's answer) | `runs/crosscheck_vlm_test_v7.summary.md` |
| Second-opinion inference cost | $0.16 per 1,000 (16,496 q in 31 min on one H100) | `runs/vlm_r3_cubicasa_test_full.summary.md`, `train/vlm/README.md` |
| PaliGemma 2 3B-896 + LoRA | 52 % on dev-val, not shipped | `train/vlm/README.md` |
| Sweep, Sat 14.11 | 2× H100: bigger detector (YOLO / RT-DETR, ensembles with flip WBF) + detector-vs-VLM arbiter, whole-pipeline 2-fold dev CV vs the shipped detector; outcome `<RESULT>`, cost `<SWEEP_COST>` | commits `134013b`, `932e822`, `fde0079` |
| Live serving | 1x RTX PRO 6000 96GB (confidential compute), $2.89/h, transformers + PEFT behind Caddy TLS, firewall allows only the demo VM; on demand (starts on upload, stops when idle, daily cap) | `deploy/vlm/serve.sh`, `bp/vlm/live.py`, `analysis/infra.json` |
| Live serving cost in COSTS.md | Sat 2.1 h = $5.94; Sun window budgeted 5.5 h = $15.90 (7.6 h, $21.84) | `docs/COSTS.md` |
| Demo hosting | Verda CPU.4V.16G, Docker (app + Caddy, automatic HTTPS), $0.048/h (~$1.15/day); $0.66 at 13.8 h when COSTS.md was generated | `docs/COSTS.md`, `analysis/infra.json`, `deploy/README.md` |
| Verda total so far | $99.83 (77.33 + 5.94 + 15.90 + 0.66), excluding the sweep | `docs/COSTS.md` |
| Total build cost (all providers) | $196.68 | `docs/COSTS.md` |
| Detector training | YOLO11m on a local RTX 4070, ~5 GPU-h total | `docs/COSTS.md` |

Notes: the RTX PRO 6000 is now started on upload rather than kept on for a fixed window; COSTS.md still shows the
scheduled Sunday window as the budget, so update `analysis/infra.json` with the real on-demand hours after judging.
The on-demand start/stop code is not on this branch yet (check its commit before quoting details).
