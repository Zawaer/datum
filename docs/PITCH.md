# Live pitch: Datum (blueprints that talk)

Junction 2026, Stoa challenge *Make Blueprints Talk*. Judged 25 % each on **accuracy**, **visualising reasoning
for verification**, **creativity** and **low inference cost**. This page has the 3-minute talk, a 90-second cut,
the live-demo run sheet with fallbacks, and short answers to the questions judges are likely to ask.

Every number here is quoted from [README.md](../README.md) (headline and verification), the deck
([docs/deck/deck.html](deck/deck.html)) or [docs/UPLOADS.md](UPLOADS.md). If one of those changes, change it
here too. Deck slide numbers refer to `docs/deck/deck.pdf` (12 slides).

**Two screens, one laptop.** Tab 1: the demo, with the hook drawing already open (run sheet below). Tab 2: the
deck PDF in full-screen presenter mode. Switch with Ctrl/Cmd+Tab or Alt+Tab. Speaker A talks, speaker B drives.
Rehearse the switch: it is the only thing that can eat time.

---

## 1. The 3-minute talk

About 470 spoken words: a brisk 160 per minute, so rehearse with a timer. **Bold** = say it with weight. *[brackets]* = what's on screen
or what the driver does. Numbers are written the way you say them.

### 0:00–0:25 · Hook (live demo, tab 1)

*[Demo: Swiss apartment plan `site3387_bldg5238_floor23498.pdf` open, empty ask box. Driver clicks the mic.]*

> *(into the mic)* "Kuinka monta ovea?"

*[Strip: Listening → Transcribing → Asking. The plan greys out and the X-ray count runs, 1 / 20 … 20 / 20.]*

> I just asked this floor plan, in Finnish, how many doors it has.
> **Twenty. Each one numbered, each one checkable.**

*[Driver clicks **See it in 3D**: the plan rises into a building, the 20 doors glow and number themselves.]*

> And there they are, in the building.
> That answer came from the CAD file. No AI model call. Zero cents.

(Checked: "Kuinka monta ovea?" on this plan answers 20 through the CAD solver, with no model call and $0.)

### 0:25–0:55 · Problem (slides 2 and 3)

*[Switch to the deck, slide 2: two wrong frontier answers.]*

> Every construction estimate starts with a takeoff: count the doors, measure the rooms.
> Today that's done by hand, and it's slow. AI could do it, but nobody trusts it.
> Here's why. We asked Claude Sonnet for the floor area of this apartment.
> It said ninety-four point seven three square metres. **The answer is one hundred and eight point three.**
> It even had the CAD file.

*[Slide 3: the fair baseline bars.]*

> Given the same CAD and BIM files, a frontier model gets **about seventy percent** right.
> And the wrong answers look exactly as confident as the right ones.

### 0:55–1:25 · How (slide 4)

*[Slide 4: the router diagram.]*

> So we don't ask a model to guess.
> We send each question to the **cheapest method that can answer it exactly.**
> A CAD plan? We read the doors and rooms straight from the CAD layers.
> A BIM model? We read the IFC.
> A scanned plan? A small symbol detector we trained ourselves.
> A language model only sees the free-text questions.
> That's **zero point four percent** of the questions.
> The model chooses what to measure. **Geometry does the measuring.**

### 1:25–1:55 · Proof (slide 8)

*[Slide 8: the results table. Point at the "All test questions" row, then the cost tiles.]*

> We tested on drawings we never trained on.
> **All twenty-five thousand, four hundred and twenty questions.** Every one, not a sample.
> We're right **ninety point zero percent** of the time.
> Claude Sonnet, given the same files: sixty-nine point eight.
> That's twenty points better, at about **one nineteen-hundredth of the cost**.
> One point three cents per thousand questions, against twenty-five dollars seventy-six.
> On CAD plans and BIM models we're at essentially one hundred percent.
> Scanned plans are the hard part. There we get eighty-five point one, and Sonnet gets sixty-three point six.

### 1:55–2:35 · Verification (live demo, tab 1; slide 9 if the demo is down)

*[Back to the door plan, answer visible.]*

> Now: **can you check it?** Four ways.

