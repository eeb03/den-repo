# Subterra benchmark matrix: which dataset may validate which claim

**Date:** 2026-10-05 · **Branch:** `research/yesan-kec-testbed-ground-truth` · **Status:** design document. No algorithm, manifest or scoring gate was changed; every currently blocked gate stays blocked.

**Principle.** No single public dataset validates Subterra end to end. Each dataset is a **tier** that may support only the claims its own ground truth can carry. A metric is reported against a dataset only where the matrix (§3) says VALID; PARTIAL claims carry their stated restriction in the same sentence.

---

## 1. P-GPR: primary-evidence check (2026-10-05)

Repository `github.com/aiiseverything/P-GPR-Dataset`, cloned at HEAD (pushed 2026-08-21), all files inspected.

| Question | Finding | Evidence |
|---|---|---|
| License | **CC BY 4.0**, including commercial use, with attribution and citation of the paper. GitHub's API shows "Other / NOASSERTION" only because the LICENSE file is custom text | `LICENSE` (full text read) |
| Raw traces outside the PNGs? | **None.** The repo holds 273 grayscale 8-bit PNG B-scans (height 256 px, width 102–2950 px), YOLO `.txt` labels, baseline training scripts and logs. No `.dzt/.rd3/.sgy/.dt/.npy/.csv` traces, no device header, no time or distance axis file | full file-type census |
| How ground truth was obtained | README: pipe locations were "recorded with reference to the construction drawings" during installation, while the pipes were exposed. GPR was scanned after levelling and tiling. **Claimed, not shown**: no record of those measurements is in the repo | `README.md` §1 |
| Physical coordinates/depths? | **Not available.** Only normalised YOLO boxes drawn "as tightly as possible" around each hyperbola's vertex and endpoints. No pipe position in metres, no depth, no wall/line identity, no pixel-to-metre scale (README says only that width is proportional to line length) | `README.md` §3; label files |
| Are labels independent of the radar? | **Only partly, and not verifiable.** Boxes are drawn on the echoes; the construction record is said to anchor *which* echoes are pipes. The **`steel` (rebar) class (1,111 of 1,490 boxes) has no stated independent truth**: it is a radar-interpretation label | `README.md` §3.2; label counts |
| Fixed splits? | **Yes**: train 188 / val 54 / test 31 (boxes: train 242 pipe + 749 steel; val 101 + 215; test 36 + 147). Two devices: `AIR` 150 images, `IECAS` 123 | file census |
| Split leakage risk | **Unresolved, plausible.** Several survey lines (2–3 heights × 2 devices) were taken over each pipe region. For `AIR`, **10 of 14 test images sit within ±2 file indices of a training image** (runs interleave: train 939–951, test 952–954, train 955, test 956–961…). `IECAS` test is mostly one contiguous block (3/17 adjacent). The training scripts point at a `dataset_grouped` directory, implying a grouping that the published split does not document | index analysis; `benchmark/benchmark.py`, `run_all.py` |
| Acquisition metadata | 2 devices, 1600 MHz, 8 ns window, indoor renovation site in Beijing, PPR water pipes and PVC conduits in reinforced-concrete and lightweight-brick walls, pipe-free rebar reference lines | `README.md` §2 |
| CIKM 2026 paper | **Not publicly available**: not on arXiv or any indexed source found; `citation.bib` still carries the placeholder `doi = {10.1145/XXXXXXX.XXXXXXX}`. Any extra acquisition or ground-truth detail in it is unverifiable today | `citation.bib`; web and arXiv search |

**Verdict:** P-GPR is a legitimate **image-domain AI detection/classification** benchmark for the `pipe` class, under the caveats above. It is not a raw-signal, time-zero, velocity, depth or metric-localisation benchmark. Any reported number must name the published split and flag the leakage risk, or use a device-held-out split (train AIR → test IECAS and the reverse), which is leakage-free by construction.

## 2. The tiers

