# Metric-coordinate object matching (readiness R1(b))

- Module: `benchmark/metric_matching.py`.
- Tests: `tests/test_metric_matching.py`. All manifests in the tests are synthetic.
- **No detector, no production detection change, no real data.**

## What it does

It matches object-level candidates to buried objects in a **planar metric frame**. That is what `docs/post-pr17-acquisition-strategy-brief.md` §6 needs:
- **one unit per object**, with lines as repeated measures;
- tolerances in metres;
- a **detected-length fraction** for linear objects;
- **false alarms only inside verified-empty areas**.

## What it reuses

| Existing piece | How it is used |
|---|---|
| `benchmark.targets` manifest, frames and point/segment geometry | the truth input, unchanged |
| `TargetManifest.capability(LOCALIZATION_ERROR)` | the gate: matching is **refused** unless the frame declares its origin, its units and its registration to the radar |
| `benchmark.predictions.PredictionArtifact` | `candidates_from_artifact` adapts it, refusing frame, unit or CRS mismatches as `target_scoring` does |
| Polylines from `benchmark.survey_truth` (R1(a)) | optional `axes` argument (plain vertex lists, so this branch does not depend on R1(a)) |

`benchmark.target_scoring` (per line, in frame units) is **not changed**. The BAM scoring path is untouched.

## Rules (deterministic; ties broken by identifier)

1. **Feasibility.** A candidate is feasible for a target within its horizontal tolerance:

   h = max(`horizontal_m`, `horizontal_depth_fraction` × depth-to-top) (+ half the largest declared dimension for compact objects, if `add_half_size` is set).

2. **One target per candidate.** Each candidate goes to its nearest feasible target. It is never counted twice.
3. **Compact objects.** The nearest assigned candidate is the detection; the others are `duplicates`, which are not further detections and not false alarms. A candidate between two objects serves only the nearer one. This is conservative, not a global optimum.
4. **Linear objects.** Each assigned candidate covers ± `coverage_radius_m` of axis around its projection. The object is detected when the covered fraction reaches `min_length_fraction`.
5. **False alarms.** An unassigned candidate inside a verified-empty area is a **false alarm**. Elsewhere it is **unverified**, never false.
6. **Depth.** Depth error against the surveyed top is reported, with `within` when a depth tolerance is declared. **It never gates detection.**

**Excluded targets.** Objects excluded via `include_ids` (for example ineligible ones) still **absorb** nearby candidates. This prevents a response on a real but ineligible object from being called a false alarm.

**Declared, not defaulted.** Every tolerance, coverage radius and length fraction must be supplied by the caller and is echoed in the result. **The values are fixed by the validation protocol (R1(c)), not here.**

## Known limitations (recorded before any data)

- **The greedy nearest-first rule can under-count closely spaced compact objects** (rule 3). This is deliberate and conservative, and it is reported.
- **Coverage on linear objects treats candidates as points.** A detector that outputs line segments would need an extension.
- **No geodesic frames, and no transform between frames.**
