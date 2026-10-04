# Blocked issues: independent re-investigation and resolution

**Date:** 2026-10-04 · **Branch:** `research/blocked-issues-resolution` (from `main` @ `9b961e6`) ·
**Not merged into main.**

Labels used throughout: **Verified** (read from a file or computed reproducibly here),
**Inferred** (reasoned, not proven), **Unresolved**.

---

## 1. Executive summary

Previous conclusions were treated as hypotheses. Most of the blockers survive re-testing,
and they survive for the reasons previously given. The useful results of this session are a
sharper characterisation of one Yesan blocker and **seven code defects**. In each defect an
uncertain quantity was presented as stronger than it is, or a hidden fallback produced a
confident-looking number:

| # | Defect | Effect before the fix |
|---|---|---|
| 1 | Method C returned `derived` on drift, baseline steps, slow "wows" and arrivals inside its quiet window | a confident time zero on lines with no direct wave |
| 2 | A non-default velocity with no recorded basis was labelled `user_declared` | an unattributed number passed the scientific depth gate |
| 3 | Candidate depth said "declared velocity" for the 0.1 m/ns platform default; mixed velocities read as "none"; time origin never stated | provenance relabelled at the interpretation layer |
| 4 | SEG-Y coordinate decoding errors became `(0.0, 0.0)` | a confident position off the coast of Africa |
| 5 | 4TU float32 NMEA storage quantises latitude to **0.904 m**, recorded nowhere | absolute horizontal precision overstated |
| 6 | MALA unreadable `START POSITION` became 0.0 silently; wheel spacing labelled "MEASURED", `verified=True` | an unknown shift; a preset calibration presented as a measurement |
| 7 | A candidate review's Grade C / operator-reviewed status was a default, not enforced | an edited or reloaded review could enter the training corpus as Grade A (circular validation) |

All seven are fixed and tested, and every fix is in the conservative direction: refuse, or
downgrade the stated provenance. **No stored depth, position or detection value changes**,
except that Method C may now refuse a line where it used to return a time zero.

**Yesan.** The authors' trace interval is exactly **27/3116 m**, an effective wheel
calibration of **3116/9 pulses/m**. The match holds to 4 × 10⁻¹³, with a chance probability
≤ 2.2 × 10⁻⁶. So the 2.8% discrepancy is a deliberate field re-calibration against a whole
number of metres; it isn't rounding, an offset, slope, projection, resampling or a parser
error. That settles the *mechanism*. It doesn't settle *which scale a target list would use*,
and there is still **no target list**. **Yesan cannot legitimately be used for quantitative
detector or localisation evaluation.**

**Depth model.** It's safe as a **display/preview** model, because it now refuses or
downgrades every case tested here. It is **not** production-safe as a *measurement*: no
independent time-zero reference exists, Method C is experimental, and the new validity
checks haven't yet been re-scored on the held corpus.

**False blockers: none found.** The DRC blocker (datasets 7 and 13 not public) could not be
re-verified from this environment, which blocks Zenodo, MDPI and de-mine.com, but nothing
found contradicts it.

## 2. Issues investigated

A Yesan registration; B time zero and depth; C DRC registration; D 4TU vertical and absolute
reference; E candidate generation and interpretation. Section 9 of the brief (propagated
assumptions) was applied across all five.

**Repository audit (Verified).** Branches on the remote are:

- the phase7 slices;
- `feat/*`, `fix/*`;
- `research/validate-timezero-method-c`;
- `research/yesan-ground-truth-registration` and `research/drc-seeded-field-benchmark`, both
  merged into `main` at `9b961e6` during this session.

The working branch was fast-forwarded onto that `main`. No research branch was merged by this
work, and `main` was not modified.

## 3. Evidence discovered

### A. Yesan

- **Sources examined.** Manifest, `docs/yesan-registration-investigation.md` (header table,
  sheet values, image-apex analysis), and the MALA converter.
- **Zenodo record.** Unreachable from this environment (egress policy). Web search surfaced
  the record's abstract only: 90 m site, 250/500/800 MHz, "documented buried targets", an
  accompanying MDPI *Sensors* paper. That paper is still not findable.
- **Exact rational calibration (new, Verified).**
  - `3 / 0.0086649550706 = 346.2222222224 ≈ 3116/9`, relative error 4 × 10⁻¹³.
  - Equivalently `dx = 27/3116 m`: 3116 traces over 27 m, 3116 pulses over 9 m, or 31,160
    pulses over 90 m (the site length).
  - The header's own value is `3 / 355.9`.
