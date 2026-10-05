# BAM quantitative validation: depth, localisation and signal processing

**Date:** 2026-10-05 · **Branch:** `research/yesan-kec-testbed-ground-truth` (not merged) · **Data:** BAM concrete step specimens Pk050 / Pk266 / Pk401, Harvard Dataverse 10.7910/DVN/FCMUJQ v1.1 (CC0; all three archives MD5-verified, Pk401 newly acquired) · **Truth:** Grohmann et al. 2026, *Data in Brief* 68:113103, Appendices A–C (CC BY)

**Purpose:** an honest baseline, not good numbers. The baseline detector and the time-zero code are unchanged. One improvement experiment is kept strictly separate (§10).

**Gates:** the evidence to resolve the BAM origin / units / DZT-mapping / depth-reference questions is assembled here. The edit to `benchmark/gates.py` / `benchmark/scoring.py` was **refused by the session's permission system**, so **no gate or manifest status was changed**. The proposed change is in §11 for explicit approval.

Reproduce (all research scripts; they read the archives, write JSON, change nothing):

```
venv/bin/python -m scripts.bam_amplitude_preservation        # §2 amplitude, DZT->grid mapping
venv/bin/python -m scripts.bam_quantitative_validation       # §3-9 calibration, t0, depth, baseline detector
venv/bin/python -m scripts.bam_candidate_experiment          # §10 experiment E1 (dev/test protocol)
venv/bin/python -m scripts.score_bam_benchmark --scan 1_5_GHz_Rot00   # frozen baseline (unchanged)
```

Compact results are committed in `evidence/bam/results/`. Full outputs, including detection lists, go to the git-ignored `artifacts/bam/validation/`.

---

## 1. Ground truth

Source: the four technical drawings in Appendices A–C of the *Data in Brief* paper, obtained as full-resolution images (about 2220 × 3330 px) from the Elsevier CDN for the open-access article (PII S2352340926006517). They are held git-ignored in `datasets/raw/references/bam_dib2026/`.

The transcription is in **`evidence/bam/specimen_ground_truth.csv`**, one row per object with its source, location and evidence grade. Every position is a drawing dimension. **No position was read from radar.**

| Specimen | Targets | Position X (mm from origin) | Depth (drawing → top surface) | Size | Other reflectors (never scored as targets) |
|---|---|---|---|---|---|
| Pk266 | 4 tendon ducts along Y (full 800 mm) | 250 / 750 / 1250 / 1750 | centre 274.5 / 214.6 / 151.4 / 94.4 → crown 241.0 / 181.1 / 117.9 / 60.9 | inner Ø60, outer Ø67 (text) | Ø10 rebars at the long edges and step verticals; stepped back wall |
| Pk401 | 4 polystyrene cuboids | 250 / 750 / 1250 / 1750; Y 398.2 / 398.2 / **498.2** / 398.2 | centre 270 / 210 / 150 / 90 → top 240 / 180 / 120 / 60 | 120 × 120 × 60 | 4 grouted boreholes in the top surface (X 368 / 506 / 647 / 827, Y ≈ 359–367); 3/10/12 mm bars mostly within 75 mm of the long edges; width 796.4 mm |
| Pk050 | none (control for ducts/voids) | — | — | — | Ø10 rebars at the edges; two M16 anchors in each side face; back wall |

**Depth reference:** the drawing leaders end at the duct-circle centre and at the cuboid mid-line, so drawing depth = **centre**. Top = centre − 33.5 mm for the ducts (outer radius; −30 mm if the reflecting surface is the inner wall, a documented ±3.5 mm reference uncertainty) and centre − 30 mm for the cuboids.

**Evidence grade:** B (fabrication drawing, not re-surveyed). It is not upgraded.

## 2. Coordinate system, units, raw signal

