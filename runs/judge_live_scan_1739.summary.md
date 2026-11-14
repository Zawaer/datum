# Judge run `live_scan_1739` (code 2a10600)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 8/13 | 8/13 | 12.3 | 0.015 |
| scanpdf | 8/13 | 8/13 | 10.7 | 0.055 |
| roughscan | 5/13 | 6/13 | 13.5 | 0.044 |

**all forms: 21/39 strict**

By sheet: archA101F 0/3, dormA1 2/3, dormA2 2/3, dormA4 3/3, dormA7 0/3, pipeM101A 0/3, pipeM101F 3/3, schedA601 0/3, school00 1/3, schoolL01 2/3, slab100F 3/3, slabS100A 2/3, slabS102P 3/3

By category: area-table 2/3, area-tag 3/3, count-easy 2/3, doors-count 0/3, piping-count+size 0/3, piping-size 3/3, rooms+area 0/3, rooms-count 3/6, schedule 0/3, slab-count 2/3, slab-rebar 6/6

| id | sheet | lang | question | gold | lowres | scanpdf | roughscan | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|---|---|
| j01 | dormA2 | en | How many dorm rooms are on the second floor? | 48 | Y 48 | Y 48 | - 144 | sheets-zones-schedule | 1 | 9.9 |
| j07 | slab100F | en | What reinforcement is in the 150 mm slab? | D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | sheets-slab-note | 2 | 23.0 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | - 5 | - 5 | - 0 | sheets-piping | 5 | 0.9 |
| j19 | school00 | fi | Montako luokkahuonetta tässä kerroksessa on? | 8 | - 4 | - (abstain; guess 0) | Y 8 | generic-ground-haiku | 4 | 11.4 |
| j26 | dormA1 | en | What's the total first floor area? | 28770 | Y 28770 | Y 28770 | ~ 28389 | sheets-zones-schedule | 1 | 10.8 |
| j29 | dormA4 | en | Area of the kitchen? | 151 | Y 151 | Y 151 | Y 151 | generic-read-haiku | 1 | 13.2 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | - (abstain; guess 0) | - (abstain; guess 0) | - 0 | generic-ground-haiku | 0 | 6.4 |
| j34 | pipeM101F | en | What size is the pump discharge header? | 300 mm | Y 300mm | Y 300mm | Y 300mm | sheets-piping | 2 | 1.2 |
| j37 | slabS100A | en | How many pump pads are on the pumphouse slab? | 5 | Y 5 | Y 5 | - 8 | generic-ground-haiku | 5 | 29.0 |
| j38 | slabS102P | en | What is the reinforcement of the tank floor slab? | D19 @ 250 E.W. top and bottom; | Y D19 bars at 250 mm spacing: radial bars  | Y Radial D19 bars (lengths 3100 to 8700 mm | Y D19 radial bars at 250 spacing (top and  | generic-read-haiku | 4 | 19.1 |
| j39 | archA101F | en | How many doors does the filter building have? | 6 | - 9 | - 7 | - 8 | sheets-openings-yolo | 9 | 3.0 |
| j41 | schedA601 | en | How many doors are listed in the pumphouse door schedule, and how many | 8 doors, 6 of them 3'-0" wide | - 8 | - 16 | - 8 | generic-ground-haiku | 8 | 3.2 |
| j43 | schoolL01 | en | How many group rooms are on level 01? | 5 | Y 5 | Y 5 | - 4 | generic-ground-haiku | 5 | 29.4 |

API cost of all asks $0.114. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
