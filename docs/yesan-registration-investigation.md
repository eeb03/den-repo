# Yesan full-scale test site: target registration investigation

**Date:** 2026-09-29, updated 2026-10-05 (KEC design report, §0) · **Dataset:** Zenodo [10.5281/zenodo.21441974](https://doi.org/10.5281/zenodo.21441974) (CC-BY-4.0, v1.0.0, published 2026-07-19) · **Manifest:** `benchmark/manifests/yesan-fullscale.targets.json`

**Verdict: BLOCKED. The targets are now known; the registration is not.**
- **Testbed:** the Korea Expressway Corporation's design report gives the constructed testbed's objects (type, size, depth, position), its line geometry, its 0 m start plate and its 90 m layout. These are now in the manifest as authoritative *testbed* truth (§0).
- **2021 radar files:** which trace is above which object is still unknown. The survey direction is only inferred, the authors' "0 m" trace is not shown to lie over testbed 0 m, and the 27 m / 3116-interval distance calibration is unexplained.

The manifest stays `not_scoring_ready`. No detector was run against Yesan, and no Yesan target position was used to tune anything.

The sections below keep four kinds of statement apart: **Verified** (read directly from a raw
file or a published record), **Inferred** (a reasoned interpretation, not proven), **Unresolved**
(blocks scoring), and **Author confirmation required**.

---

## 0. Update 2026-10-05: the KEC design report — testbed ground truth, not a 2021 registration

### 0.1 Source and how it was obtained

| Source | What | Held |
|---|---|---|
| Korea Expressway Corporation Research Institute, *포장하부 상태평가를 위한 비파괴 조사방안 연구* ("A study on non-destructive survey methods for assessing conditions under pavement"), report **EXTRI-2018-40-534.9607**, 216 pp. | design, construction and 2017–18 surveys of the testbed | public PDF on CODIL (record OTKCRK190187): https://www.codil.or.kr/filebank/original/RK/OTKCRK190187/OTKCRK190187.pdf. The earlier search failed on CODIL's TLS chain, not because the file is restricted. Downloaded 2026-10-05 to `datasets/raw/references/kec_extri_2018_40/` (git-ignored, with extracted text and figure images; copyrighted, not committed) |
| Rhee et al. 2021, *Remote Sens.* 13:1805, doi 10.3390/rs13091805, **Figure 3** | the same testbed's asphalt and concrete sections, object IDs | full-resolution PNG (3062×4063) from the MDPI CDN, `datasets/raw/references/rhee2021_fig3_fullres.png` (git-ignored). Used **only for comparison** (§0.9, Appendix A.3) |

Page references below are **PDF page (printed page)**. The printed number is the PDF number minus 22.

Committed derived data (Subterra's transcription, not the source):
- `evidence/yesan/kec_tables_4_6_to_4_8.csv`: Tables 4.6–4.8 cell by cell.
- `evidence/yesan/kec_testbed_targets.csv`: one row per drawn object, normalised.
- `evidence/yesan/rhee2021_vs_kec_comparison.csv`: the comparison, every disagreement kept.
- `evidence/yesan_kec.py`: loader, count reconciliation, facts, `SUPPORTING_ONLY`, `REGISTRATION_STATUS` and `AUTHOR_QUESTIONS`.
- `scripts/build_yesan_manifest_targets.py`: writes the manifest's targets from the CSV; a test checks there is no drift.
- `scripts/yesan_kec_figure_measure.py`: measures the coloured objects in the held figure images. It was an aid only: every row was also checked by eye against plan and section.

### 0.2 Provenance classification

The report describes **two different things**, and only one of them is ground truth for Subterra.

**Authoritative testbed ground truth** is what was built. It is independent of any radar.

| Fact | Where |
|---|---|
| Two survey lines, **1.5 m either side of the road centreline**, A on the left, B on the right | §4.3.3, 82 (60); Fig. 4.3 |
| **Line A: cavity models only.** These are styrofoam hemispheres, plus, at the abutment, two real voids made by digging out square styrofoam after the approach slab was built, each with a locator steel plate inside | 83 (61), 85 (63), 86 (64); Figs. 4.5, 4.7, 4.10 |
| **Line B: every other object type** | 84 (62), 85 (63), 86 (64) |
| **Start steel plate**: "at the point where the asphalt section starts a steel plate was installed to indicate the survey start point". 0.5×0.5×0.1 m, 0.27 m deep, drawn on line B at 0.0–0.5 m. The 2018 multichannel survey sees "the steel plate at the start of line B" | 84 (62); Table 4.6, 83 (61); Fig. 4.5; 130 (108) |
| **End steel plate** where the concrete section ends. 0.5×0.5×0.1 m, 0.45 m deep, drawn on line B at 29.5–30.0 m of the concrete section | 86 (64); Table 4.8; Fig. 4.10 |
| **Longitudinal structure**: asphalt 30 m + approach slab 30 m + concrete 30 m = 90 m, contiguous. The concrete section is plain 0–15 m and CRCP 15–30 m | Fig. 4.3, 82 (60); plain 0–15 m: 134 (112) and Fig. 4.10 |
| **Abutment** in the middle of the approach-slab section: stem 14.7–15.3 m, footing 14.0–16.0 m, i.e. **testbed 44.7–45.3 m (footing 44.0–46.0 m)**. Asphalt-side approach slab 9.0 m (testbed 36–45 m). Concrete side: 8.75 m approach slab + 6.0 m buffer slab (45–60 m) | §4.3.3.2, 84 (62); Fig. 4.7, 85 (63) |
| Object types, sizes, counts and depth (single value or range) | Tables 4.6, 4.7, 4.8: 83, 84, 86 |
| Each object's plan position **measured with GPS coordinates** at installation. The coordinates are not published | Table 4.22, 98 (76) |
| Depths are below the pavement surface. The shallowest cavity model sits "directly beneath the pavement" at 0.27 m (asphalt layers 5+7+15 cm); the model on the drain pipe is at 0.77 m; the concrete minimum 0.45 m = 30 cm slab + 15 cm lean base | 113 (91); 82–86 |
| Groundwater at 3.0 m (embankment / original ground boundary) | 139 (117) |

**Supporting only, for processing the 2021 radar.** These are the 2017–18 KEC MALA surveys. They were **never measured on the 2021 files** and are not in the manifest.

| Item | Where |
|---|---|
| Four MALA ProEx campaigns, 2017-06 to 2018-08; 100/250/500 MHz shielded antennas | Tables 5.1–5.2, 109–110 |
| Antenna separations 0.5 / 0.36 / 0.18 m | Table 5.3, 111 (89) |
| Time-zero correction: time-muting offset of −separation/c (e.g. −0.36/3E8 s ≈ 1.2 ns at 250 MHz) | Table 5.4, 112 (90) |
| Kirchhoff migration velocity 0.75E+8 m/s (0.075 m/ns) | Table 5.4 |
| Trace interval 0.05 m (0.02 m in campaign 2), ~60 ns windows, Reflex-W processing | Table 5.3 |

None of these is applied to the 2021 files. A time-zero shift chosen for a 2017 survey says nothing about the 2021 instrument's zero, and a migration velocity is a processing choice, not a measurement. `SUPPORTING_ONLY` carries `transferable_to_2021 = False` on every entry, and a test checks that none of them appears in a target, frame or depth.

**Site identity is inferred, not stated.** The report anonymises the site as a road-performance test site at "00000IC" (91 (69)). The case that it is the Zenodo 21441974 site is strong but circumstantial:
- the same organisation (KEC Research Institute);
- the same 90 m asphalt → approach slab → concrete bridge-transition layout;
- QDM file names that use exactly the KEC chainages (approach slab 30–60, plain 60–74, reinforced 75–90);
- the 2021 radar changes falling on KEC landmarks (§0.5).

This is open question `yesan-site-identity`, and it blocks scoring.

### 0.3 Count reconciliation

| Section | Text total | Table rows | Drawn | Difference |
|---|---|---|---|---|
| Asphalt (Table 4.6, Fig. 4.5) | 40 | 40 | 40 | none: every type and size matches |
| Approach slab (Table 4.7, Fig. 4.7) | **38** | **36** | **34** | steel plates: table 8, drawn 6 (2 in the abutment voids, 4 on line B). The text also says "7 types" against 8 table rows |
| Concrete (Table 4.8, Fig. 4.10) | 42 | 42 | 42 | none |

Other discrepancies inside the KEC report, kept rather than resolved:
- Fig. 4.5 labels the first loosened zone 2.0×1.8×**1.0**, while Table 4.6 says ×**0.5**; it is drawn ~0.5 m thick.
- Fig. 4.10 labels the concrete-section zones 5.0×2.8×**1.0**, while Table 4.8 says ×**0.5**.
- The approach-slab hemispheres are drawn at only ~0.7–1.7 m, against the table's 0.27–2.0 m.
- The two locator plates inside the voids are drawn at 1.15 and 1.6 m, outside the table's 0.3–1.0 m.
- The concrete hemisphere at 29 m is drawn at ~2.75 m, against a table maximum of 2.5 m.
- Five moisture sensors drawn in the asphalt section are instrumentation and not in Table 4.6.

### 0.4 Lateral placement (from the plan views)

Several "line B" objects are drawn **between the centreline and line B**, roughly 0–1.0 m from the centreline, not on the line:
- the three empty earthenware pots at 9 and 15 m;
- the 0.5×1.0 m asphalt blocks, empty plastic containers and styrofoam blocks in both sections.

Two concrete-section D0.5 hemispheres are drawn ~0.4–0.45 m outside line A. The column `lateral_placement` records this per object. It matters for any detection radius: such an object is not directly under a line-B profile.

### 0.5 Registration status, component by component

| Component | Status | Basis |
|---|---|---|
| Physical testbed 0 m reference | **SOLVED FOR TESTBED** | start of the asphalt section, marked by the buried steel plate on line B (0.0–0.5 m, 0.27 m deep). **This plate does not show that trace 0, or the authors' 2021 "0 m" trace, lies over it.** It is buried, so it is not a surface mark an operator would see, and line A has no plate |
| Constructed target coordinates / distances | **SOLVED FOR TESTBED** | type, size, count and depth from the tables; position from the figures (±0.1 m); counts reconcile except the approach slab |
| Line A / B geometry | **SOLVED FOR TESTBED** | ±1.5 m from the centreline, A left, B right |
| KEC testbed = Zenodo site | **PARTIALLY SOLVED** | inferred, strongly (§0.2); not stated by any source |
| 2021 survey direction | **PARTIALLY SOLVED** | inferred. The 2021 near-surface changes at 44.0–45.0, ~60 and 72.6–75.6 m fall on the abutment (44–46 m), the approach-slab/concrete boundary (60 m) and the plain/CRCP boundary (75 m) only if both lines start at the asphalt end. A reversed run would put the 60 and 75 m changes at 30 and 15 m. Not declared |
| 2021 trace-to-distance scale | **STILL UNKNOWN** | wheel 0.008429 m vs sheet 27/3116 m (§4) |
| Meaning of the 27 m / 3116 calibration | **STILL UNKNOWN** | below |
| Whether 2021 target positions use the same distance frame | **STILL UNKNOWN** | no 2021 target table is held |
| Exact 2021 trace-to-testbed transformation | **STILL UNKNOWN** | needs direction, start alignment and scale |

The landmark coincidence now favours **H1 (shared chainage)** over H2 (a 14.5 m offset; §7). Under H1, the abutment explains the strongest change at 44.0–45.0 m, the approach-slab/concrete boundary explains ~60 m, and the plain/CRCP boundary explains ~74–75 m. Under H2, the 44.5 m change would have to be testbed 30 m, where the asphalt simply continues (the approach slab only begins at 36 m).

**This is a consistency check, not a registration.** Fitting radar features to design landmarks would let the radar choose its own truth frame. Nothing is shifted, scaled or anchored on it.

### 0.6 The 27 m / 3116-interval calibration

The existing finding (§4) stands. The authors' sheet interval dx = 0.0086649550706 m is **exactly 27/3116** (difference < 10⁻¹²). That is a 27 m reference distance spanning 3116 trace intervals, and it equals the effective wheel calibration of 346.22 pulses·m⁻¹ quoted in §4.

The KEC report describes a 90 m site in three 30 m sections. It contains no 27 m calibration distance, and it predates the 2021 survey, so it **cannot explain** the 27 m. Nothing here supports reading 27 m as one of the 30 m sections, or as any KEC feature, so no such reading is made. Where 27 m was measured, between which marks and on which line remains an author question.

### 0.7 What this does to the scoring gate

The gate stays shut and was not loosened. The manifest now has 108 KEC targets (116 physical items), all in the testbed frames `yesan:testbed-A/B`:
- `construction_record`, grade B, independent of the GPR, `verified_by_subterra = false`;
- grade B, not A, because positions are design-figure readings and the GPS installation coordinates are unpublished.

`readiness()` is `not_scoring_ready`. Every capability in every frame is blocked by:
- `yesan-testbed-to-2021-registration`;
- `yesan-site-identity`;
- the frames' `registration_to_radar = unresolved`;
- `yesan-line-registration`, `yesan-distance-scale` and `yesan-survey-direction`.

Depth scoring is also blocked by `yesan-depth-point` and `yesan-kec-rhee-figure-discrepancies`. False positives and per-metre rates are also blocked by non-exhaustiveness and `yesan-approach-slab-count`. A test scores a prediction artifact in the testbed frame and asserts it is refused.

**The blocking question is no longer "where are the targets?"** It is whether the 2021 traces can be mapped to the testbed frame by a defensible transformation. That needs:
- the 2021 survey direction;
- the exact start alignment, i.e. which trace on each line is over testbed 0 m;
- what the 27 m / 3116 recalibration measured and whether it should be applied;
- whether target positions are meant in the same calibrated distance convention.

### 0.8 Author questions (minimum set)

1. Is the Zenodo 21441974 site the testbed of KEC report EXTRI-2018-40-534.9607 / Rhee et al. 2021? Were any objects added, removed or moved between 2018 and the 2021-04-06 survey?
2. On each 2021 line, what physical mark is "0 m" (zero traces 65/96/107 on A, 80/60/60 on B)? Is it the asphalt-start steel plate (line B), and what was used on line A, which has no plate?
3. Were both 2021 lines run from the asphalt end toward the concrete end?
4. What was the 27 m reference behind dx = 27/3116: where, on which line, and between which marks?
5. Are the target positions in the dataset's MDPI *Sensors* table in KEC design chainage (asphalt start = 0 m), the sheet distance (trace − zero trace) × dx, or the wheel distance?
6. Where KEC Figs. 4.5/4.7/4.10 and Rhee 2021 Fig. 3 differ (e.g. concrete drain at 4.6 vs 5.0 m; concrete line-A depths 0.2–0.4 m apart), which is as built? Are the GPS installation coordinates (Table 4.22) available?

### 0.9 Rhee 2021 comparison (summary)

There are 74 objects in both sources (Rhee shows no approach slab). **48 agree** within 0.15 m in both position and depth; **26 disagree**:
- **Asphalt**: agrees except AP-A07's depth (KEC 2.70, Rhee 2.52 m) and the start plate (KEC centre 0.26 m, Rhee 0.46 m).
- **Concrete line A**: Rhee draws most hemispheres **0.2–0.25 m shallower** than KEC (CP-A02 and CP-A13 0.4 m shallower, at 0.34 m, which is above the 0.45 m pavement structure), while CP-A01 is 0.28 m deeper. The drain and the hemisphere above it are at **4.6 m (KEC) vs 5.0 m (Rhee)**. Rhee labels the 22 m line-A object "CP-B10".
- **Concrete line B**: shallow objects are ~0.17 m shallower in Rhee; positions near the end drift up to −0.34 m (end plate 29.74 vs 29.40 m).

**KEC is used as read. No value is moved toward Rhee, and no radar data is shifted to reconcile them.** The full table is in Appendix A.3.

---

## 1. Evidence inventory

| Source | Where | What it holds |
|---|---|---|
| `Yesan test site GPR Raw data_0629.zip` (37,298,265 B, MD5 `6e40b0ea…` = record) | `datasets/raw/zenodo/yesan_21441974/` (git-ignored) | 6 × MALÅ `.rad`/`.rd3`, `summary of GPR data and formula.xlsx`, `TPG.py` |
| `9 GPR images.zip` (4,342,467 B, MD5 `852c53b6…` = record) | same | 9 published B-scan PNGs (ascon / approach slab / concrete × 250/500/800 MHz) |
| `1m distance data along 90m section.zip` (7,029,554 B) | read in-browser from Zenodo; not stored | 93 QDM CSVs + a nested zip that duplicates them |
| `9 repetition dataset_selected points.zip` (5,487,822 B) | file list read on Zenodo's previewer; not stored | QDM CSVs by date folder (0508 … 0712_2) |
| Zenodo record metadata (API) | read in-browser | creator, affiliation, ORCID, description, collection dates; **no related identifiers** |
| MDPI *Sensors* paper referred to by the record | web search, MDPI search | **not found / not yet indexed** |
| Author contact | Hanseo University HUCAS faculty page; public ORCID record | verified email (§10) |

Nothing else Yesan-related exists in the repository, `docs/`, or elsewhere on this machine
(searched for yesan, QDM, target/section/line names, frequency strings).

---

## 2. Raw GPR metadata (Verified)

All six `.rad` headers are **identical** except for `SIGNAL POSITION`, `RAW SIGNAL POSITION`,
`LAST TRACE` and `STOP POSITION`. Common to all: `SAMPLES 384`, `FREQUENCY 6976.245117` (the
**sampling** frequency, MHz → Δt 0.14334 ns), `TIMEWINDOW 55.043939` ns, `DISTANCE INTERVAL
0.008429` m, `WHEEL CALIBRATION 355.9`, `POSITIVE DIRECTION -1`, `START POSITION 0`,
`ANTENNAS 500 MHz shielded=2`, `ANTENNA SEPARATION 0.18`, `COMMENT Cart=4`, `STACKS 1`,
`DISTANCE FLAG 1` (wheel-triggered); `OPERATOR`, `CUSTOMER`, `SITE` are `_`. No coordinates,
no date field.

| File | Folder label | Zip timestamp | Traces | Wheel length (m) | Signal pos. | Raw signal pos. | Spectral centroid (MHz) | Sheet 0 m trace | Sheet length (m) |
|---|---|---|---|---|---|---|---|---|---|
| DAT_0066 | A, 250 MHz | 2021-04-06 14:42 | 10,801 | 91.045 | 30.69 | 51618 | 270 | 65 | 93.59 |
| DAT_0068 | B, 250 MHz | 2021-04-06 14:48 | 10,627 | 89.579 | 30.69 | 51618 | 269 | 80 | 92.08 |
| DAT_0069 | A, 800 MHz | 2021-04-06 14:58 | 10,760 | 90.700 | 26.76 | 53402 | 719 | 107 | 93.23 |
| DAT_0071 | B, 800 MHz | 2021-04-06 15:06 | 10,578 | 89.165 | 26.76 | 53402 | 715 | 60 | 91.66 |
| DAT_0072 | A, 500 MHz | 2021-04-06 15:15 | 10,767 | 90.759 | 35.19 | 49580 | 457 | 96 | 93.30 |
| DAT_0074 | B, 500 MHz | 2021-04-06 15:23 | 10,674 | 89.975 | 35.19 | 49580 | 444 | 60 | 92.49 |

Spectral centroid: mean amplitude spectrum of every trace after per-trace mean removal, Hann
window, 50–2000 MHz band. Trace counts and sheet lengths match the authors' spreadsheet exactly.
The zip member timestamps are file modification times, which normally equal the acquisition
save time on MALÅ systems — treated as **Inferred** acquisition date, not verified.

---

## 3. Antenna frequency

**Verified:** every header says `500 MHz shielded`; `SIGNAL POSITION`/`RAW SIGNAL POSITION`
fall into exactly three groups that coincide with the folder labels (not with lines A/B).

**Inferred (strong):** three physically different antennas were used, and the `ANTENNAS` field
was not updated between them. The recorded signals have spectral centroids of ~270, ~450 and
~715 MHz in the 250/500/800 MHz folders respectively, identical within each A/B pair. A single
500 MHz antenna cannot produce a 270 MHz or a 715 MHz centroid on the same site. The acquisition
order (250 A,B → 800 A,B → 500 A,B, with numbering gaps 0067/0070/0073) is what antenna changes
between pairs would look like.

So of the four options: **(A)** — the antenna field was carried over unchanged — is supported;
**(B)** the folder name is the only *declared* source; **(C)** `SIGNAL POSITION` is a
configuration fingerprint but not a frequency statement; **(D)** is contradicted by the signal.
Subterra's frequency metadata is **not** changed: a frequency breakdown must cite the folder
label plus this spectral evidence until the authors confirm.

## 4. Distance scale (the 2.8% discrepancy)

**Verified:** `DISTANCE INTERVAL 0.008429` = 3 wheel pulses / `WHEEL CALIBRATION 355.9`
pulses·m⁻¹ (3 / 355.9 = 0.0084293). The authors' sheet uses `dx = 0.0086649550706`, which is
3 / 346.22 — i.e. an effective wheel calibration of **346.22 pulses·m⁻¹**. Ratio 1.02796.
The sheet's "Survey Distance" is exactly traces × dx (10,801 → 93.59018; 10,767 → 93.29557;
10,578 → 91.65789 m, matching the listed values to 10⁻⁶ m).

**Inferred:** the authors re-calibrated the wheel after acquisition (a field-measured known
distance would produce exactly this kind of single scale factor). Neither the calibration
distance nor its method is documented. The published images (below) use the sheet scale.

**Not the explanation:** antenna offset (a constant, not a 2.8% scale), stacking or resampling
(`STACKS 1`, no resampling field), start offset (`START POSITION 0`).

**27/3116 (added 2026-10-05):** the sheet interval is exactly 27/3116 = 0.0086649550706 m
(difference < 10⁻¹²). That is a 27 m reference distance spanning 3116 trace intervals, the
same thing as the 346.22 pulses·m⁻¹ above. The KEC report (§0.6) does not explain the 27 m.

Radar distance is **not** rescaled in Subterra. A linear map `physical = a·radar + b` needs two
independent physical anchors; none is held.

## 5. What `0 m` means

**Verified:** the sheet gives a per-file "Zero-Position Trace No. (Sample Number at the 0 m
Reference Position)": 65, 80, 107, 60, 96, 60. It is 0.5–0.9 m after recording starts and
differs between runs on the same line, so it is a **physical mark the operators placed**, not
the first trace.

