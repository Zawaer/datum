#!/usr/bin/env bash
# Install a selected config into its own weights dir (the default cache/cubicasa/weights is left alone):
# flip-TTA thresholds tuned on the dev questions + calibration on all dev-val drawings, and optionally the
# VLM arbiter fitted on that config's out-of-fold dev rows (cv_pipeline output).
#   bash train/cubicasa/install_candidate.sh <out dir> <best.pt | members.txt> [cv rows for the arbiter]
# Then:  CUBICASA_WEIGHTS=<out dir>/best.(pt|txt) .venv/bin/python eval.py --solver router ...
set -euo pipefail
d=$1; w=$2; cv=${3:-}
mkdir -p $d; b=$d/best.${w##*.}; ln -sf "$(realpath "$w")" $b
.venv/bin/python train/cubicasa/tune.py --weights $b --target questions --imgsz f1280 | tail -n 1
.venv/bin/python train/cubicasa/calibrate.py --weights $b | tail -n 1
mv $d/thresholds.json $d/thresholds_flip.json; mv $d/calib.json $d/calib_flip.json
if [ -n "$cv" ]; then
  .venv/bin/python train/cubicasa/arbiter_dev.py --det $cv --vlm cache/vlm_dev/devval_r3.jsonl --out $d/arbiter_flip.json | head -n 3
fi
ls -la $d
