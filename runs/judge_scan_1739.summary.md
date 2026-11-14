# Judge run `scan_1739` (code 39fe0dd)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 25/41 | 26/41 | 8.3 | 0.069 |
| png2500 | 22/41 | 22/41 | 8.1 | 0.083 |
| scanpdf | 24/41 | 24/41 | 14.2 | 0.215 |
| roughscan | 18/41 | 18/41 | 13.0 | 0.157 |

**all forms: 89/164 strict**

By sheet: archA101F 3/8, dormA1 8/8, dormA2 17/24, dormA4 7/8, dormA7 3/12, pipeM101A 17/24, pipeM101F 8/8, schedA601 4/8, school00 5/28, schoolL01 3/4, slab100F 10/24, slabS100A 1/4, slabS102P 3/4

By category: area-convert 8/8, area-dims 3/4, area-multi-room-hard 0/4, area-room 1/4, area-sum 7/12, area-table 8/8, area-tag 3/4, baseboard-hard 0/4, count-easy 3/4, count-legend 2/4, doors-count 0/12, notes-sum 3/4, piping-count 6/8, piping-count+size 0/4, piping-equipment 4/4, piping-size 8/8, piping-tags-hard 3/4, rooms+area 0/4, rooms-count 3/12, schedule 0/4, slab-area 0/4, slab-area-by-type 2/4, slab-count 1/4, slab-rebar 7/8, slab-volume 0/4, trick 17/20

