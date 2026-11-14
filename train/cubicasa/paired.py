"""Paired comparison of two dev_eval.py row logs (same questions): accuracy difference per template, with a
bootstrap 95 % interval over drawings.   .venv/bin/python train/cubicasa/paired.py A.jsonl B.jsonl"""
import collections
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bp.cubicasa.questions import target  # noqa: E402


def main():
    A = {(r["path"], r["question"]): r for r in map(json.loads, open(sys.argv[1]))}
    B = {(r["path"], r["question"]): r for r in map(json.loads, open(sys.argv[2]))}
    keys = sorted(set(A) & set(B))
    per_t = collections.defaultdict(lambda: [0, 0, 0])
    per_d = collections.defaultdict(lambda: [0, 0])
    for k in keys:
        a, b = A[k]["correct"], B[k]["correct"]
        t = per_t[target(k[1])]
        t[0] += a
        t[1] += b
        t[2] += 1
        per_d[k[0]][0] += b - a
        per_d[k[0]][1] += 1
    n = len(keys)
    d = sum(v[0] for v in per_d.values()) / n
    rng = random.Random(0)
    ds = list(per_d.values())
    bs = []
    for _ in range(4000):
        s = [rng.choice(ds) for _ in ds]
        bs.append(sum(x[0] for x in s) / sum(x[1] for x in s))
    bs.sort()
    print(f"n={n}  A {sum(v[0] for v in per_t.values()) / n:.2%}  B {sum(v[1] for v in per_t.values()) / n:.2%}  "
          f"B-A {d:+.2%} [{bs[100]:+.2%}, {bs[3899]:+.2%}]")
    for t, (a, b, m) in sorted(per_t.items(), key=lambda x: -x[1][2]):
        print(f"  {t:12s} n={m:4d}  {a / m:.1%} -> {b / m:.1%}  ({b - a:+d})")


if __name__ == "__main__":
    main()