| Item | Value | Source |
|---|---|---|
| Specimen frame | X along the 2000 mm length, Y across the 800 (Pk401: 796.4) mm width, Z down from the scanned top surface | drawings |
| Origin | the circled cross at the **thick** end (X = 0 at the 570 mm step) | drawings. The paper's prose says "thin side", **contradicting its own drawings**. The data side with the drawings (back-wall fit, §4: as-drawn orientation residual 3–10× lower than mirrored on every 1.5 GHz scan) |
| Units | mm (drawings: "All geometric data in millimeters"); grid 5 × 5 mm, 401 × 161 | drawings; paper Table 3 |
| Time axis | 512 samples, 15 ns, Δt = 0.029354 ns, t = 0 at sample 0 (recording start, **not** time zero) | paper; DZT header; `.npy` Z-values |
| Antenna | GSSI 1.5 and 2.6 GHz, ground-coupled, scanner-mounted (contact) | paper §4.3 |
| Scan pattern | meander along X; every second stored line reversed starting with line 0; 2.5 mm raw spacing resampled to 5 mm | paper; reproduced below |
| **DZT trace count** | 152,222 = 181 × 841 + 1 redundant | **verified** on all held DZTs |
| **DZT → grid mapping** | grid row y = DZT line y + 10 (50 mm crop). Odd (forward) lines: A-scan ≈ 2x + 14…16. Even (reversed) lines: A-scan ≈ 840 − 2x − 25…26 (the ≈ 25 mm meander offset the authors corrected) | **measured**, `evidence/bam/results/amplitude_preservation.json` |
| **Amplitude preservation** | **400/400** probed grid traces (Pk266 1.5 GHz, Pk401 2.6 GHz) equal a trace decoded by Subterra's unmodified `converters.gssi_converter.read_dzt` **exactly** on samples 2–511. Samples 0–1 differ only because the authors' readgssi workflow overwrites them with sample 2, which Subterra deliberately does not do | **measured** |

Scanner/antenna offset and antenna separation are not published. Both antennas are in contact with the surface, so there is no air gap. The `.DZT` header names the antenna "2.6GHz" even for the 1.5 GHz file (a header/filename conflict, recorded and not used).

## 3. Time-zero evidence

| | What it is | BAM status |
|---|---|---|
| A. instrument/recording t0 | header field | **REFUSED**: `preprocessing.time_zero` treats `rhf_position`/`signal_position` as untrusted vendor fields |
| B. declared (publication) | paper Table 4, from the aluminium back walls, **1.5 GHz Rot00 only**: Pk266 0.7308, Pk050 0.6723, Pk401 0.6868 ns | DOCUMENTED reference. The picking convention is not stated |
| C. direct-wave onset (Method C) | `direct_wave_consensus_time_zero`, unchanged, on three full X-sweeps (Y = 250 / 400 / 550 mm) | measured below |
| Subterra known-geometry reference | intercept of t = t0 + 2d/v fitted to the four back-wall steps (envelope-peak picks; §4) | **independent of the direct wave and of all targets** |

**No absolute, instrument-level time zero is published.** Every available reference is defined by a picking convention. The comparison below is therefore convention-aware, and the operational test is the depth error each t0 produces (§6).

| Scan (1.5 GHz Rot00) | Method C per Y (ns) | Method C median | Back-wall intercept (peak picks) | Paper |
|---|---|---|---|---|
| Pk266 | 0.38 / 0.68 / 0.47 | 0.47 | 1.08 | 0.73 |
| Pk050 | 0.73 / 0.73 / 0.68 | 0.73 | 0.88 | 0.67 |
| Pk401 | 0.76 / 0.76 / 0.76 | 0.76 | 0.62 | 0.69 |

**Findings:**
- **Pk050 and Pk401 at 1.5 GHz:** Method C agrees with the paper's t0 within 2–3 samples (0.06–0.08 ns).
- **Pk266 at 1.5 GHz:** Method C is unstable across Y (0.38–0.68 ns). Small pre-signal wiggles fire the 3-sample onset rule before the true rise at about sample 25.
- **2.6 GHz:** Method C returns 0.29–0.32 ns on every scan, i.e. sample 10–11. Its quiet window is `QUIET_SAMPLES = 8`, three of which are the identical overwritten samples, so the pick sits at the method's own floor and is not interpretable.
- Method C measures an **onset**; reflection times in a B-scan are dominated by **peaks**. That convention gap is the main source of its depth bias (§6).

