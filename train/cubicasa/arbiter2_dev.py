"""Arbiter with a second detector opinion, fit on DEV-val and cross-validated like arbiter_dev.py (5-fold over drawings).

Rule "switch_vote" per template t: keep the detector's answer when it agrees with the VLM; else take the VLM's answer
when (det conf < a_t and VLM conf >= b_t)  [the shipped switch rule]  OR  (det2 == VLM and det conf < c_t).

    .venv/bin/python train/cubicasa/arbiter2_dev.py --det cache/cubicasa/tta/cv_flipq.jsonl \
        --vlm cache/vlm_dev/devval_r3.jsonl --det2 cache/cubicasa/tta/cv_base.jsonl
"""
import argparse
import collections
import random

import arbiter_dev as A

C_GRID = [0.0, 0.3, 0.5, 0.7, 0.9, 1.01]


def apply(rule, x):
    if x["det"] == x["vlm"]:
        return x["det"]
    a, b, c = rule.get(x["t"], (0.0, 1.0, 0.0))
    if x["dc"] < a and x["vc"] >= b:
        return x["vlm"]
    if x["det2"] == x["vlm"] and x["dc"] < c:
        return x["vlm"]
    return x["det"]


def fit(xs, use_vote=True):
    by = collections.defaultdict(list)
    for x in xs:
        by[x["t"]].append(x)
    rule = {}
    for t, g in by.items():
        cands = [(a, b, c) for a in A.A_GRID for b in A.B_GRID for c in (C_GRID if use_vote else [0.0])]
        rule[t] = max(cands, key=lambda r: (sum(apply({t: r}, x) == x["gold"] for x in g), -r[0], r[1], -r[2]))
    return rule


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--det", required=True)
    ap.add_argument("--vlm", required=True)
    ap.add_argument("--det2", required=True)
    ap.add_argument("--rows", default="cache/vlm_dev/devval_cc.jsonl")
    ap.add_argument("--reps", type=int, default=5)
    a = ap.parse_args()
    xs = A.load(a.det, a.vlm, a.rows, a.det2)
    n = len(xs)
    base = sum(x["det"] == x["gold"] for x in xs) / n
    res = {}
    for kind in ("switch", "switch_vote"):
        accs, oof0 = [], {}
        for rep in range(a.reps):
            right = 0
            for f in range(5):
                tr = [x for x in xs if A.fold_of(x["path"], 5, rep) != f]
                rule = fit(tr, kind == "switch_vote")
                for x in xs:
                    if A.fold_of(x["path"], 5, rep) == f:
                        ok = apply(rule, x) == x["gold"]
                        right += ok
                        if rep == 0:
                            oof0[id(x)] = ok
            accs.append(right / n)
        res[kind] = (accs, oof0)
    sw, sv = res["switch"], res["switch_vote"]
    per_d = collections.defaultdict(lambda: [0, 0])
    for x in xs:
        per_d[x["path"]][0] += sv[1][id(x)] - sw[1][id(x)]
        per_d[x["path"]][1] += 1
    ds, rng, bs = list(per_d.values()), random.Random(0), []
    for _ in range(4000):
        s = [rng.choice(ds) for _ in ds]
        bs.append(sum(v[0] for v in s) / sum(v[1] for v in s))
    bs.sort()
    m1, m2 = sum(sw[0]) / len(sw[0]), sum(sv[0]) / len(sv[0])
    print(f"n={n} detector {base:.2%}  switch CV {m1:.2%}  switch_vote CV {m2:.2%}  "
          f"vote-over-switch {m2 - m1:+.2%} 95% CI (rep 0) [{bs[100]:+.2%}, {bs[3899]:+.2%}]")
    print("fitted on all:", fit(xs))


if __name__ == "__main__":
    main()
