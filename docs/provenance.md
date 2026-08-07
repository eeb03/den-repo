# Provenance

Every number Subterra renders can say where it came from. This document is
the contract between the data model and anything that draws it.

## The seven classes

Ordered by how much the data vouches for them. `/api/provenance/vocabulary`
serves this list so a client never hard-codes it.

| strength | class | meaning |
|---|---|---|
| 5 | `measured` | an instrument recorded it |
| 5 | `declared_by_source` | the file states it about itself |
| 4 | `supplied_by_caller` | asserted at ingest, for this dataset only |
| 3 | `derived` | computed from other quantities by a stated rule |
| 2 | `inferred` | deduced from the data's own values, with a justification |
| 1 | `assumed` | taken as true without evidence, and labelled as such |
| 0 | `unavailable` | genuinely absent — not zero, not defaulted |

**`unavailable` is a value to render, not a gap to fill.** A viewer that
cannot distinguish "depth is 0 m" from "there is no depth" will eventually
draw the second as the first. That is the failure this whole model exists to
prevent, and it is why the class sits in the same enum as the others rather
than being represented by a missing field.

**Badge an object with its WEAKEST class.** An object is only as trustworthy
as its least-supported component. `summarise()` returns `weakest_class` for
exactly this purpose; showing the strongest would be backwards.

## It is a projection, not a store

`schemas/provenance.py` stores nothing. It computes every classification
from fields the frame and record already carry:

| source of truth | what it answers |
|---|---|
| `SpatialRef.crs_provenance` | horizontal CRS |
| `VerticalAxis.vertical_datum.provenance` | vertical datum |
| `VerticalAxis.kind` / `.conversion` | whether the axis is measured time or derived depth |
| `SurveyFrame.assumptions` (`basis`, `verified`) | each stated assumption |
| `position_provenance()` — native/registered/derived | where a coordinate came from |
| record metadata (`processing_applied`, `anomaly_reliable`, `velocity_source`, `acquisition_elevation_datum`) | signal stage, depth, elevation |

A converter that changes what it records changes what provenance reports,
with no second place to update and nothing to drift.

## Transitions worth knowing

These are asserted by tests, because they are where honesty is usually lost:

- **A raw amplitude is `measured`. After `process_gpr_traces` the same field
  is `derived`.** The record's `signal` is overwritten in place, so without
  this the processed value would keep claiming to be an instrument reading.
- **After `preprocess_trace_local_anomaly` it is still `derived`, and the
  basis says "not a physical unit"** — a z-score is a statistic, and drawing
  it on an amplitude colour scale is a category error.
- **A GeoTie-registered position is `supplied_by_caller`, never `measured`.**
  GeoTie is additive: `position` keeps the acquisition's own coordinate and
  `registered_position` holds the placement, so the promotion stays visible.
- **Fusion does not launder a coordinate.** Cross-CRS fusion reprojects for
  clustering only; it never writes back, so a projected record's provenance
  is unchanged afterwards. A test asserts this.
- **A depth is `derived` and names the velocity as an assertion about the
  subsurface, not a measurement of it.** With no velocity, depth is
  `unavailable` — not 0.
- **An elevation with no declared vertical datum is `inferred`, not
  `measured`**, however precise the number. See
  [`vertical-reference-site01.md`](vertical-reference-site01.md).

## Anomaly candidates

Nothing about a detector candidate is `measured`; a test enforces that.

| quantity | class | why |
|---|---|---|
| `evidence` | `derived` | measured off the z-score grid — a statistic, not an object |
| `characteristics` | `derived` | geometry computed from the supporting cells |
| `interpretation` | `derived` | a neutral shape class, explicitly **not** a physical-object claim |
| `ground_truth` | `unavailable` | a candidate is never a confirmed object |
| `lateral_extent_m` | `derived` or `unavailable` | absent when the traces carry no usable position |
| `depth_extent_m` | `derived` or `unavailable` | absent when the cells disagree on velocity |

## API

| endpoint | returns |
|---|---|
| `GET /api/provenance/vocabulary` | the classes, strongest first, each with its meaning |
| `GET /api/provenance/{dataset_id}/frames` | provenance per survey frame (`?frame_id=` to narrow) |
| `GET /api/provenance/{dataset_id}/records` | provenance for a capped sample of records |
| `POST /api/provenance/candidates` | provenance for candidates the caller supplies |

Every response carries both the full `provenance` list and a `summary` with
`counts`, `weakest_class` and `unavailable` (the quantities missing, by name).

A dataset ingested before frames existed still gets an answer:
`synthesize_frames_from_records` supplies a best-effort frame, and its
assumptions say so.

Record provenance is capped and sampled on purpose — provenance is constant
across a frame's records by construction, so a handful is representative and
a caller asking for millions is asking the wrong question.

## Worked example (real 4TU line)

```
FRAME prov_demo:Path13  ->  weakest_class = unavailable
   inferred             horizontal_crs        EPSG:4326
   measured             vertical_axis         two_way_time_ns
   unavailable          vertical_datum        None
   derived              depth_conversion      0.0999
   supplied_by_caller   assumption:gpr_velocity
   assumed              assumption:two_way_time_units
   derived              assumption:segy_byte_order
   supplied_by_caller   assumption:segy_coordinate_encoding
```

The frame is badged `unavailable` because it declares no vertical datum —
correctly, since that is what blocks comparing its elevations with AHN.