- **Converter finding (Verified).** The MALA converter recorded the header interval as
  "MEASURED", `verified=True`, without naming the wheel calibration it depends on. Fixed
  (defect 6).

### B. Time zero and depth

- **Model inventory.** The depth model (`schemas/depth_model.py`) already separates:
  - the recording delay;
  - time zero (`TimeZeroStatus`: declared / measured / derived / inconclusive / …);
  - velocity (`VelocityBasis`);
  - the depth reference;
  - `DepthStatus` (unavailable / approximate / resolved);
  - a separate `scientifically_sufficient` gate.

  That is a better structure than a single MEASURED/DECLARED/… scale, because it keeps time
  zero, velocity and reference apart. It is kept and extended rather than replaced
  (section 7).
- **Method A** reports the SEG-Y delay and never applies it. **Correct.**
- **Method B** packages a declaration. **Correct.**
- **Method C** has the documented false-`derived` modes 2 and 3. Reproduced synthetically in
  this session: the unchecked picker returns a spread under 2 ns on monotone drift, on
  baseline steps and on slow wows. Fixed with refusal-only checks (defect 1).
- **Hidden upgrade.** Unattributed velocity was promoted to `user_declared` in two places:
  `velocity_model_of` and the legacy `record_ingest` path (defect 2).
- **Invalid stored velocity.** `VelocityModel` refuses ≤ 0, > 0.30 m/ns and non-finite
  values. Readiness then reports the depth as unavailable. **Correct as found.**

### C. DRC

- **Repository state.** Two manifests (`drc-field1`, `drc-field2`), the attested-empty
  schema, and `docs/drc-seeded-field-registration.md` (merged today).
- **Datasets 7 and 13.** The prior finding is that the GSSI cart and Cobra UAV data are not
  in Zenodo 19100554 and not on the web map. Re-verification was attempted via Zenodo,
  de-mine.com and web search.
  - Zenodo and de-mine.com are **blocked by this environment's network policy**.
  - Search finds only the paper (Baur et al. 2026, *Remote Sensing* 18:2182), the Zenodo
    records 19100554 and 15324498, and the JMU article. No alternative host for the GPR
    files was found.
- **Grid registration.** The grid-ID → XY mapping is verified per field from DRC
  coordinates. XY → GPR trajectory needs the GPR files.

### D. 4TU

- **Elevation fields.**
  - Author-stated: WGS84 ellipsoidal.
  - Identified by measurement against AHN: bytes 45–48 are ellipsoidal; bytes 41–44 are
    NAP-like (sub-metre against AHN).
  - Per-site separation 43.2–44.3 m. This matches the magnitude and gradient of the Dutch
    geoid separation. Consistent, and independently checked here only for range.
- **Horizontal coordinates.** Per-trace NMEA `ddmm.mmmm` stored in float32, which the
  converter frames as EPSG:4326, `inferred`.
  - **New, Verified:** float32 spacing near 5126–5327 minutes is 2⁻¹¹ minute, so the
    latitude quantum is **0.904 m** at every 4TU site. The longitude quantum is
    0.035–0.069 m.
  - This floor comes from the storage format, so no processing can recover it. GNSS accuracy
    and RTK status remain undocumented.
- **Ground and antenna height.** The GNSS antenna height was "accounted for during
  acquisition" (author). No time-zero or air-gap correction was applied. Depth zero is
  therefore not the ground (author). The −0.83 m bytes 41–44 − AHN offset is unexplained.

### E. Candidates

- **Structure.** Generation (`interpretation/anomaly_candidates.py`), presentation and
  review (`candidate_intelligence.py`, `schemas/review.py`), truth (`benchmark/targets.py`,
  `independent_of_gpr` enforced) and scoring (`benchmark/target_scoring.py`, gated) are
  separate modules. Classification is structurally `BLOCKED`.
- **Measured performance.** Recorded honestly as approximately chance (BAM 1.04–1.13×;
  4TU AUC CI spans 0.5).
- **Defects found.** Defect 3 (candidate depth basis) and defect 7 (review grade not
  enforced).

## 4. Experiments performed

1. **Yesan scale hypotheses.** `python -m scripts.yesan_scale_hypotheses [--json OUT]`.
   Data-free and deterministic; ten hypotheses, verdicts in section 5.
