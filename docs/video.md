# Video: 2 minutes (strict), script and voice-over

One command builds the finished video (demo server on :3123 running):

```bash
.venv/bin/python docs/deck/make_video.py               # voice + cards + a new tour take + cut
.venv/bin/python docs/deck/make_video.py --reuse-take  # keep the last tour take, only re-cut
.venv/bin/python docs/deck/make_video.py --voice-only  # only synthesize and print the timing
```

Output (gitignored): `runs/video/blueprints-final.mp4` (1920×1080, H.264/AAC, ≤ 2:00) and
`runs/video/blueprints-final.srt`.

- **Voice-over:** Kokoro-82M (Apache-2.0), voice `af_heart` (American English), synthesized locally on CPU. No paid
  API. Each caption line is spoken on its own, so captions are timed exactly to the voice.
- **Timing follows the voice:** every scene lasts as long as its narration (0.35 s lead-in, 0.3 s between lines,
  0.45 s tail), and the build refuses to run past 120 s. The table below is rewritten on every build.
- **Picture:** a 2 s title card, deck slides 2 (frontier answers vs truth) and 4 (approach), cards for the frontier
  comparison, results, cost and the end, and one recorded take of demo tour steps 1–5 (`docs/deck/record_video.py`),
  each sped up / held to its scene length. The picture is scaled to 85 % with the caption band underneath, so
  neither the drawing credits nor the app's own tour captions are covered.
- The text lives in `SCENES` in `docs/deck/make_video.py` (caption and spoken form; numbers are spelled out for
  the voice). Gemini 3.1 Pro / Nemotron baselines: add them to `EXTRA_BASELINES` there once their numbers are
  final; they get a bar on the frontier card and a spoken line.

## Timing (generated)

<!-- TIMING -->
<!-- /TIMING -->

## Sources for every spoken number

- 88.2 % on 25,420 held-out test questions, 82.2 % Finnish (CubiCasa) plans, 100 % Swiss plans, 100 % IFC numeric
  questions: `docs/STATUS.md` headline and `docs/RESULTS.md` (`runs/router_full_test_v4`). Swiss is 100.0 % on counts
  and 99.9 % on areas; IFC free-text answers are 36.4 % (shown in the results card footnote).
- Claude Sonnet 5.5 63.2 % (drawing only) and 69.0 % (drawing + its CAD/IFC files): `docs/RESULTS.md`, 400-question
  stratified sample re-weighted to the test-split mix (`runs/baseline_sonnet_full400`, `runs/baseline_sonnetfair_full400`).
- $0.014 per 1,000 questions (ours, "1.4 cents") and $13–58 per 1,000 for frontier models: `docs/COSTS.md`
  ($57.67 Sonnet + files) and `docs/RESULTS.md` ($13.06 Sonnet re-weighted).
- Independent leakage audit: `docs/STATUS.md` (Codex audit, each finding re-verified).
- 94.73 m² vs 108.3 m² and 0 vs 110 windows: question ids 122272 and 88860 in `runs/baseline_sonnet_full400.jsonl`.
- "Twenty, matching the dataset": what the app shows for tour step 1 (the ✓ badge compares with the dataset answer).

## Credits on screen

Every drawing in the app shows its licence line under the drawing (Swiss Dwellings, CC BY 4.0; CubiCasa5K,
CC BY-NC-SA 4.0; Molio Demo-hus, CC BY 4.0); deck slide 2 carries its own, and the end card lists all datasets.
Training compute is "cloud GPUs (Verda)".
