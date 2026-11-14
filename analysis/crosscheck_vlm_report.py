"""CubiCasa cross-check with the fine-tuned VLM as the second opinion, measured on the full test split.

    .venv/bin/python analysis/crosscheck_vlm_report.py [runs/cubicasa_test_v4.jsonl] > runs/crosscheck_vlm_test.summary.md

Primary = the shipped detector's eval.py rows (YOLO11m v4); the second opinion comes from bp.crosscheck.crosscheck
itself (precomputed VLM answers, runs/vlm_r3_cubicasa_test_full.jsonl), so this measures the code the demo runs.
The v3 detector is read from its on-disk cache only (never run here). Writes runs/crosscheck_vlm_test.jsonl
(eval.py schema + "crosscheck") for analysis/crosscheck_report.py. Nothing is tuned: the 0.5 conflict factor and
the 0.5 abstain threshold are the router's existing dev-chosen rule.
"""
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "analysis"))
import bp.crosscheck as xc  # noqa: E402
from bp.score import is_correct  # noqa: E402
from crosscheck_report import group_key_fns, table  # noqa: E402


def _cached_dets(path):
    try:
        return json.loads((xc.CC_DET_CACHE / (Path(path).stem + ".json")).read_text())
    except (OSError, ValueError):
        return None


def pct(a, b):
    return f"{a / b:.1%}" if b else "-"


def at_coverage(rows, score, cov):
    """Accuracy over the top `cov` fraction of rows ranked by score (ties broken by id, deterministic)."""
    k = max(1, round(cov * len(rows)))
    top = sorted(rows, key=lambda r: (-score(r), r["id"], r["lang"]))[:k]
    return sum(r["correct"] for r in top) / k


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "runs/cubicasa_test_v4.jsonl"
    xc.cc_second_dets = _cached_dets
    # the full-test run only: the demo file (a separate, later run on 924 questions) differs on ~50 answers
    xc.VLM_FILES = [REPO / "runs/vlm_r3_cubicasa_test_full.jsonl"]
    rows = []
    for line in open(REPO / src):
        r = json.loads(line)
        cc = xc.crosscheck(r, {"answer": r["pred"], "method": r.get("method", "cubicasa-yolo")})
        sec = cc.get("second") or {}
        r["crosscheck"] = {"status": cc["status"], "answer": sec.get("answer"), "method": sec.get("method"),
                           "note": cc.get("note")}
        r["correct"] = bool(r["correct"])
        r["conf_x"] = (r["confidence"] or 0) * (0.5 if cc["status"] == "conflict" else 1.0)
        r["vlm_ok"] = sec.get("answer") is not None and is_correct("count", sec.get("answer"), r["gold"])
        r.pop("evidence", None)
        rows.append(r)
    out = REPO / "runs/crosscheck_vlm_test.jsonl"
    with open(out, "w") as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = len(rows)
    st = collections.Counter(r["crosscheck"]["status"] for r in rows)
    meth = collections.Counter(r["crosscheck"]["method"] for r in rows)
    ag = [r for r in rows if r["crosscheck"]["status"] == "agree"]
    cf = [r for r in rows if r["crosscheck"]["status"] == "conflict"]
    ok = lambda xs: sum(r["correct"] for r in xs)  # noqa: E731
    print("# crosscheck_vlm_test: the fine-tuned VLM as the CubiCasa second opinion\n")
    print(f"All {n:,} CubiCasa test questions (both languages). Primary: `{src}` (YOLO11m v4, the shipped "
          "detector). Second opinion: `bp/crosscheck.py` with the precomputed answers of the fine-tuned "
          "Qwen3-VL-8B + LoRA (r3, checkpoint-2200; `runs/vlm_r3_cubicasa_test_full.jsonl`). Log "
          "`runs/crosscheck_vlm_test.jsonl`; tables from `analysis/crosscheck_vlm_report.py`. Nothing tuned on "
          "test: the router rule (confidence x 0.5 on conflict, abstain below 0.5) was chosen on dev with the "
          "detector pairing; no per-target rule (the VLM has no dev-val run, so none was chosen).\n")
    print("## Headline\n")
    print("| | value |\n|---|---|")
    print(f"| second methods used | {', '.join(f'{m} ({v:,})' for m, v in meth.most_common())} |")
    print(f"| VLM alone / detector alone | {pct(sum(r['vlm_ok'] for r in rows), n)} / {pct(ok(rows), n)} |")
    print(f"| coverage (has a VLM answer) | {pct(st['agree'] + st['conflict'], n)} |")
    print(f"| **agree** | **{pct(len(ag), n)}** ({len(ag):,} questions) |")
    print(f"| **detector right when they agree** | **{pct(ok(ag), len(ag))}** |")
    print(f"| conflict | {pct(len(cf), n)} ({len(cf):,}) |")
    print(f"| on conflict: detector right / VLM right | {pct(ok(cf), len(cf))} / "
          f"{pct(sum(r['vlm_ok'] for r in cf), len(cf))} |")
    wrong = [r for r in rows if not r["correct"]]
    print(f"| conflict precision (detector wrong given conflict) | {pct(len(cf) - ok(cf), len(cf))} |")
    print(f"| recall (wrong answers flagged as conflict) | "
          f"{pct(sum(r['crosscheck']['status'] == 'conflict' for r in wrong), len(wrong))} |")
    print(f"| cost of the second opinion | $0.16 per 1,000 questions (one H100, `runs/vlm_r3_cubicasa_test_full.summary.md`) |")

    print("\n## By question kind\n")
    print(table(rows, group_key_fns()))

    print("\n## Selective answering: accuracy on the answers kept\n")
    print("Rank by the detector's calibrated confidence alone, by the router's rule (confidence x 0.5 on a VLM "
          "conflict), or agree-first (VLM agreement, then confidence); keep the top fraction.\n")
    cov_ag = len(ag) / n
    covs = [1.0, 0.9, 0.8, cov_ag, 0.7, 0.6, 0.5]
    rk = {"confidence alone": lambda r: r["confidence"] or 0,
          "confidence x 0.5 on conflict (router)": lambda r: r["conf_x"],
          "agree first, then confidence": lambda r: (r["crosscheck"]["status"] == "agree") + (r["confidence"] or 0) / 2}
    print("| ranking | " + " | ".join(f"{c:.0%}" if c != cov_ag else f"**{c:.1%}** (= agree share)" for c in covs)
          + " |")
    print("|---|" + "---|" * len(covs))
    for name, f in rk.items():
        print(f"| {name} | " + " | ".join(f"{at_coverage(rows, f, c):.1%}" for c in covs) + " |")
    print("\nRouter threshold (answer only if confidence >= 0.5, else \"not sure\"):\n")
    print("| | answered | accuracy on answered |\n|---|---|---|")
    for name, key in (("before the cross-check", "confidence"), ("after x 0.5 on VLM conflict", "conf_x")):
        kept = [r for r in rows if (r[key] or 0) >= 0.5]
        print(f"| {name} | {pct(len(kept), n)} | {pct(ok(kept), len(kept))} |")


if __name__ == "__main__":
    main()
