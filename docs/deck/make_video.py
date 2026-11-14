"""Build the demo video with voice-over: runs/video/blueprints-<cut>.mp4 (+ .srt). Storyboard: docs/video.md.

    .venv/bin/python docs/deck/make_video.py                       # 2:00 cut, Kokoro voice, all shots recorded live
    .venv/bin/python docs/deck/make_video.py --cut short           # the 60 s cut
    .venv/bin/python docs/deck/make_video.py --voice-only          # synthesize + print the timing (and refresh docs/video.md)
    .venv/bin/python docs/deck/make_video.py --only hook --out /tmp/video_test.mp4   # one shot, with its voice
    .venv/bin/python docs/deck/make_video.py --reuse                # re-cut from the last recorded shots
    .venv/bin/python docs/deck/make_video.py --tts elevenlabs       # ElevenLabs voice if the key may do TTS, else Kokoro
    .venv/bin/python docs/deck/make_video.py --draft                # quick look: lower resolution, less slow-motion

Needs the demo server (default http://localhost:3123; --url), playwright + chromium in .venv, ffmpeg, Pillow.

1. Voice-over: every caption line in SCENES is spoken by Kokoro-82M (Apache-2.0, local CPU) from cache/tts/venv,
   or with --tts elevenlabs by ElevenLabs (key from ELEVENLABS_API_KEY or data/secrets/elevenlabs.env). The key is
   probed once (the current key passed on 2026-11-14); a 401/403 (e.g. a Speech-to-Text-only key) falls back to
   Kokoro. The key is never printed. Clips are cached per engine/voice/text, so re-cuts cost nothing.
2. Timing: each scene lasts as long as its voice-over (LEAD before, GAP between lines, TAIL after); the total must
   stay <= the cut's limit (120 s / 60 s). The timing table in docs/video.md is rewritten between the TIMING markers.
3. Picture: every scene is a live recording, the result cards included (their bars grow), so nothing is a slide.
   Headless Chromium here has no GPU (the container gets the NVIDIA compute libraries only, no GL/Vulkan driver,
   so --use-angle=vulkan / --enable-gpu still end up on SwiftShader). Instead of fighting that, shots are recorded
   in slow motion: the page's clock (performance.now, Date.now, requestAnimationFrame, setTimeout/setInterval and
   CSS animations via CDP) runs SLOW times slower, a capture loop grabs JPEG frames as fast as it can with their
   page-time stamps, and the frames are resampled to a steady 30 fps. However slow the software 3D is, the video
   plays smoothly at real speed. Frames are captured at 2x device pixels, so a shot can punch in (rec.cam) to
   half the screen and still be sharp.
4. Mux: picture scaled to 85 % with a caption band underneath (drawing credits are never covered), burned-in
   captions from the same lines, loudness-normalised voice, H.264/AAC 1920x1080 30 fps.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "runs/video"
WORK = OUT / "work"
TTS_PY = ROOT / "cache/tts/venv/bin/python"
TTS_CACHE = ROOT / "cache/tts/clips"
VOICE, SPEED, SR = "af_heart", 1.05, 24000
LEAD, GAP, TAIL = 0.35, 0.30, 0.45
LIMIT = {"full": 120.0, "short": 60.0}
FPS = 30
VIEW = (1536, 864)          # CSS px; at DPR 1.25 that is exactly 1920x1080, so app text reads like a 1080p screen
REPO_URL = "github.com/Zawaer/datum"
ELEVEN_VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")   # "Rachel", a stock voice
ELEVEN_MODEL = os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")

SWISS_DOORS = "data/swiss_dwellings/site3387_bldg5238_floor23498.pdf"
Q_DOORS = "How many doors (interior doors and entrance doors together) are drawn on this floor plan?"
SWISS_AREA = "data/swiss_dwellings/site11487_bldg17991_floor47889.pdf"
Q_AREA_DE = ("Wie gross ist die Nettowohnfläche von Wohnung A in m² (Summe aller Räume ohne Balkone, Loggien, "
             "Terrassen und andere Aussenräume)?")
Q_WINDOWS = "How many windows are drawn on this floor plan?"
CUBI = "data/cubicasa5k/colorful-10052.png"
Q_DOORS_FI = "Kuinka monta ovea pohjapiirustuksessa on?"
IFC_PLAN = "data/ifc_models/bsc-molio_molio-with-uris_plan-03-grundplan.pdf"
Q_IFC_WALLS = "How many doors are shown on the floor plan of 'Grundplan'?"

# A line is (caption, spoken) or just text when both are the same. Numbers are spelled out where the TTS could
# misread them. Sources for every number: README.md, docs/RESULTS.md, docs/COSTS.md (listed in docs/video.md).
# "cuts": which cut a scene is in; "short": the lines it speaks in the 60 s cut (default: the same lines).
SCENES = [
    {"id": "hook", "kind": "shot", "cuts": "full short", "min": 8.5, "lines": [  # min: room for both chips
        "Ask a floor plan how many doors it has.",
        ("Twenty. And here is every single one.", "Twenty. And here is every single one."),
    ]},
    {"id": "problem", "kind": "card", "cuts": "full short", "lines": [
        "Quantity takeoff is still done by hand.",
        ("Frontier AI, given the very same files, gets seven answers in ten right,",
         "Frontier A.I., given the very same files, gets seven answers in ten right,"),
        "and sounds just as sure when it's wrong.",
    ], "short": [
        ("Frontier AI gets seven answers in ten right, and sounds just as sure when it's wrong.",
         "Frontier A.I. gets seven answers in ten right, and sounds just as sure when it's wrong."),
    ]},
    {"id": "how", "kind": "shot", "cuts": "full", "lines": [
        "So we don't guess. Every question goes to an exact method:",
        "the CAD geometry, the BIM model, or a small detector we trained.",
    ]},
    {"id": "xray", "kind": "shot", "cuts": "full short", "lines": [
        "Ask in plain words, and the X-ray counts every door on the drawing.",
        "A second, independent method agrees. No model call, zero cost.",
    ], "short": [
        "Ask in plain words. The X-ray counts every door on the drawing.",
    ]},
    {"id": "ghost", "kind": "shot", "cuts": "full short", "lines": [
        "Asked in German: the net living area of apartment A.",
        "Every room carries its own square metres, and they add up to the answer.",
        "Five frontier models, same drawing: all five wrong.",
    ], "short": [
        "In German: every room's square metres add up to the answer.",
        "Five frontier models, same drawing: all five wrong.",
    ]},
    {"id": "correct", "kind": "shot", "cuts": "full short", "lines": [
        "Disagree? Untick an item, or click one we missed. The total follows.",
    ]},
    {"id": "heat", "kind": "shot", "cuts": "full", "lines": [
        "One click shades every room by its area, and prints the takeoff sheet.",
    ]},
    {"id": "voice", "kind": "shot", "cuts": "full short", "lines": [
        "Or just ask out loud, in Finnish.",
        "Our detector boxes every door it counts.",
    ], "short": [
        "Or ask out loud, in Finnish.",
    ]},
    {"id": "ifc", "kind": "shot", "cuts": "full", "lines": [
        ("BIM models are answered from the model itself.", "Bim models are answered from the model itself."),
        "Explode the storeys, X-ray the rest, and the evidence glows.",
    ]},
    {"id": "results", "kind": "card", "cuts": "full short", "lines": [
        ("90.0 % right on all 25,420 held-out test questions.",
         "Ninety percent right, on all twenty-five thousand held-out test questions."),
        ("Claude Sonnet 5.5, given the same files: 69.8 %.",
         "Claude Sonnet, given the same files: seventy."),
    ]},
    {"id": "cost", "kind": "card", "cuts": "full short", "lines": [
        ("$0.013 per 1,000 questions. Sonnet: $25.76.",
         "One point three cents per thousand questions. Sonnet: twenty-five dollars seventy-six."),
    ]},
    {"id": "end", "kind": "card", "cuts": "full short", "min": 3.5, "lines": [
        "Exact. Verifiable. Cheap. Blueprints That Talk.",
    ]},
]

CREDITS = ("Drawings: Swiss Dwellings v3.0.0 (Archilyse AG, CC BY 4.0) · CubiCasa5K (CubiCasa, CC BY-NC-SA 4.0) · "
           "Molio Demo-hus (buildingSMART sample files, CC BY 4.0) · questions from the Junction 2026 Stoa dataset")


def scenes_of(cut):
    return [s for s in SCENES if cut in s["cuts"].split()]


def lines_of(scene, cut="full"):
    ls = scene.get("short", scene["lines"]) if cut == "short" else scene["lines"]
    return [l if isinstance(l, tuple) else (l, l) for l in ls]


# ---------------------------------------------------------------- voice

def tts_worker():
    """Runs inside cache/tts/venv. stdin: {"voice", "speed", "items": [{"text", "path"}]}."""
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline
    job = json.load(sys.stdin)
    pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    for it in job["items"]:
        audio = np.concatenate([r.audio.numpy() for r in pipe(it["text"], voice=job["voice"], speed=job["speed"])])
        sf.write(it["path"], audio, SR, subtype="PCM_16")
        print(f"tts {len(audio) / SR:5.2f} s  {it['text'][:70]}", flush=True)


ENGINE = "kokoro"


def clip_path(text):
    tag = f"{VOICE}|{SPEED}|{text}" if ENGINE == "kokoro" else f"eleven|{ELEVEN_VOICE}|{ELEVEN_MODEL}|{text}"
    return TTS_CACHE / f"{hashlib.sha1(tag.encode()).hexdigest()[:16]}.wav"


def eleven_key():
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"].strip()
    f = ROOT / "data/secrets/elevenlabs.env"
    if f.exists():
        for ln in f.read_text().splitlines():
            k, _, v = ln.partition("=")
            if k.strip() == "ELEVENLABS_API_KEY" and v.strip():
                return v.strip().strip('"').strip("'")
    return None


def eleven_tts(text, key):
    """-> 16-bit mono PCM at SR, or raises urllib.error.HTTPError. The key only ever goes into the request header."""
    url = (f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE}?output_format=pcm_{SR}")
    body = json.dumps({"text": text, "model_id": ELEVEN_MODEL,
                       "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/pcm"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def pick_engine(want):
    """'kokoro' | 'elevenlabs' | 'auto' -> the engine that will actually speak (probes ElevenLabs once)."""
    global ENGINE
    ENGINE = "kokoro"
    if want == "kokoro":
        return ENGINE
    key = eleven_key()
    if not key:
        print("ElevenLabs TTS: no key found; using Kokoro")
        return ENGINE
    try:
        eleven_tts("Test.", key)
        ENGINE = "elevenlabs"
        print(f"ElevenLabs TTS: available (voice {ELEVEN_VOICE}, {ELEVEN_MODEL})")
    except urllib.error.HTTPError as e:
        why = {401: "key not accepted for text-to-speech (it may be a speech-to-text-only key)",
               403: "key lacks the text-to-speech permission"}.get(e.code, "request failed")
        print(f"ElevenLabs TTS: HTTP {e.code}, {why}; falling back to Kokoro")
    except Exception as e:  # network
        print(f"ElevenLabs TTS: unreachable ({type(e).__name__}); falling back to Kokoro")
    return ENGINE


def synthesize(scenes, cut):
    TTS_CACHE.mkdir(parents=True, exist_ok=True)
    todo = [{"text": say, "path": str(clip_path(say))} for s in scenes for _, say in lines_of(s, cut)
            if not clip_path(say).exists()]
    if not todo:
        return
    if ENGINE == "elevenlabs":
        key = eleven_key()
        for it in todo:
            pcm = eleven_tts(it["text"], key)
            with wave.open(it["path"], "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
                w.writeframes(pcm)
            print(f"tts {len(pcm) / 2 / SR:5.2f} s  {it['text'][:70]}")
        return
    env = {**os.environ, "HF_HOME": str(ROOT / "cache/tts/hf")}
    subprocess.run([str(TTS_PY), "-I", __file__, "--tts-worker"], input=json.dumps(
        {"voice": VOICE, "speed": SPEED, "items": todo}), text=True, check=True, env=env)


def wav_dur(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def timeline(scenes, cut):
    """Scene start/duration and caption (start, end, text, clip) from the measured clip lengths."""
    fr = 1 / FPS
    t, plan, caps = 0.0, [], []
    for s in scenes:
        ls = lines_of(s, cut)
        c = t + (LEAD if ls else 0)
        for cap, say in ls:
            d = wav_dur(clip_path(say))
            caps.append((c, c + d, cap, clip_path(say)))
            c += d + GAP
        dur = (c - GAP + TAIL - t) if ls else 0
        dur = max(dur, s.get("min", 0))
        dur = round(dur / fr + 0.4999) * fr
        plan.append((s, t, dur))
        t += dur
    return plan, caps, t


def write_voice(caps, total, path, t0=0.0):
    pcm = bytearray(int(total * SR) * 2)
    for a, _, _, clip in caps:
        with wave.open(str(clip)) as w:
            data = w.readframes(w.getnframes())
        i = int((a - t0) * SR) * 2
        if 0 <= i < len(pcm):
            pcm[i:i + len(data)] = data[:len(pcm) - i]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(bytes(pcm))


def ts(x):
    ms = int(round(x * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(caps, path, t0=0.0):
    path.write_text("\n".join(f"{k + 1}\n{ts(a - t0)} --> {ts(e - t0 + 0.25)}\n{text}\n"
                              for k, (a, e, text, _) in enumerate(caps)), encoding="utf-8")


# ---------------------------------------------------------------- slow-motion recorder

# Injected before any page script: the page's clock runs SLOW times slower than the wall clock.
CLOCK_SHIM = """(() => {
  const S = %(slow)s; window.__SLOW = S;
  const pn = performance.now.bind(performance), t0 = pn();
  const vt = t => t0 + (t - t0) / S;
  performance.now = () => vt(pn());
  const dn = Date.now, d0 = dn(); Date.now = () => d0 + (dn() - d0) / S;
  const raf = window.requestAnimationFrame.bind(window);
  // the native rAF timestamp did not stay on the shimmed timeline (it lagged ~S x): hand callbacks the page clock
  window.requestAnimationFrame = cb => raf(() => cb(performance.now()));
  const st = window.setTimeout.bind(window), si = window.setInterval.bind(window);
  window.setTimeout = (f, ms, ...a) => st(f, (+ms || 0) * S, ...a);
  window.setInterval = (f, ms, ...a) => si(f, (+ms || 0) * S, ...a);
  // smooth scrolls are animated by the browser in wall time: redo them on the (slowed) page clock
  const ease = k => k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
  const glide = (el, top, left) => {
    const y0 = el === window ? scrollY : el.scrollTop, x0 = el === window ? scrollX : el.scrollLeft, a = performance.now();
    const go = () => { const k = Math.min(1, (performance.now() - a) / 600), e = ease(k);
      const y = y0 + ((top ?? y0) - y0) * e, x = x0 + ((left ?? x0) - x0) * e;
      if (el === window) origW.call(window, x, y); else { el.scrollTop = y; el.scrollLeft = x; }
      if (k < 1) window.requestAnimationFrame(go); };
    go();
  };
  const origE = Element.prototype.scrollTo, origW = window.scrollTo;
  Element.prototype.scrollTo = function (o, y) {
    if (o && typeof o === 'object' && o.behavior === 'smooth') return glide(this, o.top, o.left);
    return origE.call(this, o, y);
  };
  window.scrollTo = function (o, y) {
    if (o && typeof o === 'object' && o.behavior === 'smooth') return glide(window, o.top, o.left);
    return origW.call(window, o, y);
  };
})();"""

# On-screen text: a title chip / lower third drawn by the page itself (crisp at any zoom), plus "hero" layout.
OVERLAY_CSS = """
#vidtx { position: fixed; left: 50%; top: 92px; transform: translate(-50%, -12px); z-index: 99999; opacity: 0;
  transition: opacity .35s ease, transform .35s ease; pointer-events: none; text-align: center;
  font-family: Inter, "Helvetica Neue", Arial, "DejaVu Sans", sans-serif; }
