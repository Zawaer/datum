# Judge run `overnight_full` (code d4d056d)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 36/41 | 36/41 | 5.4 | 0.368 |
| png2500 | 37/41 | 38/41 | 5.8 | 0.279 |
| pdf | 34/41 | 37/41 | 6.4 | 0.017 |
| hires | 35/41 | 36/41 | 12.5 | 0.089 |
| scanpdf | 36/41 | 37/41 | 6.7 | 0.375 |
| roughscan | 30/41 | 31/41 | 7.8 | 0.317 |

**all forms: 208/246 strict**

By sheet: archA101F 7/12, dormA1 12/12, dormA2 34/36, dormA4 11/12, dormA7 11/18, pipeM101A 36/36, pipeM101F 12/12, schedA601 10/12, school00 25/42, schoolL01 5/6, slab100F 33/36, slabS100A 6/6, slabS102P 6/6

By category: area-convert 12/12, area-dims 4/6, area-multi-room-hard 0/6, area-room 6/6, area-sum 16/18, area-table 12/12, area-tag 6/6, baseboard-hard 0/6, count-easy 6/6, count-legend 4/6, doors-count 9/18, notes-sum 6/6, piping-count 12/12, piping-count+size 6/6, piping-equipment 6/6, piping-size 12/12, piping-tags-hard 6/6, rooms+area 6/6, rooms-count 12/18, schedule 4/6, slab-area 5/6, slab-area-by-type 5/6, slab-count 6/6, slab-rebar 12/12, slab-volume 5/6, trick 30/30

