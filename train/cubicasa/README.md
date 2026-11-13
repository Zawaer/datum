# cubicasa5k detector

The `cubicasa` solver (`bp/solvers/cubicasa.py`) counts symbols and typed rooms on CubiCasa5k floor-plan
PNGs with one YOLO11 detector. Weights are not in git; produce them like this (~1 h on an RTX 4070):

```bash
# 1. public CubiCasa5k release (CC BY-NC 4.0, Zenodo record 2613548, 5.5 GB)
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
