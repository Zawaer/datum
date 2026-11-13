"""Visual track helpers for the demo video (1920x1080). Used by docs/deck/make_video.py.

    .venv/bin/python docs/deck/record_video.py [--url http://localhost:3123] [--steps 5]

Run on its own, it only records one take of the demo tour (app/tour.json, steps 1..N) into runs/video/work/,
logging when each step starts and finishes (marks.json). make_video.py then cuts that take to the voice-over.

- render_pages(): screenshots HTML pages (deck slides, video cards) to PNG
- record_take(): warms the server caches, then records tour steps 1..N in one take
- still_clip() / step_clip(): turn a PNG or one recorded step into a clip of exactly the given length
  (a recorded step that is too long is sped up, one that is too short plays up to 1.4x slower and then
  holds its last frame)
Needs the demo server, playwright + chromium in the venv, and ffmpeg on PATH.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from pathlib import Path

OUT = Path("runs/video")
WORK = OUT / "work"
ARGS = ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"]
HOLD_MS = 1800
FPS = 30


def ff(*a):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, a)], check=True)


def probe_dur(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


async def render_pages(pages: list[tuple[str, Path]]):
    """pages: (url, png path). Waits for fonts so text renders final."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(args=ARGS)
        pg = await b.new_page(viewport={"width": 1920, "height": 1080})
        for url, png in pages:
            await pg.goto(url)
            await pg.wait_for_load_state("networkidle")
            await pg.evaluate("document.fonts.ready")
            await pg.screenshot(path=str(png))
        await b.close()


async def wait_step(pg, i, timeout_s=300):
    for _ in range(timeout_s * 10):
        if await pg.evaluate("window.__tourStepDone") == i:
            return
        await pg.wait_for_timeout(100)
    print(f"step {i + 1}: timed out")


async def record_take(url: str, n_steps: int):
    from playwright.async_api import async_playwright
    WORK.mkdir(parents=True, exist_ok=True)
    for old in WORK.glob("*.webm"):
        old.unlink()
    async with async_playwright() as p:
        b = await p.chromium.launch(args=ARGS)
        # warm the server caches so the take has no cold starts
        warm = await b.new_page()
        await warm.goto(url + "/")
        steps = await warm.evaluate("fetch('/api/tour').then(r => r.json())")
        for s in steps[:n_steps]:
            await warm.evaluate("""s => Promise.all([
                fetch('/api/questions?path=' + encodeURIComponent(s.path)).then(r => r.json()).then(i =>
                  i.view ? fetch('/api/render?path=' + encodeURIComponent(i.view)) : null),
                fetch('/api/ask', {method: 'POST', headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({path: s.path, question: s.question})}),
                s.source && s.source.startsWith('ifc') ? fetch('/api/mesh?path=' + encodeURIComponent(s.path)) : null])""", s)
        await warm.close()
        ctx = await b.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=str(WORK),
                                  record_video_size={"width": 1920, "height": 1080})
        pg = await ctx.new_page()
        t0 = time.time()
        await pg.goto(url + "/")
        await pg.wait_for_timeout(2000)
        marks = []
        for i in range(n_steps):
            start = time.time() - t0
            await (pg.evaluate("window.bpTour.start(true)") if i == 0 else pg.evaluate("window.bpTour.next()"))
            await wait_step(pg, i)
            await pg.wait_for_timeout(HOLD_MS)
            marks.append((start, time.time() - t0))
            print(f"step {i + 1}: {marks[-1][0]:.1f}-{marks[-1][1]:.1f} s")
        raw = Path(await pg.video.path())
        await ctx.close()
        await b.close()
    (WORK / "marks.json").write_text(json.dumps({"raw": str(raw), "marks": marks}))
    return raw, marks


def last_take():
    m = json.loads((WORK / "marks.json").read_text())
    return Path(m["raw"]), m["marks"]


def still_clip(png: Path, dur: float, out: Path):
    ff("-loop", 1, "-t", f"{dur:.3f}", "-i", png, "-vf", f"fps={FPS},format=yuv420p",
       "-c:v", "libx264", "-preset", "medium", "-crf", 18, out)


def step_clip(raw: Path, mark, dur: float, out: Path):
    a, e = mark
    seg = out.with_suffix(".seg.mp4")
    ff("-ss", f"{a:.2f}", "-to", f"{e:.2f}", "-i", raw, "-an", "-vf", f"fps={FPS}", "-c:v", "libx264",
       "-preset", "medium", "-crf", 18, seg)
    have = probe_dur(seg)
    if have >= dur:
        vf = f"setpts={dur / have:.5f}*PTS,fps={FPS}"
    else:  # play up to 1.4x slower, then hold the finished frame
        slow = min(dur / have, 1.4)
        vf = f"setpts={slow:.4f}*PTS,tpad=stop_mode=clone:stop_duration={dur - have * slow + 0.5:.2f},fps={FPS}"
    ff("-i", seg, "-vf", vf + ",format=yuv420p", "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "medium",
       "-crf", 18, out)
    return have


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:3123")
    ap.add_argument("--steps", type=int, default=5)
    a = ap.parse_args()
    asyncio.run(record_take(a.url.rstrip("/"), a.steps))
