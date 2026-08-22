# First multi-modal subsurface fusion dataset — selection and readiness

**Question.** Which real, openly available, scientifically controlled dataset
combination can demonstrate Subterra's intended architecture —

```
GPR ───────────────┐
                    │
DEM ────────────────┤
                    │
Seismic ────────────┤──► Spatial/Temporal Fusion
                    │
Borehole ───────────┘
                              │
                              ▼
                     Unified subsurface model
                              │
                   ┌──────────┴──────────┐
                   ▼                     ▼
            anomaly detection     3D reconstruction
```

— and how far can that combination actually be taken with what Subterra holds
today?

**No platform state was changed for this document.** No declaration,
readiness state, converter, dataset record, schema or production default was
touched. Section 12 cites an existing, independently reproduced test result;
nothing new was implemented, because nothing new was needed — see §12 for why.

---

## 1. Candidate datasets considered

Everything Subterra holds or has audited, drawn from
[`dataset-inventory.md`](dataset-inventory.md),
[`cross-dataset-evidence-audit.md`](cross-dataset-evidence-audit.md),
[`external-calibration-dataset-audit.md`](external-calibration-dataset-audit.md),
and the TestUM stage sequence
([`testum-evidence-audit.md`](testum-evidence-audit.md) →
[`testum-raw-data-validation.md`](testum-raw-data-validation.md) →
[`testum-borehole-depth-axis-audit.md`](testum-borehole-depth-axis-audit.md) →
[`testum-air-warr-t0-experiment.md`](testum-air-warr-t0-experiment.md)):

| Dataset | Modality | On disk | Same-site partner held? | Verdict for this stage |
|---|---|---|---|---|
| `4tu-nl-utility` | GPR (SEG-Y, 759 files, 13 sites) | ✅ acquired, CC0 | **`ahn-dtm-05m`, all 13 sites** | **selected — GPR half** |
| `ahn-dtm-05m` | DEM (AHN DTM 0.5 m, GeoTIFF, 13 site windows) | ✅ acquired, CC0 | `4tu-nl-utility` | **selected — DEM half** |
| TestUM (PANGAEA 971978) | Borehole GPR (crosshole + reflection) | ✅ 2 traces + 26 calibration files acquired, CC-BY | none held | strongest borehole evidence held; **cross-site**, kept separate (§5) |
| `tu1208-ifsttar` | GPR (67 files, 3 vendors) | ✅ acquired, CC-BY | none | no coordinates at all — cannot be spatially fused with anything |
| `bam-concrete-gpr` | GPR (concrete specimens) | ✅ acquired, CC0 | none | lab specimen, no site coordinates |
| `hillside-lancaster` | GPR + 24 surveyed corner points | ✅ acquired, CC-BY | none | corners only, no raster DEM, no subsurface truth |
| `guangzhou-ids` | GPR (subset) | ⚠️ partial | none | odometry only, no coordinates |
| `ingv-unisa` | GPR | ⚠️ licence unverified | none | no ground truth |
| Seismic (any) | — | ❌ none held | — | **UNAVAILABLE** — see §6 |
| Grimsel Test Site (crosshole/single-hole GPR, 15 boreholes) | Borehole GPR | ❌ not acquired | unknown | promising, unaudited; not pursued this stage |
| Wurtsmith AFB multi-offset GPR | GPR | ✅ acquired, machinery validation only | none | validates velocity-from-moveout machinery; not a site-fusion candidate |
| BHRS | GPR + borehole + seismic potential | ❌ site suspended, no downloadable data | — | ruled out, confirmed dead (§4 of the calibration audit) |

## 2. Selection methodology

Scored against the brief's criteria, in order of what actually discriminates
between the candidates:

1. **Same physical site, independently verifiable** — not assumed from
   shared nationality or file format. For 4TU/AHN this was established by
   computing the GPR's own measured extent from SEG-Y trace headers,
   transforming it to the DEM's declared CRS, and matching it against the
   **official PDOK tile index** — not by both files being Dutch.
2. **Existing Subterra converter support** — no new converter, no new
   `SensorType`. Both SEG-Y (GPR) and GeoTIFF (DEM) converters already exist
   and are unmodified.
3. **Reproducibility** — every number in this document that is not a
   citation to a publication was either already pinned by an existing,
   passing test, or re-derived here from a file on disk.
