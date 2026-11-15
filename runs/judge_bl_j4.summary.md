# Judge run `bl_j4` (code 9fed8ee)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 35/41 | 35/41 | 6.0 | 0.357 |
| png2500 | 38/41 | 39/41 | 6.4 | 0.258 |
| pdf | 33/41 | 36/41 | 9.1 | 0.014 |
| scanpdf | 37/41 | 38/41 | 6.7 | 0.366 |
| roughscan | 31/41 | 31/41 | 7.9 | 0.334 |

**all forms: 174/205 strict**

By sheet: archA101F 7/10, dormA1 10/10, dormA2 29/30, dormA4 9/10, dormA7 8/15, pipeM101A 29/30, pipeM101F 10/10, schedA601 8/10, school00 23/35, schoolL01 4/5, slab100F 27/30, slabS100A 5/5, slabS102P 5/5

By category: area-convert 10/10, area-dims 4/5, area-multi-room-hard 0/5, area-room 5/5, area-sum 13/15, area-table 10/10, area-tag 5/5, baseboard-hard 0/5, count-easy 5/5, count-legend 4/5, doors-count 8/15, notes-sum 5/5, piping-count 10/10, piping-count+size 5/5, piping-equipment 5/5, piping-size 10/10, piping-tags-hard 4/5, rooms+area 4/5, rooms-count 12/15, schedule 3/5, slab-area 4/5, slab-area-by-type 4/5, slab-count 5/5, slab-rebar 10/10, slab-volume 4/5, trick 25/25

