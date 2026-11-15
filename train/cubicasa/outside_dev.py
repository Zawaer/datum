"""Fit a per-template rule adding ONE outside vision reading per drawing (train/cubicasa/outside_reading.py) as a
third vote on top of the current pipeline (detector + VLM arbiter, arbiter_flip.json), on cubicasa DEV-VAL only;
gain estimated by 5-fold x 10-repeat CV over drawings, as arbiter_dev.py.

    .venv/bin/python train/cubicasa/outside_dev.py --outside cache/cubicasa/outside_reading/claude-sonnet-5-5.jsonl \
        [--out cache/cubicasa/weights/outside_flip.json]

Per template, candidate rules (P = current pipeline answer, D = detector, V = VLM, O = outside, dc = detector conf):
- "keep": P.
- "vote": O when O agrees with D or V (the majority of three), else P.
- "lowconf_a": O when dc < a (whatever the others say).
- "vote_lowconf_a": vote, but only when dc < a.
"""
import argparse
import collections
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from arbiter_dev import apply as arb_apply, fold_of, load  # noqa: E402

A_GRID = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
RULES = [("keep", None), ("vote", None)] + [(k, a) for k in ("lowconf", "vote_lowconf") for a in A_GRID]
GLOBAL = False
ROOMS = ("kitchen", "bedroom", "bathroom", "wc_room", "sauna", "balcony", "floor")
MARGIN = 1


def pick(rule, x):
    kind, a = rule
    o = x["out"]
    if kind == "keep" or o is None:
        return x["P"]
    if kind == "vote":
        return o if o in (x["det"], x["vlm"]) else x["P"]
    if kind == "lowconf":
        return o if x["dc"] < a else x["P"]
    if kind == "vote_lowconf":
        return o if x["dc"] < a and o in (x["det"], x["vlm"]) else x["P"]
    raise ValueError(kind)


FAMILIES = {
    "full": RULES,
    "vote": [("keep", None), ("vote", None)],
    "coarse": [("keep", None), ("vote", None), ("lowconf", 0.5), ("lowconf", 0.9), ("vote_lowconf", 0.5),
               ("vote_lowconf", 0.9)],
}


def fit(xs):
    if GLOBAL == "rooms":  # one shared rule for the labelled-room templates, symbols keep the pipeline answer
        rooms = [x for x in xs if x["t"] in ROOMS]
        best = max(RULES, key=lambda r: (sum(pick(r, x) == x["gold"] for x in rooms), -RULES.index(r)))
        return {t: best for t in ROOMS}
    if GLOBAL:
        best = max(RULES, key=lambda r: (sum(pick(r, x) == x["gold"] for x in xs), -RULES.index(r)))
        return {t: best for t in {x["t"] for x in xs}}
    by = collections.defaultdict(list)
    for x in xs:
        by[x["t"]].append(x)
    # ties -> the earlier (simpler) rule in RULES
    out = {}
    for t, g in by.items():  # a non-keep rule must beat keep by MARGIN questions on the training drawings
        sc = {r: sum(pick(r, x) == x["gold"] for x in g) for r in RULES}
        best = max(RULES, key=lambda r: (sc[r], -RULES.index(r)))
        out[t] = best if sc[best] - sc[("keep", None)] >= MARGIN else ("keep", None)
    return out


