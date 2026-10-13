# CCD-V1 Stages 0 and 1: frozen protocol and amendments

**Status:** FROZEN. This file was committed before any Stage 0 or Stage 1 computation ran. It implements §5–6 of `docs/coherent-clutter-discrimination-v1-brief.md`, which stays unchanged at commit `cb12628` as the baseline. Results go in `docs/ccd-v1-stage0-1-results.md`, written afterwards.
**Scope:** Stages 0 and 1 only. **Stage 2 is on hold.** No corpus is generated, no detector is implemented, and no production code is touched. The code lives in `scripts/ccd_v1_stage0.py`, `scripts/ccd_v1_stage1.py` and `scripts/ccd_v1_stats.py`, and the outputs go to `artifacts/ccd_v1/`.
**Existing outputs are preserved.** Nothing under `artifacts/simulation/hyperbola_v2/`, `artifacts/realdata/hyperbola_v2/`, `artifacts/bam/` or `evidence/` is rewritten. Every re-run writes new files.

---

## A. Amendments to the brief (made before any Stage 1 data was read)

**A1. H5's direction is replaced by a magnitude.**
- **The problem.** The brief predicted "Rot00/Rot90 ratio: ducts > cuboids". The direction of that ratio depends on whether Rot00's E-field is parallel or perpendicular to the ducts. No source read for this project documents the antenna's E-field orientation relative to the specimen axes.
- **The fix.** The pre-registered statistic is the **magnitude** of polarisation dependence: P = |ρ|, where ρ = log(A₀₀/A₉₀) − log(BW₀₀/BW₉₀). The prediction is ducts > cuboids, one-sided. The signed ρ is reported, but no direction is tested.

**A2. H6 no longer uses the drawn extent.**
- **The problem.** The brief's statistic was "lines with a response, as a fraction of the object's drawn extent". That uses truth to normalise and measures detection completeness, not elongation: both classes would score about 1.
- **The fix.** F8 is the **half-maximum run length along Y, in mm**, through the line of maximum response, with no truth extent used. H6 remains a **pipeline sanity check**: an 800 mm duct against a 120 mm cuboid is near-tautological.

**A3. H7 no longer assumes the ducts are metal.**
- **The problem.** The brief predicted the ducts to be "reversed, metal". `evidence/bam/specimen_ground_truth.csv` says the duct material is **"not stated"**, so that prediction rests on an assumption that is not in the truth.
- **The fix.**
  - **H7a (attributable).** Polystyrene cuboids are predicted to show polarity **opposite** to the aluminium back wall: concrete → polystyrene has Γ > 0, and concrete → aluminium has Γ = −1. This holds for c < 0 on k of 4 cuboids, tested by an exact binomial against 0.5.
  - **H7b (descriptive).** The duct polarity is **measured and reported**, and a two-sided exact Mann–Whitney test asks only whether ducts and cuboids **differ**. No material is inferred from the duct sign.

**A4. The dual-frequency feature is reported as not testable.** H7b in the brief (F6, dual-frequency) cannot compare the two classes. Pk401 2.6 GHz has no known-geometry calibration (it was REFUSED in `bam_quantitative_validation`), so cuboid apex times at 2.6 GHz are unknown. F6 is computed for the ducts only, as a description.

**A5. The 4TU H8 and H9 tests are not run in this stage.** The brief lists them among the hypotheses but assigns them to neither Stage 0 nor Stage 1. They need the V2 detector run on all 759 4TU radargrams, which this approval does not cover. Stage 0d only audits whether H9 is measurable.

---

## B. Stage 0: diagnostics (spent data; descriptive; no gate)

### B0a. Attribution of every V2 false positive

**Population.**
- Scenes: the corpus_s1_v2 eval split (198 scenes).
- Condition: primary (`instrument_20spp|noise_4tu_median`).
- Arm: A3 with the frozen parameters (`simulation/hyperbola_v2_freeze.json`, committed in 09dc288).

**Reproduction check.** A3 is re-run deterministically to recover per-detection positions. Each scene's `n_det` and each class count must equal the stored `artifacts/simulation/hyperbola_v2/evaluate.jsonl`. Any mismatch stops Stage 0a and is reported.

**Notation.** T = 1/f, λ = v/f and χ = √2/f, the Ricker delay already included in every truth event time. For a truth event time t, its first surface multiple is t_m = 2t − χ.

