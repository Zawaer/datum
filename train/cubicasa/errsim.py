"""Offline simulator of the shipped CubiCasa pipeline on DEV-val drawings, for error analysis and rule experiments.

Detections: flip TTA at 1280 px rebuilt from the cached per-view dumps (cache/cubicasa/tta/v4.json, the v4 weights)
with the same weighted box fusion as bp/cubicasa/infer.py. Thresholds / calibration / counting rules: the 2-fold
out-of-fold ones of cv_pipeline.sh (cache/cubicasa/tta/cv_flipq_{A,B}: tuned on fold A, applied to fold B and back),
so every prediction is out-of-fold. VLM answers: cache/vlm_dev/devval_r3.jsonl (for arbiter experiments).

    .venv/bin/python train/cubicasa/errsim.py check      # reproduces cache/cubicasa/tta/cv_flipq.jsonl
"""
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bp.cubicasa.classes import COUNTS  # noqa: E402
from bp.cubicasa.infer import wbf  # noqa: E402
from bp.cubicasa.questions import target  # noqa: E402
from bp.data import load_questions  # noqa: E402

T = ROOT / "cache/cubicasa/tta"


def style(stem):
    return stem.rsplit("-", 1)[0]


def fused(dump=T / "v4.json", size=1280):
    D = json.loads(Path(dump).read_text())
    return {stem: [tuple(d) for d in wbf([v[f"{size}_{k}"] for k in ("id", "h", "v", "hv")])] for stem, v in D.items()}


def fold_of_stem():
    """stem -> 'A' / 'B' (the fold whose val images it is in)."""
    out = {}
    for f in "AB":
        for p in (T / f"fold{f}/images/val").glob("*.png"):
            out[p.stem] = f
    return out


def solvers(tag="flipq"):
    """{'A': solver tuned on fold A, 'B': ...}; a drawing in fold X is scored by the solver tuned on the other fold."""
    import os

    os.environ["CUBICASA_ARBITER"] = "off"
    from bp.solvers.cubicasa import CubicasaSolver

    return {f: CubicasaSolver(weights=str(T / f"cv_{tag}_{f}/best.pt")) for f in "AB"}


def questions():
    stems = fold_of_stem()
    qs = [q for q in load_questions() if q["source"] == "cubicasa5k" and q["split"] == "dev"
          and Path(q["path"]).stem in stems]
    for q in qs:
        q["stem"] = Path(q["path"]).stem
        q["t"] = target(q["question"])
        q["gold_n"] = round(float(q["answer"]))
    return qs


def vlm():
    meta = {r["id"]: r for r in map(json.loads, open(ROOT / "cache/vlm_dev/devval_cc.jsonl"))}
    out = {}
    for r in map(json.loads, open(ROOT / "cache/vlm_dev/devval_r3.jsonl")):
        m = meta[r["id"]]
        out[(m["path"], m["question"])] = (r["pred"], r.get("conf") or 0.0)
    return out


def run(qs, dets, S, folds, transform=None):
    """rows: per question the out-of-fold detector answer. transform(t, stem, dets_of_template, solver) -> dets."""
    rows = []
    for q in qs:
        s = S["B" if folds[q["stem"]] == "A" else "A"]
        ds = [d for d in dets[q["stem"]] if d[0] in COUNTS[q["t"]]]
        if transform:
            ds = transform(q["t"], q["stem"], ds, s)
        k, conf, kept, how = s.decide(q["t"], ds)
        rows.append({"path": q["path"], "question": q["question"], "stem": q["stem"], "t": q["t"], "gold": q["gold_n"],
                     "pred": k, "confidence": round(conf, 3), "correct": k == q["gold_n"], "kept": kept})
    return rows


if __name__ == "__main__" and sys.argv[1:] == ["check"]:
    qs, dets, S, folds = questions(), fused(), solvers(), fold_of_stem()
    rows = run(qs, dets, S, folds)
    ref = {(r["path"], r["question"]): r for r in map(json.loads, open(T / "cv_flipq.jsonl"))}
    same = sum(ref[(r["path"], r["question"])]["pred"] == r["pred"] for r in rows)
    print(f"n={len(rows)} acc {sum(r['correct'] for r in rows) / len(rows):.2%}  same pred as cv_flipq: {same}")
    c = collections.Counter(r["t"] for r in rows if ref[(r["path"], r["question"])]["pred"] != r["pred"])
    print(c)
