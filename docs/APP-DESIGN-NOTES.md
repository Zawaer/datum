# App design notes

What changed in the demo app (`app/static/app.css`, a few strings in `app.js` / `index.html`, `how.css`) to bring it under the
same rules as the deck, `docs/deck/DESIGN-RULES.md`. The layout, the tour and `record_demo.py` are unchanged.

| Change | Rule |
|---|---|
| One type scale for the whole app, written at the top of `app.css`: 12 caption / 14 body / 16 lead / 24 title / 28 landing headline / 56 answer number (phone: 15 body, 42 number). The stray 10, 11, 13, 15, 17, 20 and 22 px sizes are gone, so a view uses at most four sizes. `/how` is mapped onto the same steps. | 6, 7 |
| Weights 400 and 600 only. All the 500s went to 400 (labels, links, tabs) or 600 (section headings, the active mode). The font request now loads Plex Sans 400/600 and Plex Mono 400 only. | 7 |
| Large type is tracked tight (-0.02 to -0.03em, line height 1.1), body text is left at 0 tracking with a 1.5 line height. | 8 |
| No all-caps labels. Section headings, the tour step (`Tour · 1 of 7`), the X-ray HUD, the heat-map legend, the ghost-comparison key, the takeoff sheet's column heads, the voice state, the trace headings and the 3D storey labels are now in sentence case at normal tracking. On `/how`, the eyebrow above the headline is hidden and the chapter numbers are plain grey numerals, not boxed blue tags. | 9 |
| No emoji-style glyphs in the UI text: the warning sign, pencil and download arrow are gone ("A second method says 4: check the evidence", "Corrected by you", "Export CSV"). Buttons are verbs in sentence case ("Add missed", "Show more", "Print"). | 9 |
| One accent. Blue #0072b2 now means only "ours / evidence": the evidence marks and numbers, "Verified by geometry", our row in the frontier comparison, the counting number. The green "right" figures, the green second-opinion line, the green $0 cost and the green "signed" badge are now ink or grey. The orange "5 of 5 wrong", the orange low-accuracy figure and the orange "Detected by vision" pill are grey or ink. The primary buttons (the tour button, Next, Ask) are ink, not blue. | 10 |
| Amber is used only for "changed by you": a corrected total, items you added (they were green), "added by you". Red (vermillion) is used only for conflicts and errors. The one exception is a deliberate one: model-read marks on the drawing stay orange and dashed, because that is a status ("read by a model, check it") with a second cue (the dash). It is not decoration. | 10 |
| No coloured side stripes. They were on the selected drawing, our row in the frontier table, the hot evidence row, the conflict box, the correction box, the method lines, the calibration lines, the voice strip, the 3D storey labels and the `/how` route cards. No double borders on the conflict box. On `/how`, the dotted "drafting paper" backgrounds, the hatched gradient bar and the underlined accent words in the headline are gone. | 12 |
| No shadows on bordered boxes. Controls on the drawing (picker, Plan/3D, view menu, zoom, legends) have a hairline and no shadow. Only floating layers (menus, the tour card, the phone answer sheet) keep one soft shadow. The focus glows on inputs became a plain ink border. | 12 |
| Fewer boxes in boxes. The answer is no longer a bordered card inside the side panel: the question, number and trust line sit on the panel, and Evidence, Frontier models, How it was worked out and the footer are separated by hairlines. The evidence list and the frontier table lost their outer boxes. The example questions are a list between hairlines, not a stack of bordered buttons. The trust badge is a word in the accent, not a tinted pill. | 12 |
| 8-pt grid. Edge offsets of 12 and 14 px became 16 (picker, view tools, zoom, legends, X-ray HUD, 3D storey bar). Paddings and gaps of 6, 10, 14, 18 and 20 px became 4, 8, 16 or 24. Controls are 32 or 40 px tall. | 11 |
| Two radii: 4 px for small marks (checkboxes, keys, tags, segmented buttons) and 8 px for everything else. The 6, 10, 12, 16 and 999 px radii are gone, so there are no pills. | 11, 12 |
| The tour card is light (white, hairline, ink text, 24 px title) to match the deck's light theme. It used to be an ink card with a blue all-caps step label. | 10 |
| On phones the header shows the mark and the "Datum" wordmark (it used to show the mark only); the tagline stays hidden. `app/static/og.png` is a new 1200x630 capture of the landing view, with the drawing's licence line visible. | 3, 11 |
| The 3D chrome injected by `view3d.js` / `plan3d.js` (storey bar, legend, storey labels) is brought onto the same grid, scale and radii by an override block at the end of `app.css`, so those files are untouched. | 7, 11, 12 |

Before and after screenshots of each view (landing, Swiss count in 2D and 3D, area answer, Finnish plan, IFC in 3D, `/how`,
`/results`, the tour, phone) were taken during the pass. They are not committed.