The earlier audit's "VALIDATED VELOCITY" for Pk266 1.5 GHz (Method C t0 + duct depths) used the scored targets themselves to fix velocity. **That result is superseded by this independent calibration.**

## 4. Velocity evidence

Calibration uses **only the stepped back wall**: four fabricated thicknesses per specimen, object-free windows chosen by excluding drawn objects (exclusion, not fitting). Picks are the envelope local maxima per step. The one-per-step combination is selected that best fits t = t0 + 2d/v with v in [0.08, 0.16] m/ns, t0 in [−0.5, 2.5] ns, and residual ≤ 0.2 ns. **Both orientations are tried, so orientation is a result, not an assumption.**

Three rule amendments were made after seeing calibration outputs only, before any target or detector metric was inspected:
1. exclude the record-end envelope artefact;
2. geometry-constrained selection, because attenuation makes the true thick-step back wall weaker than earlier internal events;
3. the residual quality gate.

| Scan | v (m/ns) | Classification | Paper v | Δ | Fit residual | Leave-one-step-out thickness error |
|---|---|---|---|---|---|---|
| Pk266 1.5 Rot00 / Rot90 | 0.1289 / 0.1279 | DERIVED_FROM_KNOWN_GEOMETRY | 0.1271 | +1.4% / +0.6% | 0.09 / 0.07 ns | ≤ 18.8 mm |
| Pk266 2.6 Rot00 / Rot90 | 0.1289 / 0.1291 | DERIVED_FROM_KNOWN_GEOMETRY | — | — | 0.06 / 0.04 ns | ≤ 12.9 mm |
| Pk050 1.5 Rot00 / Rot90 | 0.1234 / 0.1241 | DERIVED_FROM_KNOWN_GEOMETRY | 0.1246 | −1.0% / −0.4% | 0.04 / 0.03 ns | ≤ 8.3 mm |
| Pk401 1.5 Rot00 / Rot90 | 0.1026 / 0.1020 | DERIVED_FROM_KNOWN_GEOMETRY | 0.1088 | −5.7% / −6.3% | 0.06 / 0.06 ns | ≤ 11.3 mm |
| Pk050, Pk401 2.6 GHz (all) | — | **REFUSED** (no physical combination, or residual > 0.2 ns): the thick-step back wall is not resolvable at 2.6 GHz | — | — | — | — |

Paper Table 4 values are CALIBRATED/DOCUMENTED by the authors from the same back walls. Hyperbola-based estimates on the ducts (earlier audits) are ESTIMATED_FROM_RADAR on the scored targets, **not** independent, and not used as a reference here.

## 5. Baseline detector, reproduced from code

The frozen baseline (`benchmark.detection`, ring z-score, threshold 3.0, min 3 cells), rerun today (`evidence/bam/results/baseline_rerun_*.json`), reproduces the documented numbers exactly:

| Scan | Recall | Precision | TP / FP / FN | Pk050 false alarms per line |
|---|---|---|---|---|
| 1.5 GHz Rot00 | **0.0652** | **0.1351** | 45 / 288 / 602 | 2.79 |
| 2.6 GHz Rot00 | **0.0932** | **0.1465** | 63 / 367 / 584 | 1.70 |

That scorer matches on **X only**: a detection's peak trace within ±33.5 mm of a duct, at any time or depth.

## 6. Depth results

Each target's two-way time was measured at its **drawn** position: a background-subtracted mean trace (reference traces 120–200 mm away in the same step), with the strongest envelope peak between 1.2 ns and the measured back wall. This isolates **depth conversion** from detection. The error is measured against the drawn **top** surface. Results are separated by provenance and are never pooled. The four Pk266 scans (2 antennas × 2 orientations) re-measure the **same 4 ducts**, so n counts measurements, not independent objects.