#vidtx.on { opacity: 1; transform: translate(-50%, 0); }
#vidtx b { display: inline-block; background: #0b1220; color: #fff; font-size: 30px; font-weight: 800; letter-spacing: -.01em;
  padding: 12px 22px; border-radius: 12px; box-shadow: 0 8px 30px rgba(11,18,32,.25); }
#vidtx b em { font-style: normal; color: #60a5fa; }
#vidtx small { display: block; margin-top: 8px; font-size: 17px; color: #334155; background: rgba(255,255,255,.92);
  padding: 5px 12px; border-radius: 8px; width: max-content; margin-left: auto; margin-right: auto; }
body.vidhero main { grid-template-columns: 1fr !important; }
body.vidhero #list, body.vidhero #side { display: none !important; }
"""


class Rec:
    """Grabs frames from one page (CDP screenshots) stamped with page time; camera moves for punch-ins."""

    def __init__(self, pg, cdp, slow, name, view=VIEW):
        self.pg, self.cdp, self.slow, self.name, self.view = pg, cdp, slow, name, view
        self.dir = WORK / f"shot-{name}"
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)
        self.frames, self.cams, self.marks = [], [(0.0, None, 0.0)], {}
        self.t0 = None
        self.task = None

    def now(self):  # page-time seconds since the recording started
        return (time.monotonic() - self.t0) / self.slow

    async def sleep(self, s):  # page-time sleep
        await asyncio.sleep(s * self.slow)

    async def _loop(self):
        n = 0
        while self.on:
            t = self.now()
            try:
                r = await self.cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 92})
            except Exception:
                await asyncio.sleep(0.05)
                continue
            p = self.dir / f"{n:05d}.jpg"
            p.write_bytes(base64.b64decode(r["data"]))
            self.frames.append((t, p.name))
            n += 1

    async def start(self):
        self.t0 = time.monotonic()
        self.on = True
        self.task = asyncio.create_task(self._loop())

    async def stop(self, hold=0.6):
        await self.sleep(hold)
        self.on = False
        await self.task
        dur = self.now()
        meta = {"frames": self.frames, "cams": self.cams, "dur": dur, "marks": self.marks, "slow": self.slow, "view": self.view}
        (self.dir / "meta.json").write_text(json.dumps(meta))
        fps = len(self.frames) / max(dur, 1e-6)
        print(f"  shot {self.name}: {dur:.1f} s page time, {len(self.frames)} frames ({fps:.0f} fps)"
              + ("  <- low: raise --slow" if fps < 24 else ""))

    def cam(self, rect=None, over=0.9):
        """Punch in to rect = (x, y, w) in CSS px (16:9, w <= viewport width), or back out (None), over `over` s."""
        self.cams.append((self.now(), rect, over))

    async def cam_on(self, sel, w=None, over=0.9, top=False, pad=24):
        """Punch in on an element: a 16:9 window w CSS px wide (default: just wide enough), centred on it, or at its
        top edge with top=True, kept inside the viewport."""
        x, y, ew, eh = await self.pg.evaluate("""s => { const r = document.querySelector(s).getBoundingClientRect();
          return [r.left, r.top, r.width, r.height]; }""", sel)
        V = self.view
        w = min(V[0], max(560.0, w or max(ew + 2 * pad, (eh + 2 * pad) * 16 / 9)))
        h = w * 9 / 16
        cx = min(max(0.0, x + ew / 2 - w / 2), V[0] - w)
        cy = min(max(0.0, (y - pad) if top else (y + eh / 2 - h / 2)), V[1] - h)
        self.cam((cx, cy, w), over)

    def mark(self, k):
        self.marks[k] = self.now()

    async def say(self, title, sub=""):
        await self.pg.evaluate("""([t, s]) => { let o = document.getElementById('vidtx');
          if (!o) { o = document.createElement('div'); o.id = 'vidtx'; document.body.appendChild(o); }
          o.innerHTML = t ? `<b>${t}</b>${s ? `<small>${s}</small>` : ''}` : ''; o.classList.toggle('on', !!t); }""",
                               [title, sub])


async def new_page(browser, slow, dpr, url=None, extra_ctx=None, view=VIEW, mobile=False):
    ctx = await browser.new_context(viewport={"width": view[0], "height": view[1]}, device_scale_factor=dpr,
                                    is_mobile=mobile, has_touch=mobile, **(extra_ctx or {}))
    await ctx.add_init_script(CLOCK_SHIM % {"slow": slow})
    await ctx.add_init_script("document.addEventListener('DOMContentLoaded', () => { const s = document.createElement('style');"
                              f" s.textContent = {json.dumps(OVERLAY_CSS)}; document.head.appendChild(s); }});")
    pg = await ctx.new_page()
    cdp = await ctx.new_cdp_session(pg)
    # Playwright's device_scale_factor does not reach CDP screenshots here (they came back 1x): set it on the target
    await cdp.send("Emulation.setDeviceMetricsOverride", {"width": view[0], "height": view[1], "deviceScaleFactor": dpr,
                                                          "mobile": mobile})
    await cdp.send("Animation.enable")
    await cdp.send("Animation.setPlaybackRate", {"playbackRate": 1 / slow})
    if url:
        await pg.goto(url)
    return ctx, pg, cdp


def app_url(base, path, source, q=None):
    u = f"{base}/?tab={source}&path={urllib.parse.quote(path)}"
    return u + (f"&q={urllib.parse.quote(q)}" if q else "")


async def wait_js(pg, expr, timeout_s=180):
    await pg.wait_for_function(expr, timeout=timeout_s * 1000, polling=100)


ANSWERED = "(q => typeof res !== 'undefined' && res && res.question === q && !animating)"


async def type_and_ask(rec, q, wait=True):
    """Types the question into the ask box (on the page clock) and asks, like the demo tour does."""
    await rec.pg.evaluate("""async q => { const el = document.querySelector('#q'); el.value = ''; el.focus();
      const dt = Math.max(12, Math.min(40, 1400 / q.length));
      for (const ch of q) { el.value += ch; await new Promise(r => setTimeout(r, dt)); } }""", q)
    await rec.sleep(0.25)
    await rec.pg.evaluate("ask()")
    if wait:
        await wait_js(rec.pg, f"{ANSWERED}({json.dumps(q)})")


async def wait_ready(pg):
    await pg.wait_for_load_state("networkidle")
    await pg.evaluate("document.fonts.ready")


# ---- the shots. Each gets a fresh page and a Rec; they mirror the storyboard in docs/video.md.

async def shot_hook(rec, base):
    """Flat plan seen from above -> walls rise -> the 20 counted doors light up one by one, numbered."""
    pg = rec.pg
    await wait_js(pg, f"{ANSWERED}({json.dumps(Q_DOORS)})")
    await wait_js(pg, "window.__p3 && document.querySelector('#p3go')")
    await pg.evaluate("document.body.classList.add('vidhero')")
    await asyncio.sleep(1.0)                      # layout settles; geometry was prefetched by plan3d.js
    await rec.start()
    await rec.sleep(0.3)
    await pg.evaluate("window.__p3riseMs = 2600; window.__p3.open()")
    await wait_js(pg, "window.__p3.ready")
    rec.mark("risen")
    await rec.sleep(1.3)                           # doors pop in (~0.9 s on the page clock)
    await rec.say("<em>20</em> doors · every one numbered", "read from the CAD layers · no AI model call · $0")
    await rec.sleep(2.2)
    await rec.say("Blueprints <em>That Talk</em>", "Junction 2026 · Stoa: Make Blueprints Talk")
    await rec.sleep(2.0)
    await rec.stop()


async def shot_how(rec, base):
    pg = rec.pg
    await wait_ready(pg)
    await rec.start()
    await rec.sleep(1.2)
    await pg.evaluate("window.scrollTo({top: document.querySelector('#route').offsetTop - 40, behavior: 'smooth'})")
    await rec.sleep(2.5)
    await pg.evaluate("window.scrollTo({top: scrollY + innerHeight * 0.7, behavior: 'smooth'})")
    await rec.sleep(2.5)
    await pg.evaluate("window.scrollTo({top: scrollY + innerHeight * 0.7, behavior: 'smooth'})")
    await rec.sleep(2.5)
    await rec.stop()


async def shot_xray(rec, base):
    pg = rec.pg
    await wait_ready(pg)
    await rec.start()
    await rec.sleep(0.3)
    await type_and_ask(rec, Q_DOORS, wait=False)
    await wait_js(pg, "typeof animating !== 'undefined' && animating")
    await rec.cam_on("#viewer", 960, 0.8)          # punch in on the drawing while the count runs
    await wait_js(pg, f"{ANSWERED}({json.dumps(Q_DOORS)})")
    await rec.sleep(0.8)
    await rec.cam_on("#answer", 720, 0.9, top=True)  # then over to the answer card: 20, "two methods agree"
    await rec.sleep(3.2)
    rec.cam(None, 0.8)
    await rec.sleep(1.0)
    await rec.stop()


async def shot_ghost(rec, base):
    pg = rec.pg
    await wait_ready(pg)
    await rec.start()
    await rec.sleep(0.3)
    await type_and_ask(rec, Q_AREA_DE)
    await pg.evaluate("rowHot(0, true, true); hotItem(0, true)")
    await rec.sleep(1.4)
    await pg.evaluate("rowHot(0, false); hotItem(0, false)")
    await pg.evaluate("doAction('scroll:.vs')")
    await rec.sleep(1.0)
    await rec.cam_on("#answer .ghostcmp", 640, 1.0)
    await rec.say("5 frontier models · same drawing · <em>all 5 wrong</em>", "dataset answer 62.74 m² · they said 59 to 75 m²")
    await rec.sleep(4.0)
    await rec.say("")
    rec.cam(None, 0.8)
    await rec.sleep(0.9)
    await rec.stop()


async def shot_correct(rec, base):
    pg = rec.pg
    await wait_js(pg, f"{ANSWERED}({json.dumps(Q_WINDOWS)})")
    await rec.start()
    await rec.sleep(0.6)
    await rec.cam_on("#side", 1100, 0.8, top=True)
    await rec.sleep(0.8)
    await pg.evaluate("doAction('toggle:3')")
    await rec.sleep(2.2)
    rec.cam(None, 0.8)
    await rec.sleep(1.0)
    await rec.stop()


async def shot_heat(rec, base):
    pg = rec.pg
    # the view menu's "Room heat-map" and "Takeoff sheet" items call these two app functions
    await wait_js(pg, "typeof cur !== 'undefined' && cur && document.querySelector('#img').naturalWidth > 0")
    await rec.start()
    await rec.sleep(0.6)
    await pg.evaluate("setHeat(true)")
    await rec.sleep(3.4)
    await pg.evaluate("openSheet()")
    await rec.sleep(3.4)
    await rec.stop()


# the voice strip's states (Listening -> Transcribing -> Asking), then the question is asked as text
STAGE_VOICE = """async q => {
          const s = document.querySelector('#voice'), m = document.querySelector('#mic'), w = ms => new Promise(r => setTimeout(r, ms));
          const st = (state, msg) => { s.hidden = false; s.dataset.state = state; m.classList.toggle('on', state === 'listening');
            s.querySelector('.vstate').textContent = msg; s.querySelector('.vstop').hidden = state !== 'listening'; };
          st('listening', 'Listening'); s.querySelector('.vfin').textContent = ''; s.querySelector('.vint').textContent = 'Listening… stops when you pause';
          await w(1500); st('transcribing', 'Transcribing'); s.querySelector('.vint').textContent = 'Turning speech into text…';
          await w(700); st('asking', 'Asking'); s.querySelector('.vfin').textContent = q; s.querySelector('.vint').textContent = '';
          document.querySelector('#q').value = q; await w(500); s.hidden = true; m.classList.remove('on'); ask(); }"""


async def shot_voice(rec, base, wav=None):
    """With --voice-wav, Chromium's fake microphone plays that file into the real voice flow (ElevenLabs STT on
    the server). Without it the voice strip is staged with the same states the app shows, then the question is
    asked as typed text: say so if the cut is used publicly."""
    pg = rec.pg
    await wait_ready(pg)
    await wait_js(pg, "document.querySelector('#mic')", 30)
    await rec.start()
    await rec.sleep(0.5)
    await rec.cam_on(".ask", 900, 0.8, top=True)
    if wav:
        await pg.click("#mic")
        await wait_js(pg, "typeof res !== 'undefined' && res && !animating", 120)
    else:
        await pg.evaluate(STAGE_VOICE, Q_DOORS_FI)
        await wait_js(pg, f"{ANSWERED}({json.dumps(Q_DOORS_FI)})")
    await rec.sleep(0.5)
    await rec.cam_on("#viewer", 1000, 0.9)         # over to the boxed doors on the scan
    await rec.sleep(3.0)
    rec.cam(None, 0.8)
    await rec.sleep(0.8)
    await rec.stop()


async def shot_ifc(rec, base):
    pg = rec.pg
    await wait_js(pg, f"{ANSWERED}({json.dumps(Q_IFC_WALLS)})", 240)
    await rec.start()
    await rec.sleep(0.4)
    await pg.evaluate("setMode('3d')")
    await wait_js(pg, "document.querySelector('#three .v3bar button')", 240)
    await rec.sleep(2.0)
    btn = "(re => { const b = [...document.querySelectorAll('#three .v3bar button')].find(b => !b.hidden && re.test(b.textContent)); if (b) b.click(); return !!b; })"
    await pg.evaluate(btn + "(/explode/i)")                                       # Explode storeys
    await rec.sleep(2.2)
    await pg.evaluate(btn + "(/x-ray/i)")                                         # X-ray
    await rec.sleep(1.2)
    # a slow orbit by dragging the canvas (OrbitControls), on the page clock
    vx = await pg.evaluate("(() => { const r = document.querySelector('#viewer').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
    await pg.mouse.move(vx[0], vx[1])
    await pg.mouse.down()
    for k in range(40):
        await pg.mouse.move(vx[0] - 6 * k, vx[1] + 0.6 * k)
        await rec.sleep(0.05)
    await pg.mouse.up()
    await rec.sleep(1.5)
    await rec.stop()


PHONE_VIEW, PHONE_DPR = (390, 844), 3.0


async def shot_phone(rec, base):
    """Phone take (390x844 CSS at DPR 3), for an inset: a Finnish voice question on the Swiss door plan (staged
    strip, as shot_voice), the answer as a bottom sheet, then the in-context card on pin #3."""
    pg = rec.pg
    await wait_ready(pg)
    await wait_js(pg, "typeof cur !== 'undefined' && cur && document.querySelector('#img').naturalWidth > 0", 60)
    await rec.start()
    await rec.sleep(0.8)
    has_mic = await pg.evaluate("!!document.querySelector('#mic')")
    q = "Kuinka monta ovea tässä pohjapiirustuksessa on?"
    if has_mic:
        await pg.evaluate(STAGE_VOICE, q)
    else:
        await type_and_ask(rec, q, wait=False)
    await wait_js(pg, f"{ANSWERED}({json.dumps(q)})")
    await rec.sleep(1.6)
    await pg.evaluate("sheetFull(true)")
    await rec.sleep(2.2)
    await pg.evaluate("sheetFull(false)")
    await rec.sleep(1.0)
    await pg.evaluate("selectPin(2)")
    await rec.sleep(2.6)
    await pg.evaluate("selectPin(9)")
    await rec.sleep(2.4)
    await rec.stop()


