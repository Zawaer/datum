# Judge run `live_1552` (code 3fcc37e)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 7/13 | 7/13 | 19.8 | 0.019 |
| png2500 | 6/13 | 6/13 | 35.4 | 0.029 |
| pdf | 8/13 | 8/13 | 22.7 | 0.005 |

**all forms: 21/39 strict**

By sheet: archA101F 1/3, dormA1 3/3, dormA2 3/3, dormA4 3/3, dormA7 0/3, pipeM101A 0/3, pipeM101F 3/3, schedA601 0/3, school00 1/3, schoolL01 3/3, slab100F 3/3, slabS100A 0/3, slabS102P 1/3

By category: area-table 3/3, area-tag 3/3, count-easy 3/3, doors-count 1/3, piping-count+size 0/3, piping-size 3/3, rooms+area 0/3, rooms-count 4/6, schedule 0/3, slab-count 0/3, slab-rebar 4/6

| id | sheet | lang | question | gold | lowres | png2500 | pdf | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|---|---|
| j01 | dormA2 | en | How many dorm rooms are on the second floor? | 48 | Y 48 | Y 48 | Y 48 | sheets-zones-schedule | 1 | 1.8 |
| j07 | slab100F | en | What reinforcement is in the 150 mm slab? | D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | sheets-slab-note | 2 | 0.1 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | - 5 | - 5 | - 5 | sheets-piping | 5 | 3.9 |
| j19 | school00 | fi | Montako luokkahuonetta tässä kerroksessa on? | 8 | - (abstain; guess 6) | - (abstain; guess 8) | Y 8 | generic-ground-haiku | 6 | 14.5 |
| j26 | dormA1 | en | What's the total first floor area? | 28770 | Y 28770 | Y 28770 | Y 28770 | sheets-zones-schedule | 1 | 5.1 |
| j29 | dormA4 | en | Area of the kitchen? | 151 | Y 151 | Y 151 | Y 151 SF | generic-read-haiku | 1 | 17.9 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | - (abstain; guess 0) | - (abstain; guess 4) | - 4 | generic-ground-haiku | 0 | 8.5 |
| j34 | pipeM101F | en | What size is the pump discharge header? | 300 mm | Y 300mm | Y 300mm | Y 300mm | generic-read-haiku | 1 | 52.1 |
| j37 | slabS100A | en | How many pump pads are on the pumphouse slab? | 5 | - 7 | - 6 | - 24 | sheets-slab-pads | 7 | 0.1 |
| j38 | slabS102P | en | What is the reinforcement of the tank floor slab? | D19 @ 250 E.W. top and bottom; | - D22x3000 | - D22x3000 | Y D19 @ 250; D19 HOOP @ 200; D19 HOOP @ 25 | sheets-slab-bars | 0 | 0.1 |
| j39 | archA101F | en | How many doors does the filter building have? | 6 | Y 6 | - 7 | - (abstain) | generic-ground-haiku | 6 | 58.1 |
| j41 | schedA601 | en | How many doors are listed in the pumphouse door schedule, and how many | 8 doors, 6 of them 3'-0" wide | - 8 | - 8 | - 6 | generic-ground-haiku | 8 | 15.5 |
| j43 | schoolL01 | en | How many group rooms are on level 01? | 5 | Y 5 | Y 5 | Y 5 | generic-ground-haiku | 5 | 79.2 |

API cost of all asks $0.053. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
