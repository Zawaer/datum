"""The router on EVERY question of the dataset (held-out test + everything we developed / trained on), sharded over
processes, with accuracy reported per split so the in-sample part is never mixed up with the held-out headline.

    .venv/bin/python analysis/full_dataset.py --name router_full_all_v8 --shards 4 --jobs 4
    .venv/bin/python analysis/full_dataset.py --name router_full_all_v8 --merge-only   # re-merge / re-summarise

Several detector processes on a shared 8 GB GPU can run out of memory; such questions log a solver error. Re-run
them on CPU as runs/<name>_r<k>.jsonl (eval.py --ids-from, CUDA_VISIBLE_DEVICES=); --merge-only prefers rows
without an error.

Splits in the report (bp/data.py splits by drawing; the detector split by bp/cubicasa + train/cubicasa/make_yolo.py):
- test        : the 20 % held-out drawings. Nothing was trained or tuned on them (the published headline).
- cc-train    : CubiCasa dev drawings the YOLO detector was TRAINED on (in-sample for the detector).
- cc-dev-val  : CubiCasa dev drawings held out from detector training but used to tune thresholds, calibration
                and the VLM arbiter (in-sample for those choices). The VLM's precomputed dev-val answers are
                looked up here (cache/vlm_dev/devval_r3.jsonl), like the test answers are on test.
- dev         : every other source's non-test drawings (Swiss, IFC, ifc_bench, ...): rules and prompts were
                developed on them (in-sample).
On cc-train there are no precomputed VLM answers, so the arbiter never fires there (detector only).
"""
import argparse
import collections
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from bp.data import load_questions  # noqa: E402

LABELS = {
    "test": "test (held out: never trained or tuned on)",
    "cc-dev-val": "CubiCasa dev-val (in-sample for thresholds / calibration / arbiter; detector never trained on it)",
    "cc-train": "CubiCasa detector-training drawings (in-sample for the detector)",
    "dev": "other sources' dev drawings (in-sample: rules and prompts developed on them)",
}


def split_of_row(q, val_stems):
    if q["split"] == "test":
        return "test"
    if q["source"] == "cubicasa5k":
        return "cc-dev-val" if Path(q["path"]).stem in val_stems else "cc-train"
    return "dev"


def devval_vlm_lookup(out):
    """cache/vlm_dev/devval_r3.jsonl (eval_vlm rows keyed by the devval_cc row id) -> rows bp.crosscheck can index."""
    meta = {r["id"]: r for r in map(json.loads, open(REPO / "cache/vlm_dev/devval_cc.jsonl"))}
    with open(out, "w") as f:
        for r in map(json.loads, open(REPO / "cache/vlm_dev/devval_r3.jsonl")):
            m = meta[r["id"]]
            if r.get("pred") is None:
                continue
            f.write(json.dumps({"path": m["path"], "question": m["question"], "pred": r["pred"],
                                "confidence": r.get("conf"), "evidence": []}, ensure_ascii=False) + "\n")


def table(rows, key):
    by = collections.defaultdict(list)
    for r in rows:
        by[key(r)].append(r)
    out = ["| group | n | accuracy |", "|---|---|---|"]
    for k in sorted(by, key=lambda k: (-len(by[k]), k)) + ["ALL"]:
        g = rows if k == "ALL" else by[k]
        ok = sum(1 for r in g if r["correct"])
        out.append(f"| {'**ALL**' if k == 'ALL' else k} | {len(g)} | {ok / len(g):.1%} |")
    return "\n".join(out)