4. **Existing evidence reuse** — no previously resolved question was
   reopened; §12 is a re-run of tests that already existed, not new
   analysis.
5. **Relevance to 3D reconstruction** — a demonstration that stops at
   "the two files load" is not useful; the criterion that mattered most was
   whether a **vertical** relationship could even be assessed, correctly,
   without inventing one.

The strongest candidate is not the one with the most files (`bam-concrete-gpr`
is 1.75 GB and contributes nothing to site fusion) and not the one with the
richest single-dataset ground truth (`tu1208-ifsttar`'s theodolite-surveyed
depths are the best target evidence held, but the dataset carries no
coordinates of any kind and cannot participate in cross-dataset fusion at
all). The discriminator was **an independently verifiable physical
relationship between two different datasets**, and only one pair has that.

## 3. Selected dataset combination

| Modality | Dataset | Classification |
|---|---|---|
| **GPR** | `4tu-nl-utility` — NL utility surveying, 13 sites, 759 SEG-Y files | **SAME-SITE** |
| **DEM** | `ahn-dtm-05m` — AHN DTM 0.5 m, PDOK, 13 site-matched windows | **SAME-SITE** |
| **Seismic** | — | **UNAVAILABLE** (§6) |
| **Borehole** | TestUM (PANGAEA 971978) held separately | **CROSS-SITE** — real, but a different country and cannot be spatially merged into this model (§5) |

**This is a two-modality demonstration, not four.** Per the brief's own
instruction, the fourth and third modalities are not fabricated to complete
the diagram.

## 4. Why it was selected

- **It is the only pair in the corpus with an independently verified
  physical-site relationship.** Compatibility was established from measured
  extent-overlap against an official tile index, not assumed.
- **It already runs, on real data, across the entire corpus** — not one
  lucky site. All 13 4TU project sites have a matched AHN window, and
  `tests/test_ahn_multi_site.py` fuses GPR with its own surface window at
  every one of them (verified in this session — §12).
- **It exercises the hardest-to-get-right part of the architecture
  correctly**: cross-CRS reprojection is read-only and reported as derived
  (`FusionSample.n_reprojected`), position kinds are partitioned before any
  distance is computed (so an odometry or undeclared-CRS record cannot
  falsely co-locate), and the vertical relationship assessor refuses to
  promote a **measured, systematic, sub-metre residual** into a declared
  datum. That refusal is exactly the discipline this stage was asked to
  protect.
- **It has genuine, if currently blocked, relevance to ground truth**: 4TU
  carries 125 trial-trench ground-truth tables (excavated utility depths).
  They are not usable *yet* (§11), but they exist on the same dataset this
  combination already uses, which no alternative offers.

## 5. Physical-site relationship

### 5.1 GPR ↔ DEM (selected pair) — SAME-SITE, independently verified

The GPR extent was **measured**, not assumed: real SEG-Y trace headers for
4TU project 01 give WGS84 lat 52.23847–52.23961, lon 6.85149–6.85461,
transformed to EPSG:28992 as X 255012.8–255228.5, Y 473277.9–473409.0. That
box was matched against the **official AHN tile index**, which returned
exactly one covering tile per site. The GPR extent lies wholly inside the
matched AHN window at all 13 sites (`tests/test_ahn_multi_site.py::
test_the_window_covers_the_measured_gpr_extent_it_was_chosen_for`, re-run in
this session, passing for all 13).

### 5.2 GPR ↔ Borehole (TestUM) — CROSS-SITE, not merged

TestUM (Wittstock/Dosse, Brandenburg, Germany, 53.19°N 12.50°E) and 4TU
(Netherlands, multiple sites near 52.2°N 6.8°E and others) are different
countries and different acquisitions with no stated relationship. **No
attempt was made to spatially merge them**, per the brief's explicit
instruction not to merge unrelated sites because their formats are
compatible. TestUM is documented separately in §5.3 as the strongest
borehole evidence Subterra holds, kept apart from the selected pair.

### 5.3 TestUM's own internal site relationship — SAME-SITE, real

