# Thin client

`GET /client` — a deliberately minimal viewer over the existing Subterra APIs.

**This is not the production UI.** It exists to demonstrate that the backend
capabilities are real and reachable, and to make the platform's honesty
visible: what can be placed, what cannot, and why. It holds no identity logic,
no spatial mathematics, and no vertical model of its own.

## What it is built from

One static HTML file (`visualization/thin_client.html`), vanilla JavaScript,
served by a route that reads the file. **No new dependency**: Plotly was
already used by `visualization/viewer.html`, and `scattergeo` needs neither a
token nor a tile server. No build system, no framework, no bundler.

The existing `/viewer` page is untouched.

## What it supports

| view | status | notes |
|---|---|---|
| **Map** | working | `scattergeo`; one trace per provenance class, so measured and derived positions render with different marker shapes and appear separately in the legend |
| **Radargram** | working | Plotly heatmap from `/api/datasets/{id}/trace_grid`; y-axis labelled *"depth (m, derived from an assumed velocity)"* when depth exists, *"sample index"* when it does not |
| **Object list** | working | placed objects are selectable; unplaced ones appear under *Not on the map* with their reason |
| **Labels** | working | rendered with kind, source, provenance and confidence exactly as the API returns them |
| **Overlay composition** | working | relationship, basis, vertical status and notes from `/api/overlays/compose` |
| **Selection panel** | working | every view's resolution, with `reason` and `missing` verbatim for the unresolved ones |
| **Depth slice** | *unavailable, rendered as such* | needs a depth axis; across frames also a shared vertical reference |
| **3D scene** | *unavailable, rendered as such* | needs an absolute elevation |

## Views currently resolvable

For a geographic object with a member trace: **map, radargram, metadata**, plus
**depth_slice** when the selection carries a depth (i.e. a velocity was
supplied at ingest).

## Views unavailable, and why

**`scene_3d` is unavailable for every dataset currently held.** It needs an
absolute elevation, which needs a vertical registration that
[`vertical-reference-site01.md`](vertical-reference-site01.md) established does
not exist: the GPR depth axis starts at instrument time-zero rather than the
ground surface, and no source declares a vertical datum.

The client does not decide this. It POSTs the selection to
`/api/views/resolve` and renders whatever the backend returns — including the
reason and the list of what is missing. If a vertical registration is ever
supplied, the view resolves with no client change.

**`depth_slice`** is unavailable when no velocity was supplied (there is no
depth axis to slice) or when the slice would span frames that do not share a
vertical reference.

## How honesty is preserved

- **Nothing without a geographic position is plotted.** Unplaced objects and
  labels are listed separately with their reason and stay reachable through the
  API. There is no fallback coordinate anywhere in the page, and a test greps
  for one.
- **Measured and derived positions are visually distinct** — different marker
  shape, separate legend entry, provenance shown in the tooltip.
- **No Z is invented.** A test strips string literals from the script and
  asserts the code contains no velocity arithmetic and no assignment to a
  depth, elevation or z variable. The client may *display* depth the API
  derived; it may not derive any.
- **Identity is not duplicated.** Selecting anything builds a `Selection` from
  identifiers the API already returned and asks the backend which views can
  show it.
- **Association is not inferred from proximity.** Two co-located objects stay
  two objects unless the backend says they are associated.

## Five distinct empty states

The UI renders these differently and never collapses them:

| state | example |
|---|---|
| no data | *"No datasets ingested"* |
| data exists but has no geographic position | *"Not on the map"* list, with each item's reason |
| view unavailable — vertical registration required | the API's `reason` plus a `missing` list |
| association unavailable | composition shows `not_relatable` with its basis |
| actual error | red box with the HTTP status |

A 404 from the radargram endpoint renders as *"No radar data"*, not as an
error — a dataset with no trace grid is a legitimate state.

## Testing scope, stated plainly

`tests/test_thin_client.py` covers two things:

1. **the API guarantees the client leans on** — if those hold, a client that
   renders what the API returns cannot fabricate;
2. **the page's static structure** — no new dependency, no hard-coded
   coordinate, no local elevation maths, all five empty states present.

There is **no browser or DOM testing**, because the repository has no
JavaScript toolchain and this milestone was explicitly not to introduce one. A
rendering bug is therefore possible and would not be caught here. What is
caught is the class of failure that matters: an API that would let the client
plot something it should not.

## Data limitations that remain

- No dataset has an established vertical relationship, so 3D stays unavailable.
- Cross-survey tracking is unvalidated: no held dataset has repeat coverage of
  the same ground with acquisition timestamps.
- Detector candidates are not scored against truth; 4TU publishes no trench
  coordinates.
- The radargram uses the pre-existing `/api/datasets/{id}/trace_grid`
  endpoint, which requires the dataset to be registered through the ingestion
  route. Records written directly to the file store return 404, which the
  client shows as *"No radar data"*.
