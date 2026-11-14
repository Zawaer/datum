"""Capture the "beyond the answer" feature screenshots for the deck and README (1920x1080 at 1.5x, JPEG).

    .venv/bin/python docs/deck/capture_features.py [--url http://localhost:3138] [--only 3d,xray,ghost,heat,sheet,voice,how,ifc]

Saves to docs/deck/img/ (each shot keeps the drawing's credit line, or adds it under a composed strip):
  feat-3d.jpg        "See it in 3D": the Swiss plan risen into a model, the 20 counted doors lit and numbered
  feat-3d-rise.jpg   four frames of the rise, from the flat plan to the numbered model
  feat-xray.jpg      the X-ray count, caught mid-count (the browser clock is frozen to hold the frame)
  feat-ghost.jpg     the answer card with our number against five frontier models (German area question)
  feat-*-card.jpg    tighter crops of the 3D and X-ray shots (deck grid), with the credit line added under them
  feat-heatmap.jpg   every room shaded by its net area, with the legend
  feat-takeoff.jpg   the printable takeoff sheet (room schedule)
  feat-voice.jpg     the voice strip on a Finnish plan (staged: the strip is filled in, no audio is recorded or sent)
  feat-how.jpg       the "How it works" page, routing section
  feat-ifc3d.jpg     an IFC model with storeys exploded and x-ray on (slow under software WebGL)
"""
import argparse
import asyncio
import io
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright

OUT = Path("docs/deck/img")
ARGS = ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"]
K = 1.5  # device scale factor
SWISS = "data/swiss_dwellings/site3387_bldg5238_floor23498.pdf"
DOORS = "How many doors (interior doors and entrance doors together) are drawn on this floor plan?"
GERMAN = ("data/swiss_dwellings/site11487_bldg17991_floor47889.pdf",
          "Wie gross ist die Nettowohnfläche von Wohnung A in m² (Summe aller Räume ohne Balkone, Loggien, "
          "Terrassen und andere Aussenräume)?")
FINNISH = ("data/cubicasa5k/high_quality-10132.png",
           "Kuinka monta ovea pohjapiirustuksessa on? Laske oviaukot, joissa on ovi; "
           "pelkkiä oviaukkoja ilman ovilehteä ei lasketa.")
MOLIO = ("data/ifc_models/bsc-molio_molio-with-uris_plan-03-grundplan.pdf",
         "Hvad er den samlede længde af alle vægge på 'Grundplan' i meter?")
SWISS_CREDIT = ("Drawing: Swiss Dwellings v3.0.0, M. Standfest et al. (Archilyse AG), "
                "doi:10.5281/zenodo.7788422, CC BY 4.0")
VIEW = (300, 92, 1920, 1080)       # viewer + answer panel (CSS px), as in capture.py's deck crops
PLAN = (300, 92, 1440, 1080)       # viewer only
CUBICASA_CREDIT = ("Drawing: CubiCasa5K, (c) 2019 CubiCasa; Kalervo, Ylioinas, Häikiö, Karhu, Kannala, SCIA 2019; "
                   "CC BY-NC-SA 4.0")


def img(png):
    return Image.open(io.BytesIO(png)).convert("RGB")


def crop(im, box):
    return im.crop(tuple(round(v * K) for v in box))


def save(im, name, width=1800, q=85):
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    out = OUT / name
    im.save(out, quality=q, optimize=True, progressive=True)
    kb = out.stat().st_size // 1024
    if kb > 400 and q > 70:
        return save(im, name, width, q - 5)
    print(out, im.size, kb, "KB", flush=True)


def credited(im, text):
    """the crop with the drawing's credit line under it (the app's own credit row is cut off by the crop)"""
    h = round(30 * K)
    out = Image.new("RGB", (im.width, im.height + h), "white")
    out.paste(im, (0, 0))
    ImageDraw.Draw(out).text((round(10 * K), im.height + round(7 * K)),
                             text, fill=(100, 116, 139), font=font(round(15 * K)))
    return out


def font(size):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


async def open_q(pg, url, path, q, tab, wait=8000):
    await pg.goto(f"{url}/?tab={tab}&path={quote(path)}&q={quote(q)}")
    await pg.wait_for_timeout(wait)


async def shot_3d(pg, url):
    await open_q(pg, url, SWISS, DOORS, "swiss_dwellings")
    await pg.evaluate("window.__p3riseMs = 14000; window.__p3.open()")
    frames = []
    for t in (200, 1700, 1700):
        await pg.wait_for_timeout(t)
        frames.append(crop(img(await pg.screenshot()), PLAN))
    for _ in range(600):
        if await pg.evaluate("window.__p3.ready"):
            break
        await pg.wait_for_timeout(500)
    await pg.wait_for_timeout(2500)
    full = img(await pg.screenshot())
    save(crop(full, VIEW), "feat-3d.jpg")
    save(credited(crop(full, (340, 250, 1410, 980)), SWISS_CREDIT), "feat-3d-card.jpg", width=1400)
    frames.append(crop(full, PLAN))
    # rise strip: 4 frames side by side (without the credit row of each), one credit line under the strip
    fw, fh = 900, 640
    pad, cap = 14, 46
    strip = Image.new("RGB", (4 * fw + 5 * pad, fh + 2 * pad + cap), "white")
    for i, f in enumerate(frames):
        f = f.crop(tuple(round(v * K) for v in (40, 140, 1110, 900))).resize((fw, fh), Image.LANCZOS)
        strip.paste(f, (pad + i * (fw + pad), pad))
    ImageDraw.Draw(strip).text((pad, fh + 2 * pad + 6), SWISS_CREDIT, fill=(100, 116, 139), font=font(26))
    save(strip, "feat-3d-rise.jpg", width=2400)


