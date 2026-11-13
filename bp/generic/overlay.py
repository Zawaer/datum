"""Draw a solver result's evidence boxes over a render of the drawing (for inspection).

    python -m bp.generic.overlay <dataset-relative path> <result.json> out.png
"""
from __future__ import annotations

import json
import sys

from PIL import ImageDraw

from bp.data import data_root
from bp.generic import text as T


def draw(path: str, result: dict, max_side: int = 2000, page: int = 0):
    img = T.render(str(data_root() / path), page, max_side=max_side)
    d = ImageDraw.Draw(img)
    W, H = img.size
    for e in result.get("evidence", []):
        if e.get("page", 0) != page or "bbox" not in e:
            continue
        x0, y0, x1, y1 = e["bbox"]
        col = (220, 30, 30) if e["kind"] == "box" else (30, 90, 220)
        d.rectangle([x0 * W - 2, y0 * H - 2, x1 * W + 2, y1 * H + 2], outline=col, width=3)
        lab = str(e.get("label", ""))
        m = lab.split(":")[0].split()[-1] if lab else ""
        d.text((x0 * W, max(0, y0 * H - 12)), m[:12], fill=col)
    return img


if __name__ == "__main__":
    p, r, o = sys.argv[1:4]
    draw(p, json.load(open(r))).save(o)
