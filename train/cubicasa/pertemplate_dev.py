"""Per-template choice between two detector pipelines (out-of-fold dev rows of cv_pipeline.sh), scored by
5-fold CV over drawings (10 repeats); writes the combined out-of-fold rows (repeat 0) for arbiter_dev.py.
    .venv/bin/python train/cubicasa/pertemplate_dev.py A.jsonl B.jsonl --out combined.jsonl
"""
import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bp.cubicasa.questions import target  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--out")
    a = ap.parse_args()
    A = {(r["path"], r["question"]): r for r in map(json.loads, open(a.a))}
    B = {(r["path"], r["question"]): r for r in map(json.loads, open(a.b))}
    keys = sorted(set(A) & set(B))
    fold = lambda p, rep: int(hashlib.sha256(f"{rep}:{p}".encode()).hexdigest()[:8], 16) % 5  # noqa: E731
    accs, out0, picks = [], {}, collections.Counter()
    for rep in range(10):
        right = 0
        for f in range(5):
            score = collections.defaultdict(lambda: [0, 0])
            for k in keys:
                if fold(k[0], rep) != f:
                    s = score[target(k[1])]
                    s[0] += A[k]["correct"]
                    s[1] += B[k]["correct"]
            for k in keys:
                if fold(k[0], rep) == f:
                    s = score[target(k[1])]
                    r = B[k] if s[1] > s[0] else A[k]
                    right += r["correct"]
                    if rep == 0:
                        out0[k] = r
                        picks[(target(k[1]), "B" if r is B[k] else "A")] += 1
        accs.append(right / len(keys))
    base = sum(A[k]["correct"] for k in keys) / len(keys)
    print(f"A {base:.2%}  per-template choice CV {sum(accs) / len(accs):.2%} ({min(accs):.2%}..{max(accs):.2%})")
    full = collections.defaultdict(lambda: [0, 0])
    for k in keys:
        full[target(k[1])][0] += A[k]["correct"]
        full[target(k[1])][1] += B[k]["correct"]
    print("chosen on all dev-val:", {t: "B" for t, s in full.items() if s[1] > s[0]})
    if a.out:
        with open(a.out, "w") as fh:
            for k in keys:
                fh.write(json.dumps(out0[k], ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
