# Stoa example sheets by input form: v10 (overnight) vs v9 / v9c

Code d4d056d; local server :3186, fresh caches, one form at a time; examples split (41 questions per form), re-scored with the current golds (school1 = 114).

| form | before | v10 | improved | regressed | by sheet (v10) |
|---|---|---|---|---|---|
| hires (v9 -> v10) | 37/41 | 41/41 | school2, pipe7, pipe8, pipe11 | - | dormitory 8/8, special 8/8, foundation 12/12, piping 13/13 |
| pdf (v9 -> v10) | 40/41 | 41/41 | school2 | - | dormitory 8/8, special 8/8, foundation 12/12, piping 13/13 |
| png2500 (v9c -> v10) | 38/41 | 39/41 | school2, pipe12 | pipe8 | dormitory 8/8, special 8/8, foundation 12/12, piping 11/13 |
| lowres (v9c -> v10) | 31/41 | 38/41 | school2, school3, school4, school5, school6, school8, pipe3 | - | dormitory 8/8, special 7/8, foundation 12/12, piping 11/13 |
| scanpdf (v9c -> v10) | 37/41 | 39/41 | dorm8, school2, pipe11 | pipe8 | dormitory 8/8, special 8/8, foundation 12/12, piping 11/13 |
| scanrough (v9c -> v10) | 33/41 | 39/41 | dorm7, school2, school3, slab1, pipe12, slab6, slab7 | pipe10 | dormitory 8/8, special 8/8, foundation 12/12, piping 11/13 |
| **all** | 216/246 | 237/246 | | | |

Still wrong in v10:

- png2500 pipe8: How many pipe support labels are printed on the plan? -> 43 (gold 41)
- png2500 pipe11: What does note 4 say? -> MICRONIC FILTER MAY BE NECE IF TRANSFER LINE IS FR (gold MICRONIC FILTER MAY BE NECESSARY)
- lowres school7: How many linear meters of baseboard are needed in the Librar -> None (gold 20.5)
- lowres pipe8: How many pipe support labels are printed on the plan? -> 46 (gold 41)
- lowres pipe12: How many pressure gauges (PG) are shown? -> 20 (gold 21)
- scanpdf pipe8: How many pipe support labels are printed on the plan? -> 42 (gold 41)
- scanpdf pipe12: How many pressure gauges (PG) are shown? -> 22 (gold 21)
- scanrough pipe10: Which other sheets does this plan reference? -> M-001, M-301A, M-302, M-303, MS513, S-101 (gold M-001 M-301A M-302 M-303 M-504 MS513 S-101)
- scanrough pipe11: What does note 4 say? -> MICRONIC FILTEB MAY BE NECESS IF TRANSFER E IS FRO (gold MICRONIC FILTER MAY BE NECESSARY)
