# Judge run `live_1725` (code ecdcd44)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 6/13 | 6/13 | 12.9 | 0.015 |
| png2500 | 0/13 | 0/13 | 0.0 | 0.000 |
| pdf | 0/13 | 0/13 | 0.0 | 0.000 |

**all forms: 6/39 strict**

By sheet: archA101F 0/3, dormA1 1/3, dormA2 1/3, dormA4 1/3, dormA7 0/3, pipeM101A 0/3, pipeM101F 1/3, schedA601 0/3, school00 0/3, schoolL01 0/3, slab100F 1/3, slabS100A 0/3, slabS102P 1/3

By category: area-table 1/3, area-tag 1/3, count-easy 1/3, doors-count 0/3, piping-count+size 0/3, piping-size 1/3, rooms+area 0/3, rooms-count 0/6, schedule 0/3, slab-count 0/3, slab-rebar 2/6

| id | sheet | lang | question | gold | lowres | png2500 | pdf | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|---|---|
| j01 | dormA2 | en | How many dorm rooms are on the second floor? | 48 | Y 48 | - (abstain) | - (abstain) | sheets-zones-schedule | 1 | 11.4 |
| j07 | slab100F | en | What reinforcement is in the 150 mm slab? | D13 @ 300 | Y D13 @ 300 | - (abstain) | - (abstain) | sheets-slab-note | 2 | 26.2 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | - 5 | - (abstain) | - (abstain) | sheets-piping | 5 | 0.7 |
| j19 | school00 | fi | Montako luokkahuonetta tässä kerroksessa on? | 8 | - 5 | - (abstain) | - (abstain) | generic-ground-haiku | 5 | 12.3 |
| j26 | dormA1 | en | What's the total first floor area? | 28770 | Y 28770 | - (abstain) | - (abstain) | sheets-zones-schedule | 1 | 13.6 |
| j29 | dormA4 | en | Area of the kitchen? | 151 | Y 151 | - (abstain) | - (abstain) | generic-read-haiku | 1 | 13.7 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | - 4 | - (abstain) | - (abstain) | generic-ground-haiku | 4 | 9.9 |
| j34 | pipeM101F | en | What size is the pump discharge header? | 300 mm | Y 300mm | - (abstain) | - (abstain) | sheets-piping | 2 | 1.0 |
| j37 | slabS100A | en | How many pump pads are on the pumphouse slab? | 5 | - 6 | - (abstain) | - (abstain) | generic-ground-haiku | 6 | 28.4 |
| j38 | slabS102P | en | What is the reinforcement of the tank floor slab? | D19 @ 250 E.W. top and bottom; | Y Radial D19 bars at 6300, 5400, 3100, 490 | - (abstain) | - (abstain) | generic-read-haiku | 8 | 18.7 |
| j39 | archA101F | en | How many doors does the filter building have? | 6 | - 9 | - (abstain) | - (abstain) | sheets-openings-yolo | 9 | 2.8 |
| j41 | schedA601 | en | How many doors are listed in the pumphouse door schedule, and how many | 8 doors, 6 of them 3'-0" wide | - 8 | - (abstain) | - (abstain) | generic-ground-haiku | 8 | 6.3 |
| j43 | schoolL01 | en | How many group rooms are on level 01? | 5 | - (abstain) | - (abstain) | - (abstain) | error | 0 | 23.0 |

API cost of all asks $0.015. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
