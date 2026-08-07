# Vertical reference: AHN surface vs GPR depth, site 01

Investigation date 2026-08-07. **Conclusion: outcome C — a vertical
registration step is required.** No absolute Z is computed, and nothing in
the code produces one.

> **Correction, 2026-08-07 (multi-site milestone).** The residual figures
> first published here were measured against a *truncated* AHN window —
> one tile, where site 01 actually spans two. Re-measured against the
> complete window (24,013 traces instead of 18,299) the residual is
> **−0.508 m, sd 0.163**, with a per-activity spread of **0.260 m**, not the
> 1.761 m originally reported. The corrected table is below; the superseded
> one is kept collapsed beneath it, so the correction is visible.
> **The conclusion is unchanged, but the reasoning is different**: the
> offset now looks *systematic*, which points more strongly toward a shared
> datum, not less. What blocks the conclusion is no longer "the offset
> varies unexplainably" but "no source declares a datum, the −0.51 m
> constant is unexplained, and the depth axis still starts at instrument
> time-zero."

## What AHN actually provides

| | |
|---|---|
| **Quantity** | Terrain (ground) surface height, one value per 0.5 m cell |
| **Which surface** | `maaiveldbestand` per the PDOK feed — **only points classified as ground**; trees, buildings, bridges and water are excluded from the resampling, which is Squared IDW. *"Er zijn geen verdere bewerkingen uitgevoerd"* (no further processing). |
| **Units** | Metres — **not stated in the file.** Band units, band description and dataset tags are all empty. |
| **Horizontal CRS** | EPSG:28992, declared in the file, the ATOM feed and the tile index |
| **Vertical CRS** | **NONE.** The WKT is a plain 2D `PROJCS`; no `VERT_CS`, no `COMPD_CS`. |
| **Vertical datum** | NAP — **PDOK documentation only, absent from the GeoTIFF** |
| **Epoch** | **Not stated** in the feed, the tile index or the file. The feed's `updated` is 2023-04-12, which is a publication date, not a flight date. |

## What the GPR actually provides

| | |
|---|---|
| **Vertical axis** | Two-way travel time, nanoseconds — **measured** by the instrument |
| **Axis origin** | `instrument time-zero at each trace`, **not the ground surface** |
| **Depth** | Exists only when the caller supplies a velocity; then `depth = twt × v / 2`. **Derived, not measured.** |
| **Acquisition elevation** | **Yes** — two float32 values per trace, previously discarded. Bytes 41–44 give 27.373–29.331 m over site 01; bytes 45–48 give 71.320–73.280 m. |
| **Their relationship** | Constant difference **43.948297 m, sd 0.000529 m** — consistent with an orthometric/ellipsoidal pair for the Netherlands |
| **Vertical datum** | **Not declared anywhere.** Not in the SEG-Y, not in `Readme.txt`, and the 2-page `Codebook.pdf` contains no occurrence of *elevation, height, NAP, datum, vertical, antenna, geoid, ellipsoid* or *coordinate*. |
| **Antenna height** | **Not recorded.** The readme says only "air-launched", "a few centimetres above the surface". |

## The provenance chain

```
GPR instrument time-zero  (measured; t0 = 2.446 ns on these files)
   │  ▼ requires: air-path offset to ground        ← UNKNOWN
GPR ground surface        (never established)
   │  ▼ requires: caller-supplied velocity          ← available, but ASSUMED
GPR depth below origin    (derived)
   │  ▼ requires: acquisition-surface elevation     ← present, datum UNDECLARED
   │  ▼ requires: shared vertical datum             ← UNDECLARED on both sides
AHN ground surface        (measured, ground-classified, datum NAP by documentation)
   │
absolute elevation        ← NOT AVAILABLE
```

## The measurement (corrected)

**24,013** site-01 traces fall on a valid AHN cell in the complete window.

| | |
|---|---|
| **Overall residual** | **−0.508 m mean, sd 0.163 m** |

| Activity | Traces | GPR z̄ | AHN z̄ | residual | sd |
|---|---|---|---|---|---|
| 01.1 | 3684 | 28.398 | 28.859 | −0.461 | 0.031 |
| 01.2 | 2254 | 28.948 | 29.406 | −0.458 | 0.106 |
| 01.3 | 3045 | 29.181 | 29.688 | −0.507 | 0.079 |
| 01.4 | 3466 | 28.219 | 28.921 | −0.703 | 0.324 |
| 01.5 | 1937 | 28.456 | 28.898 | −0.442 | 0.034 |
| 01.6 | 2089 | 28.482 | 28.985 | −0.503 | 0.096 |
| 01.7 | 2496 | 29.097 | 29.587 | −0.489 | 0.049 |
| 01.8 | 2323 | 28.973 | 29.441 | −0.468 | 0.037 |
| 01.9 | 2719 | 29.043 | 29.507 | −0.464 | 0.116 |