def summary(name, rows):
    n = len(rows)
    ok = sum(1 for r in rows if r["correct"])
    test = [r for r in rows if r["split"] == "test"]
    ins = [r for r in rows if r["split"] != "test"]
    acc = lambda g: sum(1 for r in g if r["correct"]) / len(g)  # noqa: E731
    lines = [f"# {name}", "",
             f"**Full dataset, all {n:,} questions (every split): {ok / n:.1%}.** This number is mostly IN-SAMPLE: "
             f"{len(ins):,} of the questions are on drawings we trained the detector on or tuned rules / thresholds "
             f"on. Held-out test part alone: {acc(test):.1%} (n={len(test):,}); in-sample part alone: "
             f"{acc(ins):.1%} (n={len(ins):,}). The published held-out headline stays router_full_test_v8.", "",
             "Solver `router` (shipped pipeline: flip-TTA YOLO11m v4 + VLM arbiter for CubiCasa), text answers scored "
             "by the LLM judge, abstain = wrong. Built by analysis/full_dataset.py.", "",
             "Splits:", ""] + [f"- `{k}`: {v}" for k, v in LABELS.items()] + [
             "", "## By split", table(rows, lambda r: r["split"]), "",
             "## By source", table(rows, lambda r: r["source"]), "",
             "## By split and source", table(rows, lambda r: f"{r['split']} / {r['source']}"), "",
             "## By source and type", table(rows, lambda r: f"{r['source']} / {r['type']}"), ""]
    errs = collections.Counter(str(r["error"])[:120] for r in rows if r.get("error"))
    if errs:
        lines += [f"**{sum(errs.values())} questions hit a solver error** (counted wrong):", ""] + \
            [f"- {k} x `{e}`" for e, k in errs.most_common(5)] + [""]
    (REPO / "runs" / f"{name}.summary.md").write_text("\n".join(lines))
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="router_full_all_v8")
    ap.add_argument("--shards", type=int, default=4)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--merge-only", action="store_true")
    a = ap.parse_args()
    os.chdir(REPO)
    qs = load_questions()
    val_stems = {p.stem for p in Path("cache/yolo_cc/images/val").glob("*.png")}
    split = {q["id"]: split_of_row(q, val_stems) for q in qs}
    sd = Path("cache/full_all") / a.name
    sd.mkdir(parents=True, exist_ok=True)
    if not a.merge_only:
        lookup = sd / "vlm_devval_lookup.jsonl"
        devval_vlm_lookup(lookup)
        vlm_files = [str(REPO / "cache/vlm/demo_secondopinion.jsonl"), str(REPO / "runs/vlm_r3_cubicasa_test_full.jsonl"),
                     str(lookup)]
        # shard by drawing (keeps the per-drawing detection cache warm), balanced by drawing count
        paths = sorted({q["path"] for q in qs}, key=lambda p: (p.split("/")[1], p))
        shard_of = {p: i % a.shards for i, p in enumerate(paths)}
        procs = []
        for s in range(a.shards):
            ids = sd / f"ids_{s}.jsonl"
            with open(ids, "w") as f:
                for q in qs:
                    if shard_of[q["path"]] == s:
                        f.write(json.dumps({"id": q["id"]}) + "\n")
            env = {**os.environ, "BP_XCHECK_VLM": os.pathsep.join(vlm_files)}
            log = open(sd / f"shard_{s}.log", "w")
            procs.append(subprocess.Popen(
                [sys.executable, "eval.py", "--solver", "router", "--split", "all", "--ids-from", str(ids),
                 "--jobs", str(a.jobs), "--judge", "--name", f"{a.name}_s{s}"], env=env, stdout=log, stderr=log))
        for p in procs:
            p.wait()
    # shards, then repair runs (runs/<name>_r*.jsonl: questions re-run on CPU after a GPU out-of-memory error);
    # per question the last row without a solver error wins
    by_id = {}
    files = [Path(f"runs/{a.name}_s{s}.jsonl") for s in range(a.shards)] + sorted(Path("runs").glob(f"{a.name}_r*.jsonl"))
    for fn in files:
        for line in open(fn):
            r = json.loads(line)
            if r["id"] not in by_id or not r.get("error"):
                by_id[r["id"]] = r
    missing = [q["id"] for q in qs if q["id"] not in by_id]
    if missing:
        sys.exit(f"{len(missing)} questions have no row yet (e.g. {missing[:5]})")
    rows = list(by_id.values())
    for r in rows:
        r["split"] = split[r["id"]]
    rows.sort(key=lambda r: r["id"])
    with open(f"runs/{a.name}.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    summary(a.name, rows)


if __name__ == "__main__":
    main()