Within TestUM itself, the crosshole and reflection boreholes are on one
1×1 m grid with DGPS-surveyed collar coordinates and deviation logs — a
real, same-site, same-acquisition relationship, fully documented in
[`testum-evidence-audit.md`](testum-evidence-audit.md) and confirmed against
downloaded raw files in
[`testum-raw-data-validation.md`](testum-raw-data-validation.md). It is not
part of the selected combination because it offers no second modality: every
TestUM file is GPR (reflection or crosshole configuration of the same
instrument), so it cannot itself demonstrate cross-*modality* fusion.

## 6. Modality inventory

| Modality | Held? | Evidence |
|---|---|---|
| **GPR** | ✅ Extensively — `4tu-nl-utility`, `tu1208-ifsttar`, `bam-concrete-gpr`, `hillside-lancaster`, TestUM, `guangzhou-ids`, `ingv-unisa` | multiple SEG-Y/DZT/rd3 corpora, converters for all three vendor formats |
| **DEM** | ✅ `ahn-dtm-05m` — AHN DTM 0.5 m, 13 site windows | GeoTIFF converter; `SensorType.DEM` now exists (Phase 7, slice 31) but the stored dataset is still tagged `SensorType.LIDAR` (see caveat below) |
| **Seismic** | ❌ **UNAVAILABLE** | `external-calibration-dataset-audit.md` §7: "Well-tied seismic... not pursued to acquisition, deliberately." Marmousi excluded as synthetic; Sleipner/SEAM/SEG volumes not individually audited; no seismic dataset appears in the corpus |
| **Borehole** | ⚠️ Held, but cross-site to the selected pair | TestUM: 22 two-inch wells + 8 multilevel wells, DGPS + deviation-surveyed, CC-BY, downloaded |

**Caveat on "DEM", updated (Phase 7, slice 31).** At the time this document
was written, `SensorType` had no dedicated DEM/terrain-model member and
`ahn-dtm-05m` was tagged `SensorType.LIDAR` as the nearest existing category.
`SensorType.DEM` now exists, and the GeoTIFF converter's undeclared-band
elevation inference fires for `DEM` the same way it already did for `LIDAR`
(`docs/surface-reference.md`). The stored `ahn-dtm-05m` dataset itself was
**not** migrated or re-ingested -- it still carries its original `lidar` tag,
by the same rule that keeps every held reference dataset exactly as ingested
unless a user re-ingests it. The inventory's underlying fact is unchanged
either way: *"DTM only — ground-classified returns resampled to a raster,
not the LAZ point cloud."*

## 7. CRS inventory

| Dataset | Horizontal CRS | Coordinate source | Authority | Provenance class |
|---|---|---|---|---|
| `4tu-nl-utility` | WGS84 (native, per-trace GNSS) | SEG-Y trace header bytes | `ieee_nmea` decode, Dr. ter Huurne (author) | **measured** |
| `ahn-dtm-05m` | **EPSG:28992** (Amersfoort / RD New) | GeoTIFF WKT + PDOK ATOM `<category>` + tile index | PDOK/Rijkswaterstaat | **declared_by_source**, stated in three independent places |
| TestUM | UTM Zone 33U | `GPS_Wittstock_GEWS_2Z.xlsx` | DGPS survey (author) | **measured** |
| `tu1208-ifsttar` | — | — | — | **absent** — no CRS of any kind |

Reprojection between 4TU (WGS84) and AHN (EPSG:28992) happens **only inside
the fusion layer**, is **read-only**, and is reported per-sample via
`FusionSample.n_reprojected` — never applied at ingest, never silent. No CRS
is inferred anywhere in this combination.

## 8. Vertical-reference inventory

| Dataset | Vertical quantity held | Datum declared? | Class |
|---|---|---|---|
| `4tu-nl-utility` | acquisition elevation, 2 fields (orthometric/ellipsoidal pair, constant offset 43.948297 m, sd 0.0005 m) | **No** — not in SEG-Y, readme, codebook, or the companion Data in Brief article (checked directly, §"associated publication" in [`vertical-reference-site01.md`](vertical-reference-site01.md)) | **undeclared** |
| `ahn-dtm-05m` | ground-surface elevation, one value per 0.5 m cell | **No** — NAP is PDOK *documentation*, absent from the GeoTIFF itself (no `VERT_CS`, no `COMPD_CS`) | **undeclared** |
| TestUM | geoid height + ellipsoid height, per borehole (69.3–69.6 m / 109.3–109.6 m asl) | **Author-stated** ("asl"), geoid **realisation not named** | **author-stated, realisation unresolved** |

