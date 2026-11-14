"""Capture the deck and README screenshots from the running demo (1920x1080 at 1.5x, JPEG, credit line visible).

    .venv/bin/python docs/deck/capture.py [--url http://localhost:3123] [--only landing,finnish,tour,crop]

Saves to docs/deck/img/:
  landing.jpg      the landing page with the headline strip
  step-<n>.jpg     after each step of the demo tour (app/tour.json); the caption card is hidden for the shot
  finnish.jpg      a Finnish CubiCasa plan (test split) where the detector and our fine-tuned vision model agree on 13 doors
  deck-*.jpg       cropped to drawing + answer panel (see CROPS) for the 2-up deck slides
The deck uses landing and the crops of step-1 (Swiss doors), step-2 (German area + frontier table), step-3
(correction), finnish and step-6 (IFC walls in 3D with the arithmetic). Under software WebGL the 3D steps take minutes.
"""
import argparse
import asyncio
import io
from pathlib import Path
from urllib.parse import quote

from PIL import Image
from playwright.async_api import async_playwright

OUT = Path("docs/deck/img")
ARGS = ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"]
FINNISH = ("data/cubicasa5k/high_quality-10132.png",
           "Kuinka monta ovea pohjapiirustuksessa on? Laske oviaukot, joissa on ovi; "
           "pelkkiä oviaukkoja ilman ovilehteä ei lasketa.")


def save(png: bytes, out: Path, width=2400, q=82):
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(out, quality=q, optimize=True, progressive=True)
    print(out, out.stat().st_size // 1024, "KB", flush=True)


async def wait_step(pg, i, timeout_s=600):
    for _ in range(timeout_s * 4):
        if await pg.evaluate("window.__tourStepDone") == i:
            return
        await pg.wait_for_timeout(250)
    print(f"step {i + 1}: timed out", flush=True)


async def main(url, only):
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=ARGS)
        pg = await b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1.5)
        if "landing" in only:
            await pg.goto(url + "/")
            await pg.wait_for_timeout(4000)
            save(await pg.screenshot(), OUT / "landing.jpg")
        if "finnish" in only:
            path, q = FINNISH
            await pg.goto(f"{url}/?tab=cubicasa5k&path={quote(path)}&q={quote(q)}")
            await pg.wait_for_timeout(9000)
            save(await pg.screenshot(), OUT / "finnish.jpg")
        if "tour" in only:
            await pg.goto(url + "/")
            await pg.wait_for_timeout(2000)
            n = len(await pg.evaluate("fetch('/api/tour').then(r => r.json())"))
            await pg.evaluate("window.bpTour.start(true)")
            for i in range(n):
                await wait_step(pg, i)
                await pg.wait_for_timeout(2500)
                await pg.evaluate("document.querySelector('#caption').hidden = true")
                await pg.wait_for_timeout(400)
                save(await pg.screenshot(), OUT / f"step-{i + 1}.jpg")
                await pg.evaluate("document.querySelector('#caption').hidden = false")
                if i < n - 1:
                    await pg.evaluate("window.bpTour.next()")
        await b.close()
    if "crop" in only:
        crop()


# deck versions without the file list and header (the drawing, its credit line and the answer panel only)
CROPS = {"step-1": "deck-swiss-doors", "step-2": "deck-german-area", "step-3": "deck-correction",
         "finnish": "deck-finnish-vlm", "step-6": "deck-ifc-walls"}


def crop(q=80):
    for src, dst in CROPS.items():
        f = OUT / f"{src}.jpg"
        if not f.exists():
            continue
        im = Image.open(f)
        k = im.width / 1920  # screenshot pixels per CSS pixel
        im = im.crop((round(300 * k), round(92 * k), im.width, im.height))
        im.save(OUT / f"{dst}.jpg", quality=q, optimize=True, progressive=True)
        print(OUT / f"{dst}.jpg", (OUT / f"{dst}.jpg").stat().st_size // 1024, "KB", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:3123")
    ap.add_argument("--only", default="landing,finnish,tour,crop")
    a = ap.parse_args()
    asyncio.run(main(a.url.rstrip("/"), set(a.only.split(","))))
