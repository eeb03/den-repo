# Front-end Phase 2, arms B and C on BAM: results

**Verdict (brief §4, applied as written): STOP front-end work on this data.** On the 2.6 GHz Pk266 scans, the most favourable data, neither B nor C passes the per-scan G-REC condition. Neither arm passes the gates its continue route requires:
- **B** fails G-NULL, G-REC, G-ART and G-FREE.
- **C** fails G-CONT, G-ART and G-FREE.

No outcome calls for arm D, so **D is not indicated and was not run.**

Every result here is **EXPLORATORY** and **CONCRETE NDT ONLY**: all BAM scans were used in earlier research. No production code was changed. PRs #12–#16 stay unmerged.

**Not run** (outside the BAM-only approval):
- 4TU;
- the synthetic part of G-ART;
- the 4TU part of G-COST.

Those gates are **incomplete**. They are not counted as passed, and nothing below depends on them.

**Commits:**

| Commit | What it holds |
|---|---|
| `4078ebf` | the brief (unchanged) |
| `4e7b3b7` | the implementation note `docs/frontend-phase2-bc-protocol.md` and the code, committed before any run |
| `346d012` | the B and C freeze, committed before any holdout scan |
| (this commit) | these results |

## 1. Development selection (Pk266 1.5 GHz Rot00, all 161 lines)

**Arm B.** All 9 settings were admissible: artefact FP per line ≤ A's 0.84. Duct recall is listed as duct-1, 2, 3, 4.

| Setting | Artefact FP/line | FP/line | Median z* | Duct recall | Median recall |
|---|---|---|---|---|---|
| A | 0.84 | 2.60 | 44.2 | 0 / 0 / 0.24 / 0.05 | — |
| k = 1.5, w = 41 | 0.03 | 1.18 | 38.2 | 0 / 0 / 0.65 / 0.98 | 0.326 |
| k = 1.5, w = 81 | 0.06 | 1.48 | 39.1 | 0 / 0 / 0.72 / 0.99 | 0.360 |
| **k = 1.5, w = 161 (chosen)** | 0.08 | 1.61 | 37.0 | 0 / 0 / 0.83 / 0.98 | **0.413** |
| k = 2, w = 41 | 0.02 | 1.83 | 31.2 | 0 / 0.07 / 0.99 / 0.60 | 0.335 |
| k = 2, w = 81 | 0.04 | 1.48 | 38.5 | 0 / 0 / 0.69 / 0.01 | 0.004 |
| k = 2, w = 161 | 0.04 | 1.60 | 37.7 | 0 / 0 / 0.73 / 0.00 | 0.000 |
| k = 3, w = 41 | 0.01 | 1.95 | 32.1 | 0 / 0.07 / 0.78 / 0.00 | 0.033 |
| k = 3, w = 81 | 0.01 | 1.64 | 43.8 | 0 / 0 / 0.06 / 0 | 0.000 |
| k = 3, w = 161 | 0.01 | 1.86 | 41.7 | 0 / 0 / 0.07 / 0 | 0.000 |

A mute of k ≥ 2T removes shallow duct-4: its response at 61 mm lies inside the muted band.

**Arm C.** The null false-track rate, against the 0.1 per line budget, decided which configurations could be used:
- **G = 3:** no α in {0.3, …, 0.7} met the budget (rates 0.14–0.17), so all four G = 3 configurations were excluded.
- **G = 1:** only α = 0.7 met it (rate 0.075–0.093).

| Configuration (G = 1, α = 0.7) | Null rate | Artefact FP/line | FP/line | Duct recall | Median recall |
|---|---|---|---|---|---|
| **δx 0.25, δt 0.25 (chosen)** | 0.075 | 1.42 | 5.70 | 0 / 0.33 / 1.00 / 0.14 | **0.236** |
| δx 0.25, δt 0.5 | 0.075 | 1.41 | 5.68 | 0 / 0.33 / 1.00 / 0.10 | 0.215 |
| δx 0.5, δt 0.25 | 0.093 | 1.27 | 5.24 | 0 / 0.33 / 1.00 / 0.13 | 0.231 |
| δx 0.5, δt 0.5 | 0.093 | 1.26 | 5.22 | 0 / 0.33 / 1.00 / 0.09 | 0.211 |

## 2. Holdout results

**Per-object line recall, A → B → C.** Units are objects; lines are repeated measures.

