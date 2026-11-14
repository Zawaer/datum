"""From detector scores to a count distribution.

Each detection i of a counted class is real with probability p_i = sigmoid(a_c + b_c * logit(score))
(per-class calibration fitted on dev validation drawings). The number of objects the detector missed
entirely is Poisson(lambda_c). So the count is Poisson-binomial(p) + Poisson(sum lambda). Optionally
multiplied by the template's dev answer distribution raised to a power w (w = 0: detector only).
Answer = posterior mode, confidence = its probability.
"""
import math
import os

KMAX = 60

# Templates counted per wall run (select_runs below) instead of by plain threshold, chosen on dev-val drawings
# (train/cubicasa/rules_dev.py): candidates down to the class threshold + dt, overlaps along a wall resolved.
# Windows: dev-val exact count 48.9 % -> 51.0 % (382 drawings), but on the test split 49.1 % -> 47.9 %
# (112 questions gained, 134 lost: runs/cubicasa_test_v4rules.summary.md), so it is OFF by default.
# Doors: no dev gain, never enabled. Set CUBICASA_RUNS=1 to switch it on.
RUNS = {"window": {"cls": "window", "dt": -0.175, "ovl": 0.1, "align": 0.3}}


def runs_rule(template):
    """The wall-run rule for this template, or None (not used / switched off)."""
    return RUNS.get(template) if os.environ.get("CUBICASA_RUNS", "0") == "1" else None


def calib_p(score, ab):
    a, b = ab
    s = min(max(score, 1e-4), 1 - 1e-4)
    z = a + b * math.log(s / (1 - s))
    return 1 / (1 + math.exp(-z))


def poisson_binomial(ps, kmax=KMAX):
    dist = [1.0] + [0.0] * kmax
    for p in ps:
        for k in range(kmax, 0, -1):
            dist[k] = dist[k] * (1 - p) + dist[k - 1] * p
        dist[0] *= 1 - p
    return dist


def add_poisson(dist, lam, kmax=KMAX):
    if lam <= 0:
        return dist
    pois = [math.exp(-lam) * lam ** k / math.factorial(k) for k in range(kmax + 1)]
    out = [0.0] * (kmax + 1)
    for i, a in enumerate(dist):
        if a == 0:
            continue
        for j in range(kmax + 1 - i):
            out[i + j] += a * pois[j]
    return out


def posterior(ps, lam, prior=None, w=0.0):
    d = add_poisson(poisson_binomial(ps), lam)
    if prior and w > 0:
        # prior: {count(str): prob}; unseen counts get a small floor
        floor = 1e-3
        d = [x * (prior.get(str(k), floor) ** w) for k, x in enumerate(d)]
    z = sum(d) or 1.0
    return [x / z for x in d]


# -- wall-aligned symbols: pick one consistent segmentation per wall run ---------------------------------
# A window run on a wall can be drawn as one long symbol or as several panes, and the detector proposes both
# (a long box and pane boxes underneath it). Plain NMS keeps whichever scores highest and suppresses the rest,
# so a run the annotators split into panes comes out as one window. Here the detector's NMS is loosened and,
# per wall run, we keep the set of non-overlapping boxes with the largest total (score - t).

def _axis(b):
    """(orientation, long-axis start, end, thin-axis centre, thickness) of a box."""
    w, h = b[2] - b[0], b[3] - b[1]
    if w >= h:
        return 0, b[0], b[2], (b[1] + b[3]) / 2, h
    return 1, b[1], b[3], (b[0] + b[2]) / 2, w


def select_runs(dets, t_min, t_w, ovl=0.25, align=0.5):
    """Subset of dets [(cls, score, box)] to count: per wall run (same orientation, aligned thin-axis centres,
    touching or overlapping along the wall), the maximum-weight set of boxes whose long-axis intervals overlap
    by at most ovl x the shorter one; weight = score - t_w, candidates score >= t_min."""
    ds = [(d, _axis(d[2])) for d in dets if d[1] >= t_min and d[1] > t_w]
    n = len(ds)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        oi, a0, a1, ci, ti = ds[i][1]
        for j in range(i + 1, n):
            oj, b0, b1, cj, tj = ds[j][1]
            if oi == oj and abs(ci - cj) <= align * max(ti, tj) and min(a1, b1) - max(a0, b0) > -0.25 * max(ti, tj):
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(ds[i])
    kept = []
    for g in groups.values():
        g.sort(key=lambda x: x[1][2])  # by end
        best = [(0.0, [])]  # best[k] = (value, chosen) over the first k boxes
        for k, (d, (_, a0, a1, _, _)) in enumerate(g):
            # latest earlier box (by end) compatible with this one
            p = k
            while p > 0:
                _, (_, b0, b1, _, _) = g[p - 1]
                if b1 - a0 <= ovl * min(a1 - a0, b1 - b0):
                    break
                p -= 1
            take = best[p][0] + d[1] - t_w
            best.append((take, best[p][1] + [d]) if take > best[k][0] else best[k])
        kept += best[-1][1]
    return kept