**Inferred:** in the published `ascon_*` images, the 0 m position sits within the direct
start-of-line disturbance (0–0.8 m), consistent with a start mark at the beginning of the
asphalt section. **Not verified:** what the mark is (peg, joint, painted line, construction
station) and whether target positions are measured from it.

## 6. The published images' distance axis (Inferred, moderate)

The `concrete_500MHz` image (80–90 m) shows regularly spaced shallow hyperbolas (apexes ≈ 80.2,
81.4, 82.6, 83.8, 84.9, 86.2, 87.3 m). Locating shallow apex peaks in the raw files: with the
**sheet convention** `(trace − zero_trace) × 0.0086650`, line A (DAT_0072) gives apexes at
81.42, 84.88, 86.28 m — within 0.02 m of three image apexes; the wheel convention matches none
that closely, and line B fits worse under both. So the published images are very probably line A
plotted in the authors' own convention. This says how the authors map traces to *their*
distances; it does **not** establish that those distances equal the site's physical stationing
or the system a target list would use.

## 7. The 30 m vs ~44.5 m landmark

*Update 2026-10-05:* the KEC design places the abutment at testbed 44.0–46.0 m, the
approach-slab/concrete boundary at 60 m and the plain/CRCP boundary at 75 m, which favours H1
(§0.5). That is still a consistency check, not a registration.

