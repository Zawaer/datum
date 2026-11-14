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

# A line is L(speaker, caption, spoken): A / B are the two narrators (see VOICE_SET). The spoken form spells numbers
# out and may carry v3 audio tags ([confident], ...), dropped for other models; the caption is the plain text.
# Sources for every number: README.md, docs/RESULTS.md, docs/COSTS.md (listed in docs/video.md).
# "cuts": which cut a scene is in; "short": the lines it speaks in the 60 s cut (default: the same lines).


def L(spk, cap, say=None):
    return (spk, cap, say or cap)


FI_Q = L("F", "Kuinka monta ovea pohjapiirustuksessa on?", "[curious] Kuinka monta ovea pohjapiirustuksessa on?")

SCENES = [
    {"id": "hook", "kind": "shot", "cuts": "full short", "min": 8.5, "lines": [  # min: room for both chips
        L("A", "Ask a floor plan how many doors it has.", "[confident] Ask a floor plan how many doors it has."),
        L("B", "Twenty. And here is every single one.", "Twenty. And here's every single one."),
    ]},
    {"id": "problem", "kind": "card", "cuts": "full short", "lines": [
        L("B", "Takeoffs are still counted by hand.", "Takeoffs are still counted by hand."),
        L("A", "And general AI, given the very same files? Seven answers in ten,",
          "[leaning in] And general A.I., given the very same files? Seven answers in ten."),
        L("A", "and just as sure when it's wrong.", "[serious] And just as sure when it's wrong."),
    ], "short": [
        L("A", "General AI gets seven answers in ten right, and is just as sure when it's wrong.",
          "[leaning in] General A.I. gets seven answers in ten right. [serious] And it's just as sure when it's wrong."),
    ]},
    {"id": "ghost", "kind": "shot", "cuts": "full short", "lines": [
        L("A", "Datum shows its work. Ask, in German, for the living area,",
          "[confident] Datum shows its work. Ask, in German, for the living area,"),
        L("B", "and every room is outlined with its square metres, adding up on the drawing.",
          "and every room is outlined with its square metres, adding up on the drawing."),
        L("A", "Five AI models, same drawing: all five wrong.",
          "Five A.I. models, same drawing. [chuckles] All five wrong."),
    ], "short": [
        L("A", "Datum shows its work. Ask, in German, for the living area:",
          "[confident] Datum shows its work. Ask, in German, for the living area,"),
        L("B", "every room outlined, adding up on the drawing. Five AI models: all five wrong.",
          "and every room is outlined, adding up on the drawing. Five A.I. models? All five wrong."),
    ]},
    {"id": "xray", "kind": "shot", "cuts": "", "lines": [   # out of the 2:00 cut since the project beat
        L("A", "Every answer shows its proof: the X-ray counts each door,",
          "[confident] Every answer shows its proof. The X-ray counts each door,"),
        L("B", "and a second, independent method agrees.", "and a second, independent method agrees."),
    ]},
    {"id": "correct", "kind": "shot", "cuts": "full", "lines": [
        L("B", "Check it in seconds: untick one, or click one in. The total follows.",
          "Check it in seconds. Untick one, or click one in. The total follows."),
    ]},
    {"id": "voice", "kind": "shot", "cuts": "full short", "lines": [
        L("A", "On site? Just ask out loud, in Finnish.", "[leaning in] On site? Just ask out loud. In Finnish."),
        FI_Q,
        L("B", "Every door is boxed on the scan, and the plan rises into 3D.",
          "Every door is boxed on the scan, and the plan rises into 3D."),
    ], "short": [
        L("A", "Or ask out loud, in Finnish.", "[leaning in] Or ask out loud. In Finnish."),
        FI_Q,
    ]},
    {"id": "ifc", "kind": "shot", "cuts": "full", "lines": [
        L("A", "From a BIM model, the answer comes from the model itself.",
          "[confident] From a BIM model, the answer comes from the model itself."),
        L("B", "Explode the storeys, and the evidence glows.", "Explode the storeys, and the evidence glows."),
    ]},
    {"id": "sheet", "kind": "shot", "cuts": "full short", "min": 16.0, "min_short": 8.5, "lines": [
        L("B", "And a sheet it has never seen? Here's a school plan, uploaded.",
          "And a sheet it has never seen? Here's a school plan, uploaded."),
        L("A", "Upload it, ask, and watch it count the group rooms on the drawing.",
          "[confident] Upload it, ask, and watch it count the group rooms, right on the drawing."),
        L("B", "Then tilt it up into 3D.", "Then tilt it up into 3D."),
    ], "short": [
        L("B", "And a school sheet it has never seen: upload, ask, watch it count.",
          "And a school sheet it has never seen? Upload, ask, and watch it count."),
    ]},
    {"id": "project", "kind": "shot", "cuts": "full", "min": 9.5, "lines": [
        L("A", "A whole project? Drop in both floors and ask for every door in the school.",
          "[leaning in] And the whole project? Drop in both floors, and ask for every door in the school."),
        L("B", "171, floor by floor. Tap one to see its doors.",
          "One hundred seventy-one, floor by floor. Tap one to see its doors."),
    ]},
    {"id": "results", "kind": "card", "cuts": "full short", "lines": [
        L("A", "90.7 % right on all 25,420 held-out test questions.",
          "[confident] Ninety point seven percent right, on all twenty-five thousand held-out questions."),
        L("B", "A leading AI model, given the same files: 69.8 %.",
          "A leading A.I. model, given the same files: sixty-nine point eight."),
    ], "short": [
        L("A", "90.7 % right on all 25,420 held-out test questions.",
          "[confident] Ninety point seven percent right, on all twenty-five thousand held-out questions."),
    ]},
    {"id": "cost", "kind": "card", "cuts": "full short", "lines": [
        L("A", "$0.013 per 1,000 questions.", "[persuasive] At one point three cents per thousand questions."),
        L("B", "The AI model: $25.76.", "The A.I. model? Twenty-five dollars seventy-six."),
    ], "short": [
        L("A", "$0.013 per 1,000 questions.", "[persuasive] At one point three cents per thousand questions."),
    ]},
    {"id": "end", "kind": "card", "cuts": "full short", "min": 3.5, "lines": [
        L("B", "Not sure? It says so instead of guessing. Low-res scans are its weak spot.",
          "Not sure? It says so, instead of guessing. Low-res scans are its weak spot."),
        L("A", "Exact. Verifiable. Cheap. Datum: blueprints that talk.",
          "[confident] Exact. Verifiable. Cheap. [warmly] Datum: blueprints that talk."),
    ], "short": [
        L("A", "Exact. Verifiable. Cheap. Datum: blueprints that talk.",
          "[confident] Exact. Verifiable. Cheap. [warmly] Datum: blueprints that talk."),
    ]},
]

