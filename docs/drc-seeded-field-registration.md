# DRC seeded field (Pawnee, Oklahoma): GPR availability, truth and registration

**Date:** 2026-09-29 · **Manifests:** `benchmark/manifests/drc-field1.targets.json`,
`drc-field2.targets.json` · **Verdict: BLOCKED** — the truth is now strong, but neither GPR
dataset is public, so nothing can be scored. No detector was run.

Statements are labelled **Verified** (read from the source), **Inferred**, **Unresolved**.

---

## 1. Public data status (Verified, 2026-09-29)

| Source | GPR? | Notes |
|---|---|---|
| Zenodo [10.5281/zenodo.19100554](https://doi.org/10.5281/zenodo.19100554) — latest version (concept 15324497; versions 15324498 of 2025-05-02, 19100554 of 2026-03-18), 27 files, 11.06 GB, **CC-BY-4.0** | **No** | Files exist only for dataset IDs 1+2, 3, 4, 11, 18, 19, 22, 23, 25, 26, 29, 30, 34. The catalogue rows for **7** (University of Maryland, GSSI 400 MHz, UtilityScanCart, Site 1, June 12-16 2023) and **13** (Binghamton, Radarteam Cobra on DJI M600, Site 2) carry **no data link and no paper link**. |
| Interactive web map, de-mine.com/webmap | **No** raw or raster GPR | `data/datasets.json` lists 7 (Field 1, `Raster: "No"`, `Vector: "Yes"`) and 13 (Field 2, `Raster: ""`); the vector layer is the human AIU interpretation per item, not radar data. |
| Baur et al. 2026, *Remote Sensing* 18(13):2182, doi 10.3390/rs18132182 | — | States "we release all 34 georeferenced datasets via Zenodo"; the Data Availability Statement points only to Zenodo 19100554 and the web map. Its "Supplemental Table 1" is not linked from the article page. |

So the paper's release claim is not borne out for the two GPR datasets in the current public
release. **Obtained: none of the GPR.** Held (scratch, not in git): the web map's `1.csv`,
`2.csv`, `3.csv`, `AIU.csv`, `datasets.json` (SHA-256 recorded in the manifests).

## 2. Field instances (Verified from the DRC's own tables, geometry measured by Subterra)

The 2026 paper: "The targets were migrated from test Site 1 to test Site 2 and later Site 3 but
maintained the same placement and configuration." Site 1 established March 2023 (data June
2023); Site 2 ~200 m SE, seeded June 2023 (most data May-June 2024); Site 3 after June 2024.

- **Same configuration — verified:** the web map's Field 1, 2 and 3 tables give the same item,
  class and depth in every one of the 150 cells.
- **Same geometry — false:** fitting the cell coordinates (WGS84 → UTM 14N) to an ideal grid:

| | column step | row step | rows run toward | fit residual (median / max) |
|---|---|---|---|---|
| Published (2023) | 2.0 m | 1.5 m | south; A1 = NW | — |
| Field 1 | 2.79 m | 1.79 m | 185° | 0.11 / 0.51 m |
| Field 2 | 1.99 m | **0.98 m** | **271°** | 0.07 / 0.24 m |
| Field 3 | — | — | — | **not a grid** (residuals to 15 m): unusable |

Field 2 is rotated ~90° from Field 1, and its A1 is the **north-east** corner: the 2023 Table 3
GCPs (which the text places "at the permanent site") lie 0.51 m from Field 2's A1 (GCP NE) and
0.40 m from F1 (GCP SE). So Table 3 belongs to Field 2 (**Inferred, strong**), and GPR dataset 7
(Field 1) and dataset 13 (Field 2) sit on different physical layouts. Each field gets its own
frame and manifest; a cart-vs-aerial comparison would be across field instances.

## 3. Target accounting

| Quantity | Value | Source |
|---|---|---|
| Grid cells | 150 (6 columns A-F × 25 rows) | 2023, 2026 papers; web map |
| Filled cells | **139** | web map Field 1 and 2; Table 2 (image) — identical |
| of which control holes | **8** (F2, F4, …, F16; hole depths 14-30 cm) | same |
| of which physical objects | **131** (E23-E25 hold 2, 3, 4 shells per the tables) | same |
| Blank cells | **11** (A14, A16, A18, A20, A22, A24, F18, F20, F22, F24, F25) | same |
| "143 items (including control holes)" | text of the 2023 and 2026 papers | does not match 139 |
| Table 1 (2023): 141 + 9 "Empty" = 150 | per-class counts differ (projectiles, 40 mm, AP/submunitions) | does not match 139 + 11 |

