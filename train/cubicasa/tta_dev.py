"""Offline count accuracy of test-time-augmentation / ensemble variants on DEV-val drawings only.

Reads detection caches from tta_dump.py (several weights x views). Each variant fuses a set of views per
class (weighted box fusion: clusters of same-class boxes with IoU >= iou over all views, fused score =
sum of member scores / number of views), then counts boxes over a per-template threshold. Thresholds are
chosen by K-fold cross-validation over drawings (picked on K-1 folds, scored on the held-out fold), so the
reported accuracy is not tuned on the drawings it is measured on; the baseline (identity view, the solver's
per-class inference sizes) goes through the very same protocol, and the shipped solver's in-sample number
is printed too. Paired bootstrap over drawings for the difference.

    .venv/bin/python train/cubicasa/tta_dev.py --dets v4=cache/cubicasa/tta/v4.json v5=cache/cubicasa/tta/v5.json
"""
import argparse
import collections
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bp.cubicasa.classes import COUNTS  # noqa: E402
from bp.cubicasa.questions import target  # noqa: E402
from bp.data import load_questions  # noqa: E402

TH_GRID = [round(0.05 + 0.025 * i, 3) for i in range(37)]  # 0.05 .. 0.95


def iou(a, b):
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    i = iw * ih
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i)


def wbf(view_dets, thr=0.55, skip=0.05):
    """view_dets: list (one per view) of [(cls, score, box)] -> fused [(cls, score, box)]."""
    n = len(view_dets)
    allb = sorted((d for v in view_dets for d in v if d[1] >= skip), key=lambda d: -d[1])
    out = []
    for c in {d[0] for d in allb}:
        clusters = []  # [fused_box, [members]]
        for d in (x for x in allb if x[0] == c):
            best, bj = thr, None
            for j, (fb, _) in enumerate(clusters):
                o = iou(d[2], fb)
                if o >= best:
                    best, bj = o, j
            if bj is None:
                clusters.append([list(d[2]), [d]])
            else:
                fb, ms = clusters[bj]
                ms.append(d)
                w = sum(m[1] for m in ms)
                clusters[bj][0] = [sum(m[1] * m[2][k] for m in ms) / w for k in range(4)]
        for fb, ms in clusters:
            # one vote per view at most counts fully: cap members' total at n views
            s = sorted((m[1] for m in ms), reverse=True)[:n]
            out.append((c, sum(s) / n, fb))
    return out


def load_q(stems):
    rows = []
    for q in load_questions():
        st = Path(q["path"]).stem
        if q["source"] == "cubicasa5k" and q["split"] == "dev" and st in stems:
            t = target(q["question"])
            if t:
                rows.append((st, t, round(float(q["answer"]))))
    return rows


def fold_of(stem, k, seed=0):
    return int(hashlib.sha256(f"cv{seed}{stem}".encode()).hexdigest()[:8], 16) % k


def counts_for(fused, t, th_by_cls):
    return sum(1 for d in fused if d[0] in COUNTS[t] and d[1] >= th_by_cls[d[0]])


def _grid(t):
    cs = COUNTS[t]
    if len(cs) == 1:
        return [{cs[0]: th} for th in TH_GRID]
    g = TH_GRID[::2]
    return [{cs[0]: a, cs[1]: b} for a in g for b in g]


def _count(dets, t, th):
    if t == "sauna":  # same rule as the solver: stoves inside a kept sauna room are not counted again
        rooms = [d[2] for d in dets if d[0] == "sauna_room" and d[1] >= th["sauna_room"]]
        dets = [d for d in dets if d[0] == "sauna_room" or not any(
            r[0] - .01 <= (d[2][0] + d[2][2]) / 2 <= r[2] + .01 and r[1] - .01 <= (d[2][1] + d[2][3]) / 2 <= r[3] + .01
            for r in rooms)]
    return sum(1 for d in dets if d[0] in th and d[1] >= th[d[0]])


def cv_eval(rows, fused, k=5, seed=0):
    """fused: stem -> dets, or a list of such candidates (per template the candidate and its thresholds
    are both chosen on the k-1 training folds)."""
    cands = fused if isinstance(fused, list) else [fused]
    """fused: stem -> dets. Per template, pick per-class thresholds on k-1 folds, score the held-out fold.
    Returns ({row index: correct}, {row index: correct} in-sample, in-sample thresholds)."""
    by_t = collections.defaultdict(list)
    for i, (st, t, g) in enumerate(rows):
        by_t[t].append(i)
    res, ins, ths = {}, {}, {}
    for t, idx in by_t.items():
        grid, tab, pen = [], [], []
        for ci, fu in enumerate(cands):
            dd = {i: [d for d in fu[rows[i][0]] if d[0] in COUNTS[t]] for i in idx}
            for th in _grid(t):
                grid.append((ci, th))
                tab.append({i: _count(dd[i], t, th) == rows[i][2] for i in idx})
                pen.append(-sum(abs(v - 0.4) for v in th.values()) - ci)
        for f in range(k):
            tr = [i for i in idx if fold_of(rows[i][0], k, seed) != f]
            te = [i for i in idx if fold_of(rows[i][0], k, seed) == f]
            j = max(range(len(grid)), key=lambda j: (sum(tab[j][i] for i in tr), pen[j]))
            for i in te:
                res[i] = tab[j][i]
        j = max(range(len(grid)), key=lambda j: (sum(tab[j].values()), pen[j]))
        ths[t] = grid[j]
        ins.update(tab[j])
    return res, ins, ths


