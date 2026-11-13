# cubicasa5k detector

The `cubicasa` solver (`bp/solvers/cubicasa.py`) counts symbols and typed rooms on CubiCasa5k floor-plan
PNGs with one YOLO11 detector. Weights are not in git; produce them like this (~1 h on an RTX 4070):

```bash
# 1. public CubiCasa5k release (CC BY-NC 4.0, Zenodo record 2613548, 5.5 GB)
mkdir -p cache/cc5k_dl cache/cc5k
curl -L -o cache/cc5k_dl/cubicasa5k.zip https://zenodo.org/api/records/2613548/files/cubicasa5k.zip/content
unzip -q cache/cc5k_dl/cubicasa5k.zip -d cache/cc5k

# 2. SVG annotations -> YOLO labels (skips every drawing in our held-out test split)
.venv/bin/python train/cubicasa/make_yolo.py --src cache/cc5k/cubicasa5k --out cache/yolo_cc

# 3. train, then pick per-class score thresholds on the validation drawings
.venv/bin/python train/cubicasa/train.py --model yolo11s.pt --imgsz 1024 --epochs 60 --name cc
.venv/bin/python train/cubicasa/tune.py --weights cache/cubicasa/runs/cc/weights/best.pt --imgsz 1024

# 4. install as the default weights the solver loads
mkdir -p cache/cubicasa/weights
cp cache/cubicasa/runs/cc/weights/{best.pt,thresholds.json} cache/cubicasa/weights/
```

Or point `CUBICASA_WEIGHTS` (or the solver variant, `cubicasa@path/to/best.pt`) at a `best.pt` with a
`thresholds.json` next to it.

## Labels

Our `data/cubicasa5k/<folder>-<id>.png` is pixel-identical to CubiCasa5k's `<folder>/<id>/F1_original.png`;
`model.svg` coordinates are in `F1_scaled.png` pixels and are rescaled. `check_gold.py` compares counting
rules over the SVG with the gold answers on dev drawings; the rules that match 98-100 % are in
`bp/cubicasa/classes.py` (e.g. saunas = sauna rooms + sauna stoves outside them, WC rooms = bath spaces
named "WC", sinks include double and round sinks).

## No leakage

- Any CubiCasa5k drawing whose key lands in our test split (`bp.data.split_of(...) == "test"`) is dropped
  by `make_yolo.py` before anything is read, whether or not it appears in our question set.
- ~10 % of the remaining drawings (md5 of the name) are YOLO validation, used for thresholds and for
  iterating on dev questions; the rest are training.
- At inference the solver only opens the PNG.
