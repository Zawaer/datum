"""EVALUATION ONLY: extract the CubiCasa5k SVG annotations of TEST-split drawings into cache/eval_gold/.

    .venv/bin/python -I analysis/extract_eval_gold.py cache/cc5k_dl/cubicasa5k.zip cache/eval_gold

This is the mirror image of train/cubicasa/extract_cc5k.py: it writes ONLY test-split drawings
(model.svg + the F1_scaled.png size, which defines the SVG coordinate frame) and nothing else.
cache/eval_gold/ is read only by analysis/evidence_scoring.py; no training / tuning code reads it.
"""
import json
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bp.data import split_of  # noqa: E402


def png_size(b: bytes):
    return struct.unpack(">II", b[16:24])


def main(zip_path, out):
    out = Path(out)
    (out / "svg").mkdir(parents=True, exist_ok=True)
    z = zipfile.ZipFile(zip_path)
    sizes = {}
    for i in z.infolist():
        p = i.filename.split("/")
        if len(p) < 4 or p[1] not in ("colorful", "high_quality", "high_quality_architectural") or not p[3]:
            continue
        stem = f"{p[1]}-{p[2]}"
        if split_of(f"data/cubicasa5k/{stem}.png") != "test":
            continue
        if p[3] == "model.svg":
            (out / "svg" / f"{stem}.svg").write_bytes(z.read(i))
        elif p[3] == "F1_scaled.png":
            with z.open(i) as f:
                sizes[stem] = png_size(f.read(24))
    (out / "scaled_sizes.json").write_text(json.dumps(sizes))
    (out / "README.txt").write_text("Test-split CubiCasa5k SVG annotations, for evidence EVALUATION only.\n"
                                    "Never read by training or tuning code.\n")
    print(f"wrote {len(list((out / 'svg').glob('*.svg')))} test svgs, {len(sizes)} sizes")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