| Provenance of t0 / v | Ducts (n = 16; 4 objects) mean signed / MAE / median abs / RMSE / P95 (mm) | Cuboids (n = 8; 4 objects, 1.5 GHz) mean signed / MAE / RMSE / P95 (mm) |
|---|---|---|
| **DERIVED_FROM_KNOWN_GEOMETRY** (Subterra back-wall calibration, same scan) | **+7.1 / 7.1 / 7.5 / 7.7 / 11.0** (1.5 GHz +7.5; 2.6 GHz +6.7) | +27.1 / 27.1 / 27.5 / 32.6 |
| CALIBRATED/DOCUMENTED (paper Table 4; 1.5 Rot00 only, n = 4) | +25.3 / 25.3 / 25.4 / 26.9 | +30.6 / 30.6 / 30.6 / 31.8 |
| EXPERIMENTAL: Method C t0 + back-wall v | +42.8 / 42.8 / 45.1 / 43.8 / 52.3 | +19.2 / 19.2 / 19.7 / 24.4 |
| EXPERIMENTAL: Method C t0 + paper v (n = 4) | +41.9 / 41.9 / 41.9 / 43.4 | +26.5 / 26.5 / 26.5 / 27.6 |
| Failure case: no t0 correction + back-wall v | +71.6 / 71.6 / 72.0 / 71.7 / 76.4 | +58.3 / 58.3 / 58.4 / 63.4 |

Per-object values are in `evidence/bam/results/depth_summary.json`. With back-wall calibration, per-duct errors at 1.5 GHz Rot00 are +7.1 / +2.7 / +5.4 / +5.6 mm (deepest to shallowest).

**Interpretation:**
- **Metal ducts:** depth to within ≈ ±11 mm (P95) with a known-geometry calibration. The residual +7 mm bias is within the 3.5 mm duct-reference uncertainty plus about one sample of picking difference between a duct crown and a metal back wall.
- **Polystyrene cuboids:** biased ≈ +27 mm deep. The likely cause is interference between the 60 mm block's top and bottom reflections (opposite polarity, about 1.2 ns apart at 1.5 GHz). It is reported, **not corrected**.
- **2.6 GHz Pk401:** the deep cuboids' picks land on early events, and with no calibration there is no depth.

## 7. Localisation results

**Matching rules (pre-registered in `scripts/bam_quantitative_validation.py` before any result):**
- **L-X:** per scan line crossing a target, the highest-|z| detection within ±100 mm of the target X; other detections in that window are duplicates; a detection near no target is a false positive.
- **L-XZ:** L-X plus |depth − z_top| ≤ 60 mm under the same scan's back-wall calibration.

Errors are conditional on a match.

| Arm / scan | Recall L-X | Recall L-XZ | Median abs ΔX | RMSE ΔX | P95 ΔX | Depth error of matched candidates (median abs) |
|---|---|---|---|---|---|---|
| **Baseline** Pk266 1.5 GHz | 0.185 | **0.005** | 55 mm | 59 mm | 96 mm | 127 mm |
| **Baseline** Pk266 2.6 GHz | 0.241 | **0.053** | 45 mm | 57 mm | 95 mm | 179 mm |
| **Baseline** Pk401 1.5 / 2.6 GHz | 0.375 / 0.271 | **0.000** / n/a | 48 / 50 mm | 62 / 60 mm | 100 / 95 mm | 369 / 332 mm |
| E1 (experiment) Pk266 2.6 GHz, **test** | 0.877 | **0.818** | **10 mm** | 19 mm | 30 mm | **4.6 mm** (RMSE 46) |
| E1 (experiment) Pk401 1.5 GHz, **test** | 1.000 | **0.750** | 5 mm | 26 mm | 65 mm | 28 mm (cuboid-1 matched a shallower event) |

**Baseline "hits" are coincidental.** Its matched detections sit 127–369 mm (median) from the target depth: they are direct-wave or late-time events that happen to share the target's X, which is why X-only recall is 0.07–0.37 but depth-gated recall is 0.000–0.053.

