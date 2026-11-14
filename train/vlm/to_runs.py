"""Turn eval_vlm.py results on the test sample into eval.py's runs/ schema (+ summary.md), so VLM numbers sit
next to the other solvers and can be joined with them by question id.

    python train/vlm/to_runs.py cache/vlm/test_r3final_1000.jsonl vlm_q3vl8b_r3_test1000 \
        --like runs/vlm_q3vl8b_r2_test1000.jsonl --usd-per-hour 5.19 --wall-seconds 900

The test rows were produced on the GPU box from the same question ids as `--like` (an eval.py run); path,
type, ext, lang and gold are taken from there. Evidence boxes are re-parsed from the stored reply text.
cost_usd = wall-clock GPU time x hourly price / n (requests ran concurrently, so per-request latency would
overcount).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bp.score import is_correct  # noqa: E402
from bp.vlm.format import is_paligemma, parse_output, parse_paligemma  # noqa: E402
from eval import table  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("name")
    ap.add_argument("--like", required=True)
    ap.add_argument("--usd-per-hour", type=float, default=5.19)
    ap.add_argument("--wall-seconds", type=float, required=True, help="GPU wall time of the whole run")
    ap.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    a = ap.parse_args()
    like = {r["id"]: r for r in map(json.loads, open(a.like))}
    res = {}
    for line in open(a.results):
        try:
            r = json.loads(line)
            res[r["id"]] = r
        except ValueError:
            pass
    pali = is_paligemma(a.model)
    per_q = a.wall_seconds * a.usd_per_hour / 3600 / max(1, len(res))
    rows = []
    for qid, L in like.items():
        r = res.get(qid)
        if r is None:
            pred, conf, ev, lat = None, 0.0, [], 0.0
        else:
            p = (parse_paligemma if pali else parse_output)(r["text"])
            pred, conf, lat = r["pred"], r["conf"] or 0.0, r["seconds"]
            file = L["path"] if L["source"] != "swiss_dwellings" else str(Path(L["path"]).with_suffix(".png"))
            ev = [{"kind": "box", "file": file, "page": 0, "bbox": [round(v, 5) for v in b], "label": f"{lab} {i}",
                   "value": 1} for i, (lab, b) in enumerate(p["items"], 1)]
        rows.append({"id": qid, "path": L["path"], "source": L["source"], "type": L["type"], "ext": L["ext"],
                     "lang": L["lang"], "question": L["question"], "gold": L["gold"], "pred": pred,
                     "correct": is_correct(L["type"], pred, L["gold"]) if pred is not None else None,
                     "confidence": round(conf, 4), "cost_usd": round(per_q, 6) if r else 0.0, "latency_s": lat,
                     "method": f"vlm-{a.name}", "evidence": ev})
    out = ROOT / "runs" / f"{a.name}.jsonl"
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    text = "\n".join([f"# {a.name}", "", f"model `{a.model}` + LoRA, test split, n={len(rows)} (question ids of "
                      f"`{Path(a.like).name}`), {len(res)} answered; cost = {a.wall_seconds / 60:.0f} min GPU wall "
                      f"time x ${a.usd_per_hour}/h", "",
                      "accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.", "",
                      "## By source", table(rows, lambda r: r["source"]), "",
                      "## By language", table(rows, lambda r: r["lang"]), ""])
    (ROOT / "runs" / f"{a.name}.summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
