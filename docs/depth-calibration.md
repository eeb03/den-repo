# Known-geometry depth calibration

**Declaration kind:** `depth_calibration` · **Code:** `schemas/depth_calibration.py`,
`api/spatial.py` · **Validated on:** BAM Pk266 through the product path (below).

## What it does

Radar depth is `depth = v · (t − t₀) / 2`, with two unknowns. This declaration fits both from
reflectors whose depth is **known without the radar** (a core, an as-built or fabrication
drawing, a known slab thickness, a survey), together with the two-way time at which each
reflection was picked on one survey line:

```
tᵢ = t₀ + 2 dᵢ / v        (least squares on the known depths dᵢ)
```

Applying it writes **both halves as a pair** onto that line's frame:
- the velocity, as the axis conversion (`velocity_basis: calibrated_from_known_geometry`);
- the time zero, as the applied result (`status: calibrated`, method
  `known_geometry_calibration`).

In the same request, it corrects the records' time and rederives every stored depth. Re-running
`/apply_time_zero` keeps the calibrated pair; it is not replaced by Method C.

## Request

`POST /api/spatial/{dataset_id}/declarations`

```json
{"kind": "depth_calibration", "frame_id": "<one line>", "supplied_by": "site engineer",
 "value": {"pick_convention": "peak", "pick_precision_ns": 0.1,
           "points": [{"depth_m": 0.21, "time_ns": 4.34, "depth_source": "fabrication_drawing",
                       "depth_evidence": "drawing sheet 2, step 3", "reflector_id": "bw-3"}]}}
```

Fields in `value`:

| Field | Required | Meaning |
|---|---|---|
| `points[].depth_source` | yes | one of `construction_record`, `design_specification`, `core_or_borehole`, `excavation`, `survey_instrument`, `tape_measurement`, `fabrication_drawing`. A radar-derived source (radar, GPR, two-way time, velocity, hyperbola, Method C, …) is refused by name. |
| `points[].depth_evidence` | yes | the document or measurement that gives the depth |
| `points[].reflector_id` | no | recorded so these reflectors can be excluded from any validation of the same calibration |
| `pick_convention` | yes | `onset`, `peak` or `zero_crossing`. Anything later compared with the calibrated depth must be picked the same way. |
| `pick_precision_ns` | no | default 0.25 ns |
| `fixed_t0_ns` *or* `fixed_velocity_m_per_ns` | no | allows a single point, by holding the other quantity fixed |

## Refusals

A refused calibration is a refused declaration (HTTP 422). Nothing is written, and the reason
names the rule. The fit is refused when:
- there is one point and nothing is held fixed;
- the points span less than 5 cm of depth;
- deeper reflectors were picked earlier;
- the velocity falls outside 0.01–0.30 m/ns;
- t₀ is not before the earliest reflection;
- a pick misses the fitted line by more than 3× the stated precision;
- leave-one-out fails: a held-out reflector is mispredicted by more than max(0.10 m, 2× its
  stated depth uncertainty).

A `depth_calibration` without a `frame_id` is refused (409): one line's picks calibrate one line.

## What it can claim

| Situation | Operational | Scientifically sufficient |
|---|---|---|
| ≥ 3 reflectors, leave-one-out passed | yes | **yes**, for t₀ and v (the depth also needs a declared reference) |
| 2 reflectors (exact fit, unchecked) | yes | no |
| 1 reflector with t₀ or v held fixed | yes | no |
| A later `time_zero` declaration replaces t₀ | yes | velocity: no |
| A later `depth_conversion` replaces v | yes | t₀: no |

Depth from a calibration is still **derived**, never measured, and `validated` stays false.

## Validation on real data (BAM Pk266, product path)

`python -m scripts.bam_calibration_product_path --out evidence/bam/results/calibration_product_path.json`

- **Data:** Harvard Dataverse doi:10.7910/DVN/FCMUJQ, CC0; `Pk266_Dataset.zip`, MD5
  `e43ea0991a1e7b842d4e20d89b0b30f7`.
- **Calibration:** only the four back-wall steps. They were picked by the research study's
  unchanged, pre-registered rule; depths are the fabricated thicknesses from the drawings.
- **Ducts:** picked by the study's unchanged known-position picker, and compared with the drawn
  duct tops. No duct was used to calibrate.
- **Pre-registered** before any output was seen: peak convention, 0.1 ns pick precision, the
  central line y = 400 mm.
- **Path:** the line is stored as records, the declaration is validated and applied by
  `api.spatial`, and depth is read back from storage.

| Scan | t₀ (ns) | v (m/ns) | Residual RMS (ns) | Leave-one-out (mm) | Duct error vs drawn top (mm) |
|---|---|---|---|---|---|
| 1.5 GHz Rot00 | 1.081 | 0.1289 | 0.092 | −19 … +14 | +7.1, +2.7, +5.4, +5.6 (mean **+5.2**) |
| 2.6 GHz Rot00 | 0.963 | 0.1289 | 0.059 | −13 … +9 | +9.0, +6.5, +7.3, +1.9 (mean **+6.2**) |

- Stored depths equal the fit's conversion (to 0.1 mm), and every record carries one
  derivation id.
- The consistent positive bias is expected. Ducts are picked at the crown reflection's envelope
  peak, while the drawing gives the duct top.
- For comparison on the same ducts, the research study reports Method C's t₀ at +43 mm and no
  time zero at +72 mm.
- `tests/test_bam_calibration_product_path.py` pins this result and runs whenever the archive is
  present.

**Limits:**
- One specimen and two antennas.
- On Pk050 and Pk401 at 2.6 GHz, the research study's back-wall selection itself was refused.
- Cuboid (void-analogue) depth remains experimental (+27 mm in the research study).
