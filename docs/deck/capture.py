"""Capture the deck screenshots from the running demo (1920x1080, JPEG, credit line visible).

    .venv/bin/python docs/deck/capture.py [--url http://localhost:3123]

Runs the demo tour (app/tour.json) and saves docs/deck/img/step-<n>.jpg after each step, then step-5b.jpg
(the IFC door question opened straight in 3D). The deck uses step-1, step-2, step-4 and step-5b.
"""
import argparse
import asyncio
import io
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

OUT = Path("docs/deck/img")
ARGS = ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"]


def save(png: bytes, out: Path, width=1600, q=82):
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(out, quality=q, optimize=True, progressive=True)
    print(out, out.stat().st_size // 1024, "KB")


async def wait_step(pg, i, timeout_s=240):
    for _ in range(timeout_s * 4):
        if await pg.evaluate("window.__tourStepDone") == i:
            return
        await pg.wait_for_timeout(250)


async def main(url):
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=ARGS)
        pg = await b.new_page(viewport={"width": 1920, "height": 1080})
        await pg.goto(url + "/")
        await pg.wait_for_timeout(1500)
        n = len(await pg.evaluate("fetch('/api/tour').then(r => r.json())"))
        await pg.evaluate("window.bpTour.start(true)")
        for i in range(n):
            await wait_step(pg, i)
            await pg.wait_for_timeout(2000)
            await pg.evaluate("document.querySelector('#caption').hidden = true")
            await pg.wait_for_timeout(300)
            save(await pg.screenshot(), OUT / f"step-{i + 1}.jpg")
            await pg.evaluate("document.querySelector('#caption').hidden = false")
            if i < n - 1:
                await pg.evaluate("window.bpTour.next()")
        from urllib.parse import quote
        path = "data/ifc_models/bsc-molio_molio-with-uris_plan-03-grundplan.pdf"
        q = "How many doors are shown on the floor plan of 'Grundplan'?"
        await pg.goto(f"{url}/?tab=ifc_models&path={quote(path)}&q={quote(q)}")
        await pg.wait_for_timeout(8000)
        await pg.click("#m3d")
        await pg.wait_for_timeout(20000)
        await pg.hover('#ev div[data-i="1"]')
        await pg.wait_for_timeout(1500)
        save(await pg.screenshot(), OUT / "step-5b.jpg")
        await b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:3123")
    asyncio.run(main(ap.parse_args().url.rstrip("/")))
