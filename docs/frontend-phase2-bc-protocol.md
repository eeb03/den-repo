# Front-end Phase 2, arms B and C on BAM: implementation note (frozen before any run)

**Status:** FROZEN. This file and `scripts/frontend_phase2.py` were committed **before** any Phase 2 computation. The brief, `docs/candidate-frontend-feasibility-brief.md` (commit `4078ebf`), is unchanged. This note fixes the operational details the brief leaves open. Where it narrows a phrase in the brief, it says so.

**Scope:**
- **Run:** arms A, B and C, on BAM only.
- **Not run:**
  - **arm D**, which the brief allows only if B and C each pass, and which needs separate approval;
  - the **4TU regression check** and the **synthetic part of G-ART**, because the approval covers BAM only.
- Gates that depend on those parts are reported as **incomplete**, not as passed.
- Every result is **EXPLORATORY** and **CONCRETE NDT ONLY**.
- No production code changes.

## 1. Common to all arms

**The front-end.** V2 (A3), freeze `simulation/hyperbola_v2_freeze.json` (09dc288). Per line, the steps are:
1. canonical input;
2. t̂₀ = `estimate_time_zero` on the **raw** canonical traces;
3. the background step (which depends on the arm);
4. `stack_line`;
5. `null_peaks`, on the **same** background-processed traces, with identity `bam:{spec}_{scan}:L{j}` (the PR #13 seeding);
6. z* = `calibrated_threshold` (λ₀ = 0.25);
7. `group`.

**Scoring** (truth used only here). A detection at canonical (x, t) on line j is classified by `scripts.ccd_v1_stage1._classify`, the CCD-V1 Arm D rules, using the stored known-geometry calibration of its scan. The classes are `object` (with an object id), `back_wall`, `below_back_wall`, `direct`, `step_edge`, `edge_rebar_zone` and `other`.

**Brief §2.4: decomposing "other"** (fixed now). In order:

| Subclass | Rule |
|---|---|
| `backwall_multiple` | within T of t₀ + 2(t_bw − t₀) for the detection's step |
| `step_edge_tail` | \|x − edge\| ≤ 60 mm for some edge at 500, 1000 or 1500 mm, and t ≥ the smaller back-wall time of the two adjacent steps |
| `object_ringing` | within ±100 mm of an object's x (and, for cuboids, \|y − y_obj\| ≤ 60 mm), with t in (t_e + T, t_e + 3T] |
| `other_residual` | otherwise |

**Per-object metrics** (units are objects; lines are repeated measures). An object is detected on a crossing line if a detection classified `object` with that object's id lies on the line.
- **line recall:** detected lines ÷ crossing lines;
- **longest run** and **longest gap**, in lines, over its crossing lines in Y order;
- **runs:** the number of maximal detected runs.

**Detectable objects** on a scan are those whose median arm-A z at the crossing (the Phase 1 definition) is ≥ 6.

**Artefact FP per line.** (`direct` + `below_back_wall`) ÷ 161 lines.

**FP per line.** All non-`object` detections ÷ 161.

## 2. Arm B: artefact-aware preprocessing

The background step is a **lateral running median** over w traces, then an **early-time mute**:

- bg = tr − median_filter(tr, size = (w traces, 1 sample), mode = `nearest`).
- The mute ends at t_m = t̂₀ + k·T. The weight is 0 for t ≤ t_m − 0.5T, rises by a raised cosine to 1 at t_m, and is 1 afterwards. bg is multiplied by this weight.
- The stack, the null, `StackContext` and grouping all receive this bg. t̂₀ is still estimated from the **raw** traces.

**Grid:** k ∈ {1.5, 2, 3}; w ∈ {41, 81, 161} traces.

**Selection** on the development scan (Pk266 1.5 GHz Rot00, all 161 lines):
1. **Admissible** if artefact FP per line ≤ arm A's on the same scan.
2. Maximise the **median line recall over the 4 Pk266 ducts**.
3. **Ties:** larger k, then larger w.

If no setting is admissible, arm B is recorded as **failed at selection** and is **not run** on the holdouts.

## 3. Arm C: cross-line hysteresis

C uses arm A's own outputs on every line: the z and v̂ maps, z*_j, and the kept detections, which are the **seeds**.

**Growth (breadth-first from each seed track):**
- For each member (line j, sample s, trace i, velocity v), and each line j′ = j ± 1 … ± G not yet in the track:
  - **Window:** traces with |x − x_i| ≤ δx·λ̂ (λ̂ = v/f, or the line-median finite v̂ if v is not finite), and samples with |t − t_s| ≤ δt·T.
  - If a seed on j′ lies inside the window, it **joins** the track and is marked as used.
  - Otherwise, if the maximum of z_j′ over the window is ≥ α·z*_j′, a **grown member** is added at the argmax, with v = v̂ there.
- Each track holds at most one member per line. Growth continues until nothing more can be added.

**The output** per line is the seeds plus the grown members. A grown member within 1 sample and 1 trace of an existing detection on its line is dropped.

**The permutation null for α** (development scan only; no truth):
- For each line, permute its arm-A background traces with a generator seeded by sha256(`C-null:bam:{spec}_{scan}:L{j}`).
- Recompute the stack, then take seeds = `group(detections_at(z_perm, v_perm, z*_j))`, using the **real** line's z*_j. Grow with the same rules.
- A **false track** is a track spanning ≥ 2 lines.
- **Rate** = false tracks ÷ 161 lines.
- For each (G, δx, δt), α is the **smallest** value in {0.3, 0.4, 0.5, 0.6, 0.7} with rate ≤ 0.1. If none qualifies, that triple is excluded.

**Grid:** G ∈ {1, 3}; δx ∈ {0.25, 0.5}; δt ∈ {0.25, 0.5}.

**Selection:** maximise the development median duct line recall. Ties go to the smaller G, then the smaller δx, then the smaller δt.

## 4. Freeze

The chosen B and C configurations are written to `scripts/frontend_phase2_freeze.json` and committed **before** any holdout scan is processed. The holdout stage refuses to run unless the file's blob hash equals the committed one: git on the host, `FE2_FREEZE_BLOB` in the container.

## 5. Holdout scans and gates (brief §2.3, BAM part)

**Holdout scans:**
- Pk266: 2.6 GHz Rot00, 1.5 GHz Rot90 and 2.6 GHz Rot90;
- Pk401: 1.5 GHz Rot00 and Rot90;
- Pk050: 1.5 GHz Rot00 and Rot90.

The development scan is reported separately.

| Gate | Operational definition | Arms |
|---|---|---|
| **G-REC** | For each Pk266 duct that is detectable on ≥ 1 Pk266 holdout scan: line recall pooled over the holdout scans **where it is detectable** must be > A's. In addition, no object (any duct; cuboids pooled over the two Pk401 holdouts) may fall by more than 0.10 | B, C |
| **G-CONT** | On ≥ 2 of the 3 Pk266 holdout scans, every detectable duct has its longest gap ≤ 10 lines **and** runs ≤ max(A's runs, 1) | C (B reported) |
| **G-ART (BAM part)** | Artefact FP per line ≤ 0.5 × A's on every holdout scan. **The synthetic part is not run, so G-ART is reported as BAM-only and incomplete** | B (C reported) |
| **G-FREE** | All-class FP per line on each Pk050 holdout ≤ A's | B, C |
| **G-NULL** | **B:** the median z* over all lines falls by ≥ 25% against A on both Pk050 holdouts and on every Pk266 holdout. **C:** the development null false-track rate is ≤ 0.1 per line (true by construction; the value is reported) | B, C |
| **G-COST** | Median CPU per line ≤ 2 × A's. For C, its growth time is added to A's per-line cost. The `tracemalloc` peak on one line must be ≤ 1 GB. **The 4TU part is not run, so G-COST is BAM-only** | B, C |
| **G-FREQ/POL** | On ≥ 2 of the 3 Pk266 holdout scans (frequency × rotation), the per-scan G-REC condition holds (every duct detectable on that scan improves, and no object drops by more than 0.10) **and** the per-scan G-ART condition holds. The brief's "≥ 3 of 4" counted the development scan, which is reported separately | B, C |

**Sign tests.** "Improves on k of n detectable ducts" carries an exact one-sided sign-test p. With n ≤ 3 the smallest p is 1/8, so **no gate is a significance claim.**

**Outcome mapping** (brief §4) is applied exactly. Any outcome that would call for D is reported as "**D indicated, needs approval**".
