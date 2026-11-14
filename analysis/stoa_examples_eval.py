"""Stoa's four example sheets (final-judging style: unseen sheets uploaded through the demo) end to end.

Uploads each sheet through the real server API (POST /api/upload), asks the questions of
analysis/stoa_examples.jsonl (POST /api/ask), scores the answers against the hand-derived gold and draws the
evidence on the sheet (one PNG per question, like the viewer's overlay).

    .venv/bin/python analysis/stoa_examples_eval.py --server http://127.0.0.1:3160 --name after
    .venv/bin/python analysis/stoa_examples_eval.py --rescore runs/stoa_examples_after.jsonl   # re-score only

Gold: "conf" high = printed on the sheet (or a count we checked tile by tile); approx = our own measurement
(scored with the row's wider "tol"). Scoring: numbers within tol (relative; counts exact unless tol given),
text answers must contain every gold token (case / spacing / punctuation folded).
Outputs runs/stoa_examples_<name>.jsonl, .summary.md and runs/stoa_examples_<name>/<id>.png.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHEETS_DIR = Path("/data/attachments/s_YTlo5xSrle/stoa-examples")
QFILE = ROOT / "analysis/stoa_examples.jsonl"


def post(url, data, ctype, timeout=300):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def sheet_file(name: str, lowres: bool = False) -> Path:
    """The sheet as uploaded: the full-resolution original (<stem>_hires.png) when we have it."""
    hi = SHEETS_DIR / (Path(name).stem + "_hires.png")
    return hi if hi.exists() and not lowres else SHEETS_DIR / name


def upload(server, f: Path):
    return post(f"{server}/api/upload?name={urllib.parse.quote(f.name)}", f.read_bytes(), "application/octet-stream")


def ask(server, path, question):
    t0 = time.time()
    try:
        r = post(f"{server}/api/ask", json.dumps({"path": path, "question": question}).encode(), "application/json")
    except Exception as e:  # noqa: BLE001
        r = {"answer": None, "error": repr(e)[:300]}
    r["latency_s"] = round(time.time() - t0, 1)
    return r


def num(x):
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x)
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def fold(s):
    return re.sub(r"[^a-z0-9@.]+", " ", str(s).lower().replace("”", '"').replace("″", '"')).strip()


def score(row, ans):
    """1 / 0 (None answer = 0, reported as abstention)."""
    if ans is None:
        return 0
    g = row["gold"]
    if row.get("type") == "text":
        toks = [t for t in fold(g).split() if t]
        a = fold(ans)
        return int(all(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", a) for t in toks))
    a, gv = num(ans), num(g)
    if a is None or gv is None:
        return 0
    tol = row.get("tol", 0.0 if row.get("type") == "count" else 0.03)
    return int(abs(a - gv) <= tol * abs(gv) + 1e-9)


def overlay(sheet: Path, res: dict, out: Path, title: str):
    from PIL import Image, ImageDraw

    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(sheet).convert("RGB")
    im.thumbnail((2400, 2400))
    W, H = im.size
    d = ImageDraw.Draw(im, "RGBA")
    for e in res.get("evidence") or []:
        if e.get("page", 0) != 0:
            continue
        col = {"box": (230, 30, 30), "polygon": (20, 110, 230), "text": (0, 150, 60)}.get(e.get("kind"), (200, 0, 200))
        if e.get("points"):
            pts = [(x * W, y * H) for x, y in e["points"]]
            if len(pts) > 2:
                d.polygon(pts, outline=col + (255,), fill=col + (50,))
        elif e.get("bbox"):
            x0, y0, x1, y1 = e["bbox"]
            d.rectangle([x0 * W, y0 * H, x1 * W, y1 * H], outline=col + (255,), width=3)
    d.rectangle([0, 0, W, 64], fill=(255, 255, 255, 230))
    d.text((8, 4), title[:200], fill=(0, 0, 0), font_size=22)
    d.text((8, 34), f"answer: {res.get('answer')!s:.80}  conf {res.get('confidence')}  route {res.get('route')}  "
                    f"method {res.get('method')}", fill=(160, 0, 0), font_size=20)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)


def summary(rows, name):
    lines = [f"# Stoa example sheets: {name}", "",
             "| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |", "|---|---|---|---|---|---|---|---|---|---|"]
    by = {}
    for r in rows:
        res = r["res"]
        a = res.get("answer")
        shown = a if a is not None else f"(abstain; guess {res.get('tentative_answer')})" if res.get(
            "tentative_answer") is not None else "(abstain)"
        lines.append(f"| {r['id']} | {r['sheet'].split('_')[0]} | {r['question']} | {r['gold']}{' ~' if r.get('conf') == 'approx' else ''} "
                     f"| {str(shown)[:60]} | {res.get('confidence')} | {'Y' if r['ok'] else '-'} | "
                     f"{res.get('route')} / {res.get('method')} | {res.get('cost_usd', 0) or 0:.4f} | {res.get('latency_s')} |")
        b = by.setdefault(r["sheet"].split("_")[0], [0, 0])
        b[0] += r["ok"]
        b[1] += 1
    tot = sum(r["ok"] for r in rows)
    cost = sum(float(r["res"].get("cost_usd") or 0) for r in rows)
    lines += ["", f"**{tot}/{len(rows)} correct**; " + ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in by.items())
              + f"; API cost of the questions ${cost:.3f}"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:3160")
    ap.add_argument("--name", default="run")
    ap.add_argument("--only", default="", help="comma list of ids or sheet prefixes")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--rescore", default="")
    ap.add_argument("--no-png", action="store_true")
    ap.add_argument("--lowres", action="store_true", help="upload the ~2000 px screenshots, not the *_hires.png")
    a = ap.parse_args()
    qs = [json.loads(line) for line in QFILE.read_text().splitlines() if line.strip()]
    if a.rescore:
        old = {json.loads(x)["id"]: json.loads(x) for x in Path(a.rescore).read_text().splitlines() if x.strip()}
        rows = []
        for q in qs:
            if q["id"] in old:
                r = {**old[q["id"]], **q}
                r["ok"] = score(q, r["res"].get("answer"))
                rows.append(r)
        name = Path(a.rescore).stem.replace("stoa_examples_", "")
        Path(a.rescore).write_text("".join(json.dumps(r) + "\n" for r in rows))
        Path(a.rescore).with_suffix(".summary.md").write_text(summary(rows, name))
        print(summary(rows, name))
        return
    if a.only:
        keep = a.only.split(",")
        qs = [q for q in qs if q["id"] in keep or any(q["sheet"].startswith(k) for k in keep)]
    paths = {}
    for s in sorted({q["sheet"] for q in qs}):
        t0 = time.time()
        u = upload(a.server, sheet_file(s, a.lowres))
        paths[s] = u["path"]
        print(f"uploaded {s} -> {u['path']} ({time.time() - t0:.1f}s) notes={u.get('notes')}", file=sys.stderr)
    out = ROOT / f"runs/stoa_examples_{a.name}.jsonl"
    rows = []

    def one(q):
        res = ask(a.server, paths[q["sheet"]], q["question"])
        return {**q, "path": paths[q["sheet"]], "res": res, "ok": score(q, res.get("answer"))}

    with cf.ThreadPoolExecutor(a.jobs) as ex:
        for r in ex.map(one, qs):
            rows.append(r)
            res = r["res"]
            print(f"[{'OK' if r['ok'] else '--'}] {r['id']}: {r['question']} -> {res.get('answer')!s:.50} "
                  f"(gold {r['gold']}, conf {res.get('confidence')}, {res.get('route')}/{res.get('method')}, "
                  f"{res.get('latency_s')}s)", file=sys.stderr, flush=True)
            if not a.no_png:
                overlay(sheet_file(r["sheet"], a.lowres), res, ROOT / f"runs/stoa_examples_{a.name}/{r['id']}.png",
                        f"{r['id']}: {r['question']}  (gold {r['gold']})")
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out.with_suffix(".summary.md").write_text(summary(rows, a.name))
    print(summary(rows, a.name))


if __name__ == "__main__":
    main()
