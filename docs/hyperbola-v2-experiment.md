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

## 11. Results

(Added after the freeze and the eval run.)
