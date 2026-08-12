# Spatial reference workflow

Stage 8. What relationship a dataset has to the physical world, how a person
establishes what Subterra cannot observe, and what the platform refuses to
assume.

The goal is not "make every dataset have coordinates". It is:

> **know, prove and communicate what spatial relationship the data actually has
> to the physical world.**

A dataset with insufficient evidence stays unresolved. That is a successful
result.

## What already existed

Almost all of the domain logic. Stage 8 rebuilt none of it:

| Concept | Where | State |
|---|---|---|
| CRS + provenance | `SpatialRef`, `CRSProvenance` | worked |
| Vertical datum | `VerticalDatum` | worked |
| Vertical/time axis | `VerticalAxis`, `AxisKind` | worked |
| Control points, ties | `GeoTie`, `ingestion/geo_tie.py` | worked — residual-checked, additive |
| Assumptions | `Assumption` | worked |
| Vertical relationship | `fusion.vertical_reference.assess` | worked |
| Velocity bounds | `converters.ids_dt_converter.validate_velocity` | worked |
| Per-view resolvability | `schemas/views.resolve` | worked |
| Provenance projection | `schemas/provenance.frame_provenance` | worked |

**None of it was reachable by a user.** There was no way to declare any of it
after ingest, and no single place that said which pieces were present. That —
not the physics — was the gap.

## What Stage 8 added

1. **A per-dimension assessment** (`schemas/spatial_reference.py`) — seven
   questions, each with its own vocabulary, reason, missing list and the
   declaration that would resolve it.
2. **An append-only declaration log** (`spatial_declarations`) — who claimed
   what, when, on whose authority, and what it superseded.
3. **A workflow** — inspect → resolve → recalculate, in one round trip.

## The seven dimensions

| Dimension | States |
|---|---|
| `horizontal_position` | available · partial · missing · unresolved |
| `crs` | declared · inferred · missing · invalid · unresolved |
| `vertical_reference` | declared · missing · unresolved |
| `surface_reference` | available · unavailable · unvalidated |
| `orientation` | available · missing · unresolved |
| `depth_conversion` | measured · declared · derived · unavailable |
| `survey_geometry` | available · partial · missing |

Per-dimension rather than one shared enum, because the distinctions differ: a
CRS can be `inferred` and a position cannot; depth can be `derived` and a datum
cannot. A single vocabulary would have to drop whichever distinction did not
generalise, and those are the distinctions that matter.

**Every unresolved dimension names what is missing**, and a test asserts it: a
blocker with no enumerated cause cannot be acted on.

## The distinctions the workflow preserves

```
coordinates exist          !=  coordinates are correct
a CRS is declared          !=  a CRS is validated
a time axis exists         !=  a physical depth exists
a DEM exists               !=  a usable surface reference exists
relative geometry exists   !=  absolute geolocation exists
```

Each is a separate field, not a shade of one.

### Depth: four states, and the first two are not the same

| | |
|---|---|
| `measured` | an instrument reported a depth. **No converter sets this**, and no dataset held reaches it — reserved so a genuinely measured depth has somewhere to be |
| `declared` | the *source* stated a depth. A CSV with a `depth` column is this: computed before the file reached us, by means we cannot see |
| `derived` | a caller supplied a velocity and the platform converted a measured time — an assumption about the ground, not an observation of it |
| `unavailable` | the time axis is still a time axis |

Radar time zero is when the instrument fired, not the ground surface. A velocity
turns time into a *distance*; it does not say what that distance is measured
from. Both facts are stated on the form that accepts a velocity.

## Declarations

`POST /api/spatial/{id}/declarations` with a `kind`, a `value` and a
`supplied_by`. Six kinds, each mapping onto a schema that already existed:

| Kind | Declares | Validation |
|---|---|---|
| `crs` | the horizontal reference | always `supplied_by_caller`; an EPSG code is refused for an engineering/acquisition frame |
| `vertical_datum` | what vertical coordinates are measured from | code required |
| `antenna_offset` | sensor-to-ground offset | **no default**; −10…10 m; states what it is measured between |
| `depth_conversion` | a propagation velocity | checked against `validate_velocity`'s physical bounds |
| `geo_tie` | control points | built by `build_geo_tie`; ≥2 points; ≥3 are fitted and residuals reported |
| `surface_reference` | another dataset as the surface model | link only — usability is decided separately |

**`supplied_by` is required.** A spatial claim with no author is
indistinguishable from a guess, and this workflow is the one place a guess could
enter the platform. It names the *authority* — a surveyor, a document — and is
recorded separately from the signed-in account, because the person typing may be
relaying somebody else's measurement.

