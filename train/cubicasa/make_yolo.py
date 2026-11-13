"""Build a YOLO detection dataset from the public CubiCasa5k release (Zenodo 2613548).

    .venv/bin/python train/cubicasa/make_yolo.py --src cache/cc5k/cubicasa5k --out cache/yolo_cc

Leakage guard: a CubiCasa drawing <folder>/<id> is the same drawing as our
data/cubicasa5k/<folder>-<id>.png. Every drawing whose key falls in our held-out TEST split
(bp.data.split_of) is skipped outright, whether or not it appears in our question set, so no test
drawing is ever trained on or looked at. Of the rest, a fixed ~10 % (hash of the stem) is held out as
YOLO validation; dev questions on those drawings are what we iterate on.

Images: F1_original.png (pixel-identical to our PNGs). SVG coordinates are in F1_scaled.png pixel
space, so they are scaled by original/scaled size.
"""
import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bp.cubicasa.classes import IDX, NAMES, svg_class  # noqa: E402
from bp.cubicasa.svg import parse  # noqa: E402
from bp.data import split_of  # noqa: E402

Image.MAX_IMAGE_PIXELS = None


def is_val(stem: str) -> bool:
    return int(hashlib.md5(stem.encode()).hexdigest()[:8], 16) % 10 == 0


def convert(args):
    d, out = args
    d = Path(d)
    stem = f"{d.parent.name}-{d.name}"
    if split_of(f"data/cubicasa5k/{stem}.png") == "test":
        return stem, "test-skipped", None
    orig, scaled, svg = d / "F1_original.png", d / "F1_scaled.png", d / "model.svg"
    if not (orig.exists() and scaled.exists() and svg.exists()):
        return stem, "incomplete", None
    W, H = Image.open(orig).size
    sw, sh = Image.open(scaled).size
    sx, sy = W / sw, H / sh
    try:
        objs = parse(svg)["objects"]
    except Exception as e:  # noqa: BLE001
        return stem, f"parse-error {e!r}"[:200], None
    lines, counts = [], {}
    for o in objs:
        c = svg_class(o)
        if c is None or o.get("bbox") is None:
            continue
        x0, y0, x1, y1 = o["bbox"]
        x0, x1 = max(0, x0 * sx), min(W, x1 * sx)
        y0, y1 = max(0, y0 * sy), min(H, y1 * sy)
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        counts[c] = counts.get(c, 0) + 1
        lines.append(f"{IDX[c]} {(x0 + x1) / 2 / W:.6f} {(y0 + y1) / 2 / H:.6f} {(x1 - x0) / W:.6f} {(y1 - y0) / H:.6f}")
    part = "val" if is_val(stem) else "train"
    img_dst = Path(out) / "images" / part / f"{stem}.png"
    if not img_dst.exists():
        os.symlink(orig.resolve(), img_dst)
    (Path(out) / "labels" / part / f"{stem}.txt").write_text("\n".join(lines) + "\n")
    return stem, part, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="cache/cc5k/cubicasa5k")
    ap.add_argument("--out", default="cache/yolo_cc")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    out = Path(a.out).resolve()
    for p in ("train", "val"):
        (out / "images" / p).mkdir(parents=True, exist_ok=True)
        (out / "labels" / p).mkdir(parents=True, exist_ok=True)
    dirs = sorted(str(p.parent) for p in Path(a.src).glob("*/*/model.svg"))
    stats, meta = {}, {}
    with ProcessPoolExecutor(a.workers) as ex:
        for stem, status, counts in ex.map(convert, [(d, out) for d in dirs], chunksize=16):
            stats[status.split(" ")[0]] = stats.get(status.split(" ")[0], 0) + 1
            meta[stem] = {"status": status, "counts": counts}
    (out / "meta.json").write_text(json.dumps(meta))
    (out / "data.yaml").write_text(
        f"path: {out}\ntrain: images/train\nval: images/val\nnames:\n"
        + "".join(f"  {i}: {n}\n" for i, n in enumerate(NAMES)))
    print(stats)


if __name__ == "__main__":
    main()
