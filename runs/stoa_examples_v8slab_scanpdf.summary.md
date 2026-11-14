# Stoa example sheets: v8slab_scanpdf

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| slab1 | foundation | What is the area of the 150 mm slab-on-grade? | 61.69 ~ | 60.58 | 0.59 | Y | sheets / sheets-slab-area | 0.0138 | 49.8 |
| slab2 | foundation | What is the area of the 300 mm slab-on-grade with D16 bars? | 214.5 ~ | (abstain) | 0.0 | - | sheets / sheets-slab-timeout | 0.0000 | 56.4 |
| slab3 | foundation | What reinforcement is specified for the 150 slab-on-grade? | D13 @ 300 | D13 @ 300 | 0.8 | Y | sheets / sheets-slab-note | 0.0127 | 49.8 |
| slab4 | foundation | What is the total length of all trenches given in the notes, in mm? | 7850 | 7850.0 | 0.75 | Y | sheets / sheets-slab-trench | 0.0127 | 0.1 |
| slab5 | foundation | What is the slab area by type (thickness and bars)? | D16 D13 D22 ~ | 300 mm w/ D22 @ 300: 26.8 m²; 150 mm w/ D13 @ 300: 60.6 m²;  | 0.59 | Y | sheets / sheets-slab-area-by-type | 0.0127 | 0.1 |
| slab6 | foundation | What is the area of the 300 mm slab with D22 bars? | 26.49 ~ | 26.77 | 0.59 | Y | sheets / sheets-slab-area | 0.0127 | 0.1 |
| slab7 | foundation | What is the total slab area? | 302.7 ~ | 308.42 | 0.59 | Y | sheets / sheets-slab-area | 0.0127 | 0.2 |
| slab8 | foundation | How many control joint panels does the 300 mm slab with D16 bars have? | 6 | 6 | 0.63 | Y | sheets / sheets-slab-cj | 0.0127 | 0.2 |
| slab9 | foundation | What is the top of slab elevation of the D16 slab? | 9400 | 300 mm w/ D16 @ 300: top of slab EL. 9400 | 0.8 | Y | sheets / sheets-slab-note | 0.0127 | 0.0 |
| slab10 | foundation | How long is the pump control panel trench in mm? | 1825 | 1825.0 | 0.8 | Y | sheets / sheets-slab-trench | 0.0127 | 0.1 |
| slab11 | foundation | How many sumps are there? | 1 | 1 | 0.7 | Y | sheets / sheets-slab-sump | 0.0127 | 0.1 |
| slab12 | foundation | What bars are in the genset slab with D22? | D22 @ 300 | D22 @ 300 | 0.8 | Y | sheets / sheets-slab-note | 0.0127 | 0.0 |

**11/12 correct**; foundation 11/12; API cost of the questions $0.141
