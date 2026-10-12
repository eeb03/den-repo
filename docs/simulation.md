# Simulation (roadmap M1a)

Physics simulation is the zero-cost route to scoreable ground truth. The
platform holds 4 real trace-associated targets in its whole corpus (see
`docs/roadmap.md`, Learned Detector V1). A simulated scene, by contrast,
knows every target exactly because the solver was told where to put it.

**Simulated truth is not field truth.** Every artifact records
`"simulated": true` and `truth_kind: simulated_exact_by_construction`. A
result measured only on simulation is a simulation result.

## Pieces

| Path | Role |
|---|---|
| `docker/gprmax/Dockerfile` | Separate solver image, gprMax **4.0.0** (open-source FDTD). Never touches the API image's pins. |
| `simulation/scenario.py` | `Scenario2D` and rendering to a gprMax input file. Geometry is validated against the domain and the 10-cell absorbing boundary. |
| `simulation/truth.py` | Exact geometry, plus the straight-ray specular **predicted** reflection times. Kept apart in the manifest. |
| `simulation/analysis.py` | A blind picker plus **pre-registered** tolerances, scoring a B-scan against its truth |
| `simulation/run_gprmax.py` | The runner, and the only module that imports gprMax |
| `tests/test_simulation.py` | Runs in the platform image with no solver. Uses analytic fixtures. |

## Running

```
docker build -t subterra-gprmax:4.0.0 docker/gprmax
docker run --rm -v "$PWD:/app" subterra-gprmax:4.0.0 \
    python -m simulation.run_gprmax gprmax_reference_cylinder_bscan_2d
```

Output goes to `artifacts/simulation/<scenario_id>/`, which is git-ignored and
regenerable: `model.in`, `bscan.npz`, `truth.json`, `validation.json` and
`manifest.json` (solver version, scene fingerprint, SHA-256 of every file).

On Apple Silicon there is no linux/aarch64 wheel, so the image compiles
gprMax from source. That takes a few minutes once.

## Scope of the first slice

The first slice uses a 2D TM model, one homogeneous lossless-to-lossy soil,
and circular targets. The antennas sit on the surface. These restrictions are
what make `truth.py`'s travel times exact single-medium geometry. Lifting any
of them (an antenna height, layered soil, 3D) requires extending the truth
model first.

The first scene, `gprmax_reference_cylinder_bscan_2d`, is gprMax's own
published example, reproduced parameter for parameter. A disagreement is
therefore attributable to this module rather than to an unusual model.

## Validation rule (pre-registered)

The picker removes the mean-trace background, takes the Hilbert envelope, and
uses the global maximum per trace. It is never windowed around the
prediction. It must pass three checks:

- **Apex time:** within ½ dominant period (333 ps at 1.5 GHz).
- **Apex trace:** within 2 traces.
- **Hyperbola shape:** RMS time error over 21 traces within ½ period.

There is a known picker bias. Background removal pulls picks late by about
16 ps on the analytic fixture (about 5% of the tolerance), and this is pinned
in tests.

## Results: reference scene, 2026-10-12

| Item | Value |
|---|---|
| Solver | gprMax 4.0.0 |
| Platform | aarch64, OpenMP, 6 threads |
| Run time | 13.5 s for both runs (with-target and target-free) |
| B-scan | 637 samples × 60 traces; dt 4.717 ps; time offset 0 |

| Background method | Pre-registered? | Strongest trace (pred. 30) | Apex time error | RMS, traces 20–40 | Verdict |
|---|---|---|---|---|---|
| `mean_trace` | yes, before the first run | **0** | +54 ps | 56 ps | **FAIL** (apex position) |
| `target_free_reference` | post hoc here; pre-registered for later scenes | 30 | −7 ps | 5 ps (11 ps over all 60) | PASS |

**The pre-registered method failed, and that verdict is kept.** The
target's hyperbola spans the whole 12 cm scan, so the mean trace contains
its average. Subtracting the mean leaves a ghost at about 2.37 ns, which
wins on the weak flanks. The strongest pick landed on the first trace.

Subtracting the exact target-free twin confirmed that diagnosis. gprMax's
reflection then lies within about 2 samples of the straight-ray specular
prediction on every trace. **This validates the solver setup, the
scene-to-input rendering and the truth model together.** It also says
nothing yet about field data.

### Lessons carried forward

- Mean-trace background removal is unsafe when a target spans a large
  fraction of the line. This applies equally to real short GPR profiles and
  to the platform's own preprocessing. It is worth checking there.
- Every simulated scene now ships its target-free twin (`background` in
  `bscan.npz`). The runner scores both methods, and `pass` is based on
  `target_free_reference`.
- In this geometry, with antennas on the interface, mean-trace removal
  carries a +55 ps systematic lateness near the apex. With the exact
  background removed, that lateness disappears (−7 ps). It was therefore a
  picker effect, not a 2D line-source phase effect.

## Next

- A scenario generator (soils, objects, depths, frequencies) that yields a
  split corpus.
- 3D volumes (gprMax 3D, Kaggle or Colab GPU), which feed the `SubsurfaceVolume`
  schema and the CT slice viewer (roadmap M2/M3).
