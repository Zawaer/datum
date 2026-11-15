# Judge run `reh2_lowres` (code 38a9a51)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 34/41 | 34/41 | 4.9 | 0.085 |

**all forms: 34/41 strict**

By sheet: archA101F 2/2, dormA1 2/2, dormA2 6/6, dormA4 2/2, dormA7 2/3, pipeM101A 6/6, pipeM101F 1/2, schedA601 1/2, school00 3/7, schoolL01 1/1, slab100F 6/6, slabS100A 1/1, slabS102P 1/1

By category: area-convert 2/2, area-dims 1/1, area-multi-room-hard 0/1, area-room 1/1, area-sum 3/3, area-table 2/2, area-tag 1/1, baseboard-hard 0/1, count-easy 1/1, count-legend 1/1, doors-count 2/3, notes-sum 1/1, piping-count 2/2, piping-count+size 1/1, piping-equipment 0/1, piping-size 2/2, piping-tags-hard 1/1, rooms+area 1/1, rooms-count 1/3, schedule 0/1, slab-area 1/1, slab-area-by-type 1/1, slab-count 1/1, slab-rebar 2/2, slab-volume 1/1, trick 5/5

| id | sheet | lang | question | gold | lowres | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|
| j01 | dormA2 | en | How many dorm rooms are on the second floor? | 48 | Y 48 | sheets-zones-schedule | 1 | 4.7 |
| j02 | dormA2 | en | Total net floor area of the east wing dorm rooms? | 6092 | Y 6092 | sheets-zones-schedule | 3 | 4.7 |
| j03 | dormA2 | fi | Montako esteetöntä (ABA) asuntolahuonetta tässä kerroksessa on? | 2 | Y 2 | generic-ground-haiku | 2 | 14.9 |
| j04 | dormA2 | de | Wie groß ist die gesamte Verkehrsfläche (Circulation) im 2. OG? | 4470 | Y 4470 | sheets-zones-schedule | 4 | 1.6 |
| j05 | dormA2 | en | What's the gross area of the second floor in square metres? | 2467.7 | Y 2467.7 | sheets-zones-schedule | 17 | 2.5 |
| t01 | dormA2 | en | What is the ceiling height in the dorm rooms? | not shown | Y (abstain) | sheets-none | 0 | 2.1 |
| j07 | slab100F | en | What reinforcement is in the 150 mm slab? | D13 @ 300 | Y D13 @ 300 | sheets-slab-note | 2 | 1.8 |
| j08 | slab100F | fi | Mikä on 300 mm laatan pinta-ala siinä osassa, jossa on D22-raudoitus? | 26.49 ~ | Y 26.49 | sheets-slab-area | 2 | 1.8 |
| j09 | slab100F | en | Slab area by type (thickness and bars)? | 300 D16 ~214.5 m2; 150 D13 ~61 ~ | Y 300 mm w/ D22 @ 300: 26.5 m²; 150 mm w/  | sheets-slab-area-by-type | 6 | 0.1 |
| j10 | slab100F | sv | Hur långa är kabel- och rörkanalerna (trenches) sammanlagt? | 7850 | Y 7.85 | sheets-slab-trench | 6 | 0.1 |
| j11 | slab100F | en | Concrete volume of the 150 mm slab-on-grade? | 9.25 ~ | Y 9.27 | sheets-slab-volume | 2 | 0.1 |
| t02 | slab100F | en | What does the concrete for this slab cost per cubic metre? | not shown | Y (abstain) | sheets-none | 0 | 2.4 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | Y Check valves: 5; Discharge header size:  | parts:sheets-piping+sheets-piping | 7 | 2.3 |
| j14 | pipeM101A | fi | Montako polttoainepumppua (FP) piirustuksessa on? | 5 | Y 5 | sheets-piping | 5 | 2.3 |
| j15 | pipeM101A | en | How many filter separators are there in total (FSI + FSR)? | 7 | Y 7 | sheets-piping | 7 | 4.2 |
| j16 | pipeM101A | de | Welche Nennweite hat der Saugsammler (suction header)? | 16" | Y 16" | sheets-piping | 1 | 0.3 |
| j17 | pipeM101A | en | How many distinct pipe support tags (PS-x) are used on this plan? | 23 | Y 23 | sheets-piping | 42 | 5.4 |
| t03 | pipeM101A | en | How many fire sprinkler heads are shown on this piping plan? | none | Y 0 | generic-ground-haiku | 0 | 6.2 |
| j19 | school00 | fi | Montako luokkahuonetta tässä kerroksessa on? | 8 | - 6 | sheets-rooms-count | 6 | 1.0 |
| j20 | school00 | sv | Hur många grupprum finns det på plan 00? | 10 | - (abstain; guess 5) | generic-ground-haiku | 5 | 12.2 |
| j21 | school00 | fi | Paljonko jalkalistaa tarvitaan luokkahuoneisiin? | 265 ~ | - 156.6 | sheets-rooms-baseboard | 30 | 4.0 |
| j22 | school00 | en | How many m2 of tiling for all WCs? | 31 ~ | - 17.0 | sheets-rooms-area-sum | 4 | 0.2 |
| j23 | school00 | en | Floor area of the Multi-Purpose Hall? | 243 ~ | Y 245.66 | sheets-rooms-area | 3 | 2.8 |
| j24 | school00 | en | How many doors open into the Multi-Purpose Hall? | 8 | Y 9 | sheets-openings-room | 10 | 3.2 |
| t04 | school00 | en | What is the U-value of the external walls? | not shown | Y (abstain) | sheets-none | 0 | 2.8 |
| j26 | dormA1 | en | What's the total first floor area? | 28770 | Y 28770 | sheets-zones-schedule | 1 | 5.4 |
| j27 | dormA1 | fi | Paljonko yhteistiloja (common space) ensimmäisessä kerroksessa on neli | 406.8 | Y 621 | generic-read-haiku | 1 | 8.3 |
| j29 | dormA4 | en | Area of the kitchen? | 151 | Y 151 | generic-read-haiku | 1 | 8.2 |
| j30 | dormA4 | de | Wie groß ist die Fläche aller Technikräume (ELEC, FIRE RISER/PUMP, PRI | 1050 | Y 1050 | generic-read-haiku | 4 | 5.9 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | Y Bedrooms: 4; Area of one bedroom: 189 | parts:generic-ground-haiku+generic-read-haiku | 5 | 18.3 |
| j32 | dormA7 | en | Total bathroom floor area in one dorm module (for tiling)? | 204 | Y 204 | generic-read-haiku | 4 | 8.3 |
| j34 | pipeM101F | en | What size is the pump discharge header? | 300 mm | Y 300mm | sheets-piping | 2 | 0.3 |
| j35 | pipeM101F | fi | Kuinka suuri paineiskusäiliö (surge tank) on? | 150 L | - 250mm | sheets-piping | 1 | 0.3 |
| j37 | slabS100A | en | How many pump pads are on the pumphouse slab? | 5 | Y 5 | generic-ground-haiku | 5 | 4.5 |
| j38 | slabS102P | en | What is the reinforcement of the tank floor slab? | D19 @ 250 E.W. top and bottom; | Y D19 bars at 250 spacing: radial and hoop | generic-read-haiku | 6 | 5.0 |
| j39 | archA101F | en | How many doors does the filter building have? | 6 | Y 6 | sheets-openings-yolo | 9 | 8.4 |
| j40 | archA101F | en | What is the floor area of the generator room? | 26.49 | Y 26.49 | generic-read-haiku | 3 | 7.6 |
| j41 | schedA601 | en | How many doors are listed in the pumphouse door schedule, and how many | 8 doors, 6 of them 3'-0" wide | - Doors: 13; 3'-0" wide: 0 | parts:generic-ground-haiku+generic-ground-haiku | 13 | 10.9 |
| t05 | schedA601 | en | What fire rating do the pumphouse doors have? | none given | Y (abstain) | generic-read-haiku | 1 | 4.1 |
| j43 | schoolL01 | en | How many group rooms are on level 01? | 5 | Y 5 | generic-ground-haiku | 5 | 9.2 |
| j44 | dormA7 | en | How many doors are in this dormitory module? | 8 | - 4 doors (+12 closet doors not counted) | sheets-openings-yolo | 16 | 10.6 |

API cost of all asks $0.085. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