*[Driver unticks door #4 in the evidence list: the total drops to 19. Re-tick it.]*

> One. **The evidence adds up.** These twenty boxes *are* the answer. Untick one, and the total follows.

*[Point at the confidence line under the answer.]*

> Two. **Confidence you can take literally.** On a scan, when it says zero point nine five or more, it's right
> ninety-eight point seven percent of the time. When it's unsure, it says "not sure" instead of guessing.

*[Switch to the Finnish scan tab, `colorful-10052.png`: five boxed doors, conflict flag.]*

> Three. **A second opinion.** On scans, our own fine-tuned vision model re-counts.
> Here it says four, so the app flags it. Five boxes: a five-second check. Five is right.

> Four. **Every number an LLM writes is traced** to the facts it cited, or flagged.

### 2:35–3:00 · Close (slide 11, then 12)

*[Slide 11: path to product.]*

> A second AI agent audited our evaluation: no leakage, the numbers reproduce.
> So here's what Stoa gets: a takeoff engine that's right ninety percent of the time,
> says so when it isn't sure, and costs about a cent per thousand questions.
> **A product a professional can actually sign off on.**

*[Slide 12: team, repo, "Start the 60-second tour".]*

> Datum: on a drawing, the datum is the point every measurement is taken from, and every answer here traces
> back to the drawing. Try the tour, then ask it your own question.

### Timing cues

| at | you should be on | if you're behind |
|---|---|---|
| 0:25 | slide 2 | skip "It even had the CAD file." |
| 0:55 | slide 4 | skip slide 3's spoken line, just point at the bar |
| 1:25 | slide 8 | drop "A language model only sees the free-text questions." (keep the 0.4 %) |
| 1:55 | demo, door plan | do verification on slide 9 without switching |
| 2:35 | slide 11 | go straight to the last two lines of the close |

---

## 2. The 90-second cut

About 220 words. Same order, fewer switches: one demo moment at the start, then slides only.

| time | screen | say |
|---|---|---|
| 0:00–0:15 | demo: door plan, mic, X-ray count, **See it in 3D** | *(into the mic)* "Kuinka monta ovea?" ... "I asked this plan, in Finnish, how many doors. **Twenty. Each one numbered, each one checkable.** No AI model call. Zero cents." |
| 0:15–0:30 | slide 2 | "Takeoff is slow by hand, and nobody trusts AI with it. Claude Sonnet said this apartment is ninety-four square metres. It's one hundred and eight. And it sounded just as sure." |
| 0:30–0:45 | slide 4 | "So we route every question to the cheapest method that's exact: the CAD layers, the BIM model, or a small detector we trained. Only zero point four percent of questions ever touch a language model." |
| 0:45–1:05 | slide 8 | "On all twenty-five thousand, four hundred and twenty held-out questions, we're right **ninety point zero percent**. Sonnet, given the same files: sixty-nine point eight. Twenty points better, at **one nineteen-hundredth of the cost**." |
| 1:05–1:20 | slide 9 | "And you can check every answer. The evidence adds up to the number. The confidence means what it says. A second method re-checks it. Every LLM number is traced." |
| 1:20–1:30 | slide 11 | "For Stoa: a takeoff engine **a professional can sign off on**. Datum: blueprints that talk." |

---

## 3. Live-demo run sheet

### What needs what

| part of the demo | needs internet | needs the GPU box | note |
|---|---|---|---|
| Swiss plans, IFC models (answers, X-ray, See it in 3D, heat-map, takeoff sheet) | yes (the demo is hosted) | no | CAD / IFC solvers, $0, no model call |
| Finnish scans with the **dataset's exact question** (tour step 4, deep link below) | yes | no | the fine-tuned model's second opinion is precomputed for these questions |
| Finnish scan asked in **your own words** (e.g. by voice) | yes | **yes** | no precomputed second opinion, so it is asked live (20 s limit); if the GPU box is down the answer still comes, just without the second opinion |
| Ask by voice | yes | no | audio goes to ElevenLabs for speech-to-text; if that fails, the page falls back to the browser's speech recognition, or type |
| Frontier side-by-side ("Frontier models, same drawing") | yes | no | precomputed baseline answers |
| Uploads | yes | for raster residential plans only | read by Claude Haiku when no exact reader fits |

**Nothing works offline.** The demo is a server (no offline cache), so without a network you fall back to the
deck and the recorded video (below). The GPU box only matters for the second opinion on free-worded scan
questions and raster uploads; the run sheet below avoids both.

**Rate limit.** The public demo allows 150 asks + uploads per client IP per 10 minutes (raised from 30 because a venue shares one IP; the $5/day model-spend cap still protects the budget) (HTTP 429 after that). If
the judges and your laptop share the venue Wi-Fi, they share an IP: do not rehearse on venue Wi-Fi in the last
10 minutes before your slot, or rehearse on a phone hotspot.

### 10 minutes before: set up

1. Laptop on power, notifications off, browser zoom 100 %, screen mirrored to the projector at 1920x1080.
2. Open these tabs in order (replace `<DEMO>` with the demo link including its secret path; deep links take
   `tab`, `path` and `q`, and open with the question already asked):
   - **Tab 1, hook:** `<DEMO>/?tab=swiss_dwellings&path=data/swiss_dwellings/site3387_bldg5238_floor23498.pdf`
     (no `q`: you ask it live).
   - **Tab 2, scan:** `<DEMO>/?tab=cubicasa5k&path=data/cubicasa5k/colorful-10052.png&q=Kuinka monta ovea pohjapiirustuksessa on? Laske oviaukot, joissa on ovi; pelkkiä oviaukkoja ilman ovilehteä ei lasketa.`
     (let the browser encode it; check it shows 5 boxes and the conflict flag).
   - **Tab 3, backup German area:** `<DEMO>/?tab=swiss_dwellings&path=data/swiss_dwellings/site11487_bldg17991_floor47889.pdf&q=Wie gross ist die Nettowohnfläche von Wohnung A in m² (Summe aller Räume ohne Balkone, Loggien, Terrassen und andere Aussenräume)?`
     (62.74 m², and five frontier answers, all wrong).
   - **Tab 4:** `docs/deck/deck.pdf`, full screen, on slide 2.
3. In tab 1, press the mic once and allow microphone access, then **reload tab 1** so the ask box is empty again.
4. Say "Kuinka monta ovea?" once in tab 1 to warm the server and check the mic hears you over the room, then
   reload. (This uses 1 of the 150 asks.)

### During the talk: exact actions

| # | when (talk) | driver does | what appears | if it stalls, say |
|---|---|---|---|---|
| 1 | 0:00 | Tab 1: click the **mic** in the ask box; speaker says "Kuinka monta ovea?" and pauses | Listening → Transcribing → Asking; the X-ray count runs 1 / 20 … 20 / 20 (any key or click skips it) | "It's turning my Finnish into text..." If no transcript after 4 s: type `Kuinka monta ovea?`, Enter |
| 2 | ~0:12 | click **See it in 3D** (above the plan) | the plan rises into a building, 20 doors glow and number | "It's raising the walls from the CAD layers." If 3D is slow: stay in 2D and point at the numbered doors |
| 3 | 0:25 | switch to the deck, slide 2 | | |
| 4 | 1:55 | switch back to tab 1, click **Plan** if still in 3D; in the evidence list untick **door #4** | total 20 → 19 | |
| 5 | ~2:00 | re-tick door #4; point at the confidence line ("Very likely right") and the second-method line | back to 20 | |
| 6 | ~2:15 | switch to tab 2 (Finnish scan) | 5 boxed doors, "second opinion says 4", check advised | if tab 2 errored: skip it, say the line over slide 9 |
| 7 | 2:35 | switch to the deck, slide 11, then 12 | | |

While anything loads, keep talking: the next line of the script never depends on the screen being ready.

### Fallback plan

| what fails | do this |
|---|---|
| Mic / speech-to-text | type `Kuinka monta ovea?` and press Enter. Say: "Voice works too; on this Wi-Fi I'll type." |
| 3D is slow on the projector laptop | skip **See it in 3D**; the 2D X-ray count is the hook on its own |
| GPU box down | nothing in the run sheet uses it. Do not ask the Finnish scan a free-worded question live |
| Demo slow or 502 / 429 | stay in the deck: slide 5 (doors and German area, screenshots), slide 6 (Finnish scan and BIM), slide 7 (3D, X-ray, side-by-side, heat-map). Say the same lines while pointing at the screenshots |
| No Wi-Fi at all | phone hotspot first. Failing that: deck PDF (local) and the recorded video `runs/video/blueprints-final.mp4` (copy it to the laptop beforehand; it is on the dev box, not in git) |
| Need a single image | `docs/deck/img/`: `feat-3d.jpg` (20 doors in 3D), `feat-xray-card.jpg` (X-ray count), `feat-ghost.jpg` (frontier side-by-side), `feat-voice.jpg` (voice), `deck-finnish-vlm.jpg` (scan + second opinion), `deck-ifc-walls.jpg` (BIM walls in 3D), `deck-correction.jpg` (untick a window) |
| Over time | cut straight to the close: "So here's what Stoa gets..." |

If the judges get hands-on time after the pitch: open slide 12's **▶ Start the 60-second tour** (7 steps; arrow
keys move between them, Esc leaves), then let them type their own question.