**The measured relationship, and why it is not adopted as a datum.** GPR
acquisition elevation vs. AHN ground surface agrees to **−0.508 m mean, sd
0.163 m** across the complete site-01 window (24,013 traces), and the
per-activity offset is **systematic** (spread 0.260 m, not the 1.761 m first
measured against a truncated window — the correction is recorded in
[`vertical-reference-site01.md`](vertical-reference-site01.md)). This is
**measured, systematic, sub-metre agreement with an independent surface** —
and it is still not treated as evidence of a shared datum. Three reasons,
none inferred from the number itself:

1. No source declares it — not the SEG-Y, not the readme, not the codebook,
   not the companion publication.
2. The constant is unexplained — an antenna-height correction, terrain
   change between flights, and a geoid-model difference would all produce a
   systematic offset near this size, and nothing in the data distinguishes
   them.
3. Its **sign** is wrong for the obvious explanation (a GNSS antenna held
   above the ground would read *above* the surface; this reads *below* it).

`fusion.vertical_reference.assess(gpr_frame, ahn_frame)` returns
**`REGISTRATION_REQUIRED`** for every one of the 13 sites
(`tests/test_ahn_multi_site.py::test_no_site_yields_an_absolute_elevation`,
re-run in this session, passing for all 13) — never `ABSOLUTE_ELEVATION`,
regardless of how tight the residual is. **Correlation is not treated as
proof of physical identity.**

## 9. Time/depth inventory

| Dataset | Vertical axis | Origin | Depth available? |
|---|---|---|---|
| `4tu-nl-utility` | two-way travel time, ns (measured) | instrument time-zero at each trace, **not the ground** | only if a caller supplies a velocity — none is supplied here; no depth is computed |
| `ahn-dtm-05m` | elevation, m (band value) | n/a — it is already an elevation, not a time axis | n/a |
| TestUM | two-way travel time, 1024 samples / 150 ns / 0.146484375 ns (measured) | instrument time-zero; `rhf_position = −15.0 ns` and a separate `Radar time delay = 16.3 ns` are **two different, unreconciled numbers**, **neither adopted** | **not derived** — 25 of the 26 published air-WARR calibration files were analysed (Stage 29); the slope-consistency check passed on only 2, which disagree with each other by 1.12 ns; **INCONCLUSIVE**, no t0 adopted |

No propagation velocity is adopted for any dataset in this document. No
converter default was assumed to be a velocity.

## 10. Acquisition geometry

| Dataset | Geometry |
|---|---|
| `4tu-nl-utility` | surface, along-track, air-launched 500 MHz array, RTK GNSS per trace |
| `ahn-dtm-05m` | airborne LiDAR-derived DTM, resampled to a 0.5 m raster, ground-classified returns only (`maaiveldbestand`) |
| TestUM | **borehole-deployed** — reflection (one antenna lowered in a well) and zero-offset crosshole (two antennas in two wells, same depth simultaneously); 0.25 m depth steps, verified 265/265 across the published corpus |

TestUM's acquisition geometry is architecturally significant on its own:
Subterra's only position type for a distance-like quantity,
`OdometryPosition(along_track_m, path_id)`, models surface travel and cannot
represent a borehole depth station, a borehole identity, or (for crosshole) a
second borehole and separation. This was identified and **left unmodelled,
by instruction**, in
[`testum-borehole-depth-axis-audit.md`](testum-borehole-depth-axis-audit.md)
— see §14 below.

## 11. Ground-truth/control evidence

| Dataset | Evidence | Class | Usable for this combination? |
|---|---|---|---|
| `4tu-nl-utility` | 125 trial-trench ground-truth tables, excavated utility depths 0.23–4.80 m | **attested** (excavator) | **No** — the trench-to-survey-line registration has no metric tie (a hand-drawn map with no scale); the depths exist but cannot be associated with a specific trace |
| `ahn-dtm-05m` | none (surface model, not subsurface truth) | n/a | n/a |
| TestUM | controlled freezing front + known heat-exchanger geometry (16 probes, 18 m deep, 1×1 m grid) | **attested/controlled**, not a list of surveyed discrete targets | Not applicable to the selected pair (cross-site); would be **weak** absolute-depth truth even for TestUM alone — no published list of reflectors at attested depths tied to specific traces |
| `tu1208-ifsttar` | theodolite-surveyed target depths, 3 media, 9+ targets | **surveyed** — the best target-depth evidence Subterra holds | Not usable here — `tu1208-ifsttar` has no coordinates and no site in common with the selected pair |

