# Plan-View Linearity V1: research phase brief

**Status:** BRIEF FOR REVIEW. Nothing in it has been implemented or run. **Approval is needed before any code or analysis.**

**Branch:** `research/plan-view-linearity-v1`, from `research/coherent-clutter-discrimination-v1` (PR #14, draft). PRs #12, #13 and #14 stay unmerged, no production code changes, and CCD-V1 Stage 2 stays on hold.

**Written:** 2026-10-13.

**Origin.** This is option (b) of `docs/ccd-v1-stage0-1-results.md` §3. It responds to the one CCD-V1 feature that showed promise (line-to-line continuity, F8) and to the finding that limits it: **at real detector candidates, planar reflectors are more continuous than targets.** On BAM, back-wall and layering runs were 205–765 mm, against 30–40 mm for ducts.

**What was looked at while writing this.** These counts come from the existing Stage 0d output (`evidence/ccd_v1/stage0d_fourtu_geometry.json`) and the 4TU `Metadata.csv`. Marginal counts only; no detector output was related to any field:

| Item | Count |
|---|---|
| Activities with parallel paths | 48 |
| `.sgy` paths in those activities | 315 |
| Trench utility count recorded | 45 (3 unrecorded) |
| Trench-empty | **1** |
| Rubble present / absent | 9 / 39 |
| "Utility path linear" yes / no / blank | 38 / 7 / 3 |

---

## 1. Question

Can a **plan-view linearity** measure, computed only from radar data and survey geometry, tell responses that are long along one axis and narrow across it (utility-like) from **compact** responses (stones, voids, rubble) and **planar** responses (layers, back walls, road base)?

And can it do so **without ground truth at inference**, on the candidates the existing experimental front-end actually produces?

**What it would add.** The roadmap's Phase 6 candidate card already names *spatial coherence* and *cross-line consistency* as evidence dimensions. This experiment measures whether "cross-line linear" can be computed honestly and whether it carries any information on real data. **It is a feature experiment, not a detector.**

---

## 2. What is already known (do not re-derive)

| Fact | Source |
|---|---|
| At known positions, continuity separates 3 of 4 ducts (600 mm runs) from cuboids (110–140 mm) and from no-object positions (15–70 mm); exact p = 0.029 at n = 4 + 4 | CCD-V1 Stage 1, H6 |
| It fails on the deepest, weakest duct (135 mm) | same |
| At V2 candidates, ducts give **short** runs (median 40 mm) because V2 finds a duct only intermittently from line to line; planar responses give **long** runs | CCD-V1 Arm D |
| The polarity and polarisation features are unsupported; do not reuse them here | CCD-V1 §3 |
| 4TU paths: median length 5.5 m; parallel pairs separated by a median 1.04 m (10–90%: 0.37–1.83 m); **registration accuracy undocumented** | CCD-V1 Stage 0d |
| 4TU amplitude preservation is `unknown` | CCD-V1 Stage 0c |
| V2 (A3, freeze 09dc288) reproduces bit-for-bit on BAM | CCD-V1 Arm D |

**Physical reasoning.** The three response shapes differ in plan view:

- **A linear object crossing a set of parallel lines** produces one compact apex per line. In plan view the apexes form a straight track: consistent two-way time (if the depth is constant), a steady lateral drift (set by the crossing angle), and a narrow in-line footprint.
- **A planar reflector** produces an event that is wide *within* each line as well as continuous *across* lines.
- **A compact object** is narrow in both directions.

Linearity therefore needs **two** measurements: extent along the track (L) and in-line width (W). Continuity alone (L) cannot separate linear from planar. That is exactly what Arm D showed.

**Known blind spots, which no linearity measure on these data can remove:**

1. **Lines parallel to the object.** A linear object running *along* the survey lines looks like an in-line flat event, the same as a planar reflector. Every BAM line runs along X, so BAM's edge rebar (also along X) falls in this blind spot. Only an orthogonal grid removes it.
2. **Linear geology and structure.** Step edges, kerbs, drains, fracture traces and buried walls are also linear. **Linearity separates linear from compact and planar. It does not separate utilities from other linear features.** BAM's back-wall step edges (along Y, at X = 500, 1000 and 1500 mm) are a built-in example: a linear non-utility diffractor.
3. **Depth-varying utilities** break the constant-time assumption over long tracks. The time tolerance applies between neighbouring members, not across the whole track.

---

## 3. Definitions (forms fixed now; parameters chosen in L1 from the grids below)

### 3.1 Candidates

The candidates are the detections of V2 (A3) with the committed freeze (09dc288), run per line exactly as in PR #13 and CCD-V1. **The front-end is not modified.** On BAM, the stored CCD-V1 Arm D detections (1.5 GHz Rot00, three specimens) are reused. New A3 runs are added only for Pk266 2.6 GHz Rot00, Pk266 1.5 GHz Rot90 and Pk401 1.5 GHz Rot90 (§4, L1-R).

### 3.2 In-line width W (per candidate)

- Take the line's trace data with **no lateral background removal**, so planar events survive: dewow only (subtract a running mean over 1 period).
- At the candidate's sample, take the Hilbert envelope along x, smoothed over ±0.25 T.
- W is the contiguous half-maximum width around the candidate's trace, in units of λ̂ = v̂/f. Here v̂ is the candidate's own V2 velocity estimate, or the line median v̂ if the candidate has none.
- **No truth velocity is used.**

### 3.3 Linking into tracks

The positions are:
- **BAM:** grid (x, y); lines are Y positions 5 mm apart.
- **4TU:** each path's trace positions are projected into one local frame per activity, built from the decoded NMEA fixes (Stage 0d). Each candidate gets (e, n) and a path id.

**Linking rule (greedy).** Candidates are processed in order of descending |z|. A candidate joins an existing track if all of these hold:
- it lies on a line or path not yet in the track;
- its line is within G lines of the track's last member (BAM), or its path is parallel to and within 2 m of a member's path (4TU);
- its lateral position is within δx of the track's predicted position. That prediction is a straight-line fit through the members, or, for a single member, the member's own position with tolerance widened by the maximum crossing angle (§3.5);
- its two-way time is within δt of its nearest member.

Otherwise it starts a new track.

### 3.4 Track descriptors

| Symbol | Definition | Unit |
|---|---|---|
| L | extent of the members along the track direction | λ̂ |
| n_lines | number of distinct lines or paths in the track | count |
| s | RMS residual of the members' straight-line fit (defined for ≥ 3 members) | λ̂ |
| W_med | median of the members' W | λ̂ |

### 3.5 Three-way rule (per track; members inherit the label)

| Label | Condition |
|---|---|
| **planar** | W_med > W* |
| **linear** | W_med ≤ W*, **and** L ≥ L*, **and** n_lines ≥ 3, **and** s ≤ s* |
| **linear-2** | 4TU only: W_med ≤ W*, exactly 2 paths, and links within the angle tolerance. **Counted separately and judged only against the null**, because two points always define a line |
| **compact** | everything else |

**Fixed now, not tuned:**
- maximum crossing angle 60° from the path normal;
- s* = 0.5 λ̂.

**Parameter grid (chosen in L1 on BAM development data only):**

| Parameter | Values |
|---|---|
| G (BAM gap) | {1, 3, 5} lines |
| δx | {0.1, 0.25, 0.5} λ̂ |
| δt | {0.25, 0.5} T |
| L* | {2, 3, 4} λ̂ |
| W* | {1, 2, 3} λ̂ |

That is 162 configurations.

**4TU registration allowance.** BAM has no position error. Its δx is therefore applied on 4TU **plus a fixed registration allowance of 0.5 m**. This allowance is fixed now from Stage 0d's median parallel-pair separation scale, not tuned. Sensitivity is reported at 0.25 m and 1.0 m.

---

## 4. Experiment

### L1: development and freeze on BAM (all exposed; this is fitting, not validation)

**Selection data.** Pk266, Pk401 and Pk050 at 1.5 GHz Rot00, using the stored Arm D candidates.

**Object classes, from `evidence/bam/specimen_ground_truth.csv`. Used for selection only.**

| Class | Members | n |
|---|---|---|
| Linear, crossing | 4 ducts | 4 |
| Compact | 4 cuboids | 4 |
| Linear, non-utility | the 3 back-wall step edges per specimen (Pk266, Pk401, Pk050) | 9 |
| Planar | back-wall candidates (CCD-V1 Arm D class `back_wall`) | per candidate |
| Blind spot | edge rebar parallel to the lines | reported, not scored |

**Selection rule**, applied in order:
1. **Admissible** if every duct carries a linear track within ±100 mm of its x, **and** no cuboid carries one within ±100 mm and ±60 mm of its (x, y).
2. Among admissible configurations, choose the one that maximises the fraction of back-wall candidates labelled planar.
3. Break ties by the smallest δx, then the smallest G, then the largest L*.

**If no configuration is admissible: STOP** (§6).

**Freeze.** The chosen configuration, and the W and linking code, are committed with a blob-hash check (as in PR #13) **before** L1-R or any 4TU candidate is computed.

### L1-R: replication on BAM scans not used for selection (exposed specimens, unused scans)

Same specimens, different acquisitions:
- Pk266 2.6 GHz Rot00: new A3 run;
- Pk266 1.5 GHz Rot90: new A3 run, with the frozen parameters.
- Pk401 1.5 GHz Rot90: new A3 run, for the cuboid check.

**Prediction:** ≥ 3 of 4 ducts carry a linear track on each scan. With n = 4 this is descriptive, and it is labelled **EXPLORATORY: the same specimens**. Step edges are reported: the predicted outcome is linear, which illustrates blind spot 2.

### L2: association on 4TU (frozen parameters; never tuned on 4TU)

**Data.** The 48 activities with parallel paths (Stage 0d; 315 paths). Exact-duplicate radargrams are removed first with `scripts/audit_benchmark_leakage.py`.

**Exposure.** About 40 of the 759 4TU files had A3 candidate *counts* computed in PR #12 and PR #13. No linearity, track or plan-view analysis has ever been run on 4TU, and no detector output has been related to these activities' metadata.

**Per-activity measures:**
- the number of linear tracks per 10 m of surveyed path;
- the number of linear-2 links per 10 m;
- the density of compact clusters;
- the density of planar tracks;
- the **excess** of each over its activity-level null (§5.1).

**Units.** One activity is one unit (n = 48). Paths within an activity are not independent units.

---

## 5. Pre-registration

### 5.1 The null: chance alignment

For each activity, 99 draws. In each draw, every path's candidates get an **independent random circular shift along that path's own track**: uniform over the path length, with times and W unchanged. Linking and labelling are then re-run.

This keeps each path's candidate count, times and in-line widths, and destroys any cross-path alignment. **It needs no ground truth and no re-detection.**

From the draws:
- excess = observed − null mean;
- per-activity p = (1 + #{null ≥ observed}) / 100;
- corpus-level p from the 99 summed null totals.

**Paths shorter than 2 m cannot be shifted meaningfully.** They are kept unshifted, and this is recorded.

### 5.2 Hypotheses

| ID | Data | Statement | Test | Bar |
|---|---|---|---|---|
| **L1** | BAM dev | an admissible configuration exists (§4) | selection rule | gate for everything below |
| **L1-R** | BAM, unused scans | ≥ 3 of 4 ducts linear on each of the two replication scans; 0 of 4 cuboids linear on Pk401 1.5 GHz Rot90 (also computed) | counts | descriptive, n = 4 |
| **L2a** | 4TU | pooled linear-track excess > 0 | corpus-level permutation p (99 draws) | p ≤ 0.05 |
| **L2b** | 4TU | per-activity linear-track excess per 10 m rises with the trench utility count (n = 45 recorded) | Spearman ρ, one-sided, exact permutation p (9,999 relabellings); 95% bootstrap CI over activities | ρ > 0, p ≤ 0.05 |
| **L2c** | 4TU | linearity adds to raw density: L2b holds after controlling for the activity's total candidate density | partial Spearman, permutation p | reported; strengthens or weakens L2b |
| **L2d** | 4TU | discriminant check: rubble activities (9 vs 39) do **not** show higher linear-track excess, though they may show higher compact density | exact Mann–Whitney, two-sided, both measures | descriptive (n = 9) |
| **L2e** | 4TU | "Utility path linear" yes (38) vs no (7) | exact Mann–Whitney | descriptive (n = 7) |

**Power, stated now.**
- L2b with n = 45 has about 80% power to detect ρ ≈ 0.41 (α = 0.05, one-sided ≈ 0.37). **A null result cannot rule out a weak association.**
- L2d and L2e are too small for anything but description.
- **No presence-versus-absence test is possible**: only 1 of the 48 activities is trench-empty.

### 5.3 Controls

1. **The chance-alignment null** (§5.1) for every 4TU measure.
2. **Registration sensitivity.** L2a and L2b are recomputed with the allowance at 0.25 m and 1.0 m, plus one draw of ±0.5 m random positional jitter per path. A result that holds only at one allowance is reported as **fragile**.
3. **A density baseline.** Raw candidate density per 10 m is put through the same L2b test, so linearity is credited only for what it adds (L2c).
4. **The planar check.** On 4TU, the fraction of candidates labelled planar is reported per activity. If more than 80% of candidates are planar on most activities, the front-end is dominated by layering, and L2 is uninformative.
5. **Duplicates** are removed before any count.

### 5.4 Leakage safeguards

- **Parameters are selected only on BAM 1.5 GHz Rot00** and frozen (blob hash) **before** L1-R and before any 4TU candidate is computed.
- **4TU metadata is read only by the scoring step after the freeze.** The linking and labelling code takes no metadata input. A unit test asserts this.
- **No synthetic data is used anywhere.** No result is labelled field accuracy.
- **The 4TU trench caveat travels with every L2 number.** The trench count is what the trial trench found, not what lies under the paths. L2 is an **association**, not a detection rate.

### 5.5 Computational limits (zero-budget plan, local Docker, 6 CPUs)

| Step | Budget |
|---|---|
| L1 (stored candidates; W computation and the 162-configuration grid) | ≤ 1 h |
| L1-R (three new A3 runs, 161 lines each) | ≤ 1.5 h |
| L2 A3 on 315 4TU paths | ≤ 4 h CPU. PR #13 measured a median of 11 s per 4TU path, but the 7,130-trace path took 428 s. Paths over 30 min are skipped and listed |
| L2 nulls (re-linking only, 99 × 48 activities) | ≤ 1 h |

**There is no new simulation and no GPU.** An overrun of more than 1.5× stops the step for review.

---

## 6. Decision criteria

| Outcome | Decision |
|---|---|
| **L1 fails** (no admissible configuration on the cleanest data available) | **STOP.** Plan-view linearity cannot be extracted from the current candidate front-end. V2 finds ducts too intermittently. The lever is front-end recall across lines (CCD-V1 option (a)), not a linearity feature |
| L1 passes, **L1-R** shows < 3 of 4 ducts on either replication scan | Linearity is acquisition-specific even on one specimen. **Do not run L2**; report |
| L1 and L1-R pass, **L2a fails** (no excess over chance alignment) | **PIVOT to acquisition.** The 4TU geometry (about 1 m line spacing, unverified registration, short paths) cannot support plan-view linking. A registered grid at ≤ λ/2 spacing over known utilities is the only test left |
| L2a passes, **L2b fails** | Linear structure exists beyond chance, but it does not track trench utility counts. This is consistent either with linear non-utility features (blind spot 2) or with the trench-scope mismatch. **Undecidable on these data.** Keep linearity as a descriptive evidence dimension only |
| **L2a and L2b pass**, and L2b survives the L2c density control and the registration sensitivity | **CONTINUE.** "Cross-line linear (N lines)" becomes a candidate evidence dimension, **experimental**, with its measurability state. Next: a registered multi-line acquisition, pre-registered with located utilities and located linear non-utilities, to test utility versus linear geology |

**Whatever the outcome:**
- **No utility label.** Linearity can support "linear, utility-like geometry". It cannot support "utility".
- **No promotion to production** from this phase.

---

## 7. What is reused, and what is not

| Reused | How |
|---|---|
| V2 front-end (A3, freeze 09dc288) | candidates, unchanged |
| CCD-V1 Arm D BAM detections | L1 selection input, read-only |
| Stage 0d geometry decoder and parallel-pair list | 4TU frame and activity set |
| Exact statistics (`scripts/ccd_v1_stats.py`), FREEZE_BLOB check, leakage audit | as is |

**Not reused:** the F1 polarity and F7 polarisation features (unsupported); synthetic corpora (2D cannot represent plan view); any threshold tuned on 4TU.

---

## 8. Why this, and not something larger

- **It is the only promising feature left from CCD-V1, and it needs no new data to test, cheaply.** About 7 h CPU on held data, with no simulation and no hardware.
- **It answers a question the acquisition decision depends on.** If plan-view linking cannot be made to work even on BAM's 5 mm grid, a registered field grid would not rescue it. If it works on BAM but not on 4TU, the gap is survey geometry, and that specifies what a field acquisition must provide: line spacing, registration accuracy and an orthogonal grid.
- **It feeds the 3D roadmap directly.** Linking candidates across lines into tracks is the first step of M2's grid-to-volume object building, whatever the result.

---

## 9. Recommendation

**Proceed with L1 and L1-R first**, about 2 h on BAM, and stop for review if L1 fails. Run L2 only if L1 and L1-R pass.

The most likely outcomes are L1 passing on BAM (5 mm lines, strong ducts) and L2 being limited by 4TU's geometry. Even then the experiment earns its cost: it turns "we need better data" into a measured specification of *which* data — line spacing, registration and grid orientation — before anything is acquired.
