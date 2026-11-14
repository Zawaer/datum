# Judge run `intent_a` (code 74e1c14)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 13/18 | 13/18 | 7.8 | 0.016 |
| png2500 | 14/18 | 15/18 | 6.7 | 0.019 |
| scanpdf | 12/18 | 12/18 | 8.6 | 0.018 |

**all forms: 39/54 strict**

By sheet: dormA1 0/3, dormA2 5/6, dormA4 3/3, dormA7 5/6, pipeM101A 9/9, pipeM101F 2/3, schedA601 2/3, school00 6/12, slab100F 5/6, slabS102P 2/3

By category: area-convert 0/3, area-sum 8/9, baseboard-hard 0/3, count-legend 2/3, notes-sum 3/3, piping-count 3/3, piping-count+size 3/3, piping-equipment 2/3, piping-size 3/3, rooms+area 3/3, rooms-count 3/6, schedule 2/3, slab-area 2/3, slab-rebar 2/3, trick 3/3

| id | sheet | lang | question | gold | lowres | png2500 | scanpdf | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|---|---|
| j03 | dormA2 | fi | Montako esteetöntä (ABA) asuntolahuonetta tässä kerroksessa on? | 2 | Y 2 | - 4 | Y 2 | generic-ground-haiku | 2 | 17.4 |
| j04 | dormA2 | de | Wie groß ist die gesamte Verkehrsfläche (Circulation) im 2. OG? | 4470 | Y 4470 | Y 4470 | Y 4470 | sheets-zones-schedule | 4 | 3.5 |
| j08 | slab100F | fi | Mikä on 300 mm laatan pinta-ala siinä osassa, jossa on D22-raudoitus? | 26.49 ~ | Y 26.49 | Y 26.66 | - (abstain) | sheets-slab-area | 2 | 15.5 |
| j10 | slab100F | sv | Hur långa är kabel- och rörkanalerna (trenches) sammanlagt? | 7850 | Y 7.85 | Y 7.85 | Y 7.85 | sheets-slab-trench | 6 | 1.1 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | Y Check valves: 5 count; Discharge header  | Y Check valves: 5 count; Discharge header  | Y Check valves: 5 count; Discharge header  | parts:sheets-piping+sheets-piping | 7 | 0.6 |
| j14 | pipeM101A | fi | Montako polttoainepumppua (FP) piirustuksessa on? | 5 | Y 5 | Y 5 | Y 5 | sheets-piping | 5 | 1.2 |
| j16 | pipeM101A | de | Welche Nennweite hat der Saugsammler (suction header)? | 16" | Y 16" | Y 16" | Y 16" | sheets-piping | 1 | 0.9 |
| j19 | school00 | fi | Montako luokkahuonetta tässä kerroksessa on? | 8 | - 6 | Y 8 | Y 8 | generic-ground-haiku | 6 | 16.2 |
| j20 | school00 | sv | Hur många grupprum finns det på plan 00? | 10 | - 0 | Y 10 | - 9 | generic-ground-haiku | 0 | 7.6 |
| j21 | school00 | fi | Paljonko jalkalistaa tarvitaan luokkahuoneisiin? | 265 ~ | - 65.3 | ~ 239.4 | - 110.8 | sheets-rooms-baseboard | 24 | 5.4 |
| t04 | school00 | en | What is the U-value of the external walls? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 1.7 |
| j27 | dormA1 | fi | Paljonko yhteistiloja (common space) ensimmäisessä kerroksessa on neli | 406.8 | - 1 | - (abstain; guess 0) | - 1 | generic-ground-haiku | 1 | 8.1 |
| j30 | dormA4 | de | Wie groß ist die Fläche aller Technikräume (ELEC, FIRE RISER/PUMP, PRI | 1050 | Y 1050 | Y 1050 | Y 1050 | generic-read-haiku | 4 | 14.5 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | Y Bedrooms: 4; Area of one bedroom: 189 SF | Y Bedrooms: 4; Area of one bedroom: 189 SF | Y Bedrooms: 4; Area of one bedroom: 189 SF | parts:generic-ground-haiku+sheets-text-read | 5 | 13.2 |
| j32 | dormA7 | en | Total bathroom floor area in one dorm module (for tiling)? | 204 | - 102 SF | Y 204 | Y 204 | sheets-text-sum | 2 | 4.0 |
| j35 | pipeM101F | fi | Kuinka suuri paineiskusäiliö (surge tank) on? | 150 L | Y 150 liters | Y 150 liters | - 250mm | sheets-piping | 2 | 4.8 |
| j38 | slabS102P | en | What is the reinforcement of the tank floor slab? | D19 @ 250 E.W. top and bottom; | Y D19 radial bars at 250 mm spacing (top a | - D22x3000 | Y D19 radial bars at 250 spacing (top and  | generic-read-haiku | 6 | 12.2 |
| j41 | schedA601 | en | How many doors are listed in the pumphouse door schedule, and how many | 8 doors, 6 of them 3'-0" wide | Y Doors: 8; 3'-0" wide: 6 | Y Doors: 8; 3'-0" wide: 6 | - Doors: 16; 3'-0" wide: 6 | parts:generic-ground-haiku+generic-ground-haiku | 14 | 12.1 |

API cost of all asks $0.053. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