**No ground truth ties the selected GPR+DEM pair together in 3D.** This is
the reason §17 classifies the result as it does.

## 12. What can actually be fused

**Horizontal/spatial fusion of `4tu-nl-utility` and `ahn-dtm-05m` — already
implemented, already tested, re-verified in this session.**

The existing architecture (`fusion/sensor_fusion.py`) partitions records by
position kind before computing any distance, obtains a real WGS84 view for
every record (natively geographic, or projected-with-declared-CRS
reprojected — read-only, counted, never applied at ingest), and clusters
geographically. Applied to the selected pair:

```
tests/test_ahn_cross_crs_fusion.py   — site 01, single-window depth
tests/test_ahn_multi_site.py         — all 13 sites, breadth
tests/test_vertical_reference.py     — site 01 vertical assessment
tests/test_overlays.py               — composition without flattening
```

Re-run in this session against the real files on disk (no fixtures, no
mocks — `datasets/raw/pdok_ahn/dtm_05m/*.tif` and
`datasets/raw/4tu/.../extracted/*/**/*.sgy`):

```
89 passed, 3 warnings in 76.07s
```

with **zero skips** — every real-data test executed. The headline results
these tests pin:

- **2 multimodal (`gpr`+`lidar`) samples, 65 LiDAR + 190,976 GPR members**,
  site 01, radius 30 m — `n_reprojected = 65` (every LiDAR member; zero GPR
  members, which are natively geographic and need no transform).
- The same fusion mechanism succeeds **at all 13 sites**
  (`test_each_site_fuses_gpr_with_its_own_surface`, parametrized).
- Fusion is **deterministic**: re-running produces the same sample count and
  the same reprojected-member count, because the transform is a pure
  function of the declared CRS and the raster/trace values, and nothing is
  randomised.
- **No mutation**: `test_fusion_does_not_mutate_the_ahn_records` pins that
  source records are untouched by clustering — provenance survives because
  nothing overwrites it.
- **Provenance preserved per sample**: `FusionSample.dataset_ids` and
  `.sensor_types` name every contributing dataset and modality; the full
  `SubterraRecord` objects (not anonymised centroids) are retained in
  `records_by_sensor`, so every fused point traces back to its exact source
  record, frame and file.

**No new implementation was written for this section.** The fusion path this
stage exists to prove is not merely *implementable* — it is already built,
already tested corpus-wide, and was independently re-verified here rather
than trusted from the docs alone. Writing a second, parallel script to
demonstrate the same thing would be exactly the "two definitions that could
disagree" failure mode this platform's own conventions exist to prevent.
Reproduce with:

```
docker run --rm -v "$PWD:/app" -w /app subterra_data_platform-api:latest \
  python -m pytest tests/test_ahn_cross_crs_fusion.py tests/test_ahn_multi_site.py \
                    tests/test_vertical_reference.py tests/test_overlays.py -q
```

## 13. What cannot yet be fused

- **Vertical/depth fusion.** `fusion.vertical_reference.assess` correctly
  reports `REGISTRATION_REQUIRED` at all 13 sites (§8). No absolute Z is
  computed anywhere in the codebase for this pair, and none should be until
  a vertical datum is declared for one or both sides and the depth-axis
  origin is tied to the ground.
- **A combined horizontal+vertical "unified model" object.** These are two
  separate calls today (`fuse_datasets` and `vertical_reference.assess`),
  not one artifact. `FusionSample` carries dataset IDs, sensor types and
  full source records, but no structured field for vertical relationship,
  uncertainty/quality, or a transformation *history* (only a
  `n_reprojected` *count*). Building that combined representation is real
  work, and it is schema work, not a naming fix — **explicitly out of scope
  for this stage**, consistent with the brief's instruction not to implement
  more than the architecture already safely supports.