SHOTS = {
    "hook": (shot_hook, lambda b: app_url(b, SWISS_DOORS, "swiss_dwellings", Q_DOORS)),
    "how": (shot_how, lambda b: f"{b}/how"),
    "xray": (shot_xray, lambda b: app_url(b, SWISS_DOORS, "swiss_dwellings")),
    "ghost": (shot_ghost, lambda b: app_url(b, SWISS_AREA, "swiss_dwellings")),
    "correct": (shot_correct, lambda b: app_url(b, SWISS_DOORS, "swiss_dwellings", Q_WINDOWS)),
    "heat": (shot_heat, lambda b: app_url(b, SWISS_AREA, "swiss_dwellings")),
    "voice": (shot_voice, lambda b: app_url(b, CUBI, "cubicasa5k")),
    "ifc": (shot_ifc, lambda b: app_url(b, IFC_PLAN, "ifc_models", Q_IFC_WALLS)),
    "phone": (shot_phone, lambda b: app_url(b, SWISS_DOORS, "swiss_dwellings")),
}


async def card_shot(rec, base):
    await wait_ready(rec.pg)
    await rec.start()
    await rec.sleep(6.0)                              # bars grow over ~2 s; a long hold to cut from
    await rec.stop(0)


GL_ARGS = ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader"]
GPU_ARGS = ["--use-angle=vulkan", "--enable-features=Vulkan", "--enable-gpu", "--ignore-gpu-blocklist"]


