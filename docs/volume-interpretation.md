# Volume interpretation (Subterra Interpretation V1): response regions

**Code:** `interpretation/volume_regions.py` (the rule), `schemas/region.py`, `database/regions_store.py`,
`api/regions.py`, `api/routes/regions.py`, `frontend/components/volume/region-panel.tsx` (plus the
region layer in `slice-pane.tsx` and `volume-3d.tsx`).
**Validation:** `docs/research/subterra-interpretation-v1-validation.md`.

## What a response region is

A **ResponseRegion** is

> a spatially coherent reconstructed response that exceeds an explicitly defined,
> target-independent evidence criterion.

It is measured in the volume's own physical coordinates, carries its support and provenance, and can
be reviewed by a person.

## What it is not

- **Not an object.** It is not a pipe, void, cable, utility or mineral. There is no class field, and
  nothing in V1 sets one. The UI labels every region "unclassified".
- **Not a probability.** The `evidence_score` describes the strength and quality of the
  reconstructed response (its components are listed below). It is never the chance that something
  is there.
- **Not a 2D detector run line by line.** Regions are found in the 3D volume, using x, y and z
  coherence of the migrated response at once.
- **Not ground truth.** A confirmed review is operator evidence (grade C), never grade A.

## Inputs and eligibility

- **Input:** a `VolumeProduct` field, `response_envelope` by default, with its support classes. A
  **migrated depth-domain volume** is preferred; the preview says so when the volume is not
  migrated.
- **Time-domain volumes** are allowed. Their regions are measured in **ns along z**, never in metres,
  and orientation (azimuth/dip) is not reported.
- **The run is refused when:**
  - the volume is **stale**;
  - the field is missing;
  - more than 50% of the volume is unsupported;
  - more than 50% of the volume is interpolated.
- **Nothing is generated when the viewer opens.** Generation is preview, then
  `POST … "confirm": true`.

## The rule (target-independent; every threshold is a ratio)

1. **Background per depth sample k:** the median and MAD (×1.4826) of the field over every supported
   voxel at k. `robust_z = (e − median_k) / MAD_k`. Per-k statistics absorb attenuation with depth.
2. **Local lateral contrast:** `e / local background`. The local background is the median of 8 × 8
   voxel block medians over a 0.20 m lateral window at the same k, so it is robust to the response
   itself.
3. **Seeds:** `robust_z ≥ 8` **and** contrast ≥ 3 **and** the voxel is MEASURED or RECONSTRUCTED.
   Interpolated voxels never seed.
4. **Growth (hysteresis):** connected components of `robust_z ≥ 4` **and** contrast ≥ 1.5 that
   contain a seed.
   - The contrast condition is what stops a laterally continuous layer (the direct wave, a back wall,
     a flat interface) from forming a region or bridging two responses. Such a layer fills its own
     lateral window, so its contrast is about 1.
   - It was added on the development scan, where without it two ducts and the near-surface band
     merged into one region.
5. **Connectivity:** **6** (face-connected), chosen deliberately. Voxels that only touch along an
   edge or corner do not join. 18 and 26 are selectable and covered by the ablations.
6. **Morphology:** none by default. An optional single 3 × 3 × 3 binary closing is recorded in the
   config.
7. **Size:** components under 40 voxels are dropped and counted.
8. **Stacked-lobe merging** (conservative). Two components merge only when **all** of these hold:
   - one sits directly above the other, with lateral footprints overlapping by at least 50% of the
     smaller;
   - the vertical gap is at most one pulse length (40 mm, or 0.6 ns in time);
   - the peaks are within 3 voxels laterally.

   Laterally separate responses are never merged; two reviewable regions are better than one
   over-merged one. Every merge is recorded.
9. **Support:**
   - a component with **no** measured or reconstructed voxel is refused;
   - one with under 50% such voxels is kept as **LOW_SUPPORT**, flagged and penalised;
   - a peak in an interpolated voxel is flagged.

Multiplying the volume by any constant leaves every region unchanged (tested). Nothing in the rule
reads a target, a drawing, a manifest or a candidate.

## Measurements per region

