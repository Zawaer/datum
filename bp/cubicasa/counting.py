"""From detector scores to a count distribution.

Each detection i of a counted class is real with probability p_i = sigmoid(a_c + b_c * logit(score))
(per-class calibration fitted on dev validation drawings). The number of objects the detector missed
entirely is Poisson(lambda_c). So the count is Poisson-binomial(p) + Poisson(sum lambda). Optionally
multiplied by the template's dev answer distribution raised to a power w (w = 0: detector only).
Answer = posterior mode, confidence = its probability.
"""
import math

KMAX = 60


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
