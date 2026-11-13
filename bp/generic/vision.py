"""Grounded counting and reading on a page image with a VLM that outputs boxes.

count(): the VLM is asked to box every instance of a target on each tile of the page; boxes from
overlapping tiles are kept only when their centre lies in the tile's core (each point of the page
belongs to exactly one core), then near-duplicates are merged. count = number of boxes and every
box is one evidence item.

Backends: "qwen" (local Qwen3-VL, boxes in 0..1000 per image) and any Claude alias (haiku, sonnet;
boxes asked in pixel coords of the supplied image).
"""
from __future__ import annotations

import json
import re

from bp.generic import llm

GROUND_QWEN = ('Locate every {target} in the image. Output a JSON list, one entry per instance: '
               '[{{"bbox_2d": [x1, y1, x2, y2], "label": "{label}"}}]. Output [] if there is none.')

GROUND_CLAUDE = ("The image is {w}x{h} pixels. Find every {target} in it. Reply with JSON only: "
                 '{{"boxes": [[x0, y0, x1, y1], ...]}} in pixel coordinates of this image, one box per '
                 "instance, tight around it. Empty list if none.")

READ_QWEN = ("This is a construction / architectural drawing. Question: {question}\n"
             "Answer from what is visible. Reply with JSON only: "
             '{{"answer": <short answer{unit}>, "evidence": [{{"bbox_2d": [x1, y1, x2, y2], "label": "<what is there>"}}]}} '
             "where the boxes mark the parts of the image the answer was read from. "
             'If the drawing does not show it, answer null.')

READ_CLAUDE = ("This is a construction / architectural drawing, {w}x{h} pixels. Question: {question}\n"
               "Reply with JSON only: "
               '{{"answer": <short answer{unit}>, "evidence": [{{"bbox": [x0, y0, x1, y1], "label": "<what is there>"}}], '
               '"confidence": "high|medium|low"}} with boxes in pixel coordinates of this image marking where '
               "the answer was read from. If the drawing does not show it, answer null.")


# -------------------------------------------------------------------------------------- geometry
def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0, 0.0
    aa = (a[2] - a[0]) * (a[3] - a[1])
    ab = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (aa + ab - inter), inter / max(min(aa, ab), 1e-12)


def dedupe(boxes, thr_iou=0.45, thr_cover=0.8):
    """Greedy merge of near-identical boxes (bigger first). boxes: list of [x0,y0,x1,y1] normalised."""
    kept = []
    for b in sorted(boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1])):
        if not any((lambda u: u[0] > thr_iou or u[1] > thr_cover)(iou(b, k)) for k in kept):
            kept.append(b)
    return sorted(kept, key=lambda b: (round(b[1], 2), b[0]))


def match_f1(a, b, thr=0.3):
    """Agreement between two box sets: greedy IoU matching F1 (1.0 when both empty)."""
    if not a and not b:
        return 1.0
    used, m = set(), 0
    for x in a:
        best, bj = 0.0, None
        for j, y in enumerate(b):
            if j in used:
                continue
            u = max(iou(x, y)[0], 0.5 * iou(x, y)[1])
            if u > best:
                best, bj = u, j
        if bj is not None and best >= thr:
            used.add(bj)
            m += 1
    return 2 * m / (len(a) + len(b))


def tiles(w, h, tile=1280, overlap=0.15):
    """Tile rects (pixel x0,y0,x1,y1) and their cores, covering the image."""
    def axis(n):
        if n <= tile * 1.15:
            return [(0, n, 0, n)]
        k = max(2, round((n - tile * overlap) / (tile * (1 - overlap)) + 0.49))
        step = (n - tile) / (k - 1)
        out = []
        for i in range(k):
            a = round(i * step)
            b = a + tile
            ca = 0 if i == 0 else round(a + (tile - step) / 2)
            cb = n if i == k - 1 else round(a + step + (tile - step) / 2)
            out.append((a, b, ca, cb))
        return out
    return [((x0, y0, x1, y1), (cx0, cy0, cx1, cy1)) for (y0, y1, cy0, cy1) in axis(h) for (x0, x1, cx0, cx1) in axis(w)]


# ------------------------------------------------------------------------------------- parsing
def _boxes_qwen(text, w, h):
    """Qwen3-VL boxes are 0..1000 relative to the image it was given; return pixel boxes."""
    out = []
    data = llm.parse_json(text)
    if isinstance(data, dict):
        data = data.get("boxes") or data.get("objects") or [data]
    if isinstance(data, list):
        for d in data:
            b = d.get("bbox_2d") or d.get("bbox") if isinstance(d, dict) else d
            if isinstance(b, list) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b):
                out.append(b)
    if not out:  # truncated JSON: salvage every complete box
        out = [list(map(float, m)) for m in re.findall(r"\[\s*(\d+\.?\d*)\s*,\s*(\d+\.?\d*)\s*,\s*(\d+\.?\d*)\s*,\s*(\d+\.?\d*)\s*\]", text)]
    res = []
    for b in out:
        x0, y0, x1, y1 = (float(v) for v in b)
        if x1 <= x0 or y1 <= y0:
            continue
        res.append([x0 / 1000 * w, y0 / 1000 * h, x1 / 1000 * w, y1 / 1000 * h])
    return res


