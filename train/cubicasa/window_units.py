"""How many annotated windows does one detected window box hold? A tiny CNN on the box crop.

CubiCasa annotators split a run of window units on a wall into separate windows wherever two sash frames
meet (a double mullion), but the detector often proposes one box over the whole run, so plans with long
window bands are under-counted. This model looks at the crop of a window box (rotated to horizontal) and
predicts 1, 2 or 3 units.

Training data come from the annotations of the TRAINING drawings only (cache/yolo_cc/labels/train): every
annotated window is a 1-unit sample, the union box of 2 or 3 adjacent collinear annotated windows on one wall
is a 2- or 3-unit sample, with box jitter. The detector is not involved, so the model works with any weights.
The decision threshold is chosen on the dev-val drawings (train/cubicasa/units_dev.py).

RESULT (negative, so the solver does not use it): the model separates the two cases as well as the pixels
allow, but the annotation is not consistent across drawings. On dev-val, of detected window boxes that show a
double mullion (P(>=2 units) > 0.5), 93 were annotated as two windows and 169 as one, and the convention is
per drawing (66 of 68 drawings with 2+ such boxes are all-split or all-merged). Nothing visible in the PNG
predicts which convention a drawing used, so splitting gains about as many drawings as it loses (+0-1 pt).

    .venv/bin/python train/cubicasa/window_units.py build   # crops -> cache/cubicasa/window_units/data.npz
    .venv/bin/python train/cubicasa/window_units.py train   # -> cache/cubicasa/window_units/model.pt
"""
import random
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from PIL import Image

CH, CW = 24, 128


def crop(im, b, rng=None):
    """(grey crop CH x CW uint8 of pixel box b on grey image im with the long axis horizontal, log aspect of the box),
    or None; rng = random box jitter (training)."""
    H, W = im.shape
    x0, y0, x1, y1 = b
    vert = (y1 - y0) > (x1 - x0)
    if vert:  # work in (long, thin) coordinates
        a0, a1, t0, t1 = y0, y1, x0, x1
    else:
        a0, a1, t0, t1 = x0, x1, y0, y1
    L, T = a1 - a0, t1 - t0
    if L < 4 or T < 1:
        return None
    if rng is not None:
        a0 += rng.uniform(-0.04, 0.04) * L
        a1 += rng.uniform(-0.04, 0.04) * L
        tc = (t0 + t1) / 2 + rng.uniform(-0.1, 0.1) * T
        T *= rng.uniform(0.85, 1.2)
        t0, t1 = tc - T / 2, tc + T / 2
        L = a1 - a0
    a0, a1 = a0 - 0.06 * L, a1 + 0.06 * L
    tc, T = (t0 + t1) / 2, max(T * 1.6, 3)
    t0, t1 = tc - T / 2, tc + T / 2
    if vert:
        ys, xs = (int(max(0, a0)), int(min(H, a1 + 1))), (int(max(0, t0)), int(min(W, t1 + 1)))
    else:
        ys, xs = (int(max(0, t0)), int(min(H, t1 + 1))), (int(max(0, a0)), int(min(W, a1 + 1)))
    sub = im[ys[0]:ys[1], xs[0]:xs[1]]
    if sub.size == 0 or min(sub.shape) < 1:
        return None
    if vert:
        sub = sub.T
    asp = float(np.log(max(L, 1) / max(T / 1.6, 1)))
    return np.asarray(Image.fromarray(np.ascontiguousarray(sub)).resize((CW, CH), Image.BILINEAR), dtype=np.uint8), asp


def _axis(b):
    w, h = b[2] - b[0], b[3] - b[1]
    return (0, b[0], b[2], (b[1] + b[3]) / 2, h) if w >= h else (1, b[1], b[3], (b[0] + b[2]) / 2, w)


