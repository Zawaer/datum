# crosscheck_vlm_test_v8: the fine-tuned VLM as the CubiCasa second opinion

All 16,496 CubiCasa test questions (both languages). Primary: `runs/router_full_test_v8.jsonl` (flip-TTA YOLO11m v4 + VLM arbiter, the shipped pipeline). Second opinion: `bp/crosscheck.py` with the precomputed answers of the fine-tuned Qwen3-VL-8B + LoRA (r3, checkpoint-2200; `runs/vlm_r3_cubicasa_test_full.jsonl`). Log `runs/crosscheck_vlm_test_v8.jsonl`; tables from `analysis/crosscheck_vlm_report.py`. Nothing tuned on test: the router rule (confidence x 0.5 on conflict, abstain below 0.5) was chosen on dev with the detector pairing; no per-target rule (the VLM has no dev-val run, so none was chosen).

## Headline

| | value |
|---|---|
| second methods used | fine-tuned VLM (Qwen3-VL-8B LoRA) (16,109), None (312), cubicasa-yolo11s-v3-2nd (75) |
| VLM alone / detector alone | 73.6% / 86.1% |
| coverage (has a VLM answer) | 98.1% |
| **agree** | **73.9%** (12,197 questions) |
| **detector right when they agree** | **94.9%** |
| conflict | 24.2% (3,987) |
| on conflict: detector right / VLM right | 60.8% / 14.2% |
| conflict precision (detector wrong given conflict) | 39.2% |
| recall (wrong answers flagged as conflict) | 68.4% |
| cost of the second opinion | $0.16 per 1,000 questions (one H100, `runs/vlm_r3_cubicasa_test_full.summary.md`) |

## By question kind

| group | n | primary acc | coverage | agree | conflict | acc on agree | acc on conflict | acc on single | conflict precision | recall (all wrong) | recall (covered wrong) | 2nd right on conflict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cubicasa5k / floor | 1844 | 99.0% | 99.3% | 98.4% | 30 | 99.2% | 90.0% | 100.0% | 10.0% | 16.7% | 16.7% | 3.3% |
| cubicasa5k / window | 1844 | 52.7% | 100.0% | 28.1% | 1326 | 65.1% | 47.9% | - | 52.1% | 79.2% | 79.2% | 6.4% |
| cubicasa5k / toilet | 1840 | 92.4% | 99.0% | 80.9% | 348 | 96.9% | 76.1% | 36.8% | 23.9% | 59.3% | 64.8% | 18.1% |
| cubicasa5k / sink | 1812 | 85.5% | 98.3% | 63.4% | 652 | 94.7% | 71.9% | 33.3% | 28.1% | 69.6% | 75.3% | 17.0% |
| cubicasa5k / shower_bath | 1710 | 85.3% | 93.0% | 77.3% | 361 | 95.5% | 52.9% | 78.3% | 47.1% | 67.7% | 75.6% | 29.1% |
| cubicasa5k / door | 1326 | 72.5% | 99.4% | 42.0% | 764 | 83.2% | 65.4% | 0.0% | 34.6% | 72.3% | 73.9% | 8.0% |
| cubicasa5k / sauna | 1298 | 95.8% | 99.4% | 89.2% | 139 | 98.4% | 73.4% | 100.0% | 26.6% | 67.3% | 67.3% | 20.9% |
| cubicasa5k / kitchen | 1274 | 97.4% | 97.7% | 99.0% | 12 | 98.4% | 83.3% | 62.1% | 16.7% | 6.1% | 9.1% | 16.7% |
| cubicasa5k / bedroom | 1162 | 90.9% | 97.3% | 86.2% | 156 | 95.0% | 71.8% | 58.1% | 28.2% | 41.5% | 47.3% | 19.2% |
| cubicasa5k / bathroom | 916 | 91.0% | 98.7% | 90.4% | 87 | 95.7% | 47.1% | 91.7% | 52.9% | 56.1% | 56.8% | 43.7% |
| cubicasa5k / wc_room | 906 | 97.8% | 96.5% | 93.4% | 58 | 99.0% | 89.7% | 81.2% | 10.3% | 30.0% | 42.9% | 8.6% |
| cubicasa5k / balcony | 564 | 85.8% | 98.0% | 90.2% | 54 | 91.6% | 35.2% | 72.7% | 64.8% | 43.8% | 45.5% | 64.8% |
| **ALL** | 16496 | 86.1% | 98.1% | 75.4% | 3987 | 94.9% | 60.8% | 67.9% | 39.2% | 68.4% | 71.6% | 14.2% |

## Selective answering: accuracy on the answers kept

Rank by the detector's calibrated confidence alone, by the router's rule (confidence x 0.5 on a VLM conflict), or agree-first (VLM agreement, then confidence); keep the top fraction.

| ranking | 100% | 90% | 80% | **73.9%** (= agree share) | 70% | 60% | 50% |
|---|---|---|---|---|---|---|---|
| confidence alone | 86.1% | 90.9% | 94.0% | 95.9% | 96.4% | 96.9% | 97.4% |
| confidence x 0.5 on conflict (router) | 86.1% | 91.3% | 94.7% | 95.9% | 96.3% | 97.7% | 97.9% |
| agree first, then confidence | 86.1% | 91.2% | 94.3% | 94.9% | 96.6% | 97.7% | 97.9% |

Router threshold (answer only if confidence >= 0.5, else "not sure"):

| | answered | accuracy on answered |
|---|---|---|
| before the cross-check | 82.0% | 93.5% |
| after x 0.5 on VLM conflict | 69.9% | 96.3% |