def _boxes_claude(text, w, h):
    data = llm.parse_json(text)
    raw = data.get("boxes", []) if isinstance(data, dict) else (data or [])
    res = []
    for b in raw:
        if isinstance(b, dict):
            b = b.get("bbox") or b.get("box")
        if isinstance(b, list) and len(b) == 4:
            try:
                x0, y0, x1, y1 = (float(v) for v in b)
            except (TypeError, ValueError):
                continue
            if x1 > x0 and y1 > y0:
                res.append([max(0, x0), max(0, y0), min(w, x1), min(h, y1)])
    return res


# ------------------------------------------------------------------------------------------ API
def ground(img, target, backend="qwen", label=None):
    """Boxes (pixel coords of img) of every `target` in one image. Returns (boxes, cost_usd, gpu_s, raw)."""
    w, h = img.size
    if backend == "qwen":
        from bp.generic import qwen

        prompt = GROUND_QWEN.format(target=target, label=label or target.split("(")[0].strip())
        text, gs = qwen.generate(prompt, [img], max_new_tokens=1600, max_pixels=w * h + 1)
        return _boxes_qwen(text, w, h), 0.0, gs, text
    r = llm.ask(GROUND_CLAUDE.format(w=w, h=h, target=target), [img], model=backend, tag="ground")
    return _boxes_claude(r["text"], w, h), r["cost_usd"], 0.0, r["text"]


def count(img, target, backend="qwen", tile=1280, min_side=896, label=None, region=None, max_area=0.5):
    """Tiled grounded count over a page image (or a normalised sub-region of it).
    Returns dict with boxes normalised to the full page, and stats."""
    from PIL import Image

    if region is not None:
        PW, PH = img.size
        rx0, ry0, rx1, ry1 = region
        img = img.crop((round(rx0 * PW), round(ry0 * PH), round(rx1 * PW), round(ry1 * PH)))
    W, H = img.size
    scale = 1.0
    if max(W, H) < min_side:  # small rasters: upscale so thin symbols get enough patches
        scale = min_side / max(W, H)
        img = img.resize((round(W * scale), round(H * scale)), Image.LANCZOS)
        W, H = img.size
    boxes, cost, gpu, raws, per_tile = [], 0.0, 0.0, [], []
    for (x0, y0, x1, y1), (cx0, cy0, cx1, cy1) in tiles(W, H, tile):
        crop = img.crop((x0, y0, x1, y1))
        bs, c, g, raw = ground(crop, target, backend, label)
        cost += c
        gpu += g
        raws.append(raw[:400])
        n = 0
        for b in bs:
            gb = [b[0] + x0, b[1] + y0, b[2] + x0, b[3] + y0]
            cx, cy = (gb[0] + gb[2]) / 2, (gb[1] + gb[3]) / 2
            if cx0 <= cx < cx1 and cy0 <= cy < cy1:
                boxes.append([gb[0] / W, gb[1] / H, gb[2] / W, gb[3] / H])
                n += 1
        per_tile.append(n)
    # drop page-sized boxes (the model boxing the whole drawing instead of an instance)
    boxes = [b for b in boxes if (b[2] - b[0]) * (b[3] - b[1]) < max_area]
    boxes = dedupe(boxes)
    if region is not None:
        rw, rh = region[2] - region[0], region[3] - region[1]
        boxes = [[region[0] + b[0] * rw, region[1] + b[1] * rh, region[0] + b[2] * rw, region[1] + b[3] * rh]
                 for b in boxes]
    return {"boxes": [[round(v, 5) for v in b] for b in boxes], "cost_usd": cost, "gpu_s": gpu,
            "per_tile": per_tile, "raw": raws}


def read(img, question, backend="qwen", unit=None):
    """Free-form grounded answer on one image: (answer, [normalised boxes with labels], conf, cost, gpu_s, raw)."""
    w, h = img.size
    u = f", in {unit}" if unit and unit not in ("count", "None") else ""
    if backend == "qwen":
        from bp.generic import qwen

        text, gs = qwen.generate(READ_QWEN.format(question=question, unit=u), [img], max_new_tokens=512,
                                 max_pixels=min(w * h + 1, 1800 * 1800))
        data = llm.parse_json(text) or {}
        ev = []
        for e in (data.get("evidence") or []) if isinstance(data, dict) else []:
            b = e.get("bbox_2d") if isinstance(e, dict) else None
            if isinstance(b, list) and len(b) == 4:
                ev.append(([v / 1000 for v in b], str(e.get("label", ""))[:80]))
        ans = data.get("answer") if isinstance(data, dict) else None
        return ans, ev, None, 0.0, gs, text
    r = llm.ask(READ_CLAUDE.format(w=w, h=h, question=question, unit=u), [img], model=backend, tag="read")
    data = llm.parse_json(r["text"]) or {}
    ev = []
    for e in (data.get("evidence") or []) if isinstance(data, dict) else []:
        b = e.get("bbox") if isinstance(e, dict) else None
        if isinstance(b, list) and len(b) == 4:
            try:
                ev.append(([b[0] / w, b[1] / h, b[2] / w, b[3] / h], str(e.get("label", ""))[:80]))
            except TypeError:
                pass
    conf = {"high": 0.8, "medium": 0.55, "low": 0.3}.get(str(data.get("confidence", "")).lower()) if isinstance(data, dict) else None
    return (data.get("answer") if isinstance(data, dict) else None), ev, conf, r["cost_usd"], 0.0, r["text"]


def dump(x) -> str:
    return json.dumps(x, ensure_ascii=False)
