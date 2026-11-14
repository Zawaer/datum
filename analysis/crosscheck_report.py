"""Measure the second-method cross-check on an eval.py log written with --crosscheck.

    .venv/bin/python eval.py --solver router --split test --source swiss_dwellings --source ifc_models \
        --source cubicasa5k --jobs 4 --crosscheck --name crosscheck_test
    .venv/bin/python analysis/crosscheck_report.py runs/crosscheck_test.jsonl > runs/crosscheck_test.summary.md

coverage = questions with a second method / all; agreement = agree / covered;
conflict precision = P(primary wrong | conflict); recall = P(conflict | primary wrong) over all questions
(and over covered ones); "2nd right | conflict" = how often the second method holds the gold answer when the
two disagree (what a "prefer the second method" rule would gain).
"""
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bp.score import is_correct  # noqa: E402


def pct(a, b):
    return f"{a / b:.1%}" if b else "-"


def group_key_fns():
    from bp.cubicasa.questions import target
    from bp.solvers.swiss import parse_question

    def sub(r):
        if r["source"] == "cubicasa5k":
            return f"cubicasa5k / {target(r['question'])}"
        if r["source"] == "swiss_dwellings":
            it = parse_question(r["question"], r["type"])
            k = it[0] if it else "?"
            if it and it[0] == "count_symbol":
                k += f" {it[1]}"
            return f"swiss / {k}"
        return f"{r['source']} / {r['type']}"
    return sub


def table(rows, key):
    by = collections.defaultdict(list)
    for r in rows:
        by[key(r)].append(r)
    out = ["| group | n | primary acc | coverage | agree | conflict | acc on agree | acc on conflict | acc on single "
           "| conflict precision | recall (all wrong) | recall (covered wrong) | 2nd right on conflict |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in sorted(by, key=lambda k: (-len(by[k]), k)) + ["ALL"]:
        g = rows if k == "ALL" else by[k]
        n = len(g)
        st = collections.Counter(r["crosscheck"]["status"] for r in g)
        cov = st["agree"] + st["conflict"]
        ok = lambda xs: sum(1 for r in xs if r["correct"])  # noqa: E731
        ag = [r for r in g if r["crosscheck"]["status"] == "agree"]
        cf = [r for r in g if r["crosscheck"]["status"] == "conflict"]
        si = [r for r in g if r["crosscheck"]["status"] == "single"]
        wrong = [r for r in g if not r["correct"]]
        wrong_cov = [r for r in wrong if r["crosscheck"]["status"] != "single"]
        sec_ok = sum(1 for r in cf if is_correct(r["type"], r["crosscheck"]["answer"], r["gold"]))
        name = f"**{k}**" if k == "ALL" else k
        out.append(f"| {name} | {n} | {pct(ok(g), n)} | {pct(cov, n)} | {pct(st['agree'], cov)} | {st['conflict']} "
                   f"| {pct(ok(ag), len(ag))} | {pct(ok(cf), len(cf))} | {pct(ok(si), len(si))} "
                   f"| {pct(len(cf) - ok(cf), len(cf))} | {pct(sum(1 for r in wrong if r['crosscheck']['status'] == 'conflict'), len(wrong))} "
                   f"| {pct(sum(1 for r in wrong_cov if r['crosscheck']['status'] == 'conflict'), len(wrong_cov))} "
                   f"| {pct(sec_ok, len(cf))} |")
    return "\n".join(out)


def main():
    path = sys.argv[1]
    rows = [json.loads(line) for line in open(path)]
    rows = [r for r in rows if "crosscheck" in r]
    for r in rows:
        r["correct"] = bool(r["correct"])
    name = Path(path).stem
    methods = collections.Counter((r["source"], r["crosscheck"]["method"]) for r in rows
                                  if r["crosscheck"]["status"] != "single")
    print(f"# {name}: second-method cross-check\n")
    print(f"log `{path}`, n={len(rows)}; router primary answers, cross-check from `bp/crosscheck.py`.\n")
    print("coverage = has a second method; agree = of covered; conflict precision = P(primary wrong | conflict); "
          "recall = P(conflict | primary wrong), over all wrong answers and over the covered ones; "
          "2nd right on conflict = second method matches gold when the two disagree.\n")
    print("## By source\n")
    print(table(rows, lambda r: r["source"]))
    print("\n## By source and question kind\n")
    print(table(rows, group_key_fns()))
    print("\n## Second methods used\n")
    print("| source | method | answers checked |\n|---|---|---|")
    for (s, m), v in sorted(methods.items(), key=lambda x: -x[1]):
        print(f"| {s} | {m} | {v} |")


if __name__ == "__main__":
    main()