| id | sheet | lang | question | gold | lowres | png2500 | pdf | scanpdf | roughscan | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| j01 | dormA2 | en | How many dorm rooms are on the second floor? | 48 | Y 48 | Y 48 | Y 48 | Y 48 | Y 48 | sheets-zones-schedule | 1 | 5.2 |
| j02 | dormA2 | en | Total net floor area of the east wing dorm rooms? | 6092 | Y 6092 | Y 6092 | Y 6092 | Y 6092 | Y 6092 | sheets-zones-schedule | 3 | 5.1 |
| j03 | dormA2 | fi | Montako esteetöntä (ABA) asuntolahuonetta tässä kerroksessa on? | 2 | Y 2 | Y 2 | Y 2 | Y 2 | - (abstain; guess 2) | generic-ground-haiku | 2 | 15.9 |
| j04 | dormA2 | de | Wie groß ist die gesamte Verkehrsfläche (Circulation) im 2. OG? | 4470 | Y 4470 | Y 4470 | Y 4470 | Y 4470 | Y 4470 | sheets-zones-schedule | 4 | 2.1 |
| j05 | dormA2 | en | What's the gross area of the second floor in square metres? | 2467.7 | Y 2467.7 | Y 2467.7 | Y 2467.7 | Y 2467.7 | Y 2467.7 | sheets-zones-schedule | 17 | 3.4 |
| t01 | dormA2 | en | What is the ceiling height in the dorm rooms? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 2.5 |
| j07 | slab100F | en | What reinforcement is in the 150 mm slab? | D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | sheets-slab-note | 2 | 2.1 |
| j08 | slab100F | fi | Mikä on 300 mm laatan pinta-ala siinä osassa, jossa on D22-raudoitus? | 26.49 ~ | Y 26.49 | Y 26.66 | Y 26.7 | Y 26.41 | - (abstain) | sheets-slab-area | 2 | 2.0 |
| j09 | slab100F | en | Slab area by type (thickness and bars)? | 300 D16 ~214.5 m2; 150 D13 ~61 ~ | Y 300 mm w/ D22 @ 300: 26.5 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.7 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.7 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.4 m²; 150 mm w/  | - 150 mm w/ D13 @ 300: 52.2 m²; 300 mm w/  | sheets-slab-area-by-type | 6 | 0.4 |
| j10 | slab100F | sv | Hur långa är kabel- och rörkanalerna (trenches) sammanlagt? | 7850 | Y 7.85 | Y 7.85 | Y 7.85 | Y 7.85 | Y 7.85 | sheets-slab-trench | 6 | 0.3 |
| j11 | slab100F | en | Concrete volume of the 150 mm slab-on-grade? | 9.25 ~ | Y 9.27 | Y 9.25 | Y 9.25 | Y 9.06 | - 7.83 | sheets-slab-volume | 2 | 0.2 |
| t02 | slab100F | en | What does the concrete for this slab cost per cubic metre? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 2.2 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | parts:sheets-piping+sheets-piping | 6 | 3.0 |
| j14 | pipeM101A | fi | Montako polttoainepumppua (FP) piirustuksessa on? | 5 | Y 5 | Y 5 | Y 5 | Y 5 | Y 5 | sheets-piping | 5 | 2.6 |
| j15 | pipeM101A | en | How many filter separators are there in total (FSI + FSR)? | 7 | Y 7 | Y 7 | Y 7 | Y 7 | Y 7 | sheets-piping | 7 | 4.7 |
| j16 | pipeM101A | de | Welche Nennweite hat der Saugsammler (suction header)? | 16" | Y 16" | Y 16" | Y 16" | Y 16" | Y 16" | sheets-piping | 1 | 1.0 |
| j17 | pipeM101A | en | How many distinct pipe support tags (PS-x) are used on this plan? | 23 | Y 23 | Y 23 | Y 23 | Y 23 | - 21 | sheets-piping | 44 | 5.4 |
| t03 | pipeM101A | en | How many fire sprinkler heads are shown on this piping plan? | none | Y 0 | Y 0 | Y 0 | Y 0 | Y 0 | generic-ground-haiku | 0 | 6.1 |
| j19 | school00 | fi | Montako luokkahuonetta tässä kerroksessa on? | 8 | - 6 | Y 8 | Y 8 | Y 8 | Y 8 | sheets-rooms-count-typed | 6 | 3.5 |
| j20 | school00 | sv | Hur många grupprum finns det på plan 00? | 10 | - (abstain; guess 9) | Y 10 | Y 10 | Y 10 | Y 10 | generic-ground-haiku | 9 | 20.5 |
| j21 | school00 | fi | Paljonko jalkalistaa tarvitaan luokkahuoneisiin? | 265 ~ | - 157.6 | ~ 239.4 | ~ 225.7 | ~ 239.1 | - 200.2 | sheets-rooms-baseboard | 28 | 15.1 |
| j22 | school00 | en | How many m2 of tiling for all WCs? | 31 ~ | - 1467.0 | - 23.2 | - 19.0 | - 14.5 | - 21.3 | sheets-rooms-area-total | 86 | 0.4 |
| j23 | school00 | en | Floor area of the Multi-Purpose Hall? | 243 ~ | Y 245.66 | Y 245.91 | Y 244.77 | Y 245.7 | Y 246.08 | sheets-rooms-area | 3 | 3.1 |
| j24 | school00 | en | How many doors open into the Multi-Purpose Hall? | 8 | Y 9 | Y 8 | Y 8 | Y 8 | Y 8 | sheets-openings-room | 10 | 11.6 |
| t04 | school00 | en | What is the U-value of the external walls? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 2.3 |
| j26 | dormA1 | en | What's the total first floor area? | 28770 | Y 28770 | Y 28770 | Y 28770 | Y 28770 | Y 28770 | sheets-zones-schedule | 1 | 6.1 |
| j27 | dormA1 | fi | Paljonko yhteistiloja (common space) ensimmäisessä kerroksessa on neli | 406.8 | Y 621.2 | Y 621 | Y 621.2 | Y 621.2 | Y 621.2 | sheets-zones-schedule | 1 | 3.8 |
| j29 | dormA4 | en | Area of the kitchen? | 151 | Y 151 | Y 151 | Y 151 SF | Y 151 | Y 151 | generic-read-haiku | 1 | 7.3 |
| j30 | dormA4 | de | Wie groß ist die Fläche aller Technikräume (ELEC, FIRE RISER/PUMP, PRI | 1050 | Y 1050 | Y 1050 | ~ 1122 | Y 1050 | Y 1050 | generic-read-haiku | 4 | 6.4 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | Y Bedrooms: 4; Area of one bedroom: 189 | Y Bedrooms: 4; Area of one bedroom: 189 | - Bedrooms: not sure; Area of one bedroom: | Y Bedrooms: 4; Area of one bedroom: 189 | Y Bedrooms: 4; Area of one bedroom: 189 | parts:generic-ground-haiku+generic-read-haiku | 6 | 16.0 |
| j32 | dormA7 | en | Total bathroom floor area in one dorm module (for tiling)? | 204 | Y 204 | Y 204 | - 102 | Y 204 | Y 204 | generic-read-haiku | 4 | 6.3 |
| j34 | pipeM101F | en | What size is the pump discharge header? | 300 mm | Y 300mm | Y 300mm | Y 300mm | Y 300mm | Y 300mm | sheets-piping | 2 | 0.5 |
| j35 | pipeM101F | fi | Kuinka suuri paineiskusäiliö (surge tank) on? | 150 L | Y 150 LITER | Y 150 LITER | Y 150 LITER | Y 150 LITER | Y 150 LITER | sheets-piping | 1 | 0.5 |
| j37 | slabS100A | en | How many pump pads are on the pumphouse slab? | 5 | Y 5 | Y 5 | Y 5 | Y 5 | Y 5 | sheets-slab-pads | 0 | 3.0 |
| j38 | slabS102P | en | What is the reinforcement of the tank floor slab? | D19 @ 250 E.W. top and bottom; | Y D19 radial bars at 250 mm spacing (top a | Y D19 RADIAL BARS; D19 @ 250 E.W TOP AND B | Y D19 RADIAL BARS; D19 HOOP @ 200; D19 @ 2 | Y D19 RADIAL BARS; D19 @ 250 E.W TOP AND B | Y D19 bars at 250 spacing, top and bottom  | generic-read-haiku | 5 | 4.7 |
| j39 | archA101F | en | How many doors does the filter building have? | 6 | - 8 | Y 6 | Y 6 | Y 6 | - 8 | sheets-openings-yolo | 9 | 13.0 |
| j40 | archA101F | en | What is the floor area of the generator room? | 26.49 | Y 26.49 | Y 26.48 | ~ 25.5 | Y 26.49 | Y 26.5 | generic-read-haiku | 3 | 11.0 |
| j41 | schedA601 | en | How many doors are listed in the pumphouse door schedule, and how many | 8 doors, 6 of them 3'-0" wide | Y Doors: 8; 3'-0" wide: 6 | Y Doors: 8; 3'-0" wide: 6 | - Doors: 6; 3'-0" wide: 6 | - Doors: 16; 3'-0" wide: 6 | Y Doors: 8; 3'-0" wide: 6 | parts:generic-ground-haiku+generic-ground-haiku | 14 | 14.8 |
| t05 | schedA601 | en | What fire rating do the pumphouse doors have? | none given | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | generic-read-haiku | 1 | 4.8 |
| j43 | schoolL01 | en | How many group rooms are on level 01? | 5 | Y 5 | Y 5 | Y 5 | Y 5 | - 4 | generic-ground-haiku | 5 | 15.4 |
| j44 | dormA7 | en | How many doors are in this dormitory module? | 8 | - 4 doors (+12 closet doors not counted) | - 4 doors (+12 closet doors not counted) | - 4 doors (+12 closet doors not counted) | - 4 doors (+10 closet doors not counted) | - 7 doors (+7 closet doors not counted) | sheets-openings-yolo | 16 | 13.3 |

API cost of all asks $1.329. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
