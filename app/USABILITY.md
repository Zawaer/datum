# Usability pass: a judge's first three minutes

Done on Sat 14 Nov (morning, UTC) against the local demo, at 1440 × 900 (laptop) and 390 × 844 (phone), with a
cold browser: land on the page, take the demo tour end to end, ask four questions of my own on Swiss, Finnish
and IFC drawings, then open `/results`. Screenshots are in [`docs/img/usability/`](../docs/img/usability/).
Timings are wall-clock in headless Chromium.

## What a judge sees, step by step

| step | time | notes |
|---|---|---|
| landing | < 1 s to a drawing | before the fix: a file list, a plan and "Ask this drawing anything…"; nothing said what the project is, how good it is or that a tour exists, apart from a small "Demo tour" button |
| tour 1, Swiss doors | 7 s | strong: numbered doors, "Very likely right · 99.95 %", "Two independent methods agree" all visible at once |
| tour 2, German area | 11 s | the title promises a frontier comparison, but opening "Why this answer" pushed the frontier table out of view |
| tour 3, correction | 8–10 s | the item was unticked, then ticked again, so the end state showed no correction at all |
| tour 4, Finnish doors | 5 s | shows "Uncertain · 39.3 %" and "⚠ Conflict: 5 vs 4" with no word of explanation in the caption |
| tour 5–7, IFC in 3D | 13 s, then 2–3 min | steps 6 and 7 are slow only under software WebGL (2 fps in headless swiftshader; 60 fps in 2D). On a laptop GPU they take seconds. Step 7's caption said "the storey is cut open"; it is not |
| own: Swiss "How many bathrooms are there?" | 16 s | **wrong**: 0, from the generic vision reader ($0.003), labelled "No track record yet". The plan has several "Bad" rooms |
| own: Finnish "how many windows" | 5 s | 3, both detectors agree, "Often right · 69.3 %", boxes on the plan: good |
| own: IFC "total window count on this floor" | 5–9 s | answers 119 for the whole building (22 on this floor is in the text), "Uncertain · 26.3 %"; the text answer was indented and sat under an empty big-number slot |
| own: IFC "What is the area of the largest room?" | 14 s | honest abstention ("Not sure, so no guess"), but the explanation text is solver-speak ("the specialist solver passed … read by haiku") |
| `/results` | 2.5 s | clear tiles, but the "per 1k questions" cost added API fees and compute ($0.04 vs $27.94), which does not match the $0.014 vs $25.76 in the README |

## Top friction points

Severity: **H** = a judge may leave with the wrong idea or miss a scoring criterion, **M** = slows them down or
looks unpolished, **L** = minor.

