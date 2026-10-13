# Hyperbola detector V2 (pre-registration)

**Branch:** `exp/hyperbola-v2`, from PR #12 (`exp/detector-saturation`). PR #12 stays unmerged and KEEP_EXPERIMENTAL.

**Status:** EXPERIMENTAL. Production behaviour does not change: `anomaly_grid_from_traces`, `TRACE_ANOMALY_WINDOWS`, `find_anomaly_candidates`, the threshold 3.0 and min_cells 3 are untouched. No production path imports anything this phase adds.

**Written:** 2026-10-12. This document is committed **before** any of the following:

- any grouping, fast-stack or calibration code is written;
- the fresh corpus (§4) is generated or simulated.

Sections 1–10 must not be edited after results exist. Results go in §11, and any deviation is listed there with its reason.

**Inherited facts (PR #12, synthetic test split now development-exposed).**

- The original hyperbola stack (`benchmark/hyperbola_stack.py`, cone 45°, δ = T/4, z ≥ 6.0) has these synthetic results at the primary condition:
  - recall 0.69;
  - precision 0.44;
  - 31 of its 53 unmatched detections are limbs.
- Its z threshold does not transfer:
  - at native sampling it gives 6.4 FP per scan;
  - on BAM it gives 6–59 FP per line.
- It costs 29 s per BAM line, and 1,029 s for one pass of a 7,130-trace 4TU line.

## 1. Question

Can three changes make the hyperbola-aware detector practically useful on real GPR data, without losing the synthetic recall it already has?

1. **Grouping:** suppress detections that belong to an already-detected hyperbola.
2. **A faster implementation.**
3. **A ground-truth-free calibration:** make the operating point mean the same thing on every corpus.

Detection, localisation and classification remain separate. Classification is out of scope.

## 2. Arms compared

| Arm | Statistic | Threshold | Grouping |
|---|---|---|---|
| **A0** production ring | `anomaly_grid_from_traces` | 3.0 (production) | none |
| **A1** original hyperbola | PR #12 stack, cone 45°, δ T/4 | 6.0 (PR #12 frozen) | none |
| **A2** original + grouping | as A1 | 6.0 | §3, frozen config |
| **A3** V2 | fast stack (§5) on canonical input (§6.1) | null-calibrated, per line (§6.2) | §3, frozen config |

**A1's statistic.** A1 is computed with the fast implementation once that implementation passes the equivalence gate C3. The fast implementation is algebraically the same statistic, so A1 still means the PR #12 detector. If C3 fails, A1 and A2 use the original implementation.

**Inference inputs.** The inputs are the same as in PR #12:

- traces;
- trace positions;
- sample interval and time offset;
- the antenna's nominal frequency;
- the data-derived time zero.

V2 adds only data-derived quantities: trace permutations of the line itself. **No inference input comes from simulator truth or from real-data annotations.**

## 3. Grouping / NMS (fixed now)

**Input.** The detections (components) of one line from `detect_line`, each located at its peak cell (x_D, t_D) with peak z_D and velocity v_D, the arg-max velocity at the peak.

**The fitted curve.** For each detection, the curve is the zero-offset point-diffractor curve with apex (x_D, t_D) at velocity v_D:

t_D(x) = t_z + sqrt((t_D − t_z)² + (2 (x − x_D) / v_D)²)

Its aperture is the 45° cone used by the stack.

**The support.** S_D is the set of cells (trace i, sample j) inside D's aperture where two conditions hold:

- |t_j − t_D(x_i)| ≤ δ_g;
- the envelope exceeds its line median + 3 × 1.4826 MAD.

The envelope is the one the stack uses.

**The rule.** Detections are taken in descending z. A detection B is **merged** into an already-kept detection A, and so not reported, when **all** of the following hold:

1. **Apex proximity:** |x_B − x_A| ≤ A's aperture half-width at t_A.
2. **On A's curve:** |t_B − t_A(x_B)| ≤ δ_g.
3. **Velocity compatibility:** |v_B − v_A| / v_A ≤ κ.
4. **Shared support:** |S_B ∩ S_A| / |S_B| ≥ ρ. If S_B is empty, B is **not** merged.

Otherwise B is kept.

**Why this does not over-suppress.** Two genuinely distinct targets close together each have an apex that is **not** on the other's curve, unless they are closer than about one Fresnel zone, in which case no zero-offset method can separate them. The rule therefore has no suppression radius. Condition 1 only bounds the search.

**Estimated depth** enters through t_D and v_D: the curve test is a depth test at the scene's own velocity.

**Grid** (8 configurations):

| Parameter | Values |
|---|---|
| δ_g | {T/2, T}, with T = 1/f_nominal |
| κ | {0.25, ∞} |
| ρ | {0.3, 0.6} |

**Selection** happens on the development data (§4.3), arm A2, threshold 6.0, primary condition:

1. Keep only configurations whose development recall is ≥ ungrouped A1 development recall − 0.02, and whose recall on the development close-pair and overlap families is ≥ A1's − 0.05.
2. Among those, choose the one with the highest development precision.
3. Break ties in favour of less suppression: smaller δ_g, then smaller κ, then larger ρ.

## 4. Data, splits and the fresh corpus (fixed now)

### 4.1 Fresh corpus `corpus_s1_v2`

**Draws.** Independent scene draws come from a new generator module `simulation/generator_v2.py`. It reuses `generator.py`'s physics, cell rule, wavelength scaling and grid snapping **unchanged**. Corpus seed is 1, and each scene is drawn from `np.random.default_rng([1, family_code, index])`.

**Families, 40 scenes each (280 in total).**

| Family | What is drawn | Purpose |
|---|---|---|
| `standard` | `generator.generate_scene(1, i)` itself, an independent draw of the PR #11 distribution | comparability with corpus_s0 |
| `weak_contrast` | 1–2 rocks with \|ε_rock − ε_soil\| ∈ [0.5, 2.5] | weak dielectric contrast |
| `deep` | 1–2 targets with centre at 3.5–5.5 λ; soil depth 7 λ instead of 5 λ | deep, weak, late echoes |
| `close_pair` | 2 targets at similar depth (centres within 0.25 λ); surface-to-surface gap 0.2–1.0 λ | nearby distinct targets |
| `overlap` | 2 targets, lateral separation 0.5–2.0 λ, depth difference 1.0–2.5 λ | crossing hyperbolas |
| `wet_conductive` | soil ε_r ∈ [15, 25], σ in the upper half of `max_conductivity` (loss tangent 0.05–0.10); 1–3 targets | wet, lossy soil |
| `empty_clutter` | no scored targets; 3–8 clutter stones (rock, radius 0.03–0.08 λ, \|Δε\| ∈ [1, 4], ids `clutter_k`); in half the scenes, a horizontal soil-layer interface at 1.5–4 λ (Δε ∈ [2, 6]) | empty scans with realistic clutter |

**Shared rules.**

- **Labels.** Every family except `empty_clutter` draws labels from LABELS. The rock rule is unchanged apart from the `weak_contrast` family.
- **Loss cap.** Conductivity stays within the existing loss-tangent cap of 0.1. That cap is where `truth.py`'s low-loss velocity holds to ~0.15%, so a higher-loss soil would need a new truth model and is **out of scope**. It is stated as a limit.
- **Layers.** The layer is the only new geometry: a `#box` of a second soil material below the interface depth.
  - It appears only in `empty_clutter`, which has no scored targets, so no predicted target event is affected.
  - `Scenario2D.to_dict()` omits it when absent, so every corpus_s0 fingerprint is unchanged, and a test enforces this.
- **Clutter stones** are physical scatterers.
  - They are kept in the target-free twin, so the oracle background removes only scored targets.
  - They are excluded from recall.
  - A detection in a stone's match window counts as a **false positive** and is classed `clutter_object`.
  - A detection within T of the layer's two-way time is classed `layer`.
- **Noise and conditions** are the PR #12 calibration and seeding. The primary condition is again `instrument_20spp | noise_4tu_median | mean_trace_subtraction`.

### 4.2 Splits of corpus_s1_v2

The split is decided by the SHA-256 of the string `"{family}:1:{index}"`: **dev 30% / eval 70%**. The key is the draw, so every variant of a draw shares its split. The split code is committed before the corpus is built.

The **eval split is not read by any code path until `simulation/hyperbola_v2_freeze.json` is committed**. The selection runner asserts this, as the PR #12 runner did.

Results are always reported **per family** as well as pooled.

### 4.3 Development data (the only data any choice may use)

- **corpus_s0, all 300 scenes.** Its test split is development-exposed by PR #12.
- **corpus_s1_v2 dev split.**
- **BAM.** For **profiling cost only** (runtime and memory), the dev scan Pk266 1.5 GHz may be used. Its detections are not used for any choice.

**Held out until the freeze:**

- the corpus_s1_v2 eval split;
- every BAM scan's detections, including the dev scan's;
- INGV-UNISA (50 lines);
- 4TU (40-file subset).

## 5. Fast stack and the computational criteria (fixed now)

**Profiling first.** Profile the PR #12 implementation with `cProfile` on fixed inputs (two synthetic lines and one BAM dev line), recording wall and CPU time per function.

**Optimisations considered.**

- **Templates.** On uniform trace spacing, the curve's sample offsets depend only on the trace offset k and the apex time. They do not depend on the apex trace. That allows one cached (n_samples,) index template per (v, k), a row gather in place of the per-cell `sqrt` and `take_along_axis`, and a shared ±k template.
- **Flat sums by prefix sums** over traces.
- **Float32 accumulation.** It is allowed only if the C3 tolerance holds.
- **Line parallelism**, as now.
- **Coarse-to-fine velocity search.** It is tested, and kept only if it passes C3.

**Irregular spacing.** Lines whose spacing is irregular by more than 1% (the median absolute deviation of the step over the median step) are first regularised onto a uniform grid at the median step by linear interpolation along x. This is part of V2's canonical input (§6.1).

**Computational criteria, measured on this machine** (Docker, 6 CPUs, 5.8 GB), one process per line:

- **C1, speed:**
  - The fast stack's median time per line on the 41 PR #12 BAM lines must be ≥ 10× faster than the original stack's.
  - V2's **total** time per BAM line, including its calibration permutations, must be ≤ the original stack's (29 s median).
- **C2, memory:** peak memory ≤ 1 GB on the largest 4TU subset line (7,130 traces), and on 4× the largest synthetic line.
- **C3, equivalence:** on uniform-spacing inputs, the fast stack's z and v̂ equal the original's within 1e-6 absolute in z (identical v̂ wherever z > 1). This is checked on fixtures and on 20 corpus_s0 lines.

**Quality is never traded for speed.** An optimisation that fails C3 is not used.

## 6. Synthetic-to-real calibration (fixed now)

**Diagnosis first, with no choice depending on it.** For corpus_s0 (primary condition and native), BAM dev, INGV and 4TU, the following are tabulated:

- samples per nominal period, traces per nominal wavelength (at εr 9), and the noise-floor ratio (the `noise_calibration` statistic);
- the duration of the direct wave (envelope above half its peak);
- the dynamic range after gain;
- **the distribution of the original stack's null component peak z**, under 8 trace permutations per line.

The aim is to explain why one z threshold means different false-alarm rates on different inputs.

INGV and 4TU are held out from choices but **may** be used for this diagnosis, because no parameter is chosen from it. The diagnosis is written up before eval.

### 6.1 Canonical input

Before the stack, V2:

1. Fourier-resamples each line in time to **20 samples per nominal period**, the instrument rate already used as primary;
2. regularises trace spacing (§5).

The stack then runs on the canonical line. Detections are reported in the original coordinates.

### 6.2 Null-calibrated threshold (ground-truth free)

For each line:

1. Draw **R_cal = 8** trace permutations, seeded by SHA-256 of the line identity.
2. Run the same stack, grouping and component rule on each.
3. Collect every null component's peak z.
4. Set the line's threshold z*(line) to the value at which the expected number of null detections per line equals **λ0**. That is the ⌈λ0 · R_cal⌉-th largest null peak, or **z_floor = 3.0** if there are fewer null peaks than that.
5. Never let z*(line) fall below z_floor.

The permutation keeps each trace's own temporal structure (ringing, residual direct wave, gain) and destroys only lateral coherence, which is what the statistic is meant to detect. So λ0 is a per-line null false-alarm rate, comparable across corpora.

**λ0 grid:** {0.1, 0.25, 0.5, 1.0}.

**Selection** happens on development data only (§4.3), arm A3, with grouping fixed from §3:

1. Maximise development recall subject to development precision ≥ 0.60 and FP per scan ≤ 1.0.
2. If no λ0 meets both, choose the one with the highest precision.
3. Ties go to the smaller λ0.

**λ0 is frozen once, for every corpus. No real-data tuning of any kind.**

## 7. Matching and metrics

**Matching and metrics** are those of PR #12 (`background_benchmark.score_located`, one-to-one, recall over scored targets, precision over all detections), extended by §4.1's two FP classes, `clutter_object` and `layer`.

- Missed targets have undefined localisation error, never zero.
- Lateral error is reported in λ and m.
- Depth error is reported with the detector's own velocity, and with the oracle velocity as a diagnostic.
- The bootstrap is over scenes: 2,000 resamples, seed 0.

**Breakdowns:**

- family;
- frequency;
- soil class;
- label;
- depth bin;
- strength (PR #12 bins);
- overlapping.

**Cost** is measured per line: CPU time, wall time and `tracemalloc` peak, in a separate pass with one process and no other jobs, so the timings are comparable.

## 8. Real data (fixed now)

**BAM.** This uses the PR #12 protocol and harness: the L-XZ rule, the held-out and control scans, and the harness check against published production numbers.

- **All 161 lines per scan** are scored for every arm, because the fast stack makes this affordable.
  - If V2's projected time for all 161 lines exceeds 4 h per scan, the 41 PR #12 lines are used instead, for **every** arm, and this is recorded.
- A1 and A2 use their synthetic-frozen 6.0. A3 uses its calibrated z*.
- **Nothing is tuned on BAM.**

**INGV-UNISA** (50 content-unique lines) and **4TU** (40-file subset) use the PR #12 files and runner. For each line and arm:

- the candidate count;
- the ≥ 3-trace count;
- a trace-permutation null with **N = 99 draws**, so p = (1 + #{null ≥ observed}) / 100 and the smallest attainable p is 0.01.

**Reporting:**

- per-line p, with the number of lines at p ≤ 0.05 against the 5% expected under the global null;
- a corpus-level p from the 99 permuted corpus totals.

**Fallback.** If 99 draws on a line would take over 30 min for one arm, that line reports the null mean ± sd from as many draws as fit, with **no p-value and no significance claim**. The line is listed.

**4TU** also reports `score_activities`. With 4 trench-empty activities, its AUC is reported with an exact permutation interval and is **not** a gate.

## 9. Decision gate (fixed now)

On the corpus_s1_v2 **eval** split, primary condition:

| Gate | Criterion |
|---|---|
| **G1, recall** | A3 pooled recall ≥ 0.50, **and** A3 `standard`-family recall ≥ 0.60, **and** A3 pooled recall ≥ A1 pooled recall − 0.05 |
| **G2, false positives** | A3 pooled precision ≥ 0.60, **and** A3 FP per empty scene (standard empties + `empty_clutter`, pooled) ≤ 0.5 |
| **G3, nearby targets** | A3 recall on `close_pair` ≥ A1's − 0.10, **and** on `overlap` ≥ A1's − 0.10 |
| **C1, C2, C3** | §5 |
| **R1, BAM** | On every held-out scan, A3 recall ≥ production's published recall on that scan, **and** on each control, A3 FP per line ≤ 2× production's (5.58 at 1.5 GHz, 3.40 at 2.6 GHz) |
| **R2, INGV and 4TU** | A3 candidates per line ≤ 2× production's on each corpus. Significance against the 99-draw null is **reported, not gated**. |

| Verdict | Condition |
|---|---|
| **PROMOTE FOR FURTHER VALIDATION** | G1, G2, G3, C1, C2, C3, R1 and R2 all pass |
| **KEEP_EXPERIMENTAL** | G1 passes and any other gate fails or cannot be measured |
| **REJECT** | G1 fails |

**Explicitly not claimed, whatever the verdict:**

- field reliability;
- generalisation beyond the families simulated;
- 3D behaviour.

A synthetic pass is a pass on simulated 2D TM data only.

## 10. Scientific follow-up (separate from detector work; no detector choice depends on it)

**Observation (from existing corpus_s0 validation files, before this document).** The apex-time residual of the validation picker is **positive in every frequency group**. Its median is 0.02–0.10 of a period. Scene 13's 112 ps at 1.5 GHz is 0.17 T. Halving the cell cut it by 30%.

**H_2D.** A 2D TM simulation radiates from a **line** source. The 2D Green's function has a √t-type tail, which delays and broadens the received pulse relative to the 3D/ray assumption in `truth.ricker_peak_delay`, by up to about T/8 at the envelope peak. This delay does not converge with the cell size.

**Tests.**

1. **Analytic.** Convolve the gprMax Ricker with the 2D Green's function at each scene's two-way path length, and compute the predicted envelope-peak delay relative to the truth delay, in periods. Compare this with the per-scene residual on corpus_s0's passing scenes (Spearman correlation, and the median ratio).
2. **Quarter cell.** Re-simulate **scene 13 only** at Δ/4 (0.6 mm), about 8× the half-cell cost, about 2 h, which is justified by one scene. Fit residual(Δ) = r₀ + c·Δ^p through Δ, Δ/2 and Δ/4, and report r₀ (the Δ → 0 residual) and the apparent order p.

**H_2D is supported** if two things hold:

- the analytic delay predicts the corpus residual with ρ ≥ 0.5;
- scene 13's r₀ lies within ±25% of the analytic prediction for that scene.

Otherwise it is not supported, and the residual stays open.

**Whatever the outcome, no validation tolerance or truth model changes in this phase.** A truth-model fix would be a separately versioned change.

**Permutation statistics** (correcting PR #12). Ten draws cannot give p < 0.05: the smallest attainable p is 1/11. PR #12's "p < 0.05" columns are void, and its conclusions rested only on the null mean and p95 comparisons, which stand. This phase uses 99 draws (§8).

## Amendment 1 (2026-10-12, before any corpus_s1_v2 scene was simulated)

**The conflict.** §4.1 defined `wet_conductive` as "σ in the upper half of `max_conductivity` (loss tangent 0.05–0.10)". These two statements contradict each other. `generator.max_conductivity` also caps σ at 0.01 S/m, and at GHz frequencies that cap binds. The first test of the generator showed loss tangents of about 0.003: a nearly lossless soil, not the wet, conductive one the family exists for.

**The fix.** The family now draws the **loss tangent** uniformly in [0.05, 0.10] and sets σ from it. This keeps truth.py's low-loss bound of tan δ ≤ 0.1. The 0.01 S/m cap does not apply to this family. Nothing else changed. This was found by a generator unit test, before any simulation or result.

## 11. Results

(Added after the freeze and the eval run. Every number below comes from the artifacts listed at the end of this section; summaries are copied to `evidence/hyperbola_v2/`.)

### 11.0 Verdict: **REJECT** (by the §9 rule: G1 fails)

| Gate | Criterion | Measured (eval split, primary condition, 198 scenes, 302 scored targets) | Result |
|---|---|---|---|
| **G1** | pooled ≥ 0.50; `standard` ≥ 0.60; ≥ A1 − 0.05 | pooled **0.510** [0.46, 0.56]; `standard` **17/29 = 0.586** [0.39, 0.82]; A1 0.550 → floor 0.500 | **FAIL** (standard family, by one target) |
| **G2** | precision ≥ 0.60; FP per empty scene ≤ 0.5 | precision **0.444** [0.40, 0.50]; FP/empty **1.67** [1.10, 2.31] | **FAIL** |
| **G3** | close_pair, overlap ≥ A1 − 0.10 | close_pair 0.467 vs floor 0.417; overlap 0.550 vs floor 0.533 | PASS |
| **C1** | fast ≥ 10× original (41 BAM dev lines); V2 total ≤ 29 s/line | median speed-up **9.4×** (8.89 s → 0.94 s); V2 total 8.4 s | **FAIL** (speed-up), PASS (total) |
| **C2** | peak ≤ 1 GB | largest 4TU line (7,130 traces) 728 MB; 4× largest synthetic line 19 MB | PASS |
| **C3** | max \|Δz\| < 1e-6; identical v̂ where z > 1 | max \|Δz\| 2.1e-12 on 20 corpus_s0 lines; v̂ differs in **16 of 90,372** cells | **FAIL as worded**; all 16 are exact float ties (§11.5) |
| **R1** | held-out recall ≥ production's; controls FP/line ≤ 2× production's | 0.438 / 0.417 / 0.427 vs 0.053 / 0.000 / 0.271; controls 1.91 ≤ 5.58, 1.67 ≤ 3.40 | PASS |
| **R2** | candidates/line ≤ 2× production's | INGV 2.58 vs 51.0; 4TU 6.90 vs 35.7 | PASS |

G1 failing makes the verdict REJECT whatever the other gates say. The `standard`-family miss is one target (18/29 would have passed), and its bootstrap interval spans 0.39–0.82, so this gate could not have distinguished "0.60" from "0.55" with 29 targets. **The rule was fixed in advance and is applied as written.** The more consequential failure is G2: V2's precision on the fresh corpus is 0.44 against a 0.60 bar, and empty-with-clutter scenes average 1.7 false detections. That is not a near miss.

The verdict concerns V2 **as a candidate to promote**. PR #12 stays KEEP_EXPERIMENTAL and unmerged, and the production detector is unchanged.

### 11.1 Dev selection (frozen in 09dc288 before any eval scene was run)

**Grouping.** All eight configurations were admissible. The chosen one (δ_g = 1 period, κ = ∞, ρ = 0.3) has the highest dev precision. It removes 58 of A1's 758 dev detections (8%); precision goes from 0.441 to 0.474, and recall from 0.668 to 0.664. Grouping is real but small: most false positives are not duplicate limbs.

**λ0.** No λ0 met both precision ≥ 0.60 and FP/scan ≤ 1.0 on dev, so the §6.3 fallback (highest dev precision) chose **λ0 = 0.25**:

| λ0 | dev recall | precision | FP/scan | FP/empty scene |
|---|---|---|---|---|
| 0.1 | 0.534 | 0.592 | 0.48 | 0.24 |
| **0.25** | **0.562** | **0.593** | **0.51** | **0.28** |
| 0.5 | 0.590 | 0.563 | 0.60 | 0.33 |
| 1.0 | 0.624 | 0.550 | 0.67 | 0.54 |

The dev split was 382 scenes: all 300 of corpus_s0 plus 82 corpus_s1_v2 dev scenes. corpus_s0 is development-exposed (§3), so these dev numbers are optimistic. The eval split (§11.2) is the only clean measurement.

### 11.2 Synthetic comparison (corpus_s1_v2 eval: 198 scenes, 302 scored targets, 33 empty scenes)

Primary condition (instrument 20 spp, 4TU-median noise). Bracketed values are 95% scene-bootstrap intervals (2,000 resamples, seed 0).

| Arm | Recall | Precision | FP/scan | FP/empty scene | Lateral error (λ) | Depth error, oracle v (λ) | CPU/line | Peak memory |
|---|---|---|---|---|---|---|---|---|
| A0 production ring @ 3.0 | 0.000 | — (1 det.) | 0.005 | 0.00 | — | — | 0.04 s | 2.8 MB |
| A1 hyperbola @ 6.0 | 0.550 [0.50, 0.60] | 0.359 [0.31, 0.41] | 1.50 | 3.42 [2.64, 4.24] | 0.028 | 0.277 | 0.25 s (A1+A2) | 2.8 MB |
| A2 A1 + grouping | 0.543 [0.50, 0.59] | 0.389 [0.34, 0.44] | 1.30 | 3.03 [2.36, 3.75] | 0.028 | 0.277 | (with A1) | (with A1) |
| **A3 V2** | **0.510 [0.46, 0.56]** | **0.444 [0.40, 0.50]** | **0.98** | **1.67 [1.10, 2.31]** | 0.028 | 0.278 | 2.2 s | 4.1 MB |

Costs are medians over the eval lines in a separate one-process pass; maximum A3 CPU was 3.2 s and peak 6.0 MB. A0's zero recall is the known ring width saturation (PR #12), not a new result.

**By family** (recall, scene-bootstrap 95% interval; precision P):

| Family | A1 | A2 | A3 |
|---|---|---|---|
| standard | 19/29 = 0.66 [0.52, 0.83], P 0.54 | 0.66, P 0.56 | **17/29 = 0.59 [0.39, 0.82], P 0.52** |
| weak_contrast | 32/43 = 0.74, P 0.39 | 0.74, P 0.45 | 33/43 = 0.77 [0.65, 0.89], P 0.61 |
| deep | 16/49 = 0.33, P 0.36 | 0.33, P 0.40 | 14/49 = 0.29 [0.18, 0.39], P 0.30 |
| close_pair | 31/60 = 0.52, P 0.70 | 0.50, P 0.71 | 28/60 = 0.47 [0.38, 0.55], P 0.55 |
| overlap | 38/60 = 0.63, P 0.52 | 0.63, P 0.56 | 33/60 = 0.55 [0.45, 0.65], P 0.57 |
| wet_conductive | 30/61 = 0.49, P 0.43 | 0.48, P 0.43 | 29/61 = 0.48 [0.39, 0.57], P 0.58 |
| empty_clutter (FP per scene) | 4.04 | 3.57 | 1.96 |

Targets whose hyperbolas overlap another's: A3 0.375 (24/64) vs A1 0.406, against 0.546 vs 0.588 for isolated targets.

**Where A3's false positives come from** (unmatched-detection classes, eval, primary condition):

| Arm | Diffuse clutter | Clutter stone | Limb | Early (direct wave) | Duplicate | Layer |
|---|---|---|---|---|---|---|
| A1 | 94 | 82 | 55 | 38 | 25 | 3 |
| A3 | 98 | 46 | 24 | 19 | 6 | 0 |

Calibration plus grouping removes most limbs, duplicates and early-time detections, and about half the clutter-stone responses. The remaining false positives are dominated by **diffuse clutter**, which neither mechanism addresses, and by **clutter stones**, which are physically real point scatterers. Stones are indistinguishable from targets by any hyperbola-shape criterion, and rejecting them needs information V2 does not have (amplitude/material, 3D extent).

**Other conditions.**

| Condition | A1 recall / precision | A2 | A3 |
|---|---|---|---|
| instrument, 4TU p90 noise | 0.553 / 0.328 | 0.546 / 0.372 | 0.500 / 0.445 |
| native sampling, 4TU median noise | 0.550 / **0.113** | 0.490 / 0.229 | 0.507 / **0.451** |

V2's canonical input and per-line calibration make it **invariant to sampling**: precision is 0.44–0.45 in all three conditions. A1's fixed threshold collapses to 0.11 precision at native sampling, which is the PR #12 threshold non-transfer reproduced on fresh scenes. This invariance is the clearest positive result of V2.

**Calibrated thresholds** on eval lines: median z* = 19.0 (p10 7.1, p90 54.3). No line hit the 3.0 floor, and 6% fell below A1's 6.0. Median z* by family runs from 9.0 (overlap) to 33.1 (wet_conductive).

### 11.3 Generalisation gaps found

1. **Dev → eval on empty scenes.** At λ0 = 0.25, dev FP per empty scene was 0.28; on eval it is 1.67. Of the 81 dev empties, 69 had no clutter stones (64 corpus_s0 null scenes and 5 `standard` empties); only 12 were `empty_clutter`. Of the 33 eval empties, 28 are `empty_clutter`. The dev split under-represented the hardest negative family, and calibration on a target-free line does not see stones as noise, because a permutation null destroys their coherence while the observed line keeps it.
2. **corpus_s0 → corpus_s1_v2.** A1's recall falls from 0.668 (dev) to 0.550 (eval) and its precision from 0.44 to 0.36. Most of this drop comes from the harder families, and it confirms the brief's warning that the PR #12 numbers were development-exposed.
3. **`weak_contrast` is not weak to the detector.** It has the highest recall of any family (0.74–0.77). Its contrast reduction is small next to the noise floor of the 4TU-median condition. The family therefore does not test what its name says; a lower-SNR variant is needed.
4. **Deep targets** are the weakest family (0.29–0.33 for all hyperbola arms). This is the expected attenuation and aperture limit.

### 11.4 Calibration investigation (synthetic vs real)

Medians per line, from `artifacts/realdata/hyperbola_v2/diagnose.json`. The null is 8 trace permutations of each line, run through the A1 stack.

| Data | Samples/period | Traces/λ | Noise ratio | Direct wave (periods) | Null comps z > 6 per line | Null peak z p50 / p90 / max | Observed comps z > 6 |
|---|---|---|---|---|---|---|---|
| Synthetic, primary | 20 | 14.3 | 3.1e-4 | 0.90 | 1.0 | 5.1 / 15.9 / 18.1 | 1 |
| Synthetic, native | 182 | 14.3 | 3.1e-4 | 0.90 | 1.1 | 3.4 / 4.4 / — | — |
| BAM dev (Pk266 1.5 GHz) | 22.7 | 13.3 | 1.3e-3 | 1.23 | 25.9 | 5.9 / 19.3 / 49.1 | 6 |
| 4TU | 20.4 | 10.0 | 1.5e-4 | 1.57 | 29.4 | 7.4 / 27.5 / 63.4 | 16 |
| INGV | 48.4 | 5.6 | 0.72 | 5.39 | 0.69 | 3.5 / 5.0 / 7.7 | 1 |

**Reading.** The same z = 6 means about one chance component per line on the synthetic data and INGV, but 26–29 on BAM and 4TU. Real lines carry structured, non-flat energy (ringing, layering, antenna effects) that trace permutation scatters into stackable patterns. On BAM and 4TU the permuted lines even exceed the observed ones. This is why a fixed threshold cannot transfer, and it is exactly what per-line calibration corrects. It also means the calibrated thresholds on real data are high (BAM median z* 44–90).

**Not investigated, and still open.** Antenna radiation pattern and coupling (gprMax uses an ideal line source), 3D geometry, and the receiver's time-varying gain. No transformation of the synthetic data was used to "calibrate" the detector; the only calibration is the per-line null, which uses no ground truth.

### 11.5 Computation

- **Fast stack.** The same statistic: per-(v, |k|) row templates, a row gather shared by ±k, prefix-sum flat sums, and only the eligible rows. On the 41 PR #12 BAM dev lines, single process: original 8.89 s, fast **0.94 s** (median **9.4×**), peak 27 → 25 MB. On synthetic lines it is 6–9× faster. **C1's 10× criterion is missed.** An earlier single-line measurement of 24× was taken under different load and is superseded by this controlled run.
- **V2 total** (canonical input, the stack, 8 calibration permutations, grouping): 8.4 s per BAM line in the controlled run, below both the original stack alone (8.9 s) and the 29 s criterion. Under the 6-worker BAM job, A3's median wall time was 15–28 s per line.
- **Memory.** 728 MB on the 7,130-trace 4TU line, which takes 428 s for V2 in total. The 4× synthetic line uses 19 MB.
- **C3.** On 20 corpus_s0 lines, max |Δz| = 2.1e-12 and the NaN patterns are identical. v̂ differs in 16 of 90,372 cells with z > 1. At each of these, the original stack's raw (pre-normalisation) coherence at the two competing velocities differs by at most **1.3e-15 relative**, so they are exact float ties broken differently by a different summation order (`scripts/hyperbola_v2_c3_ties.py`). C3 as worded ("identical v̂") is not met. The deviation has no effect on detections: A1 computed with the fast stack reproduced PR #12's per-scene results on 40 scenes with 0 mismatches. Coarse-to-fine search and float32 were not adopted.

### 11.6 Real data (held out; nothing tuned on it)

**BAM** (L-XZ rule, all 161 lines per scan):

| Scan | Role | A0 recall / FP per line | A1 | A2 | **A3** | A3 median z* |
|---|---|---|---|---|---|---|
| Pk266 1.5 GHz | dev | 0.005 / 2.04 | 0.646 / 6.83 | 0.646 / 6.63 | 0.262 / 1.96 | 44.2 |
| Pk266 2.6 GHz | held-out | 0.053 / 2.43 | 0.484 / 8.43 | 0.484 / 7.69 | **0.438 / 2.14** | 59.3 |
| Pk401 1.5 GHz | held-out | 0.000 / 5.03 | 0.500 / 26.07 | 0.500 / 23.65 | **0.417 / 1.92** | 79.9 |
| Pk401 2.6 GHz | held-out | 0.271 / 2.77 | 0.990 / 59.70 | 0.990 / 51.74 | **0.427 / 1.79** | 69.5 |
| Pk050 1.5 GHz | control | — / 2.79 | — / 7.48 | — / 7.12 | — / **1.91** | 70.3 |
| Pk050 2.6 GHz | control | — / 1.70 | — / 7.90 | — / 7.45 | — / **1.67** | 90.5 |

A3's lateral error is 5–7.5 mm, against A0's 37–65 mm. Its depth error is 3–47 mm where measurable.

**This is V2's strongest result.** On every held-out BAM scan V2 beats production's recall by 0.15–0.42, with *fewer* false positives per line than production on the held-out scans and the controls. A1 has higher recall but 2.7–22× production's false-positive rate, so per-line calibration is what turns the hyperbola stack from unusable into competitive on BAM. On the dev scan, calibration costs a lot of recall (0.65 → 0.26), and on Pk401 2.6 GHz, A1's 0.99 recall falls to 0.43. **The calibrated threshold is conservative on BAM**, as §11.4 predicted.

**INGV** (50 lines, 99-draw trace-permutation null, all lines with the full 99 draws):

| Arm | Candidates/line | Lines at p ≤ 0.05 (2.5 expected under the global null) | Corpus-level p |
|---|---|---|---|
| A0 | 51.0 | 0 | 1.00 |
| A1 | 11.4 | 18 | 0.68 |
| A2 | 6.2 | 18 | 0.18 |
| A3 | 2.6 | 24 | **0.01** |

**4TU** (38-file subset, 99-draw null):

| Arm | Candidates/line | Lines with all 99 draws | Lines at p ≤ 0.05 (expected) | Corpus-level p | Activity AUC (26 utility vs 4 trench-empty) |
|---|---|---|---|---|---|
| A0 | 35.7 | 36 | 0 (1.8) | 1.00 | 0.68 |
| A1 | 62.4 | 35 | 3 (1.75) | 1.00 | 0.50 |
| A2 | 53.9 | 35 | 3 (1.75) | 1.00 | 0.49 |
| A3 | 6.9 | 29 | 21 (1.45) | **0.01** | 0.56 |

**30-minute fallback lines.** Some lines did not fit 99 draws inside the 30-minute budget, so they report the null mean ± sd from the draws that fitted, with no p-value; they are listed in `4tu.json`. A0 has 4 such lines, A1 and A2 have 5 (they share draws), and A3 has 11. A3's significance therefore rests on 29 of 40 lines. The fallback lines are the long ones (up to 7,130 traces), where V2's 99 × (stack + 8-permutation calibration) is most expensive.

**Activity-level AUC.** Every arm's AUC comes from only 4 trench-empty activities and is not a gate. A3's AUC (0.56) is lower than production's (0.68), and neither is distinguishable from 0.5 with n = 4.

**What these real-data numbers do and do not show.** The INGV and 4TU numbers are count and significance comparisons against the line's own permutation null, not accuracy. They show V2's candidates are fewer and, where p is small, more structured than chance. They do not show that the candidates are targets. BAM is the only real data with ground truth, and it is a controlled test site, not field data.

### 11.7 Scientific follow-up: the apex-time residual (separate from the detector)

**H_2D analytic test: not supported.** A 2D line source convolved with the gprMax Ricker predicts an envelope-peak delay of median **0.0007 T** (image model) or **0.0036 T** (two-leg point model). The measured median on the 131 passing corpus_s0 scenes is **0.043 T**, so the prediction is 1.7–8% of the residual, with Spearman ρ = −0.18. For scene 13 the prediction is ≤ 0.002 T against a measured 0.168 T. The far-field 2D phase (a constant π/4) does not move the Hilbert-envelope peak, and the near-field correction is tiny at τ·f ≥ 3.

**Exploratory, post hoc, not pre-registered.** A numerical-dispersion estimate for the Yee scheme at each scene's cells-per-wavelength predicts about 0.0026 T, with ρ ≈ 0.23. It does not explain the residual either.

**Quarter cell (scene 13).** Re-simulated at Δ/4 (0.6 mm, 2,234 s wall). The apex-time residual falls from **111.7 ps** (Δ) to **77.8 ps** (Δ/2) to **67.9 ps** (Δ/4). The scene still passes at every resolution, with vertex error 0 traces. A Richardson fit r(Δ) = r₀ + cΔ^p through the three levels gives an apparent order **p = 1.78**, consistent with the second-order Yee scheme, and an extrapolated **r₀ = 63.8 ps = 0.096 T** at 1.5 GHz. About 43% of scene 13's residual is therefore grid discretisation; the remaining 0.096 T does not converge away. H_2D predicts ≤ 0.0022 T for this scene, so r₀ is not within ±25% of the prediction (it is about 40× larger). **H_2D is not supported** on either pre-registered criterion. The non-convergent ~0.1 T component remains unexplained. Candidates for a later, separately registered study are the source waveform's actual (discretised) spectrum, the PML, and the internal-echo event being scored on this dielectric target. No tolerance or truth model was changed.

**Permutation statistics correction.** PR #12's 10-draw nulls could not reach p < 0.05: the smallest attainable p is 1/11 ≈ 0.091, so its "p < 0.05" columns are void. Its conclusions rested on null mean and p95 comparisons, which stand. All p-values in this section use 99 draws (smallest p = 0.01); the lines that fell back to null mean ± sd (4TU only, listed above) carry no p-value. The 4TU corpus-level p uses only the lines with all 99 draws.

### 11.8 Deviations from the pre-registration

1. **Amendment 1** (wet_conductive loss tangent) was made before any simulation.
2. **C3** was not met as worded, because of float ties. Coarse-to-fine search and float32 were not adopted.
3. **The freeze check ran inside a container without git.** It was replaced by a blob-hash check (commit fad8e3b) after the freeze commit 09dc288 and before any eval scene was run; the freeze file was unchanged.
4. **The C3 check on 20 corpus_s0 lines** was run after the eval run, not before. It is a code-equivalence check, and no parameter depends on it.
5. **The eval split has 198 scenes**, by the pre-registered sha256 split; the 30/70 target was nominal.

### 11.9 Unresolved, and what a next phase would need

- **Diffuse clutter and clutter stones** are now the dominant false positives. A per-line permutation null cannot remove them, because they are coherent. This needs a different discriminant (polarity and amplitude, multi-line 3D continuity) or a different null.
- **The dev split under-represented `empty_clutter`.** Any re-selection should weight hard negatives in dev, and that would require a new pre-registration and a new eval corpus, since this one is now spent.
- **The calibration is conservative on real data** (BAM dev recall 0.65 → 0.26). A null that preserves more of the real data's structure (block or phase permutation) might be less conservative. This is untested.
- **The standard-family gate rests on 29 targets.** Future gates on a single family need about 100 targets to resolve ±0.10.
- **The apex-time residual is still unexplained** by 2D propagation and grid dispersion.

**Artifacts.** `artifacts/simulation/hyperbola_v2/{select_grouping,select_lambda,report,equivalence}.json`, `evaluate*.jsonl`; `artifacts/realdata/hyperbola_v2/{diagnose,cost,bam,ingv,4tu}.json`; `artifacts/simulation/investigation/residual_{analytic,quarter}.json`; corpus `artifacts/simulation/corpus_s1_v2/index.json`. Summary copies are in `evidence/hyperbola_v2/`.
