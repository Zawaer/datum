"""Fit a detector-vs-VLM arbitration rule on cubicasa DEV questions (dev-val drawings only) and estimate its gain
by cross-validation over drawings.

    .venv/bin/python train/cubicasa/arbiter_dev.py --det cache/cubicasa/tta/cv_flipq.jsonl \
        --vlm cache/vlm_dev/devval_r3.jsonl [--det2 other_cv.jsonl] [--out arbiter.json]

--det: dev_eval.py rows of the primary detector pipeline, out-of-fold (cv_pipeline.sh output), so its
confidences are honest. --vlm: eval_vlm.py rows on cache/vlm_dev/devval_cc.jsonl (joined by question id).
--det2 (optional): a second detector pipeline's out-of-fold rows, used only by the vote rule.

Rules (all keep the detector's answer when the answers agree):
- "switch": per template t, take the VLM answer when det confidence < a_t and VLM confidence >= b_t
  (a_t = 0 means never). Grid-searched per template on the training folds.
- "switch_global": one (a, b) for all templates.
- "vote" (needs --det2): majority of detector, detector 2 and VLM; no majority -> detector.
Reported: accuracy of each rule on held-out folds (5-fold over drawings, 10 repeats), and the gain over the
detector with a bootstrap 95 % interval over drawings (repeat 0's out-of-fold predictions).
"""
import argparse
import collections
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bp.cubicasa.questions import target  # noqa: E402

A_GRID = [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
B_GRID = [0.0, 0.5, 0.7, 0.8, 0.9, 0.95, 0.98]


def load(det, vlm, rows_file, det2=None):
    meta = {r["id"]: r for r in map(json.loads, open(rows_file))}
    v = {}
    for line in open(vlm):
        r = json.loads(line)
        m = meta[r["id"]]
        v[(m["path"], m["question"])] = r
    d2 = {(r["path"], r["question"]): r for r in map(json.loads, open(det2))} if det2 else {}
    out = []
    for r in map(json.loads, open(det)):
        k = (r["path"], r["question"])
        if k not in v or (det2 and k not in d2):
            continue
        g = round(float(r["gold"]))
        x = {"path": r["path"], "t": target(r["question"]), "gold": g, "det": r["pred"], "dc": r["confidence"] or 0.0,
             "vlm": v[k]["pred"], "vc": v[k]["conf"] or 0.0}
        if det2:
            x["det2"] = d2[k]["pred"]
        out.append(x)
    return out


def apply(rule, x):
    if x["det"] == x["vlm"]:
        return x["det"]
    if rule["kind"] == "vote":
        if x["det2"] == x["vlm"]:
            return x["vlm"]
        return x["det"]
    a, b = rule["per_t"].get(x["t"], (0.0, 1.0)) if rule["kind"] == "switch" else rule["ab"]
    return x["vlm"] if x["dc"] < a and x["vc"] >= b else x["det"]


def acc(rule, xs):
    return sum(apply(rule, x) == x["gold"] for x in xs) / max(1, len(xs))


def fit(kind, xs):
    if kind == "vote":
        return {"kind": "vote"}
    if kind == "switch_global":
        best = max(((a, b) for a in A_GRID for b in B_GRID),
                   key=lambda ab: (acc({"kind": "switch_global", "ab": ab}, xs), -ab[0], ab[1]))
        return {"kind": "switch_global", "ab": best}
    per_t = {}
    by = collections.defaultdict(list)
    for x in xs:
        by[x["t"]].append(x)
    for t, g in by.items():
        per_t[t] = max(((a, b) for a in A_GRID for b in B_GRID),
                       key=lambda ab: (acc({"kind": "switch", "per_t": {t: ab}}, g), -ab[0], ab[1]))
    return {"kind": "switch", "per_t": per_t}


def fold_of(path, k, rep):
    return int(hashlib.sha256(f"{rep}:{path}".encode()).hexdigest()[:8], 16) % k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--det", required=True)
    ap.add_argument("--vlm", required=True)
    ap.add_argument("--rows", default="cache/vlm_dev/devval_cc.jsonl")
    ap.add_argument("--det2")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--out", help="write the rule fitted on all dev-val questions (best kind by CV) here")
    a = ap.parse_args()
    xs = load(a.det, a.vlm, a.rows, a.det2)
    n = len(xs)
    base = sum(x["det"] == x["gold"] for x in xs) / n
    print(f"n={n} drawings={len({x['path'] for x in xs})}  detector {base:.2%}  VLM "
          f"{sum(x['vlm'] == x['gold'] for x in xs) / n:.2%}  agree {sum(x['det'] == x['vlm'] for x in xs) / n:.1%}  "
          f"either right {sum(x['gold'] in (x['det'], x['vlm']) for x in xs) / n:.2%}")
    kinds = ["switch", "switch_global"] + (["vote"] if a.det2 else [])
    res = {}
    for kind in kinds:
        accs, oof0 = [], {}
        for rep in range(a.reps):
            right = 0
            for f in range(a.k):
                tr = [x for x in xs if fold_of(x["path"], a.k, rep) != f]
                te = [x for x in xs if fold_of(x["path"], a.k, rep) == f]
                rule = fit(kind, tr)
                for x in te:
                    ok = apply(rule, x) == x["gold"]
                    right += ok
                    if rep == 0:
                        oof0[id(x)] = ok
            accs.append(right / n)
        # bootstrap over drawings of (rule right - detector right), repeat 0
        per_d = collections.defaultdict(lambda: [0, 0])
        for x in xs:
            per_d[x["path"]][0] += oof0[id(x)] - (x["det"] == x["gold"])
            per_d[x["path"]][1] += 1
        ds, rng, bs = list(per_d.values()), random.Random(0), []
        for _ in range(4000):
            s = [rng.choice(ds) for _ in ds]
            bs.append(sum(v[0] for v in s) / sum(v[1] for v in s))
        bs.sort()
        m = sum(accs) / len(accs)
        res[kind] = m
        print(f"{kind:14s} CV acc {m:.2%} (reps {min(accs):.2%}..{max(accs):.2%})  gain {m - base:+.2%}  "
              f"95% CI (rep 0) [{bs[100]:+.2%}, {bs[3899]:+.2%}]")
    best = max(res, key=res.get)
    rule = fit(best, xs)
    print("fitted on all:", json.dumps(rule), f"in-sample {acc(rule, xs):.2%}")
    by = collections.defaultdict(list)
    for x in xs:
        by[x["t"]].append(x)
    for t, g in sorted(by.items(), key=lambda kv: -len(kv[1])):
        sw = [x for x in g if apply(rule, x) != x["det"]]
        print(f"  {t:12s} n={len(g):4d} det {sum(x['det'] == x['gold'] for x in g) / len(g):.1%} -> "
              f"{acc(rule, g):.1%}  switched {len(sw)} (VLM right {sum(x['vlm'] == x['gold'] for x in sw)}, "
              f"det right {sum(x['det'] == x['gold'] for x in sw)})")
    if a.out:
        prec = {}
        for t, g in by.items():  # dev precision of switched answers: the confidence reported for them
            sw = [x for x in g if apply(rule, x) != x["det"]]
            if sw:
                prec[t] = round(sum(x["vlm"] == x["gold"] for x in sw) / len(sw), 3)
        rule["switched_precision"] = prec
        rule["cv_gain_pp"] = round(100 * (res[best] - base), 2)
        Path(a.out).write_text(json.dumps(rule, indent=1))
        print("wrote", a.out)


if __name__ == "__main__":
    main()
