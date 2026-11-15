# Stoa example sheets: bl_s2_hires

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| dorm1 | dormitory | What is the total square footage of the second floor? | 26562 | 26562 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0002 | 12.1 |
| dorm2 | dormitory | What is the area of the west wing dormitory? | 6095 | 6095 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0000 | 11.5 |
| dorm3 | dormitory | How many dorm rooms are on the second floor? | 48 | 48 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0000 | 11.4 |
| dorm4 | dormitory | What is the total circulation area on this floor? | 4470 | 4470 | 0.75 | Y | sheets / sheets-zones-schedule | 0.0003 | 2.5 |
| dorm5 | dormitory | What is the total dormitory area of all three wings? | 18472 | 18472 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0003 | 1.8 |
| dorm6 | dormitory | What is the total common space area? | 4479 | 4479 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0002 | 1.2 |
| dorm7 | dormitory | What is the overall length of the building? | 323'-4" | 323'-4" | 0.9 | Y | sheets / sheets-zones-dimension | 0.0001 | 5.6 |
| dorm8 | dormitory | How much floor area is coloured as 2nd floor common area (pink) on the plan? | 4479 ~ | 4479 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0003 | 2.5 |
| school1 | special | How many doors are shown on this floor plan? | 114 ~ | 109 doors (+13 closet doors not counted) | 0.8 | Y | sheets / sheets-openings-cv | 0.0000 | 8.9 |
| school2 | special | How many windows are shown on this floor plan? | 101 ~ | 102 windows (67 in outside walls + 35 internal glazed panels | 0.8 | Y | sheets / sheets-openings-cv | 0.0000 | 6.9 |
| school3 | special | How many secondary classrooms are on this level? | 8 | 8 | 0.55 | Y | sheets / sheets-arch-rooms-count | 0.0000 | 24.9 |
| school4 | special | What is the floor area of the Multi-Purpose Hall? | 240 ~ | 244.88 | 0.7 | Y | sheets / sheets-rooms-area | 0.0000 | 17.4 |
| school5 | special | What is the floor area of the Library? | 25.5 ~ | 26.44 | 0.7 | Y | sheets / sheets-rooms-area | 0.0000 | 17.4 |
| school6 | special | What is the area of the Kitchen? | 33.5 ~ | 34.64 | 0.7 | Y | sheets / sheets-rooms-area | 0.0000 | 0.2 |
| school7 | special | How many linear meters of baseboard are needed in the Library? | 20.5 ~ | 19.6 | 0.6 | Y | sheets / sheets-rooms-baseboard | 0.0000 | 0.3 |
| school8 | special | How many linear meters of baseboard does the Multi-Purpose Hall need? | 51 ~ | 50.4 | 0.6 | Y | sheets / sheets-rooms-baseboard | 0.0000 | 0.3 |
| slab1 | foundation | What is the area of the 150 mm slab-on-grade? | 61.69 ~ | 61.69 | 0.7 | Y | sheets / sheets-slab-area | 0.0032 | 3.0 |
| slab2 | foundation | What is the area of the 300 mm slab-on-grade with D16 bars? | 214.5 ~ | 217.19 | 0.7 | Y | sheets / sheets-slab-area | 0.0032 | 3.2 |
| slab3 | foundation | What reinforcement is specified for the 150 slab-on-grade? | D13 @ 300 | D13 @ 300 | 0.8 | Y | sheets / sheets-slab-note | 0.0032 | 0.2 |
| slab4 | foundation | What is the total length of all trenches given in the notes, in mm? | 7850 | 7850.0 | 0.75 | Y | sheets / sheets-slab-trench | 0.0032 | 0.4 |
| slab5 | foundation | What is the slab area by type (thickness and bars)? | D16 D13 D22 ~ | 300 mm w/ D22 @ 300: 26.5 m²; 150 mm w/ D13 @ 300: 61.7 m²;  | 0.7 | Y | sheets / sheets-slab-area-by-type | 0.0032 | 0.4 |
| pipe1 | piping | How many non-surge check valves (CV) are shown? | 5 | 5 | 0.85 | Y | sheets / sheets-piping | 0.0122 | 1.5 |
| pipe2 | piping | How many fuel pumps are on the piping plan? | 5 | 5 | 0.85 | Y | sheets / sheets-piping | 0.0000 | 1.3 |
| pipe3 | piping | How many FSCV valves are there? | 7 | 7 | 0.85 | Y | sheets / sheets-piping | 0.0000 | 1.0 |
| pipe4 | piping | What size is the suction header? | 16" | 16" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 1.2 |
| pipe5 | piping | What is the size of the pump discharge header? | 12" | 12" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 0.9 |
| pipe6 | piping | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.85 | Y | sheets / sheets-piping | 0.0000 | 1.5 |
| ho_dorm1 | us | What is the total first floor area? | 28770 | 28770 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0002 | 14.2 |
| ho_dorm2 | us | What is the total common space area on the first floor? | 6687 | 6687 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0002 | 14.1 |
| ho_dorm3 | us | What is the third floor subtotal area, excluding the exterior stair? | 26201 | 26201 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0002 | 7.2 |
| ho_dorm4 | us | How many bedrooms are in the dormitory module? | 4 | 4 | 0.75 | Y | sheets -> generic / generic-ground-haiku | 0.0009 | 13.1 |
| ho_dorm5 | us | What is the total bedroom area in the dormitory module? | 756 | 756 | 0.8 | Y | sheets -> generic / generic-read-haiku | 0.0005 | 7.1 |
| ho_pipe1 | us | How many FSCV valves are there? | 7 | 7 | 0.85 | Y | sheets / sheets-piping | 0.0131 | 0.6 |
| ho_pipe2 | us | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.85 | Y | sheets / sheets-piping | 0.0000 | 0.7 |
| ho_slab1 | us | What size are the radial bars in the tank floor slab? | D19 | D19 RADIAL BARS | 0.42 | Y | sheets / sheets-slab-bars | 0.0023 | 0.2 |
| ho_school1 | uk | How many secondary classrooms are on this level? | 3 | 3 | 0.55 | Y | sheets / sheets-arch-rooms-count | 0.0000 | 16.4 |
| ho_school2 | uk | How many group rooms are on this level? | 5 | 5 | 0.55 | Y | sheets / sheets-arch-rooms-count | 0.0000 | 24.4 |
| pipe7 | piping | How many different pipe support types (PS tags) are on this plan? | 23 | 23 | 0.6 | Y | sheets / sheets-piping | 0.0106 | 7.1 |
| pipe8 | piping | How many pipe support labels are printed on the plan? | 41 | 41 | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.7 |
| pipe9 | piping | What sizes of pipe are on this sheet? | 1" 2" 3" 4" 6" 8" 10" 12" 16" | 1", 2", 3", 4", 6", 8", 10", 12", 16" | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.4 |
| pipe10 | piping | Which other sheets does this plan reference? | M-001 M-301A M-302 M-303 M-504 MS513 S-101 | M-001, M-301A, M-302, M-303, M-504, MS513, S-101 | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.4 |
| pipe11 | piping | What does note 4 say? | MICRONIC FILTER MAY BE NECESSARY | MICRONIC FILTER MAY BE NECESSARY. IF TRANSFER LINE IS FROM O | 0.75 | Y | sheets / sheets-piping | 0.0000 | 6.9 |
| pipe12 | piping | How many pressure gauges (PG) are shown? | 21 | 21 | 0.55 | Y | sheets / sheets-piping | 0.0112 | 8.0 |
| pipe13 | piping | What size is the return line? | 8" | 8" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 0.5 |
| ho_pipe3 | us | Which other sheets does this plan reference? | M-001 M-301B M-302 M-303 M-504 MS513 S-101 | M-001, M-301B, M-302, M-303, M-504, MS513, S-101 | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.7 |
| slab6 | foundation | What is the area of the 300 mm slab with D22 bars? | 26.49 ~ | 26.49 | 0.7 | Y | sheets / sheets-slab-area | 0.0032 | 0.2 |
| slab7 | foundation | What is the total slab area? | 302.7 ~ | 305.37 | 0.7 | Y | sheets / sheets-slab-area | 0.0032 | 0.2 |
| slab8 | foundation | How many control joint panels does the 300 mm slab with D16 bars have? | 6 | 6 | 0.63 | Y | sheets / sheets-slab-cj | 0.0032 | 0.2 |
| slab9 | foundation | What is the top of slab elevation of the D16 slab? | 9400 | 300 mm w/ D16 @ 300: top of slab EL. 9400 | 0.8 | Y | sheets / sheets-slab-note | 0.0032 | 0.2 |
| slab10 | foundation | How long is the pump control panel trench in mm? | 1825 | 1825.0 | 0.8 | Y | sheets / sheets-slab-trench | 0.0032 | 0.2 |
| slab11 | foundation | How many sumps are there? | 1 | 1 | 0.7 | Y | sheets / sheets-slab-sump | 0.0032 | 0.2 |
| slab12 | foundation | What bars are in the genset slab with D22? | D22 @ 300 | D22 @ 300 | 0.8 | Y | sheets / sheets-slab-note | 0.0032 | 0.2 |

**52/52 correct**; dormitory 8/8, special 8/8, foundation 12/12, piping 13/13, held-out us 9/9, held-out uk 2/2; API cost of the questions $0.091