2. **Quiet-window contamination rule (simulation).** Per-trace false-flag rate on Gaussian
   noise and detection rate on a 500 MHz Ricker arrival starting inside the 8-sample window
   (Δt 0.143 ns), for k = 5, 8, 10, 15, 20:

   | k | Noise-only traces flagged | Inside-window arrivals detected |
   |---|---|---|
   | 5 | 8.4% | 100% |
   | **8** | **2.4%** | **77%** |
   | 10 | 1.3% | 58% |

   **k = 8 was chosen.** A line is refused only when most of its traces fail, so on clean
   lines whole-line false refusal is negligible.
3. **Mutation test.** With the checks removed, 8 of the 14 validity tests fail; the old code
   gives a false `derived` in each.
4. **Float32 NMEA quantum** at Dutch latitudes and longitudes:
   `numpy.spacing(float32(v)) × 1852 m` per arc-minute (× cos φ for longitude).
5. **Regression comparison.** The suites below were run on `main` (temporary git worktree)
   and on this branch, and the failure sets compared. They are **identical** (all need raw
   archives absent from this environment).

## 5. Equations and calculations

- **Depth:** `depth = (t_raw − t0) · v / 2`, unchanged.
- **Yesan scale:**
  - observed ratio = `0.0086649550706 / 0.008429 = 1.027993`;
  - header: `0.008429 = 3/355.9` (= 0.0084293, printed to 6 decimals; rounding ≤ ±0.006%);
  - authors: `3/dx = 346.2222222224 = 3116/9` (error 4 × 10⁻¹³).
- **Chance of the rational match.** The number of fractions with denominator ≤ 9 in a
  20 pulses/m window is `20 · Σφ(d)`. Each has a ± window equal to the sheet's printed
  precision (5.8 × 10⁻¹² relative). Probability ≤ **2.2 × 10⁻⁶**.
- **Slope hypothesis:** grade = `√(r² − 1)` = 23.9% (13.4°), with the wrong sign: the wheel
  would be the longer measure. Rejected.
- **Projection hypothesis:** point scale error < 0.1% vs 2.8%; wheel distances are never
  projected. Rejected.