| Scan | Object (median A z; detectable?) | A | B | C |
|---|---|---|---|---|
| Pk266 2.6 GHz Rot00 | duct-1 (3.7; no) | 0 | 0 | 0 |
| | duct-2 (26.5; yes) | 0 | 0 | 0.03 |
| | duct-3 (47.2; yes) | 0.71 | 0.91 | 0.85 |
| | duct-4 (66.5; yes) | 1.00 | 1.00 | 1.00 |
| Pk266 1.5 GHz Rot90 | duct-1 (1.9; no) | 0 | 0 | 0 |
| | duct-2 (19.1; yes) | 0 | 0 | 0 |
| | duct-3 (24.7; yes) | 0.12 | 0.93 | 0.79 |
| | duct-4 (28.2; yes) | 0.58 | 1.00 | 1.00 |
| Pk266 2.6 GHz Rot90 | duct-1 (2.3; no) | 0 | 0 | 0 |
| | duct-2 (25.4; yes) | 0 | 0 | 0 |
| | duct-3 (33.9; yes) | 0.67 | 0.83 | 0.88 |
| | duct-4 (37.5; yes) | 0.98 | 1.00 | 1.00 |
| Pk401 1.5 GHz Rot00 | cuboids 1 / 2 / 3 / 4 | 0 / 0 / 0.71 / 1 | 0 / 0 / 0.75 / 1 | 0 / 0 / 0.92 / 1 |
| Pk401 1.5 GHz Rot90 | cuboids 1 / 2 / 3 / 4 | 0 / 0 / 0.21 / 1 | 0 / 0 / 0.54 / 1 | 0 / 0 / 0.88 / 1 |

**False positives and threshold, per scan, A / B / C.** The z* column has no C value: C uses A's z*.

| Scan | Artefact FP/line | All-class FP/line | Median z* (A / B) |
|---|---|---|---|
| Pk266 2.6 Rot00 | 0.31 / 0.22 / 1.09 | 2.35 / 1.62 / 7.30 | 59.3 / 57.3 (−3%) |
| Pk266 1.5 Rot90 | 0.09 / 0.29 / 0.19 | 1.50 / 2.11 / 6.22 | 32.1 / 27.0 (−16%) |
| Pk266 2.6 Rot90 | 0.33 / 0.29 / 1.30 | 1.66 / 1.50 / 5.89 | 54.9 / 50.0 (−9%) |
| Pk401 1.5 Rot00 | 0.58 / 0.87 / 1.25 | 1.91 / 2.15 / 5.01 | 79.9 / 72.8 (−9%) |
| Pk401 1.5 Rot90 | 0.29 / 0.09 / 0.67 | 1.75 / 1.92 / 5.66 | 74.7 / 77.3 (+3%) |
| Pk050 1.5 Rot00 | 0.08 / 0.23 / 0.24 | 1.91 / 2.53 / 4.28 | 70.3 / 37.6 (−46%) |
| Pk050 1.5 Rot90 | 0.01 / 0.36 / 0.02 | 1.87 / 2.88 / 4.76 | 55.5 / 31.7 (−43%) |

**Cost.** Median CPU per line:
- **B:** 1.03× to 1.43× A's (largest on 2.6 GHz Rot00: 28.7 s against 20.1 s).
- **C:** growth adds < 0.03 s per line.
- **Peak memory** on one line: 37 MB.

## 3. Gates