async def record(names, base, slow, dpr, gpu, voice_wav=None):
    from playwright.async_api import async_playwright
    args = (GPU_ARGS if gpu else GL_ARGS) + ["--autoplay-policy=no-user-gesture-required"]
    if voice_wav:
        args += ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                 f"--use-file-for-fake-audio-capture={Path(voice_wav).resolve()}%noloop"]
    cards = (WORK / "cards.html").resolve().as_uri()
    async with async_playwright() as p:
        b = await p.chromium.launch(args=args)
        probe = await b.new_page()
        await probe.goto("about:blank")
        gl = await probe.evaluate("""() => { const g = document.createElement('canvas').getContext('webgl');
          const e = g && g.getExtension('WEBGL_debug_renderer_info'); return g ? (e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : 'webgl') : 'none'; }""")
        print(f"WebGL renderer: {gl}")
        await probe.close()
        await b.close()
        for name in names:
            if name in SHOTS:
                fn, url = SHOTS[name]
                url = url(base)
            else:
                fn, url = card_shot, f"{cards}?card={name}"
            # a fresh browser per shot: after the heavy IFC scene SwiftShader's GPU process could refuse screenshots
            b = await p.chromium.launch(args=args)
            phone = name == "phone"
            ctx, pg, cdp = await new_page(b, slow, PHONE_DPR if phone else dpr, url,
                                          {"permissions": ["microphone"]} if voice_wav else None,
                                          PHONE_VIEW if phone else VIEW, phone)
            rec = Rec(pg, cdp, slow, name, PHONE_VIEW if phone else VIEW)
            t = time.time()
            try:
                await (fn(rec, base, voice_wav) if name == "voice" else fn(rec, base))
            except Exception as e:
                print(f"  shot {name} failed: {e}")
                if rec.task:
                    rec.on = False
                    try:
                        await rec.task
                    except Exception:
                        pass
                    (rec.dir / "meta.json").write_text(json.dumps(
                        {"frames": rec.frames, "cams": rec.cams, "dur": rec.now(), "marks": rec.marks, "slow": slow,
                         "view": rec.view}))
            print(f"  ({time.time() - t:.0f} s wall)")
            await ctx.close()
        await b.close()