**A user cannot declare that the source declared something.** Declaring a CRS is
always `SUPPLIED_BY_CALLER`; `DECLARED_BY_SOURCE` belongs to the file and is set
by the converter. Nor can a user mark a CRS `inferred` — an inference needs a
stated justification and a mechanism, and typing a code into a box is neither.

**Every declaration becomes an `Assumption` on the frame with
`verified=False`**, surfaced by the existing `frame_provenance` and the dataset
report alongside the converter's own assumptions. Nothing a user types is ever
promoted to a measurement.

### Order: validate, apply, then record

A declaration that cannot be applied to what is stored — a velocity for a
dataset with no time axis, a tie for a dataset with no odometry — is refused
with 409 **before** anything is written, so the log never contains a claim that
had no effect.

## Raw data immutability

Applying a declaration edits frame **metadata** — the reference a measurement is
expressed in — never a measured value. A test asserts the records file is
byte-identical across a CRS and datum declaration.

The apparent exception proves the rule: a GeoTie writes
`record.registered_position` and leaves `record.position` exactly as the
instrument reported it, so a bad tie can be replaced without having destroyed
what was measured underneath it. `position_provenance` keeps *native*,
*registered* and *derived* distinguishable afterwards.

## Audit and supersession

Append-only. A correction is a new row that supersedes the old one, with
`superseded_by` pointing at its replacement. *"What did we think the datum was in
March, and who said so"* stays answerable after somebody corrects it — which is
the reason for a log rather than a column.

## Downstream invalidation

A CRS, datum, tie or velocity changes what the data means, so anything computed
from the old reference describes a different world. Products computed before the
newest declaration are reported as stale (`has_stale_products`,
`stale_products`).

**Nothing is recomputed automatically.** Fusion is expensive, and re-running it
silently would hide the very change being reported. The state is made explicit
and the decision left to somebody who can see it.

## Surface models

Four different claims, kept apart:

```
a DEM exists  →  it is spatially registered  →  it has a valid elevation reference  →  it is usable as the survey surface
```

Linking a surface model records that somebody considers dataset X the surface
for dataset Y. Whether X can *anchor* anything is decided by its own frames: it
needs an elevation axis and a declared vertical datum. A DEM without them
reports `unvalidated`, however confidently it was linked.

**A DEM is never attached by geographic overlap.** Only an active
`surface_reference` declaration counts.

## The corpus, as it stands

Measured after Stage 8, with no declarations made:

| Dataset | horizontal | crs | vertical | depth | surface | orientation | geometry |
|---|---|---|---|---|---|---|---|
| Lazaresti COP30 DEM | available | inferred | missing | unavailable | unavailable | missing | missing |
| Lazaresti GPR depth slice | available | inferred | missing | declared | unavailable | missing | missing |
| INGV Site 1 GPR | missing | missing | missing | unavailable | unavailable | missing | available |
| INGV Site 1 GPR v2 | missing | missing | missing | unavailable | unavailable | missing | available |
| INGV Site 1 GPR v3 | available | inferred | missing | unavailable | unavailable | missing | available |
| INGV Site 1 GPR v3 (dup) | available | inferred | missing | unavailable | unavailable | missing | available |

Two results are worth reading carefully:

- **`crs: inferred`, not `declared`.** These frames were *reconstructed* from
  stored record positions, so their CRS was deduced by that reconstruction
  rather than stated by the source. Stage 6's report reported them as declared;
  the dedicated CRS dimension is more honest.
- **The Lazaresti DEM is still not a surface reference**, and Stage 8 does not
  make it one. Its vertical axis is `none`, its frame is reconstructed with
  origin "unrecorded", and 0 of 196 records carry an elevation. **The workflow
  cannot repair this** — there is no elevation to declare a datum *for*. It
  needs re-ingestion with the elevation preserved, and the assessment says so
  in the `missing` list rather than offering an action that would do nothing.

## External evidence

Requests to 4TU (the datum of the SEG-Y trace elevations; the antenna height or
time-zero convention per activity) and BAM (the absolute origin of the test-field
coordinate system) remain outstanding.

There is **no tracker for evidence requests** in this repository. Once an answer
arrives it can be recorded as a declaration with the source as `supplied_by`,
which preserves the attribution — but the request itself, its status and its
correspondence have nowhere to live. That is a genuine gap, documented here
rather than papered over with invented metadata.

## Access control

Unchanged mechanism. Reading uses `require_dataset_access`; declaring uses
`require_owned_dataset`, so published reference corpora can be inspected by
everyone and re-referenced by nobody. A non-owner gets **404, never 403**.
`/api/spatial/vocabulary` is public, pinned in the route-enumeration guard
alongside the other static capability vocabularies.
