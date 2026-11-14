# Uploads: what happens to your file, what works, what doesn't

Anyone can upload their own drawing (PDF, image, DXF, IFC) and ask about it. Uploads are real-world files:
multi-page sets, scans, phone photos, screenshots, sideways pages, the wrong document, a corrupt download. This
page describes how the demo handles them and what we measured on 30 test files (openly licensed drawings
from the web plus edge cases we made ourselves; list and licences in `cache/upload_tests/MANIFEST.md`, not
committed).

The rule throughout: **never crash, answer when the file supports it (with evidence on the drawing), and
otherwise say "not sure" and why.**

## 1. On upload (`POST /api/upload`, `app/server.py: _prepare`)

Each distinct file is prepared once (keyed by its SHA-1), in a worker thread so the server stays responsive.
It takes 3-15 s, mostly the page check in step 4.

1. **Type.** PDF, PNG, JPG, DXF and IFC are read as they are. WEBP, TIFF, BMP, GIF, SVG and HEIC/HEIF (iPhone
   photos, via `pillow-heif`, saved as JPG) are converted (a multi-page TIFF becomes a PDF, so its pages are kept).
   A multi-page PDF (a whole drawing set) gets a page index from its text layer (`bp/generic/sheetindex.py`, ~15 ms
   a page, nothing rendered): each page's sheet id and title from its title block, shown in the page picker; a
   question that names a sheet ("check valves on M-101A?") is answered on that page, whose sheet type is then
   classified on first use. DWG, RVT, SKP, ZIP, DOCX and XLSX get a
   clear 415 that says what to export instead (e.g. "DWG is a closed AutoCAD format: export the sheet to PDF or DXF").
2. **Validation.** Damaged files get a 422 that says what is wrong, not a stack trace. The checks: images are
   fully decoded, a PDF must open, have pages, not need a password, and render its first page. A DXF is read with
   `ezdxf` (or repaired with `ezdxf.recover`) and must have model-space entities. An IFC needs a STEP header with
   an IFC schema and must open in IfcOpenShell.
3. **Normalisation of images** (`_prep_raster`):
   * EXIF orientation is applied. Phones store pixels sideways plus a tag; browsers honour the tag and PIL does
     not, so without this the evidence boxes would be drawn 90° off.
   * Images over 40 MP are downscaled (a 30 MB, 65 MP scan becomes 40 MP).
   * **Phone photos of a printed plan are rectified** (`bp/generic/rectify.py`). The code looks for the paper
     sheet as the largest 4-corner contour that is brighter than its surroundings, and only acts when the sheet
     is seen in perspective. It warps the sheet to a flat rectangle, then divides by a heavy blur of itself to
     remove the shadow and vignette. Screenshots, scans and born-digital plans have no such outline, or an
     axis-aligned one, and are left alone (no false positives on the scans, screenshots, renders and photos in our test set). The solvers and the
     viewer both use the rectified image. The UI says "rectified from your photo" and links to "see your
     original file".
4. **Page check** (`bp/generic/sheets.py`, one Claude Haiku call on a contact sheet of up to 16 pages,
   about $0.001-0.002). For each page it records what the page is (floor plan / elevation / schedule / cover /
   text document / photo / 3D render ...), whether it is a drawing, a short title, whether it looks like a
   residential brochure plan, and whether it is sideways. The model reliably sees *that* a page is sideways but
   not which way, so a second call shows the page four ways (A-D) and asks which reads upright. Pages found
   sideways are turned in the stored file (`set_rotation` for PDFs). Residential brochure plans are the
   exception: they are left as drawn, because they often label half their rooms vertically. The check is
   skipped when the daily budget is used up (`BP_DAILY_USD_CAP`), or with `BP_SHEET_CHECK=0`.

The response and `/api/questions` carry `notes` (what was done), `pages`, `page_titles`, `drawing_pages`,
`not_drawing` and `original`. The UI shows the notes above the suggested questions, an amber warning for
non-drawings, and, for multi-page files, a **page picker** on the drawing.

## 2. On a question (`POST /api/ask`)

* **Typo-tolerant read-back.** "how mnay windws are there?" is read as "how many windows are there?". The fix is
  local and free: it uses a small vocabulary and allows at most one letter of length difference, and leaves
  Finnish, German and French alone. The reading is shown under the question ("read as: ..."), as is the LLM
  normaliser's rewrite for the dataset solvers.
* **Routing** (`bp/router.py`):
  * Raster uploads that the page check calls a residential plan, asked to count something the CubiCasa detector
    knows (windows, doors, toilets, sinks, showers/baths, saunas), go to the **YOLO detector** first. It takes
    0.1-3 s and costs $0.
  * If that detector is unsure (confidence < 0.3, e.g. on a 1900s plan drawn in a style it never saw), the
    general reader also answers and the more confident of the two is kept (shown as "cubicasa -> generic").
  * IFC: the rule solver first, then the IFC fact-sheet reader (`ifctext`) if the rules abstain or are unsure.
  * Everything else goes to the general reader: the text layer first, then grounded vision.
* **Which page.**
  * If you picked a page, only that page is read.
  * Otherwise, text questions use the pages whose text matches the question.
  * Vision questions use the drawing page whose text or title matches. If nothing matches, one Haiku call
    looks at the page thumbnails and picks one.
  * The answer says which page it read ("looked at page 3 of 4 (Enlarged plan ...)"), and the viewer jumps to
    the page the evidence is on.
