#!/usr/bin/env bash
# 2-fold cross-validation of the whole tuning pipeline (tune.py thresholds + calibrate.py calibration and
# per-template rules) on the dev-val drawings: tune on one half, score dev questions on the other half.
#   bash train/cubicasa/cv_pipeline.sh <tag> <weights best.pt> <modes...>     e.g.  base cache/cubicasa/weights/best.pt 1024 1280
# Fold dirs (symlinks into cache/yolo_cc, split by sha256 of the drawing name) live in cache/cubicasa/tta/fold{A,B}.
set -euo pipefail
tag=$1; w=$2; shift 2
T=cache/cubicasa/tta
for f in A B; do
  o=$([ $f = A ] && echo B || echo A)
  d=$T/cv_${tag}_$f; mkdir -p $d; ln -sf "$(realpath "$w")" $d/best.pt
  .venv/bin/python train/cubicasa/tune.py --weights $d/best.pt --data $T/fold$f ${TUNE_ARGS:-} --imgsz "$@" | tail -n 1
  .venv/bin/python train/cubicasa/calibrate.py --weights $d/best.pt --data $T/fold$f --prior-exclude cache/yolo_cc/images/val | tail -n 1
  .venv/bin/python train/cubicasa/dev_eval.py --weights $d/best.pt --val-dir $T/fold$o/images/val --out $T/cv_${tag}_on$o.jsonl | tail -n 1
done
cat $T/cv_${tag}_onA.jsonl $T/cv_${tag}_onB.jsonl > $T/cv_${tag}.jsonl
.venv/bin/python train/cubicasa/dev_eval.py --log $T/cv_${tag}.jsonl
