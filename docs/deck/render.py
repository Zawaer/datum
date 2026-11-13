"""Render docs/deck/deck.html to docs/deck/deck.pdf (1920x1080 pages) and PNG previews of single slides.

    .venv/bin/python docs/deck/render.py [--png]
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent


async def main(png: bool):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1920, "height": 1080})
        await pg.goto((HERE / "deck.html").as_uri())
        await pg.wait_for_load_state("networkidle")
        await pg.evaluate("document.fonts.ready")
        await pg.pdf(path=str(HERE / "deck.pdf"), width="1920px", height="1080px", print_background=True,
                     prefer_css_page_size=True)
        n = await pg.evaluate("document.querySelectorAll('.slide').length")
        print(f"deck.pdf: {n} slides, {(HERE / 'deck.pdf').stat().st_size // 1024} KB")
        if png:
            out = Path("/tmp/deck_png"); out.mkdir(exist_ok=True)
            for i in range(1, n + 1):
                await pg.goto((HERE / "deck.html").as_uri() + f"?slide={i}")
                await pg.wait_for_load_state("networkidle")
                await pg.screenshot(path=str(out / f"slide-{i}.png"))
        await b.close()


if __name__ == "__main__":
    asyncio.run(main("--png" in sys.argv))
