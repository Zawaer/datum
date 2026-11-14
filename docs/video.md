# Video: storyboard for the 2:00 cut and the 60 s cut

"Datum" (tagline: blueprints that talk), Junction 2026, Stoa *Make Blueprints Talk*. Everything on screen is the real app (or an
animated results card) recorded live. Nothing is a static slide. The narration states what the picture is
showing at that moment.

```bash
# demo server running (default :3123, or pass --url); voice: one narrator, Protégé clone (--voices premade | cloned for the earlier takes)
.venv/bin/python docs/deck/make_video.py                      # 2:00 cut  -> runs/video/blueprints-full.mp4 (+ .srt)
.venv/bin/python docs/deck/make_video.py --cut short --reuse  # 60 s cut from the same recorded shots
.venv/bin/python docs/deck/make_video.py --voice-only         # voice + timing tables below, no recording
.venv/bin/python docs/deck/make_video.py --only sheet --out /tmp/sheet.mp4   # one shot with its voice
.venv/bin/python docs/deck/make_video.py --reuse              # re-cut the last recorded shots (e.g. after a text edit)
.venv/bin/python docs/deck/make_video.py --draft              # fast preview: 1080p captures, less slow-motion
```

**Voice (Toivo's final decision, 14 Nov).** One narrator reads every line, so the voice is consistent: Toivo's
ElevenLabs voice **Protégé narrator (clone)** (`AesrdOgpgZSXUSHb7gw3`, on his account's key `TOIVO_ELEVENLABS_KEY` in
the root-only `VOICES_ENV`, used only in request headers), on `eleven_multilingual_v2` (stability 0.6, similarity 0.75,
style 0). In a 2-line test against `eleven_v3`, v3 put a 1.15 s pause mid-line and read "Datum" as "Dartum"; v2 had no
gaps and transcribed back exactly. The spoken Finnish question stays the premade **George** clip (project key
`ELEVENLABS_API_KEY`, `data/secrets/elevenlabs.env`). Lines keep an A / B label (who would speak them in a two-voice
cut; `F` is the Finnish clip). Earlier takes stay selectable: `--voices premade` (George + Sarah, multilingual v2)
and `--voices cloned` (Toivo + Rene clones, eleven_v3). Each line in `SCENES` is `L(speaker, caption, spoken)`: the
spoken form spells numbers out; bracketed v3 audio tags are dropped for v2. Clips are cached per
voice/model/settings/text, so a re-cut costs nothing. Leading/trailing silence is trimmed. The final mix is
loudness-normalised to -14 LUFS (two-pass loudnorm on the voice, then one measured gain trim with a -1 dBFS limiter).

**Screen-recorded look.** A visible cursor glides (eased, on the page clock) to what is clicked and shows a click ring;
the ask box types itself; every cut between scenes is a 0.33 s whip-pan to the left with horizontal motion blur (same
total length: it uses the last/first 5 frames of the two scenes); slow push-ins (`rec.cam_on(..., over=2.5–4)`) sit on
the replay moments; card numbers count up with their bars; captions are short phrases (<= 54 chars) under the picture
for the whole video. Mouse input goes through `rec.move` (Input events land at x / DPR under the CDP metrics override).

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
captions sit underneath in Plex, left-aligned with the picture, cards included. The `.srt` sidecar has every line in full. On-screen chips are white boxes with a hairline in the top-left of
the drawing. IBM Plex Sans is fetched once into `cache/fonts/` for the captions.

## 2:00 storyboard

Story: question -> proof on the drawing -> check it, then the unseen-sheet test, then the numbers. Durations follow the
voice (generated table below). Paths are under `data/`. "Q:" is typed into the ask box exactly as written.

| # | shot (`id`) | on screen (exact action) | lines (one narrator; A / B = line split of the two-voice take) |
|---|---|---|---|
| 1 | **Hook** (`hook`) | Swiss door plan (`swiss_dwellings/site3387_bldg5238_floor23498.pdf`, Q: *How many doors (interior doors and entrance doors together) are drawn on this floor plan?*), full-bleed. The cursor clicks **3D**: the drawing tilts up, walls rise, the 20 doors pin 1…20; slow push-in. Chips: **20 doors, every one numbered**, then **Datum: blueprints that talk**. | A asks, B answers "Twenty." |
| 2 | **Problem** (`problem`, card) | Two grey bars count up: a leading AI model with the drawing's CAD/BIM files 69.8 %, drawing only 63.2 % (no model names on screen or spoken; sources below). | B: takeoffs by hand; A: seven in ten, just as sure when wrong |
| 3 | **Area + replay** (`ghost`) | `swiss_dwellings/site11487_bldg17991_floor47889.pdf`, German net-area question typed; the replay outlines each room while the sum ticks to **62.74 m²** under a slow push-in; then the app's **5 of 5 wrong** frontier strip. | A / B / A |
| 4 | **Correct by click** (`correct`) | Window question on the door plan; the cursor goes to evidence row #4, it is unticked and the total drops by one. | B |
| 5 | **Voice, Finnish → 3D** (`voice`) | `cubicasa5k/colorful-10052.png`. Cursor to the mic; the strip listens while the premade George voice asks *Kuinka monta ovea pohjapiirustuksessa on?* (audible), Transcribing → Asking; the detector's boxes (5 doors); then **3D**: the scan rises into a model with the doors pinned. | A, A (Finnish), B |
| 6 | **BIM in 3D** (`ifc`) | Molio Grundplan door question in 3D; cursor clicks *Show whole building*, *Explode storeys* (on the word), *X-ray*, then drags a slow orbit. | A / B |
| 7 | **Upload a sheet** (`sheet`) | Held-out DfE special school **Level 01** (vector PDF). Cursor opens the picker, *Upload your own*; the sheet loads with its chip and suggestions. Q: *How many group rooms are on this level?* The replay numbers the 5 group rooms (push-in), then **3D**: walls rise from the sheet's linework, the rooms stay painted; punch-in on the answer card. | B / A / B |
| 8 | **Whole project** (`project`) | Both school floors (Level 00 + Level 01) uploaded at once become one project. Q: *How many doors in the whole school?* → **171**, summed per floor (Level 00 122, Level 01 49); the cursor taps Level 01 to see its marks. | A / B |
| 9 | **Numbers** (`results`, card) | Our bar counts up to **90.7 %** in the accent, the leading AI model with the same files 69.8 % in grey. | A / B |
| 10 | **Cost** (`cost`, card) | **$0.013** vs **$25.76** per 1,000 questions, counting up. | A / B |
| 11 | **Close** (`end`, card) | *Datum blueprints that talk*, *Exact, verifiable, cheap.*, repo URL, credits. | B: not sure? it says so; low-res scans are the weak spot. A: tagline |

`xray` and `how`, `heat` are kept in the script but are out of both cuts.

## 60 s cut (`--cut short --reuse`)

Shots hook, problem, ghost, voice, sheet, results, cost, end with shorter lines (`"short"` in `SCENES`), cut from the
same recordings (a shot longer than its slot plays up to 1.6x and is then trimmed).

## Notes for the team

- **Re-run the captures after any UI change.** The shots rely on stable hooks: `window.__p3` (open / ready / `__p3riseMs`),
  `#p3go`, the app globals `ask()`, `res`, `animating`, `xr` (a replay in progress: a click would skip it, so 3D is
  clicked only after it ends), `doAction()`, `setMode()`, `openSec()`, `rowHot()`/`hotItem()`, `window.bpProject()`;
  the ids `#q`, `#go`, `#img`, `#viewer`, `#answer`, `#side`, `#mic`, `#voice`, `#drawerbtn`, `#uploadbox`, `#file`;
  `.ghostcmp`, `.ppart`; and the 3D buttons, found by their label. A failing shot prints its error and marks, and saves
  `runs/video/work/fail-<id>.png`.
- **Voice shot.** The strip's states are staged on the page (headless Chromium has no microphone; a click on the real mic
  says "No microphone found"), timed to the spoken Finnish question, which is in the soundtrack. The real path was
  checked with the same clip: `POST /api/transcribe` (ElevenLabs Scribe) returns *Kuinka monta ovea pohjapiirustuksessa on?*,
  language fin, p 0.98.
