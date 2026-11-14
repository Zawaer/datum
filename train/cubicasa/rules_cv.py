"""Candidate counting fixes for the CubiCasa pipeline, scored on DEV-val with out-of-fold thresholds (errsim.py), with the
per-template choice of fix itself cross-validated (5-fold over drawings, 10 repeats, like arbiter_dev.py) and the
shipped VLM arbiter applied on top of every variant.

    .venv/bin/python train/cubicasa/rules_cv.py [--out cache/cubicasa/rules_cv.json]

Fixes (each a transform of one template's detections before counting):
- infloor[_pad]: drop symbol boxes whose centre is outside every detected floor box (CubiCasa often annotates only
  one dwelling / part of a sheet, so symbols outside the annotated floor are not in the gold count)
- contain<c>: drop a box when <c> of its area lies inside a higher-scoring box of the same template (duplicate /
  leaf-in-door boxes)
- edge: drop symbol boxes whose centre is within 1.5 % of the image border (legend strips, cut-off insets)
"""
import argparse
import collections
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import errsim as E  # noqa: E402
from errors_dev import arbitrate  # noqa: E402

ROOMS = {"bedroom", "kitchen", "bathroom", "wc_room", "balcony", "sauna", "floor"}


def inside(b, r, pad=0.0):
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return r[0] - pad <= cx <= r[2] + pad and r[1] - pad <= cy <= r[3] + pad


def frac_in(b, r):
    iw = min(b[2], r[2]) - max(b[0], r[0])
    ih = min(b[3], r[3]) - max(b[1], r[1])
    a = max(1e-12, (b[2] - b[0]) * (b[3] - b[1]))
    return iw * ih / a if iw > 0 and ih > 0 else 0.0


def make(dets):
    def infloor(pad):
        def f(t, stem, ds, s):
            if t == "floor":
                return ds
            fl = [d[2] for d in dets[stem] if d[0] == "floor" and d[1] >= s.th("floor")]
            if not fl:
                return ds
            return [d for d in ds if any(inside(d[2], r, pad) for r in fl)]
        return f

    def contain(c):
        def f(t, stem, ds, s):
            if t in ROOMS:
                return ds
            ds = sorted(ds, key=lambda d: -d[1])
            keep = []
            for d in ds:
                if d[1] >= s.th(d[0]) and any(k[1] >= s.th(k[0]) and frac_in(d[2], k[2]) >= c for k in keep):
                    continue
                keep.append(d)
            return keep
        return f

    def edge(t, stem, ds, s):
        if t in ROOMS:
            return ds
        m = 0.015
        return [d for d in ds if m < (d[2][0] + d[2][2]) / 2 < 1 - m and m < (d[2][1] + d[2][3]) / 2 < 1 - m]

    return {"base": None, "infloor": infloor(0.0), "infloor_pad": infloor(0.02), "contain0.6": contain(0.6),
            "contain0.8": contain(0.8), "edge": edge}


def fold_of(path, k, rep):
    return int(hashlib.sha256(f"{rep}:{path}".encode()).hexdigest()[:8], 16) % k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args()
    qs, dets, S, folds = E.questions(), E.fused(), E.solvers(), E.fold_of_stem()
    V = E.vlm()
    rule = json.loads((E.ROOT / "cache/cubicasa/weights/arbiter_flip.json").read_text())
    variants = make(dets)
    R = {}
    for name, fn in variants.items():
        R[name] = arbitrate(E.run(qs, dets, S, folds, fn), V, rule)
    base = R["base"]
    n = len(base)
    by_t = collections.defaultdict(list)
    for i, r in enumerate(base):
        by_t[r["t"]].append(i)
    print(f"n={n}  base (OOF det + arbiter) {sum(r['correct'] for r in base) / n:.2%}")
    print("| variant | " + " | ".join(sorted(by_t)) + " | ALL |")
    for name, rows in R.items():
        cells = [f"{sum(rows[i]['correct'] for i in by_t[t]) - sum(base[i]['correct'] for i in by_t[t]):+d}"
                 for t in sorted(by_t)]
        print(f"| {name} | " + " | ".join(cells) + f" | {sum(r['correct'] for r in rows) - sum(r['correct'] for r in base):+d} |")
    # CV of the per-template choice of variant
    paths = [r["path"] for r in base]
    accs, oof0 = [], None
    names = list(R)
    for rep in range(10):
        pick = [False] * n
        for f in range(5):
            te = [i for i in range(n) if fold_of(paths[i], 5, rep) == f]
            ch = {}
            for t, idx in by_t.items():
                tri = [i for i in idx if fold_of(paths[i], 5, rep) != f]
                ch[t] = max(names, key=lambda v: (sum(R[v][i]["correct"] for i in tri), v == "base"))
            for i in te:
                pick[i] = R[ch[base[i]["t"]]][i]["correct"]
        accs.append(sum(pick) / n)
        if rep == 0:
            oof0 = pick
    per_d = collections.defaultdict(lambda: [0, 0])
    for i, r in enumerate(base):
        per_d[r["path"]][0] += oof0[i] - r["correct"]
        per_d[r["path"]][1] += 1
    ds, rng, bs = list(per_d.values()), random.Random(0), []
    for _ in range(4000):
        s = [rng.choice(ds) for _ in ds]
        bs.append(sum(v[0] for v in s) / sum(v[1] for v in s))
    bs.sort()
    b0 = sum(r["correct"] for r in base) / n
    m = sum(accs) / len(accs)
    print(f"per-template choice, CV: {m:.2%} (gain {m - b0:+.2%}; reps {min(accs) - b0:+.2%}..{max(accs) - b0:+.2%}; "
          f"95% CI rep0 [{bs[100]:+.2%}, {bs[3899]:+.2%}])")
    full = {t: max(names, key=lambda v: (sum(R[v][i]["correct"] for i in idx), v == "base")) for t, idx in by_t.items()}
    print("choice on all dev-val:", full)
    if a.out:
        Path(a.out).write_text(json.dumps({"choice": full, "cv_gain_pp": round(100 * (m - b0), 2)}, indent=1))


if __name__ == "__main__":
    main()