async def shot_xray(pg, url):
    await open_q(pg, url, SWISS, DOORS, "swiss_dwellings")
    await pg.clock.install()
    await pg.click("#go")
    seen = ""
    for _ in range(4000):
        await pg.clock.run_for(40)
        await pg.wait_for_timeout(30)
        seen = await pg.evaluate("(() => { const h = document.querySelector('.xhud'); return h && !h.hidden ? h.querySelector('b').textContent : ''; })()")
        if seen and int(seen.split("/")[0]) >= 13:
            break
    print("x-ray frame at", seen, flush=True)
    await pg.wait_for_timeout(300)
    full = img(await pg.screenshot())
    save(crop(full, VIEW), "feat-xray.jpg")
    save(credited(crop(full, (300, 100, 1440, 876)), SWISS_CREDIT), "feat-xray-card.jpg", width=1400)


async def shot_ghost(pg, url):
    path, q = GERMAN
    await open_q(pg, url, path, q, "swiss_dwellings", wait=9000)
    g = pg.locator("#answer .ghostcmp")
    await g.scroll_into_view_if_needed()
    await pg.wait_for_timeout(1500)
    full = img(await pg.screenshot())
    bb = await g.bounding_box()
    a = await pg.locator("#answer").bounding_box()
    # the answer card's top (question + number) down to the end of the comparison
    save(crop(full, (a["x"] - 8, max(92, a["y"] - 8), a["x"] + a["width"] + 8, bb["y"] + bb["height"] + 3)),
         "feat-ghost.jpg", width=1200)


async def shot_heat(pg, url):
    await open_q(pg, url, SWISS, DOORS, "swiss_dwellings")
    await pg.click("#heatbtn")
    await pg.wait_for_timeout(3000)
    save(credited(crop(img(await pg.screenshot()), (300, 260, 1440, 1035)), SWISS_CREDIT), "feat-heatmap.jpg", width=1400)
    await pg.click("#sheetbtn")
    await pg.wait_for_timeout(2500)
    sh = await pg.locator("#sheetwrap .sheet").bounding_box()
    save(credited(crop(img(await pg.screenshot()), (sh["x"] - 10, sh["y"] + 30, sh["x"] + sh["width"] + 10,
                                                     sh["y"] + 30 + (sh["width"] + 20) / 1.47)), SWISS_CREDIT),
         "feat-takeoff.jpg", width=1400)


async def shot_voice(pg, url):
    path, q = FINNISH
    await open_q(pg, url, path, q, "cubicasa5k", wait=9000)
    stage = """() => {
      const s = document.querySelector('#voice'), mic = document.querySelector('#mic');
      if (!s || !mic) return false;
      s.hidden = false; s.dataset.state = 'listening'; mic.classList.add('on');
      s.querySelector('.vstate').textContent = 'Listening';
      s.querySelector('.vdone').hidden = true; s.querySelector('.vmeter').hidden = true; s.querySelector('.vtime').hidden = true;
      const sel = s.querySelector('.vlang'); if ([...sel.options].some(o => o.value === 'fi-FI')) sel.value = 'fi-FI';
      s.querySelector('.vfin').textContent = 'Kuinka monta ovea pohjapiirustuksessa on?';
      s.querySelector('.vint').textContent = ' Laske oviaukot, joissa on ovi';
      s.parentElement.scrollTop = 0; window.scrollTo(0, 0);
      return true; }"""
    ok = await pg.evaluate(stage)
    if not ok:
        print("voice: no mic button in this browser", flush=True)
        return
    await pg.wait_for_timeout(1500)
    await pg.evaluate(stage)
    await pg.wait_for_timeout(300)
    save(credited(crop(img(await pg.screenshot()), (1000, 92, 1920, 720)), CUBICASA_CREDIT), "feat-voice.jpg", width=1400)


async def shot_how(pg, url):
    await pg.goto(url + "/how")
    await pg.wait_for_timeout(2000)
    await pg.evaluate("document.querySelector('#route').scrollIntoView({block: 'start'})")
    await pg.wait_for_timeout(1500)
    for _ in range(12):  # scroll through the chapter so its steps play, end on the full routing graphic
        await pg.mouse.wheel(0, 120)
        await pg.wait_for_timeout(400)
    await pg.wait_for_timeout(2500)
    save(crop(img(await pg.screenshot()), (300, 100, 1610, 880)), "feat-how.jpg", width=1400)


async def shot_ifc(pg, url):
    path, q = MOLIO
    await open_q(pg, url, path, q, "ifc_models", wait=6000)
    await pg.click("#m3d")
    for _ in range(600):
        if await pg.evaluate("(window.__v3renders || 0) > 0") and await pg.locator("text=Explode storeys").count():
            break
        await pg.wait_for_timeout(1000)
    await pg.wait_for_timeout(5000)
    await pg.locator("button:has-text('Explode storeys')").click()
    await pg.wait_for_timeout(8000)
    await pg.locator("button:has-text('X-ray')").click()
    await pg.wait_for_timeout(12000)
    save(crop(img(await pg.screenshot()), VIEW), "feat-ifc3d.jpg")


SHOTS = {"3d": shot_3d, "xray": shot_xray, "ghost": shot_ghost, "heat": shot_heat, "voice": shot_voice,
         "how": shot_how, "ifc": shot_ifc}


async def main(url, only):
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=ARGS)
        for name, fn in SHOTS.items():
            if name not in only:
                continue
            pg = await b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=K)
            try:
                await fn(pg, url)
            except Exception as e:  # one failed shot should not lose the others
                print(name, "failed:", e, flush=True)
            await pg.close()
        await b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:3138")
    ap.add_argument("--only", default=",".join(SHOTS))
    a = ap.parse_args()
    asyncio.run(main(a.url.rstrip("/"), set(a.only.split(","))))
