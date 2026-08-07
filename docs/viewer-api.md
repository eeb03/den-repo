# Viewer-facing API

The backend surface a thin client renders. No UI framework is assumed; every
endpoint returns data plus the reason for anything it could not answer.

**The governing rule:** an API that cannot locate or represent something says
so, with the reason and what is missing. It never returns a default
coordinate, a null geometry, or a height of zero.

## Endpoint map

| area | endpoints |
|---|---|
| provenance | `GET /api/provenance/vocabulary`, `/{dataset}/frames`, `/{dataset}/records`, `POST /candidates` |
| labels | `GET /api/labels/vocabulary`, `GET/POST/DELETE /api/labels/{dataset}`, `/{dataset}/disagreements`, `POST /{dataset}/from_candidates` |
| overlays | `GET /api/overlays/vocabulary`, `/{dataset}/layers`, `POST /api/overlays/compose` |
| objects | `GET /api/objects/vocabulary`, `/{dataset}`, `/{dataset}/associations`, `POST /{dataset}/associations`, `POST /{dataset}/resolve` |
| views | `GET /api/views/vocabulary`, `POST /api/views/resolve` |
| exports | `GET /api/exports/formats`, `/{dataset}/objects?format=…` |

Every area serves a `vocabulary` endpoint. Clients should read these rather
than hard-coding enum values — adding a class or format becomes renderable
without a client release.

## Synchronized views

One selection, resolved per view. Each view declares what it needs:

| view | requires |
|---|---|
| `map` | a geographic position |
| `radargram` | a frame and a trace index |
| `depth_slice` | a depth axis (caller-supplied velocity); across frames, also a shared vertical reference |
| `scene_3d` | an absolute elevation |
| `metadata` | identifiers only |

`POST /api/views/resolve` returns a `ViewResolution` per view — either
`resolved: true` with coordinates in that view's own terms, or
`resolved: false` with `reason` and `missing`. It also returns
`resolvable_views` and `unresolvable_views` so a client can lay out without
inspecting each entry.

**`scene_3d` is unresolvable for every dataset currently held.** Absolute
elevation needs a vertical registration that
[`vertical-reference-site01.md`](vertical-reference-site01.md) established does
not exist: the GPR depth axis starts at instrument time-zero rather than the
ground surface, and no source declares a vertical datum. The path is not
hard-coded shut — supply a vertical relationship where
`absolute_elevation_available` is true and it resolves — it is shut by the
data. A test asserts both halves.

Worked example, a geographic GPR candidate with depth:

```
OK  map          {lat: 52.24, lon: 6.85}
OK  radargram    {frame_id: ds:line, trace_index: 42, trace_range: [40, 44]}
OK  depth_slice  {frame_id: ds:line, depth_range_m: [1.1, 1.3], scope: single_frame}
NO  scene_3d     needs an absolute elevation; no dataset has an established
                 vertical relationship
OK  metadata     {kind: candidate, dataset_id: ds, ...}
```

An odometry selection resolves only `radargram` and `metadata` — the map
answer is *"odometry has no defined location on Earth"*, not `(0, 0)`.

## Objects and associations

Kept separable on purpose. An **association** is evidence and survives on its
own; an **object** is a resolution of the association graph at one score
threshold and is replaced wholesale when re-cut.

`POST /api/objects/{dataset}/resolve` with `min_score` re-cuts the graph.
Raising the threshold splits groups; the association evidence is untouched, so
nothing needs recomputing.

Status is earned, never assigned:

| status | requires | is a real thing |
|---|---|---|
| `hypothesised` | observations associated | no |
| `corroborated` | members from ≥2 **independent** acquisitions | no |
| `attested` | an attested ground-truth label refers to it | **yes** |

A detector agreeing with itself on one survey line does not reach
`corroborated`. Nothing reaches `attested` without a ground-truth label, which
itself requires an attestation.

## Overlays

Layers arrive in their **native CRS**. A WGS84 extent accompanies each as a
render hint marked `derived` (or `measured`, when the layer was already
geographic). Compositions report `co_registered`, `disjoint`, or
`not_relatable`; the last means at least one layer cannot be placed on Earth
at all, and the response says explicitly that such layers must be rendered as
unplaced rather than at a default coordinate.

The vertical relationship is reported separately, because horizontal overlap
says nothing about depth.

## Exports

| format | requires | full provenance |
|---|---|---|
| `json` | identifiers only | yes |
| `csv` | identifiers only | yes |
| `geojson` | a geographic position per feature | no |
| `czml` | a geographic position per feature | no |
| `3d_tiles` | an absolute elevation per feature | — |

Every export returns a `report` naming what was written and what was skipped
with its reason. Exporting 100 objects and receiving 40 features tells you
which 60 could not be placed.

- **GeoJSON** skips unplaceable features rather than writing a null geometry,
  which would read as a feature at no particular place. RFC 7946 mandates
  WGS84, so coordinates are marked `derived`.
- **CZML** omits `height` and sets `CLAMP_TO_GROUND`. Cesium interprets a
  missing height honestly; `0` would place every object at sea level.
- **CSV** names each position's *kind*, so an easting is never read as a
  longitude.
- **3D Tiles** returns **409 Conflict** — the request is well-formed, but the
  data cannot support it. The message names what would unblock it.
