# Post-PR #17 research pivot: acquisition and validation strategy (brief)

**Status:** BRIEF FOR APPROVAL. Nothing in it has been implemented.
- No detector was built and no simulation was run.
- No hardware was bought and no production code was changed.
- No correspondence was sent.

**Context:**
- **Date:** 2026-10-17.
- **Branch:** `research/post-pr17-acquisition-strategy`, stacked on PR #17.
- **Budget:** zero (see the 2026-10-12 decision recorded in `docs/roadmap-to-completion-draft.md`, Part C′). Every route below is costed against that. Paid options are named only so they can be ruled in or out, and **no price is quoted that was not verified**.

**Accepted as final:**
- **PR #17 STOP.** Arms B, C and D will not be retried on BAM, and their gates will not be relaxed.
- **PRs #12–#17** stay drafts and stay unmerged.

**Evidence labels used throughout:**

| Label | Meaning |
|---|---|
| **[V]** | verified this pass against a primary source (a repository API, the archive's own file listing, or the paper's own text) |
| **[R]** | established in an earlier repository audit (cited) |
| **[S]** | a speculative lead: plausible but unconfirmed |
| **[K]** | general domain knowledge, not checked against a source this pass; it must be checked before it is relied on |

---

## 0. Why the pivot, in five lines

