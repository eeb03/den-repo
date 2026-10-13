# Plan-View Linearity V1, L1 and L1-R: implementation note (frozen before any run)

**Status:** FROZEN. This file and `scripts/pvl_v1.py` were committed **before** any L1 or L1-R computation. The brief, `docs/plan-view-linearity-v1-brief.md` (commit `f36baea`), is unchanged. This note fixes the operational details the brief leaves open. Where it narrows a phrase in the brief, it says so.

**Scope:** L1 and L1-R on BAM only. **L2 (4TU) is not run.** No production code is touched. Every result is **EXPLORATORY** and **CONCRETE NDT ONLY**: every BAM specimen and scan has been used in earlier research.

## 1. Candidates

- **N1. Velocity estimates.** The stored CCD-V1 Arm D detections lack the per-candidate velocity estimate (v_est) that W needs (brief §3.2). V2 (A3, freeze 09dc288) is therefore **re-run** on the same three scans: Pk266, Pk401 and Pk050 at 1.5 GHz Rot00. The re-run must reproduce the stored detections exactly (same count and the same line, x, t and |z| per detection). If it does not, L1 stops.
- **N2. λ̂.** λ̂ = v̂ / f_nominal. v̂ is the candidate's own v_est, else the median v_est of the other candidates on its line, else the scan median.

## 2. In-line width W (brief §3.2)

- **Dewow:** subtract a running mean over one period (round(T/dt) samples) along time, trace by trace. No lateral background removal.
- **Envelope:** the Hilbert envelope along time, then averaged over samples k ± round(0.25 T/dt), where k is the candidate's nearest sample. This gives one value per trace.
- **Half-maximum run:** let i be the candidate's nearest trace. The run is the contiguous set of traces around i whose value is ≥ 0.5 × the value at i.
- **W** = (number of traces in the run − 1) × trace step, divided by λ̂.

## 3. Linking (brief §3.3, BAM)

- Candidates are taken in descending |z|.
- A candidate is **eligible** for a track if all of these hold:
  - its line is not yet in the track;
  - min |line − member line| ≤ G;
  - |t − t of the nearest-line member| ≤ δt·T;
  - it passes the lateral test:
    - **≥ 2 members:** x = a + b·y is least-squares fitted through the members, and |x − (a + b·y)| ≤ δx·λ̂;
    - **1 member:** |Δx| ≤ δx·λ̂ + |Δy|·tan 60°.
- It joins the eligible track with the smallest lateral residual. If no track is eligible, it starts a new one.
- **A join is refused if it would make the fitted |b| exceed tan 60°.**

## 4. Track descriptors and labels (brief §3.4–3.5)

**Descriptors:**
- **L:** the distance between the two extreme members, measured along the fitted line: √(Δy² + (b·Δy)²), divided by the median λ̂ of the members. A single member has L = 0.
- **s:** the RMS of the fit residuals × cos(atan b), divided by λ̂ (defined for ≥ 3 members).
- **W_med:** the median W of the members.

**Labels:**

| Label | Rule |
|---|---|
| planar | W_med > W* |
| linear | W_med ≤ W*, and L ≥ L*, and n_lines ≥ 3, and s ≤ 0.5 |
| compact | otherwise |

## 5. Selection (brief §4 L1), with the phrase "carries a track" made operational

**What "carries a track" means:**
- **A duct carries a linear track** if some linear track has its median member x within ±100 mm of the duct's x.
- **A cuboid carries a linear track** if some linear track has its median member x within ±100 mm of the cuboid's x, **and** its member-y range overlaps [y_obj − 60, y_obj + 60] mm.

**Rule:**
1. **Admissible:** all 4 ducts (Pk266) carry a linear track, and none of the 4 cuboids (Pk401) does.
2. **Objective:** among admissible configurations, maximise the fraction of Arm D `back_wall` candidates (all three specimens pooled) whose track is labelled planar.
3. **Ties:** smallest δx, then smallest G, then largest L*, then (for determinism) smallest δt, then smallest W*.

**Diagnostics, reported but not used to select:**
- for each duct's matched track, whether its median time lies within 1T of the expected duct-top time (stored known-geometry calibration);
- whether the step edges (x = 500, 1000, 1500 mm) carry a linear track (±60 mm), on all three specimens;
- the label mix per CCD-V1 Arm D class.

**If no configuration is admissible: STOP.** L1-R is not run.

## 6. Freeze

The chosen configuration is written to `scripts/pvl_v1_freeze.json` and committed **before** any L1-R candidate is computed. The L1-R step refuses to run unless the file's git blob hash equals the committed one. On the host this is checked with git; in the container, `PVL_FREEZE_BLOB` carries the hash.

## 7. L1-R (brief §4)

New V2 runs with the frozen front-end, then the frozen linearity parameters, on three scans:
- **Pk266 2.6 GHz Rot00 and Pk266 1.5 GHz Rot90.** The prediction is ≥ 3 of 4 ducts carrying a linear track on **each** scan.
- **Pk401 1.5 GHz Rot90.** The prediction is 0 of 4 cuboids carrying one.

These are counts with n = 4, so they are **descriptive**. Step edges are reported for all three scans.
