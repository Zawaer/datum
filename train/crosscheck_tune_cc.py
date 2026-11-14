"""Tune the cross-check's second CubiCasa detector: one count threshold per question template.

Dev questions on the YOLO-validation drawings only (never trained on, never test):
    PYTHONPATH=. .venv/bin/python -m bp.crosscheck precompute-cc dev-val
    PYTHONPATH=. .venv/bin/python train/crosscheck_tune_cc.py
"""
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bp.crosscheck import CC_THRESH_FILE, cc_count, cc_second_dets  # noqa: E402
from bp.cubicasa.questions import target  # noqa: E402
from bp.data import load_questions  # noqa: E402

val = {p.stem for p in Path("cache/yolo_cc/images/val").glob("*.png")}
qs = [q for q in load_questions() if q["source"] == "cubicasa5k" and q["split"] == "dev" and Path(q["path"]).stem in val]
by = collections.defaultdict(list)
for q in qs:
    t = target(q["question"])
    if t:
        by[t].append((q, cc_second_dets(q["path"])))
out = {}
for t, items in sorted(by.items()):
    best = max((sum(len(cc_count(t, d, th)) == int(q["answer"]) for q, d in items) / len(items), -abs(th - 0.4), th)
               for th in [x / 40 for x in range(2, 38)])
    out[t] = best[2]
    print(f"{t:12s} n={len(items):4d} acc={best[0]:.1%} th={best[2]:.3f}")
CC_THRESH_FILE.write_text(json.dumps(out, indent=1))
print("wrote", CC_THRESH_FILE)
