# Video: storyboard for the 2:00 cut and the 60 s cut

"Blueprints That Talk", Junction 2026, Stoa *Make Blueprints Talk*. Everything on screen is the real app (or an
animated results card) recorded live. Nothing is a static slide. The narration states what the picture is
showing at that moment.

```bash
# demo server running (default :3123, or pass --url)
.venv/bin/python docs/deck/make_video.py                      # 2:00 cut  -> runs/video/blueprints-full.mp4 (+ .srt)
.venv/bin/python docs/deck/make_video.py --cut short          # 60 s cut  -> runs/video/blueprints-short.mp4
.venv/bin/python docs/deck/make_video.py --voice-only         # voice + timing tables below, no recording
.venv/bin/python docs/deck/make_video.py --only hook --out /tmp/hook.mp4   # one shot with its voice
.venv/bin/python docs/deck/make_video.py --reuse              # re-cut the last recorded shots (e.g. after a text edit)
.venv/bin/python docs/deck/make_video.py --draft              # fast preview: 1080p captures, less slow-motion
.venv/bin/python docs/deck/make_video.py --tts elevenlabs     # ElevenLabs voice if the key allows TTS, else Kokoro
.venv/bin/python docs/deck/make_video.py --voice-wav fi.wav   # real voice shot: the WAV is played into the mic
```

**How it records.** Headless Chromium in our container has no GPU driver (only CUDA compute is passed through:
`--use-angle=vulkan` / `--enable-gpu` still report SwiftShader), so the 3D is rendered in software. Shots are therefore
recorded in **slow motion**. The page clock runs 8x slower (`performance.now`, `requestAnimationFrame`, timers, CSS
animations), a loop grabs 3840x2160 frames stamped with page time, and they are resampled to a steady 30 fps.
Playback is smooth at real speed however slow the renderer is. The 4K frames also allow sharp **punch-ins**
(`rec.cam` / `rec.cam_on` in the script). A full 2:00 build takes roughly 25–40 min wall time. `--draft` takes about a quarter of that.

**Format.** 1920x1080, 30 fps. The picture is scaled to 85 % so the caption band underneath never covers the drawing
credits. Burned-in captions (+ `.srt`) use the caption text from the script, and the voice is loudness-normalised. Voice: Kokoro-82M
`af_heart` (Apache-2.0, local) by default. With `--tts elevenlabs` (or `auto`) the script probes the ElevenLabs key once. On
14 Nov the key **did** pass the TTS probe (voice `21m00Tcm4TlvDq8ikWAM` "Rachel", `eleven_multilingual_v2`; set
`ELEVENLABS_VOICE_ID` for another), so the ElevenLabs voice is available. A 401/403 falls back to Kokoro (the key is never printed).
With ElevenLabs the 2:00 cut times at about 1:34 and Kokoro is slower, so check `--voice-only` before deciding to add a line.
The end card credits whichever voice engine was used.

## 2:00 storyboard

Durations are planned. The real ones follow the voice (table below, regenerated on every build). Paths are under
`data/`. "Q:" is typed into the ask box exactly as written.

