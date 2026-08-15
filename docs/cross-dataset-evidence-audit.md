# Cross-dataset evidence audit

**Question.** Across everything Subterra holds, what evidence could actually
resolve propagation velocity, time-zero, physical depth, surveyed surface
elevation, vertical datum, and independently attested subsurface geometry —
and what is the fastest defensible route to running the whole chain:

```
measured two-way time -> time-zero correction -> propagation velocity
    -> physical depth -> surface elevation -> absolute subsurface elevation
```

**No platform state was changed.** No declaration, readiness state, converter,
dataset record or schema was touched. This audit reads files and publications.

**Headline: no single held dataset can complete the chain.** Two datasets can
complete it as far as *physical depth* against surveyed truth. One dataset can
carry the *geodetic tail*. They are different datasets, and the numbers do not
cross between them.

---

## 1. What changed in the picture

Three things this audit established that the existing inventory did not record:

1. **The 4TU trial-trench ground truth contains depths.** All 125 activities
   ship a `ground-truth.png` carrying a table of *distance along trench* /
   *depth in metres* / *discipline*, and some annotate a groundwater level. The
   inventory recorded only that the truth "carries no coordinates" — true of
   coordinates, but the depths are there.
2. **The TU1208 / IFSTTAR target inventory is published and open.** The
   inventory recorded it as unverified behind bot protection. The paper is
   retrievable, and it gives theodolite-surveyed target depths, target offsets,
   acquisition-line offsets, and a file-name → line table that matches the 67
   files on disk exactly. **This is the best subsurface truth Subterra holds
   for soil.**
3. **BAM's `Z-values` are nanoseconds, not depth.** The publisher did *not*
   convert to depth, so BAM is a genuine time-axis dataset with attested depth
   truth — not a pre-converted product.

---

## 2. Per-dataset evidence table

Evidence type vocabulary: **measured** (an instrument recorded it) ·
**surveyed** (an independent survey instrument recorded it) · **attested**
(the fabricator/excavator states it) · **declared** (the publisher states a
value without a stated method) · **modelled** (obtained by fitting a numerical
model) · **absent**.

### 2.1 `tu1208-ifsttar` — IFSTTAR geophysical test site

| Evidence source | Quantity | Value / range | Type | Independently verifiable | Unlocks | Limitations |
|---|---|---|---|---|---|---|
| Paper Figs 6, 9, 11, 13 (transversal sections) | subsurface target depth | silt pipes **−0.80 / −1.20 / −1.83 m**; limestone pipes **−1.20 / −1.70 / −2.40 m**; gneiss 14/20 pipes **−0.90 / −1.50 / −2.10 m**; polystyrene staircase **−0.66 → −2.05 m**; blocks −1.0/−1.5/−2.0; cavity −3.47; big blocks −1.46/−3.10 | **surveyed** (theodolite, §3.4) | Yes — open-access publication, DOI 10.3390/rs10040530 | time-zero **and** velocity, jointly | Numbers are printed in **figures**, so they need transcription. Depth reference is the interpolated surface; §3.4 says pipes were positioned from "2 points on the upper side", so pipe depths are most likely to the **crown**, not the centre — the paper does not say so in words |
| Paper §3.4 | how targets were located | theodolite; 2 points per pipe, 4 per polystyrene block, 3–20 per rock block; surface georeferenced on the axis and sides per section | **surveyed** | Yes | positional provenance of the truth | "Georeferenced" is not qualified with a CRS or datum |
| Paper §4, file nomenclature | profile → acquisition line | line 1 = **1.25 m**, 2 = **3.75 m**, 3 = **6.25 m**, 4 = **8.75 m** from the upstream section border; line number encoded in every filename | **declared** | Yes — the 67 filenames on disk match the published nomenclature exactly | horizontal registration of a profile against the target sections | Only the transverse offset; the along-line origin still has to come from the file |
| Paper Tables 3–7 | trace count, profile length, scans/m per file | e.g. `400MHz_Silt_1_rev.dzt` 1321 traces / 20.02 m / 66 scans per m | **declared** | Yes | along-track metric scale | Profile length is **NA** for several files; those cannot be metrically scaled from the paper |
| Paper §5 (FDTD model matching) | relative permittivity per region | silt **≈13**, limestone **≈6**, gneiss 14/20 **≈3**, gneiss 0/20 **≈5.5** | **modelled** | Yes, but it is a model result | an *independent cross-check* on a fitted velocity | The authors themselves write these "must be taken with care" and cite surface-layer thickness variation and block compaction. **Not a measurement of velocity** |
| File headers (on disk) | time axis | ranges 60–116 ns; 413–1024 samples | **measured** | Yes | the time half of the chain | — |
| — | surface elevation, vertical datum, CRS | **absent** | absent | — | — | The chain **cannot** reach absolute subsurface elevation here |

