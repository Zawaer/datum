# Stoa example sheets: after_hires

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| dorm1 | dormitory | What is the total square footage of the second floor? | 26562 | 26562 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0006 | 11.0 |
| dorm2 | dormitory | What is the area of the west wing dormitory? | 6095 | 6095 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0006 | 10.9 |
| dorm3 | dormitory | How many dorm rooms are on the second floor? | 48 | 48 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0004 | 10.3 |
| dorm4 | dormitory | What is the total circulation area on this floor? | 4470 | 4470 | 0.75 | Y | sheets / sheets-zones-schedule | 0.0008 | 11.6 |
| dorm5 | dormitory | What is the total dormitory area of all three wings? | 18472 | 18472 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0007 | 3.6 |
| dorm6 | dormitory | What is the total common space area? | 4479 | 4479 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0006 | 3.4 |
| dorm7 | dormitory | What is the overall length of the building? | 323'-4" | 323 | 0.8 | - | sheets -> generic / generic-read-haiku | 0.0013 | 6.5 |
| dorm8 | dormitory | How much floor area is coloured as 2nd floor common area (pink) on the plan? | 4479 ~ | 4479 | 0.75 | Y | sheets / sheets-zones-schedule | 0.0008 | 4.1 |
| school1 | special | How many doors are shown on this floor plan? | 128 ~ | 128 | 0.65 | Y | sheets / sheets-arch-detector-door | 0.0000 | 12.2 |
| school2 | special | How many windows are shown on this floor plan? | 101 ~ | 101 | 0.65 | Y | sheets / sheets-arch-detector-window | 0.0000 | 13.4 |
| school3 | special | How many secondary classrooms are on this level? | 8 | 8 | 0.55 | Y | sheets / sheets-arch-rooms-count | 0.0000 | 14.1 |
| school4 | special | What is the floor area of the Multi-Purpose Hall? | 240 ~ | 257.99 | 0.7 | Y | sheets / sheets-rooms-area | 0.0000 | 20.0 |
| school5 | special | What is the floor area of the Library? | 25.5 ~ | 26.71 | 0.7 | Y | sheets / sheets-rooms-area | 0.0000 | 11.4 |
| school6 | special | What is the area of the Kitchen? | 33.5 ~ | 34.63 | 0.7 | Y | sheets / sheets-rooms-area | 0.0000 | 9.7 |
| school7 | special | How many linear meters of baseboard are needed in the Library? | 20.5 ~ | 20.1 | 0.6 | Y | sheets / sheets-rooms-baseboard | 0.0000 | 7.7 |
| school8 | special | How many linear meters of baseboard does the Multi-Purpose Hall need? | 51 ~ | 57.6 | 0.6 | Y | sheets / sheets-rooms-baseboard | 0.0000 | 0.0 |
| slab1 | foundation | What is the area of the 150 mm slab-on-grade? | 61.69 ~ | 61.69 | 0.7 | Y | sheets / sheets-slab-area | 0.0100 | 34.0 |
| slab2 | foundation | What is the area of the 300 mm slab-on-grade with D16 bars? | 214.5 ~ | 224.01 | 0.7 | Y | sheets / sheets-slab-area | 0.0093 | 33.9 |
| slab3 | foundation | What reinforcement is specified for the 150 slab-on-grade? | D13 @ 300 | D13 @ 300 | 0.8 | Y | sheets / sheets-slab-note | 0.0090 | 34.0 |
| slab4 | foundation | What is the total length of all trenches given in the notes, in mm? | 7850 | 13.95 | 0.75 | - | sheets / sheets-slab-trench | 0.0084 | 34.0 |
| slab5 | foundation | What is the slab area by type (thickness and bars)? | D16 D13 D22 ~ | 300 mm w/ D22 @ 300: 26.8 m²; 150 mm w/ D13 @ 300: 61.7 m²;  | 0.7 | Y | sheets / sheets-slab-area-by-type | 0.0093 | 0.0 |
| pipe1 | piping | How many non-surge check valves (CV) are shown? | 5 | 5 | 0.85 | Y | sheets / sheets-piping | 0.0000 | 0.4 |
| pipe2 | piping | How many fuel pumps are on the piping plan? | 5 | 5 | 0.85 | Y | sheets / sheets-piping | 0.0000 | 1.1 |
| pipe3 | piping | How many FSCV valves are there? | 7 | 7 | 0.85 | Y | sheets / sheets-piping | 0.0000 | 0.8 |
| pipe4 | piping | What size is the suction header? | 16" | 16" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 1.3 |
| pipe5 | piping | What is the size of the pump discharge header? | 12" | 12" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 1.2 |
| pipe6 | piping | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.85 | Y | sheets / sheets-piping | 0.0000 | 0.8 |
| ho_dorm1 | us | What is the total first floor area? | 28770 | 28770 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0007 | 9.6 |
| ho_dorm2 | us | What is the total common space area on the first floor? | 6687 | 6687 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0007 | 9.6 |
| ho_dorm3 | us | What is the third floor subtotal area, excluding the exterior stair? | 26201 | 26201 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0004 | 7.6 |
| ho_dorm4 | us | How many bedrooms are in the dormitory module? | 4 | 1576 | 0.5 | - | sheets / sheets-zones-measured | 0.0005 | 8.4 |
| ho_dorm5 | us | What is the total bedroom area in the dormitory module? | 756 | 1576 | 0.5 | - | sheets / sheets-zones-measured | 0.0005 | 2.7 |
| ho_pipe1 | us | How many FSCV valves are there? | 7 | 6 | 0.85 | - | sheets / sheets-piping | 0.0485 | 58.6 |
| ho_pipe2 | us | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.85 | Y | sheets / sheets-piping | 0.0491 | 60.6 |
| ho_slab1 | us | What size are the radial bars in the tank floor slab? | D19 | D19 (19 mm diameter bars); lengths range from 3100 to 8700 l | 0.8 | Y | sheets -> generic / generic-read-haiku | 0.0014 | 22.5 |
| ho_school1 | uk | How many secondary classrooms are on this level? | 3 | 3 | 0.55 | Y | sheets / sheets-arch-rooms-count | 0.0000 | 8.8 |
| ho_school2 | uk | How many group rooms are on this level? | 4 | 5 | 0.55 | - | sheets / sheets-arch-rooms-count | 0.0000 | 0.0 |
| pipe7 | piping | How many different pipe support types (PS tags) are on this plan? | 23 | 22 | 0.6 | - | sheets / sheets-piping | 0.0000 | 0.2 |
| pipe8 | piping | How many pipe support labels are printed on the plan? | 41 | 40 | 0.7 | - | sheets / sheets-piping | 0.0000 | 0.2 |
| pipe9 | piping | What sizes of pipe are on this sheet? | 1" 2" 3" 4" 6" 8" 10" 12" 16" | 1", 2", 3", 4", 6", 8", 10", 12", 16" | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.3 |
| pipe10 | piping | Which other sheets does this plan reference? | M-001 M-301A M-302 M-303 M-504 MS513 S-101 | M-001, M-301A, M-302, M-303, M-504, MS513, S-101 | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.4 |
| pipe11 | piping | What does note 4 say? | MICRONIC FILTER MAY BE NECESSARY | MATERIALS SHALL BE PER UFC 3-460-01. | 0.75 | - | sheets / sheets-piping | 0.0000 | 0.4 |
| pipe12 | piping | How many pressure gauges (PG) are shown? | 21 | 21 | 0.55 | Y | sheets / sheets-piping | 0.0000 | 0.1 |
| pipe13 | piping | What size is the return line? | 8" | 8" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 0.3 |
| ho_pipe3 | us | Which other sheets does this plan reference? | M-001 M-301B M-302 M-303 M-504 MS513 S-101 | M-001, M-301B, M-302, M-303, M-504, MS513, S-101 | 0.7 | Y | sheets / sheets-piping | 0.0475 | 59.3 |

**36/45 correct**; dormitory 7/8, special 8/8, foundation 4/5, piping 10/13, held-out us 6/9, held-out uk 1/2; API cost of the questions $0.201