**Lateral / 2D (Pk401, unbiased):** all lines were used, gated only by X ±100 mm and depth ±60 mm (`evidence/bam/results/pk401_lateral_2d.json`).
- **E1:** candidate centroids lie 1.7 / 13.8 / 49.5 / 12.5 mm from the drawn Y (Rot00), but for three of the four cuboids the gated candidates **span Y 100–700 mm**, i.e. they are not laterally confined to the 120 mm cuboid. Lateral localisation is **not** demonstrated.
- **Baseline:** essentially no candidate at any cuboid's depth (one detection, 157 mm off).
- An earlier per-target "lateral error" that used only ground-truth lines was **biased by construction** and is not reported.

## 8. False positives

FP categories are assigned by fixed rules (time band, back-wall band, step edge ±60 mm, edge-reinforcement zone, borehole, near-target tail).

| Scan | Baseline FP per line (central band) | Dominant categories (baseline) | E1 FP per line (central band) | Dominant categories (E1) |
|---|---|---|---|---|
| Pk266 1.5 GHz | 1.19 (0.83) | direct-wave band 71, below back wall 50, near-target tails 39, step edges 21 | 14.6 (dev) | — |
| Pk266 2.6 GHz | 1.50 (1.06) | direct-wave band 172, below back wall 51 | 18.9 (13.1) | below back wall 1017, back-wall band 984, near-target tails 338, edge rebar 326, step edges 290; 1426 duplicates |
| Pk401 1.5 GHz | 4.72 (3.34) | below back wall 542, direct wave 58 | 42.9 (32.3) | near-target tails 1617, unexplained 1449, step edges 1257, edge rebar 1131 |
| Pk050 control 1.5 / 2.6 GHz | 2.79 / 1.70 | unexplained, below back wall, direct wave | 18.0 / 21.6 | back-wall band, edge rebar, unexplained |

## 9. Failure analysis: why the baseline is poor

| Category | Verdict | Evidence |
|---|---|---|
| **Candidate statistic (ring z-score)** | **primary cause** | At each duct crown the ring statistic peaks at median |z| 1.7–2.0, above 3.0 on 0–2.4% of sampled lines (`missed_diagnosis_ring_z`), while the background-subtracted signal there has 9–37× contrast. The statistic normalises a coherent hyperbola against its own neighbourhood and suppresses it |
| Time zero | contributes to depth error only | depth bias +43 mm with Method C vs +7 mm with calibrated t0 (§6). It does not affect X-only detection |
| Wrong velocity / depth | not a detection cause | known-geometry v within 1–6% of the paper |
| Candidate threshold | secondary | lowering it cannot rescue a statistic that is below 3.0 at the targets but above it in the direct-wave and late-time bands |
| Preprocessing (gain, dewow) | contributes to false positives | late-time "below back wall" false positives are amplified noise; direct-wave residue survives |
| Clutter (rebar, step edges, back wall) | contributes to false positives | step-edge and edge-rebar categories |
| Duplicates | minor in the baseline (23–34); large in E1 (1426) | |
| Hyperbola model | absent in both arms | neither scores hyperbolic shape |
| Frequency | modest | 2.6 GHz slightly better recall in both arms |
| Object geometry | matters for depth (cuboid bias), not for the baseline's failure | |
| Coordinate mismatch | **ruled out** | orientation confirmed; the duct X set is mirror-symmetric, so baseline detection numbers do not depend on it |
| Matching logic | inflates baseline recall | X-only matching credits coincidental events (L-X 0.185 vs L-XZ 0.005) |

## 10. Controlled improvement experiment (E1). EXPERIMENTAL, not a replacement

**Arm E1** (`scripts/bam_candidate_experiment.py`):
- running-median horizontal background removal (W traces);
- Hilbert envelope;
- gate: t ≥ 1.2 ns, and not within 0.5 ns of the record end;
- robust normalisation, global or per time row;
- 2-D local maxima (100 mm × 0.5 ns) above T.