| | |
|---|---|
| Identity and frame | id, set id, volume id, dataset id, coordinate frame (local or georeferenced), z domain, **z unit** |
| Size | voxel count, lines spanned |
| Position | response-weighted centroid; peak location and index |
| Extent | bounds (physical and index); physical extent in x, y, z |
| Response | peak value, robust z and local contrast; integrated and mean response |
| Width | FWHM through the peak in x, y, z (contiguous run at ≥ half the peak) |
| Support | measured, reconstructed, interpolated and unsupported fractions; nearest-measurement distance statistics; the peak voxel's class |
| Shape | weighted PCA eigenvalues and axes, elongation √(λ1/λ2), flatness √(λ2/λ3), compactness (voxels / bounding box), azimuth and dip (depth volumes only) |
| Evidence | a modality-neutral list. V1 has one GPR entry; a future ERT, magnetic, seismic, borehole or composition field adds its own entry with its own unit and method |
| Mask | bit-packed over the region's own bounding box. **No voxel is ever a database row** |

## Evidence score (inspectable; not a probability)

`evidence_score = mean(response_strength, local_contrast, persistence_3d, support_quality) − 0.25 × (interpolation_penalty + boundary_penalty)`

| Component | Definition |
|---|---|
| `response_strength` | 1 − exp(−peak robust z / 20) |
| `local_contrast` | 1 − 1 / peak contrast |
| `persistence_3d` | min(1, lines spanned / 5) × min(1, traces spanned / 5) |
| `support_quality` | fraction of measured + reconstructed voxels |
| `interpolation_penalty` | interpolated fraction |
| `boundary_penalty` | 1 if the region touches a lateral edge of the volume (its extent may be truncated) |
| `compactness` | reported, not scored |

## Review

- **The question asked:** "Is this a genuine subsurface response worth retaining?" The answers are
  `confirmed_response`, `rejected_response` and `uncertain`. Nobody is asked what the region is.
- **The log is append-only** (`regions/reviews.jsonl`). The current state is the latest event, and the
  full history is shown. Each event freezes a snapshot of what the reviewer saw: score, centroid,
  bounds, voxel count, support and status.
- **Evidence grade** is C (operator reviewed), with `ground_truth_status: not_independently_validated`.

## Staleness

A region set records its source volume's id and fingerprint. It is **stale** when:
- the volume no longer exists or was regenerated;
- the volume's fingerprint changed;
- the volume itself is stale (the calibration, time zero, registration, preprocessing or migration
  changed);
- the algorithm version changed.

Nothing regenerates automatically.

## Viewer

On `/datasets/{id}/volume`, the right panel has a **Response regions** section:
- **Generation:** preview, then confirm.
- **Layer:** a show/hide toggle; a sorted list with score, extent, top depth, support status and
  review state; a staleness banner.
- **Selected region:** measurements, support, generation provenance, Go to centroid / Go to peak, and
  the review controls with history.

The regions are a **separate, labelled layer**: "RESPONSE REGIONS — unclassified".
- In XY, XZ and YZ they are green outlines.
- In 3D they are green bounding boxes.
- The selected region is amber everywhere.

Clicking a region in any slice pane, in the list, or on its 3D box selects it and moves the **one
shared cursor**, so all four panes show the same region. The magenta BAM ground-truth layer stays
separate and separately labelled. The 3D representation is a bounding box; the mask stays the
authoritative geometry.

## API (dataset-scoped; visibility follows the dataset, generating needs ownership)

| | |
|---|---|
| `POST /api/volumes/{ds}/{vol}/regions/preview` | algorithm, threshold method, estimated count, rejected tiny / no-seed / interpolation-only, refusals |
| `POST /api/volumes/{ds}/{vol}/regions` | generate (`confirm: true`) |
| `GET  /api/volumes/{ds}/{vol}/regions` | sets, with staleness |
| `GET  …/regions/{set}` | the set: regions without masks, each with its current review |
| `GET  …/regions/{set}/{region}` | one region with its review history and generation provenance |
| `POST …/regions/{set}/{region}/reviews` | `{status, notes}`, append-only |
| `GET  …/regions/{set}/slice_labels?orientation&index` | uint16 label image for one slice |
| `GET  …/regions/{set}/export` | label-free manifest for a future training corpus: crop bounds, mask, fields, support, spacing, z domain, orientation, modality, migration, calibration; the operator review is the only judgement and no class is inferred |

The routes are nested under `/api/volumes/{dataset_id}/…`, not `/api/regions/{id}`, so the existing
dataset authorisation guard covers them; a route-enumerating test enforces that.

## Limitations

- One modality (GPR), one benchmark family (BAM concrete specimens).
- Regions are found on the envelope, so polarity information is not used.
- Laterally continuous targets wider than the 0.20 m local window are suppressed by design. A
  continuous layer is not a region in V1.
- The evidence score ranks by response quality, so a strong response **below** a specimen's back wall
  (a multiple) can rank first. Physical plausibility against known geometry is not in the
  target-independent rule.
- The 3D view shows bounding boxes, not surfaces.
