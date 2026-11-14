"""Capture the deck and README screenshots of the answers from the running demo (JPEG, every drawing's credit line visible).

    .venv/bin/python docs/deck/capture.py [--url http://localhost:3146] [--only landing,doors,area,correction,finnish,ifc,phone]

Desktop shots are 1920x1080 at 1.5x, cropped below the app's header bar; phone shots are 390x844 at 3x.
Saves to docs/deck/img/:
  landing.jpg            the calm landing (drawing, one-line pitch, tour button, ask box)
  deck-swiss-doors.jpg   "How many doors?" 20 numbered on a Swiss plan, the evidence list open, door #7's card beside it
  deck-german-area.jpg   German area question: the six rooms outlined with their m², the frontier-model section opened
  deck-correction.jpg    window #4 unticked: the total changes to 10 and the app notes the solver said 11
  deck-finnish-vlm.jpg   a Finnish CubiCasa plan, asked in Finnish: the detector's boxes and the vision model's second opinion
  deck-ifc-rooms.jpg     a BIM model asked in Danish how many rooms: the rooms painted on their floor in 3D, a pin on each
  phone-landing.jpg, phone-answer.jpg, phone-card.jpg   the phone quick-ask view: landing, answer sheet with pins, a pin's card
  phone-trio.jpg         the three phone shots side by side with the credit line under them
The "beyond the answer" shots (3D, X-ray, frontier comparison, heat-map, Accuracy, How it works) are in capture_features.py.
Under software WebGL the 3D shots take minutes.
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
K = 1.5
APP = (0, 56, 1920, 1080)  # below the header bar: drawing (with its credit line) and the answer column
SWISS = "data/swiss_dwellings/site3387_bldg5238_floor23498.pdf"
DOORS = "How many doors (interior doors and entrance doors together) are drawn on this floor plan?"
WINDOWS = "How many windows are drawn on this floor plan?"
GERMAN = ("data/swiss_dwellings/site11487_bldg17991_floor47889.pdf",
          "Wie gross ist die Nettowohnfläche von Wohnung A in m² (Summe aller Räume ohne Balkone, Loggien, "
          "Terrassen und andere Aussenräume)?")
FINNISH = ("data/cubicasa5k/high_quality-10132.png",
           "Kuinka monta ovea pohjapiirustuksessa on? Laske oviaukot, joissa on ovi; "
           "pelkkiä oviaukkoja ilman ovilehteä ei lasketa.")
MOLIO = ("data/ifc_models/bsc-molio_molio-with-uris_plan-03-grundplan.pdf",
         "Hvor mange rum er vist på plantegningen for 'Grundplan'?")
SWISS_CREDIT = ("Drawing: Swiss Dwellings v3.0.0, M. Standfest et al. (Archilyse AG), "
                "doi:10.5281/zenodo.7788422, CC BY 4.0")


def img(png):
    return Image.open(io.BytesIO(png)).convert("RGB")


def save(im, name, width=2400, q=82):
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    out = OUT / name
    im.save(out, quality=q, optimize=True, progressive=True)
    kb = out.stat().st_size // 1024
    if kb > 450 and q > 66:
        return save(im, name, width, q - 6)
    print(out, im.size, kb, "KB", flush=True)


def font(size):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


async def settle(pg, extra=1500, timeout_s=120):
    """wait for the answer card, then for the X-ray count to finish"""
    try:
        await pg.wait_for_selector("#answer:not([hidden])", timeout=timeout_s * 1000)
    except Exception:
        print("no answer card", flush=True)
    for _ in range(timeout_s * 4):
        if not await pg.evaluate("document.querySelector('#viewer').classList.contains('xray')"):
            break
        await pg.wait_for_timeout(250)
    await pg.wait_for_timeout(extra)


async def open_q(pg, url, path, q, tab, extra=1500):
    await pg.goto(f"{url}/?tab={tab}&path={quote(path)}&q={quote(q)}")
    await settle(pg, extra)


async def shot(pg, box=APP):
    return img(await pg.screenshot()).crop(tuple(round(v * K) for v in box))


async def landing(pg, url):
    await pg.goto(url + "/")
    await pg.wait_for_timeout(5000)
    save(img(await pg.screenshot()), "landing.jpg")


async def doors(pg, url):
    await open_q(pg, url, SWISS, DOORS, "swiss_dwellings")
    await pg.evaluate("document.querySelector('#evwrap').open = true")
    await pg.wait_for_timeout(800)
    await pg.locator('#ov g[data-i="6"] > rect').click(force=True)
    await pg.wait_for_timeout(1500)
    save(await shot(pg), "deck-swiss-doors.jpg")


async def area(pg, url):
    path, q = GERMAN
    await open_q(pg, url, path, q, "swiss_dwellings")
    await pg.evaluate("(() => { const d = document.querySelector('#atail details[data-sec=\"vs\"]'); if (d) d.open = true; })()")
    await pg.wait_for_timeout(1500)
    save(await shot(pg), "deck-german-area.jpg")


async def correction(pg, url):
    await open_q(pg, url, SWISS, WINDOWS, "swiss_dwellings")
    await pg.evaluate("document.querySelector('#evwrap').open = true")
    await pg.wait_for_timeout(600)
    await pg.locator('#ev div[data-i="3"] .tg').click()
    await pg.wait_for_timeout(1800)
    save(await shot(pg), "deck-correction.jpg")


async def finnish(pg, url):
    path, q = FINNISH
    await open_q(pg, url, path, q, "cubicasa5k", extra=12000)
    await pg.evaluate("document.querySelector('#evwrap').open = true")
    await pg.wait_for_timeout(800)
    save(await shot(pg), "deck-finnish-vlm.jpg")


async def ifc(pg, url):
    path, q = MOLIO
    await open_q(pg, url, path, q, "ifc_models", extra=2000)
    await pg.click("#m3d")
    for _ in range(600):
        if await pg.evaluate("(window.__v3renders || 0) > 0 && document.querySelector('#loading').hidden"):
            break
        await pg.wait_for_timeout(1000)
    await pg.wait_for_timeout(15000)
    save(await shot(pg), "deck-ifc-rooms.jpg")


async def phone(b, url):
    ctx = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True)
    pg = await ctx.new_page()
    shots = []
    await pg.goto(url + "/")
    await pg.wait_for_timeout(5000)
    shots.append(img(await pg.screenshot()))
    await open_q(pg, url, SWISS, DOORS, "swiss_dwellings", extra=2500)
    shots.append(img(await pg.screenshot()))
    await pg.locator('#ov g[data-i="6"] circle.hit').tap(force=True)
    await pg.wait_for_timeout(1800)
    shots.append(img(await pg.screenshot()))
    await ctx.close()
    for name, im in zip(("phone-landing", "phone-answer", "phone-card"), shots):
        save(im, name + ".jpg", width=1170, q=84)
    # the trio for the deck and README: three phones side by side, one credit line under them
    w, h = 780, round(780 * 844 / 390)
    pad, cap = 40, 60
    trio = Image.new("RGB", (3 * w + 4 * pad, h + 2 * pad + cap), "white")
    for i, s in enumerate(shots):
        s = s.resize((w, h), Image.LANCZOS)
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=56, fill=255)
        x = pad + i * (w + pad)
        ImageDraw.Draw(trio).rounded_rectangle((x - 3, pad - 3, x + w + 2, pad + h + 2), radius=59, fill=(203, 213, 225))
        trio.paste(s, (x, pad), mask)
    ImageDraw.Draw(trio).text((pad, h + 2 * pad + 8), SWISS_CREDIT, fill=(100, 116, 139), font=font(30))
    save(trio, "phone-trio.jpg", width=2400, q=84)


DESKTOP = {"landing": landing, "doors": doors, "area": area, "correction": correction, "finnish": finnish, "ifc": ifc}


async def main(url, only):
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=ARGS)
        for name, fn in DESKTOP.items():
            if name not in only:
                continue
            pg = await b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=K)
            try:
                await fn(pg, url)
            except Exception as e:  # one failed shot should not lose the others
                print(name, "failed:", e, flush=True)
            await pg.close()
        if "phone" in only:
            try:
                await phone(b, url)
            except Exception as e:
                print("phone failed:", e, flush=True)
        await b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:3146")
    ap.add_argument("--only", default=",".join([*DESKTOP, "phone"]))
    a = ap.parse_args()
    asyncio.run(main(a.url.rstrip("/"), set(a.only.split(","))))
