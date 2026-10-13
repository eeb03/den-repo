# Plan-View Linearity V1, L1 and L1-R: results

**Verdict: STOP at L1.** No configuration in the pre-registered grid is admissible. By the brief's own rule (§4, §6), **L1-R was not run** and no freeze file was written. **L2 (4TU) is not run.**

Every result here is **EXPLORATORY** and **CONCRETE NDT ONLY**: all BAM specimens were used in earlier research. No production code was changed. PRs #12–#15 stay unmerged, and CCD-V1 Stage 2 stays on hold.

**Commits:**

| Commit | What it holds |
|---|---|
| `f36baea` | the brief (unchanged) |
| `78db64a` | the implementation note `docs/pvl-v1-l1-protocol.md`, `scripts/pvl_v1.py` and the tests, committed **before** any run |
| (this commit) | these results |

## 1. What ran

| Step | Result |
|---|---|
| **N1: candidate re-run.** V2 (A3, freeze 09dc288) re-run on Pk266, Pk401 and Pk050 at 1.5 GHz Rot00 to recover per-candidate velocity estimates | Reproduced the stored CCD-V1 Arm D detections **exactly**: 484 / 353 / 308, the same line, x, t and \|z\| for every detection. About 9 min on 6 workers |
| **L1 selection.** All 162 grid configurations (G × δx × δt × L* × W*), scored by the frozen rule | **0 admissible.** About 9 s |
| L1-R | **not run** (STOP) |

## 2. The result

| Across all 162 configurations | Value |
|---|---|
| Ducts carrying a linear track | **0 of 4 in every configuration** |
| Cuboids carrying a linear track | 0 of 4 in every configuration (trivially, because almost nothing was labelled linear) |
| Back-wall candidates labelled planar | 0.991–1.000 |

The admissibility rule needed all 4 ducts. **No configuration reached even 1.**

## 3. Why: post-hoc diagnosis (descriptive; selects nothing)

`scripts/pvl_v1_l1_diagnosis.py` produces `artifacts/pvl_v1/l1_stop_diagnosis.json`. It reports W by CCD-V1 Arm D class and the tracks near each duct at the most permissive grid point (G = 5, δx = 0.5, δt = 0.5, L* = 2, W* = 3). **It was run after the STOP and changes no decision.**

**Cause 1: the front-end finds each duct on too few lines (the line-to-line recall of V2).** Lines carrying a V2 candidate within ±100 mm and ±1T of each duct, out of 161:

| Duct (top depth) | Lines with a candidate | Longest track near the duct (permissive point) |
|---|---|---|
| duct-1 (241 mm) | **0** | none |
| duct-2 (181 mm) | 6 | 5 lines, L = 0.64 λ̂ (compact) |
| duct-3 (118 mm) | 43 | 19 lines, L = 2.76 λ̂ (labelled planar: W = 3.4) |
| duct-4 (61 mm) | 17 | 24 lines, L = 3.0 λ̂ (labelled planar: W = 50) |

Even where V2 does find a duct, its candidates are gappy: the gaps exceed G = 5 lines (25 mm), so the tracks fragment. **A linearity measure cannot link what the front-end does not find on adjacent lines.**

**Cause 2: W, as the brief defines it, measures the background under a candidate, not the candidate.** W is the half-maximum width of the dewow-only envelope (no lateral background removal), chosen so that planar events would survive. The same choice lets **everything flat underneath a compact response** set its width. Median W by class at 1.5 GHz:

| Class | Pk266 | Pk401 | Pk050 |
|---|---|---|---|
| direct-wave band | 50.0 (the whole line) | 50.0 | 50.0 |
| object (ducts or cuboids) | 4.1 (IQR 3.1–31) | 8.8 (IQR 5.0–50) | — |
| back wall | 16.4 | — | 12.0 |
| other | 13.4 | 5.7 | 11.8 |
| edge-rebar zone | 12.9 | 0.8 | — |

- **The object candidates are wider than the grid's largest W\* (3λ̂).** Shallow duct-4 sits on the direct wave and gets W = 50. **The three-way rule therefore labels true crossings as planar.**
- The near-perfect "back wall → planar" score is uninformative, because nearly every candidate is planar.

**Neither cause is a parameter problem within the pre-registered ranges:**
- Cause 1 needs more line-to-line recall from the front-end. It is not fixed by a larger G, because duct-1 has no candidates at all.
- Cause 2 needs a different **definition** of W, not a larger W*. A W* large enough to admit the duct candidates (Pk266 object IQR up to 31 λ̂; duct-4 at 50) would also admit the back wall (median 16.4 λ̂ on Pk266) and the "other" responses (13.4 λ̂) as non-planar, and the discrimination would be lost.

## 4. Decision (brief §6, applied as written)

> **L1 fails → STOP.** Plan-view linearity cannot be extracted from the current candidate front-end; the lever is front-end recall across lines (CCD-V1 option (a)), not a linearity feature.

The diagnosis adds a second, independent reason: **the in-line width definition is not fit for purpose on raw data.** Any revival of the linearity idea would therefore need **both** of the following, as new pre-registrations:

1. **A front-end with line-to-line recall.** On BAM, V2 detects 0–43 of 161 duct crossings. The CCD-V1 Stage 1 oracle measurements show the ducts *are* visible on most lines when looked for at their known positions (F8 runs of 600 mm on 3 of 4 ducts). The signal is in the data; the candidate generator does not report it consistently.
2. **A width measured on a locally background-referenced response.** For example, subtract a lateral reference taken at the same time from neighbouring traces, as CCD-V1's object response did, while still keeping planar events identifiable. This needs its own definition and test. Brief §3.2 cannot be amended after these results.

**What this STOP does not show:**
- It does **not** show that plan-view linearity is physically uninformative. At oracle positions (CCD-V1 H6) continuity separated 3 of 4 ducts from compact cuboids.
- It does not test 4TU at all.

It shows that **with the current front-end and this W definition**, the feature cannot be computed honestly from detector output on the cleanest real grid available.

**Consequence for the roadmap.**
- Every route tried in this programme now converges on the **candidate front-end**:
  - V2's false positives are 55% noise and system artefacts (CCD-V1 Stage 0);
  - its line-to-line recall is too sparse to link (here).
- The next defensible step is a **front-end experiment, pre-registered under Task A**, with explicit line-to-line recall and artefact gates. Alternatively, acquire data where that can be measured on soil.

## 5. Deviations

**None from the implementation note.** The brief's §3.2 W definition was implemented as written. Its failure is reported, not repaired.

The diagnosis script is post hoc and labelled as such. It was run on the same development data and influences no decision.

## 6. Tests

The full suite passes: **3,223 tests**, including 7 new ones in `tests/test_pvl_v1.py`. These cover linking, descriptors, labels and W on synthetic candidate sets, plus an assertion that linking and labelling read no truth.

## 7. Artifacts

- `artifacts/pvl_v1/`:
  - `l1_candidates_check.json` (the N1 reproduction check);
  - `candidates_*.json` (with v̂ and W);
  - `l1_selection.json` (all 162 configurations, with per-object evaluation);
  - `l1_stop_diagnosis.json`.
- Copies are in `evidence/pvl_v1/`.
- Reproduce with `python -m scripts.pvl_v1 candidates --workers 6` and then `python -m scripts.pvl_v1 select`, in the test image with the repository mounted. `FREEZE_BLOB` must be set for the V2 freeze.