- **Yesan hypothesis verdicts:**

  | Hypothesis | Verdict |
  |---|---|
  | H1 header rounding | REJECT |
  | H2 field re-calibration | **ACCEPT** (mechanism); which distance UNRESOLVED |
  | H3 constant offset | REJECT (the authors' formula is multiplicative) |
  | H4 slope | REJECT |
  | H5 projection | REJECT |
  | H6 resampling / cropping / stacking | REJECT (STACKS 1; counts match) |
  | H7 reversal | REJECT (scale-preserving) |
  | H8 parser error | REJECT |
  | H9 separate figure scale | REJECT (images use dx) |
  | H10 sheet scale is physically correct | UNRESOLVED |

- **Method C transience test.** For onset `o`, first-lobe peak `p`, rise `r = max(p − o, 1)`,
  the trace must satisfy `sign·d[j] ≤ 0.5·peak` for some `j ∈ (p, o + 6r + 3]`, and
  `r ≤ 0.1·N`.
- **4TU quantum:** `Δ = spacing_float32(ddmm.mmmm) [arc-min] × 1852 m`.
  - latitude at 51–53° N: 2⁻¹¹ × 1852 = **0.904 m**;
  - longitude 3–7° E: 2⁻¹⁵ to 2⁻¹⁴ arc-min × 1852 × cos φ = **0.035–0.069 m**.

## 6. Files and source references

- **Code:** `preprocessing/time_zero.py`, `schemas/time_zero.py`, `schemas/depth_model.py`,
  `api/spatial.py`, `converters/mala_converter.py`, `converters/segy_converter.py`,
  `converters/segy_endian.py`, `interpretation/anomaly_candidates.py`,
  `interpretation/candidate_intelligence.py`, `schemas/review.py`
- **Research:** `scripts/yesan_scale_hypotheses.py`;
  `benchmark/manifests/yesan-fullscale.targets.json` (`yesan-distance-scale` statement)
- **Docs:** this file; `docs/timezero-method-c-validation.md` §6
- **Prior evidence relied on:** `docs/yesan-registration-investigation.md`,
  `docs/drc-seeded-field-registration.md`, `docs/4tu-vertical-datum.md`,
  `docs/4tu-elevation-field-identification.md`, `docs/4tu-author-evidence.md`,
  `docs/candidate-intelligence.md`
- **External:**
  - Zenodo 10.5281/zenodo.21441974 (Yesan)
  - Zenodo 10.5281/zenodo.19100554 (DRC)
  - Baur et al. 2026, doi:10.3390/rs18132182

  All identified via web search only; the hosts are blocked here.

## 7. Code changes

| Commit | Change |
|---|---|
| `a953f93` | Method C validity checks (quiet-window contamination; non-transient / slow-rise onset), refusal-only, with `pick_rejections` diagnostics |
| `5029808` | `VelocityBasis.UNDOCUMENTED` for an unattributed non-default velocity: depth stays approximate, gate refuses it, declarations cannot use it |
| `6ab8643` | MALA: unreadable or non-finite `START POSITION` refuses the axis; absent start → 0 m, stated; wheel spacing is `declared by the instrument header`, names `WHEEL CALIBRATION`, `verified=False` |
| `2a9521d` | Yesan scale-hypothesis script, tests, manifest statement (still blocking) |
| `02276ae` | SEG-Y: no `(0,0)` fallback; frame assumption `horizontal_coordinate_quantisation_m` under `ieee_nmea`; corrected "constant 43.948 m" wording |
| `c9736b0` | Candidates carry `velocity_source`, `velocity_inconsistent`, `time_zero_applied`; `depth_of` names the velocity's real provenance and the time origin |
| `61ea847` | `CandidateReview` refuses any evidence grade except C and any label source except operator-reviewed, on construction and on reload |

**Resulting provenance model:**

- **time zero:** `declared | measured | derived | inconclusive | unavailable | failed | not_run`, with per-trace refusal reasons;
- **velocity:** `independent_measurement | literature | user_declared | estimated_from_same_survey | assumed_default | undocumented`;
- **depth:** `unavailable | approximate | resolved`, plus a separate `scientifically_sufficient` gate (true only with declared/measured t0, a stated non-estimated velocity, and a known reference);
- **candidate depth:** `derived | unavailable`, never measured.

## 8. Test results

- **New and updated tests:**
  - `tests/test_time_zero_validity.py` (14)
  - `tests/test_yesan_scale_hypotheses.py` (4)
  - `tests/test_depth_model.py` (+3)
  - `tests/test_mala_converter.py` (+3)
  - `tests/test_segy_little_endian.py` (+3)
  - `tests/test_candidate_intelligence.py` (+9)
  - `tests/test_reviews.py` (+4)

  All pass.
- **Regression, affected areas** (65 files: depth, time zero, spatial, ingest, fusion,
  viewer, export, provenance, converters, candidates, reviews, benchmark): **1,522 passed**,
  90 skipped, 3 failed, 15 errors. All 18 are `test_tu1208_*`, which need the TU1208 archive
  absent here.
- **SEG-Y / 4TU set** (72 files) and **candidate / anomaly set** (44 files): the failure sets
  are **identical to `main`**, verified in a worktree. All need absent archives (TU1208,
  4TU `Metadata.csv`, the SSL and BAM corpora).
- **Skipped tests** are the held-data tests: `datasets/` is not in this environment.
- **Not run here:** the full suite in one invocation (blocked by the session's permission
  classifier) and the frontend suite (no frontend change).

## 9. Scientific limitations

- The Method C checks were developed on synthetic data only, and the operator-reference
  corpus has **not** been re-scored with them. A slow oscillating drift remains
  indistinguishable from a genuinely low-frequency direct wave (header frequency is
  unreliable: every Yesan file says 500 MHz).
- The 0.1 rise-fraction and 0.5 fall-back thresholds are physically motivated heuristics,
  not fitted values.
- The Yesan rational-calibration result proves *how* dx was computed. It doesn't prove the
  measured distance was correct, or which scale any target chainage uses.
- The 4TU quantum is a lower bound on horizontal error; GNSS accuracy is undocumented.
- No external source could be re-read from this environment: Zenodo, MDPI, DataCite,
  EuropePMC and de-mine.com are blocked.

## 10. Status table

| Issue | Previous status | New status | Evidence | Code changed? | Remaining uncertainty |
|---|---|---|---|---|---|
| Yesan: target list | blocked | **EXTERNAL DEPENDENCY** | no list in held files, record or findable paper | no | everything that needs targets |
| Yesan: 2.8% scale | unexplained re-calibration | **PARTIALLY SOLVED** | dx = 27/3116 m exactly; p ≤ 2.2 × 10⁻⁶; 9 other hypotheses rejected | script, manifest text | which distance; which scale targets use |
| Yesan: 0 m origin, direction | unresolved | **EXTERNAL DEPENDENCY** | per-file mark trace; direction inferred only | no | physical mark; bridge end |
| Yesan: scoring legitimacy | not scoring-ready | **unchanged, gated by test** | readiness test pins refusal | test | — |
| Method C false `derived` | experimental, known failure modes | **PARTIALLY SOLVED** | mutation-tested refusals for modes 2 and 3 | yes | corpus re-score owed; oscillating drift |
| Velocity provenance upgrade | not identified | **SOLVED** | two code paths fixed, tests | yes | — |
| Independent time-zero reference | none | **EXTERNAL DEPENDENCY** | none in holdings | no | needs a documented reference |
| MALA start-position fallback and spacing provenance | not identified | **SOLVED** | tests | yes | GSSI/IDS spacing still labelled MEASURED (design decision, §12) |
| DRC: grid registration | verified per field | **unchanged (SOLVED previously)** | prior work | no | coordinate survey method |
| DRC: GPR data 7/13 | not public | **EXTERNAL DEPENDENCY** (not re-verifiable here) | search finds no host | no | data, trajectories, licence |
| 4TU vertical datum | declared (author) | **unchanged; consistency confirmed** | 43.2–44.3 m = NL geoid range | wording fix | −0.83 m offset; bytes 41–44 never confirmed NAP |
| 4TU absolute horizontal | partial | **PARTIALLY SOLVED** (now quantified) | 0.904 m float32 quantum | yes | GNSS accuracy |
| 4TU depth origin | blocked | **EXTERNAL DEPENDENCY** | author: no t0 / air-gap correction | no | t0 magnitude, velocity |
| SEG-Y (0,0) fallback | not identified | **SOLVED** | test | yes | — |
| Candidate depth basis | not identified | **SOLVED** | tests incl. real generator | yes | — |
| Review grade circularity | documented, not enforced | **SOLVED** | tests incl. reload | yes | — |
| Detector accuracy | ~chance | **unchanged** | no independent labels added | no | needs independent truth |

## 11. Exact external information required

- **Yesan** (Dr Chang-Geun Oh, coh@hanseo.ac.kr; draft in the Yesan doc §11, plus one new
  question):
  - the target table (class, material, dimensions, burial depth top or centre, reference
    surface, line, chainage, how positioned);
  - the physical 0 m mark;
  - which scale chainages use;
  - **the distance over which dx = 27/3116 m was calibrated, and how it was measured;**
  - direction, and which end is the bridge;
  - antenna labels;
  - whether the list is exhaustive.
- **DRC** (jbaur@de-mine.org):
  - raw GPR for datasets 7 (GSSI 400 MHz cart) and 13 (Cobra UAV), with trajectories,
    settings and licence;
  - item-coordinate survey method and tolerance;
  - depth to top or centre;
  - "Empty" cells;
  - GCP markers.
- **4TU:**
  - a documented time-zero or air-gap reference, or system-delay measurement;
  - an independent velocity (CMP/WARR, borehole, or trench depth with coordinates);
  - GNSS receiver accuracy and RTK status;
  - confirmation that bytes 41–44 are NAP.
- **Time zero generally:** a documented first-break reference (e.g. Falerii processed
  profiles) or a second independent operator.

## 12. Recommended next steps

1. **Highest value: send the Yesan author letter**, with the added calibration question. One
   answer unlocks Yesan matching, recall and localisation, if the list exists and is
   registered.
2. On a machine holding the raw data, run `python -m scripts.validate_timezero_method_c`
   once, unchanged, and record which references change status under the new checks.
3. Decide whether GSSI (`rhf_spm`) and IDS wheel spacing should also become "declared by the
   instrument header" (`verified=False`). Today `verified=True` records header
   self-consistency, not a checked distance, and `tests/test_ids_dt_converter.py` pins that
   choice.
4. Send the DRC data request; ingest datasets 7/13 only through a supported reader (Cobra
   has none).
5. Allow `zenodo.org`, `www.mdpi.com` and `de-mine.com` in this environment's network
   settings so public sources can be re-verified from the cloud session.
