# Vertical reference: AHN surface vs GPR depth, site 01

Investigation date 2026-08-07. **Conclusion: outcome C — a vertical
registration step is required.** No absolute Z is computed, and nothing in
the code produces one.

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

## The measurement that decided it

18,299 site-01 traces fall on a valid AHN cell. Comparing the GPR
byte-41 elevation with AHN at the same coordinates:

| | |
|---|---|
| GPR elevation | 27.373 – 29.331 m (mean 28.859) |
| AHN at same xy | 27.658 – 30.179 m (mean 29.558) |
| **Residual** | **−0.699 m mean, sd 0.408 m** |

Sub-metre agreement with an independent NAP surface is strong evidence that
the GPR elevation *is* an orthometric height in NAP. It is not a
declaration, and the per-activity breakdown is why that distinction matters:

| Activity | Traces | GPR z̄ | AHN z̄ | residual | sd |
|---|---|---|---|---|---|
| 01.1 | 1150 | 28.395 | 27.964 | **+0.431** | 0.174 |
| 01.2 | 1881 | 28.972 | 29.885 | −0.913 | 0.209 |
| 01.3 | 3045 | 29.181 | 29.883 | −0.701 | 0.065 |
| 01.4 | 650 | 28.303 | 29.633 | **−1.330** | 0.275 |
| 01.5 | 2089 | 28.455 | 29.644 | −1.189 | 0.155 |
| 01.6 | 2089 | 28.482 | 29.397 | −0.914 | 0.090 |
| 01.7 | 2496 | 29.097 | 29.489 | −0.392 | 0.060 |
| 01.8 | 2323 | 28.973 | 29.581 | −0.608 | 0.040 |
| 01.9 | 2576 | 29.040 | 29.735 | −0.696 | 0.214 |

**Within** an activity the residual is tight (sd 0.040–0.275 m). **Between**
activities its mean spans +0.431 to −1.330 m — a **1.761 m spread**.

A fixed antenna height would be constant. This is not. Candidate causes —
terrain change on an active construction site between the AHN flight and the
survey, a different pole or cart setup per activity, GNSS vertical error
under obstruction, a different geoid model in the receiver — are **not
distinguishable from the available data**, and the AHN epoch is unknown, so
the construction-change hypothesis cannot even be tested.

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

## What remains unknown

- The vertical datum of the GPR elevations — evidence points to NAP, no
  source states it.
- The antenna/pole height above ground, per activity.
- The air-path offset between instrument time-zero and the ground.
- The AHN acquisition epoch, hence whether the terrain changed between the
  two surveys.
- Which of those explains the 1.761 m per-activity spread.