# ---------------------------------------------------------------- frames -> clip

def _ease(k):
    return k * k * (3 - 2 * k)


def cam_at(cams, t, full):  # punch-ins keep 16:9 (the desktop shots); the phone take never punches in
    """Crop rect (x, y, w, h) in CSS px at page time t; cams = [(t, rect | None, over)]."""
    cur = full
    for i, (t0, rect, over) in enumerate(cams):
        if t0 > t:
            break
        tgt = full if rect is None else (rect[0], rect[1], rect[2], rect[2] * 9 / 16)
        k = 1.0 if over <= 0 else _ease(min(1.0, (t - t0) / over))
        cur = tuple(a + (b - a) * k for a, b in zip(cur, tgt))
    return cur


def frames_clip(name, dur, out, dpr, size=(1920, 1080)):
    """Resample a shot's frames to FPS over exactly `dur` s: played at real speed if it fits, sped up (to at most
    1.6x) when the recording is longer, then trimmed; held on its last frame when it is shorter."""
    from PIL import Image
    d = WORK / f"shot-{name}"
    meta = json.loads((d / "meta.json").read_text())
    frames, cams, have = meta["frames"], meta["cams"], meta["dur"]
    if not frames:
        raise SystemExit(f"shot {name}: no frames recorded")
    speed = min(1.6, have / dur) if have > dur else 1.0
    V = meta.get("view", VIEW)
    full = (0.0, 0.0, float(V[0]), float(V[1]))
    W, H = size
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                          "-crf", "16", "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    j, last, cache = 0, None, {}
    for n in range(int(round(dur * FPS))):
        t = min(n / FPS * speed, frames[-1][0])
        while j + 1 < len(frames) and frames[j + 1][0] <= t:
            j += 1
        x, y, w, h = cam_at(cams, t, full)
        key = (frames[j][1], round(x, 1), round(y, 1), round(w, 1))
        if key != last:
            im = cache.get(frames[j][1]) or Image.open(d / frames[j][1]).convert("RGB")
            cache = {frames[j][1]: im}
            s = im.width / V[0]
            buf = im.resize((W, H), Image.LANCZOS, box=(x * s, y * s, (x + w) * s, (y + h) * s)).tobytes()
            last = key
        p.stdin.write(buf)
    p.stdin.close()
    p.wait()
    return have, speed


