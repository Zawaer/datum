# Judge run `or_j5` (code 73fcce1)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 34/41 | 34/41 | 7.8 | 0.074 |
| png2500 | 33/41 | 34/41 | 7.9 | 0.083 |
| pdf | 34/41 | 36/41 | 8.7 | 0.027 |
| scanpdf | 31/41 | 31/41 | 10.7 | 0.111 |
| roughscan | 27/41 | 27/41 | 32.1 | 0.103 |

**all forms: 159/205 strict**

By sheet: archA101F 7/10, dormA1 10/10, dormA2 26/30, dormA4 9/10, dormA7 7/15, pipeM101A 29/30, pipeM101F 9/10, schedA601 9/10, school00 18/35, schoolL01 4/5, slab100F 25/30, slabS100A 1/5, slabS102P 5/5

By category: area-convert 9/10, area-dims 3/5, area-multi-room-hard 0/5, area-room 4/5, area-sum 11/15, area-table 10/10, area-tag 5/5, baseboard-hard 0/5, count-easy 5/5, count-legend 2/5, doors-count 12/15, notes-sum 5/5, piping-count 9/10, piping-count+size 5/5, piping-equipment 4/5, piping-size 10/10, piping-tags-hard 5/5, rooms+area 1/5, rooms-count 9/15, schedule 4/5, slab-area 3/5, slab-area-by-type 3/5, slab-count 1/5, slab-rebar 10/10, slab-volume 4/5, trick 25/25