CREDITS = ("Drawings: Swiss Dwellings v3.0.0 (Archilyse AG, CC BY 4.0) · CubiCasa5K (CubiCasa, CC BY-NC-SA 4.0) · "
           "Molio Demo-hus (buildingSMART sample files, CC BY 4.0) · DfE model special school, Level 01 (Open Government "
           "Licence v3.0) · questions from the Junction 2026 Stoa dataset")


def scenes_of(cut):
    return [s for s in SCENES if cut in s["cuts"].split()]


def lines_of(scene, cut="full"):
    """-> [(caption, spoken, speaker)]"""
    ls = scene.get("short", scene["lines"]) if cut == "short" else scene["lines"]
    return [(cap, say, spk) for spk, cap, say in ls]


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


ENGINE = "elevenlabs"
# Two narrators, A (male) and B (female), alternate the lines. Default ("premade", Toivo's decision of 14 Nov):
# ElevenLabs premade voices George and Sarah on eleven_multilingual_v2 (steadier than v3; v3 audio tags in the spoken
# text are dropped for it), with the project key (ELEVENLABS_API_KEY in data/secrets/elevenlabs.env). "cloned"
# (--voices cloned, the first take) reads Toivo's and Rene's cloned voices, keys and models from a root-only env file;
# each key speaks only its own voice. Keys only ever go into request headers, never printed.
VOICE_SET = "protege"
PREMADE = {"A": ("George", "JBFqnCBsd6RMkjVDRZzb"), "B": ("Sarah", "EXAVITQu4vr4xnSDxMaL"),
           "F": ("George", "JBFqnCBsd6RMkjVDRZzb")}   # F: the spoken Finnish question
# "protege" (Toivo's decision, 14 Nov, final): one narrator for every line, Toivo's "Protégé narrator (clone)" voice on
# his account's key (TOIVO_ELEVENLABS_KEY in VOICES_ENV); the Finnish question stays the premade George clip.
PROTEGE = ("Protégé narrator", "AesrdOgpgZSXUSHb7gw3")
PROTEGE_MODEL = os.environ.get("PROTEGE_MODEL", "eleven_multilingual_v2")
PREMADE_MODEL = "eleven_multilingual_v2"
PREMADE_SETTINGS = {"stability": 0.6, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True}
VOICES_ENV = Path("/data/attachments/s_G5o6eFRtoL/secrets/elevenlabs.env")
CLONED = {"A": ("Toivo", "TOIVO_ELEVENLABS_KEY", "TOIVO_VOICE_ID", "TOIVO_MODEL_ID"),
          "B": ("Rene", "RENE_ELEVENLABS_KEY", "RENE_VOICE_ID", "RENE_MODEL_ID"),
          "F": ("Toivo", "TOIVO_ELEVENLABS_KEY", "TOIVO_VOICE_ID", "TOIVO_MODEL_ID")}
SPEAKERS = ("A", "B", "F")
V3_STABILITY = 0.5   # eleven_v3 takes 0.0 (creative), 0.5 (natural) or 1.0 (robust); tags work in 0.0 / 0.5


def speaker_name(spk):
    if VOICE_SET == "protege":
        return PREMADE["F"][0] if spk == "F" else PROTEGE[0]
    return (PREMADE if VOICE_SET == "premade" else CLONED)[spk][0]


def read_env(path, *names):
    env = {}
    if Path(path).exists():
        for ln in Path(path).read_text().splitlines():
            k, _, v = ln.strip().partition("=")
            if k and not k.startswith("#"):
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def voice_of(spk):
    """-> (key, voice id, model, voice settings)"""
    if VOICE_SET == "protege" and spk != "F":
        key = read_env(VOICES_ENV).get("TOIVO_ELEVENLABS_KEY")
        if not key:
            raise SystemExit(f"protege voice: TOIVO_ELEVENLABS_KEY missing in {VOICES_ENV}")
        vs = PREMADE_SETTINGS if PROTEGE_MODEL != "eleven_v3" else {"stability": V3_STABILITY}
        return key, PROTEGE[1], PROTEGE_MODEL, vs
    if VOICE_SET in ("premade", "protege"):
        key = os.environ.get("ELEVENLABS_API_KEY") or read_env(ROOT / "data/secrets/elevenlabs.env").get("ELEVENLABS_API_KEY")
        if not key:
            raise SystemExit("premade voices: ELEVENLABS_API_KEY missing (env or data/secrets/elevenlabs.env)")
        return key.strip(), PREMADE[spk][1], PREMADE_MODEL, PREMADE_SETTINGS
    env = read_env(VOICES_ENV)
    name, kk, vk, mk = CLONED[spk]
    if not env.get(kk) or not env.get(vk):
        raise SystemExit(f"voice {name}: key or voice id missing in {VOICES_ENV}")
    return env[kk], env[vk], env.get(mk) or "eleven_v3", {"stability": V3_STABILITY}


def spoken(text, model):
    """eleven_v3 reads the audio tags; other models would speak them: drop them there."""
    return text if model == "eleven_v3" else re.sub(r"\s*\[[^\]]*\]\s*", " ", text).strip()


def clip_path(text, spk="A"):
    if ENGINE == "kokoro":
        tag = f"{VOICE}|{SPEED}|{text}"
    else:
        _, vid, model, vs = voice_of(spk)
        tag = (f"eleven|{vid}|{model}|{V3_STABILITY}|{text}" if model == "eleven_v3"
               else f"eleven|{vid}|{model}|{json.dumps(vs, sort_keys=True)}|{spoken(text, model)}")
    return TTS_CACHE / f"{hashlib.sha1(tag.encode()).hexdigest()[:16]}.wav"


