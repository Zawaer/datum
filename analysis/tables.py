"""Every number behind the figures and docs/RESULTS.md, computed from runs/*.jsonl.

    .venv/bin/python analysis/tables.py      # writes analysis/out/*.csv and analysis/out/numbers.json
"""
from __future__ import annotations

import collections
import csv
import json
import sys

import numpy as np

from common import (OUT, OURS, PRIOR, ROOT, TEMPLATE_ORDER, accuracy, acc_wilson, api_cost_per_1k,
                    compute_cost_per_1k, cubicasa_template, discover_frontier, exists, label_of, load,
                    population, solver_family, stratified)

sys.path.insert(0, str(ROOT))
from bp.score import to_number  # noqa: E402

ROUTER_MIN_CONF = 0.5  # bp/router.py: below this the router would hand over to a fallback / abstain


def systems():
    out = [OURS] + list(discover_frontier())
    if exists(PRIOR):
        out.append(PRIOR)
    return out


# ---------------------------------------------------------------- 1. overall accuracy vs cost
def overall():
    rows = []
    for s in systems():
        rs = load(s)
        a, lo, hi, n, how = accuracy(rs)
        lat = np.mean([r["latency_s"] for r in rs]) if how == "Wilson" else \
            stratified(rs, value=lambda r: r["latency_s"], n_boot=1)[0]
        rows.append(dict(run=s, system=label_of(s), n=n, accuracy=a, ci_lo=lo, ci_hi=hi, ci=how,
                         api_usd_per_1k=api_cost_per_1k(rs), compute_usd_per_1k=compute_cost_per_1k(rs),
                         mean_latency_s=lat, answered=sum(r["pred"] is not None for r in rs) / len(rs)))
    return rows


def paired_on_sample():
    """Ours vs each frontier run on exactly the same sampled questions (raw and re-weighted)."""
    ours = {r["id"]: r for r in load(OURS)}
    out = []
    for f in discover_frontier():
        fr = load(f)
        mine = [ours[r["id"]] for r in fr]
        k_raw = sum(r["ok"] for r in mine) / len(mine)
        e, lo, hi, n = stratified(mine)
        both = sum(a["ok"] and b["ok"] for a, b in zip(mine, fr))
        only_ours = sum(a["ok"] and not b["ok"] for a, b in zip(mine, fr))
        only_them = sum(b["ok"] and not a["ok"] for a, b in zip(mine, fr))
        out.append(dict(baseline=label_of(f), n=n, ours_raw=k_raw, ours_reweighted=e, ours_lo=lo, ours_hi=hi,
                        baseline_raw=sum(r["ok"] for r in fr) / len(fr), both_right=both,
                        only_ours_right=only_ours, only_baseline_right=only_them))
    return out


# ---------------------------------------------------------------- 2. by source x type
def by_stratum():
    pop = population()
    keys = sorted(pop, key=lambda k: -pop[k])
    out = []
    for k in keys:
        row = dict(source=k[0], type=k[1], n_test=pop[k])
        for s in systems():
            rs = [r for r in load(s) if (r["source"], r["type"]) == k]
            if not rs:
                continue
            a, lo, hi, n = acc_wilson(rs)
            row[f"{s}:n"], row[f"{s}:acc"], row[f"{s}:lo"], row[f"{s}:hi"] = n, a, lo, hi
            if k[1] == "text":
                row[f"{s}:proxy_acc"] = sum(bool(r["proxy_correct"]) for r in rs) / n
                row[f"{s}:text_scoring"] = ",".join(sorted({r["text_scoring"] for r in rs}))
        out.append(row)
    return out


# ---------------------------------------------------------------- 3. selective prediction
def coverage_curve(rows):
    """One point per distinct confidence threshold t: answer only when confidence >= t."""
    conf = np.array([r["confidence"] or 0.0 for r in rows])
    ok = np.array([r["ok"] for r in rows], float)
    order = np.argsort(-conf, kind="stable")
    conf, ok = conf[order], ok[order]
    cum = np.cumsum(ok)
    # last index of each distinct confidence value (ties are answered together)
    last = np.r_[np.nonzero(np.diff(conf))[0], len(conf) - 1]
    cov = (last + 1) / len(conf)
    acc = cum[last] / (last + 1)
    return conf[last], cov, acc


