# cubicasa5k detector

The `cubicasa` solver (`bp/solvers/cubicasa.py`) counts symbols and typed rooms on CubiCasa5k floor-plan
PNGs with one YOLO11 detector. Weights are not in git; produce them like this (~1 h on an RTX 4070):

```bash
# 1. public CubiCasa5k release (CC BY-NC-SA 4.0 (the stricter of the two licences stated), Zenodo record 2613548, 5.5 GB)
mkdir -p cache/cc5k_dl cache/cc5k
curl -L -o cache/cc5k_dl/cubicasa5k.zip https://zenodo.org/api/records/2613548/files/cubicasa5k.zip/content
.venv/bin/python -I train/cubicasa/extract_cc5k.py cache/cc5k_dl/cubicasa5k.zip cache/cc5k  # skips test drawings

# 2. SVG annotations -> YOLO labels (skips every drawing in our held-out test split)
.venv/bin/python train/cubicasa/make_yolo.py --src cache/cc5k/cubicasa5k --out cache/yolo_cc

# 3. train (40 epochs at 1024 px, ~70 min), then optionally fine-tune at 1280 px from it
.venv/bin/python train/cubicasa/train.py --model yolo11s.pt --imgsz 1024 --epochs 40 --name s1024
.venv/bin/python train/cubicasa/train.py --model $PWD/cache/cubicasa/runs/s1024/weights/best.pt \
    --imgsz 1280 --epochs 30 --batch 6 --name s1280ft

# 4. install, then tune on the validation drawings (dev split only):
#    per-class inference size + threshold, then score calibration and per-template counting rule
mkdir -p cache/cubicasa/weights
cp cache/cubicasa/runs/s1280ft/weights/best.pt cache/cubicasa/weights/
.venv/bin/python train/cubicasa/tune.py --weights cache/cubicasa/weights/best.pt --imgsz 1024 1280
.venv/bin/python train/cubicasa/calibrate.py --weights cache/cubicasa/weights/best.pt

# 5. per-template accuracy on dev-validation questions, and on an eval.py log
.venv/bin/python train/cubicasa/dev_eval.py --weights cache/cubicasa/weights/best.pt
.venv/bin/python eval.py --solver cubicasa --split test --source cubicasa5k --jobs 4 --name cubicasa_test
.venv/bin/python train/cubicasa/dev_eval.py --log runs/cubicasa_test.jsonl
```

The solver reads `thresholds.json` and `calib.json` next to the weights. Docker's 64 MB `/dev/shm` is
too small for torch dataloader workers; `train.py` passes batches by value instead.

## Counting and confidence

Detections are counted against tuned per-class thresholds, or (where it was clearly better on dev) the
mode of a count posterior: calibrated per-detection probabilities (Poisson-binomial) + a Poisson term for
objects the detector misses + the template's dev answer distribution (`bp/cubicasa/counting.py`). The
reported confidence is always that posterior's probability for the answer.

Or point `CUBICASA_WEIGHTS` (or the solver variant, `cubicasa@path/to/best.pt`) at a `best.pt` with a
`thresholds.json` next to it.

## Labels

Our `data/cubicasa5k/<folder>-<id>.png` is pixel-identical to CubiCasa5k's `<folder>/<id>/F1_original.png`;
`model.svg` coordinates are in `F1_scaled.png` pixels and are rescaled. `check_gold.py` compares counting
rules over the SVG with the gold answers on dev drawings; the rules that match 98-100 % are in
`bp/cubicasa/classes.py` (e.g. saunas = sauna rooms + sauna stoves outside them, WC rooms = bath spaces
named "WC", sinks include double and round sinks).

## No leakage

- Any CubiCasa5k drawing whose key lands in our test split (`bp.data.split_of(...) == "test"`; 958 of the
  5,000) is never extracted from the zip (`extract_cc5k.py`) and is dropped again by `make_yolo.py`,
  whether or not it appears in our question set. Checked against the full dataset: 0 of its 922 test
  cubicasa drawings are among the 4,042 training/validation drawings.
- ~10 % of the remaining drawings (md5 of the name) are YOLO validation, used for thresholds and for
  iterating on dev questions; the rest are training.
- At inference the solver only opens the PNG.

## Flip test-time augmentation (`CUBICASA_TTA=flip`, off by default)

Mode `f1280` (`bp/cubicasa/infer.py`) runs the detector on the plan as is, mirrored left-right, upside down
and both (it was trained with both flips), maps the boxes back and merges them by weighted box fusion
(fused score = sum of a cluster's scores / 4). Selected on the 382 dev-val drawings only:

- `tta_dump.py` caches detections per view/size/model; `tta_dev.py` compares fusion variants offline with
  per-template thresholds chosen by 5-fold CV over drawings. Flip-4 at 1280 px: +1.0 pp (mean over 10 fold
  splits). 2 views: +0.3-0.4; v4 + v5 (YOLO11m 1536) WBF ensemble: +0.5; v4 + v3: +0.4; per-template choice
  among variants: no better.
- Whole pipeline (thresholds + calibration + rules), `cv_pipeline.sh` (2-fold over drawings) and `paired.py`:
  baseline 84.3 %, flip with label-tuned thresholds 84.6 %, per-class choice of 1024/1280/f1280 84.2 %,
  flip with thresholds tuned on the dev questions (`tune.py --target questions`) **84.8 % (+0.50 pp,
  95 % CI -0.4 to +1.3)**; in-sample 85.3 % -> 85.8 % (+0.50). Question-tuned thresholds without flips: 83.2 %.
- Test, run once with that config (`runs/cubicasa_test_fliptta`): **84.2 % -> 85.1 %** (+0.89 pp, 95 % CI
  +0.35 to +1.40 over drawings; 542 questions gained, 396 lost). Windows 49.1 -> 52.7 %, toilets +2.0,
  bedrooms +2.2, bathrooms +2.4; sinks -1.7, WC rooms -0.7.
- Cost: 4 passes at 1280 px instead of one at 1024 + one at 1280: 1.3-1.8 s per drawing on 2-4 CPU threads
  of a Ryzen 9 7945HX vs 0.65 s (the cache makes later questions on the same drawing free). Too slow for
  the CPU demo VM, so it stays opt-in; on a GPU it is ~0.1 s.

```bash
mkdir -p cache/cubicasa/weights_flipq && ln -sf ../weights/best.pt cache/cubicasa/weights_flipq/best.pt
.venv/bin/python train/cubicasa/tune.py --weights cache/cubicasa/weights_flipq/best.pt --target questions --imgsz f1280
.venv/bin/python train/cubicasa/calibrate.py --weights cache/cubicasa/weights_flipq/best.pt
cp cache/cubicasa/weights_flipq/thresholds.json cache/cubicasa/weights/thresholds_flip.json
cp cache/cubicasa/weights_flipq/calib.json cache/cubicasa/weights/calib_flip.json
CUBICASA_TTA=flip .venv/bin/python eval.py --solver router --split test --source cubicasa5k --jobs 8 --name cubicasa_test_fliptta
```