| # | sev | friction | screenshot | status |
|---|---|---|---|---|
| 1 | H | No value proposition or call to action on landing. The intro sat below the question chips and never mentioned the tour. | [before](../docs/img/design-after-1440-empty.png), [after](../docs/img/usability/after-landing-1440.png), [phone](../docs/img/usability/after-landing-390.png) | **fixed**: one-line value proposition at the top of the side panel plus a "▶ Start the 60-second tour" button |
| 2 | H | The headline result (accuracy, comparison, cost) was nowhere on the demo page; the header meter read "ours $0 / frontier $0 / ask something". | [after](../docs/img/usability/after-landing-1440.png) | **fixed**: a strip under the header, "89.5 % right on all 25,420 held-out test questions: every question in every language, not a sample (95 % CI 89.1–89.8) · Claude Sonnet given the same files: 69.8 % · $0.014 vs $25.76 per 1,000 questions · Scoreboard ›". Hover shows per source; it links to `/results`. The session meter says what it measures and is hidden on the phone until you ask something |
| 3 | H | Tour step 2 promised the frontier comparison, but the table was off-screen. | [before](../docs/img/usability/before-tour-2-frontier-hidden.png), [after](../docs/img/usability/after-tour-2-frontier.png), [phone](../docs/img/usability/after-phone-tour-2.png) | **fixed**: new `scroll:` tour action brings the table into view ("5 of 5 wrong") |
| 4 | H | Tour step 3 (correction) undid itself, so the screenshot and the end state showed nothing corrected. The headline number also never changed after a correction, only the list total. | [before](../docs/img/usability/before-tour-3-correction-reverted.png), [after](../docs/img/usability/after-tour-3-correction.png) | **fixed**: the tour leaves window #4 unticked; the big number follows the correction, with "corrected by you: 10 (the solver said 11) · saved as feedback" under it |
| 5 | H | Tour step 4 shows "Uncertain" and a conflict with no explanation; a judge reads it as a failure. | [before](../docs/img/usability/before-tour-4-conflict-unexplained.png), [after](../docs/img/usability/after-tour-4-conflict.png) | **fixed** (caption): the detector says 5 and our fine-tuned vision model says 4, so the app flags it and says in words to check; the five boxes make that a five-second check, and 5 is right |
| 6 | M | Jargon in the main answer card: "held-out test questions (CAD-layer geometry (Swiss DXF twins), confidence 95–99 %; this one: 98 %)", a route pill "CAD layers (DXF twin)", "frontier VLM", "IFC bench", "dev". | [after](../docs/img/usability/after-tour-3-correction.png) | **fixed**: "8,014 of 8,018 similar answers were right on test drawings we never trained on" (the technical scope moved to the tooltip), the route pill lives only in "Why this answer", "frontier model", "IFC text Q&A", "test drawing, never trained on" |
| 7 | M | Each verification layer should be seen once in the tour; "Why this answer" was opened where it hid the frontier table, and nowhere else. | [after](../docs/img/usability/after-tour-6-arithmetic.png) | **fixed**: layers per step: 1 evidence marks + confidence in words + two methods agree, 2 frontier side by side, 3 correction by clicking, 4 conflict between methods, 5 the same doors in 3D, 6 "Why this answer" arithmetic (21 walls summed), 7 sign-off and CSV |
| 8 | M | Step 7's caption said "the storey is cut open"; it is not. The tour ended with no next step. | [before](../docs/img/usability/before-tour-7-caption-wrong.png) | **fixed**: accurate caption ending "Your turn: …"; "finish" focuses the question box |
| 9 | M | The scoreboard's cost per 1k added compute to API fees ($0.04 vs $27.94) while the README, deck and strip quote API fees ($0.014 vs $25.76). The method (all questions vs a 400-question sample) was in a grey paragraph. | [before](../docs/img/usability/before-scoreboard.png), [after](../docs/img/usability/after-scoreboard.png) | **fixed**: a lead sentence with the full-split method, CI, comparison and API fees; tiles say "$0.014 API + $0.02 compute per 1k" |
| 10 | M | Free-text IFC answers were shown with the solver's indentation under an empty big-number slot. | [before](../docs/img/usability/own-ifc-windows-text.png) | **fixed**: no empty number slot, text trimmed and de-indented |
| 11 | H | Off-script questions can be wrong or unstable on the generic path. "How many bathrooms are there?" on a Swiss plan answered 0, then 3, then 4 on three asks (a vision model, uncached; it boxes WCs). "Window count on this floor" on IFC counts the whole building. The UI labels both honestly ("No track record yet", "Uncertain · 26.3 %"), but the vision model's boxes were drawn as solid blue circles, the style for "measured from CAD geometry", and a 0 said "check the boxes" with no boxes. | [Swiss, 0](../docs/img/usability/own-swiss-bathrooms.png), [Swiss, 4](../docs/img/usability/after-own-swiss-bathrooms.png), [IFC](../docs/img/usability/own-ifc-windows-text.png) | **UI part fixed**: boxes from any model are now dashed amber squares (the "read by a model, check it" style), and a 0 with nothing boxed says to look at the plan. **Solver part open**: map "bathroom / Bad" to the Swiss room-label counter, make the IFC text path respect "this floor", and cache generic answers so a judge asking twice sees the same number |
| 12 | M | The abstention explanation is solver-speak ("the specialist solver passed … read by haiku"). | [IFC](../docs/img/usability/own-ifc-largest-room-abstain.png) | **fixed**: the card shows the plain reason; the solver's own words moved into "Why this answer" |
| 13 | L | The 3D steps are slow only under software WebGL (2 fps in headless swiftshader); `record_demo.py` needs about 2–3 min per 3D step there. The 3D view renders every frame even when nothing moves. | n/a | **fixed**: the 3D view renders on demand (input, resize, highlights, easing capped at 2.5 s); 0 frames in 3 s idle, and the 3D tour steps under software WebGL drop from 2–3 min to about 10 s |
| 14 | L | The phone tour caption covers the answer card. Steps still read well because the drawing is on top, and step 2 now scrolls to the frontier table. File names (`site1000_bldg2082_floor9385.pdf`) mean nothing to a judge. | [phone](../docs/img/usability/before-phone-tour-1.png) | caption **fixed**: on phones it is a 102 px bottom sheet (step, title, two lines, "… more") and the answer number sits above it on every step; file names still **open** |

## Not changed on purpose

- The upload box and its route: another session owns that code.
- The tour stays at 7 steps. Each step shows one layer, and with a GPU the whole tour runs in about a minute.
