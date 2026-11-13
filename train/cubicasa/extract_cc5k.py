"""Extract only the non-test drawings from the CubiCasa5k zip (F1_original.png, F1_scaled.png, model.svg).

    .venv/bin/python -I train/cubicasa/extract_cc5k.py cache/cc5k_dl/cubicasa5k.zip cache/cc5k

Drawings whose key falls in our held-out test split (bp.data.split_of) never touch the disk.
"""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bp.data import split_of  # noqa: E402

FILES = ("F1_original.png", "F1_scaled.png", "model.svg")


def main(zip_path, out):
    z = zipfile.ZipFile(zip_path)
    kept, skipped = set(), set()
    for i in z.infolist():
        p = i.filename.split("/")
        if len(p) < 4 or p[1] not in ("colorful", "high_quality", "high_quality_architectural") or not p[3]:
            continue
        stem = f"{p[1]}-{p[2]}"
        if split_of(f"data/cubicasa5k/{stem}.png") == "test":
            skipped.add(stem)
            continue
        if p[3] in FILES:
            z.extract(i, out)
            kept.add(stem)
    print(f"extracted {len(kept)} drawings, skipped {len(skipped)} test-split drawings")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
