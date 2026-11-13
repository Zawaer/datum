"""Smoke-test a deployed demo: secrecy (404s, robots, headers), tour, scoreboard, asks per source, latency.

    .venv/bin/python deploy/verify.py https://<host>/<SECRET_PREFIX> [--out /tmp/bp-verify]

Screenshots go to --out (keep them out of the repo: the address bar is not in them, but stay careful).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit

from playwright.async_api import async_playwright

ARGS = ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"]


def get(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def check_http(base: str):
    u = urlsplit(base)
    origin = f"{u.scheme}://{u.netloc}"
    ok = True
    for path, want in [("/", 404), ("/robots.txt", 200), ("/api/drawings", 404), ("/results", 404),
                       ("/static/app.js", 404), (u.path + "x/", 404), (u.path[:-3] + "/", 404),
                       (u.path + "/", 200), (u.path + "/results", 200)]:
        st, h, body = get(origin + path)
        hl = {k.lower(): v for k, v in h.items()}
        flags = []
        if st != want:
            flags.append(f"WANT {want}")
        if "server" in hl:
            flags.append(f"server header {hl['server']}")
        if "noindex" not in hl.get("x-robots-tag", ""):
            flags.append("no X-Robots-Tag")
        if "access-control-allow-origin" in hl:
            flags.append("CORS header")
        if want == 404 and body.strip():
            flags.append(f"404 body {body[:40]!r}")
        if path == "/robots.txt" and b"Disallow: /" not in body:
            flags.append("robots does not disallow")
        ok &= not flags
        shown = path.replace(u.path, "/<prefix>") if u.path and u.path != "/" else path
        print(f"  {st} {shown:28s} {'OK' if not flags else ' '.join(flags)}")
    return ok


def pick_questions(base: str):
    """One question per source (first drawing of each tab), plus a 3D-capable IFC one."""
    st, _, body = get(base + "/api/drawings?limit=0")
    counts = json.loads(body)["counts"]
    out = []
    for src in counts:
        st, _, body = get(base + f"/api/drawings?source={src}&limit=3")
        for d in json.loads(body)["items"][:1]:
            st, _, qb = get(base + "/api/questions?path=" + quote(d["path"]))
            info = json.loads(qb)
            qs = [q for q in info["questions"] if q["type"] == "count"] or info["questions"]
            out.append((src, d["path"], qs[0]["question"], info.get("has3d")))
    return out


async def run(base: str, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=ARGS)
        pg = await b.new_page(viewport={"width": 1600, "height": 950})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("response", lambda r: errors.append(f"{r.status} {r.url.split('?')[0][-60:]}") if r.status >= 400 else None)
        t0 = time.time()
        await pg.goto(base + "/")
        await pg.wait_for_load_state("networkidle")
        print(f"  page load {time.time() - t0:.1f}s")
        await pg.screenshot(path=str(out / "home.png"))

        # tour
        await pg.evaluate("window.bpTour.start(true)")
        n = await pg.evaluate("window.bpTour.steps.length")
        for i in range(n):
            t0 = time.time()
            while time.time() - t0 < 240 and await pg.evaluate("window.__tourStepDone") != i:
                await pg.wait_for_timeout(250)
            print(f"  tour step {i + 1}/{n}: {time.time() - t0:.1f}s")
            await pg.wait_for_timeout(800)
            await pg.screenshot(path=str(out / f"tour-{i + 1}.png"))
            if i < n - 1:
                await pg.evaluate("window.bpTour.next()")
        await pg.evaluate("document.querySelector('#texit').click()")

        await pg.goto(base + "/results")
        await pg.wait_for_timeout(2500)
        await pg.screenshot(path=str(out / "results.png"), full_page=True)

        for src, path, q, has3d in pick_questions(base):
            await pg.goto(f"{base}/?tab={src}&path={quote(path)}&q={quote(q)}", wait_until="domcontentloaded", timeout=90000)
            t0 = time.time()
            await pg.wait_for_selector("#answer:not([hidden])", timeout=60000)
            await pg.wait_for_function("!document.querySelector('#answer .thinking')", timeout=300000)
            dt = time.time() - t0
            ans = (await pg.inner_text("#answer"))[:160].replace("\n", " | ")
            print(f"  ask {src:16s} {dt:5.1f}s  {ans}")
            await pg.wait_for_timeout(1000)
            await pg.screenshot(path=str(out / f"ask-{src}.png"))
            if has3d:
                try:
                    await pg.click("#m3d", timeout=15000)
                except Exception:  # noqa: BLE001
                    print(f"  ask {src:16s} 3D button not shown")
                    continue
                await pg.wait_for_timeout(9000)
                await pg.screenshot(path=str(out / f"ask-{src}-3d.png"))
        await b.close()
        bad = [e for e in errors if "favicon" not in e]
        print(f"  browser errors: {bad[:10] if bad else 'none'}")


def latency(base: str, n: int = 3):
    for src, path, q, _ in pick_questions(base):
        ts = []
        for _ in range(n):
            t0 = time.time()
            st, _, body = get(base + "/api/ask", json.dumps({"path": path, "question": q}).encode())
            ts.append(time.time() - t0)
        r = json.loads(body) if st == 200 else {}
        print(f"  {src:16s} HTTP {st} median {sorted(ts)[n // 2]:.2f}s answer={r.get('answer')!s:.30} "
              f"route={r.get('route')} cost=${r.get('cost_usd', 0):.4f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--out", default="/tmp/bp-verify")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    print("http checks:")
    print("  all OK" if check_http(base) else "  SOME CHECKS FAILED")
    print("latency (API, warm):")
    latency(base)
    if not a.no_browser:
        print("browser:")
        asyncio.run(run(base, Path(a.out)))
