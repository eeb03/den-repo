# Public GPR benchmark hunt: a defensible quantitative benchmark that does not wait on Yesan/KEC

**Date:** 2026-10-05 · **Branch:** `research/yesan-kec-testbed-ground-truth` · **Scope:** research only. No production code, manifest or scoring gate was changed, and **Yesan scoring stays disabled**.

## Bottom line

**Yes.** The strongest public benchmark available today is the **BAM concrete step-specimen GPR dataset** (Harvard Dataverse `10.7910/DVN/FCMUJQ`, CC0, now v1.1 with a third specimen). It has just been documented by a peer-reviewed data paper: **Grohmann, Wöstmann, Maack & Niederleithinger (2026), *Data in Brief* 68:113103, doi 10.1016/j.dib.2026.113103** (CC BY, published 2026-07-24).

That paper resolves the three blockers that kept Subterra's BAM benchmark at "detection only":
- **absolute origin:** the A-scan X000 on B-scan Y000 sits at a marked origin cross, shown on technical drawings in Appendices A–C;
- **coordinate units:** X/Y in mm on a 5 × 5 mm grid, a 2000 × 800 mm field (a 401 × 161 × 512 array);
- **time zero and velocity:** both measured **from aluminium back-wall plates at known specimen thickness**, independently of the targets (Table 4).

