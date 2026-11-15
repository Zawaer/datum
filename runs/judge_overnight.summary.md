# Judge question set: overnight run (sheet specialists on scans)

Code d4d056d (git HEAD at the start of the run), local server on :3186 with fresh caches, one form at a time. Same 41 questions x 6 upload forms as `judge_scan_1739` (analysis/judge_questions.jsonl, scored by analysis/judge_run.py; re-scored here with the current questions file). 'start of night' = the same scan forms on HEAD 2846622 at 19:20 UTC.

| form | scan_1739 | start of night | overnight | improved vs scan_1739 | regressed vs scan_1739 |
|---|---|---|---|---|---|
| lowres | 25/41 | 32/41 | 36/41 | j04, j08, j10, j11, j13, j19, j24, j31, j37, j41, t02 | - |
| png2500 | 22/41 | 30/41 | 37/41 | j04, j08, j11, j13, j19, j20, j23, j24, j29, j31, j32, j37, j38, j39, j41, t02 | j03 |
| scanpdf | 24/41 | 30/41 | 36/41 | j03, j04, j08, j09, j11, j13, j19, j23, j24, j31, j39, t02 | - |
| roughscan | 18/41 | 26/41 | 30/41 | j01, j04, j13, j14, j15, j17, j23, j24, j31, j37, j40, j41 | - |
| pdf | - | - | 34/41 | - | - |
| hires | - | - | 35/41 | - | - |
| **scan forms (lowres, png2500, scanpdf, roughscan)** | 89/164 | 118/164 | 139/164 | | |
| **all six forms** | | | 208/246 | | |

Still wrong overnight (all forms), by question:

- j03 (Montako esteetöntä (ABA) asuntolahuonetta tässä kerroksessa on? | gold 2): png2500: 4 (sheets-text-read); roughscan: 0 (generic-ground-haiku)
- j08 (Mikä on 300 mm laatan pinta-ala siinä osassa, jossa on D22-raudoitus? | gold 26.49): roughscan: 72.22 (sheets-slab-area)
- j09 (Slab area by type (thickness and bars)? | gold 300 D16 ~214.5 m2; 150 D13 ~61.7 m2; 300): roughscan: 150 mm w/ D13 @ 300: 52.2 m²; 300 mm w/  (sheets-slab-area-by-type)
- j11 (Concrete volume of the 150 mm slab-on-grade? | gold 9.25): roughscan: 7.83 (sheets-slab-volume)
- j19 (Montako luokkahuonetta tässä kerroksessa on? | gold 8): roughscan: 7 (sheets-rooms-count)
- j20 (Hur många grupprum finns det på plan 00? | gold 10): hires: 9 (sheets-arch-rooms-count); lowres: None (generic-ground-haiku); roughscan: None (generic-ground-haiku); scanpdf: 9 (generic-ground-haiku)
- j21 (Paljonko jalkalistaa tarvitaan luokkahuoneisiin? | gold 265): hires: 219.7 (sheets-rooms-baseboard); lowres: 209.5 (sheets-rooms-baseboard); pdf: 225.7 (sheets-rooms-baseboard); png2500: 239.4 (sheets-rooms-baseboard); roughscan: 246.0 (sheets-rooms-baseboard); scanpdf: 239.1 (sheets-rooms-baseboard)
- j22 (How many m2 of tiling for all WCs? | gold 31): hires: 17.5 (sheets-rooms-area-sum); lowres: 1467.0 (sheets-rooms-area-total); pdf: 19.0 (sheets-rooms-area-sum); png2500: 23.2 (sheets-rooms-area-sum); roughscan: 4.09 (sheets-rooms-area); scanpdf: 14.5 (sheets-rooms-area-sum)
- j30 (Wie groß ist die Fläche aller Technikräume (ELEC, FIRE RISER/PUMP, PRI | gold 1050): pdf: 1122 (generic-text-haiku)
- j32 (Total bathroom floor area in one dorm module (for tiling)? | gold 204): pdf: 102 (generic-text-haiku)
- j39 (How many doors does the filter building have? | gold 6): lowres: 9 (sheets-openings-yolo); pdf: 8 (sheets-openings-cv); roughscan: 8 (sheets-openings-yolo)
- j40 (What is the floor area of the generator room? | gold 26.49): hires: 25.5 (sheets-arch-rooms); pdf: 25.5 (sheets-arch-rooms)
- j41 (How many doors are listed in the pumphouse door schedule, and how many | gold 8 doors, 6 of them 3'-0" wide): hires: Doors: 13; 3'-0" wide: 6 (parts:generic-ground-haiku+generic-ground-haiku); scanpdf: Doors: 16; 3'-0" wide: 6 (parts:generic-ground-haiku+generic-ground-haiku)
- j43 (How many group rooms are on level 01? | gold 5): roughscan: 4 (generic-ground-haiku)
- j44 (How many doors are in this dormitory module? | gold 8): hires: 4 doors (+12 closet doors not counted) (sheets-openings-yolo); lowres: 4 doors (+12 closet doors not counted) (sheets-openings-yolo); pdf: 4 doors (+12 closet doors not counted) (sheets-openings-cv); png2500: 4 doors (+12 closet doors not counted) (sheets-openings-yolo); roughscan: 5 doors (+5 closet doors not counted) (sheets-openings-yolo); scanpdf: 4 doors (+10 closet doors not counted) (sheets-openings-yolo)

Per-question table of the run: runs/judge_overnight_full.summary.md.
