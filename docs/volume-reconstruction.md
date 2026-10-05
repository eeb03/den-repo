# Volume reconstruction (Subterra Volume V1)

**Code:** `reconstruction/` (pipeline, migration), `schemas/volume.py`, `schemas/survey_grid.py`,
`database/{grid_store,volumes_store}.py`, `api/volumes.py`, `api/routes/volumes.py`,
`frontend/components/volume/`, route `/datasets/{id}/volume`.
**Validation:** `docs/research/subterra-volume-v1-validation.md`.

## What a volume is

A volume is a regular x/y/z grid of reconstructed values with every claim about it stated. It
answers one question:

> What scalar field has been reconstructed here, from which measurements, by which explicit process,
> and how well is each voxel supported?

It is a **separate product from the reconstructed scene** (`/api/scene`). The scene asks "what
individually placeable evidence do we have?" and deliberately never fills the space between
measurements. Neither product is built from the other.

## What a volume is not

- **Not an interpretation.** A volume shows "this reconstructed response exists here". It never says
  "this is a pipe". Candidate generation (production or research) is not its source.
- **Not a material property.** The V1 GPR field is radar response in arbitrary instrument amplitude
  units, optionally migrated. It is never called density, material, moisture, probability or mineral
  content.
- **Not filled.** A voxel with no measurement within the stated distance is empty (NaN). The viewer
  draws it as a checkerboard, never as zero.

## Inputs and refusals

A metric volume is built from a **gridded acquisition** (`schemas/survey_grid.GriddedAcquisition`).
This is one survey frame whose traces sit on a regular lattice. It is stored as a single
memory-mapped float32 array of shape (trace, line, time), not as per-sample records. Each axis
records its own count, origin, step, unit, the source of its numbers, and the source of its unit.

| Required | Where it comes from | Missing → |
|---|---|---|
| Line identities and their order | `line_axis` (index = identity, order = axis order) | refused |
| Along-line trace spacing | `trace_axis.step` | refused (the schema cannot be built without it) |
| Line-to-line spacing | `line_axis.step` | refused |
| Line orientation | `traversal` (lines run along the trace axis) | refused |
| At least two measured lines | `missing_lines` | refused: **a single line stays a 2D B-scan and is never extruded** |
| Metric horizontal units | axis `unit` | refused |
| A scientifically sufficient depth model | the frame's time zero, velocity and surface reference (`schemas.depth_model.frame_depth_readiness`) | **time-domain volume** (z = two-way time, ns) |

Preview (`POST /api/volumes/{dataset_id}/preview`) reports all of the following before anything is
built:
- what is resolved and what is missing;
- the z domain;
- the estimated shape, voxel size and server bytes;
- whether interpolation is required.

Creation (`POST /api/volumes/{dataset_id}`) requires `"confirm": true`.

## Depth vs time

| | Depth volume | Time-domain volume |
|---|---|---|
| Needs | a scientifically sufficient depth model: e.g. a redundant known-geometry calibration **and** a declared surface reference | a valid time axis |
| z axis | `depth`, metres below the calibrated surface: z = v (t − t0) / 2 | `two_way_time`, ns, raw instrument time |
| dz | v · dt / 2, so each depth sample is exactly one time sample (sub-sample t0 shift by linear interpolation) | dt |
| Migration | allowed | refused (no velocity) |
| Ground-truth overlay | allowed (BAM) | refused: the drawings give depths |

Time is never relabelled as depth. A velocity alone (with no time zero or reference) does not make a
depth volume.

## Coordinates

| | Local volume | Georeferenced volume |
|---|---|---|
| x, y | survey metres in the acquisition's own frame | the same metres, plus a horizontal registration |
| Needs | nothing beyond the grid | an `AffineTie` on the frame (the existing registration route) |
| Earth position | none, and none is invented | lat = a·x + b·y + e, lon = c·x + d·y + f, rescaled from the frame's units to metres |
| Absolute elevation | no | **no in V1**: z stays depth below the calibrated surface |

A BAM specimen is a valid local volume. No DEM, CRS or absolute elevation is needed to inspect it.

## The reconstruction pipeline

Every stage is recorded on the product (`processing`, `migration`, `interpolation`).