| # | shot (`id`) | ~s | on screen (exact action) | narration | on-screen text |
|---|---|---|---|---|---|
| 1 | **Hook** (`hook`) | 0–8.5 (min 8.5 s) | Full-bleed 3D (side panels hidden). `swiss_dwellings/site3387_bldg5238_floor23498.pdf`, Q: *How many doors (interior doors and entrance doors together) are drawn on this floor plan?* already answered. **See it in 3D**: the flat plan, seen from straight above, rises into a building over 2.6 s (`window.__p3riseMs = 2600`). The camera tilts to three-quarter view and the 20 counted doors glow blue and pop up numbered 1…20, one after another. | "Ask a floor plan how many doors it has. Twenty. And here is every single one." | chip: **20 doors · every one numbered** / *read from the CAD layers · no AI model call · $0*, then **Blueprints That Talk** / *Junction 2026 · Stoa: Make Blueprints Talk* |
| 2 | **Problem** (`problem`, card) | 6–17 | Animated card: three orange bars grow in turn. Sonnet 5.5 + its CAD/IFC files 69.8 %, Gemini 3.1 Pro 64.2 %, Sonnet drawing-only 63.2 %. | "Quantity takeoff is still done by hand. Frontier AI, given the very same files, gets seven answers in ten right, and sounds just as sure when it's wrong." | **Frontier models get about 7 answers in 10 right, and sound just as sure when they are wrong.** |
| 3 | **How it works** (`how`) | 17–25 | `/how`: glide down to the routing chapter, where a question flies to its solver. Two further smooth scrolls through "proof on the drawing". | "So we don't guess. Every question goes to an exact method: the CAD geometry, the BIM model, or a small detector we trained." | (the page's own headings) |
| 4 | **X-ray count** (`xray`) | 25–35 | Same Swiss plan in 2D. The door question types itself. **X-ray**: the drawing greys back, each door lights up in turn and the HUD counts 1/20 … 20/20. Punch-in on the drawing during the count, then on the answer card: **20**, "Verified by geometry", "Very likely right · 99.95 %", "Two independent methods agree". | "Ask in plain words, and the X-ray counts every door on the drawing. A second, independent method agrees. No model call, zero cost." | (app HUD: *X-ray · counting 20 / 20*) |
| 5 | **Ghost comparison** (`ghost`) | 35–47 | `swiss_dwellings/site11487_bldg17991_floor47889.pdf`, Q (German): *Wie gross ist die Nettowohnfläche von Wohnung A in m² (…)?* Rooms outline with their m² while the running sum ticks up to **62.74 m²**. Hover room #1. Scroll to the ghost strip, then punch in on it: our marker on the dataset line, five ghost markers for the frontier baselines spread from 59 to 75 m², each labelled "short" or "over". | "Asked in German: the net living area of apartment A. Every room carries its own square metres, and they add up to the answer. Five frontier models, same drawing: all five wrong." | chip: **5 frontier models · same drawing · all 5 wrong** / *dataset answer 62.74 m² · they said 59 to 75 m²* |
| 6 | **Correct by click** (`correct`) | 47–53 | Door plan, Q: *How many windows are drawn on this floor plan?* Punch-in on the answer + evidence list. Window #4 highlights, is unticked, the row flashes and the total drops by one. | "Disagree? Untick an item, or click one we missed. The total follows." | |
| 7 | **Heat-map + takeoff** (`heat`) | 53–60 | German-area plan in 2D: **Heat-map** shades every room on one blue scale with its m² and per-apartment totals. Then **Takeoff sheet** opens the printable room schedule. | "One click shades every room by its area, and prints the takeoff sheet." | (legend: *Net area per room*) |
| 8 | **Voice, in Finnish** (`voice`) | 60–68 | `cubicasa5k/colorful-10052.png`. Punch-in on the ask box: the mic strip goes *Listening → Transcribing → Asking* with *Kuinka monta ovea pohjapiirustuksessa on?*. Pan to the scan: the detector's boxes, 5 doors, and the second model's conflict flag. | "Or just ask out loud, in Finnish. Our detector boxes every door it counts." | (app strip) |
| 9 | **BIM in 3D** (`ifc`) | 68–79 | `ifc_models/bsc-molio_molio-with-uris_plan-03-grundplan.pdf`, Q: *How many doors are shown on the floor plan of 'Grundplan'?* Switch to 3D, **Explode storeys** (floors lift apart), **X-ray** (everything but the evidence goes to faint outlines, counted doors glow), slow orbit drag. | "BIM models are answered from the model itself. Explode the storeys, X-ray the rest, and the evidence glows." | |
| 10 | **Numbers** (`results`, card) | 79–92 | Animated card: blue bar grows to **90.0 %**, orange bars follow (69.8 % Sonnet + files, 64.2 % Gemini). | "Ninety percent right, on all twenty-five thousand held-out test questions. Claude Sonnet, given the same files: seventy." | **90.0 % right on all 25,420 held-out test questions.** |
| 11 | **Cost** (`cost`, card) | 92–100 | Two big numbers slide in, **$0.013** vs **$25.76** per 1,000 questions, then "about 1,900 times cheaper, 0.04 s per answer instead of 16 s". | "One point three cents per thousand questions. Sonnet: twenty-five dollars seventy-six." | **Exact answers don't need a giant model.** |
| 12 | **Close** (`end`, card) | 100–~106 | Navy end card: title, *Exact · verifiable · cheap*, repo URL, dataset credits. | "Exact. Verifiable. Cheap. Blueprints That Talk." | repo URL + credits |

At the current narration the 2:00 cut runs about 1:50, which leaves ~10 s of slack for one more line.

## 60 s cut (`--cut short`)

Shots 1, 2, 4, 5, 6, 8, 10, 11, 12 with shorter lines. *How it works*, the heat-map and BIM 3D are dropped.

| # | shot | narration |
|---|---|---|
| 1 | hook | "Ask a floor plan how many doors it has. Twenty. And here is every single one." |
| 2 | problem | "Frontier AI gets seven answers in ten right, and sounds just as sure when it's wrong." |
| 3 | xray | "Ask in plain words. The X-ray counts every door on the drawing." |
| 4 | ghost | "In German: every room's square metres add up to the answer. Five frontier models, same drawing: all five wrong." |
| 5 | correct | "Disagree? Untick an item, or click one we missed. The total follows." |
| 6 | voice | "Or ask out loud, in Finnish." |
| 7 | results | "Ninety percent right, on all twenty-five thousand held-out test questions. Claude Sonnet, given the same files: seventy." |
| 8 | cost | "One point three cents per thousand questions. Sonnet: twenty-five dollars seventy-six." |
| 9 | end | "Exact. Verifiable. Cheap. Blueprints That Talk." |

Shots that are longer than their narration are sped up to at most 1.6x and then trimmed. A shot that is shorter holds its last frame.

## Notes for the team

- **Re-run the captures after the UI redesign lands.** The shots rely on stable hooks: `window.__p3` (open / ready / `__p3riseMs`), the app globals `ask()`, `res`, `animating`, `doAction()` (the tour's own action runner), `setMode()`, and the ids `#q`, `#viewer`, `#answer`, `#side`, `#heatbtn`, `#sheetbtn`, `#mic`, `#voice`, `.v3bar`, `.ghostcmp`. If the redesign renames one, fix that shot in `SHOTS` in `make_video.py`. A failing shot prints its error and keeps the frames it got.
- **Voice shot.** Without `--voice-wav`, the voice strip is *staged*: the script plays the same states the
  app shows (Listening → Transcribing → Asking) and then asks the Finnish question as text. For the real
  ElevenLabs Scribe path, record a teammate saying *"Kuinka monta ovea pohjapiirustuksessa on?"* (WAV, mono 16 or
  48 kHz) and pass `--voice-wav`. Chromium's fake microphone plays it into the real mic flow, and the server
  transcribes it. Use the real path if the voice moment is described as live.
- **Narration edits:** change `SCENES` in `docs/deck/make_video.py` (caption, spoken form). Then run `--voice-only` to
  check the length, and `--reuse` to re-cut without re-recording.
- **A shot looks wrong:** re-record just that one (`--only ghost`, output to a scratch file) and check the frames
  under `runs/video/work/shot-<id>/`. Then run the full build with `--reuse` once every shot is good. A run prints the
  capture rate per shot. Below 24 fps it says "raise --slow".
- **GPU:** `--gpu` launches Chromium with `--use-angle=vulkan --enable-gpu`. It only helps if the container is given
  the NVIDIA graphics libraries (`NVIDIA_DRIVER_CAPABILITIES` incl. `graphics`). Today it is not, and the
  script prints the WebGL renderer it got.

## Timing (generated, 2:00 cut)

<!-- TIMING -->
(run `make_video.py --voice-only`)
<!-- /TIMING -->

## Timing (generated, 60 s cut)

<!-- TIMING60 -->
(run `make_video.py --cut short --voice-only`)
<!-- /TIMING60 -->

## Sources for every number on screen or spoken

- **90.0 %** [95 % CI 89.7–90.4] on all **25,420** held-out test questions, Swiss and IFC numeric 100 %, Finnish
  (CubiCasa) 85.1 %, IFC free text 38.2 %: `README.md`, `docs/RESULTS.md`, `runs/router_full_test_v7`.
- **Claude Sonnet 5.5 + sibling CAD/IFC files 69.8 %** (spoken "seventy"), drawing only 63.2 %, Gemini 3.1 Pro
  64.2 %: `README.md` results table (400-question stratified sample, re-weighted). "Seven answers in ten" = 69.8 %.
- **$0.013 vs $25.76 per 1,000 questions**, 0.04 s vs 15.7 s per question ("16 s"), "about 1,900 times cheaper"
  (25.76 / 0.013 ≈ 1,980; README says "about 1/1,900 of the cost"): `README.md`, `docs/COSTS.md`.
- **20 doors**, "Very likely right 99.95 %", "two independent methods agree": what the app shows for that plan
  (the ✓ badge compares with the dataset answer).
- **62.74 m², five frontier baselines all wrong (59 to 75 m²)**: tour step 2 caption in `app/tour.json` and the ghost
  strip (`app/frontier.json`, the baselines' recorded answers on that question).
- **5 doors on the Finnish scan, second model says 4**: tour step 4 caption in `app/tour.json`.

## Credits on screen

Every drawing in the app shows its licence line under the drawing (Swiss Dwellings, CC BY 4.0; CubiCasa5K,
CC BY-NC-SA 4.0; Molio Demo-hus, CC BY 4.0). The end card lists all datasets. Training compute: "a local RTX 4070
and cloud GPUs (Verda)".
