# Judge run `baseline` (code d9322ce)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 21/40 | 22/40 | 17.8 | 0.191 |
| png2500 | 23/40 | 23/40 | 17.1 | 0.280 |
| pdf | 26/40 | 28/40 | 5.5 | 0.047 |
| hires | 21/40 | 23/40 | 11.3 | 0.133 |

**all forms: 91/160 strict**

By sheet: archA101F 2/8, dormA1 7/8, dormA2 20/24, dormA4 6/8, dormA7 0/8, pipeM101A 19/24, pipeM101F 8/8, schedA601 4/8, school00 6/28, schoolL01 4/4, slab100F 11/24, slabS100A 2/4, slabS102P 2/4

By category: area-convert 7/8, area-dims 2/4, area-multi-room-hard 0/4, area-room 0/4, area-sum 5/12, area-table 7/8, area-tag 2/4, baseboard-hard 0/4, count-easy 4/4, count-legend 4/4, doors-count 0/8, notes-sum 3/4, piping-count 8/8, piping-count+size 0/4, piping-equipment 4/4, piping-size 8/8, piping-tags-hard 3/4, rooms+area 0/4, rooms-count 6/12, schedule 0/4, slab-area 0/4, slab-area-by-type 4/4, slab-count 2/4, slab-rebar 6/8, slab-volume 0/4, trick 16/20