---

## 4. Judge questions: short answers

**"Isn't 100 % on the Swiss plans just reading the answer key?"**
No: the DXF is the same drawing in another format, shipped in the dataset, not the answers; we measure door
symbols and room polygons from its layers, and the audit confirmed no gold lookups at inference. Claude Sonnet
given the same DXF gets 81.5 % of the counts and 79.6 % of the areas, and our cross-check re-derives the answers
from the PDF alone (it even caught one of our own area errors).

**"How does it do on real-world scans?"**
The Finnish plans are raster scans: 85.1 % on all 16,496 test questions, 93.4 % when it answers, against 63.6 %
for Sonnet. On 30 messy uploads (phone photos, sideways scans, a 120-page set, broken files) nothing crashed, but
that is hand-checked, not a measured accuracy, so the app says "no track record yet" on uploads.

**"Why not just use GPT or Claude?"**
We measured it: Claude Sonnet 5.5 given the same CAD and IFC files gets 69.8 % at $25.76 per 1,000 questions
(Gemini 3.1 Pro, drawing only: 64.2 % at $52.47), and neither shows you why. We use a frontier model where it's strong (the 0.4 %
free-text questions) and any better model plugs into the same evidence contract; we did not benchmark GPT.

**"What's the 10 % you get wrong?"**
Almost all of it is on the scanned Finnish plans (85.1 %): mostly counts off by one, with windows the weakest
template (53 % exact), plus free text at 38.2 %. The confidence catches most of it: answering only at ≥ 0.5
turns 1,594 wrong answers into "not sure", and 95.8 % of the rest are right.

