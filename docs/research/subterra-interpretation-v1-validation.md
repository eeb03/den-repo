# Subterra Interpretation V1: validation

**Decision: KEEP_EXPERIMENTAL.** See the [decision section](#decision) for why it is not ready for
shadow mode.

- **What it is:** a target-independent proposer of 3D response regions in a reconstructed volume. It
  never classifies anything.
- **Method:** `docs/volume-interpretation.md`.
- **Benchmark:**
  - protocol and matching rule: `benchmark/region_matching.py` (`bam-region-match-v1`) and
    `scripts/bam_region_benchmark.py`;
  - development phase: `evidence/bam/results/interpretation_v1/dev_phase.json`;
  - evaluation: `evidence/bam/results/interpretation_v1_benchmark.json`;
  - browser run: `evidence/bam/results/interpretation_v1/browser_verification.json`.

## 0. Two performances, kept separate

| | Question | Where it is answered |
|---|---|---|
| **Reconstruction performance** | How well does the volume focus the specimen? (Stolt F-K 3D migration, depth calibration, support) | Volume V1 (`docs/research/subterra-volume-v1-validation.md`). **Not re-measured or changed here.** Interpretation V1 reads volumes; it does not alter how they are made. |
| **Region proposal performance** | Given a volume, does the rule propose one reviewable region per real response, and few others? | This document |

The "migrated vs unmigrated" rows below measure how much region proposal **depends on**
reconstruction quality. They are not a re-evaluation of migration.

## 1. Honest framing: a controlled benchmark, not a held-out test

- **BAM has been studied extensively in this repository:** Candidate V2, its calibration, Volume V1's
  focusing validation, and time-zero and velocity audits. No BAM scan is pristine. Rot90 in particular
  was the held-out set of Candidate V2, so it is **not untouched**.
- **Order of commits:**
  1. `e71852a` committed the matching rule and protocol **before any target-level region result
     existed**.
  2. `7dac36b` recorded the development phase. It ran on **Pk266 1.5 GHz Rot00** (ducts) and **Pk050
     1.5 GHz Rot00** (no targets), and the defaults were frozen unchanged (`FROZEN = {}`).
  3. Evaluation ran afterwards on every other depth-scoreable scan.
- **Disclosure: one rule element came from looking at dev-scan regions.** The growth-contrast
  condition (`grow_local_contrast = 1.5`) was added during implementation, before the protocol commit,
  after viewing regions on the development scan. Without it, two ducts and the near-surface band
  merged into one giant region. It was not tuned against target scores, but it was chosen with the
  development scan in view.
- **What a result here means:** a result on this benchmark is evidence that the rule behaves sensibly
  on one family of concrete specimens. It is not evidence of field performance.

## 2. Matching rule (pre-registered)

The rule is `bam-region-match-v1`, summarised here; the code is authoritative.

- **A region matches a target** when:
  - its **peak** lies inside the drawn lateral footprint ±50 mm (x for ducts; x and y for foam
    cuboids); and
  - its depth interval overlaps the drawn depth interval ±60 mm.
- **Assignment** is greedy by the output's own score. The first match credits the target. Any later
  match to an already-credited target is a **duplicate**, which is neither a hit nor a false output.
- **Known non-target structures** (the back wall, the edge reinforcement and the grouted boreholes)
  are reported but excluded from precision.
- **Everything else is a false output,** categorised as `below_back_wall`, `step_edge` or `other`.
- **Ducts and foam cuboids are never pooled.**

Precision counts duplicates as non-false: `(TP + dup) / (TP + dup + false)`. That flatters 2D
baselines that emit hundreds of hits per target. **Strict precision** (`TP / all outputs`) is
reported next to it for that reason.

## 3. Evaluation scans

| Scan | Targets | Domain |
|---|---|---|
| Pk266 2.6 GHz Rot00 | 4 ducts | depth |
| Pk266 1.5 GHz Rot90 | 4 ducts | depth |
| Pk266 2.6 GHz Rot90 | 4 ducts | depth |
| Pk401 1.5 GHz Rot00 | 4 foam cuboids | depth |
| Pk401 1.5 GHz Rot90 | 4 foam cuboids | depth |
| Pk050 1.5 GHz Rot90 | none (control) | depth |
| Pk401 2.6 GHz Rot00 | — | two-way time (no sufficient calibration): 26 regions, **not scored** |
| Pk050 2.6 GHz Rot00 | — | two-way time: 30 regions, **not scored** |

All scored region results use the frozen config on the Stolt F-K migrated volume, unless marked
otherwise.

## 4. Region proposal results (frozen, migrated)

| Scan | Regions | Class recall | Duplicates | False (categories) | Known structures | Precision | Strict precision |
|---|---|---|---|---|---|---|---|
| Pk266 2.6 Rot00 | 19 | ducts 4/4 | 1 | 6 (2 below back wall, 4 step edge) | 8 | 0.45 | 0.21 |
| Pk266 1.5 Rot90 | 15 | ducts 4/4 | 1 | 4 (2 below back wall, 2 step edge) | 6 | 0.56 | 0.27 |
| Pk266 2.6 Rot90 | 25 | ducts 4/4 | 1 | 10 (3 below back wall, 6 step edge, 1 other) | 10 | 0.33 | 0.16 |
| Pk401 1.5 Rot00 | 15 | cuboids 4/4 | 1 | 1 (below back wall) | 9 | 0.83 | 0.27 |
| Pk401 1.5 Rot90 | 12 | cuboids 4/4 | 1 | 0 | 7 | 1.00 | 0.33 |
| Pk050 1.5 Rot90 (control) | 17 | — | — | 10 (7 below back wall, 3 other) | 7 | — | — |

**Per class (eval, pooled over scans of the same class only):**

| | Ducts (3 scans, 12 targets) | Foam cuboids (2 scans, 8 targets) |
|---|---|---|
| Recall | **12/12 = 1.00** | **8/8 = 1.00** |
| Duplicates per credited target | 3/12 = 0.25 | 2/8 = 0.25 |
| Precision (dup non-false) | 15/35 = 0.43 | 10/11 = 0.91 |
| False per scan | 6.7 | 0.5 |
| False per line (161 lines) | 0.041 | 0.003 |
| False per m² (1.6 m²) | 4.2 | 0.3 |

Over all six depth scans, including the control, there are **31 false regions (5.2 per scan)**. Of
these, 17 lie below the back wall (multiples and late energy) and 12 at step edges.

### Localisation (credited targets; |error|; median / max)

| | Ducts (n = 12) | Foam cuboids (n = 8) |
|---|---|---|
| Peak lateral x | 5.0 / 10.0 mm | 5.0 / 10.0 mm |
| Peak lateral y | — (ducts run along y) | 15.0 / 33.2 mm |
| Peak depth vs drawn top | 4.2 / 23.4 mm | 22.1 / 31.8 mm |
| Region top (z_min) vs drawn top | 29.2 / 60.9 mm | 1.9 / 4.8 mm |
| Centroid lateral x | 3.5 / **472.9** mm | 5.7 / 10.7 mm |
| Centroid depth vs drawn top | 8.8 / 15.2 mm | 27.8 / 38.5 mm |
| Extent x (drawn 67 / 120 mm) | 117.5 / **2005** mm | 152.5 / 200 mm |
| FWHM x | 62.5 / **1985** mm | 102.5 / 115 mm |

**Finding: sheet credits.** In all three duct eval scans, **duct 4 is credited by a region that spans
the full 2 m width** of the specimen. It is a laterally continuous sheet whose peak happens to sit on
duct 4, so its extent is 2005 mm and its centroid is off by up to 473 mm. The peak rule credits it
correctly by the pre-registered definition. This was foreseen: a peak rule rather than an overlap rule
stops one sheet from claiming every target.

The credit is still not one compact region per duct. Counting only credits whose x extent is within
3× the drawn width gives a **post-hoc diagnostic** (not a pre-registered metric) **compact duct recall
of 9/12 = 0.75**. The sheet is the main reason the growth-contrast condition alone is not sufficient
(see Interpretation V2).

## 5. Baselines (same scans, same rule; 2D detections scored as points)

Pooled over the six depth eval scans (20 targets):

| Arm | Outputs | Recall | Duplicates per credited target | False per scan | Precision | Strict precision |
|---|---|---|---|---|---|---|
| A production ring z-score (z ≥ 3) | 3,255 | 0.30 | 12.5 | 439 | 0.03 | 0.002 |
| B envelope (T ≥ 10) | 31,773 | 1.00 | 139 | 2,676 | 0.15 | 0.001 |
| C Candidate V2 (previous, ≥ 0.768) | 2,183 | 0.80 | 106 | 16.5 | 0.95 | 0.007 |
| C Candidate V2 calibrated (≥ 0.65) | 6,799 | 0.90 | 191 | 366 | 0.61 | 0.003 |
| **D response regions, unmigrated** | 151 | 0.70 | 0.14 | 12.5 | 0.18 | 0.093 |
| **D response regions, migrated (frozen)** | **103** | **1.00** | **0.25** | **5.2** | 0.45 | **0.194** |

- **Duplicate proliferation is reduced by two to three orders of magnitude.** Regions give 0.25
  duplicates per target; the 2D arms give 12–191.
- **Strict precision is 25–190× higher** for regions than for any 2D arm.
- **Candidate V2 (previous)** has the best duplicate-tolerant precision (0.95). It does so by emitting
  about 100 detections per target, which is exactly what regions remove. It also misses half the
  cuboids.
- **Review load:** regions also produce fewer false outputs per scan than Candidate V2 previous (5.2
  vs 16.5). Counting all outputs, a reviewer sees about 17 regions per scan against about 360
  Candidate V2 previous detections.

## 6. Ablations (eval; every other parameter frozen)

| Variant | Effect on eval |
|---|---|
| **No migration** (unmigrated volume) | recall 1.00 → **0.70**; false per scan 5.2 → **12.5**, nearly all below the back wall. **The biggest single factor.** |
| **No local contrast** (`use_local_contrast = false`) | **Misses on 4 of 5 target scans:** ducts 0.75 / 0.50 / 1.00, cuboids 0.75 / 0.75. False 31 → **46**, with the control rising 10 → 17. **The most important filter.** |
| No support filtering | identical (BAM has no interpolated voxels: a fully gridded acquisition) |
| min_voxels 1 | identical (nothing between 1 and 40 voxels survives the hysteresis anyway) |
| min_voxels 200 | one false region fewer on one scan; no miss |
| connectivity 26 | removes the duplicate on 2 scans; also removes some edge-reinforcement regions; no miss |
| 3 × 3 × 3 closing | removes the duplicate on 2 scans and 1 false; no miss |
| No lobe merging | +1 region on 3 scans (one more false or duplicate each); no miss |

**On the development scan,** no variant changed recall (1.00), and no local contrast had 2 → 5 false.
That is why the defaults were frozen unchanged.

Connectivity 26 and closing look slightly better on eval. They were not adopted after seeing eval
results, which would contaminate the evaluation. They are candidates for V2 under a new dev/eval
split.

## 7. Interpolation / sparse-line experiment

The setup was **Pk266 1.5 GHz Rot00** with **every second line removed**. It was reconstructed with
`linear_bounded` interpolation, so half the lines are interpolated, and without migration. Migration
requires the regular grid.

| | Regions | LOW_SUPPORT | Seeded only by interpolation (refused) | Interpolation-only (refused) | Duct recall | False |
|---|---|---|---|---|---|---|
| Dense, unmigrated (dev phase) | 34 | — | — | — | 2/4 | 16 |
| Sparse, frozen | 35 | 1 | 1 | 0 | 2/4 | 17 |
| Sparse, support filtering off | 35 | 0 | 1 | 0 | 2/4 | 17 |

- **Halving the lines left proposals essentially unchanged** compared with the dense unmigrated volume
  on the same scan: same recall, one more false region.
- The median region is **49% interpolated voxels**, yet every kept region contains measured seeds.
  Interpolation can extend a region but cannot create one (one component was refused on that ground).
  One region was flagged LOW_SUPPORT.
- The two misses are the unmigrated-volume misses, not interpolation misses.
- Because BAM is fully gridded, **the support filter never changed an eval result.** Its behaviour is
  established by the synthetic tests, not by BAM.

## 8. Performance (real BAM volume, 401 × 161 × 475 = 30.7 M voxels, migrated)

| | Measured |
|---|---|
| Generation, compute | 5.4 s: background 2.4 s, local contrast 2.1 s, labelling 0.9 s, merging and measuring 0.1 s |
| Generation, API call including loading the field | 3.2 s (warm, UI round trip) to 10.0 s (cold) |
| Peak memory during generation | **1.34 GB RSS** (about 44 bytes per voxel). Acceptable at this size, a limit for larger volumes. |
| Stored region set | **440 KB** JSON for 19 regions (393 KB of it bit-packed masks). The source field is 123 MB, so the set is 0.36% of it. No voxel rows. |
| Loading a set | 1.5 ms |
| `slice_labels` per slice | median 0.3 ms (XY), 2.0 ms (XZ), 0.4 ms (YZ); max 2.3 ms |
| Viewer | panes redraw interactively; the 3D pane with region boxes ran at 7 fps under **software WebGL** (SwiftShader, no GPU) |

## 9. Browser verification (real BAM volume, Pk266, migrated; scratch DB)

The run is logged in `evidence/bam/results/interpretation_v1/browser_verification.json`, with figures
in `docs/research/figures/interpretation_v1_*.png`.

| # | Step | Result |
|---|---|---|
| 1 | Open the Volume Viewer | ✅ Region sets 1 before and 1 after opening: **nothing generated on open** |
| 2 | Preview, then generate | ✅ The preview showed ≈19 regions, the algorithm, the threshold method and the rejections (598 no-seed, 0 tiny, 0 interpolation). Confirm generated 19 regions in 3.2 s |
| 3 | Toggle the region layer | ✅ The "RESPONSE REGIONS — unclassified" label is shown in 0 panes when off and 3 when on |
| 4 | Click a region in XY | ✅ A **literal canvas click** on region A's peak while B was selected changed the selection r0002 → r0001 |
| 5 | Same region in XZ / YZ / 3D | ✅ The slice label under the shared cursor is `…-r0001` in xy, xz and yz; the 3D box turns amber |
| 6 | Measurements | ✅ Centroid, peak, bounds, extent 140 × 180 × 115 mm, FWHM, 9,389 voxels across 36 lines, shape, peak robust z 8.8 and contrast 3.1, evidence score 0.76 "(response quality, not a probability)" with its components |
| 7 | Support provenance | ✅ measured 0%, reconstructed 100%, interpolated 0%; the peak voxel is reconstructed; generation provenance (algorithm, version, migrated volume, rule) |
| 8 | Review | ✅ "confirmed response" with a neutral workflow-test note |
| 9–10 | Reload; the review persists | ✅ The current state and the timestamped history survived the reload |
| 11 | BAM ground truth on | ✅ The GT label is in 4 panes and the region label in 3, as two separately labelled layers (magenta vs green/amber) |
| 12 | Structurally separate | ✅ With the overlay on, the region set is unchanged (same ids, same bounds); region records carry no ground-truth field |

- **Console:** only one browser console error appeared, the dev server's `favicon.ico` 404, which
  appeared in earlier runs too.
- **UX finding:** the **top-scored region on this scan (r0001, 632–745 mm deep) lies below the back
  wall.** It is a multiple, and it is the first item a reviewer sees. The evidence score ranks
  response quality, not physical plausibility.

## 10. Success criteria

| | Criterion | Status |
|---|---|---|
| A | Generated without target ground truth | ✅ The generator reads only the volume arrays; a test asserts no class or target names reach it |
| B | One coherent response becomes one region | ✅ mostly: 0.25 duplicates per target. ❌ Duct 4 joins a full-width sheet on 3/3 scans |
| C | Duplicate proliferation materially reduced compared with 2D | ✅ 0.25 vs 12–191 per target |
| D | Geometry in physical coordinates | ✅ (ns along z for time volumes) |
| E | Support and provenance visible | ✅ |
| F | Human review end-to-end | ✅ browser-verified, persistent and append-only |
| G | Independently documented targets, precommitted rule | ✅ the drawings, and `e71852a` before results |
| H | Nothing automatically called a pipe, void or material | ✅ There is no class field; the UI says "unclassified" |
| I | Volume V1 scientifically unchanged | ✅ There is no change to `reconstruction/`; the volume tests are unchanged and pass |

## Decision

**KEEP_EXPERIMENTAL.** The core property is real: one reviewable 3D region per response, recall 1.0
on both target classes at 0.25 duplicates per target, against hundreds for 2D detection. That holds on
**one specimen family** that this project has studied repeatedly. Shadow mode would put it in front of
users on data unlike BAM. The blockers:

1. **False regions:**
   - 5.2 per scan, 10 on the empty control;
   - multiples below the back wall can **rank first** (seen in the browser run);
   - step edges produce regions.
2. **Over-merging into sheets:** a laterally continuous response can swallow a target, and does so on
   3/3 duct scans.
3. **No field data:**
   - every scored scan is a fully gridded laboratory specimen;
   - the support filter has never been exercised by real interpolated data;
   - time-domain scans are unscored.
4. **Memory:** peak memory is 1.3 GB for a 31 M-voxel volume.

## Answers to the final questions

1. **How are regions generated?**
   - Per-depth robust z (median/MAD over supported voxels), combined with a local lateral contrast
     ratio.
   - 3D hysteresis: seeds need z ≥ 8, contrast ≥ 3 and a measured or reconstructed voxel; growth
     needs z ≥ 4 and contrast ≥ 1.5.
   - 6-connected labelling, ≥ 40 voxels, conservative stacked-lobe merging, then support checks.
   - Every threshold is a ratio, and the rule never reads a target.
2. **What exactly does one region represent?**
   - A spatially coherent reconstructed response that exceeds that stated, target-independent evidence
     criterion, measured in the volume's physical frame with its support and provenance.
   - It is not an object, not a class, and its score is not a probability.
3. **How many regions are produced per BAM scan?**
   - 12–25 on the migrated depth eval scans (mean 17), and 17 on the empty control.
   - 26 and 30 on the two time-domain scans; 11–39 unmigrated.
4. **What is duct recall?**
   - 12/12 = 1.00 on three eval scans under the pre-registered rule.
   - Duct 4 is credited by a full-width sheet on all three. The compact-region recall (post hoc) is
     9/12 = 0.75.
5. **What is foam/void recall?**
   - 8/8 = 1.00 on two eval scans, with region-top depth error ≤ 5 mm.
   - The foam cuboids are void analogues. They are not voids, and nothing calls them that.
6. **What is precision?**
   - Ducts 0.43 and cuboids 0.91 (duplicates counted as non-false).
   - Strict TP/outputs is 0.19 pooled, because most of the other outputs are the back wall and the
     edge reinforcement. Those are real responses, not errors, but they are not targets either.
7. **How many false regions remain?**
   - 31 over six depth scans: 5.2 per scan, 0.03 per line, 3.2 per m².
   - 17 are below the back wall, 12 at step edges and 3 other. 10 of them are on the empty control.
8. **How many duplicate regions remain per target?**
   - 0.25 per credited target (5 over 20 targets), against 12–191 for the 2D baselines.
9. **What are centroid localisation and depth errors?**
   - **Peak lateral error:** a median of 5 mm (max 10).
   - **Peak depth error:** ducts 4 mm (max 23), cuboids 22 mm (max 32).
   - **Region-top error:** cuboids 2 mm, ducts 29 mm.
   - **Centroid error:** depth 9 mm (ducts) and 28 mm (cuboids). Lateral centroids are 4–6 mm except
     the three sheet credits (up to 473 mm).
10. **Does migration materially improve region proposal quality?**
    - **Yes.** Recall rises 0.70 → 1.00 and false regions fall 12.5 → 5.2 per scan, with strict
      precision doubling.
    - Unmigrated volumes are dominated by below-back-wall regions.
11. **Which filter removes the most false regions?** Local lateral contrast: removing it raises the
    false regions from 31 to 46, and the control from 10 to 17.
12. **Which filter causes the most misses?**
    - In the frozen config, none: no filter caused a miss on eval.
    - Removing local contrast **causes** misses, because without it neighbours merge into layers. So
      does skipping migration.
    - min_voxels 200, connectivity 26, closing and support filtering caused no misses on BAM.
13. **Are the proposed regions small enough and high-recall enough to feed a future classifier?**
    - **Recall is enough on BAM.** Most regions are compact (cuboid extent 150 mm; duct median x
      extent 118 mm).
    - **But not yet as a corpus generator:**
      - full-width sheets would hand a classifier mixed crops;
      - there is no field data;
      - the only judgement on a region is operator review (grade C).
    - The label-free export is ready for when it is.
14. **Is the human-review workflow usable?**
    - Yes. Preview, confirm, select by list, canvas or 3D, the shared cursor, measurements, support and
      append-only persistent review were all verified in the browser.
    - The known friction is ordering: multiples can top the list.
15. **Is Interpretation V1 ready for shadow mode?** **No: KEEP_EXPERIMENTAL** (see the decision
    section above).
16. **What should Interpretation V2 add next?**
    1. **Sheet splitting:** split a region whose lateral extent far exceeds its FWHM and which contains
       several local peaks. Watershed or marker-based splitting on the envelope, seeded from local
       maxima.
    2. **Context flags, not deletions:** "below the deepest continuous reflector (likely multiple)" and
       "at a lateral discontinuity", derived from the volume itself. They would order the review
       queue, never hide regions.
    3. **Re-evaluate connectivity 26 and closing** under a fresh dev/eval split.
    4. **Field data with real line gaps,** to exercise the support model on genuinely sparse
       acquisitions.
    5. **Chunked processing** to bound memory.
    6. **Polarity / phase evidence** next to the envelope, as a second evidence entry.
    7. Only after field evidence: a first non-GPR evidence modality, or an operator-review corpus.