### 2.2 `bam-concrete-gpr` — BAM concrete step specimens

| Evidence source | Quantity | Value / range | Type | Independently verifiable | Unlocks | Limitations |
|---|---|---|---|---|---|---|
| Dataverse description, already transcribed to `benchmark/bam_pk266_targets.json` | duct centre depth | **274.5 / 214.6 / 151.4 / 94.4 mm** at X = 250/750/1250/1750 mm | **attested** by the fabricator | Yes — CC0 record + `10.1016/j.dib.2023.109312` Table 4 | time-zero **and** velocity, jointly | Concrete, not soil. Open question already recorded: centre − cover = exactly 30.0 mm (inner radius) not 33.5 mm (outer), so the two published sources use different reference surfaces — **3.5 mm unresolved** |
| Same | step thicknesses (back-wall depths) | Pk266 **569.9 / 448.2 / 329.8 / 210.3 mm**; Pk050 **571.3 / 452.0 / 330.9 / 210.8 mm** | **attested** | Yes | four more attested reflector depths per specimen | Back-wall echo identity still has to be established in the data |
| Same | **negative control** | "Specimen Pk050 does not contain any embedded elements" | **attested absence** | Yes | false-alarm control | Not a control for "no reflector" — the step back walls are real |
| `Z-values.csv` / `.npy` in the archive | time axis | **0 → 15.0 ns**, 512 samples, Δt **0.029354207436399216 ns** | **measured** | Yes | the time half of the chain | — |
| `.DZT` header (read here) | `rhf_range` | **15.0 ns** — agrees with `Z-values` | **measured** | Yes | corroborates the axis | — |
| `.DZT` header | `rhf_position` (time-zero) | **0.0 ns** | **absent in practice** | Yes | nothing | 0.0 means unset; the converter already refuses to apply it. **BAM attests no time zero** |
| `.DZT` header | `rhf_epsr` | **5.5** | **declared** (operator display setting) | Yes | nothing | The converter already records `epsr_not_used_for_velocity`. The same header's text field says `2.6GHz` in a **1.5 GHz** file — the operator fields are unreliable |
| `X/Y-values.npy` | scanner grid | 0–2000 mm and 0–800 mm, uniform 5 mm | **measured** | Yes | trace ↔ target association without any transformation | — |
| — | surface elevation, vertical datum, CRS | **absent by design** — Z = 0 is the specimen's measuring surface | — | — | — | No absolute elevation exists or is implied |

### 2.3 `4tu-nl-utility`

