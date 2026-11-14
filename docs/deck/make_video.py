"""Build the 2-minute demo video with voice-over: runs/video/blueprints-final.mp4 (+ .srt).

    .venv/bin/python docs/deck/make_video.py               # voice + cards + new tour take + cut
    .venv/bin/python docs/deck/make_video.py --reuse-take  # keep the last tour take, re-cut only

1. Voice-over: every caption line in SCENES is spoken by Kokoro-82M (Apache-2.0, runs locally on CPU) from a
   separate venv in cache/tts/venv (see docs/video.md for the install). Clips are cached by text.
2. Timing: each scene lasts as long as its voice-over (LEAD before, GAP between lines, TAIL after), so the
   picture follows the voice. The total must stay <= 120 s; the script refuses to build otherwise.
3. Visuals: title/results/cost/end cards (HTML below), deck slides 2 and 4, and one recorded take of demo
   tour steps 1-5 (docs/deck/record_video.py), each cut to its scene length.
4. Mux: picture scaled to 85 % with a caption band underneath (so drawing credits are never covered),
   burned-in captions from the same lines, loudness-normalised voice, H.264/AAC 1920x1080.
Also rewrites the timing table in docs/video.md between the TIMING markers.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import os
import re
import subprocess
import sys
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
LIMIT = 120.0
REPO_URL = "github.com/Zawaer/datum"

# Baselines still being run. Fill in (label, accuracy %, spoken) to add a bar on the frontier card and a
# line to its voice-over, e.g. ("Gemini 3.1 Pro, drawing only", 61.0, "Gemini three point one Pro, sixty-one.").
EXTRA_BASELINES: list[tuple[str, float, str]] = [
    ("Gemini 3.1 Pro, drawing only ($52.47 per 1,000)", 64.2,
     "Gemini three point one Pro: sixty-four, at over fifty dollars per thousand."),
    # Nemotron 3.5 Super VL: still running; add it here when docs/RESULTS.md has its number.
]

# A line is (caption, spoken) or just text when both are the same. Numbers are spelled out where the TTS
# could misread them. Sources for every number: docs/STATUS.md, docs/RESULTS.md, docs/COSTS.md.
SCENES = [
    {"kind": "card", "ref": "title", "min": 2.0, "lines": []},
    {"kind": "slide", "ref": 2, "lines": [
        ("Quantity takeoff is still done by hand, and AI gets it wrong with total confidence:",
         "Quantity takeoff is still done by hand, and A.I. gets it wrong, with total confidence:"),
        ("94.73 m² instead of 108.3, even with the CAD file attached.",
         "ninety-four point seven square metres instead of a hundred and eight, even with the CAD file attached."),
    ]},
    {"kind": "card", "ref": "frontier", "lines": [
        ("On our held-out test split, Claude Sonnet 5.5, reading the drawing, gets 63 % right.",
         "On our held-out test split, Claude Sonnet five point five, reading the drawing, gets sixty-three percent right."),
        ("Even given the drawing's own CAD and IFC files: 70 %.",
         "Even given the drawing's own CAD and I.F.C. files: seventy."),
    ]},
    {"kind": "slide", "ref": 4, "lines": [
        "So we don't guess. A router sends each question to an exact solver, and every solver returns its proof.",
    ]},
    {"kind": "step", "ref": 0, "lines": [
        "A Swiss apartment plan: how many doors?",
        ("We read them straight from the CAD layers and number each one on the drawing.",
         "We read them straight from the CAD layers, and number each one on the drawing."),
        "Twenty, matching the dataset, with no model call.",
    ]},
    {"kind": "step", "ref": 1, "lines": [
        "Asked in German: the net living area of apartment A.",
        "Every room is outlined with its own square metres, and the list adds up to the answer.",
    ]},
    {"kind": "step", "ref": 2, "lines": [
        "Disagree? Untick an item, or click one we missed.",
        "The total updates on the spot: the evidence is the answer.",
    ]},
    {"kind": "step", "ref": 3, "lines": [
        "A Finnish raster plan, asked in Finnish.",
        "A small detector, trained only on open annotations, boxes every door it counts.",
    ]},
    {"kind": "step", "ref": 4, "lines": [
        "Plans rendered from a BIM model are answered from the model itself.",
        ("Switch to 3D, and the same doors light up as IFC elements.",
         "Switch to 3D, and the same doors light up as I.F.C. elements."),
    ]},
    {"kind": "card", "ref": "results", "lines": [
        ("Overall: 89.5 % correct on 25,420 held-out questions.",
         "Overall: eighty-nine point five percent correct, on twenty-five thousand held-out questions."),
        ("100 % on Swiss plans and BIM model quantities, 84 % on Finnish scans.",
         "A hundred percent on Swiss plans and BIM model quantities. Eighty-four on Finnish scans."),
        "Independently audited for leakage.",
    ]},
    {"kind": "card", "ref": "cost", "lines": [
        ("It costs 1.3 cents per thousand questions. Frontier models: 13 to 58 dollars.",
         "It costs one point three cents per thousand questions. Frontier models: thirteen to fifty-eight dollars."),
    ]},
    {"kind": "card", "ref": "end", "min": 4.0, "lines": [
        "Exact, verifiable, cheap. Blueprints That Talk.",
    ]},
]

CREDITS = ("Drawings: Swiss Dwellings v3.0.0 (Archilyse AG, CC BY 4.0) · CubiCasa5K (CubiCasa, CC BY-NC-SA 4.0) · "
           "Molio Demo-hus and BIM-Speed Warmond (buildingSMART sample files / TU Berlin, CC BY 4.0) · "
           "questions from the Junction 2026 Stoa dataset")


def lines_of(scene):
    out = [l if isinstance(l, tuple) else (l, l) for l in scene["lines"]]
    if scene["ref"] == "frontier":
        out += [(f"{lab.split(',')[0]}: {acc:.0f} %, at over $50 per 1,000.", say) for lab, acc, say in EXTRA_BASELINES]
    return out


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


def clip_path(text):
    h = hashlib.sha1(f"{VOICE}|{SPEED}|{text}".encode()).hexdigest()[:16]
    return TTS_CACHE / f"{h}.wav"


def synthesize():
    TTS_CACHE.mkdir(parents=True, exist_ok=True)
    todo = [{"text": say, "path": str(clip_path(say))} for s in SCENES for _, say in lines_of(s)
            if not clip_path(say).exists()]
    if todo:
        env = {**os.environ, "HF_HOME": str(ROOT / "cache/tts/hf")}
        subprocess.run([str(TTS_PY), "-I", __file__, "--tts-worker"], input=json.dumps(
            {"voice": VOICE, "speed": SPEED, "items": todo}), text=True, check=True, env=env)


def wav_dur(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def timeline():
    """Scene start/duration and caption (start, end, text) from the measured clip lengths."""
    fr = 1 / 30
    t, plan, caps = 0.0, [], []
    for s in SCENES:
        ls = lines_of(s)
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


def write_voice(caps, total, path):
    pcm = bytearray(int(total * SR) * 2)
    for a, _, _, clip in caps:
        with wave.open(str(clip)) as w:
            data = w.readframes(w.getnframes())
        i = int(a * SR) * 2
        pcm[i:i + len(data)] = data[:len(pcm) - i]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(bytes(pcm))


def ts(x):
    ms = int(round(x * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(caps, path):
    path.write_text("\n".join(f"{k + 1}\n{ts(a)} --> {ts(e + 0.25)}\n{text}\n"
                              for k, (a, e, text, _) in enumerate(caps)), encoding="utf-8")


# ---------------------------------------------------------------- cards

CARD_CSS = """
:root { --ink:#0f172a; --ink2:#475569; --muted:#94a3b8; --ours:#2563eb; --frontier:#e8590c; --navy:#0b1220; }
* { box-sizing: border-box; }
body { margin:0; font-family: Inter, "Helvetica Neue", Arial, "DejaVu Sans", sans-serif; color:var(--ink); }
.card { width:1920px; height:1080px; position:relative; overflow:hidden; background:#fff; padding:110px 120px; display:none; }
.card.on { display:flex; flex-direction:column; justify-content:center; padding-bottom:150px; }
.dark { background:var(--navy); color:#fff; }
.kicker { font-size:26px; font-weight:700; letter-spacing:.14em; text-transform:uppercase; color:var(--ours); margin-bottom:22px; }
.dark .kicker { color:#60a5fa; }
h1 { font-size:128px; line-height:1.02; font-weight:800; letter-spacing:-0.03em; margin:0 0 30px; }
h1 span, .brand span { color:#60a5fa; }
h2 { font-size:64px; line-height:1.08; font-weight:800; letter-spacing:-0.02em; margin:0 0 50px; max-width:1640px; }
.sub { font-size:40px; line-height:1.35; color:#cbd5e1; max-width:1500px; }
.foot { position:absolute; left:120px; right:120px; bottom:40px; font-size:20px; line-height:1.45; color:var(--muted); }
.bars { display:grid; grid-template-columns: 560px 1fr; gap:26px 30px; align-items:center; font-size:34px; }
.bar { height:74px; background:#f1f5f9; border-radius:8px; position:relative; }
.bar i { position:absolute; left:0; top:0; bottom:0; border-radius:8px; background:var(--frontier); }
.bar.ours i { background:var(--ours); }
.bar em { position:absolute; top:50%; transform:translateY(-50%); font-style:normal; font-weight:800; font-size:40px; padding-left:18px; }
.lab { color:var(--ink2); line-height:1.2; } .lab b { color:var(--ink); }
.tiles { display:flex; gap:36px; margin-top:60px; }
.tile { flex:1; background:#f8fafc; border-radius:14px; padding:30px 36px; }
.tile .n { font-size:76px; font-weight:800; color:var(--ours); letter-spacing:-0.02em; }
.tile .l { font-size:28px; color:var(--ink2); margin-top:6px; line-height:1.3; }
.badge { display:inline-block; margin-top:44px; font-size:30px; padding:16px 28px; border-radius:40px; background:#ecfdf5; color:#047857; font-weight:700; }
.cost { display:flex; gap:60px; align-items:stretch; margin-top:30px; }
.cost .box { flex:1; border-radius:18px; padding:50px 56px; background:#f8fafc; }
.cost .box .n { font-size:150px; font-weight:800; letter-spacing:-0.04em; line-height:1; }
.cost .box .l { font-size:34px; color:var(--ink2); margin-top:22px; line-height:1.3; }
.cost .ours .n { color:var(--ours); } .cost .fr .n { color:var(--frontier); }
.end .meta { font-size:38px; color:#cbd5e1; line-height:1.6; margin-top:40px; }
.end .meta code { font-family:"DejaVu Sans Mono", monospace; color:#fff; font-size:38px; }
.end .foot { color:#94a3b8; font-size:22px; }
"""


def bar(label, acc, ours=False):
    return (f'<div class="lab">{label}</div><div class="bar{" ours" if ours else ""}">'
            f'<i style="width:{acc * 0.8:.1f}%"></i><em style="left:{acc * 0.8:.1f}%">{acc:.1f}&nbsp;%</em></div>')


def cards_html():
    extra = "".join(bar("<b>{}</b><br>{}".format(*map(html.escape, (lab.split(", ", 1) + [""])[:2])), acc)
                    for lab, acc, _ in EXTRA_BASELINES)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CARD_CSS}</style></head><body>
<section class="card dark" id="title">
  <div class="kicker">Junction 2026 · Stoa: Make Blueprints Talk</div>
  <h1>Blueprints <span>That Talk</span></h1>
  <div class="sub">Ask a construction drawing or a BIM model anything, in any language. Every answer comes with its proof, drawn on the drawing.</div>
</section>
<section class="card" id="frontier">
  <div class="kicker">Measured, not assumed</div>
  <h2>Frontier models get about two answers in three right.</h2>
  <div class="bars">
    {bar("<b>Claude Sonnet 5.5</b><br>drawing only", 63.2)}
    {bar("<b>Claude Sonnet 5.5</b><br>drawing + its CAD / IFC files", 69.8)}
    {extra}
  </div>
  <p style="font-size:36px; color:var(--ink2); margin-top:60px; max-width:1600px">Measurements are where they fail: Sonnet gets
  38.9&nbsp;% of Swiss room areas and under 10&nbsp;% of IFC areas and volumes right, and wrong answers sound exactly as sure as right ones.</p>
  <div class="foot">Accuracy on a 400-question sample of our held-out test split, stratified by source × question type and re-weighted to the
  full test-split mix (95 % CI ±~9 pp). Counts must be exact, measurements within 2 %. Sources: docs/RESULTS.md, runs/baseline_sonnet_full400,
  runs/baseline_sonnetfair_full400{", runs/baseline_gemini_full400. Gemini cannot take .ifc files inline, so its 61 IFC-file questions count as wrong (about 0.5 % of the test mix after re-weighting)" if EXTRA_BASELINES else ""}.</div>
</section>
<section class="card" id="results">
  <div class="kicker">Results · held-out test split</div>
  <h2>89.5&nbsp;% correct on 25,420 held-out questions.</h2>
  <div class="bars">
    {bar("<b>Blueprints That Talk</b>", 89.5, True)}
    {bar("Claude Sonnet 5.5 + CAD / IFC files", 69.8)}
    {bar("Claude Sonnet 5.5, drawing only", 63.2)}
  </div>
  <div class="tiles">
    <div class="tile"><div class="n">100&nbsp;%</div><div class="l">Swiss CAD plans<br>counts and room areas</div></div>
    <div class="tile"><div class="n">100&nbsp;%</div><div class="l">BIM / IFC models<br>counts, areas, lengths, volumes</div></div>
    <div class="tile"><div class="n">84.2&nbsp;%</div><div class="l">Finnish raster plans<br>symbol counts</div></div>
  </div>
  <div class="badge">✓ Evaluation independently audited for leakage (Codex): no drawing in both train and test</div>
  <div class="foot">Ours: all 25,420 test questions, 95 % CI 89.1–89.8 % (Swiss 99.9–100 % rounded; IFC numeric questions; free-text IFC answers 38.2 %).
  Sources: docs/STATUS.md, docs/RESULTS.md, runs/router_full_test_v6.</div>
</section>
<section class="card" id="cost">
  <div class="kicker">Cost per 1,000 questions</div>
  <h2>Exact answers don't need a giant model.</h2>
  <div class="cost">
    <div class="box ours"><div class="n">$0.013</div><div class="l"><b>Blueprints That Talk</b><br>numeric answers run locally with no model call; only free-text questions call a small LLM</div></div>
    <div class="box fr"><div class="n">$13–58</div><div class="l"><b>Frontier models</b><br>Claude Sonnet 5.5, drawing only or with its CAD / IFC files, at API list price</div></div>
  </div>
  <p style="font-size:40px; color:var(--ink2); margin-top:60px">About <b style="color:var(--ink)">1,000 to 4,000 times cheaper</b>, and about 40&nbsp;ms per answer instead of 13&nbsp;s.</p>
  <div class="foot">API list prices, measured: ours on all 25,420 test questions, frontier on a 400-question sample. Local CPU/GPU compute adds ~$0.005 per 1,000.
  Detector and model training ran on cloud GPUs (Verda). Source: docs/COSTS.md, docs/RESULTS.md.</div>
</section>
<section class="card dark end" id="end">
  <div class="kicker">Built at Junction 2026</div>
  <h1>Blueprints <span>That Talk</span></h1>
  <div class="meta">Exact · verifiable · cheap<br><code>{REPO_URL}</code></div>
  <div class="foot">{html.escape(CREDITS)}.<br>Training compute: cloud GPUs (Verda). Voice: Kokoro-82M (Apache-2.0), generated locally.</div>
</section>
<script>
const c = new URLSearchParams(location.search).get('card');
document.getElementById(c).classList.add('on');
</script></body></html>"""


# ---------------------------------------------------------------- build

def update_doc(plan, caps, total):
    doc = ROOT / "docs/video.md"
    rows, k = [], 0
    for i, (s, t0, dur) in enumerate(plan):
        n = len(lines_of(s))
        text = " ".join(c[2] for c in caps[k:k + n]) or "(silent)"
        k += n
        what = (f"tour step {s['ref'] + 1}" if s["kind"] == "step" else
                f"deck slide {s['ref']}" if s["kind"] == "slide" else f"card: {s['ref']}")
        rows.append(f"| {i + 1} | {int(t0 // 60)}:{t0 % 60:05.2f}–{int((t0 + dur) // 60)}:{(t0 + dur) % 60:05.2f} | {what} | {text} |")
    words = sum(len(c[2].split()) for c in caps)
    table = ("| # | time | on screen | voice-over (caption text) |\n|---|---|---|---|\n" + "\n".join(rows) +
             f"\n\nTotal {total:.2f} s; {words} words; voice `{VOICE}` at speed {SPEED}. Generated by `make_video.py`.")
    src = doc.read_text()
    new = re.sub(r"(<!-- TIMING -->\n).*?(<!-- /TIMING -->)", lambda m: m.group(1) + table + "\n" + m.group(2), src, flags=re.S)
    doc.write_text(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:3123")
    ap.add_argument("--reuse-take", action="store_true", help="re-cut the last recorded tour take")
    ap.add_argument("--voice-only", action="store_true", help="only synthesize and print the timing")
    a = ap.parse_args()
    sys.path.insert(0, str(HERE))
    os.chdir(ROOT)
    import record_video as rv

    synthesize()
    plan, caps, total = timeline()
    for s, t0, dur in plan:
        print(f"{t0:6.2f}  {dur:5.2f}  {s['kind']} {s['ref']}")
    print(f"total {total:.2f} s")
    update_doc(plan, caps, total)
    if total > LIMIT:
        sys.exit(f"too long: {total:.2f} s > {LIMIT} s; shorten the lines or raise SPEED")
    if a.voice_only:
        return

    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "cards.html").write_text(cards_html(), encoding="utf-8")
    pages = [((WORK / "cards.html").resolve().as_uri() + f"?card={s['ref']}", WORK / f"card-{s['ref']}.png")
             for s in SCENES if s["kind"] == "card"]
    pages += [((HERE / "deck.html").as_uri() + f"?slide={s['ref']}", WORK / f"slide-{s['ref']}.png")
              for s in SCENES if s["kind"] == "slide"]
    asyncio.run(rv.render_pages(pages))
    n_steps = max(s["ref"] for s in SCENES if s["kind"] == "step") + 1
    raw, marks = rv.last_take() if a.reuse_take else asyncio.run(rv.record_take(a.url.rstrip("/"), n_steps))

    clips = []
    for i, (s, _, dur) in enumerate(plan):
        c = WORK / f"scene-{i:02d}.mp4"
        if s["kind"] == "step":
            have = rv.step_clip(raw, marks[s["ref"]], dur, c)
            print(f"scene {i + 1}: tour step {s['ref'] + 1} recorded {have:.1f} s -> {dur:.2f} s")
        else:
            rv.still_clip(WORK / f"{s['kind'] if s['kind'] == 'card' else 'slide'}-{s['ref']}.png", dur, c)
        clips.append(c)
    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    silent = WORK / "picture.mp4"
    rv.ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", silent)

    voice = WORK / "voice.wav"
    write_voice(caps, total, voice)
    srt = OUT / "blueprints-final.srt"
    write_srt(caps, srt)
    out = OUT / "blueprints-final.mp4"
    style = ("FontName=DejaVu Sans,FontSize=13,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,"
             "Outline=0,Shadow=0,Alignment=2,MarginV=10,MarginL=40,MarginR=40")
    rv.ff("-i", silent, "-i", voice,
          "-vf", f"scale=1632:918,pad=1920:1080:144:0:color=0x0b1220,subtitles={srt}:force_style='{style}'",
          "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000",
          "-c:v", "libx264", "-preset", "slow", "-crf", 20, "-pix_fmt", "yuv420p", "-r", 30,
          "-c:a", "aac", "-b:a", "192k", "-ac", 2, "-t", f"{total:.3f}", "-movflags", "+faststart", out)
    print(f"{out}: {rv.probe_dur(out):.2f} s, {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    if "--tts-worker" in sys.argv:
        tts_worker()
    else:
        main()
