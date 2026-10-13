# CCD-V1 Stages 0 and 1: results and scientific decision

**Status:** results for review. **Stage 2 is on hold and was not started.** No corpus was generated, no detector was implemented, and no production code was changed. PRs #12, #13 and #14 are unmerged.

**Commits:**

| Commit | What it holds |
|---|---|
| `cb12628` | the brief (baseline, unchanged) |
| `73629db` | the frozen protocol, amendments A1–A5 and the analysis code, committed **before** any Stage 0 or Stage 1 computation |
| (this commit) | these results |

**Labels that apply throughout:**
- Stage 0 uses spent synthetic data: **SIMULATION ONLY**, descriptive.
- Stage 1 is **EXPLORATORY**: every BAM specimen and scan was used in earlier research (PR #12, PR #13, `bam_quantitative_validation`, the trace-span experiment). **CONCRETE NDT ONLY.** Nothing here is independent validation.

**Outputs:** `artifacts/ccd_v1/`, with summary copies in `evidence/ccd_v1/`. No earlier artifact was rewritten.

**Reproduction checks (all passed):**
- Re-running V2 (A3, freeze 09dc288) reproduced the stored PR #13 eval output on **all 198 scenes**: 347 detections, 193 false positives, identical per-scene classes.
- Re-running V2 on BAM reproduced PR #13's detection counts exactly: Pk266 484, Pk401 353 and Pk050 308 at 1.5 GHz.

---

## 1. Stage 0: diagnostics

### 1.1 What V2's false positives actually are (0a)

**Population:** all 193 unmatched V2 detections on the corpus_s1_v2 eval split (primary condition). The frozen rules of protocol §B0a were applied in order. The "unexplained" remainder was split by noise-free attribution (§B0a′).

| Kind | Categories (count) | Total | Share |
|---|---|---|---|
| **System or processing artefact** | direct-wave tail just past the `early` cutoff (32); `early` direct wave (19); background-removal imprint (10) | **61** | 32% |
| **Generator-created object** | clutter stones (46); stone limbs outside the ±λ stone window (3) | **49** | 25% |
| **Noise-induced** (no noise-free response at the cell) | — | **45** | 23% |
| **Scoring policy** | limbs (24); duplicates (6) of matched targets | **30** | 16% |
| **Scored-target physics** | late events within 3λ of a target (7); multiples (0) | **7** | 4% |
| **Genuinely unexplained wavefield** | scattered field from scored targets that no rule explains (1); twin-field (0) | **1** | 0.5% |

**The 98 detections PR #13 called "clutter" split as:**
- 45 noise-induced;
- 32 direct-wave tail;
- 10 background-removal imprint;
- 7 late target events;
- 3 stone limbs;
- **1 genuinely unexplained.**

That 1 is in the `deep` family.

By family:
- `empty_clutter`: 46 of its 55 false positives are the stones themselves.
- `deep`: 19 of 32 are noise-induced, the calibrated threshold admitting noise peaks.
- `overlap`: 7 of 25 are late events of the overlapping targets.

**Reading.** V2 has essentially **no unexplained radar responses**. At most 49 of its 193 false positives (25%) are what this phase set out to address: coherent non-utility scatterers, here generated stones. **The largest share (106, 55%) is noise plus system and processing artefacts, and no object-discrimination feature can address it.** Those need front-end changes: a direct-wave mute, the choice of background removal, and the null threshold in deep scenes. That is detector work, which is outside this phase.

### 1.2 The Task A re-score (0b)

With stones counted as objects under the same matching rule:

| Measure | Value |
|---|---|
| Objects | 453, of which 151 are stones |
| Recall, all objects | 195 / 453 = **0.430** |
| Recall, stones only | 41 / 151 = 0.272 |
| Precision | 195 / 347 = **0.562** (PR #13's G2 value: 0.444) |
| FP per physically empty scene | **0.0**, but n = 5 scenes |

**Reading.**
- Under Task A, V2's precision rises from 0.44 to 0.56, still below PR #13's 0.60 bar.
- Its "1.67 FP per empty scene" was entirely an artefact of calling stone scenes empty. On the 5 genuinely empty scenes it produced nothing, but **5 scenes cannot support a rate**.
- Stones are found less often than scored targets (0.27 vs 0.51). They are smaller (0.03–0.08 λ), so this is expected.

### 1.3 4TU amplitude preservation (0c): **unknown**

| Check | Result |
|---|---|
| Files read | all 759 |
| Sample format | 16-bit integer (code 3) in every file |
| Gain fields in the trace headers (bytes 119–124) | **zero in every file** |
| Textual header | names the instrument (InfraRadar100 / RadarMap 1.0.17), stacking 1, time range 50 ns and "Dry loam, ε = 9". It **states nothing about gain or processing** |
| Amplitude-trend indicator (late/early RMS of the median envelope) | median 0.031 (5–95%: 0.014–0.081) |

The amplitudes decay strongly with time, which is **consistent with** no time-varying gain. Under the frozen rule, though, an indicator cannot establish provenance. **Outcome: `unknown`. F2 stays blocked on 4TU** until the publisher states the export processing.

### 1.4 4TU cross-line geometry (0d): **measurable in principle on 48 activities**

| Check | Result |
|---|---|
| Activities | 125, with 759 paths |
| Activities with ≥ 2 paths | 101 |
| Valid NMEA fixes per path | median 100% |
| Path length | median 5.5 m (10–90%: 2.6–16.5 m) |
| Parallel pairs (headings within 15°, separation ≤ 2 m, overlap ≥ 5 m) | **233 pairs in 48 activities** |
| Pair separation | median 1.04 m (10–90%: 0.37–1.83 m) |
| Near-identical repeat passes | 14 pairs closer than 0.25 m |

**Registration accuracy is unverified.** No GNSS quality field or document states it. One path, 012.5 `Path1`, has a 159 m track over a 20 m chord, which is an irregular or noisy track. These 48 activities are where a multi-line continuity test (H9) **could** be attempted. It was not run (amendment A5).

### 1.5 BAM footprints and acquisition parameters (0e)

| Item | Result |
|---|---|
| Lines per object | 121 per duct (central band Y 100–700 mm); 24 per cuboid (\|y − y_obj\| ≤ 60 mm) |
| Object nodes | **5** per object: the frozen ±10 mm at 5 mm spacing. The protocol text said "3 nodes" in error (deviation D1) |
| Reference nodes | 30 per object, inside the object's step and off its edges |
| Acquisition parameters, all 12 scans | the same parsed DZT parameters: 512 samples, 15 ns, 16 bit, ε setting 5.5, the same grid (401 × 161) |
| Header defect | the DZT header names the antenna "2.6GHz" on the 1.5 GHz files. Pre-existing and recorded, not resolved |
| Gain | **no gain fields are parsed from the DZT**, so cross-specimen amplitude comparisons rely on within-specimen normalisation only |
| Calibrations used | the stored known-geometry back-wall fits. Pk266: v = 0.129 m/ns. Pk401: v = 0.103 m/ns. Pk050: v = 0.123 m/ns (1.5 GHz). Pk401 and Pk050 at 2.6 GHz were refused, so there is none |

---

## 2. Stage 1: BAM features at known object positions (EXPLORATORY)

**Units:** 4 ducts (Pk266) against 4 cuboids (Pk401). One object is one unit; its lines are repeated measures, summarised by the median. All p-values are exact (70 enumerated splits). The 97.1% intervals are the exact range of the 16 pairwise differences.

### 2.1 Each feature on its own

**F8, line-to-line continuity (H6, a pipeline sanity check).** The half-maximum run along Y through the line of maximum response, in mm:

| Object | Run (mm) | Y range |
|---|---|---|
| duct-1 (deepest, top 241 mm) | **135** | 100–235 |
| duct-2 / duct-3 / duct-4 | 600 / 600 / 600 | 100–700 (the whole band) |
| cuboid-1 to cuboid-4 | 140 / 120 / 115 / 110 | each centred on its drawn Y (±10 mm) |
| Pk050 phantoms (null, 8 positions) | 15–70 | — |

H6: U = 15 of 16, **exact p = 0.029** (smallest attainable 0.014). Hodges–Lehmann shift +480 mm, 97.1% range [−5, +490] mm. Pk266 at 2.6 GHz (descriptive) gives the same pattern: duct-1 80 mm, the others 600 mm.

**F7, polarisation magnitude \|ρ\| (H5).** ρ is the Rot00/Rot90 log-amplitude ratio, normalised by the back wall's own ratio:

| Group | \|median ρ\| | Signed ρ |
|---|---|---|
| ducts 1–4 | 0.092 / 0.156 / 0.018 / 0.068 | −0.09 / −0.16 / +0.02 / +0.07 |
| cuboids 1–4 | 0.222 / 0.660 / 0.610 / 0.395 | **all positive** (IQRs mostly above 0) |
| Pk401 off-object lines (null) | 0.006–0.084 | — |
| Pk050 phantoms (null) | 0.010–0.536 | — |

H5 (predicted ducts > cuboids): U = 0, **exact p = 1.0**. The ordering is the **opposite** of the prediction on all 16 pairs (HL shift −0.42, 97.1% range [−0.64, −0.07]). That is not a significance claim in the reversed direction, which was not pre-registered.

**F1, polarity relative to the aluminium back wall (H7).** The value is the median c, with the fraction of lines where c < 0 in brackets:

| Object | Median c | Lines with c < 0 |
|---|---|---|
| duct-1 / duct-2 (deep) | **−0.62 / −0.76** | 0.80 / 0.84 |
| duct-3 / duct-4 (shallow) | **+0.94 / +0.84** | 0.10 / 0.01 |
| cuboid-1 | +0.57 | 0.00 |
| cuboid-2 / -3 / -4 | −0.34 / −0.38 / −0.41 | 0.92–1.00 |
| Pk050 phantoms (null) | −0.45 to +0.58 | — |

- **H7a**, cuboids opposite to the back wall as polystyrene predicts: **3 of 4**. Exact binomial p = 0.31; Clopper–Pearson 95% [0.19, 0.99]. With n = 4 the smallest attainable p is 0.0625, so H7a **could not** reach 0.05.
- **H7b**, ducts vs cuboids: U = 8, AUC 0.50, exact two-sided p = 1.0.

### 2.2 Controls

| Control | Result |
|---|---|
| **C4.1** Pk050 phantoms (no embedded objects) | F8 null 15–70 mm, far below every object. F1 spans −0.45 to +0.58 and F7 spans 0.01–0.54, so **the null spread of F1 and F7 is as wide as most object values** |
| **C4.2** Pk401 off-object lines | \|ρ\| 0.006–0.084: the cuboids' F7 (0.22–0.66) **is** above the within-specimen null |
| **C4.3** specimen identity (late, object-free window) | F7: AUC 0.25, F1: AUC 0.25 (exact two-sided p = 0.34 each). **Both fall outside the frozen band [0.30, 0.70], so the rule declares any Pk266-vs-Pk401 difference in F1 or F7 confounded with specimen identity.** Two caveats. First, at n = 4 + 4 the band excludes U = 4, which is not itself significant. Second, **this control has a defect: duct-4's late window (≈ 3.7–4.7 ns) contains its step's back wall (4.32 ns)**, so it was not object-free (deviation D2). The rule is applied as frozen anyway |

### 2.3 Confounds (protocol §D)

| Factor | Ducts | Cuboids | Status |
|---|---|---|---|
| Specimen | Pk266 | Pk401 | **perfectly confounded** with class |
| Concrete | v 0.129 m/ns | v 0.103 m/ns | different; only within-specimen references control it |
| Material | **not stated** | polystyrene | **no material attribution for the ducts** |
| Geometry | linear, Ø67 | compact, 120 × 120 × 60 | **confounded** with class |
| Depth to top | 241 / 181 / 118 / 61 mm | 240 / 180 / 120 / 60 mm | matched |
| x position | 250 / 750 / 1250 / 1750 | the same | matched |
| Instrument, grid, samples, range | identical in every scan | identical | matched (§1.5); gain unknown |

**Measurement confounds found in the data:**
1. **F1 depends on depth and step for the ducts.** It flips from negative (deep ducts 1–2, back-wall references at 9.8 and 8.2 ns) to positive (shallow ducts 3–4, 6.2 and 4.3 ns). One object type at one material cannot change polarity with depth. A zero-lag polarity measured against a reference reflection at a **different travel time** is therefore distorted by dispersion and attenuation (phase rotation along the path). The F1 definition is not robust.
2. **The cuboid peaks arrive 0.39–0.59 ns after the expected top time**, against 0.04–0.09 ns for the ducts. A 60 mm polystyrene block has top and bottom reflections of **opposite** sign about 0.4 ns apart, so the measured "polarity" of a thin void is a mixture. This matches the +27 mm cuboid depth bias already recorded in `bam_quantitative_validation.md`.
3. **F7 for the ducts is indistinguishable from the null.** A long conductor should depend strongly on polarisation. The absent effect is consistent with any of three explanations, and **the data cannot tell them apart**:
   - the ducts are not conductive (their material is not stated);
   - "Rot00/Rot90" is not the E-field rotation this physics assumes;
   - the in-line response at the duct crossing is dominated by its cross-section, not its length.

### 2.4 Arm D: features at V2's own BAM candidates (descriptive; not statistical units)

Per detection class, as median [IQR], 1.5 GHz:

| Specimen / class | n | F1 c | \|F7 ρ\| | F8 run (mm) |
|---|---|---|---|---|
| Pk266 object (ducts) | 66 | 0.37 [−0.03, 0.82] | 0.23 [0.12, 0.31] | **40** [11, 45] |
| Pk266 "other" | 243 | −0.61 [−1.0, 0.89] | 0.14 [0.03, 1.10] | **205** [40, 710] |
| Pk266 back wall | 31 | −0.99 | 0.10 | 710 |
| Pk401 object (cuboids) | 45 | −0.51 [−0.88, −0.37] | 0.59 [0.23, 0.79] | 30 [10, 145] |
| Pk401 "other" | 162 | −0.23 | 0.06 [0.02, 0.09] | **690** [225, 690] |
| Pk050 back wall / other | 182 / 112 | −0.79 / −0.93 | 0.04 / 0.03 | 235 / 765 |

Coverage by object:
- **V2 detected only 3 of the 4 ducts and 2 of the 4 cuboids** under this arm's ±1T rule. Duct-1 and cuboids 1–2 produced no candidates.
- **The candidate-level F8 runs over targets are short (40 mm)**, because V2 finds a duct only intermittently from line to line.

**The decisive descriptive fact: at detector candidates, planar reflectors and layering are the most continuous responses (runs of 205–765 mm).** **Continuity alone would rank clutter above targets.** It discriminates only when measured as **linear extent**: long along one axis and compact across it, a plan-view shape test. A planar reflector is extended along both axes; a duct is extended along one.

### 2.5 Combination (table only, no test; protocol §C6)

Each feature was evaluated independently first (§2.1). Combining them is uninformative:

- F8 orders 3 of 4 ducts above all cuboids.
- F7 orders the opposite way and is specimen-confounded.
- F1 is depth-confounded.

No object is ordered "correctly" by more than one feature, and no combined model is justified.

---

## 3. Scientific decision

| Feature | Verdict | Basis |
|---|---|---|
| **F8, line-to-line continuity** | **PROMISING, conditionally** | It separates 3 of 4 linear ducts from compact cuboids (exact p = 0.029, n = 4 + 4) and sits far above the object-free null. But: (i) this was a pre-registered **sanity check**, near-tautological on BAM; (ii) it fails on the deepest, weakest duct; (iii) **at real detector candidates, planar clutter is more continuous than targets**, so it must be reformulated as a plan-view *linearity* measure, which is untested; (iv) it **cannot be tested in 2D simulation** |
| **F7, polarisation ratio** | **UNSUPPORTED** | The opposite of the prediction on all pairs. The duct effect is indistinguishable from the null. The specimen-identity control fails (with the D2 defect noted). Duct material and the meaning of Rot00/Rot90 are undocumented, so no physical interpretation is possible |
| **F1, reflection polarity** | **UNSUPPORTED, and the measurement is flawed** | H7a 3 of 4 (p = 0.31; n = 4 cannot reach 0.05). H7b null. Duct polarity flips with depth, which shows that polarity referenced to a distant reflector is distorted along the path. Thin-void interference contaminates the cuboids. It would need a redefinition: a same-time reference or phase-corrected polarity. That is a new pre-registration |
| **F2, corrected amplitude** | **NOT TESTED; blocked on real data** | 4TU amplitude preservation is `unknown` (§1.3). On BAM, gain is unparsed |
| **F6, dual frequency** | **NOT TESTABLE** | There is no Pk401 2.6 GHz calibration (amendment A4) |

**Is Stage 2 justified? No, not as designed.**

1. **The brief made Stage 2 conditional on Stage 0** (§13, item 2): "worth running only if Stage 0 does not already show the in-plane route to be hopeless, e.g. if V2's unexplained FPs turn out to be dominated by artefacts that no object feature addresses." **That condition is met.** 55% of V2's false positives are noise plus system and processing artefacts. Only 25% are stone-type scatterers. Only 1 detection of 193 is a genuinely unexplained wavefield.
2. **The in-plane features Stage 2 would test (F1–F5) have no real-data support.** F1 failed on BAM and its definition is flawed. F2 is unmeasurable on the only real soil corpus.
3. **The one promising feature (F8 continuity) cannot be tested in 2D simulation at all,** and the candidate-level evidence shows it must be reformulated before any test.

**What the evidence supports instead (each would need its own approval and pre-registration):**
- **(a) Front-end precision work, under Task A.** A direct-wave mute or tail handling, background removal that avoids the mean-trace imprint, and a deep-scene noise threshold address 55% of V2's false positives. This is detector work, outside this phase's mandate, and is listed here only as the evidence-backed next lever.
- **(b) A plan-view linearity feature**, a reformulated F8 (extended along one axis, compact across it), developed on BAM as development data. It would then be tested, by association only, on the **48 4TU activities with parallel paths** (§1.4), against the activity-level "utility path linear" and rubble fields. Registration is unverified, so this is exploratory.
- **(c) Real data.** Every measured limit traces back to the data: undocumented duct material, undocumented antenna orientation, unknown 4TU processing, and no located stones or utilities in soil. The brief's §11 acquisition items (the 4TU object-log request, and a registered multi-line survey over known utilities **and** stones) remain the binding constraint. The F7 result specifically needs **documented antenna orientation and target material** before it can be interpreted at all.

**Product consequence, unchanged:** candidates stay "anomaly, type not determined". No Stage 0–1 result supports any utility-likeness claim.

---

## 4. Deviations and limitations

- **D1.** The protocol text says "3 nodes" for ±10 mm. At 5 mm spacing that is 5 nodes. The frozen ±10 mm definition was applied.
- **D2.** Control C4.3's late window was not object-free for duct-4, because it contains the step-3 back wall. The control was applied as frozen and not redesigned after seeing results.
- **D3.** Arm D's `object` rule (±1T of the expected top) is stricter than PR #13's L-XZ (±60 mm depth). So its object counts (Pk266 66) are not comparable to PR #13's hits (169).
- **D4.** Rot00/Rot90 are assumed co-registered on one grid, as the shared X/Y-values files indicate. The physical meaning of the rotation, antenna versus scan direction, is undocumented.
- **Power.** With 4 + 4 objects:
  - the smallest one-sided p is 0.014;
  - H7a cannot reach 0.05;
  - a single discordant object moves p from 0.014 to 0.029.

  **None of the Stage 1 results is replicable evidence. They are feasibility observations on two development-exposed specimens.**
- **Not run (amendment A5):** the 4TU H8 (rubble association) and H9 (multi-line) tests.

## 5. Tests

The full suite passes: **3,216 tests** (`docker run --rm -v $PWD:/app -w /app subterra-test python -m pytest`), including 7 new tests in `tests/test_ccd_v1.py`. These cover the exact statistics and the feature primitives on analytic fixtures. No production module was modified. Since `cb12628` the only files changed are the protocol, `scripts/ccd_v1_*.py`, the tests, this document and `evidence/ccd_v1/`.

## 6. Reproducing

All commands are run in the test image with the repository mounted. `FREEZE_BLOB` must be the git blob hash of `simulation/hyperbola_v2_freeze.json`.

```
python -m scripts.ccd_v1_stage0 attribution --workers 6
python -m scripts.ccd_v1_stage0 fourtu-amplitude
python -m scripts.ccd_v1_stage0 fourtu-geometry
python -m scripts.ccd_v1_stage1 footprints
python -m scripts.ccd_v1_stage1 features
python -m scripts.ccd_v1_stage1 armd --workers 6
```

Compute used: Stage 0 under 1 min; Stage 1 features 40 s; Arm D about 10 min wall on 6 workers. This is well inside the 4 h and 6 h budgets.