| Evidence source | Quantity | Value / range | Type | Independently verifiable | Unlocks | Limitations |
|---|---|---|---|---|---|---|
| `ground-truth.png` ×125 | excavated utility depth + distance along trench | e.g. 01.1 — 7 utilities at 0.80–4.80 m, depths **0.40–1.40 m**; 010.12 — 14 utilities at 0.23–1.77 m, depths **0.30–0.76 m** | **attested** (trial trench) | Yes — published with the dataset | physical-depth validation **on this dataset** | **Images, not data** — needs transcription. Depth reference (crown vs centre) is defined nowhere: not in the Readme, not in the Codebook |
| `ground-truth.png` (some) | groundwater depth | e.g. 010.12 "Groundwater level: 0.85 below surface" | **attested** | Yes | a *laterally continuous* attested reflector — better suited to a velocity fit than a pipe | Present on some activities only; the count is not yet measured |
| `Metadata.csv` | ground relative permittivity, per activity | **8.16 – 19.46**, 10 distinct values, mode 9.00, all 125 populated | **declared** (Codebook says only "the relative permittivity of the subsurface soil") | Yes | the **only 4TU-specific velocity input that exists** | No method, no instrument, no uncertainty. ε=9.00 → v≈0.0999 m/ns, but that is arithmetic on a declared number, not a measurement |
| SEG-Y trace headers | time axis | 512 samples; sample-interval field 97 ps (×96 of 108 sampled) / 195 ps (×12) → ~49.7 and ~99.8 ns windows | **measured** | Yes | the time half of the chain | The Readme's "50 ns" is the majority case, not universal |
| SEG-Y `DelayRecordingTime` | recording delay | 293–11154 raw → **0.3–11 ns**; constant within a file (checked over 40 traces × 108 files: **0 files vary**), varies between files | **measured** | Yes | nothing on its own | This is when **recording started**, not where the ground is. It is **not** an air-gap or time-zero-to-surface offset, and must not be used as one |
| SEG-Y bytes 45–48 + Stage 21 declaration | acquisition elevation + vertical datum | WGS84 ellipsoidal, per trace | **measured** (elevation) + **declared** (datum, Dr. ter Huurne) | Yes | surface elevation and the vertical datum links | `verified=False`. Bytes 41–44 remain an orthometric NAP-**like** field no author has confirmed |
| `ahn-dtm-05m` (separate dataset) | independent surface elevation | 27.374–32.549 m NAP over 4TU project 01 | **measured** | Yes — PDOK | corroboration of the surface elevation | Project 01 only; NAP is PDOK documentation, not in the GeoTIFF |
| `survey_map.png` | trench ↔ survey-line relationship | hand-drawn arrows, "Orientation of trial trench" | **absent as a measurement** | — | — | **The blocking gap.** No scale, no origin, no metric tie. Trench distance cannot be converted to a trace index |

### 2.4 `hillside-lancaster`

| Evidence source | Quantity | Value / range | Type | Independently verifiable | Unlocks | Limitations |
|---|---|---|---|---|---|---|
| Description PDF | plot corner coordinates | 24 points, British National Grid E/N, e.g. HA(1) 347289.47 / 461931.93 | **surveyed** | Yes | horizontal registration in EPSG:27700 | Corners only; per-trace `.cor` GNSS files are all 0 bytes |
| Same | corner **elevation** | **29.54 – 32.09 m aOD** across 24 points | **surveyed** | Yes | surface elevation with a **named vertical datum (ODN)** | Four points per plot, not a surface model |
| `.rad` headers | time axis | 22.17–78.63 ns, 336 samples | **measured** | Yes | the time half | — |
| — | velocity, time-zero, subsurface truth | **absent** | absent | — | — | No site velocity in `.rad`; depth stays `None` by design. **No attested target of any kind** |

### 2.5 Everything else held

| Dataset | What it offers for these six quantities | Verdict |
|---|---|---|
| `guangzhou-ids` | odometry only; no coordinates, no truth, no velocity | **Nothing.** Format regression only |
| `ingv-unisa` | pinned regression baseline; SEG-Y projected positions | **Nothing.** No ground truth; licence unverified |
| `ahn-dtm-05m` | EPSG:28992 declared; NAP by PDOK documentation; 27.374–32.549 m | **Surface elevation only** — the geodetic partner for 4TU project 01 |
| `zenodo/16910346` (Bodoc, Romania) + `gpr_normalized.csv` | a **depth slice at 0.1–0.2 m**, already converted by EKKO Project; `depth` column is a constant 0.15 | **Actively a trap.** The conversion was done upstream and the **velocity is not published**. A `depth` column here is a label, not a measurement |
| `COP30_45.964_25.87…tif` | 14×14 px DEM over the Bodoc site, EPSG:4326, no vertical datum in the file | Surface elevation for a dataset that has no time axis left |

---