| Tier | Dataset | Ground truth it actually carries | Held? |
|---|---|---|---|
| **T1 Engineering (controlled raw signal)** | **BAM** step specimens Pk050 / Pk266 / **Pk401**, Dataverse 10.7910/DVN/FCMUJQ v1.1 (CC0) + Grohmann et al. 2026 *Data in Brief* 68:113103 (CC BY) | fabricated geometry (drawings, Appendices A–C), a marked scan origin, mm grid; t0 and v_app from aluminium back walls at known thickness (Table 4, 1.5 GHz Rot00) | Pk050/Pk266 yes; **Pk401 not**; appendix drawings not yet transcribed |
| **T2 Spatial / trajectory** | **CMU-GPR**, github.com/rpl-cmu/CMU-GPR-Dataset; Baikovitz et al. 2021, arXiv 2107.07606 | robot pose from a Leica TS15 robotic total station (local, undeclared frame); wheel odometry; IMU; repeated passes. **No buried-object truth** (`docs/cmugpr-acquisition-assessment.md`) | no |
| **T3 AI detection (image domain)** | **P-GPR** (§1) | construction-stage pipe identity *claimed*; YOLO boxes on 8-bit PNGs; 2 devices | no (44 MB) |
| **T4 Field realism (real surveys)** | **4TU** utility surveys, 10.4121/96303227-5886-41c9-8607-70fdd2cfe7c1 (CC0) | trial-trench records per activity (independent, **not tied to traces**); RTK GNSS per trace (datum identified against AHN); velocity = hyperbola fit on the same data (thesis) | yes, 759/759 |
| **T5 Field object-level (future)** | **KEC/Yesan**: Zenodo 21441974 (2021 radar) + KEC EXTRI-2018-40-534.9607 (testbed truth, grade B) | constructed-testbed targets in testbed metres; **no radar-to-testbed transformation** | yes; **gate shut** |
| (supplementary) | **TU1208/IFSTTAR**, Zenodo 1211173 | theodolite-surveyed pipes in five soils; 3 vendors over the same site; no along-line origin; depth-datum caveat | yes |

**CMU-GPR licence conflict:** the repository's `LICENCE` file (read 2026-10-05) is **CC BY-SA 4.0**, while the earlier assessment recorded **CC BY-NC-SA 4.0** "for non-commercial academic use" with a commercial contact. The paper PDF states neither. Until the authors clarify, treat CMU-GPR as **non-commercial and ShareAlike**: quarantine it from anything shipped or published commercially.

## 3. Benchmark matrix

**VALID** = the dataset's own independent evidence supports the claim now. **PARTIAL** = some of it, under the stated restriction. **NOT VALID** = the dataset cannot support the claim. **BLOCKED** = the evidence exists in principle, but a named missing item keeps the gate shut.