| Stage | What it does |
|---|---|
| **A. Acquisition normalisation** | The stored array, in (trace, line, time) order exactly as registered; raw amplitude as float32; missing lines stay empty. |
| **B. Preprocessing** | Dewow (2 ns running mean; on by default). Optional line-mean background removal, which also removes real flat reflectors such as a back wall, and says so. **No gain** on the scientific field. |
| **C. Depth** | With a sufficient depth model: shift by t0 (linear sub-sample), dz = v·dt/2. Otherwise time. |
| **D. Migration** | `none`, or **Stolt F-K 3D**: constant velocity from the frame's active depth model (never estimated here); exploding reflector (v/2); zero offset; Jacobian kz/\|k\|; zero padding of 32 traces and 25% in time. Spatial aliasing is checked against the quarter-wavelength rule at the 95% spectral frequency and reported. Refused without depth or over a grid with missing lines. |
| **E. Grid formation** | Output lines at the measured spacing, or at a requested spacing. Three cases: **at a measured line** (within 0.1 spacing); **`nearest_no_fill`** (the nearest measured line within half a spacing); **`linear_bounded`** (linear between bracketing measured lines only when their gap is ≤ `max_gap_line_spacings` × spacing, default 2). Anything else is UNSUPPORTED. |
| **F. Derived field** | `response_envelope` = \|Hilbert\| of `radar_response` along z, as a separate field. |

**Display is not data.** Window, level, gain and polarity are viewer settings. The scientific values
are never rescaled or overwritten. The 3D texture is a labelled DISPLAY-ONLY block-max downsample.

## Support and provenance per voxel

| Field | Meaning |
|---|---|
| `support_class` (uint8, per voxel) | `MEASURED` (at a measured trace and sample) · `RECONSTRUCTED` (at a measured trace, computed from many traces by migration) · `INTERPOLATED` (between measured lines within the stated distance) · `UNSUPPORTED` (empty) |
| `nearest_distance` (per x/y column) | distance to the nearest measured line, m |
| `support_count` (per x/y column) | measured traces within one native spacing |
| voxel endpoint | x, y, z (with unit and meaning); every field's value; support class and meaning; count; nearest and interpolation distance; reconstruction method; migration (method, velocity and its basis, t0 and its status); depth-calibration provenance (declaration id, fit); source frames; coordinate-frame kind; validation status |

## Staleness

A volume stores a fingerprint of its inputs, in named components:
- source records (the array SHA-256);
- line geometry;
- frame registration;
- velocity / depth calibration;
- applied time zero;
- active declarations;
- preprocessing and migration configuration;
- method version.

Every read recomputes them. A changed component makes the volume **stale**, names what changed, and
suggests regeneration. **Nothing is rebuilt automatically.**

## Viewer

`/datasets/{id}/volume` (also linked from the dataset workspace as "Open volume viewer"):
- **Panes.** XY (C-scan), XZ and YZ slice panes, plus a WebGL2 ray-marched 3D pane, all on **one
  canonical cursor** (`frontend/lib/volume.ts::VolumeCursor`, index-based).
- **Slice-pane interaction.** Click or drag moves the crosshair; the wheel steps the slice (drag
  through depth in XY); ctrl/cmd + wheel zooms; shift-drag pans. Each pane also has a slice slider.
- **3D pane.** Opacity transfer and amplitude threshold, clipping in x, y and z, the three cursor
  planes, and double-click on a plane to move the cursor.
- **Display controls.** Window, level, gain, polarity (signed / inverted / absolute), slab thickness
  (mean over a centred slab), field (signed response or envelope).
- **Support controls.** The support overlay (interpolated tinted amber, empty as a checkerboard),
  "show interpolated voxels", and a support legend.
- **Navigation.** Go to coordinate, Fit volume, Reset view, and a staleness banner.
- **Ground-truth overlay (BAM only).** Opt-in; a separate magenta dashed layer labelled **GROUND
  TRUTH — NOT INPUT TO RECONSTRUCTION**; served by its own endpoint and never mixed into slice values.

## API

| | |
|---|---|
| `POST /api/volumes/{dataset_id}/preview` | feasibility, resolved and missing inputs, shape, bytes |
| `POST /api/volumes/{dataset_id}` | build; needs `confirm: true`; owner only; 409 with reasons when refused |
| `GET /api/volumes/{dataset_id}` | list, with staleness |
| `GET /api/volumes/{dataset_id}/{id}` | metadata, staleness, support meanings |
| `GET …/{id}/slice?orientation=xy\|xz\|yz&index=&field=&thickness=` | float32 values + uint8 support (base64) |
| `GET …/{id}/voxel?i&j&k` | full voxel provenance |
| `GET …/{id}/render3d?field&max_dim` | bounded DISPLAY-ONLY uint8 texture |
| `GET …/{id}/ground_truth` | BAM drawings in volume coordinates, labelled |
| `DELETE …/{id}` | owner only |

