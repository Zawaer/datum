# Stoa example sheets: baseline_lowres

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| dorm1 | dormitory | What is the total square footage of the second floor? | 26562 | 26,562 SF | 0.8 | Y | generic / generic-read-haiku | 0.0011 | 3.1 |
| dorm2 | dormitory | What is the area of the west wing dormitory? | 6095 | 6095 | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 3.6 |
| dorm3 | dormitory | How many dorm rooms are on the second floor? | 48 | 0 | 0.4 | - | generic / generic-ground-haiku | 0.0014 | 5.1 |
| dorm4 | dormitory | What is the total circulation area on this floor? | 4470 | 4470 | 0.55 | Y | generic / generic-read-haiku | 0.0013 | 4.5 |
| dorm5 | dormitory | What is the total dormitory area of all three wings? | 18472 | 18472 | 0.8 | Y | generic / generic-read-haiku | 0.0013 | 4.1 |
| dorm6 | dormitory | What is the total common space area? | 4479 | 4479 | 0.8 | Y | generic / generic-read-haiku | 0.0011 | 3.0 |
| dorm7 | dormitory | What is the overall length of the building? | 323'-4" | 323 | 0.55 | - | generic / generic-read-haiku | 0.0014 | 4.8 |
| dorm8 | dormitory | How much floor area is coloured as 2nd floor common area (pink) on the plan? | 4479 ~ | 2911 | 0.55 | - | generic / generic-read-haiku | 0.0014 | 4.9 |
| school1 | special | How many doors are shown on this floor plan? | 128 ~ | 42 | 0.315 | - | generic / generic-ground-haiku | 0.0037 | 7.3 |
| school2 | special | How many windows are shown on this floor plan? | 101 ~ | 44 | 0.314 | - | generic / generic-ground-haiku | 0.0044 | 8.1 |
| school3 | special | How many secondary classrooms are on this level? | 8 | 5 | 0.333 | - | generic / generic-ground-haiku | 0.0022 | 11.4 |
| school4 | special | What is the floor area of the Multi-Purpose Hall? | 240 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0012 | 3.6 |
| school5 | special | What is the floor area of the Library? | 25.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0012 | 3.8 |
| school6 | special | What is the area of the Kitchen? | 33.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0012 | 3.6 |
| school7 | special | How many linear meters of baseboard are needed in the Library? | 20.5 ~ | 0 | 0.4 | - | generic / generic-ground-haiku | 0.0026 | 3.1 |
| school8 | special | How many linear meters of baseboard does the Multi-Purpose Hall need? | 51 ~ | (abstain; guess 7) | 0.272 | - | generic / generic-ground-haiku | 0.0033 | 6.0 |
| slab1 | foundation | What is the area of the 150 mm slab-on-grade? | 61.69 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0013 | 4.1 |
| slab2 | foundation | What is the area of the 300 mm slab-on-grade with D16 bars? | 214.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0011 | 3.7 |
| slab3 | foundation | What reinforcement is specified for the 150 slab-on-grade? | D13 @ 300 | D13 @ 300 (No. 13 bar at 300 mm spacing) | 0.8 | Y | generic / generic-read-haiku | 0.0013 | 3.9 |
| slab4 | foundation | What is the total length of all trenches given in the notes, in mm? | 7850 | 7650 | 0.8 | - | generic / generic-read-haiku | 0.0013 | 3.9 |
| slab5 | foundation | What is the slab area by type (thickness and bars)? | D16 D13 D22 ~ | 300 | 0.55 | - | generic / generic-read-haiku | 0.0016 | 5.9 |
| pipe1 | piping | How many non-surge check valves (CV) are shown? | 5 | 5 | 0.75 | Y | generic / generic-ground-haiku | 0.0031 | 4.6 |
| pipe2 | piping | How many fuel pumps are on the piping plan? | 5 | (abstain; guess 1) | 0.15 | - | generic / generic-ground-haiku | 0.0032 | 5.8 |
| pipe3 | piping | How many FSCV valves are there? | 7 | (abstain; guess 2) | 0.15 | - | generic / generic-ground-haiku | 0.0030 | 4.9 |
| pipe4 | piping | What size is the suction header? | 16" | 16" | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 3.1 |
| pipe5 | piping | What is the size of the pump discharge header? | 12" | 12 in (12" pump discharge header) | 0.8 | Y | generic / generic-read-haiku | 0.0011 | 3.9 |
| pipe6 | piping | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.75 | Y | generic / generic-ground-haiku | 0.0034 | 5.8 |
| pipe7 | piping | How many different pipe support types (PS tags) are on this plan? | 23 | 40 | 0.694 | - | generic / generic-ground-haiku | 0.0045 | 10.6 |
| pipe8 | piping | How many pipe support labels are printed on the plan? | 41 | 41 | 0.462 | Y | generic / generic-ground-haiku | 0.0042 | 9.3 |
| pipe9 | piping | What sizes of pipe are on this sheet? | 1" 2" 3" 4" 6" 8" 10" 12" 16" | 2", 3", 4", 6", 8", 10", 12", and 16" pipe sizes are labeled | 0.8 | - | generic / generic-read-haiku | 0.0014 | 4.6 |
| pipe10 | piping | Which other sheets does this plan reference? | M-001 M-301A M-302 M-303 M-504 MS513 S-101 | M-001, M-301A, M-302, M-303, M-504, MS513, S-101 | 0.55 | Y | generic / generic-read-haiku | 0.0018 | 8.6 |
| pipe11 | piping | What does note 4 say? | MICRONIC FILTER MAY BE NECESSARY | Micronic filter may be necessary. See UFC 3-460-1 if the tra | 0.8 | Y | generic / generic-read-haiku | 0.0013 | 4.0 |
| pipe12 | piping | How many pressure gauges (PG) are shown? | 21 | 21 | 0.625 | Y | generic / generic-ground-haiku | 0.0040 | 6.6 |
| pipe13 | piping | What size is the return line? | 8" | 8" (8 inch) | 0.8 | Y | generic / generic-read-haiku | 0.0009 | 3.2 |

**15/34 correct**; dormitory 5/8, special 0/8, foundation 1/5, piping 9/13; API cost of the questions $0.069