| Capability | BAM (T1) | CMU-GPR (T2) | P-GPR (T3) | 4TU (T4) | KEC/Yesan (T5) |
|---|---|---|---|---|---|
| **Raw format ingestion** | **VALID**: native GSSI `.DZT` (SIR-20) read; the authors' `.npy` and the documented DZT→grid workflow give an external check | **PARTIAL**: raw `gpr_meas.csv` int16 traces; a new converter is needed (not built); time window and sample interval unpublished | **NOT VALID**: PNG images only, no raw traces | **VALID**: SEG-Y, 759/759 converted | **VALID** (2021 MALA `.rd3/.rad` read). Ingestion does not depend on registration |
| **Amplitude preservation** | **VALID**: compare Subterra's DZT decode against the authors' published `.npy` (16-bit ADC counts, documented reshaping and line reversal) | **PARTIAL**: raw counts plus the manufacturer's mV constant; no physical reference | **NOT VALID**: 8-bit processed images | **PARTIAL**: bit-identical regression on raw values; no physical reference | **PARTIAL**: raw counts; no reference |
| **Spatial coordinates** | **VALID** in the local specimen frame (mm; origin at the marked cross; <1.25 mm line misalignment). No CRS by design | **VALID** in a local frame: total-station positions, independent of the GPR; frame undeclared, no CRS | **NOT VALID**: no coordinates, no pixel scale | **PARTIAL**: per-trace RTK GNSS; ellipsoidal datum identified against AHN; urban GNSS gaps (thesis) | **BLOCKED**: no coordinates in files; testbed frame not registered |
| **Survey trajectory** | **VALID**: documented meander, reversal and grid | **VALID**: total-station trajectory + wheel + IMU; repeat passes | **NOT VALID** | **PARTIAL**: GNSS track per trace, gaps under buildings | **BLOCKED**: direction only inferred |
| **Time-zero handling** | **VALID**: published t0 per specimen from a known-thickness metal back wall (1.5 GHz Rot00 only); the back wall is never a scored target | **NOT VALID**: the authors' utility picks the first air-wave peak (a convention); the time axis is not in ns | **NOT VALID** | **NOT VALID** for accuracy: the author confirms no t0/air-gap correction was applied and gives no magnitude. Mechanics (DelayRecordingTime) exercised only | **NOT VALID**: KEC 2017–18 values are not transferable to 2021 |
| **Velocity provenance** | **VALID**: v_app from back walls at fabricated thickness; four thickness steps allow hold-out checks | **NOT VALID** | **NOT VALID** | **PARTIAL**: provenance recordable (Reflex-W hyperbola fit on the same surveys, thesis §5.3.1); not independent | **NOT VALID** |
| **Depth conversion** | **PARTIAL → VALID** once Appendices A–C are transcribed (depths to a drawn reference point; Pk266 centre/crown settled by Appendix B) | **NOT VALID** | **NOT VALID** (no depths published; 8 ns window, PNG only) | **BLOCKED**: no t0 magnitude; velocity not independent; trench depths not tied to traces | **BLOCKED**: registration |
| **Anomaly / candidate generation** | **VALID**: designed specimens, per-line target crossings (already run: recall 0.065–0.093, precision 0.135–0.147) | **PARTIAL**: candidate *repeatability* across passes at the same total-station position only; no object truth | **PARTIAL**: image-domain proposals only, not Subterra's trace pipeline | **PARTIAL**: activity-level presence; 107 positives vs **6** independent negatives (detects only AUC ≥ 0.742 vs chance) | **BLOCKED** |
| **Object detection** | **VALID** in the specimen frame (ducts, voids, rebar mesh) | **NOT VALID**: no buried-object truth | **PARTIAL**: `pipe` class on PNGs; construction truth claimed but unpublished; possible split leakage | **PARTIAL**: activity-level only; no trace-level object positions | **BLOCKED** |
| **Classification** | **PARTIAL**: metal duct vs polystyrene void vs rebar; very small n | **NOT VALID** | **PARTIAL**: `pipe` vs `steel`; `steel` labels are radar interpretation; the pipe material (PPR/PVC) split is not labelled | **PARTIAL**: utility type/material from trench records per activity, unregistered | **BLOCKED** |
| **Longitudinal localisation** | **PARTIAL → VALID** after transcription (origin and mm grid documented) | **NOT VALID** for objects (it does validate along-track *position*, see Spatial) | **NOT VALID**: pixels, no scale, no physical positions | **BLOCKED**: no trench-to-trace tie (author confidentiality) | **BLOCKED**: radar-to-testbed transformation |
| **2D / 3D localisation** | **PARTIAL → VALID** after transcription (X, Y in mm + depth, specimen frame) | **NOT VALID** | **NOT VALID** | **BLOCKED** | **BLOCKED** |
| **False-positive rejection** | **VALID** for duct/void classes: designed specimens are exhaustive by drawing; Pk050 has no ducts or voids (but does have rebars and M16 anchors, which must be targets or excluded) | **NOT VALID** | **PARTIAL**: pipe-free rebar lines are image-level negatives for `pipe` | **PARTIAL**: 6 independent negatives, underpowered | **BLOCKED** |
| **Cross-site generalisation** | **NOT VALID**: one lab, concrete | **PARTIAL**: 3 indoor sites, trajectory tasks only | **NOT VALID**: one site | **VALID** at activity level: 125 activities, 13 projects, about 11 towns | **BLOCKED** |
| **Cross-device generalisation** | **PARTIAL**: two antennas (1.5/2.6 GHz), one system | **NOT VALID**: one Noggin 500 | **PARTIAL → VALID** with a device-held-out split (AIR vs IECAS, same site), image domain only | **NOT VALID**: one device | **BLOCKED**: three antennas, but the headers disagree with the folder labels; scoring shut |