| id | sheet | lang | question | gold | lowres | png2500 | pdf | scanpdf | roughscan | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| j01 | dormA2 | en | How many dorm rooms are on the second floor? | 48 | Y 48 | Y 48 | Y 48 | Y 48 | Y 48 | sheets-zones-schedule | 1 | 6.6 |
| j02 | dormA2 | en | Total net floor area of the east wing dorm rooms? | 6092 | Y 6092 | Y 6092 | Y 6092 | Y 6092 | Y 6092 | sheets-zones-schedule | 3 | 6.6 |
| j03 | dormA2 | fi | Montako esteetöntä (ABA) asuntolahuonetta tässä kerroksessa on? | 2 | Y 2 | - 4 | Y 2 | - 48 | - 0 | generic-ground-haiku | 2 | 20.9 |
| j04 | dormA2 | de | Wie groß ist die gesamte Verkehrsfläche (Circulation) im 2. OG? | 4470 | Y 4470 | Y 4470 | Y 4470 | Y 4470 | Y 4470 | sheets-zones-schedule | 4 | 3.3 |
| j05 | dormA2 | en | What's the gross area of the second floor in square metres? | 2467.7 | - 26,562 SF | Y 2467.7 | Y 2467.7 | Y 2467.7 | Y 2467.7 | sheets-text-read | 1 | 8.9 |
| t01 | dormA2 | en | What is the ceiling height in the dorm rooms? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 2.4 |
| j07 | slab100F | en | What reinforcement is in the 150 mm slab? | D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | sheets-slab-note | 2 | 16.4 |
| j08 | slab100F | fi | Mikä on 300 mm laatan pinta-ala siinä osassa, jossa on D22-raudoitus? | 26.49 ~ | Y 26.49 | Y 26.66 | Y 26.7 | - (abstain) | - (abstain) | sheets-slab-area | 2 | 13.2 |
| j09 | slab100F | en | Slab area by type (thickness and bars)? | 300 D16 ~214.5 m2; 150 D13 ~61 ~ | Y 300 mm w/ D22 @ 300: 26.5 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.7 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.7 m²; 150 mm w/  | - 300 mm w/ D16 @ 300: 256.7 m²; 150 mm w/ | - 300 mm w/ D16 @ 300: 92.3 m²; 150 mm w/  | sheets-slab-area-by-type | 6 | 7.8 |
| j10 | slab100F | sv | Hur långa är kabel- och rörkanalerna (trenches) sammanlagt? | 7850 | Y 7.85 | Y 7.85 | Y 7.85 | Y 7.85 | Y 7.85 | sheets-slab-trench | 6 | 0.1 |
| j11 | slab100F | en | Concrete volume of the 150 mm slab-on-grade? | 9.25 ~ | Y 9.27 | Y 9.25 | Y 9.25 | Y 9.23 | - 5.7 | sheets-slab-volume | 2 | 0.1 |
| t02 | slab100F | en | What does the concrete for this slab cost per cubic metre? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 2.3 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | parts:sheets-piping+sheets-piping | 7 | 6.3 |
| j14 | pipeM101A | fi | Montako polttoainepumppua (FP) piirustuksessa on? | 5 | Y 5 | Y 5 | Y 5 | Y 5 | - 4 | sheets-piping | 5 | 5.6 |
| j15 | pipeM101A | en | How many filter separators are there in total (FSI + FSR)? | 7 | Y 7 | Y 7 | Y 7 | Y 7 | Y 7 | sheets-piping | 7 | 9.2 |
| j16 | pipeM101A | de | Welche Nennweite hat der Saugsammler (suction header)? | 16" | Y 16" | Y 16" | Y 16" | Y 16" | Y 16" | sheets-piping | 1 | 0.2 |
| j17 | pipeM101A | en | How many distinct pipe support tags (PS-x) are used on this plan? | 23 | Y 23 | Y 23 | Y 23 | Y 23 | Y 23 | sheets-piping | 40 | 0.1 |
| t03 | pipeM101A | en | How many fire sprinkler heads are shown on this piping plan? | none | Y 0 | Y 0 | Y 0 | Y 0 | Y 0 | generic-ground-haiku | 0 | 6.7 |
| j19 | school00 | fi | Montako luokkahuonetta tässä kerroksessa on? | 8 | - 7 | - 7 | Y 8 | Y 8 | Y 8 | generic-ground-haiku | 7 | 22.6 |
| j20 | school00 | sv | Hur många grupprum finns det på plan 00? | 10 | - (abstain; guess 0) | Y 10 | Y 10 | - 9 | - (abstain; guess 9) | generic-ground-haiku | 0 | 16.8 |
| j21 | school00 | fi | Paljonko jalkalistaa tarvitaan luokkahuoneisiin? | 265 ~ | - 78.7 | ~ 239.4 | ~ 225.7 | - 201.9 | - (abstain) | sheets-rooms-baseboard | 16 | 0.1 |
| j22 | school00 | en | How many m2 of tiling for all WCs? | 31 ~ | - 2.64 | - 23.2 | - 19.0 | - 14.5 | - (abstain) | sheets-rooms-area | 3 | 0.1 |
| j23 | school00 | en | Floor area of the Multi-Purpose Hall? | 243 ~ | Y 245.66 | Y 245.91 | Y 244.77 | Y 245.7 | - (abstain) | sheets-rooms-area | 3 | 0.1 |
| j24 | school00 | en | How many doors open into the Multi-Purpose Hall? | 8 | Y 9 | Y 8 | Y 8 | Y 8 | - 3 | sheets-openings-room | 10 | 0.0 |
| t04 | school00 | en | What is the U-value of the external walls? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 2.4 |
| j26 | dormA1 | en | What's the total first floor area? | 28770 | Y 28770 | Y 28770 | Y 28770 | Y 28770 | Y 28770 | sheets-zones-schedule | 1 | 7.0 |
| j27 | dormA1 | fi | Paljonko yhteistiloja (common space) ensimmäisessä kerroksessa on neli | 406.8 | Y 621.2 | Y 621.2 | Y 621.2 | Y 621.2 | Y 621.2 | sheets-zones-schedule | 1 | 4.0 |
| j29 | dormA4 | en | Area of the kitchen? | 151 | Y 151 | Y 151 | Y 151 SF | Y 151 | Y 151 | generic-read-haiku | 1 | 11.7 |
| j30 | dormA4 | de | Wie groß ist die Fläche aller Technikräume (ELEC, FIRE RISER/PUMP, PRI | 1050 | Y 1050 | - 824 SF | Y 1,050 SF | Y 1050 | Y 1050 | generic-read-haiku | 4 | 13.2 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | - Bedrooms: not sure; Area of one bedroom: | - Bedrooms: not sure; Area of one bedroom: | - Bedrooms: not sure; Area of one bedroom: | Y Bedrooms: 4; Area of one bedroom: 189 SF | - (abstain) | parts:generic-ground-haiku+sheets-text-read | 5 | 19.8 |
| j32 | dormA7 | en | Total bathroom floor area in one dorm module (for tiling)? | 204 | - 102 SF | Y 204 | - 102 | - 102 SF | Y 204 | sheets-text-sum | 2 | 5.4 |
| j34 | pipeM101F | en | What size is the pump discharge header? | 300 mm | Y 300mm | Y 300mm | Y 300mm | Y 300mm | Y 300mm | sheets-piping | 2 | 0.5 |
| j35 | pipeM101F | fi | Kuinka suuri paineiskusäiliö (surge tank) on? | 150 L | Y 150 liters | Y 150 liters | Y 150 liters | - 250mm | Y 150 liters | sheets-piping | 2 | 2.5 |
| j37 | slabS100A | en | How many pump pads are on the pumphouse slab? | 5 | Y 5 | - 7 | - 1 | - 8 | - 6 | generic-ground-haiku | 5 | 28.7 |
| j38 | slabS102P | en | What is the reinforcement of the tank floor slab? | D19 @ 250 E.W. top and bottom; | Y D19 bars @ 250 top and bottom (radial an | Y D19 @ 250 E-W top and bottom, with D19 r | Y D19 HOOP @ 200; D19 @ 250 E.W TOP AND BO | Y D19 @ 250 E/W top and bottom, plus addit | Y D19 radial bars (3100 to 9300 long) with | generic-read-haiku | 3 | 18.3 |
| j39 | archA101F | en | How many doors does the filter building have? | 6 | Y 6 | Y 6 | Y 6 | - 5 | Y 6 | sheets-openings-yolo | 9 | 1.6 |
| j40 | archA101F | en | What is the floor area of the generator room? | 26.49 | Y 26.49 | - (abstain) | ~ 25.5 | Y 26.49 | Y 26.5 | generic-read-haiku | 3 | 12.1 |
| j41 | schedA601 | en | How many doors are listed in the pumphouse door schedule, and how many | 8 doors, 6 of them 3'-0" wide | Y Doors: 8; 3'-0" wide: 6 | Y Doors: 8; 3'-0" wide: 6 | - Doors: 6; 3'-0" wide: 6 | Y Doors: 8; 3'-0" wide: 6 | Y Doors: 8; 3'-0" wide: 6 | parts:generic-ground-haiku+generic-ground-haiku | 14 | 18.2 |
| t05 | schedA601 | en | What fire rating do the pumphouse doors have? | none given | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | generic-read-haiku | 1 | 4.9 |
| j43 | schoolL01 | en | How many group rooms are on level 01? | 5 | Y 5 | Y 5 | Y 5 | Y 5 | - 4 | generic-ground-haiku | 5 | 14.1 |
| j44 | dormA7 | en | How many doors are in this dormitory module? | 8 | Y 8 doors (+8 closet doors not counted) | Y 8 doors (+8 closet doors not counted) | Y 8 doors (+8 closet doors not counted) | Y 8 doors (+6 closet doors not counted) | - (abstain; guess 19) | sheets-openings-yolo | 16 | 0.2 |

API cost of all asks $0.399. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