# ---------------------------------------------------------------- cards

CARD_CSS = """
:root { --ink:#0f172a; --ink2:#475569; --muted:#94a3b8; --ours:#2563eb; --frontier:#e8590c; --navy:#0b1220; }
* { box-sizing: border-box; }
html, body { margin:0; width:1536px; height:864px; overflow:hidden; }
body { font-family: Inter, "Helvetica Neue", Arial, "DejaVu Sans", sans-serif; color:var(--ink); }
.card { width:1920px; height:1080px; transform: scale(.8); transform-origin: 0 0; position:relative; overflow:hidden;
  background:#fff; padding:110px 120px; display:none; }
.card.on { display:flex; flex-direction:column; justify-content:center; padding-bottom:150px; }
.dark { background:var(--navy); color:#fff; }
.kicker { font-size:26px; font-weight:700; letter-spacing:.14em; text-transform:uppercase; color:var(--ours); margin-bottom:22px; }
.dark .kicker { color:#60a5fa; }
h1 { font-size:128px; line-height:1.02; font-weight:800; letter-spacing:-0.03em; margin:0 0 30px; }
h1 span { color:#60a5fa; }
h2 { font-size:64px; line-height:1.08; font-weight:800; letter-spacing:-0.02em; margin:0 0 50px; max-width:1640px; }
.foot { position:absolute; left:120px; right:120px; bottom:40px; font-size:20px; line-height:1.45; color:var(--muted); }
.bars { display:grid; grid-template-columns: 560px 1fr; gap:26px 30px; align-items:center; font-size:34px; }
.bar { height:74px; background:#f1f5f9; border-radius:8px; position:relative; }
.bar i { position:absolute; left:0; top:0; bottom:0; border-radius:8px; background:var(--frontier);
  transform-origin: 0 50%; animation: grow 1.4s cubic-bezier(.2,.7,.2,1) both; }
.bar.ours i { background:var(--ours); }
.bar em { position:absolute; top:50%; transform:translateY(-50%); font-style:normal; font-weight:800; font-size:40px; padding-left:18px;
  animation: fade .5s ease both; }
.lab { color:var(--ink2); line-height:1.2; } .lab b { color:var(--ink); }
@keyframes grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@keyframes fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes rise { from { opacity: 0; transform: translateY(24px); } to { opacity: 1; transform: none; } }
.in { animation: rise .7s ease both; }
.cost { display:flex; gap:60px; align-items:stretch; margin-top:30px; }
.cost .box { flex:1; border-radius:18px; padding:50px 56px; background:#f8fafc; }
.cost .box .n { font-size:150px; font-weight:800; letter-spacing:-0.04em; line-height:1; }
.cost .box .l { font-size:34px; color:var(--ink2); margin-top:22px; line-height:1.3; }
.cost .ours .n { color:var(--ours); } .cost .fr .n { color:var(--frontier); }
.end .meta { font-size:38px; color:#cbd5e1; line-height:1.6; margin-top:40px; }
.end .meta code { font-family:"DejaVu Sans Mono", monospace; color:#fff; font-size:38px; }
.end .foot { color:#94a3b8; font-size:22px; }
"""


