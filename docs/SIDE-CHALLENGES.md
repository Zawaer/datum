# Side-challenge submission texts: Datum (blueprints that talk)

Ready-to-paste texts for the tech challenges we entered (locked list in [TRACKS.md](TRACKS.md)). Main challenge:
Stoa, "Make Blueprints Talk". Numbers come from `README.md`, `docs/COSTS.md` and `analysis/infra.json`; sources are
in the facts table of [VERDA.md](VERDA.md). Placeholders to fill in at submission: `<DEMO_URL>`, `<REPO_URL>`,
`<RESULT>` (outcome of the Sat 14.11 sweep), `<SWEEP_COST>` (its GPU-hours and $, not yet in COSTS.md),
`<CRACI_BUILD_URL>`.

---

## 1. Verda Compute Track

Required: summary + Discord post. Same texts as [VERDA.md](VERDA.md).

### Summary (≤ 300 words)

Datum answers questions about construction drawings and BIM models, with the proof drawn on
the plan. On all 25,420 held-out test questions it is right 90.0 % of the time at $0.013 per 1,000 questions in
API fees; Claude Sonnet 5.5 given the same CAD/IFC files gets 69.8 % at $25.76 per 1,000.

Verda ran four parts of it:

1. **Overnight fine-tune, 2× H100 80GB.** 14.9 GPU-hours, $77.33. One
   LoRA-tuned Qwen3-VL-8B on dev drawings to count symbols with one box per item: 42.6 %
   zero-shot to 76 % on dev, 74.9 % on all 16,496 Finnish-plan test questions. The other tried PaliGemma 2
   (52 %, not shipped). The model is weaker than our detector (85.1 %), so it ships as an independent second
   opinion: when both agree (73.8 %), answers are 94.9 % right.
2. **Today's sweep, 2× H100.** A bigger detector and detector-vs-VLM arbitration, selected by whole-pipeline
   cross-validation on dev drawings. <RESULT>
3. **Live serving, RTX PRO 6000 96GB ($2.89/h).** The fine-tuned model checks users' own uploaded plans. It runs
   on demand: an upload starts the GPU, it stops when idle, and a daily cap bounds the bill. 96 GB holds the 8B
   model at a little over half the H100 rate.
4. **Public demo, CPU.4V.16G VM** (Docker + Caddy), $0.048/h: numeric answers need no GPU.

Verda so far: $99.83 of our $196.68 build cost, plus the sweep (<SWEEP_COST>).

**How it scales.** Per 1,000 questions we pay $0.013 in API fees plus about $0.006 of local compute; the VLM
second opinion adds $0.16 per 1,000 on one H100 (16,496 questions in 31 minutes). Next step: serve the model from Verda's autoscaling
serverless containers (scale to zero, scale with load) and run re-checks of a whole drawing set, every revision, as batch jobs.

Demo: `<DEMO_URL>` · Code: `<REPO_URL>`

### Discord post (≤ 120 words)

Datum (Stoa "Make Blueprints Talk") on Verda. Two H100s overnight (14.9 GPU-h, $77.33):
we LoRA-tuned Qwen3-VL-8B to count symbols on floor plans with one box per item, 42.6 % zero-shot to 76 % on
dev. It ships as a second opinion to our detector: when both agree, answers are 94.9 % right. Today 2× H100
swept a bigger detector plus VLM arbitration: <RESULT>. An RTX PRO 6000 serves the model live on users'
uploads, started on upload, stopped when idle, capped daily. The demo runs on a CPU VM for $0.048/h. Whole
system: 90.0 % on 25,420 test questions at $0.013 per 1,000.
Demo: `<DEMO_URL>` · Code: `<REPO_URL>`

---

## 2. Best Use of ElevenLabs (MLH)

### Text (≤ 200 words)

On site, hands are busy, gloves are on and crews speak many languages. In Datum you tap the
mic in any browser and ask a drawing a question. ElevenLabs Scribe (scribe_v2) transcribes it and
detects the language; we answer from the drawing and show the counted items on the plan. The answer is
spoken back with Flash v2.5 in the question's language: English, Finnish, German, French,
Italian, Dutch or Swedish. One short sentence: the number, how it was found ("Verified by geometry") and how
often that method is right.

Measured in our spend ledger: Scribe transcribed a 3.6 s question in 0.38 s for $0.0004; Flash v2.5 test calls
returned audio in a median 0.3 s.

Safeguards: the server only speaks answers it produced itself (the browser sends an answer id, never text),
so the endpoint cannot be used to read arbitrary text. Recordings are never stored and are
capped at 2 MB / 60 s; per-visitor rate limits, 15–20 s timeouts and a $2 daily cap each for speech-to-text and
text-to-speech.

Our demo video is narrated with an ElevenLabs voice.

Demo: `<DEMO_URL>` · Code: `<REPO_URL>` (`app/speak.py`, `/api/transcribe`, `/api/speak` in `app/server.py`)

---

## 3. Best Use of CRACI

### Text (≤ 200 words)

Our CI (`.github/workflows/ci.yml`) runs on CRACI runners (`runs-on: craci`) on every push:
byte-compile, ruff (pyflakes errors) and 291 pytest tests that need no dataset, weights or API keys. Each
build leaves a CycloneDX SBOM of everything the job installed.

Why that matters to us: our public demo accepts untrusted uploads (PDF, DXF, IFC and images) and parses them
with PyMuPDF (MuPDF), IfcOpenShell, ezdxf, Pillow and OpenCV, most of them native code. A malformed file is the likeliest
way in, so the SBOM CRACI records per build is exactly the list we need to watch for parser CVEs.

Today we fixed 10 security findings: unsafe serving of uploaded files (SVG/HTML), decompression
bombs (GIF/TIFF frames, pixel and size budgets), local file reads through DXF image references, endpoints
reachable for arbitrary drawings, resource exhaustion (concurrency limits), rate-limit bypass through spoofed
proxy headers, a race in the LLM spend cap, exposed API docs, raw exception text in responses, and missing
browser security headers (CSP, framing, permissions). Several are now regression tests.

Next step: fail the build when the SBOM contains a parser dependency with a known vulnerability, so we
never ship a version that a drawing can attack.

Build: `<CRACI_BUILD_URL>` · Code: `<REPO_URL>`

---

## 4. Tech used (main Stoa form, if asked)

Python, FastAPI, IfcOpenShell, ezdxf, PyMuPDF, Shapely, NumPy, Ultralytics YOLO11m (symbol detector, trained on
a local RTX 4070), PyTorch, Hugging Face Transformers + PEFT (Qwen3-VL-8B LoRA fine-tune and live serving), vLLM (batch evaluation),
three.js (3D plans and BIM viewer), ElevenLabs Scribe (voice questions) and Flash v2.5 text-to-speech (spoken
answers, video narration), Claude Haiku 5.5 (free-text BIM answers, LLM judge), Docker and Caddy (demo server),
Verda (2× H100 80GB for fine-tuning and the detector sweep, RTX PRO 6000 for live serving, CPU VM for the public
demo), CRACI runners for CI with build SBOMs, pytest and ruff, Playwright (demo recording and UI checks).
Baselines only: Claude Sonnet 5.5, Gemini 3.1 Pro, Nemotron 3.5 Super VL. Development: Claude Code, and Codex
for one independent audit of the evaluation.
