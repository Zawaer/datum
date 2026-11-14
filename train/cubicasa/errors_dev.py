"""CubiCasa error breakdown on DEV-val (out-of-fold detector pipeline, train/cubicasa/errsim.py), plus the shipped VLM
arbiter on top: per template, over- vs under-count, per drawing style, and instance-level causes (kept boxes matched
to the annotated boxes: fp = box on nothing, fn = missed object, split = 2 boxes on 1 object, merge = 1 box on 2+).

    .venv/bin/python train/cubicasa/errors_dev.py [--render window door --n 30]   # overlays -> cache/cubicasa/errs/
"""
import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import errsim as E  # noqa: E402
from count_errors import explain, gold_boxes, render  # noqa: E402

ROOT = E.ROOT
SYMB = {"window": ["window"], "door": ["door"], "toilet": ["toilet"], "sink": ["sink"],
        "shower_bath": ["shower", "bathtub"]}


def arbitrate(rows, V, rule):
    for r in rows:
        r["det_pred"] = r["pred"]
        v = V.get((r["path"], r["question"]))
        if not v or v[0] is None or v[0] == r["pred"]:
            continue
        lo, hi = rule["per_t"].get(r["t"], (0.0, 1.0))
        if r["confidence"] < lo and v[1] >= hi:
            r["pred"] = v[0]
            r["correct"] = r["pred"] == r["gold"]
    return rows


def pct(a, b):
    return f"{a / b:.1%}" if b else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", nargs="*", default=[])
    ap.add_argument("--n", type=int, default=30)
    a = ap.parse_args()
    qs, dets, S, folds = E.questions(), E.fused(), E.solvers(), E.fold_of_stem()
    rows = E.run(qs, dets, S, folds)
    rule = json.loads((ROOT / "cache/cubicasa/weights/arbiter_flip.json").read_text())
    rows = arbitrate(rows, E.vlm(), rule)
    n = len(rows)
    print(f"dev-val n={n} drawings={len({r['stem'] for r in rows})}  detector OOF "
          f"{sum(r['det_pred'] == r['gold'] for r in rows) / n:.2%}  + arbiter {sum(r['correct'] for r in rows) / n:.2%}")
    by = collections.defaultdict(list)
    for r in rows:
        by[r["t"]].append(r)
    nerr = sum(not r["correct"] for r in rows)
    print("\n| template | n | accuracy | errors | share of all errors | over | under | |err|=1 | mean gold |")
    print("|---|---|---|---|---|---|---|---|---|")
    for t, g in sorted(by.items(), key=lambda kv: -sum(not r["correct"] for r in kv[1])):
        bad = [r for r in g if not r["correct"]]
        ov = sum(r["pred"] > r["gold"] for r in bad)
        print(f"| {t} | {len(g)} | {pct(len(g) - len(bad), len(g))} | {len(bad)} | {pct(len(bad), nerr)} | {ov} | "
              f"{len(bad) - ov} | {sum(abs(r['pred'] - r['gold']) == 1 for r in bad)} | "
              f"{sum(r['gold'] for r in g) / len(g):.1f} |")
    print("\n## by style (accuracy)")
    styles = sorted({E.style(r["stem"]) for r in rows})
    print("| template | " + " | ".join(styles) + " |")
    print("|---|" + "---|" * len(styles))
    for t, g in sorted(by.items(), key=lambda kv: -len(kv[1])) + [("ALL", rows)]:
        cells = []
        for s in styles:
            gs = [r for r in g if E.style(r["stem"]) == s]
            cells.append(f"{pct(sum(r['correct'] for r in gs), len(gs))} (n={len(gs)})")
        print(f"| {t} | " + " | ".join(cells) + " |")
    print("\n## instance-level causes (detector's kept boxes vs annotated boxes, English questions only)")
    for t, cls in SYMB.items():
        g = [r for r in by[t] if r["question"].startswith("How")]
        cat, imgs = collections.Counter(), collections.Counter()
        for r in g:
            gold = [b for c in cls for b in gold_boxes(r["stem"])[c]]
            e = explain([d[2] for d in r["kept"]], gold)
            cat.update(e)
            if r["det_pred"] != r["gold"]:
                imgs["+".join(sorted(e)) or "none (annotation count != question gold)"] += 1
            r["svg_n"] = len(gold)
        mism = sum(r["svg_n"] != r["gold"] for r in g)
        print(f"- {t}: instances {dict(cat)}; wrong drawings by cause {imgs.most_common(6)}; "
              f"annotated box count != question gold on {mism}/{len(g)}")
    out = ROOT / "cache/cubicasa/errs"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "rows.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps({k: v for k, v in r.items() if k != "kept"}) + "\n")
    for t in a.render:
        bad = sorted((r for r in by[t] if not r["correct"] and r["question"].startswith("How")),
                     key=lambda r: r["stem"])[: a.n]
        for r in bad:
            gold = [b for c in SYMB.get(t, COUNTS_FALLBACK(t)) for b in gold_boxes(r["stem"])[c]
                    if b[2] - b[0] > 0.002 and b[3] - b[1] > 0.002]
            fn = out / f"{t}_{r['stem']}_g{r['gold']}_p{r['pred']}.png"
            try:
                render(r["stem"], [(d[1], d[2]) for d in r["kept"]], gold, fn)
            except ValueError:  # a gold box thinner than the inset line width
                pass
        print(f"rendered {len(bad)} {t} overlays to {out}")



def COUNTS_FALLBACK(t):
    from bp.cubicasa.classes import COUNTS

    return COUNTS[t]


if __name__ == "__main__":
    main()