- **Borehole GPR (TestUM), at all**, into this or any spatial model. Its
  positions are `OdometryPosition`, which `fuse_datasets` explicitly
  excludes (`NON_FUSABLE_REASONS["odometry"]`), and there is no borehole
  position concept to carry depth-below-collar, borehole identity, or (for
  crosshole) a second borehole and separation. This is a **schema gap**,
  identified and deliberately left unfixed in
  [`testum-borehole-depth-axis-audit.md`](testum-borehole-depth-axis-audit.md)
  §"Proposed production change", which lists the exact two failing
  conditions (no borehole position type exists; the change is not isolatable
  from three other GSSI converters).
- **Seismic, of any kind.** Nothing is held. See §6.
- **4TU's own trench ground truth**, tied to a GPR trace. The
  registration between trench distance and survey line has no metric tie
  (§11); this blocks 3D-registered anomaly validation for the selected pair
  regardless of the CRS/vertical work above.
- **Absolute subsurface elevation for TestUM.** The air-WARR t0 calibration
  is published and was analysed exhaustively in this repository (Stage 29);
  25 of 26 published files were analysed, the slope-consistency check
  passed on only 2, and the two survivors disagree by 1.12 ns.
  **INCONCLUSIVE** — no t0, therefore no velocity, therefore no depth.

## 14. Remaining blockers

| Blocker | Status | Where it is recorded |
|---|---|---|
| 4TU vertical datum (GPR side) | **BLOCKED** — undeclared everywhere checked, including the companion publication | [`vertical-reference-site01.md`](vertical-reference-site01.md) |
| AHN vertical datum | **BLOCKED** — NAP is PDOK documentation, absent from the file | same |
| 4TU depth-axis origin (t0) | **BLOCKED** | [`cross-dataset-evidence-audit.md`](cross-dataset-evidence-audit.md), [`external-calibration-dataset-audit.md`](external-calibration-dataset-audit.md) |
| 4TU propagation velocity | **BLOCKED** | same |
| 4TU physical depth | **BLOCKED** | same |
| 4TU absolute subsurface elevation | **BLOCKED** | same |
| 4TU trench-to-survey-line registration | **BLOCKED** — no metric tie | [`cross-dataset-evidence-audit.md`](cross-dataset-evidence-audit.md) §Route C |
| TestUM t0 | **BLOCKED / INCONCLUSIVE** — calibration published, analysis run, does not agree with itself | [`testum-air-warr-t0-experiment.md`](testum-air-warr-t0-experiment.md) |
| TestUM velocity | **BLOCKED** — needs t0 | same |
| Borehole position/frame representation | **UNIMPLEMENTED** — schema gap, deliberately deferred | [`testum-borehole-depth-axis-audit.md`](testum-borehole-depth-axis-audit.md) |
| Seismic dataset acquisition | **NOT PURSUED** — scoping decision, not a search failure | [`external-calibration-dataset-audit.md`](external-calibration-dataset-audit.md) §7 |
| Combined horizontal+vertical fusion artifact | **UNIMPLEMENTED** — real work, out of scope for this stage | §13 above |

**No blocker in this table was resolved by this stage, and none was
invented.** 4TU's blocker state is explicitly unchanged, per the acceptance
criteria.

## 15. Proposed fusion graph

What is real today, drawn to scale with what is actually built rather than
the aspirational four-way diagram:

```
4tu-nl-utility (GPR)             ahn-dtm-05m (DEM)
  WGS84, measured                  EPSG:28992, declared_by_source
  per-trace GNSS                   PDOK, 13 site windows
        │                                │
        │  geographic_views()            │  geographic_views()
        │  (native)                      │  (reprojected, read-only,
        │                                │   n_reprojected counted)
        └───────────────┬────────────────┘
                         ▼
              fuse_datasets()  →  FusionSample
              [HORIZONTAL — WORKING, 13/13 sites]
                         │
                         │  fusion.vertical_reference.assess(gpr, ahn)
                         ▼
              REGISTRATION_REQUIRED
              [VERTICAL — BLOCKED, 13/13 sites]
                         │
                         ✗  (stops here — no absolute Z, no unified 3D model)

TestUM (borehole GPR)                         Seismic
  UTM 33U, DGPS-measured                      UNAVAILABLE — not acquired
  OdometryPosition (mis-modelled;
  no borehole position type exists)
        │
        ✗  excluded by fuse_datasets()
           (position kind "odometry" — NON_FUSABLE_REASONS)
        │
        = CROSS-SITE to the selected pair regardless; not attempted
```