def boot(rows, a, b, n=2000, seed=0):
    stems = sorted({r[0] for r in rows})
    per = collections.defaultdict(lambda: [0, 0, 0])
    for i, r in enumerate(rows):
        per[r[0]][0] += a[i]
        per[r[0]][1] += b[i]
        per[r[0]][2] += 1
    rng = random.Random(seed)
    N = len(rows)
    diffs = []
    for _ in range(n):
        s = [rng.choice(stems) for _ in stems]
        cnt = collections.Counter(s)
        da = sum(per[x][0] * c for x, c in cnt.items())
        db = sum(per[x][1] * c for x, c in cnt.items())
        nn = sum(per[x][2] * c for x, c in cnt.items())
        diffs.append((db - da) / nn)
    diffs.sort()
    return (sum(b.values()) - sum(a.values())) / N, diffs[int(0.025 * n)], diffs[int(0.975 * n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets", nargs="+", required=True, help="name=path of tta_dump.py caches")
    ap.add_argument("--variants", nargs="*", default=None, help="name:view,view,...  view = model/size_tf or model/C_tf"
                                                              " (C = the class's tuned size)")
    ap.add_argument("--thresholds", default="cache/cubicasa/weights/thresholds.json")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--seeds", type=int, default=5, help="repeat CV with this many fold splits")
    ap.add_argument("--wbf-iou", type=float, default=0.55)
    a = ap.parse_args()
    D = {}
    for s in a.dets:
        n, p = s.split("=", 1)
        D[n] = json.loads(Path(p).read_text())
    stems = set.intersection(*[set(v) for v in D.values()])
    rows = load_q(stems)
    print(f"{len(stems)} drawings, {len(rows)} dev questions")
    cls_imgsz = json.loads(Path(a.thresholds).read_text())["_cls_imgsz"]

    def views(st, spec):
        out = []
        for v in spec.split(","):
            m, rest = v.split("/")
            sz, tf = rest.split("_")
            if sz == "C":
                vd = []
                for size in set(cls_imgsz.values()):
                    vd += [d for d in D[m][st][f"{size}_{tf}"] if cls_imgsz.get(d[0]) == size]
                out.append(vd)
            else:
                out.append(D[m][st][f"{sz}_{tf}"])
        return out

    base_spec = "v4/C_id"
    variants = a.variants or [base_spec]
    if base_spec not in [v.split(":", 1)[-1] for v in variants]:
        variants = ["base:" + base_spec] + variants
    results, fused_by = {}, {}
    for spec in variants:
        name, sp = spec.split(":", 1) if ":" in spec else (spec, spec)
        if sp.startswith("@"):  # per-template choice among earlier variants, made inside the CV
            fused = [fused_by[x] for x in sp[1:].split("+")]
        else:
            fused = {}
            for st in stems:
                vs = views(st, sp)
                fused[st] = vs[0] if len(vs) == 1 else wbf(vs, a.wbf_iou)
            fused_by[name] = fused
        cv, ins, ths = cv_eval(rows, fused, a.k)
        reps = [sum(cv_eval(rows, fused, a.k, sd)[0].values()) / len(rows) for sd in range(1, a.seeds)]
        results[name] = (cv, ths, ins, [sum(cv.values()) / len(rows)] + reps)
        by = collections.defaultdict(list)
        for i, r in enumerate(rows):
            by[r[1]].append(cv[i])
        print(f"\n== {name} ({sp}): CV {sum(cv.values()) / len(rows):.2%}  in-sample {sum(ins.values()) / len(rows):.2%}")
        print("  " + "  ".join(f"{t} {sum(v) / len(v):.1%}" for t, v in sorted(by.items())))
        print("  thresholds (in-sample):", ths)
    b = results[variants[0].split(":", 1)[0] if ":" in variants[0] else variants[0]][0]
    bm = sum(results[next(iter(results))][3]) / a.seeds
    for n, (cv, _, _, reps) in results.items():
        d, lo, hi = boot(rows, b, cv)
        print(f"{n}: mean CV over {a.seeds} fold splits {sum(reps) / a.seeds:.2%} ({sum(reps) / a.seeds - bm:+.2%} vs base)")
        per_t = collections.defaultdict(lambda: [0, 0])
        for i, r in enumerate(rows):
            per_t[r[1]][0] += cv[i] - b[i]
            per_t[r[1]][1] += 1
        print(f"{n}: CV diff vs base {d:+.2%} [{lo:+.2%}, {hi:+.2%}]  by template:",
              " ".join(f"{t}:{v[0]:+d}" for t, v in sorted(per_t.items()) if v[0]))


if __name__ == "__main__":
    main()
