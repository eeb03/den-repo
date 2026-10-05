# Subterra Volume V1: validation

**Date:** 2026-10-05 · **Branch:** `feat/subterra-volume-v1` · **Product doc:** `docs/volume-reconstruction.md`

## Summary

| Question | Answer |
|---|---|
| Can a real dense GPR grid become a reproducible 3D scientific volume? | **Yes.** BAM Pk266 at 1.5 GHz (401 × 161 × 512) becomes a 401 × 161 × 475 depth volume (5 × 5 × 1.9 mm voxels) in 7 s without migration, 15 s with Stolt. |
| Is any coordinate or depth invented? | **No.** Depth exists only after a known-geometry calibration and a surface reference were **declared in the UI**; before that the volume is time-domain. No Earth coordinates exist without a tie. |
| Does migration focus the known BAM targets? | **Ducts: yes, on every scan.** Lateral width falls from 90–185 mm to 50–70 mm; energy concentration rises from 0.45–0.63 to 0.78–0.94 (deep ducts); positions stay within ±10 mm in x and +2 to +12 mm in depth. **Foam cuboids: partially.** Small concentration gains on 3 of 8; one Rot90 cuboid has no localised response; transverse offsets get worse on Rot90. |
| Synthetic check | A point reflector focuses to the exact (x, y, z) within one voxel, and its lateral width falls below half the unmigrated width (`tests/test_volume.py`). |
| Browser | All 12 requested steps were verified in Chromium against the real BAM dataset. Five UX defects were found and fixed. |

## 1. What was validated, and how independently

- **Reconstruction inputs:** the radar grid, its declared geometry, and a depth model declared through
  the spatial workflow. The calibration is the 4 back-wall steps: times picked by the existing
  pre-registered rule, depths from the fabrication drawings. Drawn objects are only *excluded* from
  the back-wall windows. The surface reference is antenna offset 0 at the depth-axis origin, from
  the BAM acquisition documentation.
- **The drawn targets are never an input.** `tests/test_volume.py::test_reconstruction_never_reads_ground_truth`
  checks the AST of every `reconstruction/` module. Targets enter only:
  - the overlay endpoint (labelled **GROUND TRUTH — NOT INPUT TO RECONSTRUCTION**);
  - this evaluation (`scripts/bam_volume_focusing.py`).
- **Not a detector evaluation.** No threshold, no detection and no candidate is involved; the metrics
  describe the image around known positions.

## 2. Synthetic point reflector (mathematically known answer)

- **Setup** (`tests/test_volume.py::test_synthetic_point_reflector_focuses_where_the_maths_says`):
  - a zero-offset diffraction t = t0 + 2·√(Δx² + Δy² + z0²) / v with v = 0.12 m/ns and t0 = 0.5 ns;
  - a 64 × 48 × 256 grid at 5 mm;
  - a Ricker wavelet at 1.5 GHz;
  - three flat reflectors at known depths, used for the calibration.
- **Result:**
  - the migrated envelope peak sits at (x0, y0) exactly and at z0 within 3 voxels;
  - the lateral FWHM is less than half the unmigrated one;
  - a flat reflector at time t images at v·t/2 (`test_stolt_maps_a_flat_reflector_to_v_t_over_2`).
- **Scale check:** a 101 × 61 × 400 grid collapsed from 110 mm FWHM to 25 mm, at the exact
  (0.250, 0.150, 0.200) m.

## 3. BAM focusing: migration none vs Stolt F-K 3D

`python -m scripts.bam_volume_focusing --out evidence/bam/results/volume_v1_focusing.json`

**Scans:** every scan whose back-wall calibration is scientifically sufficient (Pk266 ducts at both
antennas and both rotations; Pk401 foam cuboids at 1.5 GHz, both rotations). Pk401 and Pk050 at
2.6 GHz have no accepted back-wall selection, so they get time-domain volumes only and are not
scored in depth.

**Calibrations used** (from the declarations):

| Scan | v (m/ns) | t0 (ns) |
|---|---|---|
| Pk266 1.5 Rot00 | 0.1289 | 1.081 |
| Pk266 2.6 Rot00 | 0.1289 | 0.963 |
| Pk266 1.5 Rot90 | 0.1279 | 1.011 |
| Pk266 2.6 Rot90 | 0.1291 | 0.951 |
| Pk401 1.5 Rot00 | 0.1026 | 0.623 |
| Pk401 1.5 Rot90 | 0.1020 | 0.597 |

**Metrics.** These were fixed before any result was computed:
- the envelope peak in a window (±150 mm laterally; from the drawn top −60 mm to +150 mm);
- its offset from the drawn position;
- FWHM through the peak;
- the share of window energy inside the drawn object, dilated by 20 mm.

Ducts are scored per line in the central band y ∈ [0.15, 0.65] m (median shown); cuboids once, in 3D.
Each cell reads **none → Stolt**.

