# Stoa example sheets: base0_lowres

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| dorm1 | dormitory | What is the total square footage of the second floor? | 26562 | 26562 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0001 | 7.7 |
| dorm2 | dormitory | What is the area of the west wing dormitory? | 6095 | 6095 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0002 | 7.7 |
| dorm3 | dormitory | How many dorm rooms are on the second floor? | 48 | 48 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0001 | 7.7 |
| dorm4 | dormitory | What is the total circulation area on this floor? | 4470 | 4470 | 0.75 | Y | sheets / sheets-zones-schedule | 0.0003 | 2.5 |
| dorm5 | dormitory | What is the total dormitory area of all three wings? | 18472 | 18472 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0002 | 2.0 |
| dorm6 | dormitory | What is the total common space area? | 4479 | 4479 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0002 | 2.0 |
| dorm7 | dormitory | What is the overall length of the building? | 323'-4" | 323'-4" | 0.9 | Y | sheets / sheets-zones-dimension | 0.0000 | 0.3 |
| dorm8 | dormitory | How much floor area is coloured as 2nd floor common area (pink) on the plan? | 4479 ~ | 4479 | 0.75 | Y | sheets / sheets-zones-schedule | 0.0004 | 5.9 |
| school1 | special | How many doors are shown on this floor plan? | 114 ~ | 108 doors (+11 closet doors not counted) | 0.6 | Y | sheets / sheets-openings-yolo | 0.0000 | 11.6 |
| school2 | special | How many windows are shown on this floor plan? | 101 ~ | 77 | 0.5 | - | sheets / sheets-openings-yolo | 0.0000 | 5.1 |
| school3 | special | How many secondary classrooms are on this level? | 8 | (abstain; guess 3) | 0.223 | - | sheets -> generic / generic-ground-haiku | 0.0010 | 10.8 |
| school4 | special | What is the floor area of the Multi-Purpose Hall? | 240 ~ | (abstain) | 0.0 | - | sheets / sheets-rooms-ask | 0.0017 | 12.6 |
| school5 | special | What is the floor area of the Library? | 25.5 ~ | (abstain) | 0.0 | - | sheets / sheets-rooms-ask | 0.0017 | 6.3 |
| school6 | special | What is the area of the Kitchen? | 33.5 ~ | 12.8 | 0.31 | - | sheets / sheets-rooms-area-sum | 0.0017 | 0.3 |
| school7 | special | How many linear meters of baseboard are needed in the Library? | 20.5 ~ | (abstain) | 0.0 | - | sheets / sheets-rooms-ask | 0.0017 | 5.0 |
| school8 | special | How many linear meters of baseboard does the Multi-Purpose Hall need? | 51 ~ | 63 | 0.3 | - | sheets -> generic / generic-read-haiku | 0.0024 | 5.1 |
| slab1 | foundation | What is the area of the 150 mm slab-on-grade? | 61.69 ~ | 61.81 | 0.7 | Y | sheets / sheets-slab-area | 0.0024 | 2.1 |
| slab2 | foundation | What is the area of the 300 mm slab-on-grade with D16 bars? | 214.5 ~ | 216.38 | 0.7 | Y | sheets / sheets-slab-area | 0.0024 | 0.3 |
| slab3 | foundation | What reinforcement is specified for the 150 slab-on-grade? | D13 @ 300 | D13 @ 300 | 0.8 | Y | sheets / sheets-slab-note | 0.0024 | 0.3 |
| slab4 | foundation | What is the total length of all trenches given in the notes, in mm? | 7850 | 7850.0 | 0.75 | Y | sheets / sheets-slab-trench | 0.0024 | 0.3 |
| slab5 | foundation | What is the slab area by type (thickness and bars)? | D16 D13 D22 ~ | 300 mm w/ D22 @ 300: 26.5 m²; 150 mm w/ D13 @ 300: 61.8 m²;  | 0.7 | Y | sheets / sheets-slab-area-by-type | 0.0024 | 0.3 |
| pipe1 | piping | How many non-surge check valves (CV) are shown? | 5 | 5 | 0.85 | Y | sheets / sheets-piping | 0.0129 | 2.1 |
| pipe2 | piping | How many fuel pumps are on the piping plan? | 5 | 5 | 0.85 | Y | sheets / sheets-piping | 0.0004 | 2.4 |
| pipe3 | piping | How many FSCV valves are there? | 7 | 6 | 0.6 | - | sheets / sheets-piping | 0.0005 | 3.3 |
| pipe4 | piping | What size is the suction header? | 16" | 16" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 1.4 |
| pipe5 | piping | What is the size of the pump discharge header? | 12" | 12" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 1.1 |
| pipe6 | piping | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.85 | Y | sheets / sheets-piping | 0.0008 | 5.2 |
| pipe7 | piping | How many different pipe support types (PS tags) are on this plan? | 23 | 23 | 0.6 | Y | sheets / sheets-piping | 0.0000 | 0.6 |
| pipe8 | piping | How many pipe support labels are printed on the plan? | 41 | 40 | 0.7 | - | sheets / sheets-piping | 0.0000 | 0.8 |
| pipe9 | piping | What sizes of pipe are on this sheet? | 1" 2" 3" 4" 6" 8" 10" 12" 16" | 2", 4", 6", 8", 10", 12", 16" | 0.7 | - | sheets / sheets-piping | 0.0000 | 1.0 |
| pipe10 | piping | Which other sheets does this plan reference? | M-001 M-301A M-302 M-303 M-504 MS513 S-101 | M-001, M-301A, M-302, M-303, M-504, MS513, S-101 | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.9 |
| pipe11 | piping | What does note 4 say? | MICRONIC FILTER MAY BE NECESSARY | MICRONIC FILTER MAY BE NECESSARY. SEE UFC 3-460-1, IF TRANSF | 0.75 | Y | sheets / sheets-piping | 0.0000 | 6.0 |
| pipe12 | piping | How many pressure gauges (PG) are shown? | 21 | 14 | 0.55 | - | sheets / sheets-piping | 0.0000 | 0.5 |
| pipe13 | piping | What size is the return line? | 8" | 8" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 0.7 |
| slab6 | foundation | What is the area of the 300 mm slab with D22 bars? | 26.49 ~ | 26.49 | 0.7 | Y | sheets / sheets-slab-area | 0.0024 | 0.3 |
| slab7 | foundation | What is the total slab area? | 302.7 ~ | 304.68 | 0.7 | Y | sheets / sheets-slab-area | 0.0024 | 0.3 |
| slab8 | foundation | How many control joint panels does the 300 mm slab with D16 bars have? | 6 | 6 | 0.63 | Y | sheets / sheets-slab-cj | 0.0024 | 0.3 |
| slab9 | foundation | What is the top of slab elevation of the D16 slab? | 9400 | 300 mm w/ D16 @ 300: top of slab EL. 9400 | 0.8 | Y | sheets / sheets-slab-note | 0.0024 | 0.6 |
| slab10 | foundation | How long is the pump control panel trench in mm? | 1825 | 1825.0 | 0.8 | Y | sheets / sheets-slab-trench | 0.0024 | 0.5 |
| slab11 | foundation | How many sumps are there? | 1 | 1 | 0.7 | Y | sheets / sheets-slab-sump | 0.0024 | 0.3 |
| slab12 | foundation | What bars are in the genset slab with D22? | D22 @ 300 | D22 @ 300 | 0.8 | Y | sheets / sheets-slab-note | 0.0024 | 0.2 |

**30/41 correct**; dormitory 8/8, special 1/8, foundation 12/12, piping 9/13; API cost of the questions $0.055
