# Demo app QA log

Pass on 2026-11-13 at 1440×900, 1920×1080 and 390×844 (touch, DPR 2), headless Chromium with
swiftshader WebGL. Covered: all 7 tour steps (desktop + phone), 5 drawings × 3 questions per source tab
(EN, FI, DE, FR, IT, NL, DA, ET questions), free-typed questions, uploads (PNG, vector PDF, DXF, small IFC,
a .txt and a broken PDF), /results, 3D storey cut and click-to-toggle, correction by click (remove / add),
back / forward / reload, big-IFC first load. Screenshots were taken to `/tmp/qa/shots/` (ephemeral);
the final state is in `docs/img/`.

Severity: **H** visible in the demo / wrong number, **M** visible and ugly or confusing, **L** polish.

| # | Sev | What | Where | Status |
|---|-----|------|-------|--------|
| 1 | H | 3D count animation is tick-based: on a slow GPU (swiftshader, the recorded video) the big number sat at a partial sum (125.63 / 149.83 m) for seconds while the answer is 185.13 m; screenshots caught it. If the animation was cancelled, the partial number stayed forever. | tour step 6, any 3D sum | fixed: time-based animation, `clear()` finishes a cancelled count, the tour waits for the count |
| 2 | H | Phone: hovering an evidence row called `scrollIntoView`, which scrolled the **page**, so the tour showed only the caption and the list, not the drawing | phone tour steps 2–7 | fixed: only the list scrolls |
| 3 | H | /results used the 200-question Sonnet preview run (CubiCasa 84.7 %) instead of the full-set baselines re-weighted to the test mix | /results | fixed: reads `analysis/out/*.csv` (87.2 / 63.2 / 60.6 / 41.6 %), adds per-language table and cost/speed table; raw runs folded away |
| 4 | H | Tour step 4 question text differed from the dataset question (`ilman ovea` vs `ilman ovilehteä`), so no "matches the dataset answer" pill (and it was treated as free text) | tour.json | fixed |
| 5 | H | No URL state: back / forward lost the drawing and answer; reload went to the first drawing | app.js | fixed: drawing + question in the URL (push on pick, replace on ask), popstate restores |
| 6 | M | Free-typed questions on dataset drawings abstained with "question not understood" / "question template not recognised" | /api/ask | fixed: specialist abstains on a free question → the generic reader tries (text layer first, 75 s cap), explanation says so |
| 7 | M | Solver error text leaked internals ("generic solver failed: SafetensorError: …", "Failed to open file 'cache/uploads/…'") | /api/ask, /api/upload | fixed: friendly text, detail kept in `error` |
| 8 | M | Upload timeouts were reported as "uploads of this kind (raster) are not routed to a solver yet" | /api/ask | fixed |
| 9 | M | IFC credit line started "© \| file.ifc \| …" (raw table row) | credit_for | fixed: "title · licence · credit"; click the credit to show it in full |
| 10 | M | Phone header took ~160 px (3 rows), answer card below the fold | phone | fixed: one-row header + one-line cost meter, viewer 50svh, answer above the suggestions, tour caption is a bottom sheet |
| 11 | M | Phone drawer had no backdrop; its shadow bled onto the viewer edge when closed | phone | fixed: scrim (tap to close), shadow only when open, Esc closes |
| 12 | M | Shared link to an upload that is gone rendered a blank viewer with "Could not render" | /api/questions | fixed: 404 + "This upload is no longer on the server…" |
| 13 | M | Adding a missed item did nothing when the click landed on an existing shape | correction | fixed |
| 14 | M | Room counts (polygons) had no numbers on the drawing; list numbers were vertically misaligned with labels | overlay, evidence list | fixed: numbered polygons for count answers; grid rows |
| 15 | M | Numbered badges covered the printed m² values they point at (text-layer answers) | overlay | fixed: badge sits left of thin boxes |
| 16 | M | DXF upload: vision fallback cannot render DXF ("no text layer and no renderable page") | /api/ask | fixed in app: retry on the PNG rendered from the same extents (but see open issue A) |
| 17 | M | Loading overlay for a big IFC had no clock and could stay up after switching to another drawing | 3D load | fixed: elapsed seconds, overlay only for the current drawing |
| 18 | L | Latency shown as "0 ms" for cached answers | answer card | fixed: "< 1 ms" |
| 19 | L | Suggestion chips cut mid-line | side panel | fixed: fade-out mask, taller box |
| 20 | L | Empty side panel before the first question | side panel | fixed: intro card with languages + keyboard hints |
| 21 | L | No favicon / description / social preview | index, results | fixed: SVG favicon, description, og:image (`/static/og.png`) |
| 22 | L | No keyboard shortcuts besides Enter | app.js | added: Esc (leave tour / stop adding / close drawer), `/` focus, ← → tour, `f` fit, `+ −` zoom |
| 23 | L | Thinking text promised "nothing is sent to a paid model", untrue for the generic fallback | answer card | fixed |
| 24 | L | Session meter could say "-20 % cheaper" | header | fixed ("dearer") |
| 25 | L | Shared upload link did not list the upload in "Your uploads" | list | fixed |
| 26 | L | /results tables overflowed on a phone | /results | fixed: compact cells under 640 px |

New: each answer carries a "how" badge: **Verified by geometry** (Swiss CAD layers, IFC queries),
**Looked up in the BIM model** (IFC rules), **Detected by vision** (CubiCasa detector, grounded VLM),
**Answered by an LLM** (text-layer reader, IFC fact sheet), **Abstained / Not in the model**, each with a one-line how.

## Open (not app bugs, or not fixable from app/)

- A. Generic vision path (PNG / scanned uploads, DXF via PNG, free questions on CubiCasa) times out while the
  GPU is saturated by CubiCasa training (96 % util): asks take 75–120 s and abstain. Should be fine once training stops.
- B. Solver quality seen in the pass: vector-PDF upload door count 0 at confidence 0.9 (generic); CubiCasa
  colorful-12202 windows 2 vs gold 1; IFC upload "total floor area of spaces" abstains (no area quantities).
- C. Headless phone emulation of the 3D steps is slow (swiftshader at DPR 2: 1–3 min per step); real devices use the GPU.
- D. Timed-out solver threads keep running in the 8-thread pool; many concurrent slow uploads could starve it.