def eleven_tts(text, spk):
    """-> 16-bit mono PCM at SR, or raises urllib.error.HTTPError. The key only ever goes into the request header."""
    key, vid, model, vs = voice_of(spk)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format=pcm_{SR}"
    body = json.dumps({"text": spoken(text, model), "model_id": model, "voice_settings": vs}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/pcm"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def trim_pcm(pcm, thr=300, keep=0.06):
    """Cut leading/trailing near-silence (v3 often pads a clip), keeping `keep` s on each side."""
    import array
    a = array.array("h", pcm)
    win = int(0.01 * SR)
    loud = [i for i in range(0, len(a), win) if max((abs(x) for x in a[i:i + win]), default=0) > thr]
    if not loud:
        return pcm
    i0 = max(0, loud[0] - int(keep * SR))
    i1 = min(len(a), loud[-1] + win + int(keep * SR))
    return a[i0:i1].tobytes()


def pick_engine(want):
    global ENGINE
    ENGINE = "kokoro" if want == "kokoro" else "elevenlabs"
    if ENGINE == "elevenlabs":
        for spk in SPEAKERS:
            voice_of(spk)     # fails early if a key or voice is missing
        print(f"voice: ElevenLabs {VOICE_SET}: {speaker_name('A')} / {speaker_name('B')} ({voice_of('A')[2]})")
    return ENGINE


def synthesize(scenes, cut):
    TTS_CACHE.mkdir(parents=True, exist_ok=True)
    todo = [{"text": say, "spk": spk, "path": str(clip_path(say, spk))} for s in scenes for _, say, spk in lines_of(s, cut)
            if not clip_path(say, spk).exists()]
    if not todo:
        return
    if ENGINE == "elevenlabs":
        for it in todo:
            pcm = trim_pcm(eleven_tts(it["text"], it["spk"]))
            with wave.open(it["path"], "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
                w.writeframes(pcm)
            print(f"tts {speaker_name(it['spk']):5s} {len(pcm) / 2 / SR:5.2f} s  {it['text'][:80]}")
        return
    env = {**os.environ, "HF_HOME": str(ROOT / "cache/tts/hf")}
    subprocess.run([str(TTS_PY), "-I", __file__, "--tts-worker"], input=json.dumps(
        {"voice": VOICE, "speed": SPEED, "items": [{"text": re.sub(r"\[[^\]]*\]\s*", "", t["text"]), "path": t["path"]}
                                                   for t in todo]}), text=True, check=True, env=env)


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
        for cap, say, spk in ls:
            d = wav_dur(clip_path(say, spk))
            caps.append((c, c + d, cap, clip_path(say, spk), spk))
            c += d + GAP
        dur = (c - GAP + TAIL - t) if ls else 0
        dur = max(dur, s.get("min_short", s.get("min", 0)) if cut == "short" else s.get("min", 0))
        dur = round(dur / fr + 0.4999) * fr
        plan.append((s, t, dur))
        t += dur
    return plan, caps, t


def write_voice(caps, total, path, t0=0.0):
    pcm = bytearray(int(total * SR) * 2)
    for a, _, _, clip, *_ in caps:
        with wave.open(str(clip)) as w:
            data = w.readframes(w.getnframes())
        i = int((a - t0) * SR) * 2
        if 0 <= i < len(pcm):
            pcm[i:i + len(data)] = data[:len(pcm) - i]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(bytes(pcm))


LUFS = -14.0


def loudnorm_2pass(wav, target):
    """A measured (two-pass, linear) loudnorm filter that brings the voice track to `target` LUFS integrated."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav), "-af",
                        f"loudnorm=I={target}:TP=-1.0:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
    return (f"loudnorm=I={target}:TP=-1.0:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,"
            "aresample=48000")


def short_caps(caps, most=54):
    """Split each line into short phrases (at punctuation, else words, <= `most` chars), timed by their length."""
    out = []
    for a, e, text, *rest in caps:
        parts, cur = [], ""
        for tok in re.split(r"(?<=[,;:?.!])\s+", text):   # only at punctuation then a space: not in 25,420 or 90.7
            for w in tok.split(" "):
                if cur and len(cur) + 1 + len(w) > most:
                    parts.append(cur.strip())
                    cur = ""
                cur += (" " if cur else "") + w
            if len(cur.strip()) > 18 and re.search(r"[,;:?.!]$", cur.strip()):
                parts.append(cur.strip())
                cur = ""
        if cur.strip():
            parts.append(cur.strip())
        parts = [re.sub(r"\s+", " ", p) for p in parts]
        tot = sum(len(p) for p in parts) or 1
        t = a
        for p in parts:
            d = (e - a) * len(p) / tot
            out.append((t, t + d - 0.25, p, *rest))   # write_srt adds 0.25 s back
            t += d
    return out


def ts(x):
    ms = int(round(x * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(caps, path, t0=0.0):
    path.write_text("\n".join(f"{k + 1}\n{ts(a - t0)} --> {ts(e - t0 + 0.25)}\n{text}\n"
                              for k, (a, e, text, *_) in enumerate(caps)), encoding="utf-8")


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
#vidtx { position: fixed; left: 24px; top: 104px; z-index: 99999; opacity: 0; transform: translateY(-8px);
  transition: opacity .35s ease, transform .35s ease; pointer-events: none; text-align: left; max-width: 760px;
  font-family: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif; color: #111418; }
#vidtx.on { opacity: 1; transform: none; }
#vidtx b { display: block; width: max-content; max-width: 760px; background: #fff; border: 1px solid #e4e7eb; border-radius: 4px;
  font-size: 32px; line-height: 1.15; font-weight: 600; letter-spacing: -0.015em; padding: 10px 16px; }
#vidtx b em { font-style: normal; color: #0072b2; }
#vidtx small { display: block; width: max-content; margin-top: 6px; font-size: 16px; font-weight: 400; color: #5b636e;
  background: #fff; border: 1px solid #e4e7eb; border-radius: 4px; padding: 4px 10px; }
body.vidhero main { grid-template-columns: 1fr !important; }
body.vidhero #list, body.vidhero #side { display: none !important; }
"""


# A visible mouse cursor (headless Chromium draws none): an arrow that follows real mouse events, with a click ring.
CURSOR_JS = """document.addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div'); c.id = 'vcur';
  c.innerHTML = '<svg width="26" height="30" viewBox="0 0 26 30"><path d="M2 2 L2 24 L8 18.5 L12.5 28 L16.5 26.2 L12.2 17 L20 17 Z" fill="#111418" stroke="#fff" stroke-width="2" stroke-linejoin="round"/></svg><i></i>';
  c.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;opacity:0;transition:opacity .2s;will-change:transform';
  const st = document.createElement('style');
  st.textContent = '#vcur i{position:absolute;left:-14px;top:-14px;width:28px;height:28px;border-radius:50%;border:2px solid #0072b2;opacity:0}#vcur.down i{animation:vcring .5s ease-out}@keyframes vcring{from{opacity:.9;transform:scale(.3)}to{opacity:0;transform:scale(1.4)}}';
  document.head.appendChild(st); document.body.appendChild(c);
  addEventListener('mousemove', e => { c.style.opacity = 1; c.style.transform = `translate(${e.clientX - 2}px, ${e.clientY - 2}px)`; }, true);
  addEventListener('mousedown', () => { c.classList.remove('down'); void c.offsetWidth; c.classList.add('down'); }, true);
});"""


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
        self.dpr = 1.0

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

    async def at(self, t):
        """Wait until page time t (s since start): to land an action on its spoken cue."""
        if t > self.now():
            await self.sleep(t - self.now())

    async def point(self, target, over=0.6):
        """Glide the visible cursor to an element (selector) or (x, y), ease-in-out, on the page clock."""
        if isinstance(target, str):
            target = await self.pg.evaluate("""s => { const e = document.querySelector(s); if (!e) return null;
              const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }""", target)
            if not target:
                return None
        x0, y0 = getattr(self, "mxy", (self.view[0] * 0.62, self.view[1] * 0.78))
        n = max(4, int(over * 24))
        for k in range(1, n + 1):
            e = _ease(k / n)
            await self.move(x0 + (target[0] - x0) * e, y0 + (target[1] - y0) * e)
            await self.sleep(over / n)
        self.mxy = tuple(target)
        return target

    async def move(self, x, y):
        # with the CDP device-metrics override, Input events land at (x, y) / DPR: hand them device pixels
        await self.pg.mouse.move(x * self.dpr, y * self.dpr)

    async def ring(self):
        """The click ring alone (no real click: e.g. on the mic, whose real flow needs a microphone)."""
        await self.pg.evaluate("(() => { const c = document.getElementById('vcur'); if (c) { c.classList.remove('down'); void c.offsetWidth; c.classList.add('down'); } })()")

    async def click(self, target, over=0.6):
        xy = await self.point(target, over)
        if xy:
            await self.sleep(0.12)
            await self.pg.mouse.down()
            await self.pg.mouse.up()
        return xy

    async def say(self, title, sub=""):
        await self.pg.evaluate("""([t, s]) => { let o = document.getElementById('vidtx');
          if (!o) { o = document.createElement('div'); o.id = 'vidtx'; document.body.appendChild(o); }
          o.innerHTML = t ? `<b>${t}</b>${s ? `<small>${s}</small>` : ''}` : ''; o.classList.toggle('on', !!t); }""",
                               [title, sub])


async def new_page(browser, slow, dpr, url=None, extra_ctx=None, view=VIEW, mobile=False):
    ctx = await browser.new_context(viewport={"width": view[0], "height": view[1]}, device_scale_factor=dpr,
                                    is_mobile=mobile, has_touch=mobile, **(extra_ctx or {}))
    await ctx.add_init_script(CLOCK_SHIM % {"slow": slow})
    if not mobile:
        await ctx.add_init_script(CURSOR_JS)
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
    """Clicks into the ask box, types the question (on the page clock) and clicks Ask."""
    await rec.click("#q", 0.5)
    await rec.pg.evaluate("""async q => { const el = document.querySelector('#q'); el.value = ''; el.focus();
      const dt = Math.max(12, Math.min(40, 1400 / q.length));
      for (const ch of q) { el.value += ch; await new Promise(r => setTimeout(r, dt)); } }""", q)
    await rec.sleep(0.2)
    await rec.point("#go", 0.35)                    # the cursor goes to Ask; ask() itself is called (deterministic)
    await rec.sleep(0.1)
    await rec.ring()
    await rec.pg.evaluate("ask()")
    if wait:
        await wait_js(rec.pg, f"{ANSWERED}({json.dumps(q)})")


async def wait_ready(pg):
    await pg.wait_for_load_state("networkidle")
    await pg.evaluate("document.fonts.ready")


# ---- the shots. Each gets a fresh page and a Rec; they mirror the storyboard in docs/video.md.

CUES = {}   # scene id -> start of each spoken line (s from the scene start), so actions land on their words


def cue(rec, i, default):
    c = CUES.get(rec.name, [])
    return c[i] if i < len(c) else default


async def shot_hook(rec, base):
    """Flat plan seen from above -> walls rise -> the 20 counted doors light up one by one, numbered."""
    pg = rec.pg
    await wait_js(pg, f"{ANSWERED}({json.dumps(Q_DOORS)})")
    await wait_js(pg, "window.__p3 && document.querySelector('#p3go')")
    await pg.evaluate("document.body.classList.add('vidhero')")
    await asyncio.sleep(1.0)                      # layout settles; geometry was prefetched by plan3d.js
    await rec.start()
    await rec.point((900, 600), 0.1)
    await rec.click("#p3go", 0.45)
    await pg.evaluate("window.__p3riseMs = 2600; if (!window.__p3.opened) window.__p3.open()")
    await rec.point((1400, 820), 0.5)
    await wait_js(pg, "window.__p3.ready")
    rec.mark("risen")
    rec.cam((150, 60, 1300), 4.0)                  # slow push-in while the doors pop in
    await rec.sleep(1.3)
    await rec.say("<em>20</em> doors, every one numbered", "Each one marked on the drawing.")
    await rec.sleep(2.2)
    await rec.say("Datum: blueprints that talk", "Junction 2026, Stoa: Make Blueprints Talk")
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
    await type_and_ask(rec, Q_DOORS, wait=False)
    await wait_js(pg, "typeof animating !== 'undefined' && animating")
    await rec.cam_on("#viewer", 960, 0.8)          # punch in on the drawing while the count runs
    await wait_js(pg, f"{ANSWERED}({json.dumps(Q_DOORS)})")
    await rec.at(cue(rec, 1, 4.0) - 0.4)
    await rec.cam_on("#answer", 720, 0.6, top=True)  # "a second method agrees": over to the answer card
    await rec.point("#answer", 0.6)
    await rec.sleep(2.6)
    rec.cam(None, 0.6)
    await rec.sleep(0.6)
    await rec.stop()


async def shot_ghost(rec, base):
    pg = rec.pg
    await wait_ready(pg)
    await rec.start()
    await type_and_ask(rec, Q_AREA_DE, wait=False)
    await wait_js(pg, "typeof animating !== 'undefined' && animating")
    await rec.cam_on("#viewer", 1250, 3.0)         # slow push-in while the rooms add up (the replay)
    await wait_js(pg, f"{ANSWERED}({json.dumps(Q_AREA_DE)})")
    await pg.evaluate("rowHot(0, true, true); hotItem(0, true)")
    await rec.at(cue(rec, 2, 9.0) - 1.2)
    await pg.evaluate("rowHot(0, false); hotItem(0, false)")
    rec.cam(None, 0.4)
    await pg.evaluate("doAction('scroll:.vs')")
    await rec.sleep(0.8)
    await rec.cam_on("#answer .ghostcmp", 640, 0.7)
    await rec.point("#answer .ghostcmp", 0.6)
    await rec.sleep(3.6)                            # the app's own "5 of 5 wrong" says it: no chip
    await rec.stop(0.2)


async def shot_correct(rec, base):
    pg = rec.pg
    await wait_js(pg, f"{ANSWERED}({json.dumps(Q_WINDOWS)})")
    await pg.evaluate("openSec('ev')")
    await asyncio.sleep(0.5 * rec.slow)
    await rec.start()
    await rec.cam_on("#side", 1100, 0.6, top=True)
    await rec.point('#ev div[data-i="3"]', 0.8)
    await pg.evaluate("doAction('toggle:3')")
    await rec.sleep(0.5)
    await rec.ring()     # the click ring, on the row being unticked
    await rec.sleep(2.0)
    rec.cam(None, 0.6)
    await rec.sleep(0.8)
    await rec.stop(0.2)


async def shot_heat(rec, base):
    pg = rec.pg
    # the view menu's "Room heat-map" and "Takeoff sheet" items call these two app functions
    await wait_js(pg, "typeof cur !== 'undefined' && cur && document.querySelector('#img').naturalWidth > 0")
    await rec.start()
    await rec.sleep(0.6)
    await pg.evaluate("setHeat(true)")
    await rec.sleep(0.4)
    await rec.cam_on("#viewer", 1100, 0.9)
    await rec.sleep(3.0)
    rec.cam(None, 0.5)
    await pg.evaluate("openSheet()")
    await rec.sleep(3.4)
    await rec.stop()


# the voice strip's states (Listening -> Transcribing -> Asking), then the question is asked as text; the listening
# time matches the spoken Finnish question, which is in the soundtrack at that moment
STAGE_VOICE = """async ([q, listen]) => {
          const s = document.querySelector('#voice'), m = document.querySelector('#mic'), w = ms => new Promise(r => setTimeout(r, ms));
          const st = (state, msg) => { s.hidden = false; s.dataset.state = state; m.classList.toggle('on', state === 'listening');
            s.querySelector('.vstate').textContent = msg; s.querySelector('.vstop').hidden = state !== 'listening'; };
          st('listening', 'Listening'); s.querySelector('.vfin').textContent = ''; s.querySelector('.vint').textContent = 'Listening… stops when you pause';
          await w(listen); st('transcribing', 'Transcribing'); s.querySelector('.vint').textContent = 'Turning speech into text…';
          await w(600); st('asking', 'Asking'); s.querySelector('.vfin').textContent = q; s.querySelector('.vint').textContent = '';
          document.querySelector('#q').value = q; await w(500); s.hidden = true; m.classList.remove('on'); ask(); }"""


async def shot_voice(rec, base, wav=None):
    """The Finnish question is spoken (Toivo's voice, in the soundtrack) while the strip listens; the app's voice
    strip is staged with the same states it shows (the real path, ElevenLabs Scribe on the server, is the same
    question as audio: checked separately on the same clip). Then the detector's boxes and the plan rises into 3D."""
    pg = rec.pg
    await wait_ready(pg)
    await wait_js(pg, "document.querySelector('#mic')", 30)
    await rec.start()
    await rec.cam_on(".ask", 900, 0.8, top=True)
    await rec.point("#mic", 1.0)
    c_fi, c_r = cue(rec, 1, 4.0), cue(rec, 2, 7.0)
    durs = CUES.get(rec.name + ":dur", [])
    listen = durs[1] if len(durs) > 1 else 2.5
    await rec.at(c_fi - 0.25)
    await rec.ring()
    if wav:
        await pg.click("#mic")
        await wait_js(pg, "typeof res !== 'undefined' && res && !animating", 120)
    else:
        await pg.evaluate("([a, b]) => { (" + STAGE_VOICE + ")([a, b]); }", [Q_DOORS_FI, int((listen + 0.35) * 1000)])
        await wait_js(pg, f"{ANSWERED}({json.dumps(Q_DOORS_FI)})")
    await rec.cam_on("#viewer", 1100, 0.7)          # over to the boxed doors on the scan
    await rec.point((1000, 500), 0.6)
    await rec.at(c_r + 1.4)
    rec.cam(None, 0.6)
    await wait_js(pg, "window.__p3 && document.querySelector('#p3go') && (typeof xr === 'undefined' || !xr)", 60)
    await pg.evaluate("window.__p3riseMs = 2200")
    await rec.click("#p3go", 0.5)
    await rec.sleep(0.3)
    await pg.evaluate("if (!window.__p3.opened) window.__p3.open()")
    await rec.point((1300, 800), 0.5)
    await wait_js(pg, "window.__p3.ready", 120)
    await rec.sleep(1.6)
    await rec.stop(0.2)


async def shot_ifc(rec, base):
    pg = rec.pg
    await wait_js(pg, f"{ANSWERED}({json.dumps(Q_IFC_WALLS)})", 240)
    await pg.evaluate("setMode('3d')")              # loading the model in software GL is slow: do it off camera
    await wait_js(pg, "document.querySelector('#three .v3bar button')", 300)
    await asyncio.sleep(2 * rec.slow)
    sel = ("(re => { const b = [...document.querySelectorAll('#viewer button')].find(b => !b.hidden"
           " && re.test(b.textContent)); if (!b) return null; b.dataset.vid = re.source.replace(/\\W/g, ''); "
           "return '[data-vid=\"' + b.dataset.vid + '\"]'; })")
    async def press(rx):
        q = await pg.evaluate(sel + f"(/{rx}/i)")
        if q:
            await rec.click(q, 0.5)
    await rec.start()
    await press("whole building")                   # all storeys, not just the asked one
    await rec.sleep(0.8)
    await rec.cam_on("#viewer", 1150, 1.2)
    await rec.at(cue(rec, 1, 3.0) - 0.3)
    await press("explode")                          # Explode storeys, on "explode the storeys"
    await rec.sleep(1.6)
    await press("x-ray")
    await rec.sleep(0.6)
    # a slow orbit by dragging the canvas (OrbitControls), on the page clock
    vx = await pg.evaluate("(() => { const r = document.querySelector('#viewer').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
    await rec.point(vx, 0.4)
    await pg.mouse.down()
    for k in range(20):
        await rec.move(vx[0] - 12 * k, vx[1] + 1.2 * k)
        await rec.sleep(0.05)
    await pg.mouse.up()
    rec.mxy = (vx[0] - 228, vx[1] + 23)
    await rec.sleep(1.2)
    await rec.stop(0.2)


SCHOOL = Path("/data/attachments/s_YTlo5xSrle/stoa-examples/sources/uk_dfe_sen_special_school")
Q_PROJECT = "How many doors in the whole school?"


async def shot_project(rec, base):
    """Both DfE school floors dropped in at once become one project; the whole-school door count is the sum of the
    floors, listed per floor, and a tap on a floor shows its marks."""
    pg = rec.pg
    files = []
    for lv, f in (("00", "SEN-DFE-XX-00-D-X-0201-Special_School_Plan_Level_00-A-C01.pdf"),
                  ("01", "SEN-DFE-XX-01-D-X-0202-Special_School_Plan_Level_01-A-C01.pdf")):
        up = WORK / "upload" / f"Special_School_Plan_Level_{lv}.pdf"
        up.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SCHOOL / f, up)
        files.append(str(up))
    await wait_ready(pg)
    await rec.start()
    await rec.click("#drawerbtn", 0.7)
    await rec.sleep(0.3)
    await rec.point("#uploadbox", 0.5)
    await rec.ring()
    await pg.set_input_files("#file", files)
    await wait_js(pg, "window.bpProject && window.bpProject() && (window.bpProject().sheets || []).length >= 2", 180)
    rec.mark("project")
    await rec.point((1300, 380), 0.6)
    await type_and_ask(rec, Q_PROJECT, wait=False)
    await wait_js(pg, f"{ANSWERED}({json.dumps(Q_PROJECT)})", 300)
    rec.mark("answered")
    await rec.cam_on("#side", 1000, 0.7, top=True)
    await rec.at(cue(rec, 1, 5.0) + 1.6)
    await rec.point('.ppart[data-i="1"]', 0.5)       # Level 01: its own door marks
    await rec.ring()
    await pg.evaluate("document.querySelector('.ppart[data-i=\"1\"]').click()")
    await rec.sleep(0.6)
    rec.cam(None, 0.7)
    await rec.sleep(2.2)
    await rec.stop(0.2)


SHEET_PDF = Path("/data/attachments/s_YTlo5xSrle/stoa-examples/sources/uk_dfe_sen_special_school/"
                 "SEN-DFE-XX-01-D-X-0202-Special_School_Plan_Level_01-A-C01.pdf")
Q_SHEET = "How many group rooms are on this level?"


async def shot_sheet(rec, base):
    """A held-out sheet: the DfE special school Level 01 plan (vector PDF), uploaded through the real upload input,
    asked, its replay played at page speed (no click or key: either would skip it), then See it in 3D."""
    pg = rec.pg
    up = WORK / "upload" / "Special_School_Plan_Level_01.pdf"
    up.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SHEET_PDF, up)
    await wait_ready(pg)
    await rec.start()
    await rec.sleep(0.3)
    await rec.click("#drawerbtn", 0.9)              # the drawing picker: "Upload your own" sits at its top
    await rec.sleep(0.5)
    await rec.point("#uploadbox", 0.6)
    await rec.sleep(0.2)
    await rec.ring()
    rec.mark("upload")
    await pg.set_input_files("#file", str(up))
    await wait_js(pg, "typeof cur !== 'undefined' && cur && cur.path.startsWith('uploads/') && "
                      "document.querySelector('#img').naturalWidth > 0", 120)
    await rec.point((1000, 450), 0.8)
    await rec.at(cue(rec, 1, 6.5) - 0.2)
    rec.mark("ask")
    await type_and_ask(rec, Q_SHEET, wait=False)
    await rec.point((1460, 820), 0.5)
    await rec.cam_on("#viewer", 1200, 2.5)          # slow push-in while the replay works the count out
    await wait_js(pg, f"{ANSWERED}({json.dumps(Q_SHEET)})", 120)
    rec.mark("answered")
    await rec.at(cue(rec, 2, 13.0) - 1.0)
    rec.cam(None, 0.5)
    await wait_js(pg, "window.__p3 && document.querySelector('#p3go') && !document.querySelector('#p3go').closest('[hidden]')", 60)
    await wait_js(pg, "typeof xr === 'undefined' || !xr", 120)   # a click while the replay runs would only skip it
    rec.mark("p3go")
    await pg.evaluate("window.__p3riseMs = 2200")
    await rec.click("#p3go", 0.5)
    rec.mark("clicked")
    await rec.sleep(0.3)
    await pg.evaluate("if (!window.__p3.opened) window.__p3.open()")
    await rec.point((1450, 820), 0.5)
    await wait_js(pg, "window.__p3.ready", 120)
    await rec.sleep(1.2)
    await rec.cam_on("#answer", 760, 0.8, top=True)   # the answer card: how it was read
    await rec.sleep(1.8)
    await rec.stop(0.2)


PHONE_VIEW, PHONE_DPR = (390, 844), 3.0
SHOT_SLOW = {"ifc": 2.5, "sheet": 1.5}   # the whole IFC model in software GL renders ~4x slower than the Swiss plan: more slow-motion


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
    "sheet": (shot_sheet, lambda b: f"{b}/?tab=upload"),
    "project": (shot_project, lambda b: f"{b}/?tab=upload"),
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
            sl = slow * SHOT_SLOW.get(name, 1.0)
            # a fresh browser per shot: after the heavy IFC scene SwiftShader's GPU process could refuse screenshots
            b = await p.chromium.launch(args=args)
            phone = name == "phone"
            ctx, pg, cdp = await new_page(b, sl, PHONE_DPR if phone else dpr, url,
                                          {"permissions": ["microphone"]} if voice_wav else None,
                                          PHONE_VIEW if phone else VIEW, phone)
            rec = Rec(pg, cdp, sl, name, PHONE_VIEW if phone else VIEW)
            rec.dpr = PHONE_DPR if phone else dpr
            t = time.time()
            try:
                await (fn(rec, base, voice_wav) if name == "voice" else fn(rec, base))
            except Exception as e:
                print(f"  shot {name} failed: {e}; marks {rec.marks}")
                try:
                    await pg.screenshot(path=str(WORK / f"fail-{name}.png"))
                except Exception:
                    pass
                if rec.task:
                    rec.on = False
                    try:
                        await rec.task
                    except Exception:
                        pass
                    (rec.dir / "meta.json").write_text(json.dumps(
                        {"frames": rec.frames, "cams": rec.cams, "dur": rec.now(), "marks": rec.marks, "slow": sl,
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


def scene_frames(name, dur, size=(1920, 1080), info=None):
    """Yield a shot's frames (RGB bytes) resampled to FPS over exactly `dur` s: played at real speed if it fits, sped
    up (to at most 1.6x) when the recording is longer, then trimmed; held on its last frame when it is shorter."""
    from PIL import Image
    d = WORK / f"shot-{name}"
    meta = json.loads((d / "meta.json").read_text())
    frames, cams, have = meta["frames"], meta["cams"], meta["dur"]
    if not frames:
        raise SystemExit(f"shot {name}: no frames recorded")
    speed = min(1.6, have / dur) if have > dur else 1.0
    if info is not None:
        info.update(have=have, speed=speed)
    V = meta.get("view", VIEW)
    full = (0.0, 0.0, float(V[0]), float(V[1]))
    W, H = size
    j, last, cache, buf = 0, None, {}, None
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
        yield buf


def ff_writer(out, size=(1920, 1080)):
    return subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{size[0]}x{size[1]}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                             "-crf", "16", "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)


def frames_clip(name, dur, out, dpr, size=(1920, 1080)):
    info = {}
    p = ff_writer(out, size)
    for fr in scene_frames(name, dur, size, info):
        p.stdin.write(fr)
    p.stdin.close()
    p.wait()
    return info["have"], info["speed"]


WHIP = 5   # frames each side of a cut: a 10-frame (0.33 s) whip-pan to the left, horizontal motion blur at peak speed


def whip_frames(a_frames, b_frames, size=(1920, 1080)):
    """The outgoing frames slide out left as the incoming slide in, ease-in-out (quint), blurred along x by speed."""
    from PIL import Image
    W, H = size
    n = len(a_frames) + len(b_frames)
    ease = lambda k: 16 * k ** 5 if k < .5 else 1 - (-2 * k + 2) ** 5 / 2
    out = []
    for i in range(n):
        k0, k1 = i / n, (i + 1) / n
        off = int(round(ease((k0 + k1) / 2) * W))
        v = (ease(k1) - ease(k0)) * W            # px moved this frame: the blur length
        A = Image.frombytes("RGB", size, a_frames[min(i, len(a_frames) - 1)])
        B = Image.frombytes("RGB", size, b_frames[max(0, i - len(a_frames))])
        im = Image.new("RGB", size, "white")
        im.paste(A, (-off, 0))
        im.paste(B, (W - off, 0))
        f = max(1, int(v / 6))
        if f > 1:   # horizontal-only blur: squeeze along x and stretch back
            im = im.resize((max(8, W // f), H), Image.BILINEAR).resize((W, H), Image.BILINEAR)
        out.append(im.tobytes())
    return out


def compose_picture(plan, out, size=(1920, 1080), whip=True):
    """All scenes into one silent picture; every cut between scenes is a whip-pan (same total length: the
    transition takes the last WHIP frames of one scene and the first WHIP of the next)."""
    from collections import deque
    p = ff_writer(out, size)
    tail = None
    for i, (s, t0, dur) in enumerate(plan):
        info = {}
        gen = scene_frames(s["id"], dur, size, info)
        if tail is not None:
            head = [next(gen) for _ in range(WHIP)]
            for fr in whip_frames(list(tail), head, size):
                p.stdin.write(fr)
        last = i == len(plan) - 1
        hold = deque(maxlen=WHIP if (whip and not last) else 0)
        for fr in gen:
            if hold.maxlen:
                if len(hold) == hold.maxlen:
                    p.stdin.write(hold[0])
                hold.append(fr)
            else:
                p.stdin.write(fr)
        print(f"scene {s['id']}: recorded {info.get('have', 0):.1f} s -> {dur:.2f} s (x{info.get('speed', 1):.2f})")
        tail = hold if hold.maxlen else None
    p.stdin.close()
    p.wait()


# ---------------------------------------------------------------- cards

# Cards follow docs/deck/DESIGN-RULES.md: one idea each, light theme, IBM Plex Sans 400/600 on the 120/64/32/24/18
# scale, left-aligned on the 128 px margin, one accent (#0072b2) for ours and grey for frontier models, no eyebrow
# labels, no footnotes (sources: docs/video.md), only the licence/credit line in the footer band.
PLEX = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&display=swap">')
CARD_CSS = """
:root { --ink:#111418; --g1:#5b636e; --g2:#8a929d; --g3:#e4e7eb; --ours:#0072b2; }
* { box-sizing: border-box; }
html, body { margin:0; width:1536px; height:864px; overflow:hidden; background:#fff; }
body { font-family: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif; color:var(--ink); }
.card { width:1920px; height:1080px; transform: scale(.8); transform-origin: 0 0; position:relative; overflow:hidden;
  background:#fff; padding:96px 128px 72px; display:none; }
.card.on { display:flex; flex-direction:column; justify-content:center; padding-bottom:168px; }
h1 { font-size:120px; line-height:1.05; font-weight:600; letter-spacing:-0.025em; margin:0 0 40px; }
h2 { font-size:64px; line-height:1.05; font-weight:600; letter-spacing:-0.025em; margin:0 0 72px; max-width:1500px; }
p { font-size:32px; line-height:1.4; color:var(--g1); margin:0; max-width:1300px; }
.foot { position:absolute; left:128px; right:128px; bottom:0; height:72px; font-size:18px; line-height:1.4; color:var(--g2); }
.bars { display:grid; grid-template-columns: 520px 1fr; gap:32px 32px; align-items:center; }
.lab { font-size:32px; line-height:1.25; color:var(--g1); } .lab b { color:var(--ink); font-weight:600; }
.bar { height:40px; position:relative; }
.bar i { position:absolute; left:0; top:0; bottom:0; border-radius:4px; background:var(--g2);
  transform-origin: 0 50%; animation: grow 1.4s cubic-bezier(.2,.7,.2,1) both; }
.bar.ours i { background:var(--ours); }
.bar em { position:absolute; top:50%; transform:translateY(-50%); font-style:normal; font-weight:600; font-size:32px; padding-left:16px;
  color:var(--g1); animation: fade .5s ease both; }
.bar.ours em { color:var(--ours); }
@keyframes grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@keyframes fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes rise { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: none; } }
.in { animation: rise .7s ease both; }
.vs { display:flex; gap:128px; align-items:flex-end; margin-top:8px; }
.vs .n { font-size:200px; font-weight:600; letter-spacing:-0.035em; line-height:1; }
.vs .ours .n { color:var(--ours); } .vs .fr .n { color:var(--g2); }
.vs .l { font-size:32px; line-height:1.4; color:var(--g1); margin-top:24px; }
.end code { font-family: inherit; font-size:32px; color:var(--ink); }
"""


def bar(label, acc, k, ours=False):
    d = 0.5 + 0.35 * k
    return (f'<div class="lab in" style="animation-delay:{d - .2:.2f}s">{label}</div><div class="bar{" ours" if ours else ""}">'
            f'<i style="width:{acc * 0.85:.1f}%;animation-delay:{d:.2f}s"></i>'
            f'<em style="left:{acc * 0.85:.1f}%;animation-delay:{d:.2f}s" data-to="{acc}" data-dec="1" data-suf="&nbsp;%" '
            f'data-delay="{d:.2f}">{acc:.1f}&nbsp;%</em></div>')


COUNT_JS = """// numbers count up with their bar (ease-out, 1.4 s like the bar), on the page clock
const T0 = performance.now(), els = [...document.querySelectorAll('.card.on [data-to]')];
const tick = () => {
  const t = (performance.now() - T0) / 1000;
  for (const e of els) {
    const k = Math.max(0, Math.min(1, (t - +e.dataset.delay) / 1.4)), v = +e.dataset.to * (1 - Math.pow(1 - k, 3));
    e.innerHTML = (e.dataset.pre || '') + v.toLocaleString('en-US', {minimumFractionDigits: +e.dataset.dec, maximumFractionDigits: +e.dataset.dec}) + (e.dataset.suf || '');
  }
  if (t < 4) requestAnimationFrame(tick);
};
tick();
"""


def cards_html():
    voice = "Kokoro-82M (Apache-2.0)" if ENGINE == "kokoro" else (
        "ElevenLabs" if VOICE_SET == "premade" else "Toivo and Rene, ElevenLabs v3")
    return f"""<!doctype html><html><head><meta charset="utf-8">{PLEX}<style>{CARD_CSS}</style></head><body>
<section class="card" id="problem">
  <h2 class="in">General AI gets 7 answers in 10 right, and is just as sure when it is wrong.</h2>
  <div class="bars">
    {bar("<b>Leading AI model</b><br>with the drawing's CAD / BIM files", 69.8, 0)}
    {bar("<b>Leading AI model</b><br>drawing only", 63.2, 1)}
  </div>
</section>
<section class="card" id="results">
  <h2 class="in">90.7&nbsp;% right on all 25,420 held-out test questions.</h2>
  <div class="bars">
    {bar("<b>Datum</b>", 90.7, 0, True)}
    {bar("<b>Leading AI model</b><br>same files", 69.8, 1)}
  </div>
</section>
<section class="card" id="cost">
  <h2 class="in">Cost per 1,000 questions</h2>
  <div class="vs">
    <div class="ours in" style="animation-delay:.4s"><div class="n" data-to="0.013" data-dec="3" data-pre="$" data-delay=".4">$0.013</div><div class="l">Datum</div></div>
    <div class="fr in" style="animation-delay:1.1s"><div class="n" data-to="25.76" data-dec="2" data-pre="$" data-delay="1.1">$25.76</div><div class="l">Leading AI model, same files</div></div>
  </div>
</section>
<section class="card end" id="end">
  <h1 class="in">Datum <span style="font-weight:400; color:var(--g2)">blueprints that talk</span></h1>
  <p class="in" style="animation-delay:.5s">Exact, verifiable, cheap. Exact methods first, AI only where needed.<br><code>{REPO_URL}</code></p>
  <div class="foot">{html.escape(CREDITS)}. Voice: {voice}.</div>
</section>
<script>
document.getElementById(new URLSearchParams(location.search).get('card')).classList.add('on');
{COUNT_JS}
</script></body></html>"""


# ---------------------------------------------------------------- build

def update_doc(plan, caps, total, cut):
    doc = ROOT / "docs/video.md"
    rows, k = [], 0
    for i, (s, t0, dur) in enumerate(plan):
        n = len(lines_of(s, cut))
        text = " ".join(f"**{c[4]}** {c[2]}" for c in caps[k:k + n]) or "(silent)"
        k += n
        rows.append(f"| {i + 1} | {int(t0 // 60)}:{t0 % 60:05.2f}–{int((t0 + dur) // 60)}:{(t0 + dur) % 60:05.2f} | "
                    f"{s['kind']} `{s['id']}` | {text} |")
    words = sum(len(c[2].split()) for c in caps)
    table = ("| # | time | shot | voice-over (caption text) |\n|---|---|---|---|\n" + "\n".join(rows) +
             f"\n\nTotal {total:.2f} s; {words} words; voice {ENGINE}"
             + (f" `{VOICE}` at speed {SPEED}" if ENGINE == "kokoro" else f" ElevenLabs {voice_of('A')[2]}, {speaker_name('A')} (A) + {speaker_name('B')} (B)") + ". Generated by `make_video.py`.")
    tag = "TIMING" if cut == "full" else "TIMING60"
    src = doc.read_text()
    new = re.sub(rf"(<!-- {tag} -->\n).*?(<!-- /{tag} -->)", lambda m: m.group(1) + table + "\n" + m.group(2), src, flags=re.S)
    doc.write_text(new)


def ensure_fonts():
    """IBM Plex Sans for the burned-in captions (one typeface with the app, DESIGN-RULES.md rule 6), cached."""
    d = ROOT / "cache/fonts"
    d.mkdir(parents=True, exist_ok=True)
    for w in ("Regular", "SemiBold"):
        f = d / f"IBMPlexSans-{w}.ttf"
        if not f.exists():
            urllib.request.urlretrieve(f"https://github.com/google/fonts/raw/main/ofl/ibmplexsans/IBMPlexSans-{w}.ttf", f)
    return d


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
    ap.add_argument("--tts", choices=["kokoro", "elevenlabs"], default="elevenlabs")
    ap.add_argument("--voices", choices=["protege", "premade", "cloned"], default="protege",
                    help="one narrator (Protégé clone; default), premade George + Sarah, or the cloned Toivo + Rene take")
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

    global VOICE_SET
    VOICE_SET = a.voices
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

    for sc, t0, d in plan:
        mine = [c for c in caps if t0 <= c[0] < t0 + d]
        CUES[sc["id"]] = [c[0] - t0 for c in mine]
        CUES[sc["id"] + ":dur"] = [c[1] - c[0] for c in mine]
    only = set(a.only.split(",")) if a.only else None
    plan = [x for x in plan if not only or x[0]["id"] in only]
    if not plan:
        sys.exit("--only matched no scene of this cut")
    # the chosen scenes play back to back: move each scene (and its captions) to its place in that sequence
    starts, acc = [], 0.0
    for _, t0, d in plan:
        starts.append((t0, d, acc))
        acc += d
    caps = [(c[0] - t0 + n, c[1] - t0 + n, *c[2:]) for c in caps for t0, d, n in starts if t0 <= c[0] < t0 + d]
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "cards.html").write_text(cards_html(), encoding="utf-8")
    if not a.reuse:
        asyncio.run(record([s["id"] for s, _, _ in plan], a.url.rstrip("/"), a.slow, a.dpr, a.gpu, a.voice_wav))

    silent = WORK / "picture.mp4"
    compose_picture(plan, silent)

    span = sum(d for _, _, d in plan)
    shift = caps
    voice = WORK / "voice.wav"
    write_voice(shift, span, voice)
    out = Path(a.out) if a.out else OUT / f"blueprints-{a.cut}.mp4"
    srt = out.with_suffix(".srt")
    write_srt(shift, srt)  # the sidecar has every line in full
    burn = WORK / "burn.srt"
    write_srt(short_caps(shift), burn)    # burned in: short phrases, on screen the whole time someone speaks
    fonts = ensure_fonts()
    style = ("FontName=IBM Plex Sans,FontSize=13,PrimaryColour=&H00181411,BorderStyle=1,Outline=0,Shadow=0,"
             "Alignment=1,MarginV=12,MarginL=29,MarginR=29")
    ff("-i", silent, "-i", voice,
       "-vf", (f"scale=1632:918:flags=lanczos,pad=1634:920:1:1:color=0xe4e7eb,pad=1920:1080:143:0:color=0xffffff,"
               f"subtitles={burn}:fontsdir={fonts}:force_style='{style}'"),
       "-af", loudnorm_2pass(voice, LUFS),
       "-c:v", "libx264", "-preset", "slow", "-crf", 18, "-pix_fmt", "yuv420p", "-r", FPS,
       "-c:a", "aac", "-b:a", "192k", "-ac", 2, "-t", f"{span:.3f}", "-movflags", "+faststart", out)
    trim_loudness(out, LUFS)
    print(f"{out}: {probe_dur(out):.2f} s, {out.stat().st_size / 1e6:.1f} MB")


def trim_loudness(mp4, target):
    """The final mix (speech with gaps) measures ~1 dB under the voice-track target: measure it (EBU R128) and
    correct the gain once, with a limiter at -1 dBFS; the picture is copied."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp4), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    if not m or abs(float(m[-1]) - target) < 0.3:
        return
    tmp = mp4.with_suffix(".loud.mp4")
    ff("-i", mp4, "-c:v", "copy", "-af", f"volume={target - float(m[-1]):.2f}dB,alimiter=limit=0.89:level=false",
       "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", tmp)
    tmp.replace(mp4)
    print(f"loudness {float(m[-1]):.1f} -> {target:.1f} LUFS")


if __name__ == "__main__":
    if "--tts-worker" in sys.argv:
        tts_worker()
    else:
        main()
