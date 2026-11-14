# Stoa example sheets: after_png2500

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| dorm1 | dormitory | What is the total square footage of the second floor? | 26562 | 26562 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0006 | 9.5 |
| dorm2 | dormitory | What is the area of the west wing dormitory? | 6095 | 6095 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0006 | 9.6 |
| dorm3 | dormitory | How many dorm rooms are on the second floor? | 48 | 48 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0007 | 10.1 |
| dorm4 | dormitory | What is the total circulation area on this floor? | 4470 | 4470 | 0.75 | Y | sheets / sheets-zones-schedule | 0.0007 | 9.6 |
| dorm5 | dormitory | What is the total dormitory area of all three wings? | 18472 | 18472 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0007 | 3.1 |
| dorm6 | dormitory | What is the total common space area? | 4479 | 4479 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0006 | 2.5 |
| dorm7 | dormitory | What is the overall length of the building? | 323'-4" | 323 | 0.55 | - | sheets -> generic / generic-read-haiku | 0.0013 | 4.6 |
| dorm8 | dormitory | How much floor area is coloured as 2nd floor common area (pink) on the plan? | 4479 ~ | 4479 | 0.5 | Y | sheets / sheets-zones-schedule | 0.0008 | 5.8 |
| school1 | special | How many doors are shown on this floor plan? | 128 ~ | 127 | 0.3 | Y | sheets / sheets-arch-detector-door | 0.0000 | 3.1 |
| school2 | special | How many windows are shown on this floor plan? | 101 ~ | 99 | 0.3 | Y | sheets / sheets-arch-detector-window | 0.0000 | 3.7 |
| school3 | special | How many secondary classrooms are on this level? | 8 | 8 | 0.694 | Y | sheets -> generic / generic-ground-haiku | 0.0021 | 12.5 |
| school4 | special | What is the floor area of the Multi-Purpose Hall? | 240 ~ | Total 1490 m² net over 124 rooms. Servety and / Store 294.6  | 0.55 | - | sheets / sheets-rooms-area-list | 0.0041 | 39.6 |
| school5 | special | What is the floor area of the Library? | 25.5 ~ | 26.53 | 0.7 | Y | sheets / sheets-rooms-area | 0.0041 | 38.9 |
| school6 | special | What is the area of the Kitchen? | 33.5 ~ | (abstain) | 0.0 | - | sheets / sheets-arch-noroom | 0.0001 | 47.0 |
| school7 | special | How many linear meters of baseboard are needed in the Library? | 20.5 ~ | 17.1 | 0.6 | - | sheets / sheets-rooms-baseboard | 0.0041 | 28.0 |
| school8 | special | How many linear meters of baseboard does the Multi-Purpose Hall need? | 51 ~ | 1085.2 | 0.55 | - | sheets / sheets-rooms-baseboard | 0.0041 | 0.0 |
| slab1 | foundation | What is the area of the 150 mm slab-on-grade? | 61.69 ~ | 61.69 | 0.56 | Y | sheets / sheets-slab-area | 0.0058 | 18.1 |
| slab2 | foundation | What is the area of the 300 mm slab-on-grade with D16 bars? | 214.5 ~ | (abstain) | 0.0 | - | sheets / sheets-none | 0.0000 | 22.5 |
| slab3 | foundation | What reinforcement is specified for the 150 slab-on-grade? | D13 @ 300 | D13 @ 300 | 0.8 | Y | sheets / sheets-slab-note | 0.0062 | 17.2 |
| slab4 | foundation | What is the total length of all trenches given in the notes, in mm? | 7850 | 7.85 | 0.75 | - | sheets / sheets-slab-trench | 0.0013 | 11.2 |
| slab5 | foundation | What is the slab area by type (thickness and bars)? | D16 D13 D22 ~ | untyped: 27.1 m²; 150 mm w/ D13 @ 300: 61.8 m²; 300 mm w/ D2 | 0.56 | - | sheets / sheets-slab-area-by-type | 0.0062 | 0.0 |
| pipe1 | piping | How many non-surge check valves (CV) are shown? | 5 | 5 | 0.85 | Y | sheets / sheets-piping | 0.0359 | 48.3 |
| pipe2 | piping | How many fuel pumps are on the piping plan? | 5 | 5 | 0.85 | Y | sheets / sheets-piping | 0.0382 | 49.4 |
| pipe3 | piping | How many FSCV valves are there? | 7 | (abstain) | 0.0 | - | - / timeout | 0.0000 | 75.0 |
| pipe4 | piping | What size is the suction header? | 16" | 16" | 0.8 | Y | sheets / sheets-piping | 0.0430 | 56.7 |
| pipe5 | piping | What is the size of the pump discharge header? | 12" | 12" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 0.2 |
| pipe6 | piping | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.85 | Y | sheets / sheets-piping | 0.0000 | 0.0 |
| pipe7 | piping | How many different pipe support types (PS tags) are on this plan? | 23 | 23 | 0.6 | Y | sheets / sheets-piping | 0.0000 | 0.1 |
| pipe8 | piping | How many pipe support labels are printed on the plan? | 41 | 41 | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.1 |
| pipe9 | piping | What sizes of pipe are on this sheet? | 1" 2" 3" 4" 6" 8" 10" 12" 16" | 1", 2", 3", 4", 6", 8", 10", 12", 16" | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.2 |
| pipe10 | piping | Which other sheets does this plan reference? | M-001 M-301A M-302 M-303 M-504 MS513 S-101 | M-001, M-301A, M-302, M-303, M-504, MS513, S-101 | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.2 |
| pipe11 | piping | What does note 4 say? | MICRONIC FILTER MAY BE NECESSARY | SYSTEMS OTHER THAN 2400 GPM SHALL HAVE PIPING RESIZED PER SU | 0.75 | - | sheets / sheets-piping | 0.0000 | 0.2 |
| pipe12 | piping | How many pressure gauges (PG) are shown? | 21 | 20 | 0.55 | - | sheets / sheets-piping | 0.0000 | 0.1 |
| pipe13 | piping | What size is the return line? | 8" | 8" | 0.8 | Y | sheets / sheets-piping | 0.0000 | 0.3 |

**23/34 correct**; dormitory 7/8, special 4/8, foundation 2/5, piping 10/13; API cost of the questions $0.161
