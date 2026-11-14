# Judge run `1725` (code 2d397a3)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 25/40 | 26/40 | 7.2 | 0.064 |
| png2500 | 22/40 | 22/40 | 7.1 | 0.075 |
| pdf | 27/40 | 28/40 | 5.0 | 0.040 |
| hires | 21/40 | 22/40 | 8.4 | 0.082 |

**all forms: 95/160 strict**

By sheet: archA101F 1/8, dormA1 8/8, dormA2 20/24, dormA4 5/8, dormA7 1/8, pipeM101A 19/24, pipeM101F 8/8, schedA601 4/8, school00 11/28, schoolL01 4/4, slab100F 11/24, slabS100A 1/4, slabS102P 2/4

By category: area-convert 8/8, area-dims 1/4, area-multi-room-hard 0/4, area-room 3/4, area-sum 5/12, area-table 8/8, area-tag 2/4, baseboard-hard 0/4, count-easy 3/4, count-legend 4/4, doors-count 0/8, notes-sum 3/4, piping-count 8/8, piping-count+size 0/4, piping-equipment 4/4, piping-size 8/8, piping-tags-hard 3/4, rooms+area 0/4, rooms-count 8/12, schedule 0/4, slab-area 0/4, slab-area-by-type 4/4, slab-count 1/4, slab-rebar 6/8, slab-volume 0/4, trick 16/20

