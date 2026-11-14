"""Dump a deterministic sample of judge-wrong ifctext dev answers with the fact sheet lines that the model saw,
for hand-labelling failure causes (sheet missing info / model reasoning / judge strictness).

    .venv/bin/python analysis/ifctext_failures.py runs/ifctext_dev_haiku_rerun.jsonl 40 > /tmp/fail.txt
"""
import hashlib
import json
import sys

sys.path.insert(0, ".")

run, n = sys.argv[1], int(sys.argv[2])
rows = [json.loads(l) for l in open(run)]
bad = [r for r in rows if str(r["correct"]) != "True" and r["method"].startswith("ifctext-")]
bad.sort(key=lambda r: hashlib.sha1(str(r["id"]).encode()).hexdigest())
show_sheet = "--sheet" in sys.argv
if show_sheet:
    from bp.ifc.bench import find_space, find_storey
    from bp.ifc.extract import load_model
    from bp.ifctext.factsheet import build, render
    from bp.solvers.ifc import ifc_path_for
print(f"{len(bad)} wrong of {len(rows)}; showing {n}\n")
for r in bad[:n]:
    print("=" * 100)
    print(f"id {r['id']}  {r['path']}\nQ: {r['question']}\nGOLD: {str(r['gold'])[:700]}\nPRED: {str(r['pred'])[:1200]}"
          f"\nJUDGE: {r['judge_reason']}")
    if show_sheet:
        rel, ifc = ifc_path_for(r["path"])
        m = load_model(ifc)
        st, sp = find_storey(m, r["question"]), find_space(m, r["question"])
        facts, _ = render(build(m), r["question"], 14000, focus={st["name"]} if st else None,
                          space=sp.get("name") if sp else None)
        print("SHEET:\n" + facts[:6000])