- **Sheet / project beats.** The sheet is a held-out sibling (DfE Level 01), not one of Stoa's example sheets; its credit
  line is on the end card ("DfE model special school, Level 01, Open Government Licence v3.0").

## Timing (generated, 2:00 cut)

<!-- TIMING -->
| # | time | shot | voice-over (caption text) |
|---|---|---|---|
| 1 | 0:00.00–0:08.50 | shot `hook` | **A** Ask a floor plan how many doors it has. **B** Twenty. And here is every single one. |
| 2 | 0:08.50–0:17.50 | card `problem` | **B** Takeoffs are still counted by hand. **A** And general AI, given the very same files? Seven answers in ten, **A** and just as sure when it's wrong. |
| 3 | 0:17.50–0:28.70 | shot `ghost` | **A** Datum shows its work. Ask, in German, for the living area, **B** and every room is outlined with its square metres, adding up on the drawing. **A** Five AI models, same drawing: all five wrong. |
| 4 | 0:28.70–0:33.67 | shot `correct` | **B** Check it in seconds: untick one, or click one in. The total follows. |
| 5 | 0:33.67–0:43.37 | shot `voice` | **A** On site? Just ask out loud, in Finnish. **F** Kuinka monta ovea pohjapiirustuksessa on? **B** Every door is boxed on the scan, and the plan rises into 3D. |
| 6 | 0:43.37–0:50.10 | shot `ifc` | **A** From a BIM model, the answer comes from the model itself. **B** Explode the storeys, and the evidence glows. |
| 7 | 0:50.10–1:06.10 | shot `sheet` | **B** And a sheet it has never seen? Here's a school plan, uploaded. **A** Upload it, ask, and watch it count the group rooms on the drawing. **B** Then tilt it up into 3D. |
| 8 | 1:06.10–1:15.60 | shot `project` | **A** A whole project? Drop in both floors and ask for every door in the school. **B** 171, floor by floor. Tap one to see its doors. |
| 9 | 1:15.60–1:24.63 | card `results` | **A** 90.7 % right on all 25,420 held-out test questions. **B** A leading AI model, given the same files: 69.8 %. |
| 10 | 1:24.63–1:30.83 | card `cost` | **A** $0.013 per 1,000 questions. **B** The AI model: $25.76. |
| 11 | 1:30.83–1:39.97 | card `end` | **B** Not sure? It says so instead of guessing. Low-res scans are its weak spot. **A** Exact. Verifiable. Cheap. Datum: blueprints that talk. |

