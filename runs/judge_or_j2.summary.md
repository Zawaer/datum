# Judge run `or_j2` (code 428adfb)

| form | strict | lenient (15 %) | mean s | $ |
|---|---|---|---|---|
| lowres | 8/13 | 8/13 | 8.4 | 0.012 |
| png2500 | 10/13 | 11/13 | 7.2 | 0.009 |
| pdf | 8/13 | 10/13 | 8.5 | 0.005 |
| scanpdf | 10/13 | 10/13 | 10.3 | 0.066 |
| roughscan | 6/13 | 6/13 | 9.5 | 0.010 |

**all forms: 42/65 strict**

By sheet: archA101F 6/10, dormA7 11/15, school00 20/35, schoolL01 5/5

By category: area-dims 3/5, area-multi-room-hard 0/5, area-room 5/5, area-sum 3/5, baseboard-hard 0/5, doors-count 12/15, rooms+area 4/5, rooms-count 10/15, trick 5/5

| id | sheet | lang | question | gold | lowres | png2500 | pdf | scanpdf | roughscan | method (hires) | ev | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| j19 | school00 | fi | Montako luokkahuonetta tässä kerroksessa on? | 8 | - 16 | - 7 | Y 8 | Y 8 | - (abstain; guess 8) | generic-ground-haiku | 16 | 22.8 |
| j20 | school00 | sv | Hur många grupprum finns det på plan 00? | 10 | - 0 | Y 10 | Y 10 | Y 10 | - (abstain; guess 9) | generic-ground-haiku | 0 | 18.8 |
| j21 | school00 | fi | Paljonko jalkalistaa tarvitaan luokkahuoneisiin? | 265 ~ | - 78.7 | ~ 239.4 | ~ 225.7 | - 201.9 | - 135.5 | sheets-rooms-baseboard | 16 | 4.7 |
| j22 | school00 | en | How many m2 of tiling for all WCs? | 31 ~ | - 2.64 | - 23.2 | - 19.0 | - 14.5 | - 8.53 | sheets-rooms-area | 3 | 0.0 |
| j23 | school00 | en | Floor area of the Multi-Purpose Hall? | 243 ~ | Y 245.66 | Y 245.91 | Y 244.77 | Y 245.7 | Y 246.08 | sheets-rooms-area | 3 | 0.0 |
| j24 | school00 | en | How many doors open into the Multi-Purpose Hall? | 8 | Y 9 | Y 8 | Y 8 | Y 8 | Y 8 | sheets-openings-room | 10 | 0.0 |
| t04 | school00 | en | What is the U-value of the external walls? | not shown | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | Y (abstain) | sheets-none | 0 | 2.3 |
| j31 | dormA7 | fi | Montako makuuhuonetta moduulissa on ja mikä on yhden makuuhuoneen pint | 4 bedrooms, 189 SF each | Y Bedrooms: 4; Area of one bedroom: 189 SF | Y Bedrooms: 4; Area of one bedroom: 189 SF | - Bedrooms: 2; Area of one bedroom: 189 SF | Y Bedrooms: 4; Area of one bedroom: 189 SF | Y Bedrooms: 4; Area of one bedroom: 189 | parts:generic-ground-haiku+sheets-text-read | 5 | 18.7 |
| j32 | dormA7 | en | Total bathroom floor area in one dorm module (for tiling)? | 204 | - 102 SF | Y 204 | - 102 | Y 204 | Y 204 | sheets-text-sum | 2 | 8.2 |
| j39 | archA101F | en | How many doors does the filter building have? | 6 | Y 6 | Y 6 | Y 6 | - 5 | - 7 | sheets-openings-yolo | 9 | 1.7 |
| j40 | archA101F | en | What is the floor area of the generator room? | 26.49 | Y 26.49 | Y 26.5 | ~ 25.5 | Y 26.49 | - (abstain) | generic-read-haiku | 3 | 11.6 |
| j43 | schoolL01 | en | How many group rooms are on level 01? | 5 | Y 5 | Y 5 | Y 5 | Y 5 | Y 5 | generic-ground-haiku | 5 | 20.3 |
| j44 | dormA7 | en | How many doors are in this dormitory module? | 8 | Y 8 doors (+8 closet doors not counted) | Y 8 doors (+8 closet doors not counted) | Y 8 doors (+8 closet doors not counted) | Y 8 doors (+6 closet doors not counted) | - 9 doors (+5 closet doors not counted) | sheets-openings-yolo | 16 | 0.2 |

API cost of all asks $0.101. Y = within 5 % / exact, ~ = within 15 %, - = wrong or abstained.