**The fusion graph the brief asked for — GPR + DEM + Seismic + Borehole →
one unified subsurface model → anomaly detection + 3D reconstruction — is
not yet buildable end-to-end with real data.** Two of its four inputs are
unavailable or unmergeable for physical-site reasons; the two that are
available fuse horizontally but not vertically; no ground truth currently
reaches the fused result.

## 16. Validation criteria

| # | Criterion | Result |
|---|---|---|
| 1 | Spatial alignment | ✅ verified — GPR extent computed from measured trace headers, matched against the official AHN tile index, wholly contained in the matched window, 13/13 sites |
| 2 | CRS consistency | ✅ both CRSs are declared (WGS84 native, EPSG:28992 `declared_by_source`); reprojection happens only in the fusion layer, is read-only, and is counted |
| 3 | Vertical-reference consistency | ❌ **not established** — both sides undeclared; `assess()` correctly returns `REGISTRATION_REQUIRED`, not a false pass |
| 4 | Modality provenance preservation | ✅ `FusionSample.dataset_ids`, `.sensor_types`, full source `SubterraRecord`s retained, not anonymised |
| 5 | Expected spatial overlap | ✅ measured and matched against an independent tile index, not assumed |
| 6 | Expected observation counts | ✅ pinned: 65 LiDAR + 190,976 GPR members, site 01; per-site counts pinned across all 13 |
| 7 | No silent coordinate transformation | ✅ `reproject=False` at ingest is the tested default for this pair; transform happens only in fusion and is reported via `n_reprojected` |
| 8 | No silent datum conversion | ✅ neither side declares a datum; none is invented; `REGISTRATION_REQUIRED` is the honest result even though the measured residual is tight |
| 9 | No invented depth/time calibration | ✅ no velocity, no t0, no depth computed anywhere in this combination |
| 10 | Deterministic reproduction | ✅ re-run in this session: 89/89 tests pass, no skips, against real files on disk |

**9 of 10 pass; #3 correctly fails, and its failure is the point** — a
system that reported success on #3 given the evidence in §8 would be
inventing a vertical datum.

## 17. Classification

**PARTIALLY VALIDATED.**

- The **horizontal/spatial** component is genuinely validated: an
  independently verifiable physical-site relationship, cross-CRS
  reprojection tested against real declared-CRS data, deterministic,
  corpus-wide (13/13 sites), non-destructive, fully provenance-preserving.
- The **vertical** component, and therefore any claim of a 3D "unified
  subsurface model", is **not validated and remains architecturally
  blocked** — correctly reported as such by the existing
  `REGISTRATION_REQUIRED` state rather than papered over.
- It is **not** an INTEGRATION DEMONSTRATION only, because the horizontal
  half carries real corroborating evidence (extent-matching against an
  official index, a measured and systematic — if unexplained — vertical
  residual) beyond "the files loaded together."
- It is **not** SCIENTIFICALLY VALIDATED RECONSTRUCTION, because no ground
  truth currently reaches the fused result in three dimensions, and the
  vertical relationship is explicitly unresolved.

---

## Roadmap impact

**A. What this stage unlocks.** A documented, reproducible, corpus-wide
proof that Subterra's existing fusion architecture correctly combines two
independently acquired modalities (GPR, DEM) over a verified physical site,
while correctly refusing to complete the parts of the chain it cannot
support. No new capability was built; an existing one was verified,
scoped, and written down against the exact vocabulary this brief specified
(SAME-SITE / CROSS-SITE / UNAVAILABLE, MEASURED / DECLARED / ATTESTED /
INFERRED / UNRESOLVED).

**B. Phase 7 (multi-modal).** Advances it, precisely: Phase 7's own rule is
*"modality-agnostic doesn't mean we support everything — the core model
isn't tied to one sensor."* This stage is the first time two *different*
Subterra datasets (not one dataset's own frames, which Phase 7 slices 1–3
already handled) are shown to compose spatially without inventing a
relationship. It does not advance ingest-time multi-modal capture — that
remains the human decision Grok's own Phase 7 scoping already deferred
(one dataset with several recorded modalities, vs. several datasets fused
later — this stage assumes the second, because that is what the current
architecture and holdings actually support).

