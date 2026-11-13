#!/usr/bin/env python3
"""Score the free-text answers of a run with the same LLM judge our own text answers were scored with.

    .venv/bin/python analysis/judge_runs.py baseline_sonnet_full400 baseline_haiku_full400

Writes runs/<run>.judged.jsonl: every row of the run, with text/other rows re-scored by bp/judge.py
(proxy verdict kept as `proxy_correct`, judge verdict in `judge_correct` and `correct`). Abstentions stay
wrong. Verdicts are cached under cache/judge, so re-running is free.
"""
import concurrent.futures as cf
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bp.judge import judge  # noqa: E402

RUNS = Path(__file__).resolve().parent.parent / "runs"


def main(names):
    for name in names:
        rows = [json.loads(l) for l in open(RUNS / f"{name}.jsonl")]
        todo = [r for r in rows if r["type"] in ("text", "other") and r["pred"] is not None]

        def one(r):
            v = judge(r["question"], r["gold"], r["pred"])
            return r["id"], v

        with cf.ThreadPoolExecutor(6) as ex:
            verdicts = dict(ex.map(one, todo))
        cost = 0.0
        with open(RUNS / f"{name}.judged.jsonl", "w") as f:
            for r in rows:
                if r["id"] in verdicts:
                    v = verdicts[r["id"]]
                    cost += v.get("cost_usd", 0.0)
                    r = {**r, "proxy_correct": r["correct"], "judge_correct": bool(v["correct"]),
                         "correct": bool(v["correct"]), "judge_score": v.get("score"),
                         "judge_reason": v.get("reason"), "judge_cost_usd": v.get("cost_usd", 0.0)}
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        ok = sum(v["correct"] for v in verdicts.values())
        print(f"{name}: judged {len(verdicts)} text answers, {ok} correct, judge cost ${cost:.3f}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["baseline_sonnet_full400", "baseline_haiku_full400"])
