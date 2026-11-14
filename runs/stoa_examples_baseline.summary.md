# Stoa example sheets: baseline

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| dorm1 | dormitory | What is the total square footage of the second floor? | 26562 | 26,562 SF | 0.8 | Y | generic / generic-read-haiku | 0.0011 | 3.9 |
| dorm2 | dormitory | What is the area of the west wing dormitory? | 6095 | 6095 | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 4.9 |
| dorm3 | dormitory | How many dorm rooms are on the second floor? | 48 | 4 | 0.35 | - | generic / generic-ground-haiku | 0.0021 | 12.5 |
| dorm4 | dormitory | What is the total circulation area on this floor? | 4470 | 4470 | 0.55 | Y | generic / generic-read-haiku | 0.0015 | 6.8 |
| dorm5 | dormitory | What is the total dormitory area of all three wings? | 18472 | 18472 | 0.8 | Y | generic / generic-read-haiku | 0.0013 | 4.9 |
| dorm6 | dormitory | What is the total common space area? | 4479 | 4479 | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 4.1 |
| dorm7 | dormitory | What is the overall length of the building? | 323'-4" | 323 | 0.8 | - | generic / generic-read-haiku | 0.0013 | 5.7 |
| dorm8 | dormitory | How much floor area is coloured as 2nd floor common area (pink) on the plan? | 4479 ~ | 2911 | 0.55 | - | generic / generic-read-haiku | 0.0013 | 6.0 |
| school1 | special | How many doors are shown on this floor plan? | 128 ~ | 78 | 0.372 | - | generic / generic-ground-haiku | 0.0099 | 11.7 |
| school2 | special | How many windows are shown on this floor plan? | 101 ~ | (abstain; guess 36) | 0.236 | - | generic / generic-ground-haiku | 0.0093 | 13.3 |
| school3 | special | How many secondary classrooms are on this level? | 8 | 8 | 0.75 | Y | generic / generic-ground-haiku | 0.0020 | 19.0 |
| school4 | special | What is the floor area of the Multi-Purpose Hall? | 240 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0012 | 11.8 |
| school5 | special | What is the floor area of the Library? | 25.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0013 | 9.8 |
| school6 | special | What is the area of the Kitchen? | 33.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0012 | 3.9 |
| school7 | special | How many linear meters of baseboard are needed in the Library? | 20.5 ~ | 0 | 0.4 | - | generic / generic-ground-haiku | 0.0048 | 3.3 |
| school8 | special | How many linear meters of baseboard does the Multi-Purpose Hall need? | 51 ~ | 1 | 0.75 | - | generic / generic-ground-haiku | 0.0014 | 6.3 |
| slab1 | foundation | What is the area of the 150 mm slab-on-grade? | 61.69 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0013 | 4.2 |
| slab2 | foundation | What is the area of the 300 mm slab-on-grade with D16 bars? | 214.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0015 | 4.6 |
| slab3 | foundation | What reinforcement is specified for the 150 slab-on-grade? | D13 @ 300 | D13 @ 300 | 0.8 | Y | generic / generic-read-haiku | 0.0011 | 4.1 |
| slab4 | foundation | What is the total length of all trenches given in the notes, in mm? | 7850 | 7850 | 0.8 | Y | generic / generic-read-haiku | 0.0014 | 4.7 |
| slab5 | foundation | What is the slab area by type (thickness and bars)? | D16 D13 D22 ~ | 300 | 0.8 | - | generic / generic-read-haiku | 0.0018 | 7.2 |
| pipe1 | piping | How many non-surge check valves (CV) are shown? | 5 | 5 | 0.75 | Y | generic / generic-ground-haiku | 0.0069 | 5.3 |
| pipe2 | piping | How many fuel pumps are on the piping plan? | 5 | (abstain; guess 5) | 0.15 | - | generic / generic-ground-haiku | 0.0073 | 6.6 |
| pipe3 | piping | How many FSCV valves are there? | 7 | (abstain; guess 5) | 0.15 | - | generic / generic-ground-haiku | 0.0078 | 6.9 |
| pipe4 | piping | What size is the suction header? | 16" | 16" | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 3.8 |
| pipe5 | piping | What is the size of the pump discharge header? | 12" | 12" | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 4.0 |
| pipe6 | piping | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.75 | Y | generic / generic-ground-haiku | 0.0074 | 5.4 |

**12/27 correct**; dormitory 5/8, special 1/8, foundation 2/5, piping 4/6; API cost of the questions $0.081