def selective():
    out = {}
    for name, filt in [("all", lambda r: True), ("cubicasa", lambda r: r["source"] == "cubicasa5k")]:
        rows = [r for r in load(OURS) if filt(r)]
        t, cov, acc = coverage_curve(rows)
        # area under the risk-coverage curve (lower is better), on the step curve
        risk = 1 - acc
        aurc = float(np.sum(np.diff(np.r_[0, cov]) * risk))
        pts = []
        for th in [ROUTER_MIN_CONF, 0.7, 0.9, 0.95, 0.99]:
            ans = [r for r in rows if (r["confidence"] or 0) >= th]
            k = sum(r["ok"] for r in ans)
            pts.append(dict(threshold=th, coverage=len(ans) / len(rows), answered=len(ans),
                            accuracy_answered=k / len(ans) if ans else float("nan"),
                            wrong_kept=len(ans) - k,
                            wrong_abstained=sum(not r["ok"] for r in rows) - (len(ans) - k)))
        # coverage needed for given target accuracies
        targets = {}
        for goal in [0.90, 0.95, 0.99]:
            okc = cov[acc >= goal]
            targets[goal] = float(okc.max()) if len(okc) else 0.0
        out[name] = dict(n=len(rows), base_acc=float(np.mean([r["ok"] for r in rows])), aurc=aurc,
                         thresholds=pts, coverage_at=targets, curve=(t.tolist(), cov.tolist(), acc.tolist()))
    return out


FAMILIES = [("swiss_counts", "Swiss apartment plans: counts",
             lambda r: r["source"] == "swiss_dwellings" and r["type"] == "count"),
            ("swiss_areas", "Swiss apartment plans: room areas",
             lambda r: r["source"] == "swiss_dwellings" and r["type"] == "area"),
            ("ifc_numeric", "IFC models: counts, areas, volumes, lengths", lambda r: r["source"] == "ifc_models"),
            ("cubicasa", "Finnish raster plans (CubiCasa)", lambda r: r["source"] == "cubicasa5k"),
            ("ifc_text", "IFC-Bench free text (LLM judge)", lambda r: r["source"] == "ifc_bench"),
            ("all", "all", lambda r: True)]


def selective_by_family(th=ROUTER_MIN_CONF):
    """Ours per question family: answer everything vs answer only when confidence >= th (the rest declined)."""
    rows = load(OURS)
    out = []
    for key, label, filt in FAMILIES:
        rs = [r for r in rows if filt(r)]
        if not rs:
            continue
        ans = [r for r in rs if (r["confidence"] or 0) >= th]
        out.append(dict(family=key, label=label, n=len(rs), accuracy_all=sum(r["ok"] for r in rs) / len(rs),
                        threshold=th, answered=len(ans),
                        accuracy_answered=sum(r["ok"] for r in ans) / len(ans) if ans else float("nan"),
                        declined=1 - len(ans) / len(rs)))
    return out


BINS = [(0, .5), (.5, .7), (.7, .9), (.9, .95), (.95, .99), (.99, 1.01)]


def reliability():
    """Accuracy per confidence bin (ours), all test questions and CubiCasa only."""
    out = []
    for name, filt in [("all", lambda r: True), ("cubicasa", lambda r: r["source"] == "cubicasa5k")]:
        rows = [r for r in load(OURS) if filt(r)]
        for lo, hi in BINS:
            g = [r for r in rows if lo <= (r["confidence"] or 0) < hi]
            if not g:
                continue
            a, l, h, n = acc_wilson(g)
            out.append(dict(subset=name, conf_lo=lo, conf_hi=min(hi, 1.0), n=n, accuracy=a, ci_lo=l, ci_hi=h,
                            mean_conf=float(np.mean([r["confidence"] or 0 for r in g])),
                            pred_zero_share=sum(str(r["pred"]) == "0" for r in g) / n))
    return out


def confident_zero():
    """CubiCasa answers of 0 with confidence >= 0.99 that were wrong: the detector saw nothing near threshold."""
    rs = [r for r in load(OURS) if r["source"] == "cubicasa5k" and (r["confidence"] or 0) >= 0.99]
    wrong = [r for r in rs if not r["ok"]]
    z = [r for r in wrong if str(r["pred"]) == "0"]
    return dict(high_conf=len(rs), high_conf_wrong=len(wrong), high_conf_wrong_pred0=len(z))


# ---------------------------------------------------------------- 4. cubicasa templates
def cubicasa_rows(s):
    rs = [r for r in load(s) if r["source"] == "cubicasa5k"]
    for r in rs:
        r["template"] = cubicasa_template(r["question"])
        p, g = to_number(r["pred"]), to_number(r["gold"])
        r["err"] = None if p is None or g is None else round(p) - round(g)
    return rs


def cubicasa_systems():
    out = [OURS] + list(discover_frontier())
    for extra in ["generic_cubicasa_300_haiku"]:
        if exists(extra):
            out.append(extra)
    if exists(PRIOR):
        out.append(PRIOR)
    return out


def by_template():
    out = []
    data = {s: cubicasa_rows(s) for s in cubicasa_systems()}
    for t in TEMPLATE_ORDER:
        row = dict(template=t)
        for s, rs in data.items():
            g = [r for r in rs if r["template"] == t]
            if not g:
                continue
            a, lo, hi, n = acc_wilson(g)
            errs = [r["err"] for r in g if r["err"] is not None]
            row.update({f"{s}:n": n, f"{s}:acc": a, f"{s}:lo": lo, f"{s}:hi": hi,
                        f"{s}:under": sum(e < 0 for e in errs) / n, f"{s}:over": sum(e > 0 for e in errs) / n,
                        f"{s}:abstain": sum(r["err"] is None for r in g) / n,
                        f"{s}:mean_err": float(np.mean(errs)) if errs else float("nan"),
                        f"{s}:mean_gold": float(np.mean([to_number(r["gold"]) for r in g]))})
        out.append(row)
    return out


