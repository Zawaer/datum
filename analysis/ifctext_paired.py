"""Paired comparison of two judge-scored runs on the same questions (ids in both runs).

    .venv/bin/python analysis/ifctext_paired.py runs/A.jsonl runs/B.jsonl [--llm-only]

Prints accuracy of each (95 % Wilson CI), the paired difference B - A with a bootstrap 95 % CI and an exact
McNemar p, $/question and latency (median over LLM-answered questions with a fresh call, latency > 0.5 s).
"""
import json
import math
import random
import sys


def load(p):
    return {str(r["id"]): r for r in map(json.loads, open(p))}


def ok(r):
    return str(r.get("correct")) == "True"


def wilson(k, n, z=1.96):
    if not n:
        return 0, 0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def mcnemar(b, c):
    n, k = b + c, min(b, c)
    if not n:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def main():
    a, b = load(sys.argv[1]), load(sys.argv[2])
    ids = sorted(set(a) & set(b))
    if "--llm-only" in sys.argv:
        ids = [i for i in ids if str(b[i]["method"]).startswith("ifctext-")]
    n = len(ids)
    xa = [ok(a[i]) for i in ids]
    xb = [ok(b[i]) for i in ids]
    for name, x, run in (("A", xa, a), ("B", xb, b)):
        k = sum(x)
        lo, hi = wilson(k, n)
        cost = sum(float(run[i].get("cost_usd") or 0) for i in ids) / n
        lat = sorted(float(run[i].get("latency_s") or 0) for i in ids
                     if str(run[i]["method"]).startswith("ifctext-") and float(run[i].get("latency_s") or 0) > 0.5)
        med = lat[len(lat) // 2] if lat else float("nan")
        print(f"{name}: {k}/{n} = {100 * k / n:.1f} % (95 % CI {100 * lo:.1f}-{100 * hi:.1f}); "
              f"${cost:.4f}/q (= ${1000 * cost:.2f}/1k q); median latency {med:.1f} s (n={len(lat)})")
    gain = sum(1 for p, q in zip(xa, xb) if q and not p)
    loss = sum(1 for p, q in zip(xa, xb) if p and not q)
    d = [int(q) - int(p) for p, q in zip(xa, xb)]
    rnd = random.Random(0)
    boots = sorted(sum(rnd.choice(d) for _ in range(n)) / n for _ in range(4000))
    print(f"paired B - A: {100 * sum(d) / n:+.1f} pp (bootstrap 95 % CI {100 * boots[100]:+.1f} to "
          f"{100 * boots[3899]:+.1f}); B fixes {gain}, breaks {loss}; McNemar p = {mcnemar(gain, loss):.3f}")


if __name__ == "__main__":
    main()