* **Honesty rules for uploads** (these files have no track record):
  * A page the check says is not a drawing gets no counts or vision reads: "page 1 does not look like a
    construction drawing (it looks like: text document ...), so nothing was counted". Text questions still
    work, with the cited text as evidence.
  * "0 found" with no evidence is capped at 40 % confidence. An empty result on an unfamiliar drawing is weak
    evidence.
  * Vision counts are capped at 75 % confidence: two passes agreeing is not a track record.
  * A vision read that returns null is an abstention with 0 % confidence, never "null at 80 %".
  * Below 30 % confidence the answer becomes "Not sure, so no guess". The best guess and its boxes stay visible
    as candidates ("best guess 10, but the evidence was too weak ...").
  * The held-out track record is not borrowed: uploads show "no track record yet".
  * Paid vision tiles run in parallel, and an upload question stops after 75 s, so a dense sheet answers in
    10-25 s instead of up to 60 s.

## 3. What we measured (30 files, 70 questions, about $0.35 of Haiku in total)

No crashes and no 5xx. Every damaged or unsupported file got a 4xx with a plain-language reason. Slowest
answer: 34 s (before the parallel tiles change: 64 s).

| file | question | result |
|---|---|---|
| phone photo (perspective, shadow, blur) of CubiCasa plan high_quality-10132 | windows / toilets / doors | **11 / 2 / 13 = gold**, rectified, YOLO, $0, under 3 s, boxes on the windows |
| phone photo of colorful-10706 | windows / saunas / toilets | **7 / 1 / 1 = gold** |
| the same photo with an EXIF rotation tag, typed "how mnay windws are there?" | | read as "how many windows are there?", **7** |
| screenshot of a listing page with colorful-10706 | windows / toilets / "what is the price?" | **7 / 1 = gold** (generic vision said 6 before the YOLO route), "289 000 EUR" read off the page |
| NIST 12-page vector set (public domain) | toilets on page 3 (picked in the UI) | 2, boxed on page 3 |
| | "Which sheet shows the cafeteria?" | auto-picked page 10 by its words |
| 4-page PDF: 2 text pages, a **scanned** sheet on page 3, an appendix | "What is the ceiling height of the living room?" | auto-picked page 3, **8'-1 1/2"** from the finish schedule, box on the cell |
| 2-page TIFF | "How many rooms are labelled chamber?" | page 2 picked by looking at the thumbnails, **6** (correct) |
| sideways scanned PDF / sideways JPG | sheet number / architect | turned upright on upload, **A-7** / **J. H. De Sibour** |
| 1785 Mass Ave (1900s print) | chambers, living room size, architect | **6**, 24' x 45', J. H. De Sibour |
| 30 MB 7000x9300 JPEG | rooms | downscaled on upload, answered in 20 s |
| 120-page, 31 MB PDF | any | uploaded in 11 s, answers in 15-19 s |
| board-meeting minutes PDF | "How many doors?" / "What was the maintenance budget?" | **not a drawing, no count** / "48 500 EUR" cited |
| AI photo of a living room | "How many windows on this floor plan?" | **not a drawing** (before: "4 windows") |
| 3D-rendered colour plan | bedrooms / bathrooms / area | 0 at 40 % (before: 0 at 90 %) / 1 / no area printed, so abstains |
| buildingSMART IFC4 / IFC2x3 samples | doors, windows, storeys, floor area | 0 / 0 / 1 storey (fact-sheet fallback) / 24.6 m² |
| jscad floorplan.dxf | labelled rooms / largest room | 18 / "2 CAR GARAGE" |
| truncated PDF, random-bytes PNG, empty DXF, text file named .ifc, DWG | | 422 / 422 / 422 / 422 / 415, each with a reason |

## 4. Still weak (known, not fixed)

* **Counting rooms by name on non-Finnish plans** varies between runs (e.g. "bedrooms on the enlarged plan" of
  the Capehart sheet: 4 one run, nothing found the next). It now abstains instead of answering wrongly, but it
  often abstains.
* **Mixed sheets**: "how many toilets" on a sheet with a plan *and* elevations also counts toilets drawn in the
  elevations (Capehart: 6, true count in plan 2). Ask about "the plan" and pick the page, or check the boxes.
* **Automatic page choice in big sets** is only as good as the words. "The single-family house" on the NIST set
  went to the toilet-room enlargements (page 2) instead of the house plan (page 3). The page picker fixes it in
  one click.
* **Dense text questions on vector sets** (e.g. "overall length of the garage") come back at 30 % confidence or
  abstain. The text layer does not say which dimension string belongs to which room.
* **No track record for uploads.** Answers on uploads say "no track record yet", including the detector's,
  whose CubiCasa test record (kept in `calibration_dataset`) was measured on clean dataset scans, not on
  photos or other drawing styles. We have 30 hand-checked files, not a measured accuracy.
* No OCR on scans: scanned PDFs are read by the vision model only (fine for titles, schedules and labels;
  weaker for long tables).
* HEIC (iPhone) files are converted to JPG on upload (`pillow-heif`; refused with advice to share as JPG only
  if that package is missing).