**Supplementary, TU1208:** VALID for raw ingestion of three vendors (DZT/MALA/IDS) and for **cross-device** comparison at one site. PARTIAL for detection (per-profile target counts) and relative depth ordering. NOT VALID for localisation, absolute depth and t0 (no along-line origin, datum caveat; `docs/tu1208-physical-depth-validation-report.md`).

## 4. Legitimate metrics, per tier

| Tier | Metric | Unit / scope |
|---|---|---|
| T1 BAM | detection recall and precision; false alarms per m² scanned; X/Y localisation error; depth error to the drawn reference point; t0 error vs the published back-wall t0; velocity and thickness error vs fabricated steps (calibrate on one step, test on the others); DZT decode vs `.npy` (max abs difference, should be 0 after the documented formatting) | per specimen × antenna × orientation, specimen frame, mm. Never pooled into "field" numbers |
| T2 CMU-GPR | along-track position error of odometry vs total station; repeat-pass association rate at matched total-station positions (same-sequence only); candidate repeatability | local frame, metres, per sequence |
| T3 P-GPR | `pipe` AP@0.5, precision and recall; `pipe`-vs-`steel` confusion; **device-held-out** AP | image domain. The published split is reported with a leakage caveat; no metric in metres or ns |
| T4 4TU | activity-level AUC / recall with a confidence interval stating its power; GNSS-vs-AHN surface consistency (already measured); provenance-correctness of velocity labels | activity level. **No depth error, no localisation** |
| T5 Yesan/KEC | none today | gate shut |

**Never legitimate (examples):**
- an absolute depth error on 4TU;
- any metre-scale localisation on P-GPR, CMU-GPR or 4TU;
- BAM numbers described as soil or utility performance;
- CMU-GPR as a detection benchmark;
- PNG-derived values called raw traces;
- Yesan/KEC scores of any kind.

## 5. What Subterra can prove today, and what it cannot

**Can prove today (with existing artifacts):**
1. Raw ingestion of SEG-Y (4TU), GSSI DZT (BAM, TU1208), MALA `.rd3/.rad` (Hillside, TU1208, Yesan) and IDS `.dt` (TU1208), with provenance and refusal of undeclared quantities.
2. Bit-identical processing regression on held data (the 26-test baseline; four IDS `.dt` baselines currently fail after the signed-int16 decoding fix, see the branch notes).
3. Correct identification of the 4TU vertical datum by measurement against AHN.
4. **Measured, negative** detection performance:
   - BAM recall 0.065–0.093 / precision 0.135–0.147 (`docs/bam-benchmark-detection.md`);
   - 4TU AUC 0.445, a null result that the corpus is underpowered to sharpen (`docs/4tu-utility-benchmark.md`).
5. That its scoring gates refuse claims the truth cannot support (tests across the BAM, DRC and Yesan manifests).

**Cannot yet prove:**
- metric localisation of any buried object;
- absolute depth accuracy;
- time-zero accuracy;
- velocity estimation;
- a detector that beats chance;
- classification;
- 3D reconstruction;
- field-scale cross-site/device generalisation at object level.

**Closest to provable** (data in hand or one download away): t0, velocity, depth and localisation **in the BAM specimen frame**, after Pk401 is downloaded and the appendix drawings are transcribed.

## 6. Missing evidence that needs an author or data-owner response