def runs_of(bs, align=0.5, gap=1.0):
    """Index lists of collinear boxes that touch end to end along one wall, each sorted along the wall."""
    ax = [_axis(b) for b in bs]
    parent = list(range(len(bs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, (oi, a0, a1, ci, ti) in enumerate(ax):
        for j in range(i + 1, len(bs)):
            oj, b0, b1, cj, tj = ax[j]
            t = max(ti, tj)
            if oi == oj and abs(ci - cj) <= align * t and -0.5 * t <= max(a0, b0) - min(a1, b1) <= gap * t:
                parent[find(i)] = find(j)
    runs = {}
    for i in range(len(bs)):
        runs.setdefault(find(i), []).append(i)
    return [sorted(r, key=lambda i: ax[i][1]) for r in runs.values()]


def Net():
    import torch
    import torch.nn as nn

    def blk(i, o):
        return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(), nn.MaxPool2d(2))

    class _Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.f = nn.Sequential(blk(1, 16), blk(16, 32), blk(32, 64), nn.Conv2d(64, 64, 3, padding=1), nn.ReLU(),
                                   nn.AdaptiveAvgPool2d((1, 16)), nn.Flatten())
            self.h = nn.Sequential(nn.Linear(64 * 16 + 1, 64), nn.ReLU(), nn.Dropout(0.2), nn.Linear(64, 3))

        def forward(self, x, a):  # a = log aspect, shape (n,)
            return self.h(torch.cat([self.f(x), a.view(-1, 1)], 1))

    return _Net()


_NET = {}


def unit_probs(img_path, boxes, model_path):
    """[[p1, p2, p3]] per normalised box: probability the box holds 1, 2 or 3 annotated windows."""
    import torch

    if not boxes:
        return []
    if model_path not in _NET:
        net = Net()
        net.load_state_dict(torch.load(model_path, map_location="cpu"))
        _NET[model_path] = net.eval()
    Image.MAX_IMAGE_PIXELS = None
    im = np.asarray(Image.open(img_path).convert("L"))
    H, W = im.shape
    xs, asp, ok = [], [], []
    for b in boxes:
        c = crop(im, [b[0] * W, b[1] * H, b[2] * W, b[3] * H])
        ok.append(c is not None)
        xs.append(c[0] if c is not None else np.zeros((CH, CW), np.uint8))
        asp.append(c[1] if c is not None else 0.0)
    x = torch.tensor(np.stack(xs)).float().div(255).unsqueeze(1)
    a = torch.tensor(asp, dtype=torch.float32)
    net = _NET[model_path]
    with torch.no_grad():
        p = (torch.softmax(net(x, a), 1) + torch.softmax(net(x.flip(3), a), 1)) / 2
    return [pp if k else [1.0, 0.0, 0.0] for pp, k in zip(p.tolist(), ok)]


OUT = Path("cache/cubicasa/window_units")
DATA = Path("cache/yolo_cc")


def boxes(stem, split="train"):
    out = []
    for ln in (DATA / "labels" / split / f"{stem}.txt").read_text().split("\n"):
        if ln.startswith("0 "):
            x, y, w, h = map(float, ln.split()[1:5])
            out.append([x - w / 2, y - h / 2, x + w / 2, y + h / 2])
    return out


def samples_for(stem, split="train", jit=3, seed=0):
    Image.MAX_IMAGE_PIXELS = None
    bs = boxes(stem, split)
    if not bs:
        return []
    im = np.asarray(Image.open(DATA / "images" / split / f"{stem}.png").convert("L"))
    H, W = im.shape
    px = [[b[0] * W, b[1] * H, b[2] * W, b[3] * H] for b in bs]
    rng = random.Random(f"{stem}{seed}")
    out = []
    for run in runs_of(px):  # run = indices of collinear touching windows, in order along the wall
        for k in (1, 2, 3):
            for i in range(len(run) - k + 1):
                grp = [px[j] for j in run[i:i + k]]
                u = [min(g[0] for g in grp), min(g[1] for g in grp), max(g[2] for g in grp), max(g[3] for g in grp)]
                for _ in range(jit if k == 1 else jit * 2):
                    c = crop(im, u, rng)
                    if c is not None:
                        out.append((c[0], c[1], k))
    return out


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    stems = sorted(p.stem for p in (DATA / "images" / "train").glob("*.png"))
    with Pool(12) as pool:
        res = pool.map(samples_for, stems, chunksize=8)
    X = np.stack([c for r in res for c, _, _ in r])
    A = np.array([a for r in res for _, a, _ in r], np.float32)
    y = np.array([k for r in res for _, _, k in r])
    g = np.array([i for i, r in enumerate(res) for _ in r])  # drawing id, for a held-out split
    np.savez_compressed(OUT / "data.npz", X=X, A=A, y=y, g=g)
    print(X.shape, np.bincount(y))


def train(epochs=12):
    import torch

    torch.manual_seed(0)
    d = np.load(OUT / "data.npz")
    X, A, y, g = d["X"], d["A"], d["y"] - 1, d["g"]
    ho = g % 10 == 0  # 10 % of training drawings held out for early stopping
    Xt, At, yt = torch.tensor(X[~ho]).float().div(255).unsqueeze(1), torch.tensor(A[~ho]), torch.tensor(y[~ho])
    Xh, Ah, yh = torch.tensor(X[ho]).float().div(255).unsqueeze(1), torch.tensor(A[ho]), torch.tensor(y[ho])
    net = Net()
    opt = torch.optim.AdamW(net.parameters(), 2e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    best = (1e9, None)
    for ep in range(epochs):
        net.train()
        perm = torch.randperm(len(Xt))
        for i in range(0, len(perm), 256):
            idx = perm[i:i + 256]
            xb = Xt[idx]
            if random.random() < 0.5:
                xb = xb.flip(3)
            loss = torch.nn.functional.cross_entropy(net(xb, At[idx]), yt[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        net.eval()
        with torch.no_grad():
            lo = torch.cat([net(Xh[i:i + 1024], Ah[i:i + 1024]) for i in range(0, len(Xh), 1024)])
        hl = torch.nn.functional.cross_entropy(lo, yh).item()
        acc = (lo.argmax(1) == yh).float().mean().item()
        cm = np.zeros((3, 3), int)
        for a, b in zip(yh.tolist(), lo.argmax(1).tolist()):
            cm[a, b] += 1
        print(f"epoch {ep} held-out loss {hl:.4f} acc {acc:.3f} confusion {cm.tolist()}", flush=True)
        if hl < best[0]:
            best = (hl, {k: v.clone() for k, v in net.state_dict().items()})
    torch.save(best[1], OUT / "model.pt")
    print("saved", OUT / "model.pt", "held-out loss", round(best[0], 4))


if __name__ == "__main__":
    {"build": build, "train": train}[sys.argv[1]]()