**Verified:**
- QDM "90 m section" data exist for **line A only**: `ascon` 0–30 m (2026-06-26), `approach slab`
  30–60 m (2026-07-14), `plain concrete` 60–74 m and `reinforced concrete` 75–90 m (2026-07-15),
  one stationary ~37 s recording per metre, measured in increasing station order. The CSVs hold
  `timestamp, Bx, By, Bz, B norm` only — **no coordinates**; the station exists only in the name.
- The QDM repetition data use **different distances for the same section names**:
  `approach slab_A_11–15 m`, `reinforced concrete_A_26–30 m`, `ascon_B_0–5 m`. A 26–30 m
  position cannot be section-local inside a 75–90 m (15 m long) section, so the repetition names
  use at least one other convention, unstated.
- The strongest near-surface lateral change in the raw GPR is at **44.0–45.0 m** on A-500, A-800
  and B-800 (42.5 m on B-250), under either scale; other changes at ~60 m and 72.6–75.6 m.

**Inferred, two hypotheses that the held evidence cannot separate:**
- **H1 — shared chainage:** GPR and QDM names use one origin. Supported by the ~60 m and ~74–75 m
  GPR changes (QDM approach→plain and plain→reinforced boundaries) and by the regular shallow
  reflectors at 80–89 m in the published "concrete" image (inside QDM's reinforced section).
  Then the 44.5 m change is something *inside* the approach slab (a joint, a sleeper-slab edge,
  or a buried object) — not the asphalt/approach boundary.
- **H2 — 14.5 m offset:** 30→44.5, 60→74.5, 75→89.5 (line end). Also fits the three changes.

The GPR is from **2021**, the QDM from **2026**; they were never one survey, so no shared
reference can be assumed. **Neither boundary is used as a registration anchor.**

## 8. Survey direction

*Update 2026-10-05:* PARTIALLY SOLVED by inference only (§0.5); the KEC lines run A→A′ and
B→B′ from the asphalt end, but that describes the testbed, not how the 2021 runs were made.

**Verified:** `POSITIVE DIRECTION -1` in every file (an instrument setting; it does not give a
compass direction). **Inferred:** both lines run the same way — B shows the ~73–74 m and ~44–45 m
changes near the same distances as A, where a reversed run would mirror the 74 m change to
~16 m; `ascon_B_0–5 m` in the QDM data also places B's start on asphalt. Physical start/end
(which end is the bridge) is **not** documented.

## 9. Target list, completeness and evidence grade (as of 2026-09-29, superseded for the testbed by §0)

**Verified:** no target list, target table, site plan or target photograph exists in any held
file, on the Zenodo record, or in a findable publication. The record states the data include
"supporting ground-truth information used in the accompanying MDPI Sensors publication"; none
of the four archives contains it (the spreadsheet is acquisition parameters only).

Completeness: **unknown** → `exhaustive: false`. Recall could be scored against a partial list;
precision/false positives could not.

Grade: **not assignable yet.** If the targets were installed during construction of the test
facility and their positions come from as-built records, the basis would be
`construction_record` and the grade could reach **A** (independent of the radar) — but only if the
positions are in a chainage the GPR is registered to. If positions were read from these
radargrams, the basis is `operator_radar_interpretation`, grade ≤ C. The paper has to say which.

## 10. Benchmark gates (as of 2026-09-29; for the current gate see §0.7)

| Capability | State | Why |
|---|---|---|
| Detection matching (TP/FN/recall) | **blocked** | no targets; `yesan-line-registration`, `yesan-distance-scale`, `yesan-section-boundary`, frame registration `unresolved` |
| False positives / precision / F1 | **blocked** | truth not exhaustive (no list) |
| False alarms per metre | **blocked** | plus distance scale unresolved |
| Chainage / localisation error | **blocked** | origin unverified, registration unresolved |
| Depth error | **blocked** | no targets; no depth reference surface; time-zero and velocity undeclared |

What would unlock what: a target list **with** chainages stated in the sheet convention
(`(trace − zero_trace) × dx`) and a statement that the `0 m` mark is the targets' origin would
unlock matching and recall per antenna (both lines, if direction is confirmed). An explicit
"these are all buried objects under both lines" would add precision/F1/per-metre rates. Depth
stays gated on time-zero, velocity and a declared reference surface regardless.

## 11. Author confirmation required

**Superseded in part by §0.8**, which is the current minimum set: the target table is now
known for the testbed, so the questions are about the 2021 registration. Kept for the record:
asked in the draft below — each is a question no public source answers:
1. The buried-target table (type, material, dimensions, burial depth to top/centre, reference
   surface, line, chainage), and how positions were established.
2. What physical mark `0 m` is on lines A and B.
3. Whether target chainages use the spreadsheet's `dx = 0.0086649550706` m and zero traces,
   the wheel's 0.008429 m, or site stationing.
4. Whether A and B were run in the same direction, and which end is the bridge.
5. Whether the 250/500/800 MHz folder labels are correct despite the `500 MHz` header.
6. How 0.0086649550706 m was determined.
7. Whether the list is exhaustive for both profiles.

### Draft email (not sent)

- **To:** coh@hanseo.ac.kr — Dr Chang-Geun Oh, Assistant Professor, Department of Aerospace
  Industrial and Systems Engineering, Hanseo University. Verified on the Hanseo HUCAS faculty
  page (sites.google.com/view/hucas/members/faculty-advisor-chang-geun-oh) and on the public
  ORCID record 0000-0002-9464-4397, which is the ORCID on the Zenodo record.
- **Subject:** Yesan GPR dataset (Zenodo 21441974) — target table and line registration

> Dear Dr Oh,
>
> Thank you for publishing the Yesan full-scale test-site dataset on Zenodo
> (10.5281/zenodo.21441974). We are building an open benchmark for GPR buried-object detection
> and would like to use your six MALÅ profiles with the documented buried targets as an
> independently labelled test. The target information does not appear to be in the Zenodo
> files, and we have not yet found the MDPI Sensors article. Could you help with a few specific
> points?
>
> 1. Could you share the buried-target table (type, material, dimensions, burial depth and
>    whether it is to the top or centre, the surface it is measured from, line A/B, and
>    position along the line), and say how the positions were established (e.g. construction
>    records)?
> 2. What physical mark is "0 m" on lines A and B (the zero-position traces 65/96/107 and
>    80/60/60 in your summary sheet)?
> 3. Are target positions expressed with your sheet's dx = 0.0086649550706 m and those zero
>    traces, with the wheel's 0.008429 m, or in site stationing? How was 0.0086649550706 m
>    determined?
> 4. Were lines A and B surveyed in the same direction, and which end is the bridge?
> 5. The .rad headers all read "500 MHz shielded"; can you confirm the 250/500/800 MHz folder
>    labels are the antennas actually used?
> 6. Is the target list complete for both profiles?
>
> We would cite the dataset and your article, and are glad to share our results.
>
> Kind regards,
> [name] · [organisation] · eneteebube@gmail.com

---

## 12. DRC fallback (status)

The DRC request drafted on 2026-09-29 (`~/Documents/Subterra_dataset_routes_2026-09-29.docx`,
to jbaur@de-mine.org) is ready to send. Add two questions to it: (a) the positions and exact
semantics of the **control holes** the JMU article mentions ("control holes" as a class in the
seeded grid) — whether soil was disturbed with nothing placed; (b) whether the published list is
exhaustive for the field. The `attested empty location` schema extension stays **unimplemented**
until the DRC answer states those semantics.

## 13. Sources

- Zenodo record and API: https://zenodo.org/records/21441974 (read 2026-09-29)
- Hanseo HUCAS faculty page: https://sites.google.com/view/hucas/members/faculty-advisor-chang-geun-oh
- ORCID public record: https://orcid.org/0000-0002-9464-4397
- JMU CISR, "An Accessible Seeded Field for Humanitarian Mine Action Research" (DRC control holes):
  https://www.jmu.edu/news/cisr/2023/10/273/01-273-baur.shtml
- Held raw files: `datasets/raw/zenodo/yesan_21441974/` (checksums above)
- KEC report EXTRI-2018-40-534.9607 (CODIL OTKCRK190187):
  https://www.codil.or.kr/filebank/original/RK/OTKCRK190187/OTKCRK190187.pdf (read 2026-10-05;
  held git-ignored at `datasets/raw/references/kec_extri_2018_40/`)