def error_histogram(s=OURS, clip=5):
    errs = [r["err"] for r in cubicasa_rows(s) if r["err"] is not None]
    c = collections.Counter(max(-clip, min(clip, e)) for e in errs)
    return [dict(error=e, count=c.get(e, 0), share=c.get(e, 0) / len(errs)) for e in range(-clip, clip + 1)]


# ---------------------------------------------------------------- 5. language
def by_language():
    langs = collections.Counter(r["lang"] for r in load(OURS))
    out = []
    for lang, _ in langs.most_common():
        row = dict(lang=lang)
        for s in systems():
            g = [r for r in load(s) if r["lang"] == lang]
            if not g:
                continue
            a, lo, hi, n = acc_wilson(g)
            row.update({f"{s}:n": n, f"{s}:acc": a, f"{s}:lo": lo, f"{s}:hi": hi,
                        f"{s}:sources": "; ".join(f"{k} {v}" for k, v in
                                                  collections.Counter(r["source"] for r in g).most_common())})
        out.append(row)
    return out


def language_twins():
    """CubiCasa en/fi twins (same drawing, same gold, same template): does the answer change with language?"""
    rs = cubicasa_rows(OURS)
    by = collections.defaultdict(dict)
    for r in rs:
        by[(r["path"], r["template"])][r["lang"]] = r
    pairs = [(d["en"], d["fi"]) for d in by.values() if "en" in d and "fi" in d]
    same = sum(str(a["pred"]) == str(b["pred"]) for a, b in pairs)
    return dict(pairs=len(pairs), same_answer=same,
                en_acc=sum(a["ok"] for a, _ in pairs) / max(1, len(pairs)),
                fi_acc=sum(b["ok"] for _, b in pairs) / max(1, len(pairs)))


# ---------------------------------------------------------------- 6. latency
def latency():
    groups = collections.defaultdict(list)
    for s in [OURS] + list(discover_frontier()) + (["generic_cubicasa_300_haiku"]
                                                    if exists("generic_cubicasa_300_haiku") else []):
        per_drawing = collections.defaultdict(float)
        for r in load(s):
            fam = solver_family(r["method"])
            groups[(s, fam)].append(r["latency_s"])
            if s == OURS:  # slowest question on each drawing ~ the cold path (detector / parser actually runs)
                k = (fam, r["path"])
                per_drawing[k] = max(per_drawing[k], r["latency_s"])
        for (fam, _), v in per_drawing.items():
            groups[(s, fam + " · slowest per drawing")].append(v)
    out = []
    for (s, fam), v in groups.items():
        a = np.array(v)
        out.append(dict(run=s, solver=fam, n=len(a), p50=float(np.median(a)), p90=float(np.percentile(a, 90)),
                        p99=float(np.percentile(a, 99)), mean=float(a.mean()), max=float(a.max()), values=a))
    return out


# ---------------------------------------------------------------- write
def _csv(name, rows, drop=("values",)):
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [{k: v for k, v in r.items() if k not in drop} for r in rows]
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with open(OUT / f"{name}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()})


def main():
    ov = overall()
    _csv("overall", ov)
    _csv("paired_on_sample", paired_on_sample())
    _csv("by_source_type", by_stratum())
    sel = selective()
    for k, v in sel.items():
        _csv(f"selective_{k}_thresholds", v["thresholds"])
        t, cov, acc = v["curve"]
        _csv(f"selective_{k}_curve", [dict(threshold=a, coverage=b, accuracy=c) for a, b, c in zip(t, cov, acc)])
    _csv("selective_by_family", selective_by_family())
    _csv("reliability", reliability())
    _csv("cubicasa_templates", by_template())
    _csv("cubicasa_error_hist", error_histogram())
    _csv("by_language", by_language())
    _csv("latency", latency())
    nums = dict(overall=ov, twins=language_twins(), confident_zero=confident_zero(),
                selective={k: {kk: vv for kk, vv in v.items() if kk != "curve"} for k, v in sel.items()})
    (OUT / "numbers.json").write_text(json.dumps(nums, indent=1, default=float))
    for r in ov:
        print(f"{r['system']:32s} n={r['n']:6d} acc={r['accuracy']:.3f} [{r['ci_lo']:.3f},{r['ci_hi']:.3f}] "
              f"api=${r['api_usd_per_1k']:.2f}/1k compute=${r['compute_usd_per_1k']:.4f}/1k")


if __name__ == "__main__":
    main()