| id | sheet | lang | question | gold | lowres | png2500 | scanpdf | roughscan | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| j01 | dormA2 | en | How many dorm rooms are on the second floor? | 48 | Y 48 | Y 48 | Y 48 | - 144 | sheets-zones-schedule | 1 | 7.3 |
| j02 | dormA2 | en | Total net floor area of the east wing dorm rooms? | 6092 | Y 6092 | Y 6092 | Y 6092 | Y 6092 | sheets-zones-schedule | 3 | 2.5 |
| j03 | dormA2 | fi | Montako esteetöntä (ABA) asuntolahuonetta tässä kerroksessa on? | 2 | Y 2 | Y 2 | - (abstain; guess 2) | - (abstain; guess 2) | generic-ground-haiku | 2 | 8.0 |
| j04 | dormA2 | de | Wie groß ist die gesamte Verkehrsfläche (Circulation) im 2. OG? | 4470 | - 4.47 | - 4.47 | - 4.47 | - 4.47 | generic-read-haiku | 4 | 5.5 |
| j05 | dormA2 | en | What's the gross area of the second floor in square metres? | 2467.7 | Y 2467.7 | Y 2467.7 | Y 2467.7 | Y 2467.7 | sheets-zones-schedule | 17 | 4.4 |
| t01 | dormA2 | en | What is the ceiling height in the dorm rooms? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 2.8 |
| j07 | slab100F | en | What reinforcement is in the 150 mm slab? | D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | sheets-slab-note | 2 | 21.0 |
| j08 | slab100F | fi | Mikä on 300 mm laatan pinta-ala siinä osassa, jossa on D22-raudoitus? | 26.49 ~ | - (abstain) | - (abstain) | - (abstain) | - (abstain) | sheets-none | 0 | 22.0 |
| j09 | slab100F | en | Slab area by type (thickness and bars)? | 300 D16 ~214.5 m2; 150 D13 ~61 ~ | Y 300 mm w/ D22 @ 300: 26.5 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.7 m²; 150 mm w/  | - 300 mm w/ D16 @ 300: 256.7 m²; 150 mm w/ | - 300 | sheets-slab-area-by-type | 6 | 10.1 |
| j10 | slab100F | sv | Hur långa är kabel- och rörkanalerna (trenches) sammanlagt? | 7850 | ~ 7650 mm (4275 + 1625 + 1750 mm, enligt n | Y 7850 mm (ca 7,85 m): 4275 + 1825 + 1750  | Y Ca 7 850 mm (4275 + 1825 + 1750 mm), enl | Y 7 850 mm (ca 7,85 m): motorcentralens ka | generic-read-haiku | 1 | 5.3 |
| j11 | slab100F | en | Concrete volume of the 150 mm slab-on-grade? | 9.25 ~ | - 61.81 | - 61.69 | - 61.5 | - (abstain) | sheets-slab-area | 2 | 0.2 |
| t02 | slab100F | en | What does the concrete for this slab cost per cubic metre? | not shown | - 304.68 | - 305.43 | - 318.16 | Y (abstain) | sheets-slab-area | 6 | 0.2 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | - 5 | - 5 | - 5 | - 0 | sheets-piping | 5 | 0.6 |
| j14 | pipeM101A | fi | Montako polttoainepumppua (FP) piirustuksessa on? | 5 | Y 5 | Y 5 | Y 5 | - 3 (FP-2, FP-4, FP-5) | sheets-piping | 5 | 3.1 |
| j15 | pipeM101A | en | How many filter separators are there in total (FSI + FSR)? | 7 | Y 7 | Y 7 | Y 7 | - 0 | sheets-piping | 7 | 0.2 |
| j16 | pipeM101A | de | Welche Nennweite hat der Saugsammler (suction header)? | 16" | Y 16" (Nennweite 16 Zoll) | Y 16" (16 Zoll) | Y 16" | Y 16" (Nennweite 16 Zoll) | sheets-piping | 1 | 3.1 |
| j17 | pipeM101A | en | How many distinct pipe support tags (PS-x) are used on this plan? | 23 | Y 23 | Y 23 | Y 23 | - 0 | sheets-piping | 40 | 0.3 |
| t03 | pipeM101A | en | How many fire sprinkler heads are shown on this piping plan? | none | Y 0 | Y 0 | Y 0 | Y 0 | generic-ground-haiku | 0 | 4.7 |
| j19 | school00 | fi | Montako luokkahuonetta tässä kerroksessa on? | 8 | - 0 | - 0 | - 0 | - 0 | generic-ground-haiku | 0 | 7.3 |
| j20 | school00 | sv | Hur många grupprum finns det på plan 00? | 10 | - (abstain; guess 8) | - (abstain; guess 10) | - (abstain; guess 9) | - (abstain; guess 9) | generic-ground-haiku | 8 | 9.8 |
| j21 | school00 | fi | Paljonko jalkalistaa tarvitaan luokkahuoneisiin? | 265 ~ | - (abstain) | - (abstain) | - (abstain) | - (abstain) | sheets-arch-noroom | 0 | 12.8 |
| j22 | school00 | en | How many m2 of tiling for all WCs? | 31 ~ | - (abstain; guess 4) | - (abstain; guess 6) | - Total 1459 m² net over 97 rooms. Purpose | - (abstain; guess cor: 9,324.9 m²; SEN-DFE | generic-ground-haiku | 4 | 19.3 |
| j23 | school00 | en | Floor area of the Multi-Purpose Hall? | 243 ~ | Y 246.9 | - 35.4 | - 294.75 | - (abstain; guess cor: 9,324.9 m²; SEN-DFE | sheets-arch-rooms | 11 | 4.8 |
| j24 | school00 | en | How many doors open into the Multi-Purpose Hall? | 8 | - 119 | - 128 | - 128 | - 123 | sheets-openings-yolo | 119 | 0.8 |
| t04 | school00 | en | What is the U-value of the external walls? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 3.1 |
| j26 | dormA1 | en | What's the total first floor area? | 28770 | Y 28770 | Y 28770 | Y 28770 | Y 28770 | sheets-zones-schedule | 1 | 9.3 |
| j27 | dormA1 | fi | Paljonko yhteistiloja (common space) ensimmäisessä kerroksessa on neli | 406.8 | Y Yhteistilojen yhteispinta-ala on 6 687 S | Y 6 687 SF (neliojalkaa, ei neliömetriä).  | Y 6 687 SF (square feet), eli noin 621 m². | Y 6 687 SF (neliöjalkaa), noin 621 m². Pii | generic-read-haiku | 1 | 7.0 |
| j29 | dormA4 | en | Area of the kitchen? | 151 | Y 151 | - 126 SF | Y 151 | Y 151 | generic-read-haiku | 1 | 13.2 |
| j30 | dormA4 | de | Wie groß ist die Fläche aller Technikräume (ELEC, FIRE RISER/PUMP, PRI | 1050 | Y 1050 | Y 1050 | Y 1050 | Y 1050 | generic-read-haiku | 4 | 6.4 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | - 0 | - (abstain; guess 4) | - (abstain; guess 0) | - (abstain; guess 4) | generic-ground-haiku | 0 | 6.1 |
| j32 | dormA7 | en | Total bathroom floor area in one dorm module (for tiling)? | 204 | Y 204 | - 100 SF | Y 204 | Y 204 | generic-read-haiku | 4 | 14.1 |
| j34 | pipeM101F | en | What size is the pump discharge header? | 300 mm | Y 300mm | Y 300mm | Y 300mm | Y 300mm | sheets-piping | 2 | 1.2 |
| j35 | pipeM101F | fi | Kuinka suuri paineiskusäiliö (surge tank) on? | 150 L | Y 150 litraa (150 L) | Y 150 litraa (150 LITER SURGE TANK) | Y 150 litraa (150 L) | Y 150 litraa | sheets-piping | 1 | 3.2 |
| j37 | slabS100A | en | How many pump pads are on the pumphouse slab? | 5 | - 7 | - 6 | Y 5 | - 7 | generic-ground-haiku | 7 | 30.6 |
| j38 | slabS102P | en | What is the reinforcement of the tank floor slab? | D19 @ 250 E.W. top and bottom; | Y D19 bars at 250 mm spacing in both top a | - D22x3000 | Y D19 bars at 250 spacing, E/W top and bot | Y Two-way reinforcement, top and bottom la | generic-read-haiku | 5 | 24.5 |
| j39 | archA101F | en | How many doors does the filter building have? | 6 | - 9 | - 9 | - 7 | - 8 | sheets-openings-yolo | 9 | 2.3 |
| j40 | archA101F | en | What is the floor area of the generator room? | 26.49 | Y 26.5 | Y 26.5 | Y 26.5 | - 6200 | generic-read-haiku | 3 | 13.1 |
| j41 | schedA601 | en | How many doors are listed in the pumphouse door schedule, and how many | 8 doors, 6 of them 3'-0" wide | - 0 | - 0 | - 0 | - 0 | generic-ground-haiku | 0 | 4.3 |
| t05 | schedA601 | en | What fire rating do the pumphouse doors have? | none given | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | generic-read-haiku | 1 | 7.2 |
| j43 | schoolL01 | en | How many group rooms are on level 01? | 5 | Y 5 | Y 5 | Y 5 | - (abstain; guess 4) | generic-ground-haiku | 5 | 13.1 |
| j44 | dormA7 | en | How many doors are in this dormitory module? | 8 | - 18 | - 17 | - 3 | - 16 | sheets-openings-yolo | 18 | 26.7 |

API cost of all asks $0.524. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
