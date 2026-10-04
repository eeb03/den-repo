# Yesan full-scale test site: target registration investigation

**Date:** 2026-09-29 · **Dataset:** Zenodo [10.5281/zenodo.21441974](https://doi.org/10.5281/zenodo.21441974) (CC-BY-4.0, v1.0.0, published 2026-07-19) · **Manifest:** `benchmark/manifests/yesan-fullscale.targets.json`

**Verdict: BLOCKED (partially characterised).** No target list exists in any public or held
source, and the physical meaning of `0 m` is unproven. The manifest stays `not_scoring_ready`.
No detector was run against Yesan, and no Yesan target position was used to tune anything.

The sections below keep four kinds of statement apart: **Verified** (read directly from a raw
file or a published record), **Inferred** (a reasoned interpretation, not proven), **Unresolved**
(blocks scoring), and **Author confirmation required**.

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

**Verified:** `POSITIVE DIRECTION -1` in every file (an instrument setting; it does not give a
compass direction). **Inferred:** both lines run the same way — B shows the ~73–74 m and ~44–45 m
changes near the same distances as A, where a reversed run would mirror the 74 m change to
~16 m; `ascon_B_0–5 m` in the QDM data also places B's start on asphalt. Physical start/end
(which end is the bridge) is **not** documented.

## 9. Target list, completeness and evidence grade

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

## 10. Benchmark gates today

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

Asked in the draft below — each is a question no public source answers:
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
