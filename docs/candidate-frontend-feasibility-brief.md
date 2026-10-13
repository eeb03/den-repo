# Candidate Front-End Feasibility: research brief

**Status:** BRIEF FOR REVIEW. **Approval is needed before any implementation.**

The Phase 1 diagnosis (§1) was run with the **unchanged** V2 front-end. It used no new method and tried no alternative preprocessing, so that Phase 2's design is not fitted to its own test data.

**Branch:** `research/candidate-frontend-feasibility`, from `research/plan-view-linearity-v1` (PR #15).

**Standing constraints:**
- PRs #12–#15 stay unmerged.
- **PVL-V1's L1 failure is accepted as recorded.** L1 is not revived and its gates are not relaxed.
- CCD-V1 Stage 2 stays on hold.
- No production code changes, no new detector, no simulation.

**Written:** 2026-10-13.

**The question.** Can Subterra produce candidates that are **consistent across adjacent radar lines** (high line recall at known objects, short gaps, few artefacts) well enough to support 3D interpretation? If not, where should the next investment go?

**Three layers, kept separate throughout:**
- **Signal processing:** time zero, early-time handling, background removal, gain.
- **Candidate detection:** the statistic, the threshold, grouping, and any cross-line rule.
- **Object discrimination:** CCD-V1's features. **Out of scope here.**

---

## 1. Phase 1: diagnosis

**Labels.** EXPLORATORY. CONCRETE NDT ONLY. Every BAM scan used here has influenced earlier research.

**What was run.** `scripts/frontend_phase1_diagnosis.py` produced `artifacts/frontend_feasibility/`, with copies in `evidence/frontend_feasibility/`.
- The V2 front-end (A3, freeze 09dc288) was re-run on every line crossing a known object, on five scans:
  - Pk266 at 1.5 and 2.6 GHz Rot00, and at 1.5 GHz Rot90;
  - Pk401 at 1.5 GHz Rot00 and Rot90.
- It reproduces the stored detections: 484 for Pk266 1.5 GHz and 353 for Pk401 1.5 GHz.
- At each object crossing (±10 mm, t_e − 0.5T to t_e + 1T, t_e from the stored known-geometry calibration), the detector's **own** statistic z is read and compared with the line's calibrated threshold z* and with A1's fixed z = 6.

**Truth is used only to say where to read. Nothing is tuned.**

### 1.1 Why the known ducts are missed across consecutive lines

Each object crossing is classified on every line it crosses (121 lines per duct, 24 per cuboid):

| Object (top depth) | 1.5 GHz Rot00 | 2.6 GHz Rot00 | 1.5 GHz Rot90 |
|---|---|---|---|
| duct-1 (241 mm) | statistic-limited 103, weak (z 3–6) 18. **Line recall 0.00** (median z 1.8) | weak 104, statistic-limited 15, threshold-limited 2. **0.00** (z 3.7) | statistic-limited 112, weak 9. **0.00** (z 1.9) |
| duct-2 (181 mm) | **threshold-limited 121 of 121. Recall 0.00** (z 17.8 vs z* 40) | threshold-limited 121. **0.00** (z 26.5 vs 59) | threshold-limited 121. **0.00** (z 19.1 vs 34) |
| duct-3 (118 mm) | detected 29, threshold-limited 92. **0.24**, longest run 9, longest gap 71 lines | detected 86, threshold-limited 35. **0.71**, run 46, gap 13 | detected 14, threshold-limited 107. **0.12**, run 7, gap 59 |
| duct-4 (61 mm) | detected 6, threshold-limited 110, off-window 5. **0.05**, gap 77 | **detected 121 of 121. 1.00** | detected 70, threshold-limited 51. **0.58**, gap 11 |
| cuboid-1 (240 mm) | statistic-limited 24. **0.00** (z 0.6) | n/a: no calibration | statistic-limited 24. **0.00** |
| cuboid-2 (180 mm) | threshold-limited 24. **0.00** (z 21 vs 103) | n/a | threshold-limited 24. **0.00** |
| cuboid-3 (120 mm) | detected 17, threshold-limited 7. **0.71** | n/a | detected 5. **0.21** |
| cuboid-4 (60 mm) | detected 24. **1.00** (z 187) | n/a | detected 24. **1.00** |

**Findings:**
1. **Grouping loses nothing.** "Lost in grouping" was 0 on every scan.
2. **The dominant cause is the threshold level, not the statistic.** At duct-2 and cuboid-2, z is well above A1's z = 6 on **every** line (z ≈ 18–27), yet always below the line's z* (34–103). Over the four 1.5 GHz Rot00 ducts, 323 of the 484 crossings are threshold-limited.
3. **The statistic is spatially consistent; the threshold is not the source of flicker.**
   - z at a crossing has lag-1 autocorrelation along Y of **0.96–0.99** (ducts) and 0.58–0.95 (cuboids).
   - z* is also smooth: lag-1 0.95–0.97 on Pk266, with a median line-to-line change of 5–6%.
   - Gaps appear where a smooth z hovers near a smooth z*. That is a **level** problem, not a noise problem.
4. **z* reflects specimen structure, not targets.** PR #13 measured a median z* of **70** on Pk050, which has no embedded objects but does have a stepped back wall, rebar and anchors. Pk266 and Pk401 give 44 and 80. The permutation null of a line with strong horizontal and step structure produces large chance peaks. **This is a hypothesis about cause.** It is testable without truth, because z* itself is the measurement (§2, H-B).
5. **The deepest objects are statistic-limited.** Duct-1 (z ≈ 2–4) and cuboid-1 (z < 1.1) are weak under the stack at every frequency and rotation. CCD-V1's oracle continuity was also weakest at duct-1 (135 mm). **No thresholding change can rescue a statistic at z ≈ 2.**
6. **Acquisition parameters matter as much as processing.**
   - 2.6 GHz raises duct-3/4 line recall from 0.24/0.05 to 0.71/1.00.
   - Rot90 raises duct-4 from 0.05 to 0.58.
   - The same objects and the same algorithm give very different continuity.

   Frequency and polarisation must therefore be gate dimensions, not afterthoughts.

### 1.2 Where the false positives come from (already measured; not re-run)

**Synthetic** (CCD-V1 Stage 0, V2 on the spent corpus_s1_v2 eval split, 193 false positives):

| Kind | Count | Share |
|---|---|---|
| System or processing: direct wave and direct-wave tail (51), background-removal imprint (10) | 61 | 32% |
| Generator stones | 49 | 25% |
| Noise-induced | 45 | 23% |
| Scoring policy | 30 | 16% |
| Target late events | 7 | 4% |
| **Genuinely unexplained** | **1** | 0.5% |

**BAM** (CCD-V1 Arm D, V2 1.5 GHz Rot00, by position class):

| Scan | Direct band | Back wall | Below back wall / "other" | Step edges | Edge-rebar zone | At objects |
|---|---|---|---|---|---|---|
| Pk266 (484) | **135** | 31 | 243 | 2 | 7 | 66 |
| Pk401 (353) | **94** | — | 162 | 29 | 23 | 45 |
| Pk050 (308) | 13 | **182** | 112 | 1 | — | — |

**Reading.**
- **Direct-wave responses** are the largest single artefact class on the object-bearing specimens: 28% and 27% of all detections.
- **Horizontal back-wall responses** dominate the specimen with no embedded objects.
- The "other" class on BAM has **not** been decomposed further. Separating late reverberation, step-edge diffraction tails and aggregate scattering would need a new attribution rule. **That rule is part of Phase 2 (§2.4), not done here.**

### 1.3 Does background removal suppress legitimate targets?

| Evidence | Reading |
|---|---|
| V2 subtracts the line's mean trace. A duct crosses each line once and fills about 13 of 401 traces | It barely enters the mean, so it is **not** suppressed by the background step. The z at duct-2 (≈ 18) confirms the response survives |
| The production ring statistic gives \|z\| 1.7–2.0 at duct crowns (`bam_quantitative_validation`), where the background-subtracted signal has 9–37× contrast | The **estimator**, not the background, suppressed targets in production. This was diagnosed before |
| PR #12 (descriptive, not pre-registered): no removal did better than mean-trace subtraction on BAM for the hyperbola stack | Background choice is a secondary lever **for detection**. It may still be primary **for the null level** (§1.1 finding 4) |
| **Blind spot:** an object running *along* the survey line would be largely removed by mean-trace subtraction | Untested; BAM's lines all run across the ducts |

### 1.4 What can be addressed without truth at inference

| Failure mode | Addressable without truth? | How |
|---|---|---|
| Threshold level too high because of structured background | **Yes** | Remove horizontal and step structure *before* both the stack and its permutation null, then recalibrate z* on the processed line. z* is the truth-free measurement |
| Flicker where z ≈ z* | **Yes** | Cross-line hysteresis: seed above z*, grow into neighbouring lines at a lower level. Calibrate the lower level on **permuted volumes**, so its false-track rate is set by a null, not by truth |
| Direct-wave false positives | **Yes** | An early-time mute or taper, based on time zero estimated from the data (`estimate_time_zero`), at a fixed number of periods |
| Statistic-limited deep objects | **No**, not by front-end thresholding | Frequency, polarisation, stacking or acquisition. Out of scope except as gate dimensions |
| Stones and other real non-utility scatterers | **No**: they are real anomalies | Object discrimination (CCD-V1), out of scope |

---

## 2. Phase 2: the smallest defensible experiment (pre-registration draft)

### 2.1 Arms

| Arm | Signal processing | Candidate detection | Purpose |
|---|---|---|---|
| **A** | unchanged (canonical input, mean-trace subtraction) | unchanged V2: per-line null z*, grouping | reference. The production ring is also reported, for context |
| **B, artefact-aware preprocessing** | (B1) data-estimated early-time mute: taper samples before t̂₀ + k·T; (B2) lateral running-median background over a window of w traces (replacing the whole-line mean), applied **before** the stack **and** before the permutation null | unchanged V2 | does removing structured background lower z* and artefact FPs without losing objects? |
| **C, spatially coherent generation** | unchanged | V2 statistic, plus **3D hysteresis**: seeds are kept V2 detections (z ≥ z*). A seed grows into lines j ± 1..G at the same canonical (x ± δx, t ± δt) wherever z ≥ α·z*_j. α is the smallest value in the grid whose **null false-track rate** (the same procedure on volumes with traces permuted within each line) is ≤ 0.1 tracks per line | does neighbour support close gaps without inventing tracks? |
| **D, combined** | B | C | **only if B and C each pass their own component gates** (§2.3) |

**Justification for C, from Phase 1.** z at known crossings is spatially smooth (lag-1 0.96–0.99), so neighbour support is physically warranted. C is still expected to help **only where z sits near z\***: duct-3 and duct-4 at 1.5 GHz. It will not help duct-2 (z ≈ 18 vs z* 40) unless B lowers z*. **That is why D exists.**

### 2.2 Parameter grids and selection (development scan only)

**Development scan:** Pk266 1.5 GHz Rot00. It has been the development scan in every phase since PR #12.

| Arm | Grid | Selection rule |
|---|---|---|
| B | k ∈ {1.5, 2, 3} T; w ∈ {41, 81, 161} traces | highest median object line recall on the development scan, subject to artefact FP per line ≤ A's. Ties go to the larger k, then the larger w |
| C | G ∈ {1, 3}; δx ∈ {0.25, 0.5} λ̂; δt ∈ {0.25, 0.5} T; α ∈ {0.3, 0.4, 0.5, 0.6, 0.7} | α is **set by the permutation null** for each (G, δx, δt), not by truth. Then the highest development line recall wins; ties go to the smallest G and δx |

**Freeze.** Each arm's choice is committed (blob hash) **before** any other scan is run with that arm.

**Holdout scans.** These are exposed specimens but were not used for selection, so they are **exploratory**:
- Pk266: 2.6 GHz Rot00, 1.5 GHz Rot90 and 2.6 GHz Rot90;
- Pk401: 1.5 GHz Rot00 and Rot90;
- Pk050: 1.5 GHz Rot00 and Rot90;
- synthetic corpus_s1_v2 eval (spent), for the artefact classes only.

### 2.3 Metrics and gates

**Statistical units.** One object is one unit. A duct's 121 crossing lines and a cuboid's 24 lines are **repeated measures of one object, never independent ground-truth units**. Per object:
- line recall (the fraction of crossing lines detected within ±100 mm and ±1T);
- the longest detected run;
- the longest gap;
- the number of separate runs (fragmentation).

**"Detectable" objects.** An object is detectable on a scan if A's median z at the crossing is ≥ 6, the fixed A1 level. The statistic-limited objects (duct-1, cuboid-1) are reported but excluded from the recall and continuity gates, because no front-end thresholding can rescue them. Note that this definition uses arm A's statistic, not the arm under test.

| Gate | Criterion (holdout scans) | Applies to |
|---|---|---|
| **G-REC, recall** | line recall, pooled per object over the Pk266 holdout scans, rises above A's on **all 3 detectable ducts** (duct-2, duct-3, duct-4), **and** falls by more than 0.10 on no object (ducts or cuboids) | B, C, D |
| **G-CONT, continuity** | the longest gap on detectable ducts is ≤ 10 lines (50 mm) on ≥ 2 of the 3 Pk266 holdout scans; fragmentation ≤ A's | C, D (B reported) |
| **G-ART, artefacts** | direct-band plus below-back-wall FP per line ≤ 50% of A's on every holdout scan; on synthetic, system/processing FPs ≤ 50% of A's 61, with Task A recall within 0.03 of A's | B, D (C reported) |
| **G-FREE, embedded-object-free control** | FP per line on Pk050 ≤ A's. **Pk050 is not empty**: it contains rebar, anchors and a stepped back wall. It is a control for *embedded ducts and voids* only, and no "empty-ground" claim is made | all |
| **G-NULL, truth-free** | B: median z* drops by ≥ 25% on Pk050 and Pk266. C: the null false-track rate is ≤ 0.1 per line | B, C |
| **G-COST** | CPU ≤ 2× A per line; peak memory ≤ 1 GB on the largest BAM and 4TU lines | all |
| **G-FREQ/POL** | the G-REC and G-ART outcomes hold on ≥ 3 of the 4 Pk266 frequency × rotation combinations (one is the development scan, so it is **reported separately**) | all |

**Uncertainty.**
- "Improves on k of n objects" carries an exact sign-test p. With n = 3 detectable ducts the smallest p is 1/8: **no BAM result can reach significance.** BAM gates are directional, decision-relevant counts, not statistical claims.
- Line-level statistics are reported only as distributions.

### 2.4 Additional fixed rules

- **A position-based attribution of BAM "other" FPs**, fixed before any arm runs:
  - within T of a calibrated back-wall multiple;
  - within 60 mm of a step edge after the back wall;
  - within 2T after an object's top time and within ±100 mm (object ringing);
  - the remainder.

  This decomposes the 243/162/112 "other" detections into artefact and unexplained subclasses for G-ART.
- **4TU (regression check only; no object truth).** Candidates per line, and excess over the 99-draw null, for A–D on the PR #13 40-file subset, read-only. No 4TU result enters a gate except **G-COST**, and the rule that **no arm may exceed 2× A's candidate count**.

### 2.5 Compute (local, zero-budget)

| Item | Budget |
|---|---|
| B selection (9 settings × 161 lines) | ~1.5 h |
| C null calibration | ~1 h |
| Holdouts (7 scans × 4 arms) | ~4 h |
| 4TU regression | ~2 h |
| **Total** | **≤ 9 h CPU** |

No GPU and no simulation. A 1.5× overrun stops the step for review.

---

## 3. Phase 3: evidence availability

| Test | Possible with held data? | Status |
|---|---|---|
| Line recall and continuity at known **linear** objects | BAM Pk266, 4 ducts × 4 scans | **Exploratory.** Every scan informed earlier work; only the development/holdout split is internal |
| The same at known **compact** objects | BAM Pk401, 4 cuboids × 2 scans (no 2.6 GHz calibration) | Exploratory |
| Artefact FPs | BAM, all specimens; synthetic corpus_s1_v2 (spent) | Exploratory or development |
| FPs where no embedded objects exist | Pk050 only, which **contains rebar, anchors and a stepped back wall**. No dataset held has **verified empty ground** | Control for embedded ducts and voids only |
| Frequency and polarisation dependence | Pk266: 2 frequencies × 2 rotations. **The antenna E-field orientation behind "Rot00/Rot90" is undocumented** | Descriptive |
| Soil, real utilities | 4TU: activity-level counts only, no coordinates. Trench-empty means "the trench found nothing", **not** that the survey ground was empty | Regression and association only |
| Independent validation of any arm | **None** | **Requires new data** |

**The smallest independent acquisition that would validate a front-end (zero-cost route: university partnership, Part C′):**
- **Site:** one test pit or yard with **≥ 6 known linear targets**: metal and plastic pipes or cables, at 2–3 depths, including one crossing the lines obliquely and one running *parallel* to them. It also has **≥ 6 placed compact non-utility scatterers** (stones or rubble) and one strip **documented as empty at burial time** from excavation or backfill records, not assumed.
- **Grid:** two **orthogonal** sets of parallel lines at ≤ λ/4 spacing (≈ 4–5 cm at 500 MHz for ε ≈ 9–16), each ≥ 5 m long. Positions by RTK GNSS or total station.
- **Acquisition:** **documented antenna orientation and polarisation**, two frequencies if the instrument has them, and a raw export with gain and processing logged.
- **Why this size:**
  - 6 linear + 6 compact objects give an exact Mann–Whitney minimum p of 1/924, and a sign test on 6 of 6 objects gives p = 0.016. Objects, not lines, are the units.
  - The parallel-running target tests the mean-trace blind spot.
  - The orthogonal grid removes the line-direction blind spot.
  - The empty strip gives the first verified target-free FP rate.

---

## 4. Phase 4: decision gates

Applied to the holdout results, in this order:

| Outcome | Decision |
|---|---|
| **B passes G-NULL and G-REC, and C adds nothing (fails G-CONT)** | **PIVOT → signal preprocessing.** The threshold-level problem is a background-structure problem. Invest in artefact-aware preprocessing (early-time handling, structured-background removal before null calibration) as the next pre-registered phase |
| **C passes G-CONT and G-REC without breaching G-ART or G-FREE; B is neutral** | **CONTINUE → spatially coherent detection.** Pre-register a coherent front-end for the independent acquisition in §3 |
| **B and C both pass, and D passes every gate** | **CONTINUE with D.** It is the candidate front-end for any 3D interpretation work, still experimental, pending the §3 acquisition |
| **Both fail G-REC on detectable objects, but G-NULL shows z* falling** | The statistic, not the threshold, is limiting at the new level. **PIVOT → acquisition parameters** (frequency, polarisation, line density), guided by Phase 1 finding 6 |
| **Nothing passes G-REC on 2.6 GHz Pk266, the most favourable scan, where A already reaches 0.71/1.00 on the shallow ducts** | **STOP** front-end work on this data. A single-channel 2D-line front-end cannot be made cross-line consistent here. Recommend **new acquisition** (§3), and assess **another sensing strategy**: multi-channel or array GPR (dense 3D by construction), or complementary EMI/RF locators for metallic utilities |

**On every route:**
- No result here supports an object-identity claim, and no candidate becomes a "detection".
- All BAM numbers are exploratory.
- Promotion of any front-end requires the independent acquisition.

---

## 5. Recommendation

**Run Phase 2 as specified, starting with arm B's development selection and arm C's null calibration.** The diagnosis points to a specific, truth-free-testable mechanism: z* inflated by structured background (**H-B**), not grouping and not noisy thresholds. B tests it directly, and C is justified only where z sits near z*.

In parallel, **pursue the §3 acquisition**. Two reasons:
- Every BAM result will remain exploratory.
- The two strongest levers seen in Phase 1 (frequency and polarisation) are acquisition choices.