Visibility follows the dataset (`require_dataset_access`); creating and deleting need ownership.

## Performance (measured; `evidence/volume/performance.json`)

| Grid (x × y × z) | Voxels | Build, no migration | Build, Stolt | Peak RSS (Stolt) | Stored |
|---|---|---|---|---|---|
| 201 × 81 × 495 | 8.1 M | 2.0 s | 5.4 s | 0.9 GB | 73 MB |
| **401 × 161 × 495 (BAM)** | **32 M** | **6.8 s** | **15.3 s** | **2.1 GB** | **288 MB** |
| 601 × 241 × 495 | 72 M | 17.3 s | 31.0 s | 3.9 GB | 646 MB |
| 801 × 321 × 495 | 127 M | 29.5 s | 55.6 s | 6.4 GB | 1.15 GB |

Measured on 4 CPU cores. The build limit is 200 M voxels (`MAX_VOXELS`), about 10 GB peak at the
observed ~50 bytes per voxel.

Over HTTP, for the BAM volume:
- **Slices:** 13 ms (XY, 421 kB), 20 ms (XZ, 1.2 MB) and 13 ms (YZ, 498 kB) median.
- **Voxel:** 9 ms.
- **3D texture:** 1.6 MB (`max_dim` 96), 4.5 MB (160, the default) or 20 MB (256), in 0.7–1.3 s.
- **Rendering:** 10–19 fps in headless Chromium on **software** WebGL (SwiftShader). A hardware GPU
  was not available to measure.

The whole volume never leaves the server.

## Multimodal and future fields

`PropertyField` carries property name, unit, value kind, method, uncertainty, evidence sources and its
support field. A later resistivity (ERT), velocity (seismic) or magnetic-anomaly field can occupy the
same grid with its own provenance.

A composition field (mineral or lithology probabilities or fractions) must name the sensors or assays
that measured composition. **GPR amplitude alone never yields one.** None is implemented.

## Status

| Part | Status |
|---|---|
| Gridded acquisitions, refusals, depth/time distinction, support model, staleness, API, viewer | ready for product use on gridded GPR |
| Stolt migration | validated on synthetic data and on BAM ducts (`docs/research/…`); EXPERIMENTAL for void-like targets |
| Georeferenced volumes | horizontal only; absolute elevation not in V1 |
| BAM registration (`scripts/register_bam_volume_dataset.py`) | benchmark onboarding path, not a general importer |

## What was reused, and what is new

Inspected before building: the scene and viewer, `SurveyFrame`, spatial declarations, the depth
model, fusion, three.js rendering, and the grid code.

| Reused unchanged | Why it fits |
|---|---|
| `SurveyFrame` (one frame per grid, as its docstring already allows for "a magnetometer grid") | declarations, ties and provenance attach exactly as for a line |
| The spatial declaration workflow (`api.spatial`), including `DEPTH_CALIBRATION` and `ANTENNA_OFFSET` | the volume's depth model is the frame's declared one; nothing new can set a velocity |
| `schemas.depth_model` (`frame_depth_readiness`, `velocity_model_of`, `frame_time_zero`) | the "scientifically sufficient" gate decides depth vs time |
| `AffineTie` | the only route to a georeferenced volume |
| `benchmark.bam_ingest` | the validated BAM grid mapping and amplitude path |
| Dataset ownership and visibility (`require_dataset_access` / `require_owned_dataset`) | volumes inherit the dataset's access rules |
| three.js (already a dependency) | the 3D pane; the scene component itself is untouched |

| New | Why it could not be reused |
|---|---|
| `GriddedAcquisition` + array store | the record store (JSONL `SubterraRecord`s) cannot hold 33 M samples |
| `reconstruction/` (pipeline, Stolt migration) | nothing in the repository migrates or grids; `preprocessing/spatial_grid.py` builds a 2D anomaly z-grid per line, not a volume |
| `VolumeProduct` and its store | the scene payload is a bounded point set that deliberately never fills space |
| Volume viewer | the scene's single 3D canvas has no slices, no shared cursor and no voxel provenance |

Changed in the spatial UI because browser verification required it: a dimension may now offer
alternative declarations, and gridded datasets report their grid nodes as positions.
