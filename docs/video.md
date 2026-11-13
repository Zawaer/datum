# Video: 2 minutes (strict), script and voice-over

Visual track: `.venv/bin/python docs/deck/record_video.py` (demo server running) records the demo tour and the
deck cards at 1920×1080 and cuts every scene to the slot below, so the file is exactly 120 s:

- `runs/video/blueprints-2min.mp4`: video only, for recording the voice-over on top
- `runs/video/blueprints-2min-captions.mp4`: the same with the voice-over text burned in as captions
  (picture scaled to 85 %, captions in a band underneath so no drawing credit is covered)
- `runs/video/blueprints-2min.srt`: the captions as a file

The scenes and their text live in `SCENES` in `docs/deck/record_video.py`; change both places together.
Pace: ~2.4 words per second. Read the numbers as written (they are all from `runs/*.summary.md`).

| # | time | on screen | voice-over |
|---|---|---|---|
| 1 | 0:00–0:08 | Deck slide 1: title, 87.2 % · $0 · 0.03 s | Blueprints That Talk. Ask a construction drawing or a BIM model anything, and see exactly where the answer came from. |
| 2 | 0:08–0:22 | Slide 2: two real frontier answers vs the truth | Quantity takeoff is still done by hand. Ask a frontier model and you get confident answers: 94.73 square metres instead of 108.3, or zero windows instead of 110. |
| 3 | 0:22–0:32 | Slide 3: Sonnet accuracy per source and type | We measured it on our held-out test split. Claude Sonnet gets 63 percent right, and most measurements wrong, at 13 dollars per thousand questions. |
| 4 | 0:32–0:40 | Slide 4: router → exact solvers → proof | So we don't guess. A router sends each question to an exact solver, and every solver returns its proof. |
| 5 | 0:40–0:58 | App, tour step 1: Swiss plan, doors numbered one by one, ✓ matches the dataset answer | A Swiss apartment plan: how many doors? We read them straight from the CAD layers and number every one on the drawing. Twenty, matching the dataset. No model call, zero cost. |
| 6 | 0:58–1:12 | Tour step 2: question typed in German, 9 rooms outlined with m², sum 107.40 m² | Ask in German for the net living area of apartment A. Every room is outlined with its own square metres, and the list adds up to the answer. |
| 7 | 1:12–1:22 | Tour step 3: a window is unticked, the count drops, then it is ticked again | Disagree? Untick an item, or click one we missed. The total updates on the spot: the evidence is the answer. |
| 8 | 1:22–1:34 | Tour step 4: CubiCasa plan asked in Finnish, doors boxed by the detector | A Finnish plan, asked in Finnish: a small detector, trained only on open annotations, boxes every door it counts. |
| 9 | 1:34–1:48 | Tour step 5: plan rendered from an IFC model, doors numbered, then the 3D view with the doors lit | Plans rendered from a BIM model are answered from the model itself. The doors are IFC elements: switch to 3D and the same doors light up. |
| 10 | 1:48–1:55 | Slide 7: results table and cost tiles | On 25,420 held-out questions: 87 percent correct, against 63 for the frontier model, at zero dollars. |
| 11 | 1:55–2:00 | Slide 10: team, repo | Exact, verifiable, cheap. Blueprints That Talk. |

Word count of the voice-over: 237 words for 120 s (about 2 words per second, leaving room to breathe).

## Sources for every spoken number

- 87 % (87.2 %), 25,420 questions, $0, 0.03 s: `runs/router_full_test.summary.md`
- 63 % (63.2 %), $13 ($13.06) per 1,000: `runs/baseline_sonnet_full400.summary.md`, a 400-question stratified
  sample of the test split re-weighted to the test-split mix (footnote on slides 3 and 7)
- 94.73 m² vs 108.3 m² and 0 vs 110 windows: question ids 122272 and 88860 in `runs/baseline_sonnet_full400.jsonl`;
  our answers (108.29 m², 110) in `runs/router_full_test.jsonl`
- "Twenty, matching the dataset" and the 9 rooms: what the app shows for those tour questions (the ✓ badge
  compares with the dataset answer)

## Credits on screen

Every drawing in the app shows its licence line under the drawing (Swiss Dwellings, CC BY 4.0; CubiCasa5K,
CC BY-NC-SA 4.0; Molio Demo-hus, CC BY 4.0); the deck slides carry the same credits. Keep them visible when
editing the video (don't crop the bottom of the app frames).

## Recording the voice-over

Record the narration against `blueprints-2min.mp4` (one take per row is fine), then mix:

```bash
ffmpeg -i runs/video/blueprints-2min.mp4 -i voice.wav -c:v copy -c:a aac -b:a 160k -shortest -t 120 final.mp4
```