It also documents the DZT → grid formatting step (Subterra's open question `dzt-to-grid-mapping`). And it adds **Pk401**, four 120 × 120 × 60 mm polystyrene cuboids, i.e. voids, at four embedment depths, the cavity analogue Subterra most needs.

The second-best option is the dataset the repo already holds, **TU1208/IFSTTAR**. It is the strongest *soil* option: theodolite-surveyed pipes under three vendors' radars. But it has no along-line origin and a depth-datum caveat, so it supports only partial metrics.

Every candidate below was checked against the exclusion rules: truth from the same radar, positions unknown, images only, visual-fit registration, synthetic only.

---

## 1. Search coverage (this pass)

- **Zenodo API**, 10 queries: buried pipes, buried objects + ground truth, sandbox, landmine, utility, rebar/concrete, test site, known-depth targets, DZT, rd3.
- **Figshare API:** De Montfort 8323049.
- **Harvard Dataverse API:** FCMUJQ file listing.
- **Europe PMC** full-text XML: the BAM *Data in Brief* paper.
- **PMC** article and figure CDN; the PDF was reachable in Chrome, but the viewer did not accept page navigation (see §6).
- **IEEE DataPort**; **Mendeley Data** and *Data in Brief* searches; **4TU.ResearchData**; **AI-Hub** (Korean AI-data portal, previous pass).
- **Web searches:** test sites with total-station ground truth; UAV/landmine GPR; controlled sand-tank pipe datasets.

Already-qualified repository datasets are reused from `docs/fallback-localisation-dataset-search.md`, `docs/dataset-inventory.md` and the benchmark manifests rather than re-searched.

**Blocked or limited:**
- figshare (WebFetch) returned HTTP 403, but the API works;
- the PMC PDF is behind a browser check that passed in Chrome, but its viewer could not be driven;
- IEEE DataPort is subscription-only;
- AI-Hub is restricted to Korean nationals;
- the Zenodo record 13144711 (Branco) is access-restricted.

## 2. Candidates

### 2.1 BAM concrete step specimens: **Pk050 / Pk266 / Pk401** (recommended)

| Field | Value |
|---|---|
| 1 Name | Ground-Penetrating Radar Data (Pulse-Echo Mode) Acquired with 1.5 GHz and 2.6 GHz Antennas on Concrete Step Specimens Containing Embedded Objects |
| 2 DOI/URL | data **10.7910/DVN/FCMUJQ** (v1.1, released 2026-04-23); paper **10.1016/j.dib.2026.113103** (PMC13476519) |
| 3 Authors | Grohmann, Wöstmann, Maack, Niederleithinger: BAM (Bundesanstalt für Materialforschung und -prüfung), Berlin |
| 4 Formats | native GSSI **`.DZT`** (SIR-20); formatted **`.npy`** 3D volumes (401 × 161 × 512) with X/Y (mm) and time (ns) vectors; per-B-scan **`.csv`** |
| 5 Size / count | 3 zips, 2.54 GB total. **Pk401_Dataset.zip 782.2 MB** is new; Pk050 and Pk266 are already held. Per specimen: 2 antennas (1.5 / 2.6 GHz) × 2 orientations (Rot00 / Rot90) = 4 volumes, each 181 scan lines × 841 A-scans raw |
| 6 Ground truth | **Fabrication**: specimens cast to technical drawings (Appendices A–C of the paper), ±1 mm surface tolerance. Independent of any radar. Pk266 geometry is also published in Maack et al. (earlier specimen paper); Pk401 in Beutel et al. |
| 7 Positions | in the drawings, relative to the **marked origin (X/Y = 0 mm)** that A-scan X000 / B-scan Y000 sits on |
| 8 Depths | Pk266: 4 tendon ducts (inner Ø 60 mm) at four depths. Pk401: 4 foam cuboids, one per thickness level. Pk050: 10 mm rebars at 30 mm and four M16 impact anchors on the sides. Also four known **specimen thicknesses** (stepped back wall, 500 mm per step) |
| 9 Classes / sizes | metal tendon duct Ø60 mm inner; polystyrene cuboid 120 × 120 × 60 mm (a void analogue); rebar Ø10 mm; edge reinforcement |
| 10 Registration | local specimen frame, mm; automated scanner, meander pattern with every 2nd line reversed (documented); residual line misalignment < 1.25 mm after the authors' offset correction. **No CRS, by design** |
| 11 Time zero | **t0 published per specimen** from the aluminium back-wall reflection at known thickness (1.5 GHz, Rot00): Pk266 0.7308 ns, Pk050 0.6723 ns, Pk401 0.6868 ns. 15 ns window, 512 samples (Δt 0.029354 ns) |
| 12 Velocity | **v_app from the same back walls**: Pk266 0.1271 m/ns (ε 5.56), Pk050 0.1246 (5.79), Pk401 0.1088 (7.6). Material mix in Table 1 |
| 13 Frequency | 1.5 GHz and 2.6 GHz GSSI bistatic, ground-coupled |
| 14 License | data **CC0 1.0**; paper **CC BY** |
| 15 Download | 2.54 GB (Pk401 alone 782 MB) |
| 16 Subterra support | **Yes**: `converters/gssi_converter.py` reads the DZT headers; `benchmark.bam_ingest` loads the `.npy` grids; `scripts/score_bam_benchmark.py` already scores Pk266/Pk050 detection |
| 17 Missing | the **appendix drawings' numbers**: PMC serves 100×150 thumbnails only, so the drawings must be read from the article PDF. Whether Pk266 duct depths are to centre or crown (the manifest's `depth-reference-surface` question): the drawing should settle it. t0/v are given for 1.5 GHz Rot00 only. Concrete, not soil |
| 18 Suitability | **the best available quantitative benchmark**, in a controlled concrete NDT domain |

**Why the t0/velocity are not circular.** They come from the aluminium back wall at a fabricated thickness, a reflector that is **not** one of the evaluated targets. The back wall must be excluded from target scoring, and any depth/velocity validation must report that the reference used the specimen's back wall.

### 2.2 TU1208 / IFSTTAR geophysical test site (held)

| Field | Value |
|---|---|
| DOI | Zenodo **10.5281/zenodo.1211173**; TU1208 open-database paper |
| Formats | GSSI `.dzt`, MALA `.rd3/.rad`, IDS `.dt`: **all three already converted** (67/67) |
| Ground truth | **theodolite-surveyed during construction** (pipes from 2 crown points at each end; blocks from 4 corners), in five homogeneous soil regions |
| Positions / depths | printed transverse sections; **9 pipe depths in 3 media** transcribed in `benchmark/tu1208_targets.json` (36 targets) |
| Registration | site-local. **No along-line origin**: no source says which trace is above which section point. Transverse offsets exist only as scale-bar segment lengths |
| Time zero / velocity | not independently available (`docs/tu1208-physical-depth-validation-report.md`: Outcome D) |
| Depth datum | published 0.00 omits a 10 cm limestone layer, the asphalt course and ~30 cm extra limestone in silt (`depth-datum-vs-antenna-surface`) |
| License / size | CC-BY-4.0; on disk |
| Suitability | **PARTIAL**: the strongest soil truth, but localisation and absolute depth are blocked by missing registration and datum |

