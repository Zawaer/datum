# Stoa example sheets: or3ho

| id | sheet | question | gold | answer | conf | ok | route / method | $ | s |
|---|---|---|---|---|---|---|---|---|---|
| ho_dorm1 | us | What is the total first floor area? | 28770 | 28770 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0004 | 15.6 |
| ho_dorm2 | us | What is the total common space area on the first floor? | 6687 | 28770 | 0.9 | - | sheets / sheets-zones-schedule | 0.0008 | 16.2 |
| ho_dorm3 | us | What is the third floor subtotal area, excluding the exterior stair? | 26201 | 26201 | 0.9 | Y | sheets / sheets-zones-schedule | 0.0006 | 11.6 |
| ho_dorm4 | us | How many bedrooms are in the dormitory module? | 4 | 4 | 0.625 | Y | sheets -> generic / generic-ground-haiku | 0.0024 | 21.2 |
| ho_dorm5 | us | What is the total bedroom area in the dormitory module? | 756 | 756 | 0.8 | Y | sheets -> generic / generic-read-haiku | 0.0014 | 18.8 |
| ho_pipe1 | us | How many FSCV valves are there? | 7 | 7 | 0.85 | Y | sheets / sheets-piping | 0.0000 | 1.0 |
| ho_pipe2 | us | How many filter separators (FSI and FSR) are shown? | 7 | 7 | 0.85 | Y | sheets / sheets-piping | 0.0000 | 0.8 |
| ho_slab1 | us | What size are the radial bars in the tank floor slab? | D19 | D19 | 0.8 | Y | sheets -> generic / generic-read-haiku | 0.0015 | 24.0 |
| ho_school1 | uk | How many secondary classrooms are on this level? | 3 | 3 | 0.55 | Y | sheets / sheets-arch-rooms-count | 0.0000 | 11.5 |
| ho_school2 | uk | How many group rooms are on this level? | 5 | 5 | 0.55 | Y | sheets / sheets-arch-rooms-count | 0.0000 | 8.2 |
| ho_pipe3 | us | Which other sheets does this plan reference? | M-001 M-301B M-302 M-303 M-504 MS513 S-101 | M-001, M-301B, M-302, M-303, M-504, MS513, S-101 | 0.7 | Y | sheets / sheets-piping | 0.0000 | 0.5 |

**10/11 correct**; held-out us 8/9, held-out uk 2/2; API cost of the questions $0.007