**"What does it cost at scale?"**
$0.013 in API fees per 1,000 questions plus about $0.006 of local compute, so a million questions is roughly $13
plus $6, at 0.04 s each. Numeric answers make no paid calls at all, so cost grows with CPU/GPU time, not tokens.

**"How would Stoa integrate it?"**
It's an HTTP service: upload a drawing or model, ask a question, get back `{answer, confidence, method, cost_usd,
explanation, evidence[]}`, with evidence as boxes and polygons in page coordinates or IFC GlobalIds, ready to draw
in Stoa's own viewer. It's MIT-licensed and numeric answers need no API keys, so it can run inside Stoa's own
infrastructure; next is re-asking every question on every drawing revision and flagging what changed.

**"What's fine-tuned and what's off-the-shelf?"**
Trained by us: the YOLO11m symbol detector (on a local RTX 4070, non-test CubiCasa drawings only) and a
Qwen3-VL-8B LoRA second opinion (cloud H100s, dev drawings only; 74.9 % alone, so it never answers alone).
Off-the-shelf: ezdxf, Shapely and IfcOpenShell for the geometry, and Claude Haiku 5.5 for free text and for
rewording unusual questions.

**"What about privacy of uploads?"**
CAD, IFC and dataset-scan answers are computed on our own server; an upload that no exact reader can answer is
read by Claude Haiku, and the app says so next to the drawing (voice audio goes to ElevenLabs for transcription
and is never stored). Self-hosted, the numeric answers on CAD, IFC and scans make no outside call at all.

**"What about free-text questions? 38 % isn't great."**
Agreed, it's our weakest area and we say so: 38.2 % on 110 questions (0.4 % of the test set), against 9.1 % for
Sonnet under the same LLM judge. Every number in those answers is traced to the model facts it cites, or flagged.

**"How do you know there's no test leakage?"**
We split by whole drawing with a hash of its id, so every format and language version of a drawing is on one
side: 5,884 drawing groups, 0 straddle dev and test, and the training scripts drop test drawings before reading
anything. A second AI agent (Codex, OpenAI) audited the evaluation read-only; every finding was re-checked, and
the recount reproduces.

**Extra, if asked:**

- *"Why is Sonnet's confidence interval so wide?"* The frontier runs are a 400-question sample (about 54 per
  source × type cell), re-weighted to the real test mix, so 69.8 % has a CI of 60.9–78.4; ours is every question,
  89.7–90.4.
- *"Does it really work in six languages?"* The 12,654 pairs of the same question in English and in Finnish,
  German, French, Italian or Dutch agree on 100 %.
- *"Isn't 0.4 % LLM a benchmark artefact?"* On the test set, yes, only the 110 free-text questions call Haiku. In
  the demo, a typed question no parser understands adds one cached Haiku call to reword it (about $0.0003–0.003),
  and the app shows "read as: ...".
- *"Can I correct it?"* Untick a box or click a missed item; the total updates, and the correction is saved as
  feedback for the next training run.