1. Three successive front-end experiments on BAM all stalled: V2 (PR #13), linearity (PR #15), and arms B and C (PR #17).
2. In every case the limit was **data**, not tuning:
   - one site;
   - 4 ducts and 4 cuboids;
   - single-channel lines;
   - concrete, not soil;
   - all of it already exposed during development.
3. **Frequency and antenna orientation moved recall more than any processing arm** (Phase 1, PR #17 §5.4). Those are **acquisition** choices.
4. Every BAM number is exploratory, so no further BAM result can promote anything.
5. The binding constraint is therefore **independent, object-level, real-world truth on more than one site**. The strategy below is built around getting it.

---

## 1. Controlled survey specification (the smallest useful survey)

**Purpose.** Produce the first dataset on which a Task A result (anomaly detection) could be **promoted**, not merely observed. "Smallest" is set by the statistics in §6.4, not by convenience.

### 1.1 Sites

- **At least 2 sites**, with different soils (for example sand or gravel at one, a loam or clay-bearing soil at the other). One is for development and one for testing. **A third site is strongly preferred**, so that one site can be held back untouched.
- Each site has a **scored area of at least 8 m × 10 m**, plus a 1 m margin surveyed but not scored. The margin keeps edge effects and the turning of the cart outside the score.
- Each site needs a surface that is accessible and flat enough to survey at under 2 cm of positioning error: grass, compacted gravel, or paving.

### 1.2 Targets per site (all independently known)

| Class | Count per site | Specification | Why |
|---|---|---|---|
| Metallic pipe | 2 | steel or ductile iron, Ø 50–150 mm, ≥ 4 m long, crossing the area | strong GPR return; a direct test case for EM locators |
| Plastic pipe, no tracer | 2 | PE or PVC, Ø 50–160 mm, one water-filled and one air-filled | the hard case: GPR is the only routine sensor that sees it [K] |
| Plastic pipe with tracer wire | 1 | as above, with tracer | lets an EM locator be scored on a non-metallic utility |
| Cable or duct | 2 | one cable (unpowered), one empty duct, Ø ≥ 25 mm | the thin linear class |
| Stone or rubble | 4 | 2 single stones (15–30 cm), 2 rubble clusters (≈ 0.5 m) | the compact clutter class that CCD-V1 could not separate from utilities |
| Void analogue | 1 | sealed air-filled container, ≈ 30 × 30 × 20 cm | the cavity class (Pk401's only real-world analogue) |
| **Verified-empty cells** | **≥ 4 cells of ≥ 1 m² each** | excavated to at least 1.5 m and backfilled with the native soil, documented and photographed | Task A false-alarm budget (§6.5). Without these, "empty" cannot be claimed (brief rule) |
| Calibration reflector | 1 | metal plate ≥ 0.3 × 0.3 m at a measured depth, **outside the scored area** | velocity and time-zero check; **never scored** |

**Depths and orientation.**
- Target tops at **0.3–1.5 m**, spread over at least 3 depth bands.
- Linear utilities at **at least 2 orientations** relative to the survey grid (0° and about 30–45°). This prevents the "every utility runs parallel to the lines" artefact that BAM had (all 4 ducts parallel).

**Totals.**
- About **12 scored objects per site**, 24 over two sites, and **≥ 8 verified-empty m²**.
- Smaller numbers cannot meet the §6.4 stop/go rule.

### 1.3 Acquisition geometry

| Parameter | Single-channel GPR (minimum) | Array GPR (preferred) |
|---|---|---|
| Line spacing | **0.10 m** on an orthogonal grid. Both directions, so the cross-line axis is never under-sampled: "Rot00 + Rot90" as on BAM | native channel spacing (≈ 4–8 cm on commercial arrays [K]; 4.4 cm VV on IDS Stream C [V]), with passes overlapping ≥ 10% |
| In-line trace spacing | ≤ 0.02 m (encoder-triggered) | ≤ 0.02 m |
| Frequencies | **two:** ≈ 250 MHz (depth) **and** ≈ 500–700 MHz (resolution) [K], both over the same grid | the array's native band. Add a single-channel low-frequency pass if the array is above 600 MHz |
| Polarisation | both grid directions are the polarisation control | **both** polarisations where the array has them (Stream C: VV and HH channels [V]) |
| Time window / samples | ≥ 2.5 × the two-way time to 1.5 m at the slowest expected velocity; ≥ 512 samples | same |
| Stacking / gain | record **raw**: no on-board gain, filter or background removal, or else log them exactly | same |
| Repeats | **one full repeat** of one frequency on one day, to measure test–retest stability | same |

**Effort** (an estimate [K], to be confirmed with the operator): one grid of 8 × 10 m at 0.10 m in both directions is about 180 lines and about 1.6 km of profile, per frequency. That is roughly **half a day per frequency with a cart**, or about 1 hour with an array.

### 1.4 Positioning

- **Local control:** at least 3 monuments per site, surveyed by robotic total station or RTK GNSS to ≤ 2 cm, and tied to a national CRS and vertical datum (with EPSG codes recorded).
- **Per trace:** encoder distance along each line, with each line's start and end surveyed. RTK or total-station tracking of the antenna is preferred. **The antenna-to-prism or antenna-to-GNSS offset must be measured and recorded.**
- **Grid layout:** marked on the ground (string lines or paint) and surveyed. Cross-line position must never come from the GPR itself (the TU1208 / 4TU failure mode [R]).
- **Surface elevation:** a surface DEM or spot heights at ≤ 0.5 m spacing over the grid. Depths are measured from the surveyed surface.

### 1.5 Calibration (independent of the targets)

- **Time zero:**
  - an air shot or metal-plate reflection at a measured antenna height, at the start and end of each session;
  - plus the calibration plate at its measured depth.
  - The TestUM attempt at an independent air-shot procedure was INCONCLUSIVE [R], so the plate is mandatory, not optional.
- **Velocity:**
  - a CMP or WARR gather if the system is bistatic;
  - **plus** the calibration plate at its known depth;
  - **plus** soil cores or TDR moisture at ≥ 3 points per site.
  - **Hyperbola fitting on scored targets is not a calibration** and may not be used as truth.
- **Soil:**
  - texture class, gravimetric moisture and electrical conductivity at ≥ 3 points;
  - date, weather, and rainfall over the previous 72 h.

### 1.6 Ground-truth requirements

**Truth that counts for scoring (grade A):**
- Every object surveyed **at burial**, with the trench open:
  - end points, plus a point every ≤ 1 m along linear objects, by total station or RTK, at ≤ 2 cm;
  - top-of-object depth measured from the surveyed surface;
  - material, outer diameter, contents (air or water), photographs with a scale bar.
- Verified-empty cells documented the same way (excavated, photographed, backfilled).

**Existing utilities at a third-party site.** Truth needs one of:
- an as-built survey **plus** pothole or vacuum-excavation confirmation of **≥ 1 point per object** (grade B); or
- a full excavation (grade A).

Utility records alone are **grade D**: they are never scored.

**Custody:**
- The truth file is written **before any GPR file is processed**.
- It is hashed, committed, and held out of the processing environment until scoring. This is the same blob-hash freeze pattern used since PR #13.

**Exclusions:**
- No truth may be derived from the same radar, from EM locator output, or from an operator's interpretation of the data (`EvidenceGrade` C or D [R]).

### 1.7 Metadata (machine-readable, one file per session)

- **Instrument:** make, model and serial; antenna centre frequencies; polarisation; antenna separation.
- **Acquisition:** sampling interval, samples per trace, time window, trigger mode, encoder calibration, on-board processing, and the firmware or software version.
- **Positions:** CRS and EPSG codes, vertical datum, control-point coordinates, antenna offsets.
- **Conditions:** operator, date and time, weather, soil, calibration-shot file names.
- **Line log:** line ID, direction, start and end coordinates, and notes (obstacles, re-shoots).
- **Truth:** the truth-file hash; the evidence grade per object; and the verified-empty polygon list.
- **Licence:** the target is CC0 or CC BY, with an explicit commercial-use permission.

---

## 2. Existing-data opportunities

### 2.1 Not repeated: already conclusively exhausted

These were checked in earlier passes and are **not re-searched**. No new evidence was found that would reopen any of them:

`docs/external-gpr-benchmark-acquisition.md`, `docs/research/public_gpr_benchmark_hunt.md`, `docs/fallback-localisation-dataset-search.md`, `docs/research/kec_raw_gpr_data_hunt.md` and `docs/roadmap.md`. They cover:
- BAM, TU1208, 4TU, Stadler, CMU-GPR, Branco, Morocco/LCSkhalid, MERL, MCG, INGV/UNISA, De Montfort;
- AI-Hub, KEC/Yesan, DRC, RUP-FS, TestUM, BHRS, Wurtsmith, Grimsel, Hillside;
- the Guangzhou single-file data, and Sense-City and Zhejiang "described, but no public repository".

**Net result:** no open GPR dataset with raw traces, independent object truth and registered coordinates exists **outside a concrete lab** (BAM).

### 2.2 New this pass

| Candidate | What was checked | Raw amplitudes | Spatial coordinates | Object truth | Licence | Verdict |
|---|---|---|---|---|---|---|
| **Frankfurt utility test site** (DETECTINO, Goethe University Frankfurt), surveyed with **IDS Stream C** by Fraunhofer IOSB (Karle et al. 2022, ISPRS XLIII-B1, 85) | the paper's own text [V] | yes, held by the authors | the paper uses an orthophoto as reference; site truth is in Naser & Junge (2010) | **40 pipes and cables**: PE, steel, vitrified clay and concrete, at various diameters and inclinations, in 2 troughs (1.5 m and 3 m deep), with 7 subsoil materials and 3 surfaces [V] | the paper is CC BY 4.0; **no data release found** | **The strongest new lead, but not available.** It is a purpose-built, documented, multi-soil utility test bed already surveyed with a 34-channel dual-polarisation array. **Ask for it** (§3) |
| **Tindari multichannel GPR**, Zenodo 15464768 | API record [V] | ReflexW, 3D volumes, 315 MB | local | **none**: archaeological, interpreted from the GPR | CC BY 4.0 | **Reject for scoring.** Possible use as an array-format and clutter-texture sample |
| **Guangzhou University GPR dataset**, Zenodo 14637589 | central directory read again over HTTP Range this pass: 5,046 entries [V] | yes: IDS `.dt`, MALÅ `.rd3`/`.rad`, plus IDS **multi-channel project trees** (`.MIS`/`.ZON` with `ROHDATA/*.DAT`) | none | **no truth file** of any kind. This agrees with the earlier `roadmap.md` audit [R] | CC BY 4.0 | **Reject for scoring.** It confirms that IDS multi-channel project files exist in an open archive, which is a **format-readiness** test case (§5) |
| **Pulsed vs SFCW rebar**, Zenodo 10962520 | API record [V] | yes, small (3.7 MB) | lab | rebar specimens (8–32 mm) | GPL-3.0 | concrete NDT. **Out of scope** for soil utilities |
| **Risk-calibrated utility sensor fusion**, Zenodo 23375299 / 23375305 | API record [V] | **simulation only**, stated by the authors | — | synthetic | MIT / CC BY | **Reject.** It is a fusion-method reference only |
| **FHWA / VDOT NDE utility test beds** (FHWA-HRT-22-111) | search result summary only [S] | not public | — | lab test beds with PVC and metallic pipes to 6 ft; field sites with documented utilities [S] | US public report | report only. **Data access unknown**; ask (§3) |
| Vendor sample data (IDS, ImpulseRadar, Kontur) | web search | none found online [V: none found] | — | — | — | not available without contact |

**Conclusion.** Getting existing data now depends on **people, not searches**. The one high-value candidate (Frankfurt plus Stream C) exists, is documented and matches §1 closely, but it is not public. Further open-web searching has low expected yield, and **§3 outreach supersedes it.**

---

## 3. Potential partners

All outreach is drafted for the human operator to send. **Nothing is sent by the platform.** Status as of 2026-10-17:

| # | Partner | What they have | Status | What to ask |
|---|---|---|---|---|
| P1 | **Fraunhofer IOSB, Ettlingen** (Karle, Boldt, Thiele) and **Goethe University Frankfurt, Applied Geophysics** (the DETECTINO test site) | Stream C array data over the 40-object site; the site's documentation (Naser & Junge 2010) | **Confirmed to exist** [V]. **Willingness to share is unconfirmed** | (a) release of the 2020 Stream C data plus the as-built geometry under a research licence; (b) access to the site for a §1 survey with borrowed equipment |
| P2 | **Dr. ter Huurne** (University of Twente, the 4TU dataset author) | 4TU utility data; replied once before | **Confirmed correspondent** [R]. Follow-up sent 2026-08-15, **no reply yet** | after the pending questions: whether trench coordinates could be released under NDA, or whether there is a Dutch field site |
| P3 | **BAM (Grohmann, Wöstmann, Maack, Niederleithinger)** | the published concrete specimens; GPR lab | **Confirmed authors of open data** [R]. Never contacted | whether a soil sandbox or utility test field exists at BAM; and the 1.5/2.6 GHz calibrations for the other rotations |
| P4 | **Université Gustave Eiffel, Sense-City** (Paris-Est) | 250 m² urban test bed with a pipe zone, targets at 14.5–64.5 cm, surveyed with 3 GPR systems (300 MHz–1.5 GHz) [V: EGU 2016 abstract] | **Facility confirmed**; no public data [R] | the radargrams plus the pipe-zone as-built, or a visit |
| P5 | **University of Birmingham, NBIF / Mapping the Underworld** (Metje, Rogers) | the National Buried Infrastructure Facility: a 25 × 10 × 5 m test pit [V]; the MTU multi-sensor programme (GPR, low-frequency EM, passive magnetic, acoustic) [V] | **Facility confirmed**; GPR use and external-access terms **unconfirmed** [S] | a student-project collaboration: burying a §1.2 target set in the pit, or access to existing MTU multi-sensor data |
| P6 | **Guangzhou University GPR group** (Prof. Hai Liu) | open raw data, including multi-channel pipe surveys | **Data released**, contact published [V]; **no truth** | whether as-built pipe positions exist for the University Town surveys |
| P7 | **Virginia DOT / FHWA NDE programme** | test beds with buried PVC and metallic pipes [S] | **Report only** [S] | whether the test-bed data are archived and shareable |
| P8 | **Local PAS 128 / ASCE 38 utility-survey firms; a nearby university civil-engineering or geophysics department** | equipment, operators, real sites with potholing | **Speculative** [S]: no specific firm identified | equipment loan, or a joint survey on a site they are already potholing (this yields grade B truth) |

**Priority:** P1, then P5 and P4 (purpose-built test beds with documented objects), then P8 (the most likely source of equipment), then P2, P3, P6 and P7 (low cost to ask, lower expected yield).

**Offer:** co-authorship, an open processing pipeline, a reproducible evaluation report, and a student project. This is the same pattern as Part C′.

---

## 4. Alternative sensors

All capability statements in this table are **[K]** unless marked otherwise. They must be checked against vendor documentation, or measured on the §1 survey, before any choice is final.

| Sensor | Sees | Misses / limits | Data access | Integration need | Advantage for Subterra |
|---|---|---|---|---|---|
| **EM utility locator**, active (direct connection, clamp or induction) and passive (power, radio) | **continuous conductive utilities**: metallic pipes, energised or traceable cables, tracer wires. Gives position and an estimated depth | **plastic without tracer**, stones, voids. Distorted by neighbouring conductors and by bends. Depth is a model estimate | RD8200-class units log GNSS position and instrument parameters each second, exportable as CSV via RD Manager [V: vendor support page and retailers]. **Whether field strength and depth are exported per point is unverified** [V: not found] | a new `SensorType` (for example `EM_LOCATOR`), a CSV converter, and point or polyline records in the survey frame. **This is a production change and needs approval** | **High for metallic and traced utilities.** It is the industry's routine partner to GPR; PAS 128 survey practice combines EML and GPR [K]. It is cheap to borrow, but it **is not truth for GPR** (it is another sensor with its own errors) |
| **Multi-channel / array GPR** | the same physics as GPR, but **dense 3D by construction**, often dual polarisation | cost and weight; proprietary formats; vendor-processed exports must be avoided (raw is required) | IDS (`.MIS`/`.ZON` + `.DAT`, seen in an open archive [V]); 3D-Radar; ImpulseRadar (RGPR reads `.iprb`/`.iprh` [V]) | per-channel geometry (channel offsets) into `SurveyFrame`; a multi-channel reader; a volume store | **Directly fixes the measured BAM blocker**: cross-line sampling and polarisation (PR #15, #17). **The highest scientific value of any option**, and access is through partners only |
| **FDEM conductivity meter** (for example CMD- or GEM-2-class) | metallic objects; trench backfill contrast; soil conductivity (which also predicts GPR attenuation) | small non-metallic objects; resolution is metre-scale | logger CSV with GNSS [K] | a gridded scalar → `preprocessing/spatial_grid.py` already handles scalar grids [V: module docstring] | **Moderate.** FHWA-HRT-22-111 lists FDEM among the most promising technologies [V: summary]. It is also useful as a **site-attenuation covariate** for GPR |
| **Magnetometer / gradiometer** | ferrous pipes and objects | non-ferrous objects; urban noise | CSV + GNSS [K] | `MAGNETOMETER` already exists in `SensorType` [V] | **Low to moderate.** The phone magnetometer (Part C′) is a demo sensor only, **not evidence-grade** |
| **Acoustic / vibro-acoustic** | plastic water and gas pipes (active excitation) | needs pipe access or excitation; specialist equipment | research systems | new | **Niche.** MTU reports it working better than EM in clay [V: transcript, qualitative only] |
| **Seismic MASW** | voids, large structures | small utilities | SEG-Y | `SEISMIC` exists | low for this object set (FHWA lists it for some cases [V: summary]) |

**Recommendation.**
- The meaningful pair for Subterra's object set is **array or dual-frequency GPR plus an EM locator**.
- EM covers metallic and traced utilities with high confidence. GPR remains the only routine sensor for plastic pipes, stones and voids.
- **Fusion value** comes from EM resolving the conductive subset, which narrows what GPR must explain. **It must be scored as a separate sensor, not used as GPR truth.**
- **No hardware is to be bought.** Every sensor is accessed through §3 partners.

---

## 5. Reassessing the existing architecture (reuse without rebuild)

| Component | Supports the new strategy? | Evidence | Gap (future work, needs approval) |
|---|---|---|---|
| **Converters:** GSSI `.dzt`, MALÅ `.rd3`/`.rad`, IDS `.dt`, SEG-Y (endian-aware), CSV | **Yes**, for single-channel data from the 3 major vendors | each verified on real files [R] | **multi-channel IDS project trees** (`.MIS`/`.ZON`/`ROHDATA`) and ImpulseRadar are unverified; a reader is needed if P1 data arrive |
| **`SurveyFrame`, spatial reference, `geo_tie`, `crs_transform`, `vertical_reference`, KMZ/affine ties** | **Yes.** It was designed exactly for "position only from declared control points" | module docstrings [V]; the 4TU/TU1208/Hillside audits [R] | per-channel antenna offsets for arrays; total-station control import |
| **Provenance, `EvidenceGrade` (A–D), review store** | **Yes.** It already forbids promoting grade C or D to truth | `schemas/segmentation.py`, `schemas/review.py` [R] | a truth-file schema for §1.6 (object geometry, verified-empty polygons, custody hash) |
| **Benchmark layer:** `benchmark/association.py`, `gates.py`, `leakage.py`, `scoring.py`, targets manifests; the freeze-by-blob-hash pattern; `scripts/ccd_v1_stats.py` exact statistics | **Yes.** These are the scoring and integrity primitives §6 needs | [V] | association is in **grid indices**. Matching in **metric 3D coordinates** with tolerances (§6.3) needs an extension |
| **Null models** (`validation/null_models.py`), calibrated threshold, V2 front-end | **Yes, as baselines.** V2 A3 stays frozen as the reference arm | PR #13 [R] | none. **Not to be tuned again** |
| **Preprocessing:** `time_zero`, trace processing, `spatial_grid` | **Yes** | [R] | time zero must be checkable against the §1.5 plate and air shot (validation hooks exist from the TestUM work [R]) |
| **Simulation (gprMax 4.0.0 container, generators v1/v2)** | **Yes, for design only.** It can check that the §1.2 layout is resolvable before burial (the antenna spacing and depth bands) | `docs/simulation.md` [R] | **not run now** (the brief forbids it). Any later run is a design aid, **never validation** |
| **Fusion** (`fusion/sensor_fusion.py`) | **Partly.** It clusters records by location, with a tolerance and a position-kind partition | docstring [V] | no `EM_LOCATOR` sensor type; no object-level (polyline) fusion |
| **3D reconstruction / scene** (`schemas/scene.py`, `api/scene.py`) | **Partly.** Elevation-anchored scene assembly with a DECLARED / MEASURED discipline | docstrings [V] | **no migration and no volume schema** exist yet (Part D items 2 and 5 are still open). An array survey would be the first real input that deserves them |
| **Device and session layer** (`schemas/devices.py`) | **Yes.** It is the path for borrowed-device sessions | docstring [V] | a device profile per borrowed instrument |

**Bottom line.** Ingestion, positioning, provenance, evidence grading and the benchmark integrity machinery are **reusable as they are**. The new strategy needs four bounded additions, **each its own approved stage**:
1. a truth-file schema;
2. metric-tolerance association;
3. a multi-channel reader;
4. an EM-locator sensor type and converter.

Nothing needs rebuilding.

---

## 6. Validation plan (fixed before any new data are used)

### 6.1 Site independence
- **Development:** site A only. Every parameter is frozen (blob-hash committed) before site B is opened.
- **Test:** site B, opened **once**. If a third site exists, it is held back for the confirmatory test.
- **No pooling** of sites in the primary metric; each site is reported separately.
- BAM, TU1208 and 4TU stay **exploratory** and are never pooled with the new data.

### 6.2 Positives and negatives
- **Positives:** grade-A or grade-B objects (§1.6) only.
- **Negatives:** verified-empty cells only. **A region without truth is "unverified", never "empty".**
- **Units:** objects (and verified-empty m²). Lines and traces are repeated measures.

### 6.3 Matching tolerances (proposed; to be checked against the PAS 128 and ASCE 38 text before freezing) [K]

| Quantity | Tolerance |
|---|---|
| Horizontal position | a detection matches an object if it lies within **max(0.15 m, 0.15 × depth)** of the object's surveyed axis or centre |
| Depth | depth error must be ≤ **max(0.10 m, 0.15 × depth)**. It is reported separately and does not gate detection |
| Linear objects | **detected length fraction**: the fraction of the object's surveyed length with a matched detection within tolerance |
| Matching rule | one-to-one (Hungarian) for compact objects; length-based for linear objects |

### 6.4 Statistics and the stop/go rule
- Exact Clopper–Pearson intervals; one-sided exact tests (the PR #14 tooling).
- **Why the object count matters:** with n objects all detected, the 95% lower bound on recall is about 0.74 for n = 12 and about 0.86 for n = 24. With 2 misses out of 12, it falls to about 0.52.
- **Proposed promotion gate:** on the test site, **object recall lower bound ≥ 0.6 per class group** (linear and compact, separately), together with §6.5.
- This is why §1.2 asks for about 12 objects per site and 2 sites.

### 6.5 False-alarm budget (Task A)
- **Rate:** false alarms per verified-empty m². The proposed gate is an **exact one-sided 95% Poisson upper bound ≤ 0.25 per m²**. Its feasibility depends on the area: 8 m² with 0 false alarms gives an upper bound of 0.375, so **≥ 12 m² of verified-empty area is needed** for the gate to be passable at all. **That makes §1.2's "≥ 4 cells" a floor, and 12 cells is the target.**
- **Precision** (matched ÷ all detections over the scored area) is reported; detections in unverified regions are counted as "unverified", not as false.

### 6.6 Runtime
- Processing an 8 × 10 m two-frequency survey must take **≤ 15 min CPU on the reference laptop** (matching G-COST in PR #17).
- Peak memory must be ≤ 4 GB.
- An array volume must be processable in tiles.

### 6.7 Evidence standard
- Pre-registered protocol and code, committed before access to the test site.
- Development and test data in separate custody.
- **One-shot test.** Failures are recorded, not repaired.
- Every result carries its exposure label and its truth grade.
- **No claim about object identity** (pipe vs cable vs stone) without a separately pre-registered Task U test (utility discrimination).

---

## 7. Prioritised roadmap to an evidence-backed MVP

**MVP definition.** On an independent soil test site, Subterra ingests a real survey, reports candidate anomalies in metric coordinates with uncertainty, and meets §6.4–§6.6 against grade A/B truth. **Detection only (Task A); no object typing.**

| Stage | Work | Dependencies | Cost | Go / stop |
|---|---|---|---|---|
| **R0: outreach** (now; weeks 0–8) | operator sends 5 drafted emails (P1, P4, P5, P8, plus a P2 follow-up). Approved, documentation-only drafts | approval of this brief | **zero** (email) | **Go** if ≥ 1 partner confirms **data with grade A/B truth** or **site plus equipment access**. **Stop or re-scope** at week 8 with no confirmation: fall back to R0′ |
| R0′: fallback | one local university or survey firm via P8, for a single-site pilot on potholed utilities (grade B) | the operator's location | zero, if equipment is borrowed | this yields only a one-site exploratory result; it cannot promote anything |
| **R1: readiness** (parallel with R0; 2–3 small branches) | (a) a §1.6 truth-file schema and custody hash; (b) metric-tolerance association and §6 scoring; (c) a §6 protocol template. **No detector work** | approval per stage (b touches benchmark code; none is production detection) | zero (local CPU) | **Go** when tests pass on synthetic fixtures |
| **R2: data arrival** | ingest the partner data or the pilot survey; a reader for the format if needed (multi-channel IDS, EM CSV), **each approved separately** | R0, R1 | zero | **Go** if the §1.5 calibration checks pass (plate depth recovered within tolerance using the independent velocity). **Stop** if the truth is not grade A/B |
| **R3: development on site A** | baseline arms only: V2 A3 frozen as-is, plus at most one pre-registered alternative chosen in a separate brief. Freeze by blob hash | R2 | zero | **Go** if site-A dev recall and FA are within reach of §6.4/§6.5. **Stop** if A3 already fails at dev **and** no pre-registered alternative exists |
| **R4: one-shot test on site B** | apply the frozen configuration | R3; a second site | zero | **MVP reached** if §6.4–§6.6 pass. **Stop** otherwise: report and go back to acquisition design, **not** to tuning |
| R5: fusion (optional) | EM-locator layer scored separately; then a pre-registered fusion test | EM data from R2 | zero if borrowed | only after R4, and only if EM data exist |

**Cost and access risks.**
- Every stage is zero-cash **only if equipment is borrowed**.
- The real costs are the operator's time, travel to a site, and partner goodwill.
- **Burying targets (§1.2) needs a site owner's permission and utility clearance before digging** [K]. That is the partner's responsibility and a hard prerequisite.
- If no partner materialises, the honest outcome is that **an evidence-backed MVP is not reachable at zero budget**. That would be a decision for the owner, not something to engineer around.

---

## 8. Decisions requested

1. **Approve this brief**, including the §6 validation plan, as the standard to be frozen before any new data are used.
2. **Approve R0:** drafting the 5 partner emails (the operator sends them).
3. **Approve R1(a)–(c)** as three small, separate branches. They touch benchmark and schema code, **not production detection**.
4. Confirm the **operator's region**, so that P8 can be made specific.
5. Confirm that **zero budget** still holds, and whether a modest equipment rental would ever be considered. That changes whether R0′ is viable.

---

## Sources (this pass)

- Karle, Boldt, Thiele, Thoennessen (2022), *3D mapping of buried pipes in multi-channel GPR data*, ISPRS Archives XLIII-B1-2022, 85. https://isprs-archives.copernicus.org/articles/XLIII-B1-2022/85/2022/
- Zenodo API records: 15464768 (Tindari), 14637589 (Guangzhou), 10962520 (pulsed vs SFCW), 23375299 (fusion simulation). https://zenodo.org/api/records/
- University of Birmingham, NBIF: https://www.birmingham.ac.uk/research/centres-institutes/uk-collaboratorium-for-research-on-infrastructure-and-cities/national-buried-infrastructure-facility-nbif/about-nbif
- Mapping the Underworld (REF impact case): https://impact.ref.ac.uk/casestudies/CaseStudy.aspx?Id=38848
- Sense-City GPR test bed, EGU 2016 abstract: https://meetingorganizer.copernicus.org/EGU2016/EGU2016-8173.pdf
- FHWA-HRT-22-111 summary: https://highways.dot.gov/sites/fhwa.dot.gov/files/FHWA-HRT-22-111.pdf
- Radiodetection usage-logging support article: https://support.radiodetection.com/hc/en-gb/articles/15650473571869-Usage-Logging
- RGPR formats: https://github.com/emanuelhuber/RGPR
- Earlier repository audits are cited inline as [R].
