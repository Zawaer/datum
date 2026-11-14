# crosscheck_vlm_test_v7: the fine-tuned VLM as the CubiCasa second opinion

All 16,496 CubiCasa test questions (both languages). Primary: `runs/router_full_test_v7.jsonl` (YOLO11m v4 with flip test-time augmentation, the shipped detector; CubiCasa rows of the canonical router run). Second opinion: `bp/crosscheck.py` with the precomputed answers of the fine-tuned Qwen3-VL-8B + LoRA (r3, checkpoint-2200; `runs/vlm_r3_cubicasa_test_full.jsonl`). Log `runs/crosscheck_vlm_test_v7.jsonl`; tables from `analysis/crosscheck_vlm_report.py`. Nothing tuned on test: the router rule (confidence x 0.5 on conflict, abstain below 0.5) was chosen on dev with the detector pairing; no per-target rule (the VLM has no dev-val run, so none was chosen).

## Headline

| | value |
|---|---|
| second methods used | fine-tuned VLM (Qwen3-VL-8B LoRA) (16,496) |
| VLM alone / detector alone | 74.9% / 85.1% |
| coverage (has a VLM answer) | 100.0% |
| **agree** | **73.8%** (12,178 questions) |
| **detector right when they agree** | **94.9%** |
| conflict | 26.2% (4,318) |
| on conflict: detector right / VLM right | 57.3% / 18.6% |
| conflict precision (detector wrong given conflict) | 42.7% |
| recall (wrong answers flagged as conflict) | 74.9% |
| cost of the second opinion | $0.16 per 1,000 questions (one H100, `runs/vlm_r3_cubicasa_test_full.summary.md`) |

## By question kind

| group | n | primary acc | coverage | agree | conflict | acc on agree | acc on conflict | acc on single | conflict precision | recall (all wrong) | recall (covered wrong) | 2nd right on conflict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cubicasa5k / floor | 1844 | 98.4% | 100.0% | 97.7% | 42 | 99.2% | 64.3% | - | 35.7% | 50.0% | 50.0% | 31.0% |
| cubicasa5k / window | 1844 | 52.7% | 100.0% | 28.1% | 1326 | 65.1% | 47.9% | - | 52.1% | 79.2% | 79.2% | 6.4% |
| cubicasa5k / toilet | 1840 | 92.9% | 100.0% | 80.1% | 367 | 96.9% | 76.8% | - | 23.2% | 65.4% | 65.4% | 17.7% |
| cubicasa5k / sink | 1812 | 85.1% | 100.0% | 62.4% | 682 | 94.7% | 69.2% | - | 30.8% | 77.8% | 77.8% | 18.0% |
| cubicasa5k / shower_bath | 1710 | 80.4% | 100.0% | 71.3% | 490 | 95.5% | 42.7% | - | 57.3% | 83.6% | 83.6% | 42.7% |
| cubicasa5k / door | 1326 | 72.5% | 100.0% | 41.8% | 772 | 83.2% | 64.9% | - | 35.1% | 74.5% | 74.5% | 7.9% |
| cubicasa5k / sauna | 1298 | 94.8% | 100.0% | 88.6% | 148 | 98.4% | 66.2% | - | 33.8% | 73.5% | 73.5% | 28.4% |
| cubicasa5k / kitchen | 1274 | 96.7% | 100.0% | 96.8% | 41 | 98.4% | 46.3% | - | 53.7% | 52.4% | 52.4% | 53.7% |
| cubicasa5k / bedroom | 1162 | 90.2% | 100.0% | 83.6% | 190 | 95.3% | 64.2% | - | 35.8% | 59.6% | 59.6% | 24.7% |
| cubicasa5k / bathroom | 916 | 89.7% | 100.0% | 89.2% | 99 | 95.7% | 40.4% | - | 59.6% | 62.8% | 62.8% | 51.5% |
| cubicasa5k / wc_room | 906 | 94.9% | 100.0% | 89.7% | 93 | 99.1% | 58.1% | - | 41.9% | 84.8% | 84.8% | 36.6% |
| cubicasa5k / balcony | 564 | 83.7% | 100.0% | 87.9% | 68 | 91.7% | 25.0% | - | 75.0% | 55.4% | 55.4% | 72.1% |
| **ALL** | 16496 | 85.1% | 100.0% | 73.8% | 4318 | 94.9% | 57.3% | - | 42.7% | 74.9% | 74.9% | 18.6% |

## Selective answering: accuracy on the answers kept

Rank by the detector's calibrated confidence alone, by the router's rule (confidence x 0.5 on a VLM conflict), or agree-first (VLM agreement, then confidence); keep the top fraction.

| ranking | 100% | 90% | 80% | **73.8%** (= agree share) | 70% | 60% | 50% |
|---|---|---|---|---|---|---|---|
| confidence alone | 85.1% | 90.3% | 93.6% | 95.7% | 96.3% | 96.8% | 97.3% |
| confidence x 0.5 on conflict (router) | 85.1% | 90.5% | 94.8% | 96.1% | 96.6% | 97.7% | 97.9% |
| agree first, then confidence | 85.1% | 90.5% | 94.2% | 94.9% | 96.6% | 97.7% | 97.9% |

Router threshold (answer only if confidence >= 0.5, else "not sure"):

| | answered | accuracy on answered |
|---|---|---|
| before the cross-check | 81.0% | 93.4% |
| after x 0.5 on VLM conflict | 68.6% | 96.7% |

## What it shows

Same measurement as `runs/crosscheck_vlm_test.summary.md` (primary YOLO11m v4 without flip TTA, 84.2 %), redone
with the detector the canonical run `router_full_test_v7` ships (flip test-time augmentation, 85.1 %). The VLM
answers are the same precomputed file; only the primary changed.

- **Agreement is a strong "verified" signal**: on the 73.8 % of raster questions where the fine-tuned VLM and the
  detector agree, the detector is right 94.9 % (85.1 % overall; previous primary: 73.7 % agree, 94.6 %).
- **Conflicts catch three quarters of the detector's errors** (recall 74.9 %; conflict precision 42.7 % against a
  14.9 % base error rate). Windows and doors conflict most (the VLM is weakest there: right on 6-8 % of their conflicts).
- **Never switch to the VLM's answer**: on conflict it is right only 18.6 % of the time vs 57.3 % for the detector.
  The router keeps the detector's answer and halves its confidence, which beats confidence-only ranking at every
  coverage below 100 % (+1.2 pt at 80 %, +0.9 pt at 60 %) and, at the existing 0.5 threshold, answers 68.6 % of
  questions at 96.7 % (vs 81.0 % at 93.4 % without the check).
- Not tuned on test: the rule and threshold predate this run; no per-target switch (no VLM dev-val run).
