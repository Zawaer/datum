"""Phone photo of a printed plan -> flat, top-down, evenly lit image.

1. find the sheet: the largest 4-corner contour of the bright paper against the background (Otsu threshold on
   a blurred grey image, then edges as a fallback), covering 20-97 % of the photo;
2. only when it is really a perspective view (corners off an axis-aligned rectangle): warp it to a rectangle
   whose sides are the mean lengths of the opposite edges;
3. flatten the lighting: divide by a heavy blur of the image (removes the shadow of the phone / hand and the
   vignette), then stretch the contrast.
Screenshots, scans and born-digital images have no such quadrilateral (or an axis-aligned one) and are left alone.
"""
from __future__ import annotations

import numpy as np


def _order(pts):
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def _paper(gray, quad) -> bool:
    """Paper is brighter than what surrounds it, and the photo shows a real margin of background."""
    import cv2

    m = np.zeros(gray.shape, np.uint8)
    cv2.fillConvexPoly(m, quad.reshape(4, 2).astype(np.int32), 255)
    inside, outside = gray[m > 0], gray[m == 0]
    if outside.size < 0.03 * gray.size:
        return False
    return float(np.median(inside)) > float(np.median(outside)) + 30 and float(np.std(outside)) < 45


def find_sheet(gray):
    """4 corners (tl, tr, br, bl) of the paper sheet in a grey image, or None."""
    import cv2

    H, W = gray.shape
    area = H * W
    blur = cv2.GaussianBlur(gray, (0, 0), max(2.0, max(H, W) / 600))
    cands = []
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    cands.append(th)
    ed = cv2.Canny(blur, 30, 90)
    cands.append(cv2.dilate(ed, np.ones((5, 5), np.uint8)))
    best = None
    for mask in cands:  # every plausible sheet from both masks; the biggest wins (shadows shrink the Otsu one)
        cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cs, key=cv2.contourArea, reverse=True)[:3]:
            a = cv2.contourArea(c)
            if not 0.2 * area < a < 0.97 * area:
                continue
            hull = cv2.convexHull(c)
            if a < 0.9 * cv2.contourArea(hull):
                continue  # a building outline / furniture, not a sheet of paper
            peri = cv2.arcLength(hull, True)
            for eps in (0.01, 0.02, 0.03, 0.05):
                ap = cv2.approxPolyDP(hull, eps * peri, True)
                if len(ap) == 4 and _paper(gray, ap):
                    qa = cv2.contourArea(ap)
                    if best is None or qa > best[0]:
                        best = (qa, _order(ap))
                    break
    if best is not None:
        return best[1]
    return None


def is_perspective(q, W, H, tol=0.012):
    """True when the quad is not (close to) an axis-aligned rectangle."""
    tl, tr, br, bl = q
    dev = max(abs(tl[1] - tr[1]) / H, abs(bl[1] - br[1]) / H, abs(tl[0] - bl[0]) / W, abs(tr[0] - br[0]) / W)
    return dev > tol


def flatten_light(gray):
    import cv2

    bg = cv2.GaussianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), (0, 0), max(gray.shape) / 40)
    norm = cv2.divide(gray, np.maximum(bg, 1), scale=255)
    lo, hi = np.percentile(norm, (1, 99.5))
    return np.clip((norm.astype(np.float32) - lo) * 255.0 / max(hi - lo, 1), 0, 255).astype(np.uint8)


def rectify(img):
    """PIL image -> (rectified PIL image, info) or (None, info) when it is not a photo of a sheet."""
    import cv2
    from PIL import Image

    rgb = np.asarray(img.convert("RGB"))
    H, W = rgb.shape[:2]
    s = 1200 / max(H, W)
    small = cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), (round(W * s), round(H * s)), interpolation=cv2.INTER_AREA)
    q = find_sheet(small)
    if q is None:
        return None, {"why": "no sheet outline found"}
    if not is_perspective(q, small.shape[1], small.shape[0]):
        return None, {"why": "sheet is already flat (screenshot / scan)"}
    q = q / s
    tl, tr, br, bl = q
    w = int(round((np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2))
    h = int(round((np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2))
    if w < 300 or h < 300:
        return None, {"why": "sheet too small"}
    M = cv2.getPerspectiveTransform(q.astype(np.float32), np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]]))
    flat = cv2.warpPerspective(rgb, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    gray = flatten_light(cv2.cvtColor(flat, cv2.COLOR_RGB2GRAY))
    # keep colour where the plan has it (CubiCasa-style coloured walls): scale each channel by the same lighting gain
    g0 = cv2.cvtColor(flat, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gain = (gray.astype(np.float32) + 1) / (g0 + 1)
    out = np.clip(flat.astype(np.float32) * gain[..., None], 0, 255).astype(np.uint8)
    return Image.fromarray(out), {"corners": [[round(float(x)), round(float(y))] for x, y in q], "size": [w, h]}