**Resolution of 150 vs 143:** 150 is the number of grid cells; the item tables fill 139 of them
(131 objects + 8 control holes). Neither 143 nor Table 1's 141/9 split reconciles with the
tables, so **which blank cells are documented "Empty"** ("nothing buried in this location") is
unresolved. The manifests therefore list the 8 control holes as `attested_empty_locations`
(kind `control_hole`) and the 11 blank cells as **unresolved**, not as attested empty.

Independent check: Subterra transcribed Table 2 from the 2023 paper's image before finding the
web-map tables; the two agree on every cell (item, depth, blank, control hole).

## 4. Schema extension: attested-empty locations

`benchmark.targets.AttestedEmptyLocation` (commit `3ba21ee`): kind `control_hole` (dug, left
empty, refilled; may carry `hole_depth`) or `undisturbed_empty` (documented nothing placed; no
hole depth). Justified by the 2023 paper: control holes "were dug at various depths and filled
with the goal of decoupling a signature resulting from soil displacement or disturbance from one
resulting from the items themselves". Never a false negative; with a declared
`MatchRule.control_radius`, predictions near one are reported as control responses (a subset
of the false positives, reported even when precision is gated). Unlisted ground is never
treated as attested empty.

## 5. Registration

| Item | State |
|---|---|
| Grid geometry per field | **Verified** from the DRC coordinates (table above) |
| CRS | web map: WGS84 lon/lat; manifests use EPSG:32614 (UTM 14N) |
| GCPs | 6 (Table 3, Trimble Geo7x, ±5 cm); **Inferred** Field 2 |
| How item coordinates were obtained | **Unresolved** (not stated; they imply a spacing different from the paper's) |
| Item placement tolerance | **Unresolved** (not published) |
| GSSI (7) positioning, trajectory, format | **Unavailable** — data not public |
| Cobra (13) positioning, trajectory, format | **Unavailable** — data not public |

`grid ID → physical XY` is available per field from the DRC's coordinates. `physical XY → GPR
acquisition coordinates` is impossible without the GPR files.

## 6. GSSI and Cobra data

Not public, so format, geometry, timing and positioning cannot be inspected. Ingestion readiness
from vendor knowledge only (**Inferred**): a GSSI UtilityScan exports `.DZT`, which Subterra's
existing GSSI converter reads (BAM, TU1208); a Radarteam Cobra writes its own format, which
Subterra does **not** support and must not force through another vendor's reader.

## 7. Evidence grade

Basis `seeded_placement`, **grade B** (`measurement_associated`), independent of GPR, not verified
by Subterra. Not A because: the coordinates' survey method is unstated and implies a spacing
different from the paper's; no placement tolerance is published; the depth reference point is
ambiguous (§8); and the published counts do not reconcile. A would need the per-field survey of
item positions and a statement of how depths were referenced.

## 8. Depth

Burial depth 0-20 cm (control holes to 30 cm), ruler at burial, ±1 cm. The text says "depth to
the center of mass" but the vertical ruler rested "on the uppermost surface of the item" →
`measured_to: unresolved` with open question `drc-depth-point`. The web map's `AIU.csv` also
carries a per-dataset "True Depth" that differs from the burial depth (e.g. A1: 8 cm at burial,
10 cm for dataset 1), consistent with the soil deposition the 2026 paper describes; depth truth is
therefore time-dependent. Depth-stratified detection would use the burial depth, labelled as such.

## 9. Exhaustiveness

**Not attested** → precision, false positives, F1 and false alarms per area stay gated. Every
cell is accounted for, but the published counts disagree, the 11 blanks are not documented as
empty, GCP markers lie inside the grid, and no source says the tables list every object.
Control-hole responses remain reportable (their emptiness *is* attested).

## 10. Predeclared matching rule (before any prediction exists)

Radius bands **0.25 m** and **0.45 m** (primary), `control_radius` equal to the band. Basis:
item sizes ~2.5-40 cm; coordinate fit residuals 0.07-0.11 m median; GCP accuracy ±5 cm; GPR
positioning unknown; and 0.45 m stays below half of Field 2's 0.98 m row step, so no prediction
is within reach of two cell centres along a row. Chosen now, before any Subterra prediction, and
not to be changed after seeing a score.

## 11. Published GPR baseline (descriptive only; not used to tune anything)

Baur et al. 2026: detection is **human interpretation** on the AIU index (anomaly / identifiable
/ unique identifiable). Reported: GPR is the only modality detecting buried plastic targets —
55.6% for the cart system, 18.2% for UAV GPR at current flight heights. Per-item labels exist in
the web map's `AIU.csv`; they stay out of every detection path and would only be compared,
descriptively, after a frozen blind Subterra run.

## 12. Licence

Zenodo 19100554: **CC-BY-4.0** (record metadata `license.id`). Commercial use, redistribution and
derivatives are permitted with attribution. The web-map data carry no separate licence
statement; treat as the dataset's and attribute the DRC. Any GPR files obtained by request must
have their own licence confirmed.

## 13. Data request (updates the 2026-09-29 draft to jbaur@de-mine.org)

Only what no public source provides:
1. Raw GPR for datasets 7 (GSSI 400 MHz UtilityScan cart, Field 1) and 13 (Radarteam Cobra,
   Field 2), with positioning/trajectory files and acquisition settings — the 2026 paper says
   they were released, but they are not in Zenodo 19100554 or on the web map.
2. How the web-map item coordinates were obtained, and per-item placement tolerance.
3. Whether depths are to the item's top or centre, and what the web map's "True Depth" is.
4. Which blank cells are documented "Empty", reconciling 143 / 141+9 / 139+11.
5. Positions and material of the GCP markers inside the grid.
6. The licence for the GPR files.

## 14. Sources

- Zenodo record and API: https://zenodo.org/records/19100554
- Web map and data: https://de-mine.com/webmap (`data/1.csv`, `2.csv`, `3.csv`, `AIU.csv`, `datasets.json`)
- Baur et al. 2026, https://doi.org/10.3390/rs18132182
- Baur et al. 2023, JCWD 27.3: https://www.jmu.edu/news/cisr/2023/10/273/01-273-baur.shtml

## 15. Re-verification from the sources, 2026-10-04

Network access to Zenodo and de-mine.com was available for this pass; MDPI
returned 403 to automated clients, so the paper was not re-read.

**GPR availability: unchanged, now re-verified (Verified).**

- Both versions of the concept record (15324498: 16 files; 19100554: 27
  files) and the record 19100554 `isSupplementTo` (8323244: one RGB
  orthomosaic) hold no GPR file.
- Zenodo searches (demining, seeded minefield, landmine GPR, Radarteam Cobra,
  UtilityScan, and the DRC authors) find no other DRC record. 18769571 (a
  ground/UAV GPR set) is the INGV/Salerno dataset, unrelated.
- Figshare, OSF, Harvard Dataverse and Mendeley Data return nothing relevant.
- The web map's `datasets.json`, `1.csv` and `2.csv` are byte-identical to the
  29 September copies (SHA-256 in the manifests). Its bundle loads only
  `AIU.csv`, `datasets.json` and `<field>.csv`; rasters come only from
  datasets flagged `Raster: Yes/UPLOADED`. Dataset 7 is `No`; 13 is blank.

**Who holds the data (Verified, from the catalogue and the 2026 author list).**
Dataset 7's group is "Maryland - Heidi", co-author Heidi Myers (University
of Maryland). Dataset 13's group is "Binghamton - TdS & AN", co-authors
Timothy de Smet and Alex Nikulin (Binghamton University).

**When Field 2 existed (new, Verified).**

- Zenodo 8323244 `Seeded_Minefield_June15th_Georeferenced.tif` (published
  2023-09-07) is byte-identical (MD5 `9571543dd528289729e604ab1f1d631e`,
  60,883,879 B) to 19100554 `19-1_Field2_Mavic3E_RGB_0days.tif`.
- Its EPSG:4326 footprint (−96.857272 to −96.856830 E, 36.352916 to
  36.353174 N; 3.5e-8° pixels, ~4 mm) contains **150/150 Field 2** grid
  cells, 0/150 of Field 1 and 0/150 of Field 3.
- So Field 2 was laid out and freshly seeded ("0 days") by **15 June 2023**,
  matching JCWD 2023 ("reseeded at a permanent location in June 2023").
- The web map's date for 19-1 (`June 10`, 2024, `Preburial`) contradicts both,
  so the catalogue's dates are not reliable per item.

**Consequence for dataset 13 (Unresolved).** It is catalogued Field 2,
"June 12 - 16" 2023, "Postburial". Field 2 existing in that week makes the
field label consistent, which removes the worry that 13 belongs to Field 1's
layout. But "post-burial" holds only if the flight was on or after the day
the items went in. Recorded as open question `drc-13-flight-vs-seeding`,
which blocks matching. The flight log answers it.

**Possible next step (not done).** At ~4 mm per pixel and 0 days after
burial, the 15 June image may show the disturbed soil of each burial. This
would give an image-based check of the web-map item coordinates
(`drc-coordinate-method`), independent of any radar.