### 2.3 4TU utility surveys, ter Huurne (held)

| Field | Value |
|---|---|
| DOI | 10.4121/96303227-5886-41c9-8607-70fdd2cfe7c1 |
| Formats | SEG-Y (**converted**, 759 lines) + GNSS RTK per trace |
| Ground truth | trial trenches dug by contractors, recorded as PNG cross-sections / CAD; **independent of the radar** |
| Registration | GNSS per trace (ellipsoidal, field identified); **no metric tie between the trench sketch and a trace index** |
| Time zero / velocity | no t0 correction (author-confirmed); velocity is a hyperbola fit on the same surveys (thesis, §8 of `docs/4tu-author-evidence.md`) |
| License | CC0 |
| Suitability | **PARTIAL**: real-world utilities, but no trace-level registration and no independent velocity |

### 2.4 Solla, *concrete cracks*: Zenodo 14918577 (new)

| Field | Value |
|---|---|
| Authors | Mercedes Solla (Universidade de Vigo); paper *Case Stud. Constr. Mater.* doi 10.1016/j.cscm.2025.e04782 |
| Formats | **MALA `.rd3/.rad/.mrk/.cor`** (30 profiles; plus `.add/.em`). **Subterra reads MALA** (`mala_converter.py`) |
| Ground truth | laboratory build: 3 slabs 0.15 × 0.15 × 0.60 m, 7 cracks of designed width 2–30 mm and depth 10–110 mm, 5 infill states (air, dry sand, saturated sand, water, bitumen). File-to-condition table in `Description:Metadata.docx` |
| Acquisition | MALA ProEx, 2.3 GHz, 2 mm trace interval, 10 ns / 336 samples, survey wheel, along the slab's central axis, 2 antenna orientations |
| Missing | crack positions along the slab (only in a figure); t0/velocity not given |
| License / size | CC-BY-4.0; 5.6 MB |
| Suitability | **PARTIAL**: a tiny, clean lab set for crack detection and infill contrast, not object localisation |

### 2.5 Solla, *rebar, SFCW vs pulsed*: Zenodo 10962520 (new)

| Field | Value |
|---|---|
| Formats | pulsed: **MALA `.rd3/.rad`** (3 specimens); SFCW: separate zip (format not inspected) |
| Ground truth | laboratory specimens, rebar Ø8–32 mm; geometry only in the SMAR 2024 conference paper (not checked) |
| License / size | **GPL-3.0-or-later** (an unusual licence for data); 3.7 MB |
| Suitability | **PARTIAL**: needs the paper's specimen geometry |

### 2.6 Grimsel ISC GPR, ETH Zurich (qualified previously)

| Field | Value |
|---|---|
| DOI | 10.3929/ethz-b-000420930; Solid Earth 11:1441 (2020) |
| Formats | **MALA `.rd3/.rad/.rd7`** (2 tunnel profiles) |
| Ground truth | shear-zone geometry from televiewer, core logs and tunnel mapping (independent) |
| Missing | borehole coordinates sit in a separate dataset (10.3929/ethz-b-000243199); the target is a 3D fracture surface, not discrete objects |
| License | **In Copyright, Non-Commercial Use Permitted** |
| Suitability | **PARTIAL**: geology, a single day, a non-commercial licence |

### 2.7 Checked and rejected (would be excluded by the rules)