### Ducts (Pk266), median over 101 lines

| Scan | Duct (top) | Lateral FWHM mm | Depth FWHM mm | Concentration | dx mm | dz vs top mm |
|---|---|---|---|---|---|---|
| 1.5 Rot00 | 1 (241 mm) | 180 → **55** | 43.5 → 45.4 | 0.45 → **0.92** | −20 → −10 | +4.9 → +3.0 |
| | 2 (181) | 160 → **55** | 37.8 → 41.6 | 0.50 → **0.94** | +5 → 0 | +4.3 → +2.4 |
| | 3 (118) | 160 → **70** | 39.7 → 43.5 | 0.56 → **0.92** | −5 → −5 | +7.0 → +5.1 |
| | 4 (61) | 100 → **65** | 35.9 → 39.7 | 0.27 → 0.34 | −5 → −10 | +3.4 → +3.4 |
| 2.6 Rot00 | 1 | 170 → **50** | 35.9 → 34.0 | 0.50 → **0.81** | −25 → −10 | +14.4 → +10.6 |
| | 2 | 150 → **50** | 35.9 → 34.0 | 0.54 → **0.81** | −5 → −5 | +6.2 → +6.2 |
| | 3 | 135 → **55** | 32.2 → 34.0 | 0.50 → **0.68** | 0 → −5 | +8.8 → +8.8 |
| | 4 | 90 → **65** | 35.9 → 35.9 | 0.37 → 0.45 | −10 → −10 | −2.3 → −0.4 |
| 1.5 Rot90 | 1 | 185 → **65** | 45.0 → 48.8 | 0.50 → **0.93** | −15 → 0 | +12.4 → +12.4 |
| | 2 | 150 → **60** | 43.2 → 45.0 | 0.59 → **0.93** | 0 → +5 | +8.5 → +8.5 |
| | 3 | 130 → **65** | 39.4 → 43.2 | 0.60 → **0.82** | 0 → 0 | +11.6 → +9.7 |
| | 4 | 100 → **65** | 39.4 → 39.4 | 0.22 → 0.24 | −5 → 0 | +8.5 → +8.5 |
| 2.6 Rot90 | 1 | 155 → **55** | 32.2 → 34.1 | 0.52 → **0.78** | −10 → −5 | +11.0 → +11.0 |
| | 2 | 140 → **50** | 37.9 → 36.0 | 0.63 → **0.79** | +5 → 0 | +6.5 → +6.5 |
| | 3 | 110 → **55** | 34.1 → 34.1 | 0.51 → 0.58 | 0 → −5 | +10.9 → +9.0 |
| | 4 | 90 → **60** | 41.7 → 36.0 | 0.30 → 0.32 | 0 → 0 | −2.2 → −2.2 |

**Verdict: migration makes every duct response more spatially concentrated and keeps it correctly
located.**
- **Lateral width:** shrinks by 1.4–3.4× on all 16 duct × scan combinations, to 50–70 mm. That is
  close to the 67 mm duct diameter plus the pulse footprint.
- **Concentration:** rises on all 16, strongly for the three deeper ducts.
- **Position:** stays within ±10 mm in x. Depth is unchanged in kind (+2 to +12 mm against the drawn
  top, consistent with the earlier product-path validation).
- **Depth width:** unchanged (32–49 mm). That is expected, because migration does not shorten the pulse.
- **The shallowest duct (61 mm)** gains little concentration. Its window starts at 1 mm depth and
  includes the direct-wave zone, which migration cannot remove.

### Foam cuboids (Pk401, 1.5 GHz), 3D