| id | sheet | lang | question | gold | lowres | png2500 | pdf | hires | scanpdf | roughscan | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| j01 | dormA2 | en | How many dorm rooms are on the second floor? | 48 | Y 48 | Y 48 | Y 48 | Y 48 | Y 48 | Y 48 | sheets-zones-schedule | 1 | 10.1 |
| j02 | dormA2 | en | Total net floor area of the east wing dorm rooms? | 6092 | Y 6092 | Y 6092 | Y 6092 | Y 6092 | Y 6092 | Y 6092 | sheets-zones-schedule | 3 | 2.3 |
| j03 | dormA2 | fi | Montako esteetöntä (ABA) asuntolahuonetta tässä kerroksessa on? | 2 | Y 2 | - 4 | Y 2 | Y 2 | Y 2 | - 0 | generic-ground-haiku | 2 | 56.7 |
| j04 | dormA2 | de | Wie groß ist die gesamte Verkehrsfläche (Circulation) im 2. OG? | 4470 | Y 4470 | Y 4470 | Y 4470 | Y 4470 | Y 4470 | Y 4470 | sheets-zones-schedule | 4 | 2.6 |
| j05 | dormA2 | en | What's the gross area of the second floor in square metres? | 2467.7 | Y 2467.7 | Y 2467.7 | Y 2467.7 | Y 2467.7 | Y 2467.7 | Y 2467.7 | sheets-zones-schedule | 18 | 2.8 |
| t01 | dormA2 | en | What is the ceiling height in the dorm rooms? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 4.3 |
| j07 | slab100F | en | What reinforcement is in the 150 mm slab? | D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | sheets-slab-note | 2 | 27.0 |
| j08 | slab100F | fi | Mikä on 300 mm laatan pinta-ala siinä osassa, jossa on D22-raudoitus? | 26.49 ~ | Y 26.49 | Y 26.66 | Y 26.7 | Y 26.49 | Y 26.41 | - 72.22 | sheets-slab-area | 2 | 0.8 |
| j09 | slab100F | en | Slab area by type (thickness and bars)? | 300 D16 ~214.5 m2; 150 D13 ~61 ~ | Y 300 mm w/ D22 @ 300: 26.5 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.7 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.7 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.5 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.4 m²; 150 mm w/  | - 150 mm w/ D13 @ 300: 52.2 m²; 300 mm w/  | sheets-slab-area-by-type | 6 | 0.8 |
| j10 | slab100F | sv | Hur långa är kabel- och rörkanalerna (trenches) sammanlagt? | 7850 | Y 7.85 | Y 7.85 | Y 7.85 | Y 7.85 | Y 7.85 | Y 7.85 | sheets-slab-trench | 7 | 0.8 |
| j11 | slab100F | en | Concrete volume of the 150 mm slab-on-grade? | 9.25 ~ | Y 9.27 | Y 9.25 | Y 9.25 | Y 9.25 | Y 9.06 | - 7.83 | sheets-slab-volume | 2 | 0.8 |
| t02 | slab100F | en | What does the concrete for this slab cost per cubic metre? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 2.8 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | parts:sheets-piping+sheets-piping | 7 | 11.2 |
| j14 | pipeM101A | fi | Montako polttoainepumppua (FP) piirustuksessa on? | 5 | Y 5 | Y 5 | Y 5 | Y 5 | Y 5 | Y 5 | sheets-piping | 5 | 1.0 |
| j15 | pipeM101A | en | How many filter separators are there in total (FSI + FSR)? | 7 | Y 7 | Y 7 | Y 7 | Y 7 | Y 7 | Y 7 | sheets-piping | 7 | 1.0 |
| j16 | pipeM101A | de | Welche Nennweite hat der Saugsammler (suction header)? | 16" | Y 16" | Y 16" | Y 16" | Y 16" | Y 16" | Y 16" | sheets-piping | 1 | 0.8 |
| j17 | pipeM101A | en | How many distinct pipe support tags (PS-x) are used on this plan? | 23 | Y 23 | Y 23 | Y 23 | Y 23 | Y 23 | Y 23 | sheets-piping | 41 | 7.1 |
| t03 | pipeM101A | en | How many fire sprinkler heads are shown on this piping plan? | none | Y 0 | Y 0 | Y 0 | Y 0 | Y 0 | Y 0 | generic-ground-haiku | 0 | 9.4 |
| j19 | school00 | fi | Montako luokkahuonetta tässä kerroksessa on? | 8 | Y 8 | Y 8 | Y 8 | Y 8 | Y 8 | - 7 | generic-ground-haiku | 8 | 24.8 |
| j20 | school00 | sv | Hur många grupprum finns det på plan 00? | 10 | - (abstain; guess 10) | Y 10 | Y 10 | - 9 | - 9 | - (abstain; guess 10) | sheets-arch-rooms-count | 9 | 0.5 |
| j21 | school00 | fi | Paljonko jalkalistaa tarvitaan luokkahuoneisiin? | 265 ~ | - 209.5 | ~ 239.4 | ~ 225.7 | - 219.7 | ~ 239.1 | ~ 246.0 | sheets-rooms-baseboard | 40 | 14.4 |
| j22 | school00 | en | How many m2 of tiling for all WCs? | 31 ~ | - 1467.0 | - 23.2 | - 19.0 | - 17.5 | - 14.5 | - 4.09 | sheets-rooms-area-sum | 7 | 0.5 |
| j23 | school00 | en | Floor area of the Multi-Purpose Hall? | 243 ~ | Y 245.66 | Y 245.91 | Y 244.77 | Y 244.88 | Y 245.7 | Y 246.08 | sheets-rooms-area | 2 | 0.5 |
| j24 | school00 | en | How many doors open into the Multi-Purpose Hall? | 8 | Y 9 | Y 8 | Y 8 | Y 8 | Y 8 | Y 8 | sheets-openings-room | 9 | 0.5 |
| t04 | school00 | en | What is the U-value of the external walls? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 2.6 |
| j26 | dormA1 | en | What's the total first floor area? | 28770 | Y 28770 | Y 28770 | Y 28770 | Y 28770 | Y 28770 | Y 28770 | sheets-zones-schedule | 15 | 13.9 |
| j27 | dormA1 | fi | Paljonko yhteistiloja (common space) ensimmäisessä kerroksessa on neli | 406.8 | Y 621.2 | Y 621.2 | Y 621.2 | Y 621.2 | Y 621 | Y 621.2 | sheets-zones-schedule | 2 | 6.1 |
| j29 | dormA4 | en | Area of the kitchen? | 151 | Y 151 | Y 151 | Y 151 SF | Y 151 | Y 151 | Y 151 | generic-read-haiku | 1 | 55.7 |
| j30 | dormA4 | de | Wie groß ist die Fläche aller Technikräume (ELEC, FIRE RISER/PUMP, PRI | 1050 | Y 1050 | Y 1050 | ~ 1122 | Y 1050 | Y 1050 | Y 1050 | generic-read-haiku | 4 | 53.7 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | Y Bedrooms: 4; Area of one bedroom: 189 | Y Bedrooms: 4; Area of one bedroom: 189 | Y Bedrooms: 4; Area of one bedroom: 189 SF | Y Bedrooms: 4; Area of one bedroom: 189 | Y Bedrooms: 4; Area of one bedroom: 189 | Y Bedrooms: 4; Area of one bedroom: 189 | parts:generic-ground-haiku+generic-read-haiku | 6 | 25.2 |
| j32 | dormA7 | en | Total bathroom floor area in one dorm module (for tiling)? | 204 | Y 204 | Y 204 | - 102 | Y 204 | Y 204 | Y 204 | generic-read-haiku | 4 | 6.1 |
| j34 | pipeM101F | en | What size is the pump discharge header? | 300 mm | Y 300mm | Y 300mm | Y 300mm | Y 300 | Y 300mm | Y 300mm | sheets-piping | 2 | 24.5 |
| j35 | pipeM101F | fi | Kuinka suuri paineiskusäiliö (surge tank) on? | 150 L | Y 150 LITER | Y 150 LITER | Y 150 LITER | Y 150 LITER | Y 150 LITER | Y 150 | sheets-piping | 1 | 0.8 |
| j37 | slabS100A | en | How many pump pads are on the pumphouse slab? | 5 | Y 5 | Y 5 | Y 5 | Y 5 | Y 5 | Y 5 | sheets-slab-pads | 0 | 37.1 |
| j38 | slabS102P | en | What is the reinforcement of the tank floor slab? | D19 @ 250 E.W. top and bottom; | Y D19 radial bars and D19 hoops at 200/250 | Y D19 RADIAL BARS; D19 @ 250 E.W TOP AND B | Y D19 RADIAL BARS; D19 HOOP @ 200; D19 @ 2 | Y D19 RADIAL BARS; D19 @ 250 E.W TOP AND B | Y D19 RADIAL BARS; D19 @ 250 E.W TOP AND B | Y D19 @ 250 E.W top and bottom | sheets-slab-bars | 0 | 30.8 |
| j39 | archA101F | en | How many doors does the filter building have? | 6 | - 9 | Y 6 | - 8 | Y 6 doors (+1 closet doors not counted) | Y 6 | - 8 | sheets-openings-cv | 7 | 12.4 |
| j40 | archA101F | en | What is the floor area of the generator room? | 26.49 | Y 26.49 | Y 26.49 | ~ 25.5 | ~ 25.5 | Y 26.5 | Y 26.5 | sheets-arch-rooms | 1 | 5.8 |
| j41 | schedA601 | en | How many doors are listed in the pumphouse door schedule, and how many | 8 doors, 6 of them 3'-0" wide | Y Doors: 8; 3'-0" wide: 6 | Y Doors: 8; 3'-0" wide: 6 | Y Doors: 8; 3'-0" wide: 6 | - Doors: 13; 3'-0" wide: 6 | - Doors: 16; 3'-0" wide: 6 | Y Doors: 8; 3'-0" wide: 6 | parts:generic-ground-haiku+generic-ground-haiku | 19 | 8.3 |
| t05 | schedA601 | en | What fire rating do the pumphouse doors have? | none given | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | generic-read-haiku | 1 | 5.1 |
| j43 | schoolL01 | en | How many group rooms are on level 01? | 5 | Y 5 | Y 5 | Y 5 | Y 5 | Y 5 | - 4 | sheets-arch-rooms-count | 5 | 9.1 |
| j44 | dormA7 | en | How many doors are in this dormitory module? | 8 | - 4 doors (+12 closet doors not counted) | - 4 doors (+12 closet doors not counted) | - 4 doors (+12 closet doors not counted) | - 4 doors (+12 closet doors not counted) | - 4 doors (+10 closet doors not counted) | - 5 doors (+5 closet doors not counted) | sheets-openings-yolo | 16 | 33.2 |

API cost of all asks $1.445. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