| id | sheet | lang | question | gold | lowres | png2500 | pdf | hires | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| j01 | dormA2 | en | How many dorm rooms are on the second floor? | 48 | Y 48 | - 144 | Y 48 | Y 48 | sheets-zones-schedule | 1 | 7.3 |
| j02 | dormA2 | en | Total net floor area of the east wing dorm rooms? | 6092 | Y 6092 | Y 6092 | Y 6092 | Y 6092 | sheets-zones-schedule | 3 | 4.3 |
| j03 | dormA2 | fi | Montako esteetöntä (ABA) asuntolahuonetta tässä kerroksessa on? | 2 | Y 2 | Y 2 | Y 2 | Y 2 | generic-ground-haiku | 2 | 11.1 |
| j04 | dormA2 | de | Wie groß ist die gesamte Verkehrsfläche (Circulation) im 2. OG? | 4470 | - 4.47 | - 2 | Y 4470 | - 4.47 | generic-read-haiku | 4 | 7.1 |
| j05 | dormA2 | en | What's the gross area of the second floor in square metres? | 2467.7 | Y 2467.7 | Y 2467.7 | Y 2467.7 | Y 2467.7 | sheets-zones-schedule | 18 | 4.8 |
| t01 | dormA2 | en | What is the ceiling height in the dorm rooms? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 3.8 |
| j07 | slab100F | en | What reinforcement is in the 150 mm slab? | D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | sheets-slab-note | 2 | 24.9 |
| j08 | slab100F | fi | Mikä on 300 mm laatan pinta-ala siinä osassa, jossa on D22-raudoitus? | 26.49 ~ | - (abstain) | - (abstain) | - 0.954 m² (795 × 1200 mm) | - (abstain) | sheets-none | 0 | 5.3 |
| j09 | slab100F | en | Slab area by type (thickness and bars)? | 300 D16 ~214.5 m2; 150 D13 ~61 ~ | Y 300 mm w/ D22 @ 300: 26.5 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.7 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.7 m²; 150 mm w/  | Y 300 mm w/ D22 @ 300: 26.5 m²; 150 mm w/  | sheets-slab-area-by-type | 6 | 0.3 |
| j10 | slab100F | sv | Hur långa är kabel- och rörkanalerna (trenches) sammanlagt? | 7850 | ~ Sammanlagt cirka 7 650 mm (4275 + 1625 + | Y 7850 (4275 + 1825 + 1750) | Y 7850 | Y 7850 mm (ca 7,85 m): motorcentralens kan | generic-read-haiku | 1 | 5.3 |
| j11 | slab100F | en | Concrete volume of the 150 mm slab-on-grade? | 9.25 ~ | - 61.81 | - 61.69 | - 61.69 | - 61.69 | sheets-slab-area | 2 | 0.5 |
| t02 | slab100F | en | What does the concrete for this slab cost per cubic metre? | not shown | - 304.68 | - 305.43 | - 305.58 | - 305.37 | sheets-slab-area | 6 | 0.5 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | - 5 | - 5 | - 5 | - 5 | sheets-piping | 5 | 1.0 |
| j14 | pipeM101A | fi | Montako polttoainepumppua (FP) piirustuksessa on? | 5 | Y 5 | Y 5 | Y 5 | Y 5 | generic-ground-haiku | 5 | 8.8 |
| j15 | pipeM101A | en | How many filter separators are there in total (FSI + FSR)? | 7 | Y 7 | Y 7 | Y 7 | Y 7 | sheets-piping | 7 | 0.5 |
| j16 | pipeM101A | de | Welche Nennweite hat der Saugsammler (suction header)? | 16" | Y 16" (Nennweite 16 Zoll) | Y 16" (16 Zoll) | Y 16" | Y 16" | sheets-piping | 1 | 6.3 |
| j17 | pipeM101A | en | How many distinct pipe support tags (PS-x) are used on this plan? | 23 | Y 23 | Y 23 | Y 23 | - 22 | sheets-piping | 40 | 0.8 |
| t03 | pipeM101A | en | How many fire sprinkler heads are shown on this piping plan? | none | Y 0 | Y 0 | Y 0 | Y 0 | generic-ground-haiku | 0 | 4.8 |
| j19 | school00 | fi | Montako luokkahuonetta tässä kerroksessa on? | 8 | - 2 | - 0 | Y 8 | - (abstain; guess 0) | generic-ground-haiku | 0 | 10.1 |
| j20 | school00 | sv | Hur många grupprum finns det på plan 00? | 10 | - 0 | Y 10 | Y 10 | Y 10 | generic-ground-haiku | 10 | 11.1 |
| j21 | school00 | fi | Paljonko jalkalistaa tarvitaan luokkahuoneisiin? | 265 ~ | - (abstain) | - (abstain) | - (abstain) | - (abstain) | sheets-rooms-ask | 0 | 45.3 |
| j22 | school00 | en | How many m2 of tiling for all WCs? | 31 ~ | - (abstain; guess 1) | - (abstain; guess 6) | - Total 1500 m² net over 101 rooms. Second | - Total 1494 m² net over 101 rooms. Second | sheets-rooms-area-list | 102 | 2.8 |
| j23 | school00 | en | Floor area of the Multi-Purpose Hall? | 243 ~ | Y 246.9 | - 35.4 | Y 244.77 | Y 244.88 | sheets-rooms-area | 2 | 0.5 |
| j24 | school00 | en | How many doors open into the Multi-Purpose Hall? | 8 | - 119 | - 128 | - 120 | - 122 | sheets-openings-cv | 122 | 0.5 |
| t04 | school00 | en | What is the U-value of the external walls? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 3.1 |
| j26 | dormA1 | en | What's the total first floor area? | 28770 | Y 28770 | Y 28770 | Y 28770 | Y 28770 | sheets-zones-schedule | 15 | 6.8 |
| j27 | dormA1 | fi | Paljonko yhteistiloja (common space) ensimmäisessä kerroksessa on neli | 406.8 | Y 6,687 SF (square feet, not m²) total com | Y 6 687 SF (neliöjalkaa, ei neliömetriä) | Y 6 687 SF (neliöjalkaa, ei neliömetriä).  | Y 6 687 SF (neliöjalkaa, ei neliömetriä).  | generic-read-haiku | 1 | 6.6 |
| j29 | dormA4 | en | Area of the kitchen? | 151 | Y 151 | - 126 SF | Y 151 SF | - (abstain) | sheets-arch-timeout | 0 | 54.1 |
| j30 | dormA4 | de | Wie groß ist die Fläche aller Technikräume (ELEC, FIRE RISER/PUMP, PRI | 1050 | Y 1050 | Y 1050 | Y 1048 | - (abstain) | sheets-none | 0 | 4.8 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | - 0 | - (abstain; guess 4) | - 4 | - 0 | generic-ground-haiku | 0 | 5.1 |
| j32 | dormA7 | en | Total bathroom floor area in one dorm module (for tiling)? | 204 | - 102 SF | Y 204 | - 51 | - (abstain) | sheets-arch-noscale | 0 | 21.2 |
| j34 | pipeM101F | en | What size is the pump discharge header? | 300 mm | Y 300mm | Y 300mm | Y 300mm | Y 300 | sheets-piping | 2 | 1.0 |
| j35 | pipeM101F | fi | Kuinka suuri paineiskusäiliö (surge tank) on? | 150 L | Y 150 litraa (150 L) | Y 150 litraa (150 LITER SURGE TANK) | Y 150 litraa | Y 150 litraa | sheets-piping | 1 | 4.6 |
| j37 | slabS100A | en | How many pump pads are on the pumphouse slab? | 5 | Y 5 | - 6 | - 24 | - 26 | sheets-slab-pads | 26 | 22.9 |
| j38 | slabS102P | en | What is the reinforcement of the tank floor slab? | D19 @ 250 E.W. top and bottom; | Y D19 bars at 250 spacing, top and bottom  | - D22x3000 | Y D19 HOOP @ 200; D19 @ 250 E.W TOP AND BO | - D22x3000 | sheets-slab-bars | 0 | 16.4 |
| j39 | archA101F | en | How many doors does the filter building have? | 6 | - 9 | - 9 | - 8 | - 7 | sheets-openings-cv | 7 | 1.3 |
| j40 | archA101F | en | What is the floor area of the generator room? | 26.49 | Y 26.5 | - (abstain) | ~ 25.5 | ~ 25.5 | sheets-arch-rooms | 1 | 6.3 |
| j41 | schedA601 | en | How many doors are listed in the pumphouse door schedule, and how many | 8 doors, 6 of them 3'-0" wide | - 0 | - 0 | - 6 | - 0 | generic-ground-haiku | 0 | 4.3 |
| t05 | schedA601 | en | What fire rating do the pumphouse doors have? | none given | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | generic-read-haiku | 1 | 6.1 |
| j43 | schoolL01 | en | How many group rooms are on level 01? | 5 | Y 5 | Y 5 | Y 5 | Y 5 | sheets-arch-rooms-count | 5 | 5.3 |

API cost of all asks $0.263. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
