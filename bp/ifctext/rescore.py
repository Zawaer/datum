"""Re-score the text rows of existing eval runs with the LLM judge.

    python -m bp.ifctext.rescore runs/ifc_full_all.jsonl [more.jsonl ...] [--jobs 8] [--by method]

Prints proxy vs judge accuracy per split (dev/test) and writes <run>.judged.jsonl next to each input
(rows gain proxy_correct / judge_correct / judge_score / judge_reason / judge_cost_usd).
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import json
from pathlib import Path

from bp.data import load_questions
from bp.judge import judge


def rescore(path: str, jobs: int = 8, by: str | None = None) -> dict:
    split = {q["id"]: q["split"] for q in load_questions()}
    rows = [json.loads(line) for line in open(path)]
    rows = [r for r in rows if r["type"] in ("text", "other")]

    def one(r):
        v = judge(r["question"], r["gold"], r["pred"]) if r["pred"] is not None else \
            {"correct": False, "score": 0.0, "reason": "abstained", "cost_usd": 0.0}
        return {**r, "split": split.get(r["id"], "?"), "proxy_correct": bool(r["correct"]),
                "judge_correct": v["correct"], "judge_score": v.get("score"), "judge_reason": v.get("reason"),
                "judge_cost_usd": v.get("cost_usd", 0.0)}

    with cf.ThreadPoolExecutor(jobs) as ex:
        out = list(ex.map(one, rows))
    dst = Path(path).with_suffix(".judged.jsonl")
    with open(dst, "w") as f:
        for r in out:
            r.pop("evidence", None)
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    res = summarize(out, by)
    print(f"{path}: judge cost ${sum(r['judge_cost_usd'] for r in out):.3f} -> {dst}")
    return res


def summarize(rows, by=None):
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r["source"], r["split"])].append(r)
        groups[(r["source"], "all")].append(r)
    print("| source | split | n | proxy acc | judge acc | solver $/1k q |")
    print("|---|---|---|---|---|---|")
    res = {}
    for k in sorted(groups):
        g = groups[k]
        n = len(g)
        p = sum(r["proxy_correct"] for r in g) / n
        j = sum(r["judge_correct"] for r in g) / n
        c = sum(r.get("cost_usd") or 0 for r in g) / n * 1000
        res[k] = (n, p, j)
        print(f"| {k[0]} | {k[1]} | {n} | {p:.1%} | {j:.1%} | {c:.2f} |")
    if by:
        bm = collections.defaultdict(list)
        for r in rows:
            bm[r.get(by)].append(r)
        print(f"\n| {by} | n | proxy | judge |\n|---|---|---|---|")
        for k, g in sorted(bm.items(), key=lambda kv: -len(kv[1])):
            print(f"| {k} | {len(g)} | {sum(r['proxy_correct'] for r in g)} | {sum(r['judge_correct'] for r in g)} |")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--by")
    a = ap.parse_args()
    for p in a.runs:
        rescore(p, a.jobs, a.by)
