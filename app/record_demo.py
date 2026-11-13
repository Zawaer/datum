"""Record the demo tour as a 1920x1080 video, plus small screenshots for the docs.

    .venv/bin/python app/record_demo.py [--url http://localhost:3123] [--no-video] [--no-shots]

Video  -> runs/video/demo-tour-<time>.webm   (gitignored)
Shots  -> docs/img/tour-<n>.png, docs/img/scoreboard.png, docs/img/phone.png   (committed; licence credit visible)
Needs the server running and playwright + chromium in the venv. WebGL runs on swiftshader when headless.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import shutil
import time
from pathlib import Path

from playwright.async_api import async_playwright

ARGS = ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"]
IMG = Path("docs/img")
VID = Path("runs/video")


def save_small(png: bytes, out: Path, width: int = 1280):
    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im = im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    im.save(out, optimize=True)
    print(f"  {out} ({out.stat().st_size // 1024} KB)")


async def wait_step(pg, i: int, timeout_s: float = 240):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if await pg.evaluate("window.__tourStepDone") == i:
            return
        await pg.wait_for_timeout(250)
    print(f"  step {i + 1}: timed out waiting")


async def main(url: str, video: bool, shots: bool, hold_ms: int):
    IMG.mkdir(parents=True, exist_ok=True)
    VID.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=ARGS)
        # warm the caches (renders, IFC meshes) so the recording has no cold-start waits
        warm = await b.new_page(viewport={"width": 1920, "height": 1080})
        await warm.goto(url + "/")
        steps = await warm.evaluate("fetch('/api/tour').then(r => r.json())")
        for s in steps:
            await warm.evaluate("""s => Promise.all([
                fetch('/api/questions?path=' + encodeURIComponent(s.path)).then(r => r.json()).then(i =>
                  i.view ? fetch('/api/render?path=' + encodeURIComponent(i.view)) : null),
                fetch('/api/ask', {method: 'POST', headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({path: s.path, question: s.question})}),
                s.source && s.source.startsWith('ifc') ? fetch('/api/mesh?path=' + encodeURIComponent(s.path)) : null])""", s)
        await warm.close()
        print(f"warmed {len(steps)} steps")

        ctx = await b.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1,
                                  record_video_dir=str(VID) if video else None,
                                  record_video_size={"width": 1920, "height": 1080} if video else None)
        pg = await ctx.new_page()
        await pg.goto(url + "/")
        await pg.wait_for_timeout(1500)
        await pg.evaluate("window.bpTour.start(true)")
        for i in range(len(steps)):
            await wait_step(pg, i)
            await pg.wait_for_timeout(hold_ms)
            if shots:
                save_small(await pg.screenshot(), IMG / f"tour-{i + 1}.png")
            if i < len(steps) - 1:
                await pg.evaluate("window.bpTour.next()")
        await pg.evaluate("document.querySelector('#texit').click()")
        await pg.goto(url + "/results")
        await pg.wait_for_timeout(2500)
        if shots:
            save_small(await pg.screenshot(full_page=True), IMG / "scoreboard.png")
        await pg.mouse.wheel(0, 700)
        await pg.wait_for_timeout(2500)
        vpath = await pg.video.path() if video else None
        await ctx.close()

        if shots:  # phone layout
            ph = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True,
                                     has_touch=True)
            pp = await ph.new_page()
            s = steps[1]
            from urllib.parse import quote

            await pp.goto(f"{url}/?tab={s['source']}&path={quote(s['path'])}&q={quote(s['question'])}")
            await pp.wait_for_timeout(6000)
            save_small(await pp.screenshot(), IMG / "phone.png", width=390)
            await ph.close()
        await b.close()
        if vpath:
            out = VID / f"demo-tour-{time.strftime('%Y%m%d-%H%M%S')}.webm"
            shutil.move(vpath, out)
            print(f"video: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:3123")
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--no-shots", action="store_true")
    ap.add_argument("--hold", type=int, default=2500, help="ms to linger on each finished step")
    a = ap.parse_args()
    asyncio.run(main(a.url.rstrip("/"), not a.no_video, not a.no_shots, a.hold))