**Protocol:**
- Grid: W ∈ {21, 41, 81}, N ∈ {global, per_row}, T ∈ {4, 6, 8, 10}, 24 combinations.
- Selection on the **development** scan only (Pk266 1.5 GHz Rot00), by L-XZ F1.
- **Frozen:** W = 81 (≈ 400 mm), global normalisation, T = 10. Applied unchanged to the test and control scans.
- The development scan is never reported as a test result.

| | Recall L-XZ | Precision L-XZ | FP per line | Δ vs baseline |
|---|---|---|---|---|
| Dev: Pk266 1.5 GHz | 0.786 | 0.175 | 14.6 | recall 0.005 → 0.786; FP 1.19 → 14.6 |
| **Test: Pk266 2.6 GHz** | **0.818** | 0.146 | 18.9 | recall 0.053 → 0.818; FP 1.50 → 18.9 |
| **Test: Pk401 1.5 GHz** | **0.750** | 0.010 | 42.9 | recall 0 → 0.75 |
| Test: Pk401 2.6 GHz | n/a (no calibration) | — | 43.8 | L-X recall 1.0 |
| **Control: Pk050 1.5 / 2.6 GHz** | — | — | **18.0 / 21.6** | baseline 2.79 / 1.70 |

E1 shows the targets are detectable at the correct depth and position with a simple physics-shaped statistic. Its false-alarm rate (15–43 per line, with many duplicates) makes it unusable as a detector on its own.

## 11. Capability verdicts

| Capability | Before | Evidence | Metric | Result | New status |
|---|---|---|---|---|---|
| Raw signal ingestion (GSSI DZT, BAM) | header-only; DZT→grid unresolved | DZT counts on all 12 files; mapping reproduced | trace count; mapping | 181 × 841 + 1 everywhere; exact mapping | **VALIDATED** (this instrument/format) |
| Amplitude preservation | unverified | 400 probes, 2 specimens, 2 antennas | exact equality, samples 2–511 | 400/400 exact | **VALIDATED** (decode level) |
| Time zero, Method C | "validated" (target-circular audit) | paper Table 4; back-wall intercept; depth chain | t0 difference; depth bias | 1.5 GHz: within 0.08 ns of the paper on 2/3 specimens, unstable on Pk266; 2.6 GHz pinned at the floor; depth bias +43 mm (ducts) | **FAILED** as a depth-chain t0 (convention mismatch, floor effect) |
| Time zero, known-geometry calibration | — | back-wall step fit | fit residual; depth error | 0.03–0.09 ns; ducts +7 mm | **PARTIALLY_VALIDATED** (needs a known reflector; 1.5 GHz all specimens, 2.6 GHz Pk266 only) |
| Propagation velocity | ESTIMATED_FROM_RADAR | back-wall known geometry vs paper | Δv; LOSO thickness | −6.3% to +1.4%; LOSO ≤ 19 mm | **PARTIALLY_VALIDATED** (DERIVED_FROM_KNOWN_GEOMETRY; refused at 2.6 GHz on Pk050/Pk401) |
| Depth conversion (known position) | BLOCKED | drawings + calibration | error vs top | ducts mean +7.1, P95 11.0 mm (4 objects); cuboids +27 mm | **PARTIALLY_VALIDATED** (metal ducts) / **EXPERIMENTAL** (voids) |
| Longitudinal localisation, baseline | BLOCKED | drawings; L-X / L-XZ | ΔX; recall | depth-gated recall 0.000–0.053; matches coincidental | **FAILED** |
| Longitudinal localisation, E1 | — | same rules, frozen on dev | ΔX | test median 5–10 mm, RMSE 19–26 mm | **EXPERIMENTAL** |
| 2D / lateral localisation | BLOCKED | Pk401 drawings; unbiased all-line gate | ΔY | centroids 2–50 mm off but not laterally confined | **FAILED** (both arms) |
| Candidate generation, baseline | measured poor | ring z at crowns | max abs z at target | 1.7–2.0 < 3.0 | **FAILED** |
| Candidate generation, E1 | — | dev/test protocol | recall L-XZ | 0.75–0.82 on test | **EXPERIMENTAL** |
| False-positive rejection | 1.7–2.8 per line on control | taxonomy | FP per line | baseline low only because insensitive; E1 18–43 per line | **FAILED** |
| Object detection (baseline) | recall 0.065 / 0.093 | reproduced; depth-gated | recall, precision | L-XZ recall 0.005 / 0.053 | **FAILED** |
| Truth-side gates (origin, units, DZT mapping, depth reference) | BLOCKED | drawings, exact mapping, orientation fit | — | evidence complete | **BLOCKED in code**: the resolution edit was refused by the permission system; **proposed** below |

