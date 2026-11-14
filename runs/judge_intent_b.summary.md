# Judge run `intent_b` (code 824b94f)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 4/5 | 4/5 | 7.1 | 0.001 |
| png2500 | 3/5 | 3/5 | 5.1 | 0.001 |
| scanpdf | 2/5 | 2/5 | 10.4 | 0.001 |

**all forms: 9/15 strict**

By sheet: dormA1 3/3, dormA2 1/3, pipeM101A 3/3, pipeM101F 2/3, school00 0/3

By category: area-convert 3/3, area-multi-room-hard 0/3, count-legend 1/3, piping-count+size 3/3, piping-equipment 2/3

| id | sheet | lang | question | gold | lowres | png2500 | scanpdf | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|---|---|
| j03 | dormA2 | fi | Montako esteetöntä (ABA) asuntolahuonetta tässä kerroksessa on? | 2 | Y 2 | - 4 | - (abstain; guess 2) | generic-ground-haiku | 2 | 17.8 |
| j13 | pipeM101A | en | How many check valves and what size is the discharge header? | 5 check valves (CV-1..CV-5); 1 | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | Y Check valves: 5; Discharge header size:  | parts:sheets-piping+sheets-piping | 7 | 0.5 |
| j22 | school00 | en | How many m2 of tiling for all WCs? | 31 ~ | - 1467.0 | - 1495.4 | - Total 1459 m² net over 97 rooms. Purpose | sheets-rooms-area-total | 86 | 5.8 |
| j27 | dormA1 | fi | Paljonko yhteistiloja (common space) ensimmäisessä kerroksessa on neli | 406.8 | Y 621.2 | Y 621.2 | Y 621.2 | sheets-zones-schedule | 1 | 8.9 |
| j35 | pipeM101F | fi | Kuinka suuri paineiskusäiliö (surge tank) on? | 150 L | Y 150 liters | Y 150 liters | - 250mm | sheets-piping | 2 | 2.4 |

API cost of all asks $0.003. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