| id | sheet | lang | question | gold | lowres | png2500 | pdf | hires | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| j01 | dormA2 | en | How many dorm rooms are on the second floor? | 48 | Y 48 | Y 48 | Y 48 | Y 48 | sheets-zones-schedule | 1 | 6.3 |
| j02 | dormA2 | en | Total net floor area of the east wing dorm rooms? | 6092 | Y 6092 | Y 6092 | Y 6092 | Y 6092 | sheets-zones-schedule | 3 | 2.8 |
| j03 | dormA2 | fi | Montako esteetöntä (ABA) asuntolahuonetta tässä kerroksessa on? | 2 | Y 2 | Y 2 | Y 2 | Y 2 | generic-ground-haiku | 2 | 8.1 |
| j04 | dormA2 | de | Wie groß ist die gesamte Verkehrsfläche (Circulation) im 2. OG? | 4470 | - 4.47 | - 4.47 | Y 4470 | - 4.47 | generic-read-haiku | 4 | 7.3 |
| j05 | dormA2 | en | What's the gross area of the second floor in square metres? | 2467.7 | - 26,562 SF | Y 2467.7 | Y 2467.7 | Y 2467.7 | sheets-zones-schedule | 18 | 4.3 |
| t01 | dormA2 | en | What is the ceiling height in the dorm rooms? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 4.1 |
| j07 | slab100F | en | What reinforcement is in the 150 mm slab? | D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | sheets-slab-note | 2 | 27.8 |
| j08 | slab100F | fi | Mikä on 300 mm laatan pinta-ala siinä osassa, jossa on D22-raudoitus? | 26.49 ~ | - (abstain) | - (abstain) | - (abstain; guess 795 x 1200 mm = 0,954 m² | - (abstain) | sheets-none | 0 | 5.3 |
| j09 | slab100F | en | Slab area by type (thickness and bars)? | 300 D16 ~214.5 m2; 150 D13 ~61 ~ | Y 300 mm w/ D22 @ 300: 26.7 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.7 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.9 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.8 m²; 150 mm w/  | sheets-slab-area-by-type | 6 | 0.3 |
| j10 | slab100F | sv | Hur långa är kabel- och rörkanalerna (trenches) sammanlagt? | 7850 | ~ Sammanlagt ca 7 650 mm (7,65 m): motorce | Y 7850 mm (4275 + 1825 + 1750) | Y 7850 | Y 7850 mm (ca 7,85 m) sammanlagt: 4275 + 1 | generic-read-haiku | 1 | 7.4 |
| j11 | slab100F | en | Concrete volume of the 150 mm slab-on-grade? | 9.25 ~ | - 62.06 | - 61.69 | - 61.69 | - 61.69 | sheets-slab-area | 2 | 0.3 |
| t02 | slab100F | en | What does the concrete for this slab cost per cubic metre? | not shown | - 302.79 | - 312.31 | - 312.48 | - 312.53 | sheets-slab-area | 6 | 0.3 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | - 5 | - 5 | - 5 | - 5 | sheets-piping | 5 | 0.3 |
| j14 | pipeM101A | fi | Montako polttoainepumppua (FP) piirustuksessa on? | 5 | Y 5 | Y 5 | Y 5 | Y 5 | generic-ground-haiku | 5 | 10.1 |
| j15 | pipeM101A | en | How many filter separators are there in total (FSI + FSR)? | 7 | Y 7 | Y 7 | Y 7 | Y 7 | sheets-piping | 7 | 0.3 |
| j16 | pipeM101A | de | Welche Nennweite hat der Saugsammler (suction header)? | 16" | Y 16" | Y 16" (16 Zoll) | Y 16" | Y 16" | sheets-piping | 1 | 2.5 |
| j17 | pipeM101A | en | How many distinct pipe support tags (PS-x) are used on this plan? | 23 | Y 23 | Y 23 | Y 23 | - 22 | sheets-piping | 40 | 0.3 |
| t03 | pipeM101A | en | How many fire sprinkler heads are shown on this piping plan? | none | Y 0 | Y 0 | Y 0 | Y 0 | generic-ground-haiku | 0 | 7.6 |
| j19 | school00 | fi | Montako luokkahuonetta tässä kerroksessa on? | 8 | - (abstain; guess 0) | - 0 | Y 8 | - 0 | generic-ground-haiku | 0 | 5.9 |
| j20 | school00 | sv | Hur många grupprum finns det på plan 00? | 10 | - 0 | - (abstain; guess 10) | Y 10 | - (abstain; guess 10) | generic-ground-haiku | 10 | 8.1 |
| j21 | school00 | fi | Paljonko jalkalistaa tarvitaan luokkahuoneisiin? | 265 ~ | - (abstain) | - (abstain) | - (abstain) | - (abstain) | sheets-arch-noroom | 0 | 32.6 |
| j22 | school00 | en | How many m2 of tiling for all WCs? | 31 ~ | - Total 1481 m² net over 85 rooms. Corrido | - Total 1491 m² net over 125 rooms. Multi- | - Total 1539 m² net over 106 rooms. Second | - Total 1542 m² net over 99 rooms. Multi-P | sheets-rooms-area-list | 100 | 1.5 |
| j23 | school00 | en | Floor area of the Multi-Purpose Hall? | 243 ~ | - Total 1481 m² net over 85 rooms. Corrido | - 294.6 | ~ 258.07 | ~ 257.99 | sheets-rooms-area | 2 | 0.3 |
| j24 | school00 | en | How many doors open into the Multi-Purpose Hall? | 8 | - 106 | - 127 | - 128 | - 128 | sheets-arch-detector-door | 128 | 0.3 |
| t04 | school00 | en | What is the U-value of the external walls? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 3.8 |
| j26 | dormA1 | en | What's the total first floor area? | 28770 | - (abstain) | Y 28770 | Y 28770 | Y 28770 | sheets-zones-schedule | 15 | 8.2 |
| j27 | dormA1 | fi | Paljonko yhteistiloja (common space) ensimmäisessä kerroksessa on neli | 406.8 | Y Drawing gives common space as 4,379 SF ( | Y Piirustus ilmoittaa yhteistilat neliöjal | Y ≈407 m² (4,379 SF) | Y Piirustuksessa yhteistilat ilmoitetaan n | generic-read-haiku | 2 | 9.3 |
| j29 | dormA4 | en | Area of the kitchen? | 151 | Y 151 | - 126 SF | Y 151 SF | - (abstain) | timeout | 0 | 75.2 |
| j30 | dormA4 | de | Wie groß ist die Fläche aller Technikräume (ELEC, FIRE RISER/PUMP, PRI | 1050 | Y 1050 | Y 1050 | Y 1048 | Y 1050 | generic-read-haiku | 4 | 7.6 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | - 0 | - 0 | - 4 | - (abstain; guess 0) | generic-ground-haiku | 0 | 11.4 |
| j32 | dormA7 | en | Total bathroom floor area in one dorm module (for tiling)? | 204 | - 102 SF | - 51 SF | - Total 414 m² net over 35 rooms. BATH 6.4 | - 51 | sheets-zones-schedule | 1 | 8.6 |
| j34 | pipeM101F | en | What size is the pump discharge header? | 300 mm | Y 300mm | Y 300mm | Y 300mm | Y 300mm | sheets-piping | 2 | 75.2 |
| j35 | pipeM101F | fi | Kuinka suuri paineiskusäiliö (surge tank) on? | 150 L | Y 150 litraa (150 L) | Y 150 litraa (150 LITER SURGE TANK) | Y 150 litraa | Y 150 litraa | sheets-piping | 1 | 4.8 |
| j37 | slabS100A | en | How many pump pads are on the pumphouse slab? | 5 | Y 5 | Y 5 | - 7 | - 12 | generic-ground-haiku | 12 | 42.4 |
| j38 | slabS102P | en | What is the reinforcement of the tank floor slab? | D19 @ 250 E.W. top and bottom; | - D22x3000 | - D22x3000 | Y D19 @ 250; D19 HOOP @ 200; D19 HOOP @ 25 | Y D19 bars at 250 mm spacing, top and bott | generic-read-haiku | 3 | 32.3 |
| j39 | archA101F | en | How many doors does the filter building have? | 6 | - 7 | - 7 | - 7 | - 7 | sheets-arch-detector-door | 7 | 5.6 |
| j40 | archA101F | en | What is the floor area of the generator room? | 26.49 | Y 26.5 | Y 26.5 | ~ 25.5 | ~ 25.5 | sheets-arch-rooms | 1 | 6.1 |
| j41 | schedA601 | en | How many doors are listed in the pumphouse door schedule, and how many | 8 doors, 6 of them 3'-0" wide | - 0 | - 0 | - 8 | - 0 | generic-ground-haiku | 0 | 3.8 |
| t05 | schedA601 | en | What fire rating do the pumphouse doors have? | none given | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | generic-read-haiku | 1 | 4.8 |
| j43 | schoolL01 | en | How many group rooms are on level 01? | 5 | Y 5 | Y 5 | Y 5 | Y 5 | sheets-arch-rooms-count | 5 | 8.9 |

API cost of all asks $0.651. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
