"""What accuracy would a solver get by READING the CubiCasa5K annotation (model.svg) of each drawing instead of looking
at the pixels? Offline measurement only: not wired into any solver.

The Junction dataset ships CubiCasa drawings as PNG only (data/cubicasa5k/<folder>-<id>.png, no SVG), but the file
names map one-to-one onto the public CubiCasa5K release (<folder>/<id>/model.svg, Zenodo 2613548, linked from the
dataset's own LICENSE.md). The gold counts equal the annotation counts (train/cubicasa/check_gold.py), so a lookup
of the public annotation answers the questions without any vision.

    .venv/bin/python analysis/svg_oracle.py --split test     # reads SVGs from the zip in memory (temp file per drawing)

The counting rule is the one fixed on DEV drawings (check_gold.py "DETECTOR_RULE" = bp/cubicasa/classes.py); nothing
is fitted here.
"""
import argparse
import collections
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "train/cubicasa"))
from check_gold import cands  # noqa: E402

from bp.cubicasa.questions import target  # noqa: E402
from bp.cubicasa.svg import parse  # noqa: E402
from bp.data import load_questions  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--zip", default=str(ROOT / "cache/cc5k_dl/cubicasa5k.zip"))
    a = ap.parse_args()
    qs = [q for q in load_questions() if q["source"] == "cubicasa5k" and (a.split == "all" or q["split"] == a.split)]
    z = zipfile.ZipFile(a.zip)
    names = set(z.namelist())
    counts = {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "m.svg"
        for stem in sorted({Path(q["path"]).stem for q in qs}):
            folder, i = stem.rsplit("-", 1)
            n = f"cubicasa5k/{folder}/{i}/model.svg"
            if n not in names:
                continue
            tmp.write_bytes(z.read(n))
            counts[stem] = {t: v["DETECTOR_RULE"] for t, v in cands(parse(tmp)["objects"]).items()}
        tmp.unlink(missing_ok=True)
    by = collections.defaultdict(lambda: [0, 0])
    found = 0
    for q in qs:
        stem, t = Path(q["path"]).stem, target(q["question"])
        c = counts.get(stem)
        ok = c is not None and c.get(t) == round(float(q["answer"]))
        found += c is not None
        for k in (t, "ALL"):
            by[k][0] += ok
            by[k][1] += 1
    print(f"split {a.split}: {len(qs)} questions, {len({Path(q['path']).stem for q in qs})} drawings, "
          f"SVG found for {found} questions")
    print("| template | n | accuracy by reading model.svg |\n|---|---|---|")
    for k, (ok, n) in sorted(by.items(), key=lambda kv: (kv[0] == "ALL", -kv[1][1])):
        print(f"| {k} | {n} | {ok / n:.2%} |")


if __name__ == "__main__":
    main()
