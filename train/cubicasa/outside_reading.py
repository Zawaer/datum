"""One outside vision reading per CubiCasa drawing: a single Claude call returning counts for every question
template, cached to cache/cubicasa/outside_reading/<model>.jsonl (one row per drawing).

    .venv/bin/python train/cubicasa/outside_reading.py --split dev [--limit 20] [--model claude-sonnet-5-5]

Key: ANTHROPIC_API_KEY from the environment or data/secrets/anthropic.env (never printed). Stops when the logged
spend passes --budget dollars.
"""
import argparse
import base64
import io
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

PRICE = {"claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50), "claude-opus-5-5": (4.0, 20.0)}
FIELDS = {
    "door": "doors: doorways fitted with a door leaf (open doorways without a door leaf do not count)",
    "window": "windows",
    "bedroom": "bedrooms (makuuhuone, usually marked MH)",
    "kitchen": "kitchens (including kitchenettes, open kitchens and utility kitchens; K, KK, KEITTIÖ, TK)",
    "bathroom": "bathrooms or washrooms (KH, KPH, PH, PESUH, SH), not counting separate WC rooms",
    "wc_room": "separate WC rooms (toilet rooms marked WC)",
    "sauna": "saunas (S, SAUNA)",
    "balcony": "balconies (parveke, PARV, including glazed balconies, LASITETTU PARVEKE)",
    "toilet": "toilet bowls (WC seats) drawn as symbols",
    "sink": "sinks and wash basins drawn as symbols (kitchen and bathroom combined; a double-bowl sink counts as one)",
    "shower_bath": "showers and bathtubs drawn as symbols, in total",
    "floor": "floors (storeys) the plan shows",
}
PROMPT = ("This is a Finnish real-estate floor plan from the CubiCasa5k dataset. Count carefully, room by room, "
          "and report an integer for each of:\n" + "\n".join(f"- {k}: {v}" for k, v in FIELDS.items()) +
          "\nCount only what is drawn on this plan.")
SCHEMA = {"type": "object", "additionalProperties": False, "required": list(FIELDS),
          "properties": {k: {"type": "integer"} for k in FIELDS}}


def api_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    for line in Path("data/secrets/anthropic.env").read_text().splitlines():
        if line.strip().startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no ANTHROPIC_API_KEY")


def image_b64(path, max_side=1568):
    from PIL import Image

    from bp.data import data_root
    p = Path(path) if Path(path).is_absolute() else data_root() / path
    im = Image.open(p).convert("RGB")
    s = max(im.size)
    if s > max_side:
        im = im.resize((round(im.size[0] * max_side / s), round(im.size[1] * max_side / s)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode()


def read(client, model, path, effort="low"):
    """Counts dict for one drawing (keys = FIELDS), plus usage and cost."""
    r = client.messages.create(
        model=model, max_tokens=4000,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64(path)}},
            {"type": "text", "text": PROMPT}]}])
    txt = next(b.text for b in r.content if b.type == "text")
    pin, pout = PRICE.get(model, (2.0, 10.0))
    u = r.usage
    cost = (u.input_tokens * pin + u.output_tokens * pout) / 1e6
    return {k: int(v) for k, v in json.loads(txt).items() if k in FIELDS}, u.input_tokens, u.output_tokens, cost


def drawings(split):
    if split == "dev":
        return sorted({json.loads(line)["path"] for line in open("cache/vlm_dev/devval_cc.jsonl")})
    from bp.data import data_root, split_of
    ps = set()
    for line in open(data_root() / "questions.jsonl"):
        q = json.loads(line)
        p = q.get("path") or q.get("file")
        if p and "cubicasa5k" in p and split_of(p) == "test":
            ps.add(p)
    return sorted(ps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], required=True)
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--budget", type=float, default=60.0)
    ap.add_argument("--tag", default="", help="cache file suffix, e.g. _high")
    a = ap.parse_args()
    import anthropic
    client = anthropic.Anthropic(api_key=api_key(), max_retries=6, timeout=180)
    out = Path(f"cache/cubicasa/outside_reading/{a.model}{a.tag}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    done, spent = set(), 0.0
    if out.exists():
        for line in open(out):
            r = json.loads(line)
            done.add(r["path"])
            spent += r.get("cost_usd", 0.0)
    todo = [p for p in drawings(a.split) if p not in done][: a.limit]
    print(f"{len(todo)} drawings to read, {len(done)} cached, spent so far ${spent:.3f}", flush=True)
    lock = threading.Lock()
    state = {"spent": spent, "n": 0, "fail": 0}

    def one(p):
        if state["spent"] > a.budget:
            return
        t0 = time.time()
        for attempt in range(3):
            try:
                counts, ti, to, cost = read(client, a.model, p, a.effort)
                break
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {str(e)[:200]}"
                time.sleep(2 + 4 * attempt)
        else:
            with lock:
                state["fail"] += 1
                print("FAIL", p, err, flush=True)
            return
        row = {"path": p, "model": a.model, "counts": counts, "in_tok": ti, "out_tok": to,
               "cost_usd": round(cost, 6), "latency_s": round(time.time() - t0, 2)}
        with lock:
            state["spent"] += cost
            state["n"] += 1
            with open(out, "a") as f:
                f.write(json.dumps(row) + "\n")
            if state["n"] % 25 == 0:
                print(f"{state['n']}/{len(todo)} spent ${state['spent']:.3f}", flush=True)

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, todo))
    print(f"done {state['n']} fail {state['fail']} total spend ${state['spent']:.3f}", flush=True)


if __name__ == "__main__":
    main()