def run(per_t, x):
    return pick(per_t.get(x["t"], ("keep", None)), x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--det", default="cache/cubicasa/tta/cv_flipq.jsonl")
    ap.add_argument("--vlm", default="cache/vlm_dev/devval_r3.jsonl")
    ap.add_argument("--arbiter", default="cache/cubicasa/weights/arbiter_flip.json")
    ap.add_argument("--outside", required=True)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--out")
    ap.add_argument("--family", default="full", choices=list(FAMILIES) + ["global", "rooms"])
    ap.add_argument("--margin", type=int, default=1)
    a = ap.parse_args()
    global RULES, GLOBAL, MARGIN
    MARGIN = a.margin
    GLOBAL = a.family if a.family in ("global", "rooms") else False
    RULES = RULES if GLOBAL else FAMILIES[a.family]
    arb = json.loads(Path(a.arbiter).read_text())
    outside = {r["path"]: r["counts"] for r in map(json.loads, open(a.outside))}
    xs = [x for x in load(a.det, a.vlm, "cache/vlm_dev/devval_cc.jsonl") if x["path"] in outside]
    for x in xs:
        x["P"] = arb_apply(arb, x)
        x["out"] = outside[x["path"]].get(x["t"])
    n = len(xs)
    base = sum(x["P"] == x["gold"] for x in xs) / n
    print(f"n={n} drawings={len({x['path'] for x in xs})}  pipeline {base:.2%}  detector "
          f"{sum(x['det'] == x['gold'] for x in xs) / n:.2%}  VLM {sum(x['vlm'] == x['gold'] for x in xs) / n:.2%}  "
          f"outside {sum(x['out'] == x['gold'] for x in xs) / n:.2%}  any right "
          f"{sum(x['gold'] in (x['P'], x['out']) for x in xs) / n:.2%}")
    accs, oof = [], collections.defaultdict(list)
    for rep in range(a.reps):
        right = 0
        for f in range(a.k):
            tr = [x for x in xs if fold_of(x["path"], a.k, rep) != f]
            te = [x for x in xs if fold_of(x["path"], a.k, rep) == f]
            rule = fit(tr)
            for x in te:
                ok = run(rule, x) == x["gold"]
                right += ok
                oof[id(x)].append(ok)
        accs.append(right / n)
    # bootstrap over drawings of (rule right - pipeline right), out-of-fold right averaged over the repeats
    per_d = collections.defaultdict(lambda: [0.0, 0])
    for x in xs:
        per_d[x["path"]][0] += sum(oof[id(x)]) / len(oof[id(x)]) - (x["P"] == x["gold"])
        per_d[x["path"]][1] += 1
    ds, rng, bs = list(per_d.values()), random.Random(0), []
    for _ in range(4000):
        s = [rng.choice(ds) for _ in ds]
        bs.append(sum(v[0] for v in s) / sum(v[1] for v in s))
    bs.sort()
    m = sum(accs) / len(accs)
    print(f"CV acc {m:.2%} (reps {min(accs):.2%}..{max(accs):.2%})  gain {m - base:+.2%}  "
          f"95% CI over drawings [{bs[100]:+.2%}, {bs[3899]:+.2%}]")
    rule = fit(xs)
    by = collections.defaultdict(list)
    for x in xs:
        by[x["t"]].append(x)
    for t, g in sorted(by.items(), key=lambda kv: -len(kv[1])):
        sw = [x for x in g if run(rule, x) != x["P"]]
        print(f"  {t:12s} n={len(g):4d} rule {rule.get(t, ('keep', None))}  pipeline {sum(x['P'] == x['gold'] for x in g) / len(g):.1%} -> "
              f"{sum(run(rule, x) == x['gold'] for x in g) / len(g):.1%}  outside {sum(x['out'] == x['gold'] for x in g) / len(g):.1%}"
              f"  switched {len(sw)} (outside right {sum(x['out'] == x['gold'] for x in sw)}, "
              f"pipeline right {sum(x['P'] == x['gold'] for x in sw)})")
    if a.out:
        prec = {}
        for t, g in by.items():
            sw = [x for x in g if run(rule, x) != x["P"]]
            if sw:
                prec[t] = [sum(x["out"] == x["gold"] for x in sw), len(sw)]
        Path(a.out).write_text(json.dumps({
            "per_t": {t: list(r) for t, r in rule.items() if r[0] != "keep"}, "switched_n": prec,
            "cv_gain_pp": round(100 * (m - base), 2), "ci_pp": [round(100 * bs[100], 2), round(100 * bs[3899], 2)],
            "outside": Path(a.outside).name}, indent=1))
        print("wrote", a.out)


if __name__ == "__main__":
    main()
