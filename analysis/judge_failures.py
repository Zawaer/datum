"""Prioritised failure list of a judge run (runs/judge_<name>.jsonl) -> markdown on stdout.

    .venv/bin/python analysis/judge_failures.py runs/judge_baseline.jsonl [--prev runs/judge_1530.jsonl] [--notes notes.md]

Priority: questions wrong on every form (the system cannot do it at all) > wrong on some forms (input-form fragility:
works on hi-res, not on the low-res JPG or the PDF, or the reverse) > only lenient-correct (number off by 5-15 %).
Within a tier: tricks answered with a confident number first, then by sheet.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

FORMS = ("scanpdf", "roughscan", "lowres", "png2500", "pdf", "hires")


def load(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def acc_by_form(rows):
    d = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        d[r["form"]][0] += r["ok"]; d[r["form"]][1] += r["ok15"]; d[r["form"]][2] += 1
    return d


def short(res):
    a = res.get("answer")
    s = str(a) if a is not None else (f"abstain (guess {res.get('tentative_answer')})" if res.get("tentative_answer")
                                     is not None else "abstain")
    return s.replace("\n", " ")[:90]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--prev", default="")
    ap.add_argument("--notes", default="")
    a = ap.parse_args()
    rows = load(a.run)
    name = Path(a.run).stem.replace("judge_", "")
    L = [f"# Judge QA: latest run `{name}`", ""]
    if a.notes and Path(a.notes).exists():
        L += [Path(a.notes).read_text().strip(), ""]
    acc = acc_by_form(rows)
    prev = acc_by_form(load(a.prev)) if a.prev else {}
    L += ["## Accuracy per upload form", "",
          "| form | strict | lenient 15 % |" + (" previous strict |" if prev else ""),
          "|---|---|---|" + ("---|" if prev else "")]
    for f in FORMS:
        if f in acc:
            v = acc[f]
            L.append(f"| {f} | {v[0]}/{v[2]} | {v[1]}/{v[2]} |" + (f" {prev[f][0]}/{prev[f][2]} |" if f in prev else ""))
    tot = sum(r["ok"] for r in rows)
    L += ["", f"Total {tot}/{len(rows)} strict. Forms: scanpdf = image-only PDF of a clean ~200 dpi "
              "office scan (no text layer), roughscan = ~2500 px JPEG of a poor scan (1.5 deg skew, blur, noise, yellow "
              "paper, q55), lowres = ~2000 px JPG, png2500 = ~2500 px PNG, pdf = single-page vector PDF, hires = "
              "full-resolution PNG (asked through the real UI with Playwright).", ""]
    if a.prev:
        old = {(r["id"], r["form"]): r for r in load(a.prev)}
        fixed = [(r["id"], r["form"]) for r in rows if r["ok"] and not old.get((r["id"], r["form"]), {}).get("ok", 1)]
        broke = [(r["id"], r["form"], str(old[(r["id"], r["form"])]["res"].get("answer"))[:30], short(r["res"])[:40])
                 for r in rows if not r["ok"] and old.get((r["id"], r["form"]), {}).get("ok")]
        L += [f"Since `{Path(a.prev).stem.replace('judge_', '')}`: fixed {len(fixed)}: "
              + ", ".join(f"{i}/{f}" for i, f in fixed), "",
              f"**Regressions {len(broke)}**: " + ("; ".join(f"{i}/{f} (was `{o}`, now `{n}`)" for i, f, o, n in broke)
                                                   or "none"), ""]
    by_id = defaultdict(dict)
    for r in rows:
        by_id[r["id"]][r["form"]] = r
    tiers = {"A": [], "B": [], "C": []}
    for qid, d in by_id.items():
        oks = [d[f]["ok"] for f in d]
        if all(oks):
            continue
        r0 = next(iter(d.values()))
        trick_conf = r0["type"] == "trick" and any(d[f]["res"].get("answer") is not None and not d[f]["ok"] for f in d)
        if not any(oks):
            tier = "C" if any(d[f]["ok15"] for f in d) else "A"
        else:
            tier = "B"
        tiers[tier].append((0 if trick_conf else 1, r0["sheet"], qid, d))
    titles = {"A": "Wrong on every form (fix first)", "B": "Form-dependent (right on some uploads, wrong on others)",
              "C": "Close but outside 5 % (within 15 %)"}
    n = 0
    for t in "ABC":
        if not tiers[t]:
            continue
        L += [f"## {titles[t]}", ""]
        for _, sheet, qid, d in sorted(tiers[t]):
            n += 1
            r0 = next(iter(d.values()))
            L.append(f"{n}. **{qid}** [{sheet} / {r0['category']} / {r0['lang']}] \"{r0['question']}\"  ")
            L.append(f"   gold: {r0['gold']} ({r0['gold_confidence']}; {r0['how'][:160]})  ")
            for f in FORMS:
                if f in d:
                    res = d[f]["res"]
                    ev = res.get("evidence") or []
                    L.append(f"   - {f}: {'OK' if d[f]['ok'] else 'x '} `{short(res)}` (conf {res.get('confidence')}, "
                             f"{res.get('method')}, {len(ev)} evidence, {res.get('latency_s')} s)"
                             + (f" — error {str(res.get('error'))[:80]}" if res.get("error") else ""))
            h = d.get("hires", {})
            if h.get("screenshot"):
                L.append(f"   - screenshot: {h['screenshot']}")
            L.append("")
    print("\n".join(L))


if __name__ == "__main__":
    main()