Per-activity means span **−0.442 to −0.703 m — a 0.260 m spread**. The
residual is **systematic**, not erratic.

<details>
<summary>Superseded measurement (truncated one-tile window, 18,299 traces)</summary>

Residual −0.699 m, sd 0.408; per-activity means +0.431 to −1.330 m, a
1.761 m spread. That spread was largely an artefact of sampling activities
against partial coverage and nodata at the window edge, and the inference
drawn from it — "this cannot be a fixed offset" — does not survive complete
coverage.
</details>

### Why this still does not establish a datum

Sub-metre, systematic agreement with an independent NAP surface is **strong
evidence** that the GPR elevation is an orthometric height in NAP. It is
still not a declaration, and three things remain open:

1. **No source declares it.** Not the SEG-Y, not the readme, not the
   codebook. Evidence is not provenance.
2. **The −0.51 m constant is unexplained.** An antenna-height correction
   applied by the operator, terrain change between the AHN flight and the
   survey, and a geoid-model difference in the receiver would all produce a
   systematic offset of roughly this size. Nothing in the data distinguishes
   them, and the AHN epoch is unpublished so the terrain-change hypothesis
   cannot even be tested.
3. **Its sign is the wrong way round for the obvious explanation.** A GNSS
   antenna carried above the ground would sit *above* the surface; this sits
   0.51 m below it.

Declaring a datum on this basis would be inventing provenance.

## Outcome

**C — a vertical datum/registration step is required.** Three things are
missing, and the model names each one:

1. a declared vertical datum for the GPR acquisition elevations;
2. a declared vertical datum for the AHN surface (the caller can now supply
   NAP, which PDOK documents);
3. the offset from the depth-axis origin to the ground — for an air-launched
   antenna this is an air path the constant ground velocity does not model.

Supplying (2) alone does not unlock absolute Z, and a test pins that.

## What was implemented

Nothing that produces Z. The model was extended just enough to *state* the
gap:

- `schemas/spatial.py` — `VerticalDatum` (code + provenance + name; a code
  without a provenance is refused) and `VerticalRelationshipKind`
  (`absolute_elevation` / `relative_depth_only` / `registration_required` /
  `unrelated`). `VerticalAxis.vertical_datum` is optional; **absent means
  undeclared**, which is the true state of every dataset held.
- `fusion/vertical_reference.py` — `assess(subsurface_frame, surface_frame)`
  returning the kind plus `reasons` and an actionable `missing` list, and
  `absolute_elevation_available` as the single question a 3D consumer should
  ask before drawing Z. **It inspects no coordinate values**: numbers
  agreeing is not evidence of a shared datum.
- `converters/segy_converter.py` — exposes the previously-discarded
  acquisition elevation as `record.elevation`, marked
  `acquisition_elevation_datum: "UNDECLARED"`, under the existing
  `ieee_nmea` declaration only. INGV populates those fields as standard
  scaled integers, so the default path is untouched and the pinned records
  are unchanged.
- `converters/geotiff_converter.py` — optional `vertical_datum` kwarg so a
  caller can assert what PDOK documents. Recorded as
  `SUPPLIED_BY_CALLER`, never `declared_by_source`.

## The associated publication was checked, and does not declare it either

**2026-08-07.** The one authoritative source not previously examined was the
dataset's companion article — ter Huurne et al., *Ground penetrating radar at
work: a realistic perspective on utility surveying in the Netherlands through a
comprehensive ground-truth dataset*, **Data in Brief 54 (2024) 110329**,
[10.1016/j.dib.2024.110329](https://doi.org/10.1016/j.dib.2024.110329).

It contains **no occurrence** of *coordinate system*, *coordinate reference
system*, *RD*, *Rijksdriehoek*, *EPSG*, *WGS84*, *NAP*, *Normaal Amsterdams
Peil*, *datum*, *geoid*, *ellipsoid*, or *antenna height*. It states only that
a "GNSS RTK receiver" recorded "geodetic locations in the x, y, and z axes",
and — for the trench records — that "geospatial information has been omitted to
preserve data and utility location confidentiality".

**Consequence: the vertical datum cannot be resolved from documentation.**
Every published source has now been exhausted. The remaining routes are author
contact (University of Twente) or an independent control measurement. Until one
of those succeeds, outcome C stands and no absolute Z is computable.

## What remains unknown

- The vertical datum of the GPR elevations — evidence points to NAP, no
  source states it.
- The antenna/pole height above ground, per activity.
- The air-path offset between instrument time-zero and the ground.
- The AHN acquisition epoch, hence whether the terrain changed between the
  two surveys.
- Which of those explains the **0.260 m** per-activity spread. (This line
  previously said 1.761 m — a leftover from the superseded truncated-window
  measurement corrected at the top of this document.)
