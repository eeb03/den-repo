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
| `simulation/run_gprmax.py` | The runner, and the only module that imports gprMax. `--rescore` re-validates a stored artifact without the solver. |
| `simulation/generator.py` | A seeded random scene generator (see "Scenario generator" below) |
| `simulation/build_corpus.py` | Resumable corpus builder with `index.json` |
| `tests/test_simulation.py`, `tests/test_simulation_generator.py` | Run in the platform image with no solver |

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

Corpus:

```
docker run --rm -v "$PWD:/app" subterra-gprmax:4.0.0 \
    python -m simulation.build_corpus --seed 0 --count 20
```

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

## Scenario generator (slice 2)

`generate_scene(seed, index)` is deterministic and independent of batch size.
These rules were fixed before any generated scene ran; each one's reason is
in the module docstring.

- **Frequencies:** 250 MHz, 500 MHz, 1 GHz, 1.5 GHz and 2.6 GHz. **Soil:**
  ε_r 3–25, with σ capped so the loss tangent stays ≤ 0.1. That keeps the
  low-loss velocity within about 0.15%.
- **Geometry in wavelengths:** an 8 λ-wide domain, 5 λ of soil, a 0.5 λ
  antenna offset and a λ/12 trace step. Every scene is therefore about a
  280 × 210 grid with about 80 traces, whatever its frequency or soil.
- **Cell size:** the largest multiple of 0.1 mm giving ≥ 12 cells per
  wavelength at 2.9 f. The first draft rounded down to a coarse list
  (1, 2, 2.5 mm …). That over-resolved some scenes by about 2×, which costs
  about 8× in 2D. It was changed before any generated scene ran.
- **Grid-snapped coordinates.** The truth is exactly what the solver builds.
- **Scene mix:** 20% empty, 50% single-target and 30% with 2–3 targets.
  Labels are pipe and cable (PEC), void (free space), and rock (ε 4–12,
  required to differ from the soil by at least 3).
- **Split:** train/val/test 70/15/15, decided by a hash of the scene
  fingerprint.
- Validation scores single-target scenes only. Empty and multi-target scenes
  are recorded as `not_applicable`, because the blind global-max picker is
  defined for one target.

**Cost** (Apple Silicon, 6 OpenMP threads): about 70 s per scene with a
target (two runs: the scene and its target-free twin), and about half that
for an empty scene.

### Finding: the strongest return is not the apex

The first generated scene, gen_s0_00004 (a pipe at 1 GHz, ε_r 8.03), FAILED
the pre-registered v1 apex check. Its travel times agreed to 27 ps RMS
against a 500 ps tolerance. The reflection amplitude is *lowest* near the
apex (0.86) and peaks in **two symmetric lobes about 33° off vertical**
(1.00 at traces 23 and 71; the apex is 47). This is the radiation pattern of
a dipole lying on a dielectric interface, which sends its energy obliquely.
"Strongest return = apex" was a physically wrong premise. It was not a
picker error.

**v2, kinematic vertex:** the apex is now the vertex of a least-squares fit
of t² as a quadratic in midpoint position, over the whole scan. This is
blind to amplitude, and so to the antenna pattern. Under v2:

| Scene | v1 (amplitude) | v2 (kinematic) |
|---|---|---|
| reference, `mean_trace` | trace 0, FAIL | trace 30, PASS |
| reference, `target_free_reference` | trace 30, PASS | trace 30, PASS |
| gen_s0_00004, both methods | traces 71 / 23, FAIL | PASS |

v2 is post hoc for these two scenes and pre-registered for every later
scene. Both v1 failures are archived (`validation_history/`,
`superseded_validations` in the manifest), and the v1 amplitude apex is
still recorded as a diagnostic. **Consequence for real data:** any detector
or UI that assumes the brightest pixel of a hyperbola marks the object's
position is biased by the antenna pattern. Localisation should be
kinematic.

Adding the `materials` field changed every scene's fingerprint. `rescore`
then correctly **refused** the old reference artifact as stale, and the
artifact was regenerated with identical results. (That refusal also exposed
an ordering bug: rescore archived the old verdict before checking the
fingerprint. It was fixed and is pinned by a test.)

### First corpus: seed 0, scenes 0–19 (2026-10-12)

The run took 1,579 s of CPU on the Mac, about 26 minutes. Split: 9 train, 7
val, 4 test. The corpus holds 7 empty scenes, 3 multi-target scenes (not
scored) and 10 single-target scenes.

| Scene | f, ε_r (soil) | Target | `target_free_reference` (pre-reg.) | `mean_trace` |
|---|---|---|---|---|
| 03 | 1 GHz, 21.93 | rock | PASS, 103 ps | FAIL (apex) |
| 04 | 1 GHz, 8.03 | pipe | PASS, 27 ps | PASS |
| 05 | 1.5 GHz, 15.05 | cable | PASS, 18 ps | FAIL (no hyperbola) |
| 06 | 1 GHz, 7.69 | void | PASS, 106 ps | PASS |
| 07 | 1.5 GHz, 20.1 | rock | PASS, 148 ps | PASS |
| 09 | 0.5 GHz, 24.67 | void | PASS, 274 ps | PASS |
| 10 | 0.5 GHz, 7.52 | pipe | PASS, 24 ps | PASS |
| 12 | 2.6 GHz, 16.87 | pipe | PASS, 4 ps | PASS |
| **13** | 1.5 GHz, 5.48 | rock | **FAIL, 1,400 ps** | FAIL |
| 14 | 1.5 GHz, 6.53 | pipe | PASS, 19 ps | PASS |
| 18 | 0.5 GHz, 7.38 | pipe | PASS, 16 ps | PASS |
| 19 | 0.5 GHz, 16.04 | rock | PASS, 208 ps | FAIL (no hyperbola) |

RMS values are hyperbola-shape time errors over the central 21 traces.
**11 of 12 pass** on the pre-registered method. `mean_trace` fails 4 of 12,
all weak or deep targets, which is further evidence against it.

**The gen_s0_00013 failure (open).** The apex is located exactly (39/39),
but every pick sits **+1.40 ns** late, uniformly across the scan. The picks
track the reflection from the **bottom of the rock**. A rough
straight-path estimate of the extra round trip (6.2 cm, ε_r 9.69) is
+1.30 ns. That bottom echo is the strongest (envelope 1.00 on the apex
trace), and the top reflection is present at 0.55. The solver is right.
`truth.py` predicts only the top reflection, and the global-max picker took
the stronger bottom one. The failure is recorded, not re-scored.

- **Open fix, in its own slice:** predict the bottom/internal reflection of
  dielectric targets (refraction through the circle), and score picks
  against the nearest predicted event. The method has already changed
  twice in this session, so it was not changed a third time here.
- **Unverified, plausibly the same cause:** dielectric targets (rock, void)
  show higher RMS (100–300 ps) than PEC targets (4–27 ps), consistent with
  top/bottom interference. That is still within tolerance.
- **Training labels are unaffected.** Geometry truth is exact. Only this
  sanity check of predicted travel times is incomplete for dielectric
  targets.

## Next

- Dielectric-target bottom reflections in `truth.py` (see gen_s0_00013).
- Grow the corpus. Locally this is about 80 s per scene, or about 45 scenes
  an hour. Kaggle or Colab is needed for hundreds of scenes, and for 3D.
- 3D volumes (gprMax 3D, Kaggle or Colab GPU), which feed the `SubsurfaceVolume`
  schema and the CT slice viewer (roadmap M2/M3).
