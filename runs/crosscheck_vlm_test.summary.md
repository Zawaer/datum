# crosscheck_vlm_test: the fine-tuned VLM as the CubiCasa second opinion

All 16,496 CubiCasa test questions (both languages). Primary: `runs/cubicasa_test_v4.jsonl` (YOLO11m v4, the shipped detector). Second opinion: `bp/crosscheck.py` with the precomputed answers of the fine-tuned Qwen3-VL-8B + LoRA (r3, checkpoint-2200; `runs/vlm_r3_cubicasa_test_full.jsonl`). Log `runs/crosscheck_vlm_test.jsonl`; tables from `analysis/crosscheck_vlm_report.py`. Nothing tuned on test: the router rule (confidence x 0.5 on conflict, abstain below 0.5) was chosen on dev with the detector pairing; no per-target rule (the VLM has no dev-val run, so none was chosen).

## Headline

| | value |
|---|---|
| second methods used | fine-tuned VLM (Qwen3-VL-8B LoRA) (16,496) |
| VLM alone / detector alone | 74.9% / 84.2% |
| coverage (has a VLM answer) | 100.0% |
| **agree** | **73.7%** (12,153 questions) |
| **detector right when they agree** | **94.6%** |
| conflict | 26.3% (4,343) |
| on conflict: detector right / VLM right | 55.1% / 19.9% |
| conflict precision (detector wrong given conflict) | 44.9% |
| recall (wrong answers flagged as conflict) | 74.9% |
| cost of the second opinion | $0.16 per 1,000 questions (one H100, `runs/vlm_r3_cubicasa_test_full.summary.md`) |

## By question kind

| group | n | primary acc | coverage | agree | conflict | acc on agree | acc on conflict | acc on single | conflict precision | recall (all wrong) | recall (covered wrong) | 2nd right on conflict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cubicasa5k / floor | 1844 | 97.9% | 100.0% | 97.4% | 48 | 99.1% | 56.2% | - | 43.8% | 55.3% | 55.3% | 43.8% |
| cubicasa5k / window | 1844 | 49.1% | 100.0% | 28.1% | 1325 | 62.8% | 43.8% | - | 56.2% | 79.4% | 79.4% | 7.2% |
| cubicasa5k / toilet | 1840 | 90.9% | 100.0% | 78.2% | 401 | 97.0% | 68.8% | - | 31.2% | 74.4% | 74.4% | 24.2% |
| cubicasa5k / sink | 1812 | 86.8% | 100.0% | 64.4% | 645 | 94.1% | 73.5% | - | 26.5% | 71.2% | 71.2% | 14.7% |
| cubicasa5k / shower_bath | 1710 | 80.5% | 100.0% | 72.7% | 466 | 94.7% | 42.5% | - | 57.5% | 80.2% | 80.2% | 42.1% |
| cubicasa5k / door | 1326 | 71.8% | 100.0% | 41.9% | 770 | 82.9% | 63.8% | - | 36.2% | 74.6% | 74.6% | 7.9% |
| cubicasa5k / sauna | 1298 | 94.1% | 100.0% | 87.2% | 166 | 98.8% | 62.7% | - | 37.3% | 81.6% | 81.6% | 33.7% |
| cubicasa5k / kitchen | 1274 | 96.7% | 100.0% | 96.5% | 45 | 98.5% | 46.7% | - | 53.3% | 57.1% | 57.1% | 53.3% |
| cubicasa5k / bedroom | 1162 | 88.0% | 100.0% | 82.7% | 201 | 94.7% | 55.7% | - | 44.3% | 63.6% | 63.6% | 31.3% |
| cubicasa5k / bathroom | 916 | 87.3% | 100.0% | 86.4% | 125 | 95.7% | 34.4% | - | 65.6% | 70.7% | 70.7% | 60.8% |
| cubicasa5k / wc_room | 906 | 95.6% | 100.0% | 91.5% | 77 | 98.4% | 64.9% | - | 35.1% | 67.5% | 67.5% | 31.2% |
| cubicasa5k / balcony | 564 | 82.6% | 100.0% | 86.9% | 74 | 91.6% | 23.0% | - | 77.0% | 58.2% | 58.2% | 74.3% |
| **ALL** | 16496 | 84.2% | 100.0% | 73.7% | 4343 | 94.6% | 55.1% | - | 44.9% | 74.9% | 74.9% | 19.9% |

## Selective answering: accuracy on the answers kept

Rank by the detector's calibrated confidence alone, by the router's rule (confidence x 0.5 on a VLM conflict), or agree-first (VLM agreement, then confidence); keep the top fraction.

| ranking | 100% | 90% | 80% | **73.7%** (= agree share) | 70% | 60% | 50% |
|---|---|---|---|---|---|---|---|
| confidence alone | 84.2% | 89.7% | 93.0% | 94.9% | 95.7% | 96.4% | 96.8% |
| confidence x 0.5 on conflict (router) | 84.2% | 90.0% | 93.9% | 95.5% | 96.3% | 97.5% | 97.9% |
| agree first, then confidence | 84.2% | 90.0% | 93.6% | 94.6% | 96.3% | 97.5% | 97.9% |

Router threshold (answer only if confidence >= 0.5, else "not sure"):

| | answered | accuracy on answered |
|---|---|---|
| before the cross-check | 80.9% | 92.8% |
| after x 0.5 on VLM conflict | 68.5% | 96.5% |

## What it shows

- **Agreement is a strong "verified" signal**: on the 73.7 % of raster questions where the fine-tuned VLM and the
  detector agree, the detector is right 94.6 % (84.2 % overall). The earlier second-detector pairing reached
  90.7 % on its agree set (80 % of questions, previous primary; `runs/crosscheck_test.summary.md`): a different
  model family makes agreement mean more.
- **Conflicts catch three quarters of the detector's errors** (recall 74.9 %; conflict precision 44.9 % against a
  15.8 % base error rate). Windows and doors conflict most (the VLM is weakest there: right on 7-8 % of their conflicts).
- **Never switch to the VLM's answer**: on conflict it is right only 19.9 % of the time vs 55.1 % for the detector.
  The router keeps the detector's answer and halves its confidence, which beats confidence-only ranking at every
  coverage below 100 % (+0.9 pt at 80 %, +1.1 pt at 60 %) and, at the existing 0.5 threshold, answers 68.5 % of
  questions at 96.5 % (vs 80.9 % at 92.8 % without the check).
- Not tuned on test: the rule and threshold predate this run; no per-target switch (no VLM dev-val run).
