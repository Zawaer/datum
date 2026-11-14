# Stoa example sheets: after

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| dorm1 | dormitory | What is the total square footage of the second floor? | 26562 | 26,562 SF | 0.8 | Y | sheets / sheets-text-read | 0.0014 | 9.5 |
| dorm2 | dormitory | What is the area of the west wing dormitory? | 6095 | 6,095 SF | 0.8 | Y | sheets / sheets-text-read | 0.0014 | 10.1 |
| dorm3 | dormitory | How many dorm rooms are on the second floor? | 48 | (abstain; guess 28) | 0.15 | - | sheets -> generic / generic-ground-haiku | 0.0077 | 13.0 |
| dorm4 | dormitory | What is the total circulation area on this floor? | 4470 | 4,470 SF | 0.8 | Y | sheets / sheets-text-sum | 0.0018 | 8.4 |
| dorm5 | dormitory | What is the total dormitory area of all three wings? | 18472 | 18,472 SF | 0.8 | Y | sheets / sheets-text-sum | 0.0017 | 7.6 |
| dorm6 | dormitory | What is the total common space area? | 4479 | 4,479 SF | 0.8 | Y | sheets / sheets-text-read | 0.0015 | 3.4 |
| dorm7 | dormitory | What is the overall length of the building? | 323'-4" | 323 | 0.55 | - | sheets -> generic / generic-read-haiku | 0.0014 | 6.4 |
| dorm8 | dormitory | How much floor area is coloured as 2nd floor common area (pink) on the plan? | 4479 ~ | 2911 | 0.55 | - | sheets -> generic / generic-read-haiku | 0.0015 | 10.7 |
| school1 | special | How many doors are shown on this floor plan? | 128 ~ | (abstain; guess 64) | 0.276 | - | sheets -> generic / generic-ground-haiku | 0.0107 | 18.3 |
| school2 | special | How many windows are shown on this floor plan? | 101 ~ | 57 | 0.434 | - | sheets -> generic / generic-ground-haiku | 0.0093 | 13.2 |
| school3 | special | How many secondary classrooms are on this level? | 8 | 8 | 0.55 | Y | sheets / sheets-arch-rooms-count | 0.0000 | 8.9 |
| school4 | special | What is the floor area of the Multi-Purpose Hall? | 240 ~ | 274.73 | 0.7 | - | sheets / sheets-rooms-area | 0.0000 | 1.2 |
| school5 | special | What is the floor area of the Library? | 25.5 ~ | 25.1 | 0.6 | Y | sheets / sheets-arch-rooms | 0.0000 | 3.7 |
| school6 | special | What is the area of the Kitchen? | 33.5 ~ | (abstain) | 0.0 | - | sheets / sheets-arch-noroom | 0.0002 | 8.9 |
| school7 | special | How many linear meters of baseboard are needed in the Library? | 20.5 ~ | 21.7 | 0.5 | Y | sheets / sheets-arch-baseboard | 0.0000 | 0.0 |
| school8 | special | How many linear meters of baseboard does the Multi-Purpose Hall need? | 51 ~ | 71.7 | 0.6 | - | sheets / sheets-rooms-baseboard | 0.0000 | 0.0 |
| slab1 | foundation | What is the area of the 150 mm slab-on-grade? | 61.69 ~ | 74.32 | 0.56 | - | sheets / sheets-slab-area | 0.0000 | 13.5 |
| slab2 | foundation | What is the area of the 300 mm slab-on-grade with D16 bars? | 214.5 ~ | (abstain) | 0.0 | - | sheets / sheets-none | 0.0000 | 17.5 |
| slab3 | foundation | What reinforcement is specified for the 150 slab-on-grade? | D13 @ 300 | D13 bars @ 300 (150 slab-on-grade w/ D13 @ 300) | 0.8 | Y | sheets -> generic / generic-read-haiku | 0.0014 | 15.2 |
| slab4 | foundation | What is the total length of all trenches given in the notes, in mm? | 7850 | 1.825 | 0.75 | - | sheets / sheets-slab-trench | 0.0000 | 6.0 |
| slab5 | foundation | What is the slab area by type (thickness and bars)? | D16 D13 D22 ~ | untyped: 434.7 m²; 300 mm w/ D22 @ 300: 29.0 m²; 150 mm: 74. | 0.56 | - | sheets / sheets-slab-area-by-type | 0.0000 | 0.0 |
| pipe1 | piping | How many non-surge check valves (CV) are shown? | 5 | 5 | 0.85 | Y | sheets / sheets-piping | 0.0565 | 60.9 |
| pipe2 | piping | How many fuel pumps are on the piping plan? | 5 | 5 | 0.85 | Y | sheets / sheets-piping | 0.0524 | 60.3 |
| pipe3 | piping | How many FSCV valves are there? | 7 | 7 | 0.85 | Y | sheets / sheets-piping | 0.0617 | 66.2 |
| pipe4 | piping | What size is the suction header? | 16" | 16" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 0.6 |
| pipe5 | piping | What is the size of the pump discharge header? | 12" | 12" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 1.0 |
| pipe6 | piping | How many filter separators (FSI and FSR) are shown? | 7 | 5 | 0.85 | - | sheets / sheets-piping | 0.0000 | 0.5 |

**14/27 correct**; dormitory 5/8, special 3/8, foundation 1/5, piping 5/6; API cost of the questions $0.210
