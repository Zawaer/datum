# Stoa example sheets: baseline_png2500

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| dorm1 | dormitory | What is the total square footage of the second floor? | 26562 | 26,562 SF | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 4.1 |
| dorm2 | dormitory | What is the area of the west wing dormitory? | 6095 | 6095 | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 3.9 |
| dorm3 | dormitory | How many dorm rooms are on the second floor? | 48 | 0 | 0.4 | - | generic / generic-ground-haiku | 0.0012 | 5.2 |
| dorm4 | dormitory | What is the total circulation area on this floor? | 4470 | 4470 | 0.55 | Y | generic / generic-read-haiku | 0.0014 | 5.6 |
| dorm5 | dormitory | What is the total dormitory area of all three wings? | 18472 | 18472 | 0.8 | Y | generic / generic-read-haiku | 0.0013 | 4.9 |
| dorm6 | dormitory | What is the total common space area? | 4479 | 4479 | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 4.1 |
| dorm7 | dormitory | What is the overall length of the building? | 323'-4" | 323 | 0.55 | - | generic / generic-read-haiku | 0.0013 | 4.3 |
| dorm8 | dormitory | How much floor area is coloured as 2nd floor common area (pink) on the plan? | 4479 ~ | 2911 | 0.55 | - | generic / generic-read-haiku | 0.0014 | 7.7 |
| school1 | special | How many doors are shown on this floor plan? | 128 ~ | 66 | 0.322 | - | generic / generic-ground-haiku | 0.0093 | 11.0 |
| school2 | special | How many windows are shown on this floor plan? | 101 ~ | (abstain; guess 31) | 0.299 | - | generic / generic-ground-haiku | 0.0088 | 9.5 |
| school3 | special | How many secondary classrooms are on this level? | 8 | 8 | 0.75 | Y | generic / generic-ground-haiku | 0.0023 | 12.1 |
| school4 | special | What is the floor area of the Multi-Purpose Hall? | 240 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0012 | 3.8 |
| school5 | special | What is the floor area of the Library? | 25.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0012 | 4.6 |
| school6 | special | What is the area of the Kitchen? | 33.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0013 | 4.1 |
| school7 | special | How many linear meters of baseboard are needed in the Library? | 20.5 ~ | 0 | 0.4 | - | generic / generic-ground-haiku | 0.0049 | 3.5 |
| school8 | special | How many linear meters of baseboard does the Multi-Purpose Hall need? | 51 ~ | 5 | 0.464 | - | generic / generic-ground-haiku | 0.0074 | 6.2 |
| slab1 | foundation | What is the area of the 150 mm slab-on-grade? | 61.69 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0013 | 4.2 |
| slab2 | foundation | What is the area of the 300 mm slab-on-grade with D16 bars? | 214.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0014 | 4.6 |
| slab3 | foundation | What reinforcement is specified for the 150 slab-on-grade? | D13 @ 300 | D13 @ 300 | 0.8 | Y | generic / generic-read-haiku | 0.0013 | 4.2 |
| slab4 | foundation | What is the total length of all trenches given in the notes, in mm? | 7850 | 7850 | 0.8 | Y | generic / generic-read-haiku | 0.0015 | 5.1 |
| slab5 | foundation | What is the slab area by type (thickness and bars)? | D16 D13 D22 ~ | 300 | 0.8 | - | generic / generic-read-haiku | 0.0017 | 7.2 |
| pipe1 | piping | How many non-surge check valves (CV) are shown? | 5 | 5 | 0.75 | Y | generic / generic-ground-haiku | 0.0071 | 6.5 |
| pipe2 | piping | How many fuel pumps are on the piping plan? | 5 | 5 | 0.464 | Y | generic / generic-ground-haiku | 0.0075 | 6.8 |
| pipe3 | piping | How many FSCV valves are there? | 7 | (abstain; guess 4) | 0.15 | - | generic / generic-ground-haiku | 0.0073 | 5.6 |
| pipe4 | piping | What size is the suction header? | 16" | 16" | 0.8 | Y | generic / generic-read-haiku | 0.0011 | 3.2 |
| pipe5 | piping | What is the size of the pump discharge header? | 12" | 12" | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 3.7 |
| pipe6 | piping | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.75 | Y | generic / generic-ground-haiku | 0.0075 | 5.6 |
| pipe7 | piping | How many different pipe support types (PS tags) are on this plan? | 23 | 40 | 0.62 | - | generic / generic-ground-haiku | 0.0108 | 12.5 |
| pipe8 | piping | How many pipe support labels are printed on the plan? | 41 | 43 | 0.585 | - | generic / generic-ground-haiku | 0.0102 | 11.5 |
| pipe9 | piping | What sizes of pipe are on this sheet? | 1" 2" 3" 4" 6" 8" 10" 12" 16" | 1", 2", 3" (sleeve), 4" (venturi), 6", 8", 10", 12", and 16" | 0.8 | Y | generic / generic-read-haiku | 0.0015 | 6.4 |
| pipe10 | piping | Which other sheets does this plan reference? | M-001 M-301A M-302 M-303 M-504 MS513 S-101 | S-101, M-001, M-301A, M-302, M-303, M-504, MS513 | 0.55 | Y | generic / generic-read-haiku | 0.0019 | 9.2 |
| pipe11 | piping | What does note 4 say? | MICRONIC FILTER MAY BE NECESSARY | Micronic filter may be necessary. See UFC 3-460-1, if transf | 0.8 | Y | generic / generic-read-haiku | 0.0013 | 4.4 |
| pipe12 | piping | How many pressure gauges (PG) are shown? | 21 | 17 | 0.596 | - | generic / generic-ground-haiku | 0.0091 | 8.0 |
| pipe13 | piping | What size is the return line? | 8" | 8" | 0.8 | Y | generic / generic-read-haiku | 0.0012 | 3.5 |

**17/34 correct**; dormitory 5/8, special 1/8, foundation 2/5, piping 9/13; API cost of the questions $0.122
