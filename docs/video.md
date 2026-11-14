# Video: storyboard for the 2:00 cut and the 60 s cut

"Datum" (tagline: blueprints that talk), Junction 2026, Stoa *Make Blueprints Talk*. Everything on screen is the real app (or an
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

**Format and style** ([`docs/deck/DESIGN-RULES.md`](deck/DESIGN-RULES.md)). The video is 1920x1080 at 30 fps. The product
footage is the hero. Each card carries one idea in IBM Plex Sans 400/600, on the rules' scale and left-aligned. Ours is in
the accent #0072b2, frontier models are grey, and there are no eyebrow labels, gradients, shadows or footnotes.
The numbers' sources are listed below. The picture is scaled to 85 % on white with a 1 px #e4e7eb hairline. The
captions sit underneath in Plex, left-aligned with the picture, and are not burned in over the cards, whose text is
already on screen. The `.srt` sidecar has every line. On-screen chips are white boxes with a hairline in the top-left of
the drawing. IBM Plex Sans is fetched once into `cache/fonts/` for the captions.

## 2:00 storyboard

Durations are planned. The real ones follow the voice (table below, regenerated on every build). Paths are under
`data/`. "Q:" is typed into the ask box exactly as written.

| # | shot (`id`) | ~s | on screen (exact action) | narration | on-screen text |
|---|---|---|---|---|---|
| 1 | **Hook** (`hook`) | 0–8.5 (min 8.5 s) | Full-bleed 3D (picker and answer panel hidden). `swiss_dwellings/site3387_bldg5238_floor23498.pdf`, Q: *How many doors (interior doors and entrance doors together) are drawn on this floor plan?* already answered. `window.__p3.open()` with `__p3riseMs = 2600`: the drawing lies flat and tilts up into a low cut-away model. The 20 counted doors light up blue and are pinned 1…20 one after another. | "Ask a floor plan how many doors it has. Twenty. And here is every single one." | top-left chip: **20 doors, every one numbered** / *Read from the CAD layers. No AI model call.*, then **Datum: blueprints that talk** / *Junction 2026, Stoa: Make Blueprints Talk* |
| 2 | **Problem** (`problem`, card) | 8.5–19.5 | Light card with one chart. Three grey bars grow in turn: Sonnet 5.5 with its CAD/IFC files 69.8 %, Gemini 3.1 Pro 64.2 %, Sonnet drawing-only 63.2 %. | "Quantity takeoff is still done by hand. Frontier AI, given the very same files, gets seven answers in ten right, and sounds just as sure when it's wrong." | **Frontier models get 7 answers in 10 right, and sound just as sure when they are wrong.** |
| 3 | **How it works** (`how`) | 17–25 | `/how`: glide down to the routing chapter, where a question flies to its solver. Two further smooth scrolls through "proof on the drawing". | "So we don't guess. Every question goes to an exact method: the CAD geometry, the BIM model, or a small detector we trained." | (the page's own headings) |
| 4 | **X-ray count** (`xray`) | 25–35 | Same Swiss plan in 2D. The door question types itself. **X-ray**: the drawing greys back, each door lights up in turn and the HUD counts 1/20 … 20/20. Punch-in on the drawing during the count, then on the answer card: **20**, "Verified by geometry", "Very likely right · 99.95 %", "Two independent methods agree". | "Ask in plain words, and the X-ray counts every door on the drawing. A second, independent method agrees. No model call, zero cost." | (app HUD: *X-ray · counting 20 / 20*) |
| 5 | **Ghost comparison** (`ghost`) | 39–51 | `swiss_dwellings/site11487_bldg17991_floor47889.pdf`, Q (German): *Wie gross ist die Nettowohnfläche von Wohnung A in m² (…)?* Rooms outline with their m² while the running sum ticks up to **62.74 m²**. Room #1 is held highlighted for 3 s. `doAction('scroll:.vs')` opens the *Frontier models* section, then a punch-in on it shows the app's own **5 of 5 wrong**: our marker on the dataset line, five ghosts from 59 to 75 m², each labelled short or over. | "Asked in German: the net living area of apartment A. Every room carries its own square metres, and they add up to the answer. Five frontier models, same drawing: all five wrong." | none (the app's "5 of 5 wrong" is the text) |
| 6 | **Correct by click** (`correct`) | 47–53 | Door plan, Q: *How many windows are drawn on this floor plan?* Punch-in on the answer + evidence list. Window #4 highlights, is unticked, the row flashes and the total drops by one. | "Disagree? Untick an item, or click one we missed. The total follows." | |
| 7 | **Heat-map + takeoff** (`heat`) | 56–61 | German-area plan in 2D. `setHeat(true)` (view menu: *Room heat-map*) shades every room on one blue scale with its m², with a punch-in on the drawing. Then `openSheet()` (*Takeoff sheet*) opens the printable room schedule. | "One click shades every room by its area, and prints the takeoff sheet." | (the app's legend) |
| 8 | **Voice, in Finnish** (`voice`) | 60–68 | `cubicasa5k/colorful-10052.png`. Punch-in on the ask box: the mic strip goes *Listening → Transcribing → Asking* with *Kuinka monta ovea pohjapiirustuksessa on?*. Pan to the scan: the detector's boxes, 5 doors, and the second model's conflict flag. | "Or just ask out loud, in Finnish. Our detector boxes every door it counts." | (app strip) |
| 9 | **BIM in 3D** (`ifc`) | 66.5–75 | `ifc_models/bsc-molio_molio-with-uris_plan-03-grundplan.pdf`, Q: *How many doors are shown on the floor plan of 'Grundplan'?* The 3D model loads off camera. Then: *Show whole building*, punch-in, **Explode storeys** (seven storeys lift apart, the Grundplan storey tagged "evidence" with its 12 pinned doors), **X-ray**, slow orbit drag. Recorded at 2.5x more slow-motion (`SHOT_SLOW`). | "BIM models are answered from the model itself. Explode the storeys, X-ray the rest, and the evidence glows." | |
| 10 | **Upload a sheet** (`sheet`) | 75–90 (~15 s) | A sheet the app has never seen: the DfE special school *Level 01* plan as a vector PDF (from the public set listed in `docs/research/EXAMPLE-SOURCES.md`; a held-out sheet, not one of Stoa's example sheets). Drag it onto the upload box; the sheet-type chip and three suggested questions appear. Q: *How many group rooms are on this level?* The **replay** runs: scale bar first, then the five group rooms fill one by one with numbered pins while the total ticks to **5**. Then **See it in 3D**: the plan tilts up, walls rise from the drawing's own linework, the five rooms stay painted on the floor. Punch-in on the answer card's *how it was read* line. | "Final judging uses sheets nobody has seen. Upload one, ask, and watch the answer work itself out on the drawing. Then tilt it into 3D." | (the app's chip and answer card) |
| 11 | **Numbers** (`results`, card) | 90–100 | One chart: our bar grows in the accent blue to **90.0 %**, grey bars follow (69.8 % Sonnet with the same files, 64.2 % Gemini). | "Ninety percent right, on all twenty-five thousand held-out test questions. Claude Sonnet, given the same files: seventy." | **90 % right on all 25,420 held-out test questions.** |
| 12 | **Cost** (`cost`, card) | 100–106 | One number against another, at 200 px: **$0.013** (accent) vs **$25.76** (grey) per 1,000 questions. | "One point three cents per thousand questions. Sonnet: twenty-five dollars seventy-six." | **Cost per 1,000 questions** |
| 13 | **Close** (`end`, card) | 106–~112 | White end card: *Datum* with the tagline *blueprints that talk*, *Exact, verifiable, cheap.*, repo URL. The footer band holds the dataset licences and the voice credit. | "Exact. Verifiable. Cheap. Datum: blueprints that talk." | repo URL + credits |

With the ElevenLabs voice the 2:00 cut ran about 1:37 before the sheet beat (shot 10); with it, about 1:52. Kokoro is slower; check with `--voice-only`. The timing tables below are generated and do not include shot 10 until the next build.

## 60 s cut (`--cut short`)

Shots 1, 2, 4, 5, 6, 8, 11, 12, 13 with shorter lines. *How it works*, the heat-map, BIM 3D and the sheet upload are dropped.

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
| 9 | end | "Exact. Verifiable. Cheap. Datum: blueprints that talk." |

Shots that are longer than their narration are sped up to at most 1.6x and then trimmed. A shot that is shorter holds its last frame.

## Notes for the team

- **Status (14 Nov):** every shot has been run once against the simplified UI with `--draft` and checked frame by frame. **The final 2:00 / 60 s renders are on hold until the deck/app restyle lands.** Then run `make_video.py --tts elevenlabs` and `--cut short --tts elevenlabs`.
- **Sheet beat (shot 10), not yet in `SCENES`.** Add a `sheet` shot to `make_video.py` before `results`: upload with `page.set_input_files` on the upload input, wait for the sheet chip, ask, let the replay run at page speed (2–4 s, it is skipped by any key or click, so do not click), then press *See it in 3D* and wait for `window.__p3.ready`. Use a held-out sibling sheet (DfE Level 01, or DAF dorm A-1 with *What is the total first floor area?*, 28,770 SF from the sheet's table) rather than one of Stoa's own example sheets. Check first that the 3D toggle appears on that upload (walls come from `/api/walls`); if it does not, end the shot on the replay. Its credit line: "Drawing: DfE model special school, Level 01, Open Government Licence v3.0".
- **Phone inset:** `make_video.py --phone` records a 390x844 take at DPR 3 (`runs/video/phone-inset.mp4`, 1080x2336, about 17 s, no voice). It shows a staged Finnish voice question, the X-ray count, the answer sheet, and the in-context cards on pins #3 and #10 (`selectPin`).
- **Re-run the captures after any UI change.** The shots rely on stable hooks: `window.__p3` (open / ready / `__p3riseMs`), the app globals `ask()`, `res`, `animating`, `doAction()` (the tour's own action runner), `setMode()`, `setHeat()`, `openSheet()`, `selectPin()`, `sheetFull()`; the ids `#q`, `#img`, `#viewer`, `#answer`, `#side`, `#mic`, `#voice`; `.ghostcmp`; and the 3D buttons, found by their label (*Show whole building*, *Explode storeys*, *X-ray*). If the redesign renames one, fix that shot in `SHOTS` in `make_video.py`. A failing shot prints its error and keeps the frames it got.
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
| # | time | shot | voice-over (caption text) |
|---|---|---|---|
| 1 | 0:00.00–0:08.50 | shot `hook` | Ask a floor plan how many doors it has. Twenty. And here is every single one. |
| 2 | 0:08.50–0:19.47 | card `problem` | Quantity takeoff is still done by hand. Frontier AI, given the very same files, gets seven answers in ten right, and sounds just as sure when it's wrong. |
| 3 | 0:19.47–0:28.33 | shot `how` | So we don't guess. Every question goes to an exact method: the CAD geometry, the BIM model, or a small detector we trained. |
| 4 | 0:28.33–0:39.17 | shot `xray` | Ask in plain words, and the X-ray counts every door on the drawing. A second, independent method agrees. No model call, zero cost. |
| 5 | 0:39.17–0:50.77 | shot `ghost` | Asked in German: the net living area of apartment A. Every room carries its own square metres, and they add up to the answer. Five frontier models, same drawing: all five wrong. |
| 6 | 0:50.77–0:55.77 | shot `correct` | Disagree? Untick an item, or click one we missed. The total follows. |
| 7 | 0:55.77–1:01.00 | shot `heat` | One click shades every room by its area, and prints the takeoff sheet. |
| 8 | 1:01.00–1:06.53 | shot `voice` | Or just ask out loud, in Finnish. Our detector boxes every door it counts. |
| 9 | 1:06.53–1:14.83 | shot `ifc` | BIM models are answered from the model itself. Explode the storeys, X-ray the rest, and the evidence glows. |
| 10 | 1:14.83–1:24.83 | card `results` | 90.0 % right on all 25,420 held-out test questions. Claude Sonnet 5.5, given the same files: 69.8 %. |
| 11 | 1:24.83–1:31.13 | card `cost` | $0.013 per 1,000 questions. Sonnet: $25.76. |
| 12 | 1:31.13–1:37.07 | card `end` | Exact. Verifiable. Cheap. Datum: blueprints that talk. |

Total 97.07 s; 209 words; voice elevenlabs `21m00Tcm4TlvDq8ikWAM`. Generated by `make_video.py`.
<!-- /TIMING -->

## Timing (generated, 60 s cut)

<!-- TIMING60 -->
| # | time | shot | voice-over (caption text) |
|---|---|---|---|
| 1 | 0:00.00–0:08.50 | shot `hook` | Ask a floor plan how many doors it has. Twenty. And here is every single one. |
| 2 | 0:08.50–0:14.13 | card `problem` | Frontier AI gets seven answers in ten right, and sounds just as sure when it's wrong. |
| 3 | 0:14.13–0:19.47 | shot `xray` | Ask in plain words. The X-ray counts every door on the drawing. |
| 4 | 0:19.47–0:27.33 | shot `ghost` | In German: every room's square metres add up to the answer. Five frontier models, same drawing: all five wrong. |
| 5 | 0:27.33–0:32.33 | shot `correct` | Disagree? Untick an item, or click one we missed. The total follows. |
| 6 | 0:32.33–0:34.77 | shot `voice` | Or ask out loud, in Finnish. |
| 7 | 0:34.77–0:44.77 | card `results` | 90.0 % right on all 25,420 held-out test questions. Claude Sonnet 5.5, given the same files: 69.8 %. |
| 8 | 0:44.77–0:51.07 | card `cost` | $0.013 per 1,000 questions. Sonnet: $25.76. |
| 9 | 0:51.07–0:57.00 | card `end` | Exact. Verifiable. Cheap. Datum: blueprints that talk. |

Total 57.00 s; 111 words; voice elevenlabs `21m00Tcm4TlvDq8ikWAM`. Generated by `make_video.py`.
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
- **Sheet beat (shot 10)**: group rooms on the DfE Level 01 plan = 5 (`runs/stoa_examples_final_hires.summary.md`, `ho_school2`, held-out split).

## Credits on screen

Every drawing in the app shows its licence line under the drawing (Swiss Dwellings, CC BY 4.0; CubiCasa5K,
CC BY-NC-SA 4.0; Molio Demo-hus, CC BY 4.0). The end card lists all datasets. Training compute: "a local RTX 4070
and cloud GPUs (Verda)".
