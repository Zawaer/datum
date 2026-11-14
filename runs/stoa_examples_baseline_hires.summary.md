# Stoa example sheets: baseline_hires

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| dorm1 | dormitory | What is the total square footage of the second floor? | 26562 | 26,562 SF | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 4.6 |
| dorm2 | dormitory | What is the area of the west wing dormitory? | 6095 | 6095 | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 4.5 |
| dorm3 | dormitory | How many dorm rooms are on the second floor? | 48 | 0 | 0.4 | - | generic / generic-ground-haiku | 0.0016 | 8.3 |
| dorm4 | dormitory | What is the total circulation area on this floor? | 4470 | 4470 | 0.55 | Y | generic / generic-read-haiku | 0.0015 | 7.1 |
| dorm5 | dormitory | What is the total dormitory area of all three wings? | 18472 | 18472 | 0.55 | Y | generic / generic-read-haiku | 0.0014 | 5.7 |
| dorm6 | dormitory | What is the total common space area? | 4479 | 4479 | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 4.0 |
| dorm7 | dormitory | What is the overall length of the building? | 323'-4" | 323 | 0.8 | - | generic / generic-read-haiku | 0.0012 | 4.7 |
| dorm8 | dormitory | How much floor area is coloured as 2nd floor common area (pink) on the plan? | 4479 ~ | 4479 | 0.55 | Y | generic / generic-read-haiku | 0.0016 | 6.6 |
| school1 | special | How many doors are shown on this floor plan? | 128 ~ | 74 | 0.35 | - | generic / generic-ground-haiku | 0.0093 | 16.0 |
| school2 | special | How many windows are shown on this floor plan? | 101 ~ | 53 | 0.377 | - | generic / generic-ground-haiku | 0.0097 | 13.4 |
| school3 | special | How many secondary classrooms are on this level? | 8 | 8 | 0.75 | Y | generic / generic-ground-haiku | 0.0023 | 13.9 |
| school4 | special | What is the floor area of the Multi-Purpose Hall? | 240 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0012 | 4.0 |
| school5 | special | What is the floor area of the Library? | 25.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0012 | 3.6 |
| school6 | special | What is the area of the Kitchen? | 33.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0014 | 5.8 |
| school7 | special | How many linear meters of baseboard are needed in the Library? | 20.5 ~ | 0 | 0.4 | - | generic / generic-ground-haiku | 0.0054 | 8.0 |
| school8 | special | How many linear meters of baseboard does the Multi-Purpose Hall need? | 51 ~ | 12 | 0.307 | - | generic / generic-ground-haiku | 0.0074 | 10.8 |
| slab1 | foundation | What is the area of the 150 mm slab-on-grade? | 61.69 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0013 | 4.4 |
| slab2 | foundation | What is the area of the 300 mm slab-on-grade with D16 bars? | 214.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0011 | 4.4 |
| slab3 | foundation | What reinforcement is specified for the 150 slab-on-grade? | D13 @ 300 | D13 @ 300 | 0.8 | Y | generic / generic-read-haiku | 0.0013 | 4.2 |
| slab4 | foundation | What is the total length of all trenches given in the notes, in mm? | 7850 | 7850 | 0.8 | Y | generic / generic-read-haiku | 0.0013 | 4.8 |
| slab5 | foundation | What is the slab area by type (thickness and bars)? | D16 D13 D22 ~ | 300 | 0.8 | - | generic / generic-read-haiku | 0.0016 | 6.2 |
| pipe1 | piping | How many non-surge check valves (CV) are shown? | 5 | 5 | 0.75 | Y | generic / generic-ground-haiku | 0.0073 | 8.3 |
| pipe2 | piping | How many fuel pumps are on the piping plan? | 5 | (abstain; guess 1) | 0.15 | - | generic / generic-ground-haiku | 0.0078 | 11.7 |
| pipe3 | piping | How many FSCV valves are there? | 7 | 5 | 0.608 | - | generic / generic-ground-haiku | 0.0080 | 9.4 |
| pipe4 | piping | What size is the suction header? | 16" | 16 inch (16" SUCTION HEADER) | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 4.1 |
| pipe5 | piping | What is the size of the pump discharge header? | 12" | 12" | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 4.2 |
| pipe6 | piping | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.75 | Y | generic / generic-ground-haiku | 0.0075 | 8.9 |
| ho_dorm1 | us | What is the total first floor area? | 28770 | 28770 | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 4.3 |
| ho_dorm2 | us | What is the total common space area on the first floor? | 6687 | 6687 | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 4.5 |
| ho_dorm3 | us | What is the third floor subtotal area, excluding the exterior stair? | 26201 | 26201 | 0.8 | Y | generic / generic-read-haiku | 0.0013 | 4.9 |
| ho_dorm4 | us | How many bedrooms are in the dormitory module? | 4 | 4 | 0.75 | Y | generic / generic-ground-haiku | 0.0021 | 12.8 |
| ho_dorm5 | us | What is the total bedroom area in the dormitory module? | 756 | 756 | 0.8 | Y | generic / generic-read-haiku | 0.0014 | 5.1 |
| ho_pipe1 | us | How many FSCV valves are there? | 7 | 5 | 0.608 | - | generic / generic-ground-haiku | 0.0075 | 7.1 |
| ho_pipe2 | us | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.75 | Y | generic / generic-ground-haiku | 0.0069 | 6.2 |
| ho_slab1 | us | What size are the radial bars in the tank floor slab? | D19 | D19 bars, cut to lengths from 3100 to 8700 (mm) | 0.8 | Y | generic / generic-read-haiku | 0.0015 | 6.4 |
| ho_school1 | uk | How many secondary classrooms are on this level? | 3 | 3 | 0.75 | Y | generic / generic-ground-haiku | 0.0019 | 8.2 |
| ho_school2 | uk | How many group rooms are on this level? | 4 | 5 | 0.75 | - | generic / generic-ground-haiku | 0.0020 | 11.0 |
| pipe7 | piping | How many different pipe support types (PS tags) are on this plan? | 23 | 40 | 0.612 | - | generic / generic-ground-haiku | 0.0097 | 12.0 |
| pipe8 | piping | How many pipe support labels are printed on the plan? | 41 | 42 | 0.603 | - | generic / generic-ground-haiku | 0.0095 | 13.1 |
| pipe9 | piping | What sizes of pipe are on this sheet? | 1" 2" 3" 4" 6" 8" 10" 12" 16" | 1", 2", 3", 4", 6", 8", 10", 12", and 16" pipe sizes are lab | 0.8 | Y | generic / generic-read-haiku | 0.0014 | 6.5 |
| pipe10 | piping | Which other sheets does this plan reference? | M-001 M-301A M-302 M-303 M-504 MS513 S-101 | M-001, M-301A, M-302, M-303, M-504, MS513, S-101 | 0.55 | Y | generic / generic-read-haiku | 0.0018 | 8.9 |
| pipe11 | piping | What does note 4 say? | MICRONIC FILTER MAY BE NECESSARY | Micronic filter may be necessary. See UFC 3-460-1, if transf | 0.8 | Y | generic / generic-read-haiku | 0.0013 | 4.4 |
| pipe12 | piping | How many pressure gauges (PG) are shown? | 21 | 21 | 0.75 | Y | generic / generic-ground-haiku | 0.0081 | 8.9 |
| pipe13 | piping | What size is the return line? | 8" | 8" | 0.8 | Y | generic / generic-read-haiku | 0.0011 | 3.7 |
| ho_pipe3 | us | Which other sheets does this plan reference? | M-001 M-301B M-302 M-303 M-504 MS513 S-101 | M-001, M-301B, M-302, M-303, M-504, MS513, S-101 | 0.8 | Y | generic / generic-read-haiku | 0.0018 | 9.5 |

**27/45 correct**; dormitory 6/8, special 1/8, foundation 2/5, piping 9/13, held-out us 8/9, held-out uk 1/2; API cost of the questions $0.150
