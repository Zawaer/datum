"""Per-template accuracy of the cubicasa solver.

    # dev questions on the YOLO-validation drawings (never trained on): for iterating
    .venv/bin/python train/cubicasa/dev_eval.py --weights cache/cubicasa/runs/s1024/weights/best.pt
    # or summarise an eval.py run log per template
    .venv/bin/python train/cubicasa/dev_eval.py --log runs/cubicasa_test.jsonl
"""
import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bp.cubicasa.questions import target  # noqa: E402
from bp.data import load_questions  # noqa: E402
from bp.score import is_correct  # noqa: E402


def table(rows):
    by = collections.defaultdict(list)
    for r in rows:
        by[target(r["question"])].append(r)
    out = ["| template | n | accuracy | mean conf (right) | mean conf (wrong) |", "|---|---|---|---|---|"]
    for k in sorted(by, key=lambda k: -len(by[k])) + ["ALL"]:
        g = rows if k == "ALL" else by[k]
        ok = [r for r in g if r["correct"]]
        bad = [r for r in g if not r["correct"]]
        mc = lambda xs: f"{sum(r['confidence'] or 0 for r in xs) / len(xs):.2f}" if xs else "-"  # noqa: E731
        out.append(f"| {k} | {len(g)} | {len(ok) / len(g):.1%} | {mc(ok)} | {mc(bad)} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights")
    ap.add_argument("--log")
    ap.add_argument("--val-dir", default="cache/yolo_cc/images/val")
    ap.add_argument("--out", help="write rows jsonl here")
    a = ap.parse_args()
    if a.log:
        rows = [json.loads(line) for line in open(a.log)]
    else:
        from bp.solvers.cubicasa import CubicasaSolver

        val = {p.stem for p in Path(a.val_dir).glob("*.png")}
        qs = [q for q in load_questions() if q["source"] == "cubicasa5k" and q["split"] == "dev"
              and Path(q["path"]).stem in val]
        s = CubicasaSolver(weights=a.weights)
        rows = []
        for q in qs:
            r = s(q)
            rows.append({"path": q["path"], "question": q["question"], "gold": q["answer"], "pred": r["answer"],
                         "confidence": r["confidence"], "correct": bool(is_correct("count", r["answer"], q["answer"]))})
        if a.out:
            with open(a.out, "w") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(table(rows))


if __name__ == "__main__":
    main()