- Rhee et al. 2021, Remote Sens. 13:1805, https://doi.org/10.3390/rs13091805, Figure 3 at full
  resolution (held git-ignored at `datasets/raw/references/rhee2021_fig3_fullres.png`)

---

## Appendix A. KEC testbed tables (generated from `evidence/yesan/*.csv`)

### A.1 Tables 4.6–4.8 as transcribed

| Table (PDF p.) | Section | Object (KEC term) | Size (m) | Count | Depth stated |
|---|---|---|---|---|---|
| 4.6 (83) | asphalt | steel_plate (강판) | 0.5x0.5x0.1 | 1 | 0.27m |
| 4.6 (83) | asphalt | plastic_container_air (플라스틱 통(공기)) | 0.5x0.5x0.1 | 1 | 0.27m |
| 4.6 (83) | asphalt | plastic_container_air (플라스틱 통(공기)) | 0.5x1.0x0.1 | 1 | 1m |
| 4.6 (83) | asphalt | plastic_container_water (플라스틱 통(물)) | 0.5x0.5x0.1 | 2 | 0.27m~1m |
| 4.6 (83) | asphalt | styrofoam_hemisphere (스티로폼) | D0.5 | 7 | 0.27m~2m |
| 4.6 (83) | asphalt | styrofoam_hemisphere (스티로폼) | D1.0 | 5 | 0.27m~3m |
| 4.6 (83) | asphalt | asphalt_block (아스콘블럭) | 0.5x1.0x0.1 | 1 | 1m |
| 4.6 (83) | asphalt | asphalt_block (아스콘블럭) | 0.5x1.0x0.2 | 2 | 2m~2.5m |
| 4.6 (83) | asphalt | asphalt_block (아스콘블럭) | 0.5x0.5x0.1 | 1 | 0.27m |
| 4.6 (83) | asphalt | rock (암석) | D0.6 | 1 | 2m |
| 4.6 (83) | asphalt | loosened_ground_zone (지반이완대) | 2.0x1.8x0.5 | 1 | 0.27m |
| 4.6 (83) | asphalt | loosened_ground_zone (지반이완대) | 5.0x1.8x1.0 | 1 | 2m |
| 4.6 (83) | asphalt | loosened_ground_zone (지반이완대) | 6.0x2.8x1.0 | 1 | 1m |
| 4.6 (83) | asphalt | concrete_block (콘크리트블럭) | 0.5x0.5x0.1 | 2 | 0.27m~1m |
| 4.6 (83) | asphalt | concrete_block (콘크리트블럭) | 0.5x0.5x0.2 | 2 | 2m~2.5m |
| 4.6 (83) | asphalt | earthenware_air (토기(공기)) | D0.4 | 6 | 2m~2.5m |
| 4.6 (83) | asphalt | earthenware_water (토기(물)) | D0.4 | 4 | 2m~2.5m |
| 4.6 (83) | asphalt | transverse_drain_pipe (횡배수관) | D0.9 | 1 | 1.5m |
| 4.7 (84) | approach_slab | steel_plate (강판) | 0.5x0.5x0.1 | 8 | 0.3m~1.0m |
| 4.7 (84) | approach_slab | plastic_container_water (플라스틱 통(물)) | 1.0x1.0x0.1 | 4 | 1.0m |
| 4.7 (84) | approach_slab | void (공동(빈공간)) | 1.0x1.8x0.5 | 2 | 0.5m~1.0m |
| 4.7 (84) | approach_slab | styrofoam_hemisphere (스티로폼) | D1.0 | 10 | 0.27m~2.0m |
| 4.7 (84) | approach_slab | asphalt_block (아스콘블럭) | 1.0x1.0x0.1 | 4 | 1.0m |
| 4.7 (84) | approach_slab | rock (암석) | D0.6 | 2 | 2.0m~2.5m |
| 4.7 (84) | approach_slab | loosened_ground_zone (지반이완대) | 5.0x1.8x1.0 | 2 | 1.5m |
| 4.7 (84) | approach_slab | concrete_block (콘크리트블럭) | 1.0x1.0x0.1 | 4 | 1.0m |
| 4.8 (86) | concrete | steel_plate (강판) | 0.5x0.5x0.1 | 1 | 0.45m |
| 4.8 (86) | concrete | plastic_container_air (플라스틱 통(공기)) | 0.5x1.0x0.1 | 4 | 0.45m~1.0m |
| 4.8 (86) | concrete | plastic_container_water (플라스틱 통(물)) | 0.5x0.5x0.1 | 3 | 0.45m~1.0m |
| 4.8 (86) | concrete | plastic_container_water (플라스틱 통(물)) | 0.5x1.0x0.1 | 1 | 0.45m |
| 4.8 (86) | concrete | styrofoam_block (스티로폼) | 0.5x1.0x0.2 | 2 | 2.0m |
| 4.8 (86) | concrete | styrofoam_hemisphere (스티로폼) | D0.5 | 2 | 2.0m |
| 4.8 (86) | concrete | styrofoam_hemisphere (스티로폼) | D1.0 | 12 | 0.45m~2.5m |
| 4.8 (86) | concrete | asphalt_block (아스콘블럭) | 0.5x0.5x0.1 | 3 | 0.45m~1.0m |
| 4.8 (86) | concrete | asphalt_block (아스콘블럭) | 0.5x1.0x0.2 | 2 | 2.0m |
| 4.8 (86) | concrete | asphalt_block (아스콘블럭) | 0.5x1.0x0.1 | 1 | 0.45 |
| 4.8 (86) | concrete | rock (암석) | D0.6 | 1 | 2.0m |
| 4.8 (86) | concrete | loosened_ground_zone (지반이완대) | 5.0x2.8x0.5 | 2 | 0.45m |
| 4.8 (86) | concrete | concrete_block (콘크리트블럭) | 0.5x0.5x0.2 | 2 | 2.0m |
| 4.8 (86) | concrete | earthenware_water (토기(물)) | D0.4 | 4 | 2.0m |
| 4.8 (86) | concrete | transverse_drain_pipe (횡배수관) | D0.9 | 2 | 1.5m |

