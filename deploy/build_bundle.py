"""Build the public-demo data bundle: tour drawings + a curated sample per source, nothing else.

    .venv/bin/python deploy/build_bundle.py [--out deploy/bundle]

deploy/bundle/  (gitignored; never commit or redistribute it: the dataset is non-commercial, per-file licences)
  dataset/questions.jsonl            only the questions of the included drawings, each with its full-set "id"
  dataset/data/<source>/...          the drawings (and their twins: .pdf/.png/.dxf/.svg, IFC + rendered plans)
  dataset/data/<source>/LICENSE.md   each included source's licence/credit file
  runs/*.summary.md                  for /results; runs/baseline_*.jsonl stripped to source/cost/latency
  analysis/                          analysis/out tables (csv/json) behind /api/analysis
  weights/best.pt, thresholds.json, calib.json   CubiCasa YOLO detector (primary, YOLO11m v4)
  xcheck/best.pt, cc_second_thresholds_v3s.json   cross-check second detector (YOLO11s v3) + its dev-tuned
                                                  count thresholds (container env BP_XCHECK_CC_WEIGHTS / _TAG)
  xcheck/demo_secondopinion.jsonl    precomputed fine-tuned VLM answers (+ boxes) for the bundle's CubiCasa
                                     questions: the VLM second opinion (container env BP_XCHECK_VLM)
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from bp.data import data_root, split_of  # noqa: E402

N_SWISS, N_CUBI = 40, 50
IFC_MODELS = [  # model stems (IFC <= ~15 MB except molio, which the tour uses)
    "bsc-molio_molio-with-uris", "kit-fzk-haus_ac20-fzk-haus", "kit-institute_ac20-institute-var-2",
    "kit-smiley-west_ac-20-smiley-west-10-bldg", "bsc-duplex_duplex-a-20110907", "bsc-clinic_clinic-architectural",
    "bimspeed-warmond_ar", "tuwien-escape-route_real-world-escape-route-test-model-zdb",
    "rwth-digitalhub_digitalhub-fm-arc-v2", "bsc-esplanades_1807-ep-ar-v18", "bsc-gymzaal-amersfoort_example-project-location",
    "bimspeed-gdynia_ruchu-oporu-18", "bimspeed-frigento_modello-palazzo-testa-cipriano",
]
IFC_BENCH = ["fzk_house_arc", "duplex_arc", "ac20_arc", "4351_arc", "digital_hub_arc", "fantasy_hotel_1_arc",
             "smiley_west_arc", "dental_clinic_arc", "fantasy_office_building_3_arc"]
N_RESBIM = 6
XCHECK_TAG = "v3s"
XCHECK_WEIGHTS = Path("cache/cubicasa/weights_v3/best.pt")
XCHECK_THRESH = Path(f"cache/crosscheck/cc_second_thresholds_{XCHECK_TAG}.json")
XCHECK_VLM = Path("cache/vlm/demo_secondopinion.jsonl")  # Qwen3-VL-8B LoRA r3 answers, precomputed on GPU


def main(out: Path):
    root = data_root()
    qs = [json.loads(l) for l in open(root / "questions.jsonl")]
    by_path = collections.defaultdict(list)
    for q in qs:
        by_path[q["path"]].append(q)
    src = lambda p: p.split("/")[1]  # noqa: E731
    rnd = random.Random(2026)

    tour = json.loads((REPO / "app/tour.json").read_text())
    pick = {s["path"] for s in tour if s.get("path") in by_path}

    def sample(source, n):
        paths = sorted(p for p in by_path if src(p) == source)
        test = [p for p in paths if split_of(p) == "test"]
        rnd.shuffle(test)
        return test[:n]

    pick |= set(sample("swiss_dwellings", N_SWISS)) | set(sample("cubicasa5k", N_CUBI))
    stem = lambda p: Path(p).stem.split("_plan-")[0]  # noqa: E731
    resbim = sorted({stem(p) for p in by_path if src(p) == "ifc_models" and stem(p).startswith("resbim-")})
    rnd.shuffle(resbim)
    models = set(IFC_MODELS) | set(resbim[:N_RESBIM])
    pick |= {p for p in by_path if src(p) == "ifc_models" and stem(p) in models}
    pick |= {p for p in by_path if src(p) == "ifc_bench" and stem(p) in IFC_BENCH}
    pick |= {p for p in by_path if src(p) == "opening_design"}

    ds = out / "dataset"
    if ds.exists():
        shutil.rmtree(ds)
    files: set[Path] = set()
    for p in pick:
        f = root / p
        st = stem(p)
        files |= {g for g in f.parent.iterdir() if g.is_file() and (g.stem == f.stem or g.stem == st
                                                                     or g.stem.startswith(st + "_plan-"))}
    for s in {src(p) for p in pick}:
        if (root / "data" / s / "LICENSE.md").exists():
            files.add(root / "data" / s / "LICENSE.md")
    for f in sorted(files):
        dst = ds / f.relative_to(root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
    with open(ds / "questions.jsonl", "w") as fo:
        for i, q in enumerate(qs):  # keep the full-set id: frontier.json, runs and the VLM file are keyed by it
            if q["path"] in pick:
                q = {**q, "id": q.get("id", i)}
                fo.write(json.dumps(q, ensure_ascii=False) + "\n")

    runs = out / "runs"
    if runs.exists():
        shutil.rmtree(runs)
    runs.mkdir(parents=True)
    for f in (REPO / "runs").glob("*.summary.md"):
        shutil.copy2(f, runs / f.name)
    for f in (REPO / "runs").glob("baseline_*.jsonl"):
        if ".judged" in f.name:
            continue
        with open(f) as fi, open(runs / f.name, "w") as fo:
            for line in fi:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                fo.write(json.dumps({k: r.get(k) for k in ("source", "cost_usd", "latency_s")}) + "\n")

    an = out / "analysis"
    if an.exists():
        shutil.rmtree(an)
    an.mkdir(parents=True)
    for f in (REPO / "analysis/out").glob("*"):
        if f.suffix in (".csv", ".json"):
            shutil.copy2(f, an / f.name)

    w = out / "weights"
    w.mkdir(parents=True, exist_ok=True)
    for name in ("best.pt", "thresholds.json", "calib.json"):
        if (REPO / "cache/cubicasa/weights" / name).exists():
            shutil.copy2(REPO / "cache/cubicasa/weights" / name, w / name)

    # cross-check: the second, separately trained detector and its own count thresholds (bp/crosscheck.py)
    x = out / "xcheck"
    x.mkdir(parents=True, exist_ok=True)
    for src_, name in ((REPO / XCHECK_WEIGHTS, "best.pt"), (REPO / XCHECK_THRESH, XCHECK_THRESH.name),
                       (REPO / XCHECK_VLM, XCHECK_VLM.name)):
        if not src_.exists():
            sys.exit(f"missing {src_} (cross-check second detector)")
        shutil.copy2(src_, x / name)

    per = collections.Counter(src(p) for p in pick)
    nq = sum(len(by_path[p]) for p in pick)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"{len(pick)} drawings, {nq} questions, {len(files)} files, {size / 1e6:.0f} MB -> {out}")
    for s, n in sorted(per.items()):
        print(f"  {s:18s} {n}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "deploy/bundle"))
    main(Path(ap.parse_args().out))