| Dataset | Why not |
|---|---|
| INGV/UNISA cart + UAV low-frequency GPR, Zenodo 18769571 (CC-BY, SEG-Y + GeoTable, RTK) | features "identified" from the cart GPR itself; no independent targets (20–140 MHz geology) |
| De Montfort "Ground penetrating radar dataset", figshare 8323049 (CC-BY, 1.4 GB `.dat` grid) | no description of what was buried, where or how deep; no linked ground-truth document |
| Yurt et al., IEEE DataPort "Buried Object Characterization" | **synthetic** (full-wave simulator) and subscription-only |
| Stadler 2024 landmine/IED simulation, Zenodo 8276600 | synthetic. Usable only as a separately labelled secondary benchmark |
| AI-Hub 71327 / 71457 / 71676; Mendeley "Intelligent recognition of subsurface utilities" (Morocco); MCG GPR (Zenodo 14270869) | **image-only** (JPG/PNG + boxes); labels drawn on the radargrams |
| Branco "GPR Dataset", Zenodo 13144711 | access **restricted**; annotated B-scan images |
| CMU-GPR | robot-localisation data, no buried-object truth |
| Matthews et al., Zenodo 17292599 | literature meta-database (CSV of published results), no traces |
| DRC seeded minefield | strong truth, but **no public GPR** (`docs/drc-seeded-field-registration.md`) |
| Yesan (Zenodo 21441974) / KEC 2017–18 | 2021 registration unresolved; 2017–18 raw data not public (`docs/research/kec_raw_gpr_data_hunt.md`) |
| RUP-FS (Univ. Gustave Eiffel) | no GPR labels; designed pavement structure only (`docs/dataset-inventory.md`, deferred) |

## 3. Capability scores

READY = defensible now or after transcription from the cited source alone, with no fitting to radar responses. PARTIAL = some of it, with named gaps. NOT = not defensible.

| Capability | **BAM (Pk266 + Pk401 + Pk050)** | TU1208 | 4TU | Solla cracks | Solla rebar | Grimsel |
|---|---|---|---|---|---|---|
| Detection precision/recall | **READY**: designed specimens, every embedded object drawn; Pk050 is a control for the duct/void classes only (it still has 10 mm rebars at 30 mm and four M16 impact anchors) | PARTIAL: per-profile target count only; precision needs exhaustiveness per line | PARTIAL: trench-level presence, no trace tie | PARTIAL: per-profile crack count | PARTIAL | NOT (surface, not objects) |
| Longitudinal localisation | **READY after drawing transcription**: X000 at the marked origin, 5 mm grid, misalignment < 1.25 mm | NOT: no along-line origin | NOT: no trench-to-trace tie | PARTIAL (positions in figure) | PARTIAL | NOT |
| 2D / 3D localisation | **READY after transcription** (X, Y in mm + depth below the scanned surface) | NOT | PARTIAL: GNSS per trace, trench depths unregistered | NOT | NOT | PARTIAL (3D fracture vs separate borehole coordinates) |
| Depth error | **READY** for objects whose drawn reference point is unambiguous: t0 and v_app independent of targets. PARTIAL for Pk266 until centre/crown is read from Appendix B | PARTIAL: relative depths; datum caveat; no t0/v | NOT: no t0, velocity from the same data | PARTIAL: designed crack depth, no t0/v | PARTIAL | PARTIAL |
| Candidate-generation validation | **READY** (4 volumes per specimen × 3 specimens; void and metal contrasts) | PARTIAL | PARTIAL | PARTIAL | PARTIAL | NOT |
| Time-zero validation | **READY**: published t0 from a known-thickness metal back wall, per specimen. Compare Subterra's t0 estimate on the same files (1.5 GHz Rot00) | NOT (`docs/tu1208-physical-depth-validation-report.md` §6) | NOT (author: none applied, no magnitude) | NOT | NOT | NOT |
| Velocity / depth-model validation | **READY**: four fabricated thickness steps plus a reflective back wall per specimen give velocity checks against known geometry (hold one step out if v is calibrated on another) | PARTIAL: known media, no independent v | NOT | NOT | NOT | PARTIAL |

## 4. Choice

1. **BAM Pk266 + Pk401 (+ Pk050 as control): the primary benchmark.**
   - The only public dataset found where all seven capabilities can be made READY from independent documentation, with no visual fitting.
   - Licensed CC0/CC BY, the format is already supported, and Subterra's own BAM pipeline already runs on two of the three specimens.
   - **Pk401 matters most**: polystyrene voids are the closest controlled analogue to the cavities Yesan/KEC were built to test.
2. **TU1208/IFSTTAR: the secondary, soil-domain benchmark.**
   - It is limited to what the theodolite truth supports without registration: per-profile detection counts and relative depth ordering within a region.
   - It is reported separately and never pooled with BAM.