| Scan | Cuboid (top) | FWHM x / y / z mm | Concentration | dx / dy mm | dz vs top mm |
|---|---|---|---|---|---|
| Rot00 | 1 (240) | 115→95 / 150→115 / 39→47 | 0.60 → 0.70 | 0→−5 / 2→2 | +19 → +21 |
| | 2 (180) | 85→90 / 110→100 / 38→44 | 0.63 → 0.70 | 20→5 / 2→2 | +20 → +20 |
| | 3 (120) | 80→90 / 115→100 / 36→41 | 0.39 → 0.38 | 5→5 / 2→2 | +22 → +28 |
| | 4 (60) | 75→90 / 115→100 / 38→42 | 0.19 → 0.19 | 5→0 / −3→2 | +30 → +32 |
| Rot90 | 1 | 140→115 / 190→120 / 37→45 | 0.37 → 0.61 | 5→5 / 2→**−28** | +29 → +19 |
| | 2 | 110→110 / 145→50 / 36→43 | 0.40 → 0.57 | 15→10 / −13→**−33** | +33 → +21 |
| | 3 | **no localised response** (the peak is a laterally continuous event at the window's top edge) | 0.21 → 0.25 | — | — |
| | 4 | 115→110 / 65→50 / 40→42 | 0.17 → 0.17 | 10→10 / −38→−28 | +28 → +30 |

**Verdict: partially focused.**
- **Where it helps:** concentration rises on cuboids 1–2 at both rotations. Transverse width shrinks on
  every resolved cuboid.
- **Where it does not:** longitudinal width is unchanged or slightly wider on 3 of 4 (Rot00).
- **Known depth bias:** the response sits about 20–30 mm below the drawn top, as in every earlier study.
  The strongest envelope is in the block, not at its top.
- **Rot90 transverse offsets of −28 to −38 mm.** This is the one result that bears on registration. The
  Rot90 y-axis registration was only weakly established (Candidate V2 study: the y-mirror
  hypothesis scored within 0.01–0.04 of identity). A consistent ~30 mm transverse shift is a further
  reason to treat Rot90 y positions as **unverified**. This is recorded, not corrected.
- **The model does not fit these objects.** The point-scatterer migration model is not a void model.
  Focusing flat-topped void-analogue blocks is EXPERIMENTAL.

## 4. Browser verification (Chromium, real BAM dataset, real API)

`evidence/volume/browser_verification.json`; screenshots `docs/research/figures/volume_v1_bam_*.png`.

| # | Step | Result |
|---|---|---|
| 1 | Open the BAM dataset | Workspace opens; "Open volume viewer" link present |
| 2 | Construct the calibration | On the Spatial page:<br>• "or: Calibrate depth on known reflectors" (frame id prefilled), peak picks, 0.1 ns, the 4 back-wall points<br>• then the antenna offset (0 m at the depth-axis origin, acquisition documentation)<br>The depth dimension becomes **derived** |
| 3 | Preview | "Reconstruction is possible · Z: depth (m) · v 0.1289 m/ns · t0 1.081 ns · 401×161×475 · ≈ 276 MB · interpolation required: no" |
| 4 | Create | Confirmed in the UI; 6–24 s round trip |
| 5 | Viewer | XY / XZ / YZ / 3D panes and the crosshair readout |
| 6 | Drag through depth | Wheel over XY: 225.1 → 227.0 mm, one slice per event |
| 7 | Move the crosshair in XY | XZ slice 82 → 59, YZ slice 202 → 141; X = 0.700 m, Y = 0.290 m |
| 8 | XZ / YZ update | A click in XZ moved the XY slice to 43 (79.5 mm) |
| 9 | Inspect a voxel | Values; RECONSTRUCTED with its meaning; count 9; nearest 0 mm; method; v 0.1289 (calibrated) and t0 1.081 (calibrated) with the declaration id; source frame; local frame |
| 10 | Support overlay | Toggled; legend 100% reconstructed |
| 11 | Ground-truth overlay | Labelled in all 4 panes; drawn ducts and back-wall planes over the image; 3D wireframes |
| 12 | Layers distinct | Slice values byte-identical with the overlay on and off; the overlay comes from its own endpoint and is drawn on its own layer |
| + | 3D rendering | 10–19 fps on software WebGL (SwiftShader, headless); zoom, Fit volume and Reset view exercised |

**UX defects found by this run and fixed:**
1. The Depth dimension offered only a velocity, so the known-geometry calibration and antenna offset
   were unreachable from the UI. Dimensions now list alternatives, and the only frame id is prefilled.
2. A gridded dataset reported "no records, nothing to position". Its traces now report as declared
   grid nodes in a local frame.
3. Slice canvases collapsed to zero height.
4. Wheel stepping used a stale cursor and scrolled the page. It is now a non-passive listener with
   functional updates.
5. Dark-on-white grey mapping was replaced by the CT convention (strong = bright). The volume list
   now shows build time and id.

Remaining notes:
- The 404s in the console come from the existing workspace panes asking for record-based views of a
  record-less gridded dataset. Those panes handle the 404 as an absence.

## 5. Performance

See the table in `docs/volume-reconstruction.md` (`evidence/volume/performance.json`).
- **BAM (32 M voxels):** 6.8 s without migration, 15.3 s with Stolt; 2.1 GB peak; 288 MB stored.
- **127 M voxels:** 56 s and 6.4 GB.
- **Slices over HTTP:** 13–20 ms, 0.4–1.2 MB.
- **3D texture:** 4.5 MB by default.
- **Rendering:** 10–19 fps on software WebGL.

## 6. Limits

- One benchmark family (concrete specimens), two antennas, and a regular publisher-gridded array.
  Field surveys with irregular lines need a gridding stage V1 does not have: its output grid follows
  the measured lines.
- Stolt assumes constant velocity and zero offset. Layered media need a v(z) migration (e.g. phase
  shift), which is not implemented.
- The Rot90 y registration remains weakly established, and the cuboid offsets above reinforce that.
- Absolute elevation and georeferenced placement were tested only synthetically (affine tie), not on
  real georeferenced grids.