## 3. The three distinctions the brief asked for

**(a) Evidence that applies to its own dataset.** TU1208's surveyed target
depths; BAM's attested duct and step depths; 4TU's trench depths, permittivity
and GNSS elevations; hillside's surveyed corner elevations. Each is evidence
about the ground or specimen it was recorded on, and nowhere else.

**(b) Evidence that can validate Subterra's conversion machinery.** Only
where an attested depth sits under a measured time axis in the same frame:
**TU1208 and BAM**. These test whether the code — time axis → time-zero
correction → velocity → depth → local Z — recovers a number somebody
independently surveyed. That is a test of the *machinery*, and its result is
transferable; the velocity it fits is not.

**(c) Evidence that transfers to another dataset.** **Almost none, and none of
it numeric.** What transfers is *method and code*: a fitting procedure
validated on TU1208 is a validated procedure everywhere. What does not
transfer is every value — velocity, permittivity, time-zero, air-gap. TU1208
itself demonstrates why: the *same* pipes in silt, limestone and gneiss sit at
different depths and the authors attribute the differing travel times to
differing velocity, with modelled permittivities from 3 to 13. A single site
spans a factor of ~2 in velocity. **No BAM or TU1208 number may be used as a
4TU value**, and this audit proposes none.

---

## 4. Route assessment

### Route A — TU1208 / IFSTTAR ✅ **recommended first**

Runs: measured time → time-zero → velocity → physical depth, against
**theodolite-surveyed** truth, in **soil**, with **three host materials**.

Why it is the fastest defensible route:

- **Nine pipe depths across three media** (three per medium), plus voids,
  blocks and a cavity. Three depths in one medium make `t = t0 + 2d/v`
  **over-determined** — two unknowns, three or more observations — so the fit
  produces residuals, and residuals are what makes it a test rather than an
  assertion.
- **The association is published, not visual.** Target offsets are printed in
  the section figures, acquisition-line offsets are published (1.25/3.75/6.25/
  8.75 m), and the line is encoded in every filename. Which reflector is which
  target is answered by the survey, not by what looks plausible.
- **Independent cross-check.** The authors' FDTD-matched permittivities give an
  expected velocity per region. Agreement is corroboration; disagreement is a
  finding. Either way the check is external.
- **Zero ingestion work.** 67/67 files already read, three vendors.
- **It refutes velocity transfer with data**, by fitting different velocities
  in different media on one site.

Cost: transcribe four figures and five tables into a `benchmark/` truth file
with `provenance_class: transcribed_from_publication`, exactly as
`bam_pk266_targets.json` already does.

**Ends at physical depth.** No CRS, no vertical datum, no absolute surface
elevation. The last two links cannot run here, and no amount of work on this
dataset will change that.

### Route B — BAM concrete ✅ **cheapest, weakest transfer**

Truth is **already transcribed** and in the repository, so this is the least
new work of any route. Four attested duct depths plus four attested step
thicknesses per specimen, and a genuine attested negative control.

But: concrete, not soil; a 15 ns window; and the repository's own inventory
already says results here "must not be reported as if they transfer" to the
4TU corpus. Best used as a **unit test of the machinery**, not as the
headline demonstration. Note also that `rhf_position = 0.0` means BAM attests
**no** time zero — t0 must be solved, and the 3.5 mm cover-vs-centre question
stays open.

### Route C — 4TU ⚠️ **the only route to the geodetic tail, and it is blocked**

4TU is the only dataset that holds both halves: excavated depths *and*
GNSS-surveyed elevations with a declared datum. Three things block it:

1. **Registration.** Trench distance → trace index has no metric tie. The only
   artefact relating them is a hand-drawn map with no scale. The trench appears
   to run roughly parallel to the survey lines, so this may reduce to a
   one-dimensional offset rather than a full 2-D registration — but that is a
   **hypothesis to be tested by residual**, not a fact, and it is the single
   largest piece of work.
2. **No measured velocity.** Only a provider-declared permittivity per activity
   with no stated method. Usable as a declared input; not a measurement.