**C. Phase 8 (validated detection).** Does not advance it. No detector was
run, no candidate was generated from this combination, and §11 shows no
ground truth reaches the fused pair.

**D. Phase 9 (fusion).** This *is* Phase 9-adjacent groundwork, but only the
horizontal half. Phase 9's own diagram requires a "unified subsurface
model" with X, Y **and** Z; §13 documents exactly what is missing to get
there (a combined artifact; a declared vertical datum on at least one side;
a depth-axis-to-ground offset).

**E. Phase 10 (3D reconstruction).** Does not advance it, and this document
does not claim otherwise. 3D reconstruction needs the vertical half this
stage shows is blocked.

**F. Stage 8–12 blockers (the earlier vertical-reference work).** All remain
exactly as before: 4TU vertical datum, depth-axis origin, propagation
velocity, physical depth and absolute subsurface elevation are **BLOCKED**,
unchanged by this stage. TestUM's t0 is **INCONCLUSIVE**, unchanged.

**G. Can the selected combination become Subterra's first end-to-end
demonstration dataset?** For the **horizontal** half, effectively already
does — 13/13 sites, real data, deterministic. For a genuine **end-to-end**
(GPR trace → verified physical depth → 3D position) demonstration: **not
with what is held today.** The missing piece is not more data volume, it is
a single acquisition where the same party surveys the ground surface in a
named datum, records or independently constrains a velocity, and knows a
target depth — exactly the conclusion
[`cross-dataset-evidence-audit.md`](cross-dataset-evidence-audit.md) reached
before this stage, and nothing found since changes it.

**H. The exact next stage required, if pursued.** Not a dataset-acquisition
stage — the corpus already has what it can usefully use for this pattern.
Two independent tracks, either of which is a real, scoped, boundable next
stage:

1. **Vertical registration, declared not invented.** Ask the 4TU author (or
   the instrument vendor) the specific question already sharpened by prior
   stages: was an air-path time-zero calibration at a measured antenna
   separation ever recorded for this instrument, and separately, what datum
   are the SEG-Y elevation bytes in. Either answer, once obtained, is a
   **declaration** this architecture already knows how to consume
   (`VerticalDatum(code, provenance)`, `origin_offset`) — no schema change
   needed, only the fact.
2. **Borehole position schema**, scoped as its own stage per the explicit
   stopping point in
   [`testum-borehole-depth-axis-audit.md`](testum-borehole-depth-axis-audit.md):
   a position/frame concept carrying depth-below-collar, borehole identity,
   and (for crosshole) a second borehole and separation, isolated from the
   three existing GSSI/MALA/IDS converters that currently funnel every
   distance-like quantity into `OdometryPosition`. This would make TestUM's
   real borehole data usable, though still not mergeable with the 4TU/AHN
   pair (different site) — it would stand as its own, second, real
   integration case.

Neither is "acquire a fourth dataset to complete the diagram." Both are
"declare or model what is already held."

---

## Sources

All primary sources are cited in the documents linked throughout this
report:
[`cross-dataset-evidence-audit.md`](cross-dataset-evidence-audit.md),
[`external-calibration-dataset-audit.md`](external-calibration-dataset-audit.md),
[`dataset-inventory.md`](dataset-inventory.md),
[`vertical-reference-site01.md`](vertical-reference-site01.md),
[`testum-evidence-audit.md`](testum-evidence-audit.md),
[`testum-raw-data-validation.md`](testum-raw-data-validation.md),
[`testum-borehole-depth-axis-audit.md`](testum-borehole-depth-axis-audit.md),
[`testum-air-warr-t0-experiment.md`](testum-air-warr-t0-experiment.md).

Test re-execution in this session (2026-08-14):
`tests/test_ahn_cross_crs_fusion.py`, `tests/test_ahn_multi_site.py`,
`tests/test_vertical_reference.py`, `tests/test_overlays.py` — **89 passed,
0 skipped, 0 failed**, against real files under `datasets/raw/` (gitignored;
reproducible via the acquisition scripts and provenance records already in
the repository, not by re-downloading anything new for this document).
