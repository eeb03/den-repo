# Surface reference — the vertical anchor

Stage 11. Making it possible for any dataset to be a usable surface model, so
that a subsurface depth can eventually be measured down from something real.

## Why this is Stage 11

The roadmap listed **11 as "acquisition sessions"**. That label is obsolete:
Stage 10 (`958f7f0`) implemented `AcquisitionSession` with a full lifecycle,
capability/evidence separation and FileDrop convergence. Stage 12 in the old
list — a real hardware adapter — is blocked externally: no specific instrument
or protocol is identified, and building one speculatively is forbidden by the
brief and pointless without hardware.

So the next stage was chosen by dependency, not by label. Stages 8, 9 and 10 all
ended with the same finding recorded twice:

> The Lazaresti COP30 DEM cannot anchor anything. That is a re-ingestion, not a
> research problem, and it is the cheapest thing standing between the corpus and
> a vertically registered dataset.

**It is the only blocker on the road to reconstruction that needs no external
evidence.** Every other one — a vertical datum for the GPR frames, the
depth-axis origin, 4TU's and BAM's answers — waits on somebody outside this
repository. This one waited on a defect inside it.

## What was actually wrong

Two category errors in `converters/geotiff_converter.py`, both real, neither a
research problem:

**1. The elevation axis was inferred from the declared modality.**

```python
kind = AxisKind.ELEVATION_M if sensor_type == SensorType.LIDAR else AxisKind.NONE
```

A raster the operator called `lidar` got an elevation axis nobody had asserted;
one called `satellite` got `AxisKind.NONE`. The COP30 DEM was ingested as
satellite — which is what it is — so it could never anchor anything. The same
error points both ways: it invented an elevation claim for one raster and
suppressed a true one for another.

**2. `record.elevation` was never set by any raster ingest.**

The band value went to `signal` only. So even a frame whose axis said
`ELEVATION_M` produced records with no elevation, and `assess_surface` had
nothing to anchor with. This affected **every** GeoTIFF dataset, including AHN,
not just the DEM.

Neither fix invents anything. The numbers were already in the file and already
in `signal`. What was missing was somebody saying what they mean, and a
converter that recorded who said it.

## The declaration

`band_is_elevation` joins `vertical_datum` as an explicit caller declaration on
the same converter. Three states, and the difference matters:

| | |
|---|---|
| `True` | the caller asserts band 1 is elevation in metres |
| `False` | the caller asserts it is not |
| `None` | nobody has said; the modality inference is used **and recorded as an inference** rather than passing silently as fact |

Both outcomes land on the frame as an `Assumption` with `verified=False` —
nothing checked the band against anything — carrying either *"SUPPLIED BY
CALLER"* or *"INFERRED from the declared modality … this is a deduction, not
something the raster said."* The existing behaviour for callers who declare
nothing is unchanged, so no ingest path regressed.

When the axis is an elevation, the band value is also written to
`record.elevation`. `signal` keeps it either way, so nothing is lost when the
claim is absent or later withdrawn.

## Where a user makes the declaration

At the **FileDrop review step** — the hold point Stage 9 built for exactly this
kind of question. The checkbox appears only for a format whose converter can act
on it, and the backend refuses an option the detected format cannot use rather
than recording a claim that had no effect.

Unticked is the default and a legitimate answer. The copy says so.

## What this unblocks, and what it does not

Measured against the **real COP30 file** held in this repository:

| | vertical axis | records with elevation | `surface_reference` |
|---|---|---|---|
| as held today | `none` | 0 of 4 | `unvalidated` |
| band declared elevation | `elevation_m` | 4 of 4 (576.6–682.4 m) | `unvalidated` |
| band **and** datum declared | `elevation_m` | 4 of 4 | **`available`** |

Those elevations are the file's own values; 576–682 m is plausible for
Lazăreşti. Nothing was invented to produce them.

**This is the first configuration in the platform's history that reaches
`surface_reference: available`.**

It does **not** vertically register a survey. An absolute elevation needs three
things and this supplies one:

1. an elevation for the acquisition surface — **now obtainable**
2. a declared vertical datum shared by both frames — Stage 8's workflow, still
   requires somebody who knows it
3. a known offset from the depth-axis origin to the ground — **still missing**;
   every held GPR frame's origin is instrument time zero

A test asserts exactly that: a usable surface plus a depth axis whose origin is
instrument time zero still yields `absolute_elevation_available: False`.

## The held datasets were not modified

The COP30 dataset in the corpus is system data — readable by everyone, writable
by nobody — and still carries its old frame. The capability now exists to
re-ingest it correctly; doing so is a user action, and silently rewriting held
reference data to make a stage look successful is precisely what this platform
does not do.

## Ingest options

`ImportJob.ingest_options` (migration 007) records what the user declared at
review. Persisted rather than derived because it is a **claim that changed what
the converter produced** — no later inspection of the records could recover
whether somebody said the band was elevation or the modality inference guessed
it, and the frame's provenance points back to it.

`INGEST_OPTIONS_BY_FORMAT` maps formats to the options their converter can use;
anything else is a 422.

## Limitations

- **Nothing verifies the claim.** Subterra cannot check that band 1 really is
  elevation. It records who said so, unverified, like every other declaration.
- **No datum is inferred from a declared elevation.** Saying the band is height
  says nothing about what it is measured from; a test pins that.
- **Re-ingestion is the only route for already-imported rasters.** A declaration
  changes what the converter produces, and the converter has already run. Stage
  8's declarations write frame metadata and deliberately never rewrite records.