3. **No time-zero.** `DelayRecordingTime` is a recording delay, not a
   ground-surface offset, and the author has confirmed no time-zero correction
   or air-gap removal was applied.

Transcribing the 125 ground-truth tables is worth doing regardless — it is the
only excavated truth Subterra holds — but it does not on its own unblock (1).

### What no held dataset can do

**Absolute subsurface elevation in a geodetic datum.** It needs surveyed
surface elevation *and* a vertical datum *and* an attested subsurface depth
*and* a defensible velocity, all on the same ground. The holdings split
exactly across that line:

| | attested subsurface depth | surveyed surface elevation + datum |
|---|---|---|
| TU1208 | ✅ theodolite | ❌ none |
| BAM | ✅ fabricator | ❌ none by design |
| hillside | ❌ none | ✅ 24 pts, m aOD (ODN) |
| 4TU | ✅ trial trench (unregistered) | ✅ GNSS + declared datum |

4TU is the only row with both ticks, and its subsurface tick is unregistered.

---

## 5. Recommendation

1. **Run Route A.** Transcribe the TU1208 target geometry and acquisition-line
   offsets, then fit `t0` and `v` per region against three or more surveyed
   depths and report the residuals. This is the first time Subterra would
   convert time to depth against a number somebody surveyed.
2. **Keep Route B as the regression test**, including the Pk050 negative
   control. Truth is already in the repo.
3. **Transcribe the 4TU trench tables** into a machine-readable truth file with
   `provenance_class: transcribed_from_publication`, recording per activity
   whether the table is populated — and treating a blank table as **missing
   information, never as attested absence**. Activity 09.4 has an empty table
   while its own photograph shows several utilities in the trench; that alone
   settles the point.
4. **Do not attempt the last link on held data.** Completing
   time → depth → surface elevation → absolute subsurface elevation on one
   dataset requires an acquisition where the same party surveys the surface
   (RTK or levelling, in a named datum), records a CMP or another *measured*
   velocity, and knows a target depth. Nothing held meets all three. That is a
   dataset to acquire or commission, and it should be stated as such rather
   than assembled out of numbers borrowed between sites.

## 6. What this audit refuses to do

- No velocity was inferred from a reflector that merely looks plausible.
- No time zero was inferred from an apparent surface return.
- No BAM or TU1208 value is proposed as a 4TU value.
- No synthetic ground truth was treated as field evidence; the TU1208 FDTD
  permittivities are labelled **modelled** and are used only as a cross-check
  on a fit, never as an input to one.
- Reading a printed number off a published figure is **transcription** and is
  labelled as such. Measuring a distance off a drawing with a ruler would be
  digitisation, and none was done — it is the reason BAM's Pk401 remains
  untranscribed, and the same bar applies here.

## Sources

- Dérobert, X. & Pajewski, L. (2018), *TU1208 Open Database of Radargrams: The
  Dataset of the IFSTTAR Geophysical Test Site*, Remote Sensing 10(4) 530 —
  [mdpi.com/2072-4292/10/4/530](https://www.mdpi.com/2072-4292/10/4/530)
  (target depths Figs 6/9/11/13, geolocation §3.4, file tables 3–7)
- ter Huurne, R. (2023), 4TU.ResearchData
  [10.4121/96303227-5886-41c9-8607-70fdd2cfe7c1.v1](https://doi.org/10.4121/96303227-5886-41c9-8607-70fdd2cfe7c1.v1)
  — Readme, Codebook, `Metadata.csv`, 125 `ground-truth.png`
- Grohmann, M. et al. (2026), Harvard Dataverse
  [10.7910/DVN/FCMUJQ](https://doi.org/10.7910/DVN/FCMUJQ), companion
  [10.1016/j.dib.2026.113103](https://doi.org/10.1016/j.dib.2026.113103),
  geometry source [10.1016/j.dib.2023.109312](https://doi.org/10.1016/j.dib.2023.109312)
- Binley, A., Lancaster University, Zenodo
  [10.5281/zenodo.8253179](https://doi.org/10.5281/zenodo.8253179) —
  *Hillside GPR file structure and description*
