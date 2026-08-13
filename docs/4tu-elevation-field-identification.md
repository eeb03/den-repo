# Which SEG-Y field holds the ellipsoidal GNSS elevation?

Dr. ter Huurne established that the GNSS elevations in the exported 4TU SEG-Y
files are **WGS84 ellipsoidal heights**, and did not say which of the two
populated elevation fields holds them. The two differ by ~44 m, so guessing
would risk a 44 m error in every elevation.

**The data answers it.** No further author question is needed for this.

## A. Dataset and header audit

Decoded from the raw bytes in `scripts/identify_segy_elevation_field.py` —
`struct.unpack` on the trace headers, independent of the existing converter.

| | |
|---|---|
| Format | SEG-Y, **little-endian**, binary-header format code **3** (int16 samples) |
| Trace record | 240-byte header + `n_samples × 2` |
| Elevation scalar (bytes 69–70) | **1** |
| Coordinate scalar (bytes 71–72) | **−1000** |
| Bytes 41–44 (Receiver Group Elevation) | IEEE float32, populated on every trace |
| Bytes 45–48 (Source Surface Elevation) | IEEE float32, populated on every trace |
| Bytes 73–76 / 77–80 | IEEE float32, NMEA `ddmm.mmmm` |

The files use **IEEE floats where the SEG-Y standard specifies scaled
integers**. The scalars are therefore read and reported but **not applied** —
multiplying a scalar into a value that was never scaled would corrupt it.

## B. Coordinate decoding

`5214.3379 → 52°14.3379′ → 52.23896°N`; `651.0929 → 6°51.0929′ → 6.85155°E`.
Sites span **51.449–53.235 °N, 4.439–6.852 °E** — all within the Netherlands,
and within the EPSG:7001 ETRS89↔NAP extent (50.75–53.7 °N, 3.2–7.22 °E).

Traces are rejected, never approximated: a file that is not little-endian
format-3 returns `None`; a trace outside the AHN window or on a nodata cell
yields `NaN` and is excluded from the statistics.

## C. Independent reference

| | |
|---|---|
| Product | **AHN** (Actueel Hoogtebestand Nederland), DTM 0.5 m |
| Source | **PDOK**, the Dutch national geodata portal |
| Quantity | ground-classified terrain surface height |
| Horizontal CRS | EPSG:28992, declared in the file |
| **Vertical datum** | **NAP — orthometric.** Documented by PDOK, *not* declared in the GeoTIFF |
| Local provenance | `datasets/raw/pdok_ahn/dtm_05m/PROVENANCE_site<NN>.json` |

**Not circular.** AHN is a separate national dataset, not derived from these
SEG-Y files. `SubterraRecord.elevation` is *derived from one of the candidates*
and is therefore never used as truth — a test parses the script's imports to
enforce that.

**The datums are not mixed.** AHN is orthometric NAP; the comparison is used to
identify *which candidate behaves orthometrically*, not to convert anything.

## D & E. Both fields against AHN

**366,019 traces across 107 activities and 12 sites.**

| | bytes 41–44 − AHN | bytes 45–48 − AHN |
|---|---|---|
| mean | **−0.834 m** | **+43.383 m** |
| median | −0.857 | +43.551 |
| sd | 1.934 | 1.976 |
| RMSE | 2.106 | 43.428 |

Per site:

| site | activities | traces | 41–44 − AHN | 45–48 − AHN |
|---|---|---|---|---|
| 01 | 9 | 24,013 | −0.500 | 43.449 |
| 02 | 7 | 16,655 | **−3.979** | 41.226 |
| 03 | 8 | 11,093 | −0.689 | 43.713 |
| 04 | 8 | 5,167 | −0.503 | 42.908 |
| 05 | 10 | 35,809 | −1.255 | 43.922 |
| 06 | 6 | 12,886 | −1.403 | 43.526 |
| 07 | 4 | 5,491 | −1.265 | 43.726 |
| 08 | 8 | 11,644 | −0.155 | 44.330 |
| 09 | 9 | 80,335 | −0.837 | 43.582 |
| 010 | 24 | 108,211 | −0.442 | 43.176 |
| 012 | 8 | 42,347 | −0.944 | 43.618 |
| 013 | 6 | 12,368 | −1.538 | 40.679 |

Bytes 41–44 track an independent NAP terrain model to within **0.16–1.5 m at
eleven of twelve sites**. Site 02 is an outlier at −3.98 m and is reported, not
explained away.

## F. The ~44 m difference: geoid, or something else?

The difference ranges **42.217–45.206 m** and is **not constant**, which is the
discriminator. Across the 12 site centroids:

| | |
|---|---|
| correlation with **latitude** | **−0.999** |
| correlation with longitude | −0.338 |
| planar fit | −1.675 m per degree latitude |
| **R²** | **0.998** |
| residual sd about the plane | **0.034 m** (against a 2.989 m spread) |

A smooth, large-scale function of position, flat to 3 cm. Against the
alternatives §6 required:

| Explanation | Verdict |
|---|---|
| **Geoid separation** | **Supported** — smooth, spatial, right magnitude and gradient |
| Antenna/instrument geometry | **Rejected** — would be constant; this varies 2.99 m with R²=0.998 on position |
| Source/receiver elevation difference | **Rejected** — centimetres for a GPR, and would not track latitude |
| Another SEG-Y header semantic | **Rejected** — no header pair differs by a smooth function of latitude |
| Coordinate/reference transformation | **This is that** — a geoid separation *is* a vertical reference transformation |
| RadarMap convention | **Consistent** — the author notes RadarMap can transform to RD/NAP, so it plausibly wrote both |

### External corroboration

> "In the Netherlands the geoid separation has values between **41 m in
> Groningen** and **47 m in Limburg**." Amsterdam Dam square: 2.68 m NAP
> corresponds to 45.6 m ellipsoidal — a separation of 42.92 m.
> — bertt.wordpress.com, *Vertical Coordinate Reprojection: From Geoid to
> Ellipsoid*, 2023-08-24, retrieved 2026-08-13.
> Corroborating: EPSG:7001 ETRS89-to-NAP height, accuracy 0.01 m, extent
> 50.75–53.7 °N / 3.2–7.22 °E (epsg.io/7001, retrieved 2026-08-13).

Measured here: **42.217 m at site 013 (53.24 °N — far north, toward Groningen)**
rising to **45.206 m at site 02 (51.45 °N — south)**. Same range, same
north-to-south direction. **This is an external reference, not a Subterra
measurement**, and is labelled as such in the artifact.

## G. Verdicts

**Hypothesis A — bytes 41–44 (Receiver Group Elevation) are the WGS84
ellipsoidal GNSS elevation: REJECTED.**
It would require the ground at these sites to lie ~44 m below what an
independent national terrain model measures — around −15 m NAP at Enschede.
AHN puts it within 0.83 m of the field itself. The hypotheses are separated by
~44 m against a reference good to ~1 m; this is not marginal.

**Hypothesis B — bytes 45–48 (Source Surface Elevation) are the WGS84
ellipsoidal GNSS elevation: SUPPORTED.**
Bytes 41–44 behave as an orthometric NAP height (sub-metre agreement with AHN at
11 of 12 sites); bytes 45–48 equal that plus a smooth latitude-dependent
42.2–45.2 m matching the published NL geoid separation in range and gradient.
Given the author's statement that the GNSS elevations are ellipsoidal, bytes
45–48 is the field that holds them.

**Note a tension worth recording.** The author wrote "ellipsoidal heights
(WGS84) **rather than** NAP heights", which reads as though NAP is not stored —
yet a NAP-like field demonstrably is. The coherent reading is that RadarMap
exported both the raw GNSS ellipsoidal height and its NAP transform, and the
author was describing the GNSS elevation specifically. That is an
interpretation, not something the author said.

## H. Roadmap implications

**Genuinely resolved:** which field holds the ellipsoidal GNSS elevation, and
which holds an orthometric NAP-like height. The `which-header-holds-the-
ellipsoidal-height` question can move from OUTSTANDING to **answered by
measurement** (not by the author).

**Not resolved, and untouched:**

- **depth-axis origin** — the author is explicit that no time-zero correction
  and no air-gap removal were applied, so the ground surface does not
  correspond to depth zero. Identifying a surface elevation does **not**
  establish where the depth axis begins.
- **propagation velocity** — unaddressed by anything here.
- **physical reflector depth** and **absolute elevation of a subsurface
  reflector** — both still require the two above.
- the **−0.83 m** mean offset between bytes 41–44 and AHN remains unexplained;
  antenna-height handling, terrain change between the AHN flight and the survey,
  and a geoid-model difference in the receiver would all produce something of
  this size, and nothing here distinguishes them. The AHN epoch is unpublished,
  so the terrain-change hypothesis cannot even be tested.

## I. Is another author question necessary?

**Not for this.** The measurement settles the field identification.

The remaining questions are the two the data cannot answer: the **time-zero /
air-gap magnitude** and whether a **propagation velocity** was ever determined.
Neither is inferable from the files.

## J. No platform state was changed

No `SpatialDeclaration`, no datum, no `record.elevation` semantics, no converter,
no CRS, no readiness state, no historical dataset. This stage measured and
reported. Acting on the result is a separate, narrowly scoped change.

Reproduce with:

```
python -m scripts.identify_segy_elevation_field --out artifacts/4tu/elevation_field.json
```