## 5. Answers

**1. Can Subterra get a defensible public benchmark without waiting for the Yesan/KEC authors?** Yes: the BAM dataset with its 2026 *Data in Brief* documentation. It is a **controlled concrete NDT** benchmark. It is not evidence of soil- or utility-scale performance, and results must say so (the scope boundary already in `docs/bam-benchmark-detection.md`).

**2. The strongest dataset.** BAM Pk266 / Pk401 / Pk050, Harvard Dataverse 10.7910/DVN/FCMUJQ v1.1 + *Data in Brief* 68:113103 (2026).

**3. Exact files**
- `Pk401_Dataset.zip` (782.2 MB) from https://doi.org/10.7910/DVN/FCMUJQ. Use the Dataverse file API, record the version number (1.1) and the MD5 shown on the record.
- Re-check `Pk050_Dataset.zip` / `Pk266_Dataset.zip` against v1.1's checksums; they're already held, `PROVENANCE.json` in `datasets/raw/bam_concrete/`.
- The article PDF (open access) for the **Appendix A–C technical drawings**: https://doi.org/10.1016/j.dib.2026.113103 (or PMC13476519 → PDF). The full-text XML is already held git-ignored at `datasets/raw/references/bam_dib2026/bam_dib.xml`.

**4. Subterra work required (no new converter)**
- a. Extend `benchmark.bam_ingest` to Pk401 (the same `.npy` layout, 401 × 161 × 512).
- b. Transcribe Appendices A–C into the manifests: object X/Y/depth in mm relative to the marked origin, and the specimen thickness steps. Mark the back wall as a **calibration reflector, excluded from scoring**.
- c. Update `bam-pk266` (and a new `bam-pk401`) manifest frames:
  - `origin_status` → declared (citing the paper's origin statement);
  - `units_status` → declared (mm);
  - close `coordinate-units`, `absolute-origin` and `dzt-to-grid-mapping` with the paper as the source;
  - resolve `depth-reference-surface` from the drawing.
  - **This is a gate change and needs explicit approval.**
- d. Record t0 / v_app from Table 4 as **author-published calibration**, kept apart from Subterra's own estimates, and use them only for the 1.5 GHz Rot00 volumes unless the authors give other values.
- e. Add tests that the back wall is never a scored target, and that localisation uses the declared origin only, never a hyperbola fit.

**5. Metrics that could legitimately be reported (in the specimen frame, per specimen, antenna and orientation)**
- detection recall and precision, with Pk050 as a negative control **for duct/void classes** (its rebars and anchors are real reflectors and must be targets or explicitly excluded);
- false alarms per m² of scanned area;
- X/Y localisation error (mm) and depth error (mm, to the drawn reference point);
- t0 error against the published back-wall t0;
- velocity and thickness error against the fabricated steps.

**6. Limitations**
- **Concrete, lab-scale, 1.5/2.6 GHz.** It says nothing about soil, utilities, metre-scale depths, GNSS registration or vertical datums.
- **Few targets:** 4 ducts, 4 voids and a rebar mesh. Confidence intervals will be wide.
- **Fabrication truth (grade B, "measurement associated"), not re-surveyed:** the specimens are about 25 years old, and Pk401 was stored outdoors under cover.
- **t0 and v_app are the authors' estimates** from a back-wall reflection: independent of the targets, but still derived from radar, at 1.5 GHz Rot00 only, and "apparent" (bulk) values.
- **Appendix numbers are not yet transcribed:** the drawings must be read from the PDF before any localisation or depth claim.
- **The soil gap remains.** TU1208 is the best soil option and still lacks an along-line origin, so no public soil benchmark found supports localisation or absolute depth. Yesan/KEC remain blocked as documented.

## 6. What was not completed in this pass

The PMC article PDF loaded in Chrome after an automatic browser check, but the viewer would not accept page navigation (two attempts). Per the browser-automation rules I stopped rather than loop. **The Appendix A–C drawings therefore have not been read.** Every BAM capability marked "READY after transcription" depends on that step. It needs either a manual download of the open-access PDF (the user's choice) or a direct publisher download.