**Proposed gate change (not applied):**
- In `benchmark/gates.py`, set `absolute-origin`, `coordinate-units`, `dzt-to-grid-mapping` and `depth-reference-surface` to RESOLVED, each with the evidence text from this document.
- Set `LOCALIZATION_STATUS` to RESOLVED, meaning localisation is **scoreable**, not that it is validated.
- Make `score_localization` still refuse, with `NotImplementedError` pointing to this research scorer.
- Mirror the change in `benchmark/manifests/bam-pk266.targets.json`, with frame origin/units/registration → declared and the cover-vs-centre question made non-blocking.
- Add `bam-pk401.targets.json` from the evidence CSV.
- Update `tests/test_bam_benchmark_pipeline.py` and `tests/test_bam_target_migration.py`, which pin the current BLOCKED state on purpose.

## 12. Limitations

- **Domain:** concrete laboratory specimens at 1.5 and 2.6 GHz, metal ducts and foam voids. None of this transfers to soil, utilities or field-scale localisation.
- **Small numbers:** 4 ducts and 4 cuboids. Repeated scans re-measure the same objects, so confidence intervals are wide.
- **Evidence grade B:** fabrication drawings, not re-surveyed; the specimens are about 25 years old, and Pk401 was stored outdoors.
- **Known-position depth is not end-to-end depth:** it isolates conversion from detection, and end-to-end depth depends on the candidate chosen.
- **Calibration needs a known reflector:** the back wall. Most field data has none, so the PARTIALLY_VALIDATED t0/velocity route does not carry over as such.
- **2.6 GHz back walls:** unresolvable on the thick steps of Pk050 and Pk401.
- **Rule amendments:** three were made after seeing calibration outputs (documented in §4 and in the script), none after seeing target or detector metrics.

## 13. Recommended next engineering work

1. **Redesign candidate generation before any AI classifier.** Keep E1's background-removed envelope (it finds the targets) and add hyperbola-shape scoring (matched template or curvature consistent with the calibrated velocity), cross-line consistency (an object persists over adjacent lines; a duct across all of them, a cuboid across about 24), and non-maximum suppression in 3D. Target: hold L-XZ recall ≥ 0.75 on Pk401/Pk266 test scans while cutting control false positives below about 2 per line.
2. **Fix Method C before using it for depth:** pick a convention matched to how reflection times are read (peak, or onset for both); widen and clean the quiet window (exclude samples 0–2 when overwritten); detect floor-pinned picks and refuse them.
3. **Treat t0 + v from known geometry as the depth-chain reference** where a known reflector exists, and keep it labelled DERIVED_FROM_KNOWN_GEOMETRY.
4. **Apply the gate proposal** in §11 once approved, then implement product localisation scoring against the pre-registered rules.
5. **Regression fixture:** see §14A.

## 14. Regression issues (investigated)

