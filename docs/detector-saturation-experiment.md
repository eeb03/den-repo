# Detector saturation: three-detector experiment (pre-registration)

**Branch:** `exp/detector-saturation`, from PR #11 (`feat/m1a-pilot-corpus`), which stays unmerged.
**Status:** EXPERIMENTAL. Production behaviour does not change: `anomaly_grid_from_traces`, `TRACE_ANOMALY_WINDOWS`, `find_anomaly_candidates`, the threshold 3.0 and min_cells 3 are untouched.
**Written:** 2026-10-12. Every rule below was committed **before** any experimental detector was run on a corpus scene or a real line. The only exceptions are analytic unit fixtures and a smoke run on one scene, which check that the code executes.

Results go in §9, which is added afterwards. Sections 1–8 must not be edited after results exist. Any deviation is listed in §9 with its reason.

## 1. Question and intended use

The question is whether a wider-window ring or a hyperbola-aware detector can recover the targets the production ring z-score misses, at acceptable false-positive rates and with no unexplained regression on real radar data.

**Intended use.** The detector is a candidate generator. Its candidates are reviewed by an analyst or a later classifier. A missed target cannot be recovered downstream, while a false candidate costs review time. Detection, localisation and classification are separate stages:

- **Detection** decides that a candidate exists.
- **Localisation** reports the candidate's lateral position and time, plus depth if the detector estimates a velocity.
- **Classification** (pipe, void, rock and so on) is **out of scope** here.

**Baselines.**