def bar(label, acc, k, ours=False):
    d = 0.5 + 0.35 * k
    return (f'<div class="lab in" style="animation-delay:{d - .2:.2f}s">{label}</div><div class="bar{" ours" if ours else ""}">'
            f'<i style="width:{acc * 0.8:.1f}%;animation-delay:{d:.2f}s"></i>'
            f'<em style="left:{acc * 0.8:.1f}%;animation-delay:{d + 1.1:.2f}s">{acc:.1f}&nbsp;%</em></div>')


def cards_html():
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CARD_CSS}</style></head><body>
<section class="card" id="problem">
  <div class="kicker">Measured, not assumed</div>
  <h2 class="in">Frontier models get about 7 answers in 10 right, and sound just as sure when they are wrong.</h2>
  <div class="bars">
    {bar("<b>Claude Sonnet 5.5</b><br>drawing + its CAD / IFC files", 69.8, 0)}
    {bar("<b>Gemini 3.1 Pro</b><br>drawing only", 64.2, 1)}
    {bar("<b>Claude Sonnet 5.5</b><br>drawing only", 63.2, 2)}
  </div>
  <div class="foot">Accuracy on a 400-question sample of our held-out test split, stratified by source × question type and re-weighted to the
  full test-split mix (95 % CI about ±9 pp). Counts must be exact, measurements within 2 %. Source: docs/RESULTS.md.</div>
</section>
<section class="card" id="results">
  <div class="kicker">Results · held-out test split</div>
  <h2 class="in">90.0&nbsp;% right on all 25,420 held-out test questions.</h2>
  <div class="bars">
    {bar("<b>Blueprints That Talk</b><br>every test question", 90.0, 0, True)}
    {bar("<b>Claude Sonnet 5.5</b><br>same drawing + CAD / IFC files", 69.8, 1)}
    {bar("<b>Gemini 3.1 Pro</b><br>drawing only", 64.2, 2)}
  </div>
  <div class="foot">Ours: all 25,420 test questions, 95 % CI 89.7–90.4 %; frontier: 400-question stratified sample re-weighted to the test mix.
  Swiss CAD plans and IFC quantities 100 %, Finnish raster plans 85.1 %, IFC free text 38.2 %. Evaluation cross-audited for leakage.
  Sources: README.md, docs/RESULTS.md, runs/router_full_test_v7.</div>
</section>
<section class="card" id="cost">
  <div class="kicker">API cost per 1,000 questions</div>
  <h2 class="in">Exact answers don't need a giant model.</h2>
  <div class="cost">
    <div class="box ours in" style="animation-delay:.4s"><div class="n">$0.013</div><div class="l"><b>Blueprints That Talk</b><br>numbers come from geometry and a small detector; only free text calls a small LLM</div></div>
    <div class="box fr in" style="animation-delay:1.1s"><div class="n">$25.76</div><div class="l"><b>Claude Sonnet 5.5</b><br>given the same drawing and its CAD / IFC files, at API list price</div></div>
  </div>
  <p class="in" style="font-size:40px; color:var(--ink2); margin-top:60px; animation-delay:1.8s">About <b style="color:var(--ink)">1,900 times cheaper</b>, and 0.04&nbsp;s per answer instead of 16&nbsp;s.</p>
  <div class="foot">API list prices, measured; local compute adds about $0.006 per 1,000. Source: README.md, docs/COSTS.md.</div>
</section>
<section class="card dark end" id="end">
  <div class="kicker in">Built at Junction 2026 · Stoa: Make Blueprints Talk</div>
  <h1 class="in" style="animation-delay:.3s">Blueprints <span>That Talk</span></h1>
  <div class="meta in" style="animation-delay:.8s">Exact · verifiable · cheap<br><code>{REPO_URL}</code></div>
  <div class="foot">{html.escape(CREDITS)}.<br>Training compute: a local RTX 4070 and cloud GPUs (Verda). Voice: {"Kokoro-82M (Apache-2.0), generated locally" if ENGINE == "kokoro" else "ElevenLabs"}.</div>
