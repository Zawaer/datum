# Judge run `live_1655` (code 55db5e2)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 10/13 | 10/13 | 13.8 | 0.035 |
| png2500 | 8/13 | 8/13 | 14.4 | 0.084 |
| pdf | 8/13 | 8/13 | 9.9 | 0.006 |

**all forms: 26/39 strict**

By sheet: archA101F 2/3, dormA1 3/3, dormA2 3/3, dormA4 3/3, dormA7 0/3, pipeM101A 0/3, pipeM101F 3/3, schedA601 0/3, school00 3/3, schoolL01 3/3, slab100F 3/3, slabS100A 1/3, slabS102P 2/3

By category: area-table 3/3, area-tag 3/3, count-easy 3/3, doors-count 2/3, piping-count+size 0/3, piping-size 3/3, rooms+area 0/3, rooms-count 6/6, schedule 0/3, slab-count 1/3, slab-rebar 5/6

| id | sheet | lang | question | gold | lowres | png2500 | pdf | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|---|---|
| j01 | dormA2 | en | How many dorm rooms are on the second floor? | 48 | Y 48 | Y 48 | Y 48 | sheets-zones-schedule | 1 | 8.2 |
| j07 | slab100F | en | What reinforcement is in the 150 mm slab? | D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | Y D13 @ 300 | sheets-slab-note | 2 | 23.9 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | - 5 | - 5 | - 5 | sheets-piping | 5 | 0.6 |
| j19 | school00 | fi | Montako luokkahuonetta tässä kerroksessa on? | 8 | Y 8 | Y 8 | Y 8 | generic-ground-haiku | 8 | 14.5 |
| j26 | dormA1 | en | What's the total first floor area? | 28770 | Y 28770 | Y 28770 | Y 28770 | sheets-zones-schedule | 1 | 5.7 |
| j29 | dormA4 | en | Area of the kitchen? | 151 | Y 151 | Y 151 | Y 151 SF | generic-read-haiku | 1 | 10.6 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | - 0 | - 0 | - 4 | generic-ground-haiku | 0 | 8.0 |
| j34 | pipeM101F | en | What size is the pump discharge header? | 300 mm | Y 300mm | Y 300mm | Y 300mm | sheets-piping | 2 | 0.7 |
| j37 | slabS100A | en | How many pump pads are on the pumphouse slab? | 5 | Y 5 | - 6 | - 24 | generic-ground-haiku | 5 | 6.4 |
| j38 | slabS102P | en | What is the reinforcement of the tank floor slab? | D19 @ 250 E.W. top and bottom; | Y D19 bars at 250 spacing, top and bottom  | - D22x3000 | Y D19 HOOP @ 200; D19 @ 250 E.W TOP AND BO | generic-read-haiku | 4 | 5.3 |
| j39 | archA101F | en | How many doors does the filter building have? | 6 | Y 6 | Y 6 | - 8 | generic-ground-haiku | 6 | 56.1 |
| j41 | schedA601 | en | How many doors are listed in the pumphouse door schedule, and how many | 8 doors, 6 of them 3'-0" wide | - 8 | - 8 | - 8 | generic-ground-haiku | 8 | 8.4 |
| j43 | schoolL01 | en | How many group rooms are on level 01? | 5 | Y 5 | Y 5 | Y 5 | generic-ground-haiku | 5 | 30.6 |

API cost of all asks $0.125. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
