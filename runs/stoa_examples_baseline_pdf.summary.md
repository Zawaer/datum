# Stoa example sheets: baseline_pdf

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| dorm1 | dormitory | What is the total square footage of the second floor? | 26562 | 26,562 SF | 0.85 | Y | generic / generic-text-haiku | 0.0014 | 2.8 |
| dorm2 | dormitory | What is the area of the west wing dormitory? | 6095 | 6,095 SF | 0.85 | Y | generic / generic-text-haiku | 0.0013 | 2.1 |
| dorm3 | dormitory | How many dorm rooms are on the second floor? | 48 | 48 dorms | 0.85 | Y | generic / generic-text-haiku | 0.0014 | 3.1 |
| dorm4 | dormitory | What is the total circulation area on this floor? | 4470 | 4470 | 0.6 | Y | generic / generic-text-haiku | 0.0016 | 4.4 |
| dorm5 | dormitory | What is the total dormitory area of all three wings? | 18472 | 18472 | 0.85 | Y | generic / generic-text-haiku | 0.0014 | 3.1 |
| dorm6 | dormitory | What is the total common space area? | 4479 | 4,479 SF | 0.85 | Y | generic / generic-text-haiku | 0.0014 | 2.7 |
| dorm7 | dormitory | What is the overall length of the building? | 323'-4" | 323'-4" | 0.6 | Y | generic / generic-text-haiku | 0.0017 | 5.6 |
| dorm8 | dormitory | How much floor area is coloured as 2nd floor common area (pink) on the plan? | 4479 ~ | 2911 | 0.55 | - | generic / generic-read-haiku | 0.0045 | 13.7 |
| school1 | special | How many doors are shown on this floor plan? | 128 ~ | 0 | 0.4 | - | generic / generic-ground-haiku | 0.0028 | 5.2 |
| school2 | special | How many windows are shown on this floor plan? | 101 ~ | 0 | 0.4 | - | generic / generic-ground-haiku | 0.0020 | 7.2 |
| school3 | special | How many secondary classrooms are on this level? | 8 | 8 | 0.85 | Y | generic / generic-text-haiku | 0.0016 | 6.2 |
| school4 | special | What is the floor area of the Multi-Purpose Hall? | 240 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0036 | 8.1 |
| school5 | special | What is the floor area of the Library? | 25.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0024 | 5.6 |
| school6 | special | What is the area of the Kitchen? | 33.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0024 | 5.6 |
| school7 | special | How many linear meters of baseboard are needed in the Library? | 20.5 ~ | 0 | 0.4 | - | generic / generic-ground-haiku | 0.0061 | 5.7 |
| school8 | special | How many linear meters of baseboard does the Multi-Purpose Hall need? | 51 ~ | (abstain; guess 10) | 0.25 | - | generic / generic-ground-haiku | 0.0080 | 10.4 |
| slab1 | foundation | What is the area of the 150 mm slab-on-grade? | 61.69 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0059 | 11.4 |
| slab2 | foundation | What is the area of the 300 mm slab-on-grade with D16 bars? | 214.5 ~ | (abstain) | 0.0 | - | generic / generic-read-haiku | 0.0059 | 10.9 |
| slab3 | foundation | What reinforcement is specified for the 150 slab-on-grade? | D13 @ 300 | D13 @ 300 | 0.85 | Y | generic / generic-text-haiku | 0.0024 | 4.2 |
| slab4 | foundation | What is the total length of all trenches given in the notes, in mm? | 7850 | 7850 | 0.85 | Y | generic / generic-text-haiku | 0.0022 | 2.8 |
| slab5 | foundation | What is the slab area by type (thickness and bars)? | D16 D13 D22 ~ | 300 | 0.8 | - | generic / generic-read-haiku | 0.0038 | 10.9 |
| pipe1 | piping | How many non-surge check valves (CV) are shown? | 5 | 5 | 0.34 | Y | generic / generic-text-haiku | 0.0026 | 3.4 |
| pipe2 | piping | How many fuel pumps are on the piping plan? | 5 | 5 | 0.3 | Y | generic / generic-text-haiku | 0.0029 | 6.2 |
| pipe3 | piping | How many FSCV valves are there? | 7 | 7 | 0.85 | Y | generic / generic-text-haiku | 0.0025 | 3.7 |
| pipe4 | piping | What size is the suction header? | 16" | 16" | 0.85 | Y | generic / generic-text-haiku | 0.0024 | 2.3 |
| pipe5 | piping | What is the size of the pump discharge header? | 12" | 12" | 0.85 | Y | generic / generic-text-haiku | 0.0025 | 2.6 |
| pipe6 | piping | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.85 | Y | generic / generic-text-haiku | 0.0027 | 5.3 |
| pipe7 | piping | How many different pipe support types (PS tags) are on this plan? | 23 | 23 | 0.85 | Y | generic / generic-text-haiku | 0.0033 | 10.3 |
| pipe8 | piping | How many pipe support labels are printed on the plan? | 41 | 41 | 0.6 | Y | generic / generic-text-haiku | 0.0038 | 11.9 |
| pipe9 | piping | What sizes of pipe are on this sheet? | 1" 2" 3" 4" 6" 8" 10" 12" 16" | 1", 2", 4" (venturi), 6", 8", 10", 12", 16" | 0.6 | - | generic / generic-text-haiku | 0.0033 | 9.2 |
| pipe10 | piping | Which other sheets does this plan reference? | M-001 M-301A M-302 M-303 M-504 MS513 S-101 | 7 sheets: M-001, M-301A, M-302, M-303, M-504, MS513, S-101 | 0.36 | Y | generic / generic-text-haiku | 0.0032 | 8.6 |
| pipe11 | piping | What does note 4 say? | MICRONIC FILTER MAY BE NECESSARY | MICRONIC FILTER MAY BE NECESSARY. SEE UFC 3-460-1, IF TRANSF | 0.85 | Y | generic / generic-text-haiku | 0.0027 | 4.4 |
| pipe12 | piping | How many pressure gauges (PG) are shown? | 21 | 21 | 0.6 | Y | generic / generic-text-haiku | 0.0031 | 6.9 |
| pipe13 | piping | What size is the return line? | 8" | 8" | 0.85 | Y | generic / generic-text-haiku | 0.0024 | 2.4 |

**22/34 correct**; dormitory 7/8, special 1/8, foundation 2/5, piping 12/13; API cost of the questions $0.101