### A.2 Per-object ground truth (testbed frame)

Position = testbed chainage from the asphalt-section start, read from the KEC figure (±0.1 m). Depth basis: `text` = stated in the report text, `table` = the table's single value for that object type and size, `figure` = read from the cross-section (±0.15 m). Every row: source KEC EXTRI-2018-40-534.9607, evidence level *authoritative testbed design*, applies to the 2021 survey: *not established*.

| ID | Line | Lateral | Object | Size (m) | n | Position (m) | Depth (m) | Depth basis | Table / Fig. (PDF p.) | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| AS-A01 | A | on line | styrofoam hemisphere | D0.5 | 1 | 2.00 | 0.35 | figure | 4.6 / 4.5 (83) | drawn directly beneath the 0.27 m asphalt layers; report text (PDF p.113) cites a line-A cavity model directly beneath the pavement at 0.27 m without saying which one |
| AS-A02 | A | on line | styrofoam hemisphere | D0.5 | 1 | 5.00 | 0.77 | text | 4.6 / 4.5 (83) | on top of the transverse drain pipe; depth stated in text (PDF p.113, printed p.91); figure reads 0.80 |
| AS-A03 | A | on line | styrofoam hemisphere | D0.5 | 1 | 8.00 | 1.00 | figure | 4.6 / 4.5 (83) |  |
| AS-A04 | A | on line | styrofoam hemisphere | D0.5 | 1 | 11.00 | 1.55 | figure | 4.6 / 4.5 (83) |  |
| AS-A05 | A | on line | styrofoam hemisphere | D0.5 | 1 | 14.00 | 2.05 | figure | 4.6 / 4.5 (83) | deepest D0.5; table maximum 2.0 |
| AS-A06 | A | on line | styrofoam hemisphere | D1.0 | 1 | 17.00 | 3.05 | figure | 4.6 / 4.5 (83) | deepest D1.0; table maximum 3.0 |
| AS-A07 | A | on line | styrofoam hemisphere | D1.0 | 1 | 20.00 | 2.70 | figure | 4.6 / 4.5 (83) | Rhee 2021 Fig. 3 draws it at ~2.5 m (see comparison) |
| AS-A08 | A | on line | styrofoam hemisphere | D1.0 | 1 | 23.00 | 2.00 | figure | 4.6 / 4.5 (83) |  |
| AS-A09 | A | on line | styrofoam hemisphere | D1.0 | 1 | 26.05 | 1.55 | figure | 4.6 / 4.5 (83) |  |
| AS-A10 | A | on line | styrofoam hemisphere | D1.0 | 1 | 29.00 | 0.40 | figure | 4.6 / 4.5 (83) | drawn directly beneath the asphalt layers; table minimum 0.27 |
| AS-D01 | A;B | crosses both lines | transverse drain pipe | D0.9 | 1 | 5.00 | 1.50 | table | 4.6 / 4.5 (83) | transverse pipe under both lines; the drawn box top is ~1.05 m, so 1.5 m may be the pipe centre (unresolved) |
| AS-B01 | B | on line | steel plate | 0.5x0.5x0.1 | 1 | 0.0–0.5 | 0.27 | table | 4.6 / 4.5 (83) | installed at the start of the asphalt section 'to mark the survey start point' (PDF p.84, printed p.62); drawn in plan only (0.0-0.5 m) |
| AS-B02 | B | spans line | loosened ground zone | 2.0x1.8x0.5 | 1 | 1.0–3.0 | 0.27 | table | 4.6 / 4.5 (83) | Fig. 4.5 labels it 2.0x1.8x1.0; table says 2.0x1.8x0.5; drawn ~0.5 m thick |
| AS-B03 | B | on line | rock | D0.6 | 1 | 2.00 | 2.00 | table | 4.6 / 4.5 (83) | beneath AS-B02 |
| AS-B04 | B | on line | styrofoam hemisphere | D0.5 | 1 | 4.25 | 1.75 | figure | 4.6 / 4.5 (83) | line-B hemisphere beside the drain pipe; Rhee's 'top surface' statement covers line A only |
| AS-B05 | B | on line | styrofoam hemisphere | D0.5 | 1 | 5.75 | 1.10 | figure | 4.6 / 4.5 (83) | line-B hemisphere beside the drain pipe |
| AS-B06 | B | on line | earthenware water | D0.4 | 2 | 8.00 | 2.35 | figure | 4.6 / 4.5 (83) | 2 water-filled pots (15 kg) |
| AS-B07 | B | between centreline and line | earthenware air | D0.4 | 3 | 9.00 | 2.35 | figure | 4.6 / 4.5 (83) | 3 empty pots drawn in plan ~0.2-1.0 m from the centreline, i.e. not on line B |
| AS-B08 | B | on line | concrete block | 0.5x0.5x0.2 | 1 | 11.00 | 2.40 | figure | 4.6 / 4.5 (83) |  |
| AS-B09 | B | between centreline and line | asphalt block | 0.5x1.0x0.2 | 1 | 12.00 | 2.40 | figure | 4.6 / 4.5 (83) | drawn in plan ~0.1-1.0 m from the centreline |
| AS-B10 | B | spans line | loosened ground zone | 6.0x2.8x1.0 | 1 | 13.0–19.0 | 1.00 | table | 4.6 / 4.5 (83) | contains AS-B11..AS-B14 and 5 moisture sensors (instrumentation, not in Table 4.6) |
| AS-B11 | B | on line | earthenware water | D0.4 | 2 | 14.00 | 2.05 | figure | 4.6 / 4.5 (83) |  |
| AS-B12 | B | between centreline and line | earthenware air | D0.4 | 3 | 15.00 | 2.05 | figure | 4.6 / 4.5 (83) | drawn in plan ~0.2-1.0 m from the centreline |
| AS-B13 | B | on line | concrete block | 0.5x0.5x0.2 | 1 | 17.00 | 2.00 | figure | 4.6 / 4.5 (83) |  |
| AS-B14 | B | between centreline and line | asphalt block | 0.5x1.0x0.2 | 1 | 17.95 | 2.00 | figure | 4.6 / 4.5 (83) | drawn in plan ~0.1-1.0 m from the centreline |
| AS-B15 | B | on line | plastic container water | 0.5x0.5x0.1 | 1 | 20.05 | 1.10 | figure | 4.6 / 4.5 (83) | five 4 L water bottles |
| AS-B16 | B | between centreline and line | plastic container air | 0.5x1.0x0.1 | 1 | 21.00 | 1.00 | table | 4.6 / 4.5 (83) | nine empty 4 L bottles; drawn in plan ~0.1-1.0 m from the centreline |
| AS-B17 | B | on line | concrete block | 0.5x0.5x0.1 | 1 | 23.05 | 1.00 | figure | 4.6 / 4.5 (83) |  |
| AS-B18 | B | between centreline and line | asphalt block | 0.5x1.0x0.1 | 1 | 24.00 | 1.00 | table | 4.6 / 4.5 (83) | drawn in plan ~0.1-1.0 m from the centreline |
| AS-B19 | B | spans line | loosened ground zone | 5.0x1.8x1.0 | 1 | 25.0–30.0 | 2.00 | table | 4.6 / 4.5 (83) | sand mixed with styrofoam particles |
| AS-B20 | B | on line | plastic container water | 0.5x0.5x0.1 | 1 | 26.00 | 0.40 | figure | 4.6 / 4.5 (83) | five 4 L water bottles |
| AS-B21 | B | on line | plastic container air | 0.5x0.5x0.1 | 1 | 27.00 | 0.27 | table | 4.6 / 4.5 (83) | five empty 4 L bottles |
| AS-B22 | B | on line | concrete block | 0.5x0.5x0.1 | 1 | 28.00 | 0.35 | figure | 4.6 / 4.5 (83) |  |
| AS-B23 | B | on line | asphalt block | 0.5x0.5x0.1 | 1 | 29.00 | 0.27 | table | 4.6 / 4.5 (83) |  |
| SL-A01 | A | on line | styrofoam hemisphere | D1.0 | 1 | 31.00 | 0.70 | figure | 4.7 / 4.7 (84/85) | approach-slab figure readings span only ~0.7-1.7 m against the table's 0.27-2.0 m |
| SL-A02 | A | on line | styrofoam hemisphere | D1.0 | 1 | 33.00 | 1.20 | figure | 4.7 / 4.7 (84/85) |  |
| SL-A03 | A | on line | styrofoam hemisphere | D1.0 | 1 | 35.25 | 0.70 | figure | 4.7 / 4.7 (84/85) | section reads 5.22 m, plan 5.33 m |
| SL-A04 | A | on line | styrofoam hemisphere | D1.0 | 1 | 38.00 | 1.20 | figure | 4.7 / 4.7 (84/85) | beneath the asphalt-side approach slab (6-15 m) |
| SL-A05 | A | on line | styrofoam hemisphere | D1.0 | 1 | 41.00 | 1.45 | figure | 4.7 / 4.7 (84/85) |  |
| SL-V01 | A | spans line | void | 1.0x1.8x0.5 | 1 | 44.10 | 1.00 | figure | 4.7 / 4.7 (84/85) | real void against the abutment, formed by removing square styrofoam after the slab was built (PDF p.85, printed p.63) |
| SL-A06 | A | on line | steel plate | 0.5x0.5x0.1 | 1 | 44.10 | 1.60 | figure | 4.7 / 4.7 (84/85) | locator plate inside void SL-V01; figure depth is outside the table's 0.3-1.0 m |
| SL-V02 | A | spans line | void | 1.0x1.8x0.5 | 1 | 46.10 | 0.55 | figure | 4.7 / 4.7 (84/85) | real void on the concrete side of the abutment |
| SL-A07 | A | on line | steel plate | 0.5x0.5x0.1 | 1 | 46.10 | 1.15 | figure | 4.7 / 4.7 (84/85) | locator plate inside void SL-V02; figure depth is outside the table's 0.3-1.0 m |
| SL-A08 | A | on line | styrofoam hemisphere | D1.0 | 1 | 49.05 | 1.70 | figure | 4.7 / 4.7 (84/85) |  |
| SL-A09 | A | on line | styrofoam hemisphere | D1.0 | 1 | 51.50 | 1.20 | figure | 4.7 / 4.7 (84/85) |  |
| SL-A10 | A | on line | styrofoam hemisphere | D1.0 | 1 | 54.00 | 0.70 | figure | 4.7 / 4.7 (84/85) |  |
| SL-A11 | A | on line | styrofoam hemisphere | D1.0 | 1 | 57.00 | 1.70 | figure | 4.7 / 4.7 (84/85) |  |
| SL-A12 | A | on line | styrofoam hemisphere | D1.0 | 1 | 59.10 | 0.70 | figure | 4.7 / 4.7 (84/85) |  |
| SL-B01 | B | on line | plastic container water | 1.0x1.0x0.1 | 1 | 31.00 | 1.00 | table | 4.7 / 4.7 (84/85) | fifteen 4 L water bottles |
| SL-B02 | B | on line | asphalt block | 1.0x1.0x0.1 | 1 | 32.50 | 1.00 | table | 4.7 / 4.7 (84/85) |  |
| SL-B03 | B | on line | rock | D0.6 | 1 | 32.50 | 2.05 | figure | 4.7 / 4.7 (84/85) | beneath SL-B02 |
| SL-B04 | B | on line | concrete block | 1.0x1.0x0.1 | 1 | 34.00 | 1.00 | table | 4.7 / 4.7 (84/85) |  |
| SL-B05 | B | on line | steel plate | 0.5x0.5x0.1 | 1 | 36.10 | 1.05 | figure | 4.7 / 4.7 (84/85) |  |
| SL-B06 | B | on line | steel plate | 0.5x0.5x0.1 | 1 | 37.00 | 0.55 | figure | 4.7 / 4.7 (84/85) | directly under the start of the asphalt-side approach slab |
| SL-B07 | B | spans line | loosened ground zone | 5.0x1.8x1.0 | 1 | 38.0–43.0 | 1.50 | table | 4.7 / 4.7 (84/85) | contains SL-B08..SL-B10 |
| SL-B08 | B | on line | plastic container water | 1.0x1.0x0.1 | 1 | 39.00 | 1.00 | table | 4.7 / 4.7 (84/85) | fifteen 4 L water bottles; figure reads 1.16 |
| SL-B09 | B | on line | asphalt block | 1.0x1.0x0.1 | 1 | 40.60 | 1.00 | table | 4.7 / 4.7 (84/85) | figure reads 1.16 |
| SL-B10 | B | on line | concrete block | 1.0x1.0x0.1 | 1 | 42.15 | 1.00 | table | 4.7 / 4.7 (84/85) | figure reads 1.16 |
| SL-B11 | B | spans line | loosened ground zone | 5.0x1.8x1.0 | 1 | 47.0–52.0 | 1.50 | table | 4.7 / 4.7 (84/85) | contains SL-B12..SL-B14 |
| SL-B12 | B | on line | plastic container water | 1.0x1.0x0.1 | 1 | 48.00 | 1.00 | table | 4.7 / 4.7 (84/85) | figure reads 1.16 |
| SL-B13 | B | on line | asphalt block | 1.0x1.0x0.1 | 1 | 49.60 | 1.00 | table | 4.7 / 4.7 (84/85) | figure reads 1.16 |
| SL-B14 | B | on line | concrete block | 1.0x1.0x0.1 | 1 | 51.15 | 1.00 | table | 4.7 / 4.7 (84/85) | figure reads 1.16 |
| SL-B15 | B | on line | steel plate | 0.5x0.5x0.1 | 1 | 53.20 | 0.55 | figure | 4.7 / 4.7 (84/85) |  |
| SL-B16 | B | on line | steel plate | 0.5x0.5x0.1 | 1 | 54.85 | 0.55 | figure | 4.7 / 4.7 (84/85) |  |
| SL-B17 | B | on line | plastic container water | 1.0x1.0x0.1 | 1 | 55.90 | 1.00 | table | 4.7 / 4.7 (84/85) |  |
| SL-B18 | B | on line | asphalt block | 1.0x1.0x0.1 | 1 | 57.50 | 1.00 | table | 4.7 / 4.7 (84/85) |  |
| SL-B19 | B | on line | rock | D0.6 | 1 | 57.50 | 2.05 | figure | 4.7 / 4.7 (84/85) | beneath SL-B18 |
| SL-B20 | B | on line | concrete block | 1.0x1.0x0.1 | 1 | 59.05 | 1.00 | table | 4.7 / 4.7 (84/85) |  |
| CO-A01 | A | on line | styrofoam hemisphere | D1.0 | 1 | 61.00 | 2.20 | figure | 4.8 / 4.10 (86/87) | Rhee 2021 Fig. 3 draws ~2.5 m |
| CO-A02 | A | on line | styrofoam hemisphere | D1.0 | 1 | 62.00 | 0.75 | figure | 4.8 / 4.10 (86/87) | Rhee 2021 Fig. 3 draws ~0.35 m |
| CO-A03 | A | on line | styrofoam hemisphere | D1.0 | 1 | 64.60 | 1.25 | figure | 4.8 / 4.10 (86/87) | on top of drain pipe CO-D01; Rhee 2021 puts it at 5.0 m |
| CO-A04 | A | outside line | styrofoam hemisphere | D0.5 | 1 | 65.45 | 2.00 | table | 4.8 / 4.10 (86/87) | drawn in plan ~0.45 m outside line A (≈1.95 m from the centreline); figure depth 2.15 |
| CO-A05 | A | on line | styrofoam hemisphere | D1.0 | 1 | 68.00 | 1.25 | figure | 4.8 / 4.10 (86/87) |  |
| CO-A06 | A | on line | styrofoam hemisphere | D1.0 | 1 | 71.05 | 1.75 | figure | 4.8 / 4.10 (86/87) |  |
| CO-A07 | A | on line | styrofoam hemisphere | D1.0 | 1 | 74.00 | 2.25 | figure | 4.8 / 4.10 (86/87) |  |
| CO-A08 | A | on line | styrofoam hemisphere | D1.0 | 1 | 76.05 | 2.25 | figure | 4.8 / 4.10 (86/87) | first object in the CRCP part (15-30 m) |
| CO-A09 | A | on line | styrofoam hemisphere | D1.0 | 1 | 79.05 | 1.70 | figure | 4.8 / 4.10 (86/87) |  |
| CO-A10 | A | on line | styrofoam hemisphere | D1.0 | 1 | 82.00 | 1.25 | figure | 4.8 / 4.10 (86/87) | labelled CP-B10 in Rhee 2021 Fig. 3 although it sits on line A |
| CO-A11 | A | outside line | styrofoam hemisphere | D0.5 | 1 | 84.35 | 2.00 | table | 4.8 / 4.10 (86/87) | drawn in plan ~0.4 m outside line A; figure depth 2.10 |
| CO-A12 | A | on line | styrofoam hemisphere | D1.0 | 1 | 85.05 | 1.25 | figure | 4.8 / 4.10 (86/87) | on top of drain pipe CO-D02 |
| CO-A13 | A | on line | styrofoam hemisphere | D1.0 | 1 | 88.00 | 0.75 | figure | 4.8 / 4.10 (86/87) | Rhee 2021 Fig. 3 draws ~0.35 m |
| CO-A14 | A | on line | styrofoam hemisphere | D1.0 | 1 | 89.05 | 2.75 | figure | 4.8 / 4.10 (86/87) | figure depth exceeds the table maximum of 2.5 m |
| CO-D01 | A;B | crosses both lines | transverse drain pipe | D0.9 | 1 | 64.60 | 1.50 | table | 4.8 / 4.10 (86/87) | Rhee 2021 Fig. 3 puts this pipe at 5.0 m |
| CO-D02 | A;B | crosses both lines | transverse drain pipe | D0.9 | 1 | 85.05 | 1.50 | table | 4.8 / 4.10 (86/87) |  |
| CO-B01 | B | on line | plastic container water | 0.5x0.5x0.1 | 1 | 61.00 | 0.50 | figure | 4.8 / 4.10 (86/87) | five 4 L water bottles |
| CO-B02 | B | between centreline and line | plastic container air | 0.5x1.0x0.1 | 1 | 62.00 | 0.50 | figure | 4.8 / 4.10 (86/87) | nine empty 4 L bottles; drawn in plan ~0-1.0 m from the centreline |
| CO-B03 | B | on line | rock | D0.6 | 1 | 62.00 | 2.00 | table | 4.8 / 4.10 (86/87) |  |
| CO-B04 | B | on line | asphalt block | 0.5x0.5x0.1 | 1 | 63.00 | 0.50 | figure | 4.8 / 4.10 (86/87) |  |
| CO-B05 | B | on line | plastic container water | 0.5x0.5x0.1 | 1 | 67.00 | 0.90 | figure | 4.8 / 4.10 (86/87) | five 4 L water bottles |
| CO-B06 | B | between centreline and line | plastic container air | 0.5x1.0x0.1 | 1 | 68.00 | 0.90 | figure | 4.8 / 4.10 (86/87) | drawn in plan ~0-1.0 m from the centreline |
| CO-B07 | B | on line | asphalt block | 0.5x0.5x0.1 | 1 | 69.00 | 0.90 | figure | 4.8 / 4.10 (86/87) |  |
| CO-B08 | B | spans line | loosened ground zone | 5.0x2.8x0.5 | 1 | 70.0–75.0 | 0.45 | table | 4.8 / 4.10 (86/87) | Fig. 4.10 labels it 5.0x2.8x1.0 and draws ~1.0 m thick; contains CO-B09..CO-B12 |
| CO-B09 | B | on line | earthenware water | D0.4 | 2 | 71.00 | 2.00 | table | 4.8 / 4.10 (86/87) |  |
| CO-B10 | B | between centreline and line | styrofoam block | 0.5x1.0x0.2 | 1 | 72.00 | 2.00 | table | 4.8 / 4.10 (86/87) | drawn in plan ~0-1.0 m from the centreline |
| CO-B11 | B | on line | concrete block | 0.5x0.5x0.2 | 1 | 73.00 | 2.00 | table | 4.8 / 4.10 (86/87) |  |
| CO-B12 | B | between centreline and line | asphalt block | 0.5x1.0x0.2 | 1 | 74.00 | 2.00 | table | 4.8 / 4.10 (86/87) | drawn in plan ~0-1.0 m from the centreline |
| CO-B13 | B | spans line | loosened ground zone | 5.0x2.8x0.5 | 1 | 75.0–80.0 | 0.45 | table | 4.8 / 4.10 (86/87) | contains CO-B14..CO-B17 |
| CO-B14 | B | on line | earthenware water | D0.4 | 2 | 76.00 | 2.00 | table | 4.8 / 4.10 (86/87) |  |
| CO-B15 | B | between centreline and line | styrofoam block | 0.5x1.0x0.2 | 1 | 77.00 | 2.00 | table | 4.8 / 4.10 (86/87) | drawn in plan ~0-1.0 m from the centreline |
| CO-B16 | B | on line | concrete block | 0.5x0.5x0.2 | 1 | 78.00 | 2.00 | table | 4.8 / 4.10 (86/87) |  |
| CO-B17 | B | between centreline and line | asphalt block | 0.5x1.0x0.2 | 1 | 79.00 | 2.00 | table | 4.8 / 4.10 (86/87) | drawn in plan ~0-1.0 m from the centreline |
| CO-B18 | B | on line | plastic container water | 0.5x0.5x0.1 | 1 | 81.00 | 0.90 | figure | 4.8 / 4.10 (86/87) |  |
| CO-B19 | B | between centreline and line | plastic container air | 0.5x1.0x0.1 | 1 | 82.00 | 0.90 | figure | 4.8 / 4.10 (86/87) | drawn in plan ~0-1.0 m from the centreline |
| CO-B20 | B | on line | asphalt block | 0.5x0.5x0.1 | 1 | 83.00 | 0.90 | figure | 4.8 / 4.10 (86/87) |  |
| CO-B21 | B | spans line | plastic container water | 0.5x1.0x0.1 | 1 | 87.05 | 0.45 | table | 4.8 / 4.10 (86/87) | drawn in plan ~0.9-1.9 m from the centreline, across line B |
| CO-B22 | B | between centreline and line | plastic container air | 0.5x1.0x0.1 | 1 | 88.00 | 0.50 | figure | 4.8 / 4.10 (86/87) | drawn in plan ~0-1.0 m from the centreline |
| CO-B23 | B | spans line | asphalt block | 0.5x1.0x0.1 | 1 | 89.00 | 0.45 | table | 4.8 / 4.10 (86/87) | drawn in plan ~0.9-1.9 m from the centreline, across line B |
| CO-B24 | B | on line | steel plate | 0.5x0.5x0.1 | 1 | 89.5–90.0 | 0.45 | table | 4.8 / 4.10 (86/87) | installed at the end of the concrete section to mark the survey point (PDF p.86, printed p.64) |

