# Stoa example sheets: after_scanpdf

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| dorm1 | dormitory | What is the total square footage of the second floor? | 26562 | 26562 | 0.75 | Y | sheets / sheets-zones-schedule | 0.0007 | 15.9 |
| dorm2 | dormitory | What is the area of the west wing dormitory? | 6095 | 7005 | 0.75 | - | sheets / sheets-zones-schedule | 0.0008 | 18.0 |
| dorm3 | dormitory | How many dorm rooms are on the second floor? | 48 | 48 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0007 | 15.3 |
| dorm4 | dormitory | What is the total circulation area on this floor? | 4470 | 2154 | 0.75 | - | sheets / sheets-zones-schedule | 0.0009 | 18.0 |
| dorm5 | dormitory | What is the total dormitory area of all three wings? | 18472 | 14697 | 0.75 | - | sheets / sheets-zones-schedule | 0.0008 | 4.4 |
| dorm6 | dormitory | What is the total common space area? | 4479 | 4479 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0006 | 3.0 |
| dorm7 | dormitory | What is the overall length of the building? | 323'-4" | 323 | 0.55 | - | sheets -> generic / generic-read-haiku | 0.0013 | 6.8 |
| dorm8 | dormitory | How much floor area is coloured as 2nd floor common area (pink) on the plan? | 4479 ~ | 4479 | 0.75 | Y | sheets / sheets-zones-schedule | 0.0007 | 3.8 |
| school1 | special | How many doors are shown on this floor plan? | 128 ~ | 128 | 0.45 | Y | sheets / sheets-arch-detector-door | 0.0000 | 11.7 |
| school2 | special | How many windows are shown on this floor plan? | 101 ~ | 102 | 0.45 | Y | sheets / sheets-arch-detector-window | 0.0000 | 12.3 |
| school3 | special | How many secondary classrooms are on this level? | 8 | (abstain; guess 8) | 0.15 | - | sheets -> generic / generic-ground-haiku | 0.0018 | 17.4 |
| school4 | special | What is the floor area of the Multi-Purpose Hall? | 240 ~ | Total 1463 m² net over 123 rooms. Servery / Furniture 288.4  | 0.5 | - | sheets / sheets-rooms-area-list | 0.0044 | 59.9 |
| school5 | special | What is the floor area of the Library? | 25.5 ~ | 26.05 | 0.63 | Y | sheets / sheets-rooms-area | 0.0044 | 54.1 |
| school6 | special | What is the area of the Kitchen? | 33.5 ~ | (abstain) | 0.0 | - | sheets / sheets-arch-noscale | 0.0000 | 61.3 |
| school7 | special | How many linear meters of baseboard are needed in the Library? | 20.5 ~ | 17.0 | 0.54 | - | sheets / sheets-rooms-baseboard | 0.0044 | 45.4 |
| school8 | special | How many linear meters of baseboard does the Multi-Purpose Hall need? | 51 ~ | 1105.9 | 0.5 | - | sheets / sheets-rooms-baseboard | 0.0044 | 0.1 |
| slab1 | foundation | What is the area of the 150 mm slab-on-grade? | 61.69 ~ | 62.69 | 0.7 | Y | sheets / sheets-slab-area | 0.0125 | 69.6 |
| slab2 | foundation | What is the area of the 300 mm slab-on-grade with D16 bars? | 214.5 ~ | 231.01 | 0.7 | Y | sheets / sheets-slab-area | 0.0133 | 70.1 |
| slab3 | foundation | What reinforcement is specified for the 150 slab-on-grade? | D13 @ 300 | D13 @ 300 | 0.8 | Y | sheets / sheets-slab-note | 0.0135 | 70.1 |
| slab4 | foundation | What is the total length of all trenches given in the notes, in mm? | 7850 | 10.967 | 0.75 | - | sheets / sheets-slab-trench | 0.0127 | 61.5 |
| slab5 | foundation | What is the slab area by type (thickness and bars)? | D16 D13 D22 ~ | 300 mm w/ D22 @ 300: 27.9 m²; 150 mm w/ D13 @ 300: 62.7 m²;  | 0.7 | Y | sheets / sheets-slab-area-by-type | 0.0125 | 0.1 |
| pipe1 | piping | How many non-surge check valves (CV) are shown? | 5 | (abstain) | 0.0 | - | - / timeout | 0.0000 | 75.0 |
| pipe2 | piping | How many fuel pumps are on the piping plan? | 5 | (abstain) | 0.0 | - | - / timeout | 0.0000 | 75.0 |
| pipe3 | piping | How many FSCV valves are there? | 7 | (abstain) | 0.0 | - | - / timeout | 0.0000 | 75.0 |
| pipe4 | piping | What size is the suction header? | 16" | (abstain) | 0.0 | - | - / timeout | 0.0000 | 75.1 |
| pipe5 | piping | What is the size of the pump discharge header? | 12" | (abstain) | 0.0 | - | - / timeout | 0.0000 | 75.0 |
| pipe6 | piping | How many filter separators (FSI and FSR) are shown? | 7 | (abstain) | 0.0 | - | - / timeout | 0.0000 | 75.1 |
| pipe7 | piping | How many different pipe support types (PS tags) are on this plan? | 23 | (abstain) | 0.0 | - | - / timeout | 0.0000 | 75.1 |
| pipe8 | piping | How many pipe support labels are printed on the plan? | 41 | (abstain) | 0.0 | - | - / timeout | 0.0000 | 75.1 |
| pipe9 | piping | What sizes of pipe are on this sheet? | 1" 2" 3" 4" 6" 8" 10" 12" 16" | 1", 2", 3", 4", 6", 8", 10", 12", 16" | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.4 |
| pipe10 | piping | Which other sheets does this plan reference? | M-001 M-301A M-302 M-303 M-504 MS513 S-101 | M-001, M-301A, M-302, M-303, M-504, MS513, S-101 | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.3 |
| pipe11 | piping | What does note 4 say? | MICRONIC FILTER MAY BE NECESSARY | MATERIALS SHALL BE PER UFC 3-460-01. | 0.75 | - | sheets / sheets-piping | 0.0000 | 0.5 |
| pipe12 | piping | How many pressure gauges (PG) are shown? | 21 | 20 | 0.55 | - | sheets / sheets-piping | 0.0000 | 0.5 |
| pipe13 | piping | What size is the return line? | 8" | 8" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 0.8 |

**14/34 correct**; dormitory 4/8, special 3/8, foundation 4/5, piping 3/13; API cost of the questions $0.090