**A. The four "IDS .dt" regression failures are neither IDS nor a regression.**
- The failing tests (`tests/test_gpr_regression_baseline.py`, processed and anomaly grids for `C1T_7,5_0001/0002`) use **INGV SEG-Y** lines.
- They fail **at the commit that introduced the test** (`084f61d`, 2026-08-06) and at every later commit sampled. The raw grids pass.
- numpy 2.1.1 and scipy 1.14.1 (pinned and unchanged) were reinstalled on 2026-09-29 on a newer macOS that uses Apple Accelerate. The exact sha256-of-float64 digests captured on 2026-08-06 no longer reproduce.
- **Classification:** a platform-specific test-fixture issue, not a regression and not related to the signed-int16 fix (which is kept).
- **Not fixed:** re-pinning the digests would hide genuine drift. Recommended: store the reference arrays and compare with an explicit tolerance plus an environment fingerprint.

**B. The MALA `.RAD`/`.rad` collision is a real implementation bug, now fixed.**
- On a case-insensitive filesystem, `find_rad` probed `x.rad`, which "exists" when the file is `x.RAD`, and returned the probed spelling, recording a filename not on disk.
- It now returns the real directory entry: exact spellings first, then a case-insensitive match. Behaviour on case-sensitive filesystems is unchanged.
- `tests/test_mala_converter.py`: 37/37 pass. MALA/Hillside/TU1208/Yesan suites: 126 pass.

## 15. Answers

1. **Can Subterra measure depth accurately inside BAM specimens?** Yes, but only for metal ducts at a known position with a known-geometry (back-wall) calibration. It does not yet do so from its own detector output, and void-analogue depths are biased.
2. **Error:** ducts mean +7.1 mm, MAE 7.1 mm, RMSE 7.7 mm, P95 11.0 mm (16 measurements of 4 objects, both antennas). Cuboids +27 mm. With Method C t0, ducts +43 mm; with no t0, +72 mm.
3. **Can Subterra locate known objects in metres?** Not with the current detector: its "hits" are coincidental (depth-gated recall ≤ 5%). The experimental E1 candidates do, longitudinally, on held-out scans.
4. **Localisation error:**
   - Baseline: median 45–55 mm, but not real matches.
   - E1 (test): median |ΔX| 5–10 mm, RMSE 19–26 mm, P95 30–65 mm.
   - Lateral: not demonstrated (candidates not confined in Y).
5. **Why the detector is poor:** its ring z-score statistic stays below threshold (|z| ≈ 1.7–2.0) exactly where the targets are, while firing on direct-wave residue, gain-amplified late noise and step edges. X-only matching then credits coincidences.
6. **Single change that would help most:** replace the ring z-score candidate statistic with a background-removed envelope (E1's core). On held-out scans it raised depth-gated recall from 0.053 to 0.818 (Pk266 2.6 GHz) and from 0 to 0.75 (Pk401 1.5 GHz), at the cost of false positives that the next step (hyperbola and cross-line scoring) must remove.
7. **Is Method C helping or hurting?** Hurting, in the depth chain: +43 mm duct bias vs +7 mm with a geometry-calibrated t0. It agrees with the paper's t0 on 2 of 3 specimens at 1.5 GHz but is unstable on Pk266 and floor-pinned at 2.6 GHz. It is better than no correction (+72 mm).
8. **Can now move from blocked → validated:**
   - Raw DZT ingestion and amplitude preservation: **VALIDATED**.
   - Known-geometry velocity and t0 calibration, and duct depth conversion at known position: **PARTIALLY_VALIDATED**.
   - The truth-side BAM gates have the evidence to move to RESOLVED, **pending your approval** (the edit was refused).
9. **Remain blocked or failed:**
   - Code gates (localisation and depth scoring), until approved.
   - Detector-based localisation, 2D/lateral localisation, false-positive rejection, object detection.
   - Void-analogue depth, Method C as a depth-chain t0, and every 2.6 GHz Pk050/Pk401 calibration.
10. **Is the candidate generator good enough to build an AI classifier on?** No. The baseline misses the targets almost entirely: a classifier cannot recover objects that are never proposed. **Redesign candidate generation first.** E1 shows the targets are proposable (recall 0.75–0.82 held out), but at 15–43 false candidates per line. The next step is physics-constrained scoring (hyperbola shape, cross-line persistence, 3D NMS), and only then a learned classifier on top.