### A.3 KEC vs Rhee 2021 Figure 3

Positions are within the section (m); depths are the drawn top edge below the surface (m), both read from the figures. Agreement = both differences ≤ 0.15 m.

| Object | Rhee ID | KEC position | Rhee position | KEC depth | Rhee depth | Agreement | Notes |
|---|---|---|---|---|---|---|---|
| AS-A01 styrofoam D0.5 | AP-A01 | 2.00 | 1.98 | 0.34 | 0.35 | agree | KEC text cites 0.27 m for a cavity model directly beneath the pavement |
| AS-A02 styrofoam D0.5 over drain | AP-A02 | 5.00 | 5.01 | 0.80 | 0.89 | agree | KEC text states 0.77 m |
| AS-A03 styrofoam D0.5 | AP-A03 | 8.00 | 8.00 | 0.98 | 1.01 | agree |  |
| AS-A04 styrofoam D0.5 | AP-A04 | 11.00 | 10.99 | 1.57 | 1.53 | agree |  |
| AS-A05 styrofoam D0.5 | AP-A05 | 14.00 | 14.00 | 2.06 | 2.03 | agree |  |
| AS-A06 styrofoam D1.0 | AP-A06 | 17.00 | 16.99 | 3.04 | 3.03 | agree |  |
| AS-A07 styrofoam D1.0 | AP-A07 | 20.00 | 20.01 | 2.70 | 2.52 | **DISAGREE** depth |  |
| AS-A08 styrofoam D1.0 | AP-A08 | 23.03 | 23.00 | 2.00 | 2.02 | agree |  |
| AS-A09 styrofoam D1.0 | AP-A09 | 26.06 | 25.99 | 1.54 | 1.52 | agree |  |
| AS-A10 styrofoam D1.0 | AP-A10 | 29.02 | 29.01 | 0.38 | 0.35 | agree |  |
| AS-D01 transverse drain pipe (box top) | AP-B04† | 5.00 | 5.00 | 1.05 | 1.05 | agree | Rhee group label AP-B03,04,05 |
| AS-B01 steel plate (start marker) | AP-B01† | 0.26 | 0.46 | — | 0.32 | **DISAGREE** position (depth not comparable: not drawn in KEC section) | KEC draws the plate in plan only (0.02-0.49 m); Rhee draws it at 0.21-0.71 m |
| AS-B02 loosened zone 2.0x1.8 | — | 2.00 | 2.01 | 0.31 | 0.33 | agree | extents: KEC 1.0-3.0 m, Rhee 1.02-3.00 m |
| AS-B03 rock D0.6 | AP-B02† | 1.98 | 1.98 | 2.02 | 2.02 | agree |  |
| AS-B04 styrofoam D0.5 (line B) | AP-B03† | 4.25 | 4.30 | 1.74 | 1.70 | agree |  |
| AS-B05 styrofoam D0.5 (line B) | AP-B05† | 5.76 | 5.71 | 1.10 | 1.09 | agree |  |
| AS-B06 earthenware, water | AP-B06† | 7.97 | 7.98 | 2.36 | 2.40 | agree |  |
| AS-B07 earthenware, empty | AP-B07† | 9.01 | 8.97 | 2.36 | 2.42 | agree |  |
| AS-B08 concrete block | AP-B08† | 11.00 | 10.95 | 2.40 | 2.45 | agree |  |
| AS-B09 asphalt block | AP-B09† | 12.02 | 11.98 | 2.40 | 2.45 | agree |  |
| AS-B10 loosened zone 6.0x2.8 | — | 16.00 | 15.99 | 0.90 | 0.90 | agree | extents: KEC 13.0-19.0 m, Rhee 12.99-18.98 m |
| AS-B11 earthenware, water | AP-B10† | 14.02 | 13.97 | 2.05 | 1.97 | agree |  |
| AS-B12 earthenware, empty | AP-B11† | 15.02 | 15.01 | 2.05 | 1.97 | agree |  |
| AS-B13 concrete block | AP-B12† | 16.98 | 16.99 | 2.00 | 1.97 | agree |  |
| AS-B14 asphalt block | AP-B13† | 17.95 | 18.01 | 2.00 | 1.97 | agree |  |
| AS-B15 plastic container, water | AP-B14† | 20.06 | 19.94 | 1.09 | 1.06 | agree |  |
| AS-B16 plastic container, empty | AP-B15† | 20.98 | 20.94 | 1.05 | 1.06 | agree |  |
| AS-B17 concrete block | AP-B16† | 23.04 | 22.98 | 1.02 | 1.06 | agree |  |
| AS-B18 asphalt block | AP-B17† | 23.99 | 23.98 | 1.02 | 1.06 | agree |  |
| AS-B19 loosened zone 5.0x1.8 | — | 27.50 | 27.53 | 2.00 | 2.01 | agree | extents: KEC 25.0-30.0 m, Rhee 25.02-30.04 m |
| AS-B20 plastic container, water | AP-B18† | 26.01 | 26.04 | 0.41 | 0.36 | agree |  |
| AS-B21 plastic container, empty | AP-B19† | 26.98 | 27.03 | 0.41 | 0.36 | agree |  |
| AS-B22 concrete block | AP-B20† | 28.01 | 28.03 | 0.33 | 0.36 | agree |  |
| AS-B23 asphalt block | AP-B21† | 29.00 | 29.04 | 0.36 | 0.36 | agree |  |
| CO-A01 styrofoam D1.0 | CP-A01† | 0.99 | 1.00 | 2.21 | 2.49 | **DISAGREE** depth | Rhee group label CP-A01,02 |
| CO-A02 styrofoam D1.0 | CP-A02† | 2.04 | 1.98 | 0.73 | 0.34 | **DISAGREE** depth | Rhee's 0.34 m is shallower than the 0.45 m concrete pavement structure |
| CO-A03 styrofoam D1.0 over drain | CP-A03† | 4.59 | 4.98 | 1.25 | 1.19 | **DISAGREE** position | Rhee group label CP-A03,04 |
| CO-A04 styrofoam D0.5 (off line A) | CP-A04† | 5.43 | 5.71 | 2.16 | 2.03 | **DISAGREE** position |  |
| CO-A05 styrofoam D1.0 | CP-A05 | 8.03 | 7.97 | 1.23 | 1.03 | **DISAGREE** depth |  |
| CO-A06 styrofoam D1.0 | CP-A06 | 11.04 | 10.96 | 1.75 | 1.50 | **DISAGREE** depth |  |
| CO-A07 styrofoam D1.0 | CP-A07 | 14.02 | 13.95 | 2.26 | 2.03 | **DISAGREE** depth |  |
| CO-A08 styrofoam D1.0 | CP-A08 | 16.03 | 15.96 | 2.26 | 2.01 | **DISAGREE** depth |  |
| CO-A09 styrofoam D1.0 | CP-A09 | 19.03 | 18.99 | 1.72 | 1.51 | **DISAGREE** depth |  |
| CO-A10 styrofoam D1.0 | CP-B10 | 21.99 | 21.98 | 1.25 | 1.02 | **DISAGREE** depth | Rhee labels this line-A object 'CP-B10'; by sequence it would be CP-A10 |
| CO-A11 styrofoam D0.5 (off line A) | CP-A11† | 24.35 | 24.23 | 2.09 | 2.09 | agree | Rhee group label CP-A11,12 |
| CO-A12 styrofoam D1.0 over drain | CP-A12† | 25.03 | 24.97 | 1.23 | 1.22 | agree |  |
| CO-A13 styrofoam D1.0 | CP-A13† | 27.98 | 27.89 | 0.75 | 0.34 | **DISAGREE** depth | Rhee group label CP-A13,14; Rhee's 0.34 m is shallower than the 0.45 m pavement structure |
| CO-A14 styrofoam D1.0 | CP-A14† | 29.05 | 28.88 | 2.74 | 2.52 | **DISAGREE** position + depth |  |
| CO-D01 transverse drain pipe (box top) | CP-B04 | 4.60 | 4.99 | 1.54 | 1.45 | **DISAGREE** position |  |
| CO-D02 transverse drain pipe (box top) | CP-B19 | 25.04 | 24.90 | 1.51 | 1.48 | agree |  |
| CO-B01 plastic container, water | (group CP-B01–03) | 1.00 | 0.96 | 0.51 | 0.34 | **DISAGREE** depth | Rhee group label CP-B01,02,03 covers 4 drawn objects |
| CO-B02 plastic container, empty | (group CP-B01–03) | 2.00 | 1.97 | 0.51 | 0.34 | **DISAGREE** depth |  |
| CO-B03 rock D0.6 | (group CP-B01–03) | 1.98 | 1.98 | 1.98 | 2.03 | agree |  |
| CO-B04 asphalt block | (group CP-B01–03) | 3.00 | 2.98 | 0.51 | 0.34 | **DISAGREE** depth |  |
| CO-B05 plastic container, water | CP-B05† | 7.00 | 6.98 | 0.90 | 0.95 | agree | Rhee group label CP-B05,06,07 |
| CO-B06 plastic container, empty | CP-B06† | 8.00 | 7.97 | 0.90 | 0.95 | agree |  |
| CO-B07 asphalt block | CP-B07† | 9.00 | 8.94 | 0.90 | 0.95 | agree |  |
| CO-B08 loosened zone 5.0x2.8 | — | 12.50 | 12.49 | 0.51 | 0.34 | **DISAGREE** depth | extents: KEC 10.0-15.0 m, Rhee 10.0-14.97 m |
| CO-B09 earthenware, water (x2) | CP-B08† | 11.00 | 10.96 | 2.05 | 1.98 | agree | Rhee group label CP-B08,09,10,11 |
| CO-B10 styrofoam block | CP-B09† | 12.00 | 11.93 | 2.05 | 1.98 | agree | Rhee symbol: white dotted rectangle; legend class not resolved at this resolution |
| CO-B11 concrete block | CP-B10† | 13.00 | 12.92 | 2.05 | 1.98 | agree |  |
| CO-B12 asphalt block | CP-B11† | 14.00 | 13.92 | 2.05 | 1.98 | agree |  |
| CO-B13 loosened zone 5.0x2.8 | — | 17.50 | 17.45 | 0.51 | 0.34 | **DISAGREE** depth | extents: KEC 15.0-20.0 m, Rhee 15.0-19.91 m |
| CO-B14 earthenware, water (x2) | CP-B12† | 15.95 | 15.90 | 2.05 | 1.98 | agree | Rhee group label CP-B12,13,14,15 |
| CO-B15 styrofoam block | CP-B13† | 17.00 | 16.91 | 2.05 | 1.98 | agree |  |
| CO-B16 concrete block | CP-B14† | 18.00 | 17.90 | 2.05 | 1.98 | agree |  |
| CO-B17 asphalt block | CP-B15† | 19.00 | 18.90 | 2.05 | 1.98 | agree |  |
| CO-B18 plastic container, water | CP-B16† | 21.00 | 20.90 | 0.90 | 1.06 | **DISAGREE** depth | Rhee group label CP-B16,17,18 |
| CO-B19 plastic container, empty | CP-B17† | 22.00 | 21.89 | 0.90 | 1.06 | **DISAGREE** depth |  |
| CO-B20 asphalt block | CP-B18† | 23.00 | 22.92 | 0.90 | 1.06 | **DISAGREE** depth |  |
| CO-B21 plastic container, water | CP-B20† | 27.05 | 26.89 | 0.51 | 0.38 | **DISAGREE** position | Rhee group label CP-B20,21,22,23 |
| CO-B22 plastic container, empty | CP-B21† | 28.00 | 27.89 | 0.51 | 0.38 | agree |  |
| CO-B23 asphalt block | CP-B22† | 29.00 | 28.84 | 0.51 | 0.38 | **DISAGREE** position |  |
| CO-B24 steel plate (end marker) | CP-B23† | 29.74 | 29.40 | 0.51 | 0.39 | **DISAGREE** position | KEC 29.5-30.0 m; Rhee 29.15-29.66 m |

† Rhee labels some objects as a group (e.g. AP-B03,04,05); the individual ID is assigned by left-to-right order within the group, which is an inference.