Total 99.97 s; 235 words; voice elevenlabs ElevenLabs eleven_multilingual_v2, Protégé narrator (A) + Protégé narrator (B). Generated by `make_video.py`.
<!-- /TIMING -->

## Timing (generated, 60 s cut)

<!-- TIMING60 -->
| # | time | shot | voice-over (caption text) |
|---|---|---|---|
| 1 | 0:00.00–0:08.50 | shot `hook` | **A** Ask a floor plan how many doors it has. **B** Twenty. And here is every single one. |
| 2 | 0:08.50–0:13.50 | card `problem` | **A** General AI gets seven answers in ten right, and is just as sure when it's wrong. |
| 3 | 0:13.50–0:23.70 | shot `ghost` | **A** Datum shows its work. Ask, in German, for the living area: **B** every room outlined, adding up on the drawing. Five AI models: all five wrong. |
| 4 | 0:23.70–0:28.97 | shot `voice` | **A** Or ask out loud, in Finnish. **F** Kuinka monta ovea pohjapiirustuksessa on? |
| 5 | 0:28.97–0:37.47 | shot `sheet` | **B** And a school sheet it has never seen: upload, ask, watch it count. |
| 6 | 0:37.47–0:42.60 | card `results` | **A** 90.7 % right on all 25,420 held-out test questions. |
| 7 | 0:42.60–0:45.87 | card `cost` | **A** $0.013 per 1,000 questions. |
| 8 | 0:45.87–0:50.07 | card `end` | **A** Exact. Verifiable. Cheap. Datum: blueprints that talk. |

Total 50.07 s; 101 words; voice elevenlabs ElevenLabs eleven_multilingual_v2, Protégé narrator (A) + Protégé narrator (B). Generated by `make_video.py`.
<!-- /TIMING60 -->

## Sources for every number on screen or spoken

- **90.7 %** [95 % CI 90.4–91.1] on all **25,420** held-out test questions (spoken "ninety percent"), Swiss and IFC
  numeric 100 %, Finnish (CubiCasa) 86.1 %, IFC free text 38.2 %: `README.md`, `docs/RESULTS.md`, `runs/router_full_test_v8`.
- **Claude Sonnet 5.5 + sibling CAD/IFC files 69.8 %** (spoken "seventy"), drawing only 63.2 %, Gemini 3.1 Pro
  64.2 %: `README.md` results table (400-question stratified sample, re-weighted). "Seven answers in ten" = 69.8 %.
- **$0.013 vs $25.76 per 1,000 questions**, 0.06 s vs 15.7 s per question ("16 s"), "about 1,900 times cheaper"
  (25.76 / 0.013 ≈ 1,980; README says "about 1/1,900 of the cost"): `README.md`, `docs/COSTS.md`.
- **20 doors**, "Very likely right 99.95 %", "two independent methods agree": what the app shows for that plan
  (the ✓ badge compares with the dataset answer).
- **62.74 m², five frontier baselines all wrong (59 to 75 m²)**: tour step 2 caption in `app/tour.json` and the ghost
  strip (`app/frontier.json`, the baselines' recorded answers on that question).
- **5 doors on the Finnish scan, second model says 4**: tour step 4 caption in `app/tour.json`.
- **Sheet beat**: group rooms on the DfE Level 01 plan = 5 (`runs/stoa_examples_v8_hires.summary.md`, `ho_school2`, held-out split).
- **Project beat**: 171 doors = Level 00 122 + Level 01 49, what the app answers for the two DfE school floors as one project (c40450e).
- **Honesty line** ("weakest on low-res scans, and it says so"): `docs/PITCH.md` ("Scans and low-res school plans are the weak spot, and it says so").

## Credits on screen

Every drawing in the app shows its licence line under the drawing (Swiss Dwellings, CC BY 4.0; CubiCasa5K,
CC BY-NC-SA 4.0; Molio Demo-hus, CC BY 4.0). The end card lists all datasets. Training compute: "a local RTX 4070
and cloud GPUs (Verda)".