</section>
<script>
document.getElementById(new URLSearchParams(location.search).get('card')).classList.add('on');
</script></body></html>"""


# ---------------------------------------------------------------- build

def update_doc(plan, caps, total, cut):
    doc = ROOT / "docs/video.md"
    rows, k = [], 0
    for i, (s, t0, dur) in enumerate(plan):
        n = len(lines_of(s, cut))
        text = " ".join(c[2] for c in caps[k:k + n]) or "(silent)"
        k += n
        rows.append(f"| {i + 1} | {int(t0 // 60)}:{t0 % 60:05.2f}–{int((t0 + dur) // 60)}:{(t0 + dur) % 60:05.2f} | "
                    f"{s['kind']} `{s['id']}` | {text} |")
    words = sum(len(c[2].split()) for c in caps)
    table = ("| # | time | shot | voice-over (caption text) |\n|---|---|---|---|\n" + "\n".join(rows) +
             f"\n\nTotal {total:.2f} s; {words} words; voice {ENGINE}"
             + (f" `{VOICE}` at speed {SPEED}" if ENGINE == "kokoro" else f" `{ELEVEN_VOICE}`") + ". Generated by `make_video.py`.")
    tag = "TIMING" if cut == "full" else "TIMING60"
    src = doc.read_text()
    new = re.sub(rf"(<!-- {tag} -->\n).*?(<!-- /{tag} -->)", lambda m: m.group(1) + table + "\n" + m.group(2), src, flags=re.S)
    doc.write_text(new)


def ff(*a):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, a)], check=True)


def probe_dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:3123")
    ap.add_argument("--cut", choices=["full", "short"], default="full")
    ap.add_argument("--only", help="comma-separated scene ids (e.g. hook): render just those, voice included")
    ap.add_argument("--out", help="output mp4 (default runs/video/blueprints-<cut>.mp4)")
    ap.add_argument("--reuse", action="store_true", help="re-cut from the shots recorded last time")
    ap.add_argument("--voice-only", action="store_true", help="only synthesize and print the timing")
    ap.add_argument("--tts", choices=["kokoro", "elevenlabs", "auto"], default="kokoro")
    ap.add_argument("--slow", type=float, default=8.0, help="page-clock slow-motion factor while recording")
    ap.add_argument("--dpr", type=float, default=2.5, help="device pixels per CSS px (2.5 = 3840x2160 captures)")
    ap.add_argument("--draft", action="store_true", help="--dpr 1.25 --slow 4: quick, no sharp punch-ins")
    ap.add_argument("--gpu", action="store_true", help="try Chromium's GPU path (needs NVIDIA graphics libs in the container)")
    ap.add_argument("--phone", action="store_true",
                    help="only record the phone take -> runs/video/phone-inset.mp4 (1080x2336, no voice), for an inset")
    ap.add_argument("--voice-wav", help="a recorded (Finnish) question: played into the real mic flow of the voice shot")
    a = ap.parse_args()
    if a.draft:
        a.dpr, a.slow = 1.25, 4.0
    os.chdir(ROOT)
    if a.phone:
        WORK.mkdir(parents=True, exist_ok=True)
        if not a.reuse:
            asyncio.run(record(["phone"], a.url.rstrip("/"), a.slow, a.dpr, a.gpu))
        dur = json.loads((WORK / "shot-phone/meta.json").read_text())["dur"]
        out = Path(a.out) if a.out else OUT / "phone-inset.mp4"
        frames_clip("phone", round(dur, 2), out, PHONE_DPR, (1080, 2336))
        print(f"{out}: {probe_dur(out):.2f} s")
        return

    pick_engine(a.tts)
    scenes = scenes_of(a.cut)
    synthesize(scenes, a.cut)
    plan, caps, total = timeline(scenes, a.cut)
    for s, t0, dur in plan:
        print(f"{t0:6.2f}  {dur:5.2f}  {s['kind']:5s} {s['id']}")
    print(f"total {total:.2f} s ({a.cut} cut)")
    if not a.only:
        update_doc(plan, caps, total, a.cut)
        if total > LIMIT[a.cut]:
            sys.exit(f"too long: {total:.2f} s > {LIMIT[a.cut]} s; shorten the lines or raise SPEED")
    if a.voice_only:
        return

    only = set(a.only.split(",")) if a.only else None
    plan = [x for x in plan if not only or x[0]["id"] in only]
    if not plan:
        sys.exit("--only matched no scene of this cut")
    t_first = plan[0][1]
    caps = [c for c in caps if any(t0 <= c[0] < t0 + d for _, t0, d in plan)]
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "cards.html").write_text(cards_html(), encoding="utf-8")
    if not a.reuse:
        asyncio.run(record([s["id"] for s, _, _ in plan], a.url.rstrip("/"), a.slow, a.dpr, a.gpu, a.voice_wav))

    clips, t = [], 0.0
    for i, (s, t0, dur) in enumerate(plan):
        c = WORK / f"scene-{s['id']}.mp4"
        have, speed = frames_clip(s["id"], dur, c, a.dpr)
        print(f"scene {s['id']}: recorded {have:.1f} s -> {dur:.2f} s (x{speed:.2f})")
        clips.append(c)
    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    silent = WORK / "picture.mp4"
    ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", silent)

    span = sum(d for _, _, d in plan)
    # with --only, the captions/voice are shifted to the first chosen scene (scenes are contiguous in the usual case)
    shift = [(c[0] - t_first, c[1] - t_first, c[2], c[3]) for c in caps]
    voice = WORK / "voice.wav"
    write_voice(shift, span, voice)
    out = Path(a.out) if a.out else OUT / f"blueprints-{a.cut}.mp4"
    srt = out.with_suffix(".srt")
    write_srt(shift, srt)
    style = ("FontName=DejaVu Sans,FontSize=13,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,"
             "Outline=0,Shadow=0,Alignment=2,MarginV=10,MarginL=40,MarginR=40")
    ff("-i", silent, "-i", voice,
       "-vf", f"scale=1632:918:flags=lanczos,pad=1920:1080:144:0:color=0x0b1220,subtitles={srt}:force_style='{style}'",
       "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000",
       "-c:v", "libx264", "-preset", "slow", "-crf", 18, "-pix_fmt", "yuv420p", "-r", FPS,
       "-c:a", "aac", "-b:a", "192k", "-ac", 2, "-t", f"{span:.3f}", "-movflags", "+faststart", out)
    print(f"{out}: {probe_dur(out):.2f} s, {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    if "--tts-worker" in sys.argv:
        tts_worker()
    else:
        main()