| Owner | Request | Unblocks |
|---|---|---|
| BAM (Grohmann et al.) | none required for T1. Optional: t0 / v_app for 2.6 GHz and Rot90; drawing files in vector form | t0/velocity at the second antenna |
| P-GPR (Yue et al., Tsinghua / AIRCAS) | the construction-stage pipe records (positions/depths per wall and line); image → line/wall/height mapping; the `dataset_grouped` split definition; pixel-to-metre scale; whether raw traces can be released; the CIKM DOI/paper | independence of labels, leakage check, any metric localisation |
| CMU-GPR (Baikovitz, Kaess) | licence (CC BY-SA vs CC BY-NC-SA); total-station frame and accuracy; GPR time window / sample interval | commercial use; time axis |
| 4TU (ter Huurne) | already sent 2026-08-15: t0/air gap, velocity method (method now answered by the thesis). Still needed: trench coordinates or a trench-to-trace tie; more attested-empty surveys | localisation; AUC power; depth |
| KEC / Hanseo (Oh Chang-Geun; KEC Jeong Jin-deok; SNU Min Dong-joo; Geoscan) | 2021 0 m mark, direction, 27/3116 calibration; 2017–18 raw files; installation GPS | the Yesan gate (T5) |
| TU1208 (Pajewski et al.) | along-line origin; as-built surface levels | localisation and absolute depth at a soil site |

## 7. Staged validation plan (research prototype → product-ready)

| Stage | Goal | Dataset | Exit criterion | Gate impact |
|---|---|---|---|---|
| **0, now** | Freeze claims to this matrix | all | every published number cites a VALID cell | none |
| **1, signal engineering** | ingestion, amplitude, t0, velocity, depth, localisation in a controlled frame | **BAM** Pk266 + Pk401 (+ Pk050 control) | DZT decode = authors' `.npy`; t0 within one sample of the published value; thickness error within tolerance on held-out steps; X/Y/depth errors reported per object; back wall never scored | **needs explicit approval** to declare origin and units in the BAM frames and add `bam-pk401` |
| **2, spatial and trajectory** | positioning, odometry, repeat-pass association | **CMU-GPR** A.6 (89 MB) → more sequences | odometry vs total-station error curve; association rate at matched poses, thresholds declared not tuned | none (no object gate); licence decision first |
| **3, AI detection** | learned detector/classifier on real echoes | **P-GPR**, device-held-out split | AP@0.5 for `pipe` on AIR→IECAS and IECAS→AIR; the published-split number shown only with the leakage caveat | none (image domain, separate track) |
| **4, field realism** | presence detection on real surveys; GNSS/surface consistency | **4TU** (+ more negatives on request) | AUC with a power statement; no depth or localisation claims | unchanged (localisation stays BLOCKED) |
| **5, field object-level** | first metric localisation and depth on buried objects in soil | **Yesan/KEC** (or TU1208 if its origin is supplied) | an independently established radar-to-testbed transformation, then recall/localisation with radius ≥ 0.15 m | **stays shut** until the registration is established by author/site evidence, never by fitting radar responses |
| **6, product-ready** | claims for customers | all tiers | each product claim maps to ≥ 1 VALID cell, a field-domain result exists (stage 4 or 5), and limitations are shown in the UI | — |

## 8. Smallest set to download and integrate

| # | Item | Size | Why it is needed | Status |
|---|---|---|---|---|
| 1 | **BAM `Pk401_Dataset.zip`** (Dataverse FCMUJQ v1.1) + the **Data in Brief PDF** (Appendices A–C) | 782 MB + PDF | the only path to VALID t0 / velocity / depth / localisation; void targets | download needed; PDF retrieval needs a manual or permitted download |
| 2 | **P-GPR repository** | ~44 MB | the only real-echo AI detection/classification set with claimed independent truth and a cross-device split | download needed (CC BY) |
| 3 | **CMU-GPR sequence A.6** | 89 MB | the only independent trajectory ground truth | **after the licence decision** |
| — | 4TU, TU1208, BAM Pk050/Pk266, Yesan | — | already held | no download |

Total new download: **~915 MB**. Nothing else is needed for stages 1–4.
