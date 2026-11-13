"""Record the 2-minute video track (1920x1080) to match the script in docs/video.md.

    .venv/bin/python docs/deck/record_video.py [--url http://localhost:3123]

1. Renders the deck slides used as cards (docs/deck/deck.html?slide=N) to PNG.
2. Records demo tour steps 1-5 (app/tour.json) in one take, logging when each step starts and finishes.
3. Cuts each scene and fits it to its slot in SCENES (freeze the last frame if short, speed up if long), so
   the video is exactly 120 s and every scene starts where the voice-over expects it.
4. Writes runs/video/blueprints-2min.mp4, the captions (.srt) and blueprints-2min-captions.mp4 (video scaled
   down, captions in a band underneath, so neither the drawing credits nor the tour captions are covered).
Needs the demo server, playwright + chromium in the venv, and ffmpeg (with libass) on PATH.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
OUT = Path("runs/video")
WORK = OUT / "work"
ARGS = ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"]
HOLD_MS = 1800

# (kind, ref, seconds, voice-over) -- kept in sync with docs/video.md; the durations add up to 120 s.
SCENES = [
    ("slide", 1, 8, "Blueprints That Talk. Ask a construction drawing or a BIM model anything, and see exactly where the answer came from."),
    ("slide", 2, 14, "Quantity takeoff is still done by hand. Ask a frontier model and you get confident answers: 94.73 square metres instead of 108.3, or zero windows instead of 110."),
    ("slide", 3, 10, "We measured it on our held-out test split. Claude Sonnet gets 63 percent right, and most measurements wrong, at 13 dollars per thousand questions."),
    ("slide", 4, 8, "So we don't guess. A router sends each question to an exact solver, and every solver returns its proof."),
    ("step", 0, 18, "A Swiss apartment plan: how many doors? We read them straight from the CAD layers and number every one on the drawing. Twenty, matching the dataset. No model call, zero cost."),
    ("step", 1, 14, "Ask in German for the net living area of apartment A. Every room is outlined with its own square metres, and the list adds up to the answer."),
    ("step", 2, 10, "Disagree? Untick an item, or click one we missed. The total updates on the spot: the evidence is the answer."),
    ("step", 3, 12, "A Finnish plan, asked in Finnish: a small detector, trained only on open annotations, boxes every door it counts."),
    ("step", 4, 14, "Plans rendered from a BIM model are answered from the model itself. The doors are IFC elements: switch to 3D and the same doors light up."),
    ("slide", 7, 7, "On 25,420 held-out questions: 87 percent correct, against 63 for the frontier model, at zero dollars."),
    ("slide", 10, 5, "Exact, verifiable, cheap. Blueprints That Talk."),
]


def ff(*a):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, a)], check=True)


def probe_dur(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


async def wait_step(pg, i, timeout_s=300):
    for _ in range(timeout_s * 10):
        if await pg.evaluate("window.__tourStepDone") == i:
            return
        await pg.wait_for_timeout(100)
    print(f"step {i + 1}: timed out")


async def record(url: str):
    WORK.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=ARGS)
        # cards
        pg = await b.new_page(viewport={"width": 1920, "height": 1080})
        for _, n, *_ in [s for s in SCENES if s[0] == "slide"]:
            await pg.goto((HERE / "deck.html").as_uri() + f"?slide={n}")
            await pg.wait_for_load_state("networkidle")
            await pg.evaluate("document.fonts.ready")
            await pg.screenshot(path=str(WORK / f"slide-{n}.png"))
        await pg.close()
        # warm the server caches so the take has no cold starts
        warm = await b.new_page()
        await warm.goto(url + "/")
        steps = await warm.evaluate("fetch('/api/tour').then(r => r.json())")
        for s in steps[:5]:
            await warm.evaluate("""s => Promise.all([
                fetch('/api/questions?path=' + encodeURIComponent(s.path)).then(r => r.json()).then(i =>
                  i.view ? fetch('/api/render?path=' + encodeURIComponent(i.view)) : null),
                fetch('/api/ask', {method: 'POST', headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({path: s.path, question: s.question})}),
                s.source && s.source.startsWith('ifc') ? fetch('/api/mesh?path=' + encodeURIComponent(s.path)) : null])""", s)
        await warm.close()
        # one take of tour steps 1-5
        ctx = await b.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=str(WORK),
                                  record_video_size={"width": 1920, "height": 1080})
        pg = await ctx.new_page()
        t0 = time.time()
        await pg.goto(url + "/")
        await pg.wait_for_timeout(2000)
        marks = []
        n_steps = max(s[1] for s in SCENES if s[0] == "step") + 1
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
    (WORK / "marks.json").write_text(json.dumps(marks))
    return raw, marks


def build(raw: Path, marks):
    clips = []
    for k, (kind, ref, dur, _) in enumerate(SCENES):
        c = WORK / f"scene-{k:02d}.mp4"
        if kind == "slide":
            ff("-loop", 1, "-t", dur, "-i", WORK / f"slide-{ref}.png", "-vf", "fps=30,format=yuv420p",
               "-c:v", "libx264", "-preset", "medium", "-crf", 20, c)
        else:
            a, e = marks[ref]
            seg = WORK / f"seg-{k:02d}.mp4"
            ff("-ss", f"{a:.2f}", "-to", f"{e:.2f}", "-i", raw, "-an", "-vf", "fps=30", "-c:v", "libx264",
               "-preset", "medium", "-crf", 20, seg)
            have = probe_dur(seg)
            if have >= dur:
                vf = f"setpts={dur / have:.5f}*PTS,fps=30"
            else:  # play up to 1.4x slower, then hold the finished frame
                slow = min(dur / have, 1.4)
                vf = f"setpts={slow:.4f}*PTS,tpad=stop_mode=clone:stop_duration={dur - have * slow + 0.5:.2f},fps=30"
            ff("-i", seg, "-vf", vf + ",format=yuv420p", "-t", dur, "-c:v", "libx264", "-preset", "medium",
               "-crf", 20, c)
            print(f"scene {k + 1}: recorded {have:.1f} s -> {dur} s")
        clips.append(c)
    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    out = OUT / "blueprints-2min.mp4"
    ff("-f", "concat", "-safe", 0, "-i", lst, "-c:v", "libx264", "-preset", "medium", "-crf", 21,
       "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-t", 120, out)
    # captions
    srt, t = [], 0.0
    for k, (_, _, dur, text) in enumerate(SCENES):
        def ts(x):
            return f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{int(round(x % 1 * 1000)):03d}"
        srt.append(f"{k + 1}\n{ts(t + 0.2)} --> {ts(t + dur - 0.2)}\n{text}\n")
        t += dur
    sp = OUT / "blueprints-2min.srt"
    sp.write_text("\n".join(srt))
    cap = OUT / "blueprints-2min-captions.mp4"
    style = "FontName=DejaVu Sans,FontSize=13,PrimaryColour=&H00FFFFFF,Alignment=2,MarginV=8,MarginL=40,MarginR=40"
    ff("-i", out, "-vf", f"scale=1632:918,pad=1920:1080:144:0:color=0x0b1220,subtitles={sp}:force_style='{style}'",
       "-c:v", "libx264", "-preset", "medium", "-crf", 21, "-pix_fmt", "yuv420p", "-movflags", "+faststart", cap)
    for p in (out, cap):
        print(f"{p}: {probe_dur(p):.2f} s, {p.stat().st_size // 1024 // 1024} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:3123")
    ap.add_argument("--rebuild", action="store_true", help="reuse the last take (runs/video/work) and only re-cut")
    a = ap.parse_args()
    assert sum(s[2] for s in SCENES) == 120, "scene durations must add up to 120 s"
    if a.rebuild:
        raw = max(WORK.glob("*.webm"), key=lambda p: p.stat().st_mtime)
        build(raw, json.loads((WORK / "marks.json").read_text()))
    else:
        build(*asyncio.run(record(a.url.rstrip("/"))))
