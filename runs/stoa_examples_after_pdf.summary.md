# Stoa example sheets: after_pdf

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| dorm1 | dormitory | What is the total square footage of the second floor? | 26562 | 26562 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0004 | 3.9 |
| dorm2 | dormitory | What is the area of the west wing dormitory? | 6095 | 6095 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0004 | 3.7 |
| dorm3 | dormitory | How many dorm rooms are on the second floor? | 48 | 48 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0004 | 3.7 |
| dorm4 | dormitory | What is the total circulation area on this floor? | 4470 | 4470 | 0.75 | Y | sheets / sheets-zones-schedule | 0.0006 | 3.7 |
| dorm5 | dormitory | What is the total dormitory area of all three wings? | 18472 | 18472 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0004 | 3.0 |
| dorm6 | dormitory | What is the total common space area? | 4479 | 4479 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0004 | 2.5 |
| dorm7 | dormitory | What is the overall length of the building? | 323'-4" | 323'-4" | 0.6 | Y | sheets -> generic / generic-text-haiku | 0.0008 | 3.9 |
| dorm8 | dormitory | How much floor area is coloured as 2nd floor common area (pink) on the plan? | 4479 ~ | 4479 | 0.75 | Y | sheets / sheets-zones-schedule | 0.0005 | 3.8 |
| school1 | special | How many doors are shown on this floor plan? | 128 ~ | 128 | 0.65 | Y | sheets / sheets-arch-detector-door | 0.0000 | 3.3 |
| school2 | special | How many windows are shown on this floor plan? | 101 ~ | 101 | 0.65 | Y | sheets / sheets-arch-detector-window | 0.0000 | 4.3 |
| school3 | special | How many secondary classrooms are on this level? | 8 | 8 | 0.55 | Y | sheets / sheets-arch-rooms-count | 0.0000 | 5.2 |
| school4 | special | What is the floor area of the Multi-Purpose Hall? | 240 ~ | 258.07 | 0.7 | Y | sheets / sheets-rooms-area | 0.0000 | 6.3 |
| school5 | special | What is the floor area of the Library? | 25.5 ~ | 27.05 | 0.7 | Y | sheets / sheets-rooms-area | 0.0000 | 4.6 |
| school6 | special | What is the area of the Kitchen? | 33.5 ~ | 34.58 | 0.7 | Y | sheets / sheets-rooms-area | 0.0000 | 3.1 |
| school7 | special | How many linear meters of baseboard are needed in the Library? | 20.5 ~ | 20.5 | 0.6 | Y | sheets / sheets-rooms-baseboard | 0.0000 | 1.2 |
| school8 | special | How many linear meters of baseboard does the Multi-Purpose Hall need? | 51 ~ | 56.9 | 0.6 | Y | sheets / sheets-rooms-baseboard | 0.0000 | 0.0 |
| slab1 | foundation | What is the area of the 150 mm slab-on-grade? | 61.69 ~ | 61.69 | 0.85 | Y | sheets / sheets-slab-area | 0.0000 | 2.0 |
| slab2 | foundation | What is the area of the 300 mm slab-on-grade with D16 bars? | 214.5 ~ | 223.87 | 0.85 | Y | sheets / sheets-slab-area | 0.0000 | 2.1 |
| slab3 | foundation | What reinforcement is specified for the 150 slab-on-grade? | D13 @ 300 | D13 @ 300 | 0.95 | Y | sheets / sheets-slab-note | 0.0000 | 2.0 |
| slab4 | foundation | What is the total length of all trenches given in the notes, in mm? | 7850 | 7.85 | 0.9 | - | sheets / sheets-slab-trench | 0.0000 | 1.7 |
| slab5 | foundation | What is the slab area by type (thickness and bars)? | D16 D13 D22 ~ | 300 mm w/ D22 @ 300: 26.9 m²; 150 mm w/ D13 @ 300: 61.7 m²;  | 0.85 | Y | sheets / sheets-slab-area-by-type | 0.0000 | 0.0 |
| pipe1 | piping | How many non-surge check valves (CV) are shown? | 5 | 5 | 0.9 | Y | sheets / sheets-piping | 0.0000 | 0.0 |
| pipe2 | piping | How many fuel pumps are on the piping plan? | 5 | 5 | 0.9 | Y | sheets / sheets-piping | 0.0000 | 0.0 |
| pipe3 | piping | How many FSCV valves are there? | 7 | 7 | 0.9 | Y | sheets / sheets-piping | 0.0000 | 0.0 |
| pipe4 | piping | What size is the suction header? | 16" | 16" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 0.1 |
| pipe5 | piping | What is the size of the pump discharge header? | 12" | 12" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 0.1 |
| pipe6 | piping | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.9 | Y | sheets / sheets-piping | 0.0000 | 0.0 |
| pipe7 | piping | How many different pipe support types (PS tags) are on this plan? | 23 | 23 | 0.6 | Y | sheets / sheets-piping | 0.0000 | 0.0 |
| pipe8 | piping | How many pipe support labels are printed on the plan? | 41 | 41 | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.1 |
| pipe9 | piping | What sizes of pipe are on this sheet? | 1" 2" 3" 4" 6" 8" 10" 12" 16" | 1", 2", 3", 4", 6", 8", 10", 12", 16" | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.1 |
| pipe10 | piping | Which other sheets does this plan reference? | M-001 M-301A M-302 M-303 M-504 MS513 S-101 | M-001, M-301A, M-302, M-303, M-504, MS513, S-101 | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.2 |
| pipe11 | piping | What does note 4 say? | MICRONIC FILTER MAY BE NECESSARY | MICRONIC FILTER MAY BE NECESSARY. SEE UFC 3-460-1, IF TRANSF | 0.75 | Y | sheets / sheets-piping | 0.0000 | 0.2 |
| pipe12 | piping | How many pressure gauges (PG) are shown? | 21 | 21 | 0.55 | Y | sheets / sheets-piping | 0.0000 | 0.2 |
| pipe13 | piping | What size is the return line? | 8" | 8" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 0.2 |

**33/34 correct**; dormitory 8/8, special 8/8, foundation 4/5, piping 13/13; API cost of the questions $0.004