| Gate | B | C |
|---|---|---|
| **G-REC** (pooled over holdouts where detectable; no object drops by more than 0.10) | **FAIL.** duct-2 0 → 0; duct-3 0.50 → 0.89; duct-4 0.85 → 1.00. Improves 2 of 3, sign p = 0.5 | **PASS, narrowly.** duct-2 0 → 0.011 (4 of 363 line-crossings); duct-3 0.50 → 0.84; duct-4 0.85 → 1.00. Improves 3 of 3, sign p = 0.125. No drops |
| **G-CONT** | FAIL (reported only): duct-2 has no detections, so its gap is 121 on every scan | **FAIL** on 0 of 3 scans: duct-2 gaps 112, 121, 121 |
| **G-ART** (BAM part only; **incomplete**) | **FAIL.** Rises against A on Pk266 1.5 Rot90, Pk401 Rot00 and both Pk050 scans | FAIL (reported only): 2.2× to 4.0× A's on every scan |
| **G-FREE** (Pk050 all-class FP/line ≤ A's) | **FAIL:** 2.53 and 2.88, against 1.91 and 1.87 | **FAIL:** 4.28 and 4.76, against 1.91 and 1.87 |
| **G-NULL** | **FAIL.** z* falls by ≥ 25% on both Pk050 scans (−46%, −43%) but on no Pk266 holdout (−3% to −16%) | PASS by construction: development null rate 0.075 |
| **G-COST** (BAM part only; **incomplete**) | PASS (BAM) | PASS (BAM) |
| **G-FREQ/POL** | **FAIL** on 0 of 3 scans | **FAIL** on 0 of 3 scans |

**No gate is a significance claim.** With at most 3 detectable ducts, the smallest sign-test p is 1/8.

## 4. Applying the brief's §4 mapping

The rows are checked in order:

1. *B passes G-NULL and G-REC, and C fails G-CONT.* **No.** B fails both G-NULL and G-REC.
2. *C passes G-CONT and G-REC without breaching G-ART or G-FREE.* **No.** C fails G-CONT, G-ART and G-FREE.
3. *B and C both pass, and D passes.* **No.** D is not indicated.
4. *Both fail G-REC, but G-NULL shows z\* falling.* **No.** C passes pooled G-REC, and on Pk266 z* does not fall by 25%.
5. *Nothing passes G-REC on 2.6 GHz Pk266.* **Yes, as written.** The per-scan G-REC condition fails on both 2.6 GHz scans, for both arms:
   - duct-2 is detectable (median z 25–27) but has 0 recall in A and B on both scans, and 0 in C on Rot90;
   - on Rot00, C fails only because duct-4 is already at 1.00 in A and cannot strictly improve.

→ **STOP front-end work on this data.** Recommend a **new acquisition** (brief §3), and assess **another sensing strategy**: multi-channel or array GPR, or EMI/RF locators for metallic utilities.

**How sensitive this mapping is** (stated because it bears on the decision):
- The per-scan "every detectable duct improves" rule has a **ceiling defect**: an object already at 1.00 in A cannot strictly improve.
- Under a ceiling-tolerant reading, C would meet the recall condition on 2.6 GHz Rot00. It would do so through **4 detected lines of duct-2**, with artefact FP/line 1.09 against A's 0.31.
- Row 5 would then not trigger, and **no row would match**. That leaves the mapping undetermined, not a continue.
- Rows 1 and 2 fail for reasons the ceiling does not touch (G-NULL, G-CONT, G-ART, G-FREE). **No reading of the gates supports continuing with B, C or D.**

## 5. What the data show (descriptive; selects nothing)

1. **B's recall gains are real on the bright ducts, but they are not a threshold effect.**
   - The lateral running median raises duct-3 recall from 0.12 to 0.93 on Pk266 1.5 Rot90, and pooled from 0.50 to 0.89. On Pk266, z* barely moves (−3% to −16%).
   - So on Pk266 the gain comes from cleaner object z, not from a lower threshold.
   - On Pk050 the opposite happens: z* halves (−46%, −43%) and FPs rise (G-FREE fails). Pk050 has rebar, anchors and a stepped back wall; it is **not empty**.
   - H-B ("z* inflated by structured background") is **supported on Pk050, not on Pk266**.
2. **duct-2 is the decisive object, and no arm reaches it.** It is detectable (median z 18–27, against z* of 27–59) on every Pk266 scan, yet it gets 0 lines in A and B. C reaches 0.33 on the development scan but only 0.01 on the holdouts. **It stays threshold-limited.**
3. **C grows clutter faster than it grows objects.**
   - All-class FP/line rises 2.2× to 4.1× against A; artefact FP 2.2× to 4.0×.
   - On the development scan, C's "other" rises from 243 to 524, and 121 of those are object ringing.
   - The null budget forces α = 0.7, close to the seed threshold. At that α, growth mostly extends tracks that were already detected (duct-3, duct-4, cuboid-3) and adds their ringing and the planar events.
4. **Frequency and polarisation remain strong levers, as in Phase 1.**
   - At 2.6 GHz, A already reaches 0.71 and 1.00 on duct-3 and duct-4 (Rot00).
   - At 1.5 GHz Rot90, A reaches 0.12 and 0.58; at 1.5 GHz Rot00, 0.24 and 0.05.
   - These are acquisition choices, not front-end choices.
5. **duct-1 and cuboid-1 are statistic-limited** (median z < 6). **cuboid-2 is detectable** (median z 19–21) but has 0 recall under every arm; like duct-2, it stays threshold-limited.

## 6. Deviations

- **D1: two "other" subclasses can never fire** (protocol §1, brief §2.4).
  - `backwall_multiple` (t ≈ 2t_bw − t₀) always lies beyond t_bw + T, so `_classify` labels it `below_back_wall` first.
  - `step_edge_tail` requires |x − edge| ≤ 60 mm, which `_classify` labels `step_edge` first.
  - So the "other" decomposition only separates `object_ringing` from `other_residual`. The multiple-reflection and step-edge populations are counted inside `below_back_wall` (and so inside artefact FP) and inside `step_edge`.
  - This was found after the run. It is **recorded, not repaired**, and it affects no gate.
- **D2: per-scan G-REC ceiling** (above). Recorded, not repaired. Its effect on the mapping is set out in §4.
- No other departure from the implementation note.

## 7. Tests

The full suite passes in the test image with the repository mounted: **3,227 tests**, including 4 in `tests/test_frontend_phase2.py`.

## 8. Artifacts

- `artifacts/frontend_feasibility/phase2/`: `dev_b.json`, `dev_c.json`, `holdout.json` (per-scan scores for A, B and C, plus gates).
- Logs: `artifacts/frontend_feasibility/phase2_*.log`.
- Copies are in `evidence/frontend_feasibility/phase2/`.
- Reproduce with `python -m scripts.frontend_phase2 {dev-b,dev-c,freeze,holdout} --workers 6`, in the test image with `FREEZE_BLOB` and `FE2_FREEZE_BLOB` set.
