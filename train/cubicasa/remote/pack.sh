#!/usr/bin/env bash
# Package the YOLO dataset (train + dev-val drawings only; make_yolo.py already dropped every test drawing)
# with symlinks dereferenced, plus the code train.py needs, for a remote GPU box.
#   bash train/cubicasa/remote/pack.sh   -> cache/cubicasa/remote/yolo_cc.tar, code.tar
set -euo pipefail
O=cache/cubicasa/remote; mkdir -p $O
# leakage guard: no image in the package may belong to the held-out test split
.venv/bin/python - <<'PY'
from pathlib import Path
from bp.data import split_of
imgs = list(Path("cache/yolo_cc/images").glob("*/*.png"))
bad = [p for p in imgs if split_of(f"data/cubicasa5k/{p.stem}.png") == "test"]
assert not bad, bad[:5]
print(f"{len(imgs)} images, 0 test")
PY
[ -f $O/yolo_cc.tar ] || tar -chf $O/yolo_cc.tar --transform 's,^cache/yolo_cc,yolo_cc,' \
  cache/yolo_cc/images cache/yolo_cc/labels
printf 'path: /root/bp-det/cache/yolo_cc\ntrain: images/train\nval: images/val\n' > $O/data.yaml
sed -n '/^names:/,$p' cache/yolo_cc/data.yaml >> $O/data.yaml
tar -cf $O/code.tar bp/__init__.py bp/cubicasa train/cubicasa/train.py train/cubicasa/remote
ls -la $O