| | Synthetic | BAM (L-XZ, from PR research/candidate-generation-v2) |
|---|---|---|
| Recall | 0/382 targets in every arm (PR #11) | 0.005 (dev) and 0.053 / 0.000 / 0.271 (L-X) on the held-out scans |
| FP per line | | 2.04 (dev); 2.43 / 5.03 / 2.77 (held out); 2.79 / 1.70 (controls) |

The INGV-UNISA 50-line run produced 2,551 candidates, at the trace-permutation chance rate.

## 2. Detectors (experimental arms)

The production ring and the widened ring produce a z-grid that goes through `benchmark.detection.detect_line` (|z| > threshold, 4-connected components, min_cells 3). The hyperbola stack uses the same rule, so only the statistic differs.

| Arm | What changes | Inputs used at inference |
|---|---|---|
| `ring` | nothing (production) | traces |
| `ring_widened` | the ring's window sizes only | traces |
| `hyperbola_stack` | statistic: one-sided contrast between the envelope stacked along a diffraction hyperbola and along a flat line, maximised over a velocity grid (`benchmark/hyperbola_stack.py`) | traces, trace positions, sample interval, the antenna's nominal centre frequency (instrument metadata), and time zero **estimated from the data** (direct-wave envelope peak of the median raw trace) |

**No inference input comes from simulator truth.** The soil velocity, the wavelet delay, target geometry and the target-free twin are never read by a detector. The oracle background arm uses the twin, and it is labelled as a simulation-only upper bound.

**Velocity grid:** εr 3–25 (9 values). This equals the generator's range, which flatters the hyperbola detector on synthetic data. The limitation is stated, not hidden.

**Non-ideal and overlapping hyperbolas** are handled in three ways:

- a time tolerance (envelope maximum within ±δ along the curve);
- a cone-limited aperture, so overlapping events from other targets fall partly outside;
- per-target one-to-one matching, so a merged response cannot credit two targets.

A point-diffractor, zero-offset curve is assumed. Large-radius targets and shallow targets relative to the antenna offset are mismatched by construction.

## 3. Parameter search spaces (fixed now)

| Arm | Parameters | Grid |
|---|---|---|
| `ring` | threshold only | THRESHOLDS |
| `ring_widened` | trace axis (inner, outer) × depth axis (inner, outer) | {(5,9), (7,13), (11,21)} × {(5,15) production, (9,27)}, giving 6 configurations |
| `hyperbola_stack` | cone half-angle × time tolerance δ | {30°, 45°, 60°} × {0, 1/(4 f_nominal)}, giving 6 configurations |
| all | threshold | THRESHOLDS = 2, 2.5, 3, 3.5, 4, 5, 6, 8, 10, 15, 20, 30 |

## 4. Synthetic corpus, conditions, splits

- **Corpus and splits.** The PR #11 corpus: seed 0, 300 scenes, 382 targets, unchanged. Splits (`SPLIT_VERSION` 2, by random draw) are train 211, val 35 and test 54.
- **Samplings.**
  - `instrument_20spp`: Fourier-resampled to 20 samples per period, the 4TU rate.
  - `native`: the solver's own sampling.
- **Noise.**
  - `noise_free`.
  - `noise_4tu_median`: white Gaussian noise at 2.99×10⁻⁴ of the line's direct-wave reference amplitude, the median over all 759 raw 4TU lines (`simulation/noise_calibration.py`).
  - `noise_4tu_p90`: 1.25×10⁻³, the 90th percentile; used for sensitivity only.
  - Noise is added to the traces, never to the twin, and is seeded from the scene id.
- **Conditions run.** {instrument, native} × {noise_free, noise_4tu_median}, plus instrument × noise_4tu_p90.
- **Background arms.** `no_background_removal`, `mean_trace_subtraction` (production), and `target_free_reference_oracle` (simulation only).
- **Primary condition.** `instrument_20spp` + `noise_4tu_median` + `mean_trace_subtraction`. This is the deployable arm at a realistic sampling and noise level.

## 5. Matching and metrics (from PR #11, `background_benchmark.score_located`)

**Matching rule.**

- A detection is located at its peak |z| cell.
- A detection **matches** a target when two conditions hold:
  - |x − x_centre| ≤ λ_c, the soil wavelength at the centre frequency;
  - t lies within [top-echo apex − T, latest predicted-event apex + T], where T = 1/f.
- Assignment is **one-to-one**. Targets are taken in truth order, and each takes the highest-|z| unmatched detection in its window.
- Unmatched detections are classed, using the first class that applies:
  - **duplicate**: inside a target window;
  - **limb**: within T of a predicted event time on its trace;
  - **early**: before the direct wave has passed;
  - **clutter**: anything else.
- A **missed** target has localisation errors `null`, never zero, and is excluded from error medians.

**Metrics.**

| Metric | Definition |
|---|---|
| Recall | matched targets / targets |
| Precision | matched detections / all detections (duplicates and limbs count against it) |
| FP per scan | all unmatched detections (strict) / scenes |
| FP per empty scene | all detections in empty scenes / empty scenes |
| Lateral error | in λ and m |
| Depth error, own velocity | the detector's own velocity (hyperbola only) |
| Depth error, oracle velocity | diagnostic only, labelled as such |

- **Breakdowns:** soil class, frequency, label and depth bin, plus weak and overlapping echoes:
  - **strength:** weak < 10 dB, moderate 10–25 dB, strong ≥ 25 dB SNR at the 4TU median noise;
  - **overlapping:** another target within λ laterally with an overlapping match window.
- **Cost:** CPU time per scene (process time) and peak memory (`tracemalloc`) per detector, over every scene at the primary condition.
- **Uncertainty:** a scene-level bootstrap with 2,000 resamples and seed 0, giving 95% percentile intervals for recall, precision, FP per scan and FP per empty scene.
- **Curves:** precision–recall and FP–recall over THRESHOLDS for every detector × arm × condition. Sensitivity to noise level, sampling and parameter configuration is shown on **val**.

## 6. Selection and freezing

1. **Selection.** On **train ∪ val** (246 scenes), at the primary condition, every detector configuration × threshold is scored. The selection rule is: maximise recall subject to FP per scan ≤ 1.0. Ties go to the higher threshold, then to the configuration listed first in §3. The production `ring` is also scored at its production threshold of 3.0.
2. **Freezing.** The chosen configuration and threshold for each detector are written to `simulation/detector_freeze.json` and **committed** before the test split is scored. The test split is not read before that commit. The frozen configuration is used unchanged for every arm, condition and sampling.
3. **Test.** The test split (54 scenes) is scored once, with the frozen values.

## 7. Real data

The frozen detector configurations are applied unchanged. Real data has no oracle background, so the arms are mean-trace subtraction and no removal.

- **BAM concrete (L-XZ rule, `benchmark.scoring.score_localization`).** This uses the split of the earlier candidate-V2 experiment:
  - development scan: Pk266 1.5 GHz;
  - held-out scans: Pk266 2.6, Pk401 1.5, and Pk401 2.6 (L-X only);
  - empty controls: Pk050 1.5 and 2.6.

  The synthetic-frozen threshold does not transfer to concrete, so each detector's operating threshold is frozen **on the dev scan only**. It is the threshold with the lowest FP per line at dev L-XZ recall ≥ 0.80. If that recall is unreachable, it is the threshold with the highest dev recall at FP per line ≤ 2.04, the production dev rate.

  The harness is checked first by reproducing the published production numbers.
- **INGV-UNISA, 50 content-unique lines.** I measure each detector's candidate count and multi-trace candidates against a trace-permutation null (10 draws per line), as prescribed after any ring-window change.
- **4TU utility survey.** I compute the activity-level comparison (`benchmark.fourtu_scoring.score_activities`): candidate density per activity against utilities found in the trial trench, on the same 40-file subset as the existing null run.

**Previously reported results** are compared, never re-tuned:

- BAM: production, envelope E1 and Candidate V2;
- INGV: 2,551 candidates and the permutation null;
- 4TU: the activity-level null.

## 8. Decision gate (fixed now)

**S1, meaningful synthetic recovery.** At the primary condition on the **test** split:

- recall ≥ 0.50; and
- the bootstrap 95% lower bound exceeds the upper bound of the production ring's test recall.

**S2, acceptable synthetic false positives.** On the test split at the frozen operating point:

- FP per empty scene ≤ 1.0; and
- precision ≥ 0.50.

**R1, no major real-data regression (BAM).** On every held-out BAM scan at the frozen dev threshold:

- recall ≥ the production detector's published recall on that scan; and
- FP per line on each control ≤ 2× production's (5.58 at 1.5 GHz, 3.40 at 2.6 GHz).

**R2, no unexplained explosion of real-data candidates.** On INGV-UNISA and 4TU:

- candidates per line ≤ 2× the production ring's on the same lines; or
- if above that, the excess is explained by a measured excess over that detector's own permutation null, meaning real lateral structure rather than noise.

**Verdict.**

| Verdict | Condition |
|---|---|
| **PROMOTE FOR FURTHER VALIDATION** | S1, S2, R1 and R2 all pass |
| **KEEP_EXPERIMENTAL** | S1 passes and any of S2, R1 or R2 fails or cannot be measured |
| **REJECT** | S1 fails |

If both arms are rejected, the failure mechanism and the next research approach are reported instead.

**Why these numbers.** The best real-data candidate generator so far is Candidate V2, which reaches 0.62 recall at 2.3 FP per line on held-out Pk266. The synthetic data are 2D and cleaner than any field line, so requiring at least half the targets at one false candidate per empty scene is a bar no weaker than what real data already shows to be possible. The 2× real-data margin allows for a more sensitive detector producing some more candidates. Anything beyond it must be explained.

## 9. Results

(Added after the frozen test run; see below.)