**Rules.** Every unmatched detection goes into the first category whose rule it meets. Existing `score_v2` classes are kept as they are.

| Order | Category | Rule | Kind |
|---|---|---|---|
| 1 | `duplicate` | existing | **policy**: a real response of a scored object, counted as an FP by the one-to-one rule |
| 2 | `limb` | existing (within T of a scored target's predicted event on that trace) | **policy** |
| 3 | `early` | existing (t ≤ direct-wave end) | **system**: direct wave |
| 4 | `clutter_object` | existing (within ±λ and the event window of a clutter stone) | **generator object** |
| 5 | `layer` | existing (within T of the layer time) | **generator object** |
| 6 | `stone_limb` | within T of any clutter-stone predicted event (top or internal) on that trace, at any x | **generator object** |
| 7 | `layer_multiple` | within T of 2·t_layer − χ | **generator object** |
| 8 | `target_multiple` | within T of 2t − χ, for any scored-target event t on that trace | **scored-target physics** |
| 9 | `target_late` | \|x − x_target\| ≤ 3λ, and t later than the target's window end (last event + T) by no more than 6T | **scored-target physics** (ringing, creeping or interior waves) |
| 10 | `direct_tail` | t ≤ direct-wave end + 2T | **system**: boundary of the `early` policy |
| 11 | `unexplained` | none of the above | split by B0a′ |

**B0a′. Noise-free attribution of `unexplained` detections.** The scene is digitised identically with **no noise**, giving two lines:
- F: the full scene, mean-trace-removed;
- B: the target-free twin, which keeps the stones and the layer, mean-trace-removed.

At the detection cell (the nearest sample and trace) we take Hilbert envelopes:
- e_F = |H(F)|;
- a = |H(full − twin)|, the scored targets' raw scattered field;
- m = |H(mean over traces of (full − twin))|, the imprint of mean-trace removal at that sample;
- s_F = the median of |H(F)| over the line after the direct-wave end.

| Subclass | Rule |
|---|---|
| `unexplained_noise` | e_F < 3·s_F: there is no noise-free response there; it is noise-induced |
| `unexplained_imprint` | otherwise, if m > a: an artefact of background removal |
| `unexplained_target_field` | otherwise, if a ≥ 0.5·e_F: real scattered field from scored targets, outside every geometric rule |
| `unexplained_twin_field` | otherwise: real energy present in the twin (stones, layer, direct wave) outside every rule |

**What "genuinely unexplained" means.** Only `unexplained_target_field` and `unexplained_twin_field` count as unexplained radar responses. `unexplained_noise` is a statistically expected false alarm. `unexplained_imprint` is a processing artefact.

**Reporting.**
- Counts per category and kind, by family.
- The top-level split: (i) generator objects, (ii) scoring-policy artefacts, (iii) system or processing artefacts (`early`, `direct_tail`, imprint), (iv) scored-target physics, (v) noise-induced, (vi) genuinely unexplained wavefield.

### B0b. Task A re-score (descriptive)

`score_located` is applied to the **full** truth: clutter stones become objects to be matched under the same window rule. The re-score reports:
- recall over all objects;
- recall over stones only;
- precision;
- FP per **physically empty** scene (no objects, no stones), with its n.

### B0c. 4TU amplitude-preservation audit

For every 4TU `.sgy` (all files):
- the SEG-Y textual header is searched for gain or processing words;
- trace-header gain fields are read (bytes 119–124: gain type, gain constant, initial gain);
- the sample format code is recorded;
- an **amplitude-trend indicator** is computed: the RMS over the last 30% of the window, divided by the RMS over 20–35% of the window (after the direct wave), from the median trace envelope.

**Outcome rule.**
- `not_preserved` if a header or the documentation states that gain or AGC was applied.
- `preserved` only if documentation states raw export.
- `unknown` otherwise, with the indicator's distribution reported as **circumstantial evidence only**. An indicator cannot establish provenance.

### B0d. 4TU cross-line geometry audit

For each activity: the number of `.sgy` paths; per path, coordinates decoded from SourceX/SourceY under the corpus's declared `ieee_nmea` encoding, the fraction of valid fixes, length and heading.

A **parallel pair** is two paths with:
- headings within 15°;
- median perpendicular separation ≤ 2 m;
- along-track overlap ≥ 5 m.

**Outcome.** The list of activities with ≥ 1 parallel pair: F8 is *measurable in principle* there. Registration accuracy is **unverified** in every case, because no GNSS quality field or documentation states it.

### B0e. BAM object footprint table (no radar picks)

For each object and scan (1.5 GHz Rot00 and Rot90 on all three specimens; 2.6 GHz Rot00 and Rot90 on Pk266):
- x node;
- lines with |y − y_obj| ≤ 60 mm (cuboids). For ducts, the central band Y 100–700 mm, which excludes the edge-rebar zones;
- the expected top time t_e = t₀ + 2·z_top/v, from the stored known-geometry back-wall calibration (`evidence/bam/results/quantitative_validation.json`, `calibration_backwall_peak`);
- the back-wall time for the object's step (the stored `backwall[step].t_ns`);
- the reference x set: nodes 120–200 mm from the object on both sides, inside the same 500 mm step and ≥ 60 mm from step edges.

**The acquisition-parameter confound table.** DZT header fields (range, samples, bits, ε setting, and any gain fields read by `read_dzt_header`) for every scan, side by side.

---

## C. Stage 1: BAM features at known object positions (EXPLORATORY)

**Labelling.** **EXPLORATORY: every BAM specimen and scan has been used in previous research (PR #12, PR #13, `bam_quantitative_validation`, the trace-span experiment). No result here is independent validation. CONCRETE NDT ONLY.**

**Units.** **One object is one unit.** The 161 lines and 3 trace nodes over one object are repeated measures of one unit and are summarised by their **median** before any test. Line-level values are shown only as distributions, never as n.

**Primary frequency.** 1.5 GHz (calibrated on every specimen and rotation). The Pk266 2.6 GHz duct values are a descriptive replication.

### C1. The per-line object response (shared by every feature)

On line j, the object trace is the mean of the traces within ±10 mm of x_obj (3 nodes). The reference trace is the mean of the reference x set. The response is r_j = object − reference.

The window is W = [t_e − 0.5T, t_e + 1.0T], with T = 1/f_nominal. Then:
- p_j = argmax over W of |H(r_j)|;
- A_j = |H(r_j)|(p_j).

The back-wall reference on line j is b_j = the mean of the reference traces, raw, with no subtraction because the back wall is flat. Its peak q_j is the envelope argmax within ±0.5T of the step's stored back-wall time, and BW_j = |H(b_j)|(q_j).

### C2. The features, each evaluated on its own

- **F1, polarity.**
  - Take two wavelets: r_j in [p_j − 0.6T, p_j + 0.6T] and b_j in [q_j − 0.6T, q_j + 0.6T].
  - c_j = their normalised zero-lag correlation (both peak-centred), in [−1, 1].
  - The object value is the median of c_j over its lines. c > 0 means the same polarity as the aluminium back wall (Γ = −1); c < 0 means opposite.
- **F7, polarisation.** On each line, ρ_j = log(A_j⁰⁰ / A_j⁹⁰) − log(BW_j⁰⁰ / BW_j⁹⁰), using the co-registered Rot00 and Rot90 volumes (the same grid; t_e is computed per rotation from its own calibration). The object value is P = |median ρ_j|. The signed median is reported.
- **F8, continuity.**
  - Over every line in Y 100–700 mm, compute A_j (Rot00, 1.5 GHz).
  - Find j* = argmax A_j.
  - The run is the contiguous set of lines through j* with A_j ≥ 0.5·A_j*.
  - The object value is the run length in mm: (n_lines − 1) × 5 mm.
  - The search uses the object's x and depth (an oracle position) but **not its Y extent**.

### C3. Tests (exact; 4 ducts vs 4 cuboids)

The exact Mann–Whitney U is computed by enumerating all 70 splits.

| ID | Statistic | Alternative | Smallest attainable p | Decision bar |
|---|---|---|---|---|
| H5 | P = \|ρ\| | ducts > cuboids | 1/70 = 0.014 | p ≤ 0.05 (U ≥ 15) |
| H6 | F8 run length | ducts > cuboids | 1/70 | p ≤ 0.05; **sanity check only** |
| H7a | cuboid c < 0 | count of 4, exact binomial against 0.5 | 1/16 = 0.0625 | **cannot reach 0.05 with n = 4**: reported as k/4 with its exact p |
| H7b | median c | ducts ≠ cuboids, two-sided | 2/70 = 0.029 | descriptive; no material is inferred |

**Uncertainty.** Each comparison reports:
- n per group;
- U;
- the exact p;
- the Hodges–Lehmann shift (the median of the 16 pairwise differences);
- the range of the 16 pairwise differences, which is an exact **97.1%** confidence interval for the shift (1 − 2/70) under the location-shift model.

### C4. Controls

1. **Object-free phantoms (null).** The features are computed at the 8 object (x, z_top) positions in **Pk050**, which has no embedded objects, using Pk050's own calibration. F8 there gives the null run length.
2. **Off-object lines in Pk401.** The 4 cuboids' (x, z_top) are evaluated on lines Y 100–250 mm and 620–700 mm, which lie outside every cuboid's Y extent by ≥ 80 mm. This gives a within-specimen null for F1 and F7.
3. **The specimen-identity control (brief §6.4).** Features F1 and F7 are computed at the same x positions, on the same lines, in a **late, object-free window** centred at t_e + 3T, for both Pk266 and Pk401. This gives 4 values per specimen. The Mann–Whitney AUC between specimens must lie in [0.30, 0.70] (U ∈ 5..11). If it does not, any Pk266-vs-Pk401 difference in that feature is **declared confounded with specimen identity**.
4. **The confound table** (§D) is reported with every result.

### C5. Arm D: features at V2 candidates (descriptive only, no inference)

- **Detections.** A3 with the frozen parameters, re-run on all 161 lines of the 1.5 GHz Rot00 scans of Pk266, Pk401 and Pk050, written to new files.
- **Classification of each detection.**
  - `object` if within ±100 mm of an object's x (for cuboids, also |y − y_obj| ≤ 60 mm) and within 1T of t_e;
  - otherwise one of: `back_wall` (within T of the step's back-wall time), `below_back_wall`, `direct` (t < t₀ + 2T), `step_edge` (within 60 mm of x = 500/1000/1500), `edge_rebar_zone` (y < 100 or y > 700 mm), or `other`.
- **Features at each detection:**
  - F1, taking the detection's (x, t) as the object position;
  - F7, read from the Rot90 volume at the same cell;
  - F8, the number of contiguous adjacent lines with a detection within ±10 mm and ±0.5T, × 5 mm.
- **Reporting.** The median and IQR per class. `object` detections are also summarised per object (8 units). Non-object detections are **not** units and get no p-value.

### C6. Combination

Combination comes **only after** the independent tables. With 4 + 4 units, no combined statistical test is valid in Stage 1. The report shows one object × feature table and counts how many features order each object as predicted. **No classifier is fitted.**

---

## D. Confounds that must be reported with every Stage 1 result

| Factor | Ducts (Pk266) | Cuboids (Pk401) | Consequence |
|---|---|---|---|
| Specimen | Pk266 | Pk401 | object class ≡ specimen: **perfect confounding** |
| Concrete | C32.5 GK16; v ≈ 0.129 m/ns at 1.5 GHz | C30/37 GK16; v ≈ 0.103 m/ns | different permittivity and probably attenuation, controlled only by the within-specimen references (back wall, reference traces) and control C4.3 |
| Material | **not stated** | polystyrene | **no material attribution for the ducts** |
| Geometry | linear (800 mm along Y), Ø67 | compact, 120 × 120 × 60 | shape ≡ class |
| Depth (top) | 241 / 181 / 118 / 61 mm | 240 / 180 / 120 / 60 mm | matched by design: **not a confound** |
| x position | 250 / 750 / 1250 / 1750 | the same | matched |
| Antenna, grid, instrument | GSSI SIR-20, the same grid | the same | matched, to be confirmed in B0e's DZT table |
| Rotation and frequency | the same scans per specimen | the same | matched |

**Attribution rule.**
- **F7 and F8.** A significant duct-vs-cuboid difference that passes control C4.3 may be attributed to **"the object class (linear duct vs compact cuboid) in these two specimens"**. Shape and material cannot be separated, so it may **not** be attributed to shape, material or conductivity individually.
- **F1.** Only H7a (cuboids against the physics prediction, using a within-specimen reference) is attributable to material contrast.
