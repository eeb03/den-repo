# Coherent Clutter Discrimination V1: research phase brief

**Status:** BRIEF FOR REVIEW. Nothing in it has been implemented or run. **Approval is needed before any code, simulation or analysis.**
**Branch:** `research/coherent-clutter-discrimination-v1`, from `exp/hyperbola-v2` (PR #13, draft, REJECT). PRs #12 and #13 stay unmerged, and production code is untouched.
**Written:** 2026-10-13.
**Inputs read:**
- `ROADMAP.md`, `AGENTS.md` and `docs/roadmap-to-completion-draft.md` (Part C′, the zero-budget plan, is active);
- `docs/detector-saturation-experiment.md` (PR #12), `docs/hyperbola-v2-experiment.md` (PR #13) and `docs/detector-multiscale-experiment.md`;
- `docs/candidate-intelligence.md`, `docs/ground-truth-benchmarks.md`, `docs/bam-benchmark-detection.md` and `docs/research/bam_quantitative_validation.md`;
- `docs/4tu-utility-benchmark.md`, `docs/dataset-inventory.md`, `docs/roadmap.md` (the SSL encoder) and `docs/simulation.md`;
- the committed evidence in `evidence/detector_saturation/`, `evidence/hyperbola_v2/` and `evidence/bam/`.

**What was looked at while writing this, beyond the documents.** Facts derived from existing artifacts are marked † where they are used. They are:
- V2's eval false positives, by class and family (`evidence/hyperbola_v2/report.json` and the eval JSONL);
- the FP-class rules in `simulation/background_benchmark.py`;
- the generator's object and clutter constants (`simulation/generator.py`, `generator_v2.py`);
- the marginal counts of the 4TU `Metadata.csv` context fields.

**No relationship between any detector output and any 4TU context field has been computed.** Those are pre-registered below as untested hypotheses.

---

## 0. The question, in one sentence

Can Subterra tell **utility-relevant targets** from **coherent non-utility scatterers** (stones, rubble, roots, layer edges, reinforcement, antenna/system artefacts) using information it can measure? Can it do so **before** another detector architecture is built? And where it can't, can we show that the limit is in the data rather than in the method?

---

## 1. What has been tried, and how it failed

### 1.1 The record

| Method | Where | What it showed | Status |
|---|---|---|---|
| Production ring z-score at 3.0 | BAM, 4TU, INGV, corpus_s0, corpus_s1_v2 | Saturates on any laterally coherent target: 0/382 synthetic targets, BAM depth-gated recall 0.000–0.053, 4TU AUC 0.445 [0.22, 0.66] | Production; at chance |
| Ring threshold tuning | BAM dev | No threshold rescues a statistic that sits below 3.0 at the targets and above 3.0 in the direct-wave and late bands | Do not repeat |
| Trace-span post-filter (K) | BAM | K = 1 selected; recall collapses fourfold by K = 2 | Rejected |
| Multi-scale estimator | synthetic, BAM, 4TU | Fixes width saturation on synthetic; BAM gain confined to one duct; 4TU at chance | Not promoted |
| Widened ring | PR #12 | Recall 0.03; 38–105 FP per BAM line from back-wall and rebar | REJECT |
| E1 envelope local maxima (BAM) | `bam_quantitative_validation.md` | Targets are detectable (L-XZ recall 0.75–0.82), at 15–43 FP per line | Experimental, unusable alone |
| Hyperbola stack at fixed z = 6 | PR #12 | Synthetic recall 0.69 but precision 0.44, with limbs dominant; z = 6 does not transfer (6–59 FP per BAM line) | KEEP_EXPERIMENTAL |
| V2: grouping + per-line null calibration + canonical input + fast stack | PR #13 | Fresh-corpus recall 0.51, precision 0.44, 1.67 FP per empty scene. Sampling-invariant precision. BAM held-out recall 0.42–0.44 at fewer FPs than production | REJECT (G1, G2) |
| SSL encoder (masked reconstruction) | `docs/roadmap.md` | Transfers to unseen sites on reconstruction loss. The BAM target-cell probe is **inconclusive**: both models are below chance on rank | Promising but variable |

### 1.2 What the failures have in common

Every method so far is a **single-line, single-polarisation, single-frequency, shape-or-contrast statistic**: a ring, a window, an envelope maximum or a diffraction stack. Each asks one question: *is there a localised coherent scatterer here?* None asks *what kind of scatterer is it?* A stone, a cable and a void crossing one B-scan all produce a diffraction hyperbola. A shape statistic that finds one finds all three. **The precision ceiling we keep hitting is not a detector-tuning problem. The task is under-specified for the information used.**

### 1.3 Three corrections to the record that change the framing †

1. **V2's largest false-positive class is not geological clutter.** PR #13 §11 called its largest class "diffuse clutter". In fact `score_located` labels as `clutter` any unmatched detection that is after the direct wave, not within one period of a predicted target event, and not near a stone or a layer. The synthetic soil is **homogeneous** (no fractal or heterogeneous medium is generated), so this class is a **residual of unexplained late events**: candidate sources are stone limbs outside the ±1 λ stone window, target multiples and ringing, and noise peaks. The class (98 of A3's 193 eval false positives) needs decomposing before anything is built against it (Stage 0). PR #13's wording should be amended when that PR is next touched.
2. **The stone false positives are partly a task-definition artefact.**
   - 103 of the 302 scored eval targets are **rocks**, and the generator scores rocks of radius 0.15–0.50 λ as targets.
   - Clutter stones are rocks of radius 0.03–0.08 λ, which is the same radius range as **cables**.
   - In `empty_clutter`, 46 of A3's 55 false positives are the stones themselves.
   - So V2 was penalised for detecting rocks smaller than an arbitrary radius. **Under an anomaly-detection task those 46 are correct.** Recomputing V2 under that task (descriptive, and on a spent split) bounds A3's precision at most at (154 + 46) / 347 = 0.58, still below the 0.60 bar.
3. **The synthetic corpus cannot represent the main real-world discriminator.**
   - gprMax 2D TM models every object as an **infinite cylinder** normal to the scan, with a single polarisation.
   - In 2D, a "stone" *is* a cylinder, and its out-of-plane extent, the property that most separates a utility (long, linear) from a stone (compact), does not exist.
   - Polarisation dependence does not exist either.
   - **No 2D simulation can test spatial continuity or polarisation.** Every 2D result about stone-versus-utility discrimination is limited to in-plane signal properties.

---

## 2. Physically meaningful discriminators

Each candidate feature has a physical reason to differ between classes, a known failure mode, and a measurability status on what Subterra already holds.

### 2.1 The feature inventory

| # | Feature | Physical basis | Separates | Fails on |
|---|---|---|---|---|
| F1 | **Reflection polarity** (sign of the apex wavelet relative to the direct or surface wave) | Sign of the impedance contrast: metal and high-ε inclusions reverse it; voids, air-filled plastic and low-ε inclusions do not | metal from void/air; high-ε stone from low-ε stone | **metal vs high-ε stone** (same sign); water-filled plastic pipes (sign set by the water) |
| F2 | **Corrected reflection strength** (apex amplitude normalised to the direct wave, corrected for geometric spreading and attenuation using the detector's own v̂) | \|Γ\| ≈ 1 for metal against \|Γ\| = \|√ε₁ − √ε₂\| / (√ε₁ + √ε₂) ≲ 0.3 for natural contrasts | metal from stones | small metal (cables) vs large stones; needs amplitude-preserving data and an attenuation estimate |
| F3 | **Diffraction-curve completeness and amplitude-vs-offset** (support fraction along the fitted curve; amplitude decay with offset) | Cylinders and points have different AVO; a stone's internal multiple and a pipe's interior echo differ in delay | pipe with interior echo vs solid stone | weak targets; overlapping events |
| F4 | **Interior/second-event structure** (delay and polarity of a second event below the apex) | Hollow pipes give a top and a bottom echo set by interior fill; voids give opposite-polarity top and bottom; stones give an internal echo at √ε-scaled delay | hollow utility vs solid stone | sub-wavelength objects (events merge) |
| F5 | **Spectral shift** (centroid or bandwidth of the target echo relative to the direct wave) | Sub-wavelength scattering is frequency-dependent (Rayleigh-like for compact objects, different for cylinders); conductive soil adds a separate low-pass | size and shape regime | confounded by depth-dependent attenuation |
| F6 | **Dual-frequency ratio** (response at f₁ vs f₂ on the same object) | Same as F5, without the single-band confound | size regime | needs co-registered dual-frequency data |
| F7 | **Polarisation ratio** (response with antenna rotated 0° vs 90°) | A long conductor responds strongly with E parallel to its axis; compact or isotropic objects are weakly polarisation-dependent | **linear conductor vs compact object**; also orientation | dielectric (plastic) pipes are weakly polarisation-dependent |
| F8 | **Along-axis continuity / elongation** (a candidate that recurs on adjacent parallel lines at a consistent apex time, offset and velocity, forming a line in plan view) | Utilities are long and linear (the 4TU metadata: "Utility path linear = Yes" for 104 of 116 recorded activities); stones and rubble are compact | **utility vs stone**: the strongest physical discriminator | requires multi-line geometry with known line positions; short utility stubs; rubble trenches that are themselves linear |
| F9 | **Context and clutter density** (rate of null-calibrated candidates per metre on the line; texture statistics; layer presence) | Rubble fill and root zones raise the local scatterer density | supplies the prior, not the per-candidate label | correlated with urban land use, which also carries utilities |
| F10 | **Learned features** (frozen SSL encoder embedding at the candidate) | Unknown | unknown | no evidence yet; the BAM probe was inconclusive |

### 2.2 Measurability: what exists versus what needs new acquisition

| Feature | Synthetic 2D (corpus_s0/s1_v2) | BAM (3D grid, 2 polarisations, 2 frequencies) | 4TU (real utilities, activity truth) | INGV | Needs new data |
|---|---|---|---|---|---|
| F1 polarity | yes | yes (metal ducts vs polystyrene cuboids) | measurable, but no object truth | measurable, no truth | — |
| F2 corrected strength | yes (amplitudes preserved) | yes (amplitude preservation validated, 400/400) | **unknown**: whether the SEG-Y export applied gain must be audited first | unknown | an amplitude-preserving field acquisition |
| F3 curve/AVO | yes | yes | measurable, no truth | measurable | — |
| F4 interior events | yes, but only PEC (no interior) and voids; **no plastic or water-filled pipe class exists** | partly (ducts are metal; cuboids have top/bottom) | no truth | no | a plastic-pipe class (generator) and real plastic utilities |
| F5 spectral | yes | yes | measurable, no truth | measurable | — |
| F6 dual frequency | needs new 2D runs (each scene at two frequencies) | **yes, held** (1.5 and 2.6 GHz on the same specimens) | no (single antenna) | no | — |
| F7 polarisation | **impossible in 2D TM** | **yes, held** (Rot00 and Rot90) | no | no | 3D simulation or real dual-polarisation data |
| F8 continuity | **impossible in 2D** | **yes** (161 lines at 5 mm) | plausible: multiple paths per activity with header NMEA positions, but cross-line registration accuracy is **unverified** | unknown | 3D simulation; real grids over known linear utilities and stones |
| F9 context | layer only; no heterogeneous soil | concrete, not soil | **activity-level labels exist** (rubble 35/125, tree roots 17/125, ground condition, land use) | no | site-level clutter surveys |
| F10 SSL | yes | yes | yes | excluded (licence) | — |

**Reading the table.** Most of the features with the most physical leverage (F7, F8, and partly F6) **cannot be tested on simulated 2D data at all**. On real data they can be tested only on **BAM**: concrete, two specimens with eight embedded objects, and every scan already development-exposed (§4.3). F1–F5 can be tested on synthetic data, but only for in-plane identity. The decisive real-world question, **"is this compact scatterer a stone or a short utility crossing?"**, needs multi-line data over attested utilities **and** attested stones. **Subterra holds none.**

---

## 3. Anomaly detection is not object classification

### 3.1 Two tasks, scored separately from now on

| Task | Question | Positive | Negative | What a rock is |
|---|---|---|---|---|
| **A, anomaly detection** | Is there a localised subsurface scatterer here? | any embedded object or localised discontinuity: pipe, cable, void, stone, root, rubble block | homogeneous ground, planar layers, system artefacts (direct wave, ringing, multiples), noise | **a true positive** |
| **U, utility-relevant discrimination** | Given an anomaly, is it consistent with a utility? | pipes and cables (metal and plastic), ducts, chambers | stones, rubble, roots, voids*, layer edges, reinforcement* | **a correct anomaly, but a false positive for U** |

\*Voids and reinforcement are **not utilities, but they are not clutter either**. A void under a road is a hazard that a utility survey should report. Rebar is the target in concrete NDT. Task U therefore has a third outcome: **"non-utility anomaly of interest"**. The product must never fold these into "clutter".

### 3.2 When a rock is valid, and when it is a false positive

- **Under Task A**, a rock is always a valid detection. Reporting it is the detector working. Scoring it as a false positive (as PR #13's G2 did for clutter stones) measures the task definition, not the detector.
- **Under Task U**, a rock is a false positive **only if the system claims utility-likeness for it**. A candidate list that says "anomaly, type undetermined" for a rock is correct. The error is "probable utility".
- **Consequence for gates.** Detector gates (recall, FP per empty scene) belong to Task A, with **physically empty** negatives: no scatterers at all. Discrimination gates belong to Task U and are scored on **candidates that Task A already produced**. One gate must never mix the two.

### 3.3 What this means for the product

This is the roadmap's own Phase 6 → Phase 8 rule ("Candidate ≠ Detection"; "something anomalous appears here" before "this is probably a pipe"). This phase adds one thing: Task U outputs are **evidence dimensions on a candidate** (polarity, strength, continuity, polarisation), each with its measurability status. They are not a class label. A label requires the Task U gates of §6 to pass on real data, which is out of reach with current data (§4).

---

## 4. Is the evidence sufficient?

### 4.1 Per-dataset sufficiency

| Dataset | Object truth | Hard negatives (attested non-utility scatterers) | Exposure | Supports |
|---|---|---|---|---|
| corpus_s0 (300 2D scenes) | full | rocks (as targets), no clutter stones | **all splits development-exposed** (PR #12 test spent) | feature development only |
| corpus_s1_v2 (280 2D scenes) | full | clutter stones, layers | **dev used for V2 selection; eval spent by PR #13** | feature development only |
| BAM Pk266 / Pk401 / Pk050 | 4 metal ducts (linear); 4 polystyrene cuboids (compact); 4 grouted boreholes; edge rebar; anchors; stepped back walls | rebar (linear, metal), boreholes, back-wall steps; **no stones**; Pk050 has no embedded objects | **every scan development-exposed** (Pk266 1.5 GHz Rot00 is dev in every experiment; the others were test in PR #12, PR #13 and E1). Rot90 was used to choose K in the trace-span experiment and in the back-wall velocity calibration. No Rot90 detection score is published in the documents read | real-data feasibility on known geometry: **exploratory, not independent validation** |
| 4TU (125 activities) | per-activity utility **count** only (no coordinates); utility material on 43; linearity on 116 | **activity-level context:** rubble yes 35, tree roots yes 17, polluted 3; **trench-empty 7**: 6 independent after the duplicate audit. Rubble is present in 5 of the 7, and in 4 of the 6 independent ones | candidate counts computed in PR #12 and PR #13; **never related to context fields** | activity-level association tests only, underpowered for utilities, adequate for rubble (§5, H8) |
| INGV (50 lines) | none | none | null-only use | null calibration and count regression only |
| TU1208 | target inventory **unverified** | — | — | **excluded**: no truth, and none is to be inferred |

### 4.2 What is missing (do not manufacture it)

1. **Real attested hard negatives in soil.** No dataset has located stones, rubble or roots. 4TU's rubble field is activity-level ("present"), not object-level.
2. **Real multi-line data over known linear utilities.** BAM is concrete, and 4TU's trench truth has no coordinates.
3. **Plastic utilities with object-level truth.** 4TU records PE, PVC or HDPE on at least 15 activities, at activity level only.
4. **Amplitude-preservation status of 4TU's SEG-Y.** This is unknown, and F2 is blocked on it.
5. **A synthetic corpus with matched designs.** In current corpora, label is confounded with radius (stones 0.03–0.08 λ; rocks 0.15–0.50 λ; cables 0.03–0.08 λ), contrast, and placement. A feature can separate classes by learning the generator's design choices.
6. **3D simulation.** It is required for F7 and F8 on synthetic data. It is the expensive step (GPU), and it is **not** proposed for V1.

**Synthetic negatives never enter real-world metrics** (`docs/ground-truth-benchmarks.md` §12). That rule stands.

### 4.3 Exposure ledger (the leakage baseline)

- **Spent, development-only from now on:** corpus_s0 (all splits), corpus_s1_v2 (dev and eval), and every BAM Rot00 scan.
- **Partly exposed:** BAM Rot90. It was used to choose K in the trace-span experiment and in the back-wall velocity calibration. No Rot90 detection score is published. Rot90 records the same specimens as Rot00 with the antenna rotated, so it is **not** independent of Rot00 for any object-identity claim. H5 uses the two polarisations jointly and is labelled exploratory for this reason.
- **Never used for any selection or score:**
  - The 4TU context fields against any detector output.
  - Any new seed of the generator.

---

## 5. The smallest scientifically defensible experiment

**Principle.** Test **discriminability**, not a detector. The candidate generator is held fixed (the V2 machinery, reused experimentally; §7). The experiment measures, per candidate, whether pre-registered physical features separate classes. It also separates **"the features cannot separate them even in principle"** from **"our extraction failed"**, using an oracle arm. No new detector architecture, no training of deep models, and no production change.

### Stage 0: diagnostics on spent data (no new data; about 4 h CPU; no gate)

- **0a. Decompose V2's 98 `clutter` false positives** (corpus_s1_v2 eval, spent, descriptive) into:
  - stone limbs beyond ±λ;
  - target late events (multiples, ringing, interior echoes), using the truth geometry;
  - layer-related events;
  - residual.

  This changes no score. It decides whether a "late-event / multiple" feature (F4) or a "stone-limb grouping" step deserves a slot in Stage 2.
- **0b. Task A re-score of V2** (descriptive): precision and FP per empty scene with stones counted as true anomalies. This is reported, not gated.
- **0c. 4TU amplitude audit.** Read the 4TU SEG-Y headers and processing notes, and trace statistics, to decide whether F2 is measurable on 4TU. The outcome is `measurable` / `not measurable` / `unknown`, with evidence.
- **0d. 4TU cross-line geometry audit.** For each activity: number of paths, header NMEA positions, inter-path spacing and angle, and position quality. The outcome is the list of activities where F8 is measurable in principle.
- **0e. BAM object footprint table.** For each object in each scan, the grid lines and samples where its response is expected, from `evidence/bam/specimen_ground_truth.csv` and the existing velocity calibration. **No radar picks.** It also records the specimen-level background reference regions used by the confound control (§6.4).

### Stage 1: real-data feasibility on BAM (held data; about 6 h CPU; pre-registered, exploratory)

Features F1, F2, F5, F6, F7 and F8 are extracted at the **known object footprints (oracle position)** and at **V2 candidates** (frozen 09dc288 parameters). The object classes are:

- **linear metal**: the 4 ducts;
- **compact dielectric**: the 4 cuboids;
- **compact grouted**: the 4 boreholes, secondary because near-surface responses overlap the direct wave;
- **linear metal, thin**: edge rebar, descriptive.

The units are **objects, not lines**: the 161 lines over one duct are one unit. This tests whether the physics shows up in real data, with the real antenna, real concrete and real noise.

### Stage 2: matched synthetic discriminability (requires review; new 2D corpus; ≤ 24 h CPU)

- **Corpus `corpus_s2_ccd`.** Seed 2, which has never been generated. Single-object scenes, so attribution is unambiguous, with classes drawn under **matched nuisance distributions**:

| Class | Material | n (dev / test) |
|---|---|---|
| metal pipe | PEC | 15 / 35 |
| metal cable | PEC | 15 / 35 |
| plastic pipe, water-filled | thin PVC shell (ε ≈ 3) + water core (ε ≈ 80, σ per soil) | 15 / 35 |
| void | air | 15 / 35 |
| stone, high-ε | ε_soil + U(1, 6) | 15 / 35 |
| stone, low-ε | ε_soil − U(1, 3), floored at 1.5 | 15 / 35 |
| empty, with a layer | — | 10 / 20 |

  That is 300 object scenes plus 30 empty-with-layer scenes, 330 in total. At corpus_s1_v2's measured ~1.9 min per scene this is about 10.5 h CPU.
- **Matching.** Every class draws radius from **one** distribution, U(0.05, 0.20) λ, depth from U(0.5, 4) λ, and frequency, soil and noise from the PR #11/#13 samplers. Any feature that separates classes must therefore do it through physics, not through generator design. The 2D limitation is stated: no F7, no F8.
- **Splits** are by sha256("ccd:2:<index>"), 30/70, and **the test split is untouched until the Stage 2 freeze is committed.**
- **Generator change.** The plastic-pipe class needs a new generator path: a shell plus core, two materials. This is a reviewed code change under `simulation/` only.

### What V1 deliberately does not do

- No 3D gprMax (deferred to PIVOT P2).
- No deep model training.
- No hyperparameter search on any test split.
- No change to `anomaly_grid_from_traces`, `find_anomaly_candidates` or any production threshold.

---

## 6. Pre-registration

These are fixed now. They may be amended only before the relevant data is touched, as in PR #13's Amendment 1.

### 6.1 Hypotheses

**Stage 1, BAM (exploratory).** Units are objects. The test is an exact one-sided Mann–Whitney. With 4 vs 4 the smallest p is 1/70 = 0.014, so "significant at 0.05" requires at most one discordant pair (U ≥ 15).

| ID | Feature | Predicted ordering | Physics basis |
|---|---|---|---|
| **H5** | F7 polarisation ratio (Rot00 / Rot90 response, normalised to the same specimen's back-wall ratio) | ducts > cuboids | linear conductor vs compact dielectric |
| **H6** | F8 along-axis continuity (number of adjacent lines carrying a consistent response, as a fraction of the object's drawn extent) | ducts > cuboids | Recorded as a **pipeline sanity check, not a discovery**: an 800 mm duct versus a 120 mm cuboid is near-tautological |
| **H7** | F1 polarity relative to the surface reflection | ducts (metal) reversed; cuboids (polystyrene, ε ≈ 1 in concrete) not reversed; prediction holds on ≥ 7 of 8 objects | sign of the impedance contrast |
| **H7b** | F6 dual-frequency ratio | ducts and cuboids differ | **descriptive only, no direction pre-registered** |

**Stage 2, synthetic (confirmatory on the fresh test split).** Units are scenes; the CI is a scene bootstrap with 2,000 resamples.

| ID | Classes | Feature | Predicted outcome |
|---|---|---|---|
| **H1** | metal vs low-ε stone | F1 polarity | AUC ≥ 0.85 |
| **H1b** | metal vs high-ε stone | F1 polarity | AUC ≤ 0.65: **predicted failure**, pre-registered to test whether the physics behaves as expected |
| **H2** | metal vs stones (both) | F2 corrected strength | AUC ≥ 0.80, CI lower bound ≥ 0.70 |
| **H3** | plastic pipe vs stones (both) | best of F3, F4, F5 (chosen on dev) | AUC ≥ 0.75 |
| **H4 (combined, Task U)** | — | fixed logistic regression (L2, C = 1, standardised) on ≤ 4 features chosen on dev, applied to V2's frozen candidates on the test split | At the operating point that keeps ≥ 90% of V2's matched utility candidates, Task U precision rises by ≥ 0.15 absolute over V2 alone |

**Real data, 4TU (association; never read as accuracy).** Units are activities, de-duplicated by `scripts/audit_benchmark_leakage.py`.

| ID | Prediction | Control |
|---|---|---|
| **H8** | V2 (A3) candidate density per 1,000 traces is higher in rubble = Yes than rubble = No activities: AUC > 0.5 with the bootstrap CI excluding 0.5. **A confirmation would show that the current candidate generator responds to coherent clutter in real ground.** | stratified by land use; partial association controlling for utility count |
| **H8b** | the same, for tree roots | (descriptive: n = 17) |
| **H9** | If F8 is measurable on ≥ 20 activities (Stage 0d), the fraction of candidates that align across paths is higher in "utility path linear = Yes" activities than in rubble-only activities | **exploratory** |

### 6.2 Arms

| Arm | Candidates | Feature extraction | Purpose |
|---|---|---|---|
| **O, oracle ceiling** | true object positions | noise-free, twin-background, true velocity (synthetic); drawing positions (BAM) | **identifiability:** can the feature separate the classes at all? |
| **R, realistic** | true object positions | primary noise condition, background estimated from the line, the detector's own v̂ | does extraction survive realistic data? |
| **D, detector** | V2 A3 detections (frozen 09dc288) | as R | does discrimination work on what the pipeline actually produces? |
| **Baselines** | as D | (i) V2 z only; (ii) depth and frequency only; (iii) shuffled labels | Does a feature add beyond detection strength and nuisance variables? |
| **SSL (exploratory)** | as D | frozen canonical SSL checkpoint embedding + the same logistic probe | Do learned features add anything? Not gated |

### 6.3 Metrics

| Scope | Metrics |
|---|---|
| Per hypothesis | AUC with scene-bootstrap (synthetic) or exact permutation (BAM) intervals |
| Task U on V2 candidates | precision at ≥ 90% retention of matched utility candidates; class-confusion matrix (utility / non-utility anomaly of interest / stone / artefact) |
| Task A | recall, precision and FP per **physically empty** scene, for context only |
| Calibration | Brier score of H4's logistic output. Descriptive: no probability is shown in any product surface from this phase |
| Cost | CPU seconds per candidate and peak memory |

### 6.4 Controls

- **Shuffled-label control.** AUC must fall within [0.40, 0.60]. If not, a leak is assumed and the hypothesis is void.
- **Nuisance-only baseline (depth, frequency, soil ε).** A feature must beat it by ≥ 0.10 AUC to be credited.
- **Detector-score baseline (V2 z).** A feature that only re-encodes detection strength is not a discriminator.
- **BAM specimen-identity control.** The same features computed on **background regions** (Stage 0e) must not separate Pk266 from Pk401 (AUC within [0.30, 0.70]). The two specimens differ in velocity (0.129 vs 0.103 m/ns at 1.5 GHz), so without this control a "duct vs cuboid" result could be a "specimen A vs specimen B" result.
- **4TU land-use stratification** for H8 and H8b, because rubble and utilities both concentrate in urban ground.

### 6.5 Leakage safeguards

1. **Features use only data and instrument metadata at inference.** No truth velocity or position, except in the labelled oracle arm.
2. **Freeze before test.** Feature definitions, the H4 feature subset and the logistic coefficients are committed (blob-hash checked, as in PR #13) **before** any `corpus_s2_ccd` test scene is simulated. Simulating the test scenes before the freeze is forbidden, not just scoring them.
3. **Spent data is used for development only.** No result on corpus_s0, corpus_s1_v2 or Rot00 BAM is reported as validation.
4. **No BAM tuning.** BAM features are computed with definitions frozen in Stage 0, before Stage 1 is run. No threshold is chosen on BAM.
5. **Grouped resampling.** Candidates from one scene or one object are never split across resamples; BAM units are objects.
6. **Duplicate audit** on 4TU before any H8 count (34 duplicate groups are known).
7. **Synthetic results are labelled SIMULATION ONLY**, and BAM results CONCRETE NDT ONLY, wherever they appear.

### 6.6 Computational limits (zero-budget plan)

| Stage | Budget | Hardware |
|---|---|---|
| Stage 0 | ≤ 4 h CPU | local Docker, 6 CPU |
| Stage 1 | ≤ 6 h CPU; peak ≤ 4 GB. BAM volumes are about 401 × 161 × 512 per scan, read per line | local |
| Stage 2 simulation | ≤ 24 h CPU 2D gprMax, **only after review** | local |
| Stage 2 analysis | ≤ 4 h CPU | local |
| Feature extraction | ≤ 2 s per candidate (median), measured | — |

No GPU, no cloud, and no 3D gprMax in V1. An overrun of more than 1.5× on any budget stops the stage for review.

---

## 7. Do not repeat; do reuse

### 7.1 Do not repeat

- Threshold sweeps on the ring statistic, the widened ring, the trace-span filter and the multi-scale estimator as clutter fixes. All of them have measured negative results.
- **A wider suppression radius or more aggressive grouping** as a precision fix. Grouping removed 8% of detections, and the residual FPs are not duplicates.
- **A fixed z threshold across corpora.** PR #13 §11.4 showed a ~30× difference in the null rate per line.
- **Detector-level gates that count real anomalies as false positives** (§3).
- **Re-using spent splits as validation**, and tuning anything on BAM.
- **10-draw permutation p-values.** Use 99 draws or none.
- **An end-to-end deep detector** on current labels: 8 embedded real objects in concrete, plus 0 object-located utilities in soil.

### 7.2 Reuse experimentally (no promotion implied)

| Component | Reused as |
|---|---|
| **Per-line null calibration** (`benchmark/hyperbola_v2.py`) | the **candidate generator** for arm D. Its sampling-invariance (precision 0.44–0.45 across conditions) and its BAM behaviour (fewer FPs than production) make it the best available Task A front-end |
| Canonical input, fast stack, v̂ | the velocity for F2's spreading and attenuation correction and for F3's curve |
| `StackContext` support sets | F3 (curve completeness) |
| Grouping | de-duplication before feature extraction |
| FP-class scorer and `score_v2` | extended in Stage 0a with `stone_limb` and `target_late_event` classes |
| 99-draw null harness and FREEZE_BLOB check | 4TU H8 and the Stage 2 freeze |
| `generator_v2` (stones, layers, clutter-preserving twin) | the base for `corpus_s2_ccd`, plus a plastic-pipe path |
| SSL canonical checkpoint | the exploratory F10 arm only |

---

## 8. Method class: physics, conventional ML, SSL or hybrid?

**Physics-based features with a low-capacity conventional classifier are justified. Deep or end-to-end learning is not justified at this point.**

| Option | Evidence for | Evidence against | Verdict |
|---|---|---|---|
| **Physics features + rule or logistic** | Every discriminator in §2 has a stated mechanism and a predicted failure. It is interpretable as product evidence (§10). It is trainable on 15 dev scenes per class | It caps out at what the features capture | **Primary** |
| Gradient-boosted trees on the same features | handles interactions | about 100 dev scenes; overfits silently | Allowed only as a dev-only sensitivity check |
| SSL embedding + linear probe | Beats baselines on reconstruction at unseen sites | The BAM target probe is below chance on rank; the embedding is not tied to any physical quantity | **Exploratory arm**, not gated |
| Supervised deep (CNN/U-Net) on synthetic | It can learn F1–F5 jointly | The 2D synthetic data lacks the decisive features (F7, F8); a sim-to-real gap has been measured (§11.4 of PR #13: a 30× difference in null rate); 0 real object labels in soil to adapt to | **Not justified** until 3D simulation plus real multi-line labels exist |
| Hybrid (physics features + SSL features) | could add context | doubles the comparison count for one small test set | Only if F10 beats the physics-only H4 on dev by ≥ 0.05 AUC |

A deep model would have to learn F7 and F8 from data that does not contain them, and be validated on real objects that do not exist in soil. That is not a modelling choice; it is an evidence gap.

---

## 9. Decision criteria

Applied after Stages 1 and 2, in this order.

### 9.1 STOP: evidence that single-line GPR cannot separate a class pair

For a class pair, **if the oracle arm (O) gives an AUC below 0.70 for every pre-registered in-plane feature (F1–F5) and for the H4 combination**, then single-line, single-polarisation GPR at the simulated frequencies cannot separate that pair even with perfect detection, background and velocity. The predicted case is **plastic pipe vs low-ε stone at matched size**. This is recorded as an **identifiability limit**:

- the product must label such candidates **"anomaly: type not determinable from this survey"**;
- no further single-line method is attempted for that pair.

A STOP on all pairs ends in-plane discrimination work. It does **not** end anomaly detection (Task A).

### 9.2 CONTINUE: to CCD-V2, a discrimination stage behind the V2 front-end, still experimental

All four must hold:

- H2 or H3 passes on the fresh synthetic test;
- **and** H4 passes (Task U precision +0.15 at 90% retention);
- **and** at least one of H5 or H7 is significant on BAM with the specimen-identity control passing;
- **and** the shuffled-label control is clean everywhere.

CCD-V2 would then be pre-registered with real-data gates. It still could not be promoted without real soil validation (§9.4).

### 9.3 PIVOT: decided by where the signal is

| Outcome | Pivot |
|---|---|
| **P1.** In-plane features fail (STOP on the key pairs) but BAM shows F7/F8 separating linear from compact (H5 significant) | Discrimination is a **multi-line / polarisation** problem. Move to M2's 3D track: build F8 on registered multi-line grids, and plan 3D simulation (Kaggle GPU, a separate review) for linear-vs-compact with stones |
| **P2.** Oracle features pass but arms R and D fail (extraction or detection is the bottleneck) | Work on the front-end: background, velocity and the Task A detector, not discrimination |
| **P3.** H8 confirms that candidate density tracks rubble on 4TU, **and** nothing in Stages 1–2 separates stones from utilities with real-data support | **Prioritise data acquisition** (§11) over any further method work |
| **P4.** Physics features work on synthetic data but F2 is unmeasurable on real data (Stage 0c) | Amplitude-preserving acquisition becomes a stated requirement for the hardware and FileDrop track (Phase 2/3 DeviceProfile: record gain and processing) |

### 9.4 What would establish that GPR alone cannot reliably separate certain targets from clutter

Three independent lines of evidence. Only (a) is attainable with current data:

- **(a) The oracle identifiability limit** (§9.1) on matched synthetic designs. This is necessary but not sufficient: 2D lacks F7 and F8.
- **(b) A 3D synthetic limit**: F7 + F8 at the oracle fail to separate compact utilities (short crossings, chambers) from stones. This needs 3D simulation, so it is not V1.
- **(c) A real-data limit**: on a registered multi-line survey with attested utilities and attested stones/rubble, the best frozen feature set fails at the pre-registered AUC. This needs new data.

Only (a) + (b) + (c) together would support the statement "GPR alone cannot separate X from Y". Until then, the product must say **"not determined"**, not **"not determinable"**.

---

## 10. How this serves the MVP and the 3D roadmap

- **MVP (Phase 6 candidate detection).** The roadmap's own candidate card lists *geometry, signal evidence, spatial coherence, cross-line consistency*, and "confidence: not a single score". F1, F2, F7 and F8 are **exactly those evidence dimensions, made physical and measured**. Even with no classifier promoted, each candidate can carry evidence chips with their own measurability states, for example "reflection polarity consistent with metal or high-permittivity material", "continuous across 4 adjacent lines" or "polarisation not measured on this survey". This is shippable, honest product value from a negative or partial result. It builds on the existing `CANDIDATE_SCORE_MEANING` and `CLASSIFICATION_STATUS = BLOCKED` rules, which stay.
- **Task A vs Task U** gives the product its vocabulary: "anomaly" (Task A), "consistent with a utility" (Task U, evidence-based), and "non-utility anomaly of interest" (voids, foundations). Phase 8's object hypotheses become reachable without mislabelling rocks.
- **3D reconstruction (M2/M3, Phases 9–10).** F8 *is* the bridge from candidates to 3D objects: a utility in a volume is a chain of line-candidates linked by consistent apex, time and velocity. Building F8 on BAM's grid (Stage 1) is the first piece of the multi-line linking that M2's grid-to-volume builder needs, and its coverage/evidence channel is the honest-3D principle applied to objects.
- **Acquisition requirements (Phases 2–4, 11).** The result tells the hardware track what to record: polarisation, dual frequency, amplitude-preserving export with gain logged, and registered line spacing. That is a concrete DeviceProfile and AcquisitionSession specification derived from evidence, not from guesses.

---

## 11. Data acquisition that would change the answer (zero-cost routes first)

Ranked by information per effort:

1. **Ask the 4TU publisher** (University of Twente) whether object-level trench logs exist, including **rubble or stone observations** and **utility positions** within each trench, under confidentiality if needed. This costs an email. **No request has been sent**; drafting one is an owner decision.
2. **A university partnership survey** (Part C′): a registered multi-line grid at ≤ λ/4 spacing over a pit with **known utilities (metal and plastic) and placed stones and rubble**, at two polarisations where the instrument allows. One afternoon would yield more Task U truth than every held dataset combined.
3. **RUP-FS (Gustave Eiffel).** This is a 3D grid with a declared CRS but **no buried objects**, so it is a texture and clutter-density source for F9 only. Its value to this phase is low.
4. **3D gprMax on free GPU** (Kaggle). This is only after V1 and as PIVOT P1, to test F7 and F8 with stones versus short utilities under matched designs.

---

## 12. Deliverables, if approved

- **Stage 0.** A diagnostics note (`docs/ccd-v1-stage0.md`) and JSON outputs, with the 4TU amplitude and geometry audits recorded as measurability states.
- **Stage 1.** Frozen feature definitions committed **before** extraction, then the BAM feature table (objects × features × scans) and the H5–H7 results with the specimen control.
- **Stage 2.** A **separate approval** for the generator change and the ~10.5 h corpus build. Then the dev freeze, the test, the H1–H4 results and the oracle limits.
- **Report.** A verdict of STOP / CONTINUE / PIVOT per §9, on a draft PR that is not merged.

Production code, PRs #12 and #13, and every published number stay unchanged throughout.

---

## 13. Recommendation

**Proceed, narrowed. Run Stages 0 and 1 now. Hold Stage 2 for review. In parallel, start acquiring real hard-negative data, because that, not the method, is the binding constraint.**

1. **Stage 0 and Stage 1 cost nothing.** They are about 10 h of local CPU on held data with no simulation, and they answer three questions no previous phase asked:
   - What actually are V2's unexplained false positives?
   - Do the physically decisive features (polarisation, continuity, polarity) show up in real radar data at all?
   - Does Subterra's candidate density track attested rubble in real ground?

   Each answer is useful whatever its sign.
2. **Stage 2 (a matched synthetic corpus) is worth running only if Stage 0 does not already show the in-plane route to be hopeless**, for example if V2's unexplained FPs turn out to be dominated by artefacts that no object feature addresses. It is also only in-plane: by construction it cannot test the strongest discriminators.
3. **Do not build a new detector architecture.** Four detector phases have shown that the candidate front-end is now adequate for Task A on real concrete (V2 beats production on BAM). What is missing is **information**: multi-line geometry, polarisation and attested negatives. No architecture supplies that.
4. **Prioritise data.** The single highest-value action for this question is a registered multi-line survey over known utilities **and** known stones or rubble (§11, item 2). The second is the 4TU object-log request (§11, item 1). Both need owner decisions, not code. Without them, the honest ceiling for Subterra's product claim stays at **"anomaly, with physical evidence dimensions; type not determined"**, and that is worth shipping as is.
