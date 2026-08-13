# Declaring the 4TU vertical datum

Stage 19 established *what* the 4TU GNSS elevations are measured from (the
author). Stage 20 established *which stored field* holds them (measurement
against AHN). This stage records that in the platform, and changes nothing else.

## A. What is now recorded

One `SpatialDeclaration`, through the existing Stage 8 workflow — no new
declaration type, no new store.

| | |
|---|---|
| kind | `vertical_datum` |
| code | `WGS84 ellipsoidal` |
| `applies_to` | **`acquisition_elevation`** |
| `field` | `SEG-Y bytes 45-48 (Source Surface Elevation)` |
| provenance | `supplied_by_caller` |
| `supplied_by` | **Dr. ter Huurne, author of the 4TU dataset (direct written response)** |
| `verified` | **False** |

On the frame it lands in `acquisition_elevation_datum`, and as an `Assumption`
reading:

> SUPPLIED BY CALLER through the spatial reference workflow: vertical datum
> WGS84 ellipsoidal for the acquisition elevation (SEG-Y bytes 45-48 (Source
> Surface Elevation)), NOT the vertical axis, asserted by 'Dr. ter Huurne …'.
> This is a declaration, not a measurement.

**Attributed to the author, not to the signed-in user and not to Subterra.**
The account that entered it is in the declaration log as `declared_by_user_id`,
where an audit trail belongs; `supplied_by` is the authority for the claim.
Subterra has surveyed none of these elevations and the datum is not marked
verified anywhere.

**The two halves have different authors and are recorded separately.** The
author stated the datum. He did **not** say which field holds it — that is
Subterra's measurement against AHN (`docs/4tu-elevation-field-identification.md`),
and the declaration's note says so in those terms.

## B. Why the datum could not simply be "declared for the frame"

A 4TU GPR frame carries **two vertical quantities**:

| quantity | what it is | datum |
|---|---|---|
| `vertical_axis` | two-way travel time from **instrument time zero** | none exists; no geodetic datum describes a travel time |
| acquisition elevation | the **GNSS height of the instrument position**, per trace | WGS84 ellipsoidal, per the author |

Before this stage there was one slot. Declaring the author's datum would have
written it onto the time axis — asserting that instrument time zero is
referenced to the WGS84 ellipsoid, which is false — and would have advanced the
vertical-reference dimension on evidence that says nothing about the depth axis.

So `vertical_datum` declarations now name the quantity. **`vertical_axis` stays
the default and stays the behaviour every earlier caller got**, including Stage
12's datum → depth-origin → resolved workflow, which is untouched.

## C. What the assessment says now

`vertical_reference` moves **`missing` → `unresolved`**. That is not a readiness
transition; both are non-ready states carrying a non-empty `missing[]`.

Before, on a dataset where a datum had just been supplied:

> no frame declares a vertical datum

— which was no longer true, and whose `missing[]` asked for exactly what had
been given. Now:

> the acquisition elevations are declared as WGS84 ellipsoidal (SEG-Y bytes
> 45-48 (Source Surface Elevation)), but the vertical axis is `two_way_time_ns`
> and nothing says what THAT is measured from; a datum for a stored elevation
> does not reference the depth axis

**still missing:** a declared vertical datum for the vertical axis itself · where
the depth axis zero sits relative to the ground.

Carried alongside: `validated: false`, "Subterra has not surveyed these
elevations; this is the declaring party's statement about them".

**An acquisition-elevation datum can never produce `declared`.** It is not a
datum for the axis, and the code will not let it stand in for one.

## D. What did not move — verified on a real 4TU dataset

Ingested `01/01.1/Radargrams/Path8.sgy`, declared through the API, reassessed:

| dimension | after |
|---|---|
| horizontal position | `partial` — unchanged |
| CRS | `unresolved` — unchanged |
| **vertical reference** | **`unresolved`** (was `missing`) |
| depth | `derived` — unchanged; still the converter's uncalibrated 0.1 m/ns |
| surface | `unavailable` — unchanged |
| orientation | `missing` — unchanged |
| survey geometry | `available` — unchanged |

On the frame afterwards:

```
axis.kind           : two_way_time_ns          (unchanged)
axis.origin         : instrument time-zero at each trace   (unchanged)
axis.vertical_datum : None
axis.origin_offset  : None
acq_elevation_datum : WGS84 ellipsoidal / SEG-Y bytes 45-48
assumption.verified : False
```

Still blocked, and blocked for the same reasons as before:

- **depth-axis origin** — the author is explicit that no time-zero correction
  and no air-gap removal were applied. No offset was created, and none was
  inferred from the ~44 m difference between the two elevation fields, which is
  a geoid separation and not an instrument geometry.
- **propagation velocity** — nothing here addresses it.
- **physical depth** and **absolute elevation of a subsurface reflector** — both
  need the two above.

No elevation was transformed from WGS84 ellipsoidal to RD/NAP. No record was
rewritten. No historical dataset was touched: the declaration applies to the
dataset it was made against, and nothing back-fills.

## E. The tension that stays on the record

The author wrote the elevations are ellipsoidal "**rather than** NAP", which
reads as though NAP is not stored — yet bytes 41–44 track an independent NAP
terrain model to within 0.83 m. Declaring bytes 45–48 does not resolve that, and
does not relabel bytes 41–44: they remain an orthometric **NAP-like** field that
no author has confirmed as NAP. The coherent reading — that RadarMap exported
both the raw GNSS height and its NAP transform — is an interpretation, not
something the author said, and is recorded as one.

## F. Where a person meets this

The declaration form now asks **which quantity** the datum describes, with no
option preselected: the choice is made by the person declaring, not by the form.
It states, before submission, that an acquisition-elevation datum does not say
what the depth axis is measured from, does not place depth zero at the ground,
and does not supply a propagation velocity.

`tests/test_vertical_datum_scope.py` ·
`components/spatial/spatial-reference.test.tsx`
