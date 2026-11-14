#!/usr/bin/env bash
# Score one detector candidate through the whole dev pipeline the shipped model uses (flip TTA at 1280 px,
# thresholds tuned on dev questions, calibration + per-template rules), 2-fold CV over the dev-val drawings,
# and compare it paired with the shipped v4 config (cache/cubicasa/tta/cv_flipq.jsonl).
#   bash train/cubicasa/sweep_select.sh <tag> <best.pt | members.txt> [mode, default f1280]
set -euo pipefail
tag=$1; w=$2; mode=${3:-f1280}
TUNE_ARGS="--target questions" bash train/cubicasa/cv_pipeline.sh $tag "$w" $mode | tee cache/cubicasa/tta/cv_$tag.log
.venv/bin/python train/cubicasa/paired.py cache/cubicasa/tta/cv_flipq.jsonl cache/cubicasa/tta/cv_$tag.jsonl \
  | tee -a cache/cubicasa/tta/cv_$tag.log
