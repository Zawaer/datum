# Judge run `mid_roughscan` (code 7dc4192)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| roughscan | 20/29 | 20/29 | 17.9 | 0.023 |

**all forms: 20/29 strict**

By sheet: dormA1 2/2, dormA2 5/6, dormA4 2/2, dormA7 1/3, pipeM101A 4/6, pipeM101F 2/2, slab100F 3/6, slabS100A 0/1, slabS102P 1/1

By category: area-convert 2/2, area-sum 3/3, area-table 2/2, area-tag 1/1, count-easy 1/1, count-legend 0/1, doors-count 0/1, notes-sum 1/1, piping-count 2/2, piping-count+size 0/1, piping-equipment 1/1, piping-size 2/2, piping-tags-hard 0/1, rooms+area 0/1, slab-area 0/1, slab-area-by-type 0/1, slab-count 0/1, slab-rebar 2/2, slab-volume 0/1, trick 3/3

| id | sheet | lang | question | gold | roughscan | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|
| j01 | dormA2 | en | How many dorm rooms are on the second floor? | 48 | Y 48 | sheets-zones-schedule | 1 | 6.8 |
| j02 | dormA2 | en | Total net floor area of the east wing dorm rooms? | 6092 | Y 6092 | sheets-zones-schedule | 1 | 6.8 |
| j03 | dormA2 | fi | Montako esteetöntä (ABA) asuntolahuonetta tässä kerroksessa on? | 2 | - (abstain; guess 2) | generic-ground-haiku | 2 | 59.2 |
| j04 | dormA2 | de | Wie groß ist die gesamte Verkehrsfläche (Circulation) im 2. OG? | 4470 | Y 4470 | sheets-zones-schedule | 4 | 2.2 |
| j05 | dormA2 | en | What's the gross area of the second floor in square metres? | 2467.7 | Y 2467.7 | sheets-zones-schedule | 55 | 2.2 |
| t01 | dormA2 | en | What is the ceiling height in the dorm rooms? | not shown | Y (abstain) | sheets-none | 0 | 3.8 |
| j07 | slab100F | en | What reinforcement is in the 150 mm slab? | D13 @ 300 | Y D13 @ 300 | sheets-slab-note | 2 | 23.1 |
| j08 | slab100F | fi | Mikä on 300 mm laatan pinta-ala siinä osassa, jossa on D22-raudoitus? | 26.49 ~ | - (abstain) | sheets-none | 0 | 23.1 |
| j09 | slab100F | en | Slab area by type (thickness and bars)? | 300 D16 ~214.5 m2; 150 D13 ~61 ~ | - 300 mm w/ D16 @ 300: 92.3 m²; 150 mm w/  | sheets-slab-area-by-type | 6 | 0.1 |
| j10 | slab100F | sv | Hur långa är kabel- och rörkanalerna (trenches) sammanlagt? | 7850 | Y 7.85 | sheets-slab-trench | 5 | 0.1 |
| j11 | slab100F | en | Concrete volume of the 150 mm slab-on-grade? | 9.25 ~ | - 5.7 | sheets-slab-volume | 2 | 0.1 |
| t02 | slab100F | en | What does the concrete for this slab cost per cubic metre? | not shown | Y (abstain) | sheets-none | 0 | 3.6 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | - Check valves: 4; Discharge header size:  | parts:sheets-piping+sheets-none | 4 | 9.2 |
| j14 | pipeM101A | fi | Montako polttoainepumppua (FP) piirustuksessa on? | 5 | Y 5 | sheets-piping | 5 | 4.0 |
| j15 | pipeM101A | en | How many filter separators are there in total (FSI + FSR)? | 7 | Y 7 | sheets-piping | 7 | 9.0 |
| j16 | pipeM101A | de | Welche Nennweite hat der Saugsammler (suction header)? | 16" | Y 16" | sheets-piping | 1 | 0.2 |
| j17 | pipeM101A | en | How many distinct pipe support tags (PS-x) are used on this plan? | 23 | - 21 | sheets-piping | 37 | 0.1 |
| t03 | pipeM101A | en | How many fire sprinkler heads are shown on this piping plan? | none | Y 0 | generic-ground-haiku | 0 | 4.8 |
| j26 | dormA1 | en | What's the total first floor area? | 28770 | Y 28770 | sheets-zones-schedule | 1 | 6.0 |
| j27 | dormA1 | fi | Paljonko yhteistiloja (common space) ensimmäisessä kerroksessa on neli | 406.8 | Y 621.2 | sheets-zones-schedule | 1 | 4.8 |
| j29 | dormA4 | en | Area of the kitchen? | 151 | Y 151 | generic-read-haiku | 1 | 54.8 |
| j30 | dormA4 | de | Wie groß ist die Fläche aller Technikräume (ELEC, FIRE RISER/PUMP, PRI | 1050 | Y 1050 | generic-read-haiku | 4 | 54.9 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | - (abstain) | timeout | 0 | 100.0 |
| j32 | dormA7 | en | Total bathroom floor area in one dorm module (for tiling)? | 204 | Y 204 | generic-read-haiku | 4 | 55.6 |
| j34 | pipeM101F | en | What size is the pump discharge header? | 300 mm | Y 300mm | sheets-piping | 2 | 0.4 |
| j35 | pipeM101F | fi | Kuinka suuri paineiskusäiliö (surge tank) on? | 150 L | Y 150 liters | sheets-piping | 2 | 2.1 |
| j37 | slabS100A | en | How many pump pads are on the pumphouse slab? | 5 | - 7 | sheets-slab-pads | 7 | 9.3 |
| j38 | slabS102P | en | What is the reinforcement of the tank floor slab? | D19 @ 250 E.W. top and bottom; | Y D19 @ 250 E.W top and bottom | generic-read-haiku | 3 | 16.5 |
| j44 | dormA7 | en | How many doors are in this dormitory module? | 8 | - (abstain; guess 15) | generic-ground-haiku | 15 | 57.7 |

API cost of all asks $0.023. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
