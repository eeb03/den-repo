# BAM benchmark: detection and false-alarm scoring

**The first quantitative detection measurement Subterra has ever had.** Every
number below was produced by `scripts/score_bam_benchmark.py` from the acquired
archives and is stored in `artifacts/bam/score_<scan>.json`.

> **Scope boundary.** BAM benchmark results measure performance on controlled
> concrete NDT specimens. **They are not evidence of soil/utility-scale
> subsurface detection or localisation performance.** No CRS, no verified
> absolute origin, no utility-scale geometry.

**Localisation scoring is BLOCKED** and enforced in code — see §6.

## 1. What runs

```
Pk266 / Pk050 archive (unchanged, MD5-verified)
   ↓  benchmark.bam_ingest      grid + volume + DZT header provenance
   ↓  preprocessing.spatial_grid.anomaly_grid_from_traces
        (background_removal → dewow → apply_gain → ring z-score)
   ↓  scipy.ndimage.label + min_cells      the find_anomaly_candidates rule
   ↓  benchmark.association                exact grid-node association
   ↓  benchmark.scoring                    detection + false alarms
```

**No new detector and no new model.** The pipeline is the one the 4TU corpus
went through, and `parameters_changed_for_this_benchmark` is `none` in every
report. Thresholds are the detector's published defaults (3.0 / 3 cells); they
were **not** tuned for this benchmark.

### Why the amplitudes come from the `.npy`, not the `.DZT`

The DZT holds **152,222 traces**; the coordinate-registered grid is
**401 × 161 = 64,561**. No source documents how DZT traces map onto grid nodes.
The DZT is therefore opened for its header — proving the existing GSSI reader
handles these files, and recording `n_samples 512`, `range_ns 15.0`, `bits 16`,
`epsr 5.5` as provenance — and the `3D_Dataset_*.npy` volume, whose shape is
exactly `(401, 161, 512)`, supplies the amplitudes. Carried as the open
question `dzt-to-grid-mapping`.

## 2. Association, and the matching rule

A line is a traverse along X at fixed Y, so **trace index *is* the X grid
node** — there is no resampling and nothing to interpolate. Each target's
footprint is the grid nodes within one published outer radius (67 mm / 2) of
its published X, and `GridSpec.x_node` **raises** rather than rounding, so the
association cannot silently degrade into nearest-neighbour matching.

| target | X | node | footprint | type |
|---|---|---|---|---|
| `Pk266-duct-1` | 250 | **50** | 44–56 (13 nodes) | tendon duct |
| `Pk266-duct-2` | 750 | **150** | 144–156 | tendon duct |
| `Pk266-duct-3` | 1250 | **250** | 244–256 | tendon duct |
| `Pk266-duct-4` | 1750 | **350** | 344–356 | tendon duct |

**Matching rule, stated rather than assumed:** a detection matches a target
when its **peak trace node** lies inside that target's footprint. **No
tolerance is added.** The peak is used rather than "any overlapping node"
because a component can straddle a footprint edge, and crediting a target for a
detection whose evidence is mostly elsewhere would inflate recall. The
permissive count is reported too, as `overlapping_any_node`, so the choice is
visible rather than buried.

**Counting unit: target × line.** Four targets over 161 lines is 644
opportunities. A target found on some lines and missed on others is neither a
clean hit nor a clean miss at scan level, and per-line counting says exactly
how consistent the detector is.

## 3. Results — all 161 lines, both antennas

| | 1.5 GHz Rot00 | 2.6 GHz Rot00 |
|---|---|---|
| Detections on Pk266 | 333 | 430 |
| **True positives** | 45 | 63 |
| **False positives** | 288 | 367 |
| **False negatives** | 602 | 584 |
| **Recall** | **0.065** | **0.093** |
| **Precision** | **0.135** | **0.147** |
| **F1** | **0.088** | **0.114** |

TP (45) exceeds the recall numerator (42) because TP counts *matched
detections* while recall counts *(target, line) pairs covered* — more than one
detection can land on the same target on the same line.

### False alarms, on attested-empty ground

| | 1.5 GHz Rot00 | 2.6 GHz Rot00 |
|---|---|---|
| Detections on Pk050 | 449 | 274 |
| Lines scored | 161 | 161 |
| **Detections per line** | **2.79** | **1.70** |

Pk050 is **attested by its fabricator** to contain no embedded elements, which
is what makes this a false-alarm measurement rather than an unlabelled count.

**The caveat travels with the number, and is not optional:** Pk050 is *not
featureless*. Its step back walls are real reflectors at 571.3 / 452.0 / 330.9 /
210.8 mm, and any detector will respond to them. This is a control for
**embedded objects**, not for "no reflector". A share of these 449 and 274
detections are almost certainly back-wall responses, and nothing here separates
them.

No per-area rate is computed: the archives **declare no physical unit** for
X/Y, so an area cannot be stated without assuming one.

## 4. Reading this honestly

**The detector performs poorly on this benchmark.** Recall 0.065–0.093 means
it misses the great majority of target crossings, and precision 0.135–0.147
means most of what it reports is not at a target.

This is consistent with a limitation **already measured before this benchmark
existed**: the ring z-score **saturates with target width**, so a broad,
laterally coherent target scores no higher than a narrow one and can sit below
|z| ≥ 3 regardless of contrast. A tendon duct spanning the full specimen width
is precisely that kind of target. The benchmark did not discover a new problem;
it put a number on a known one.

**No threshold was changed in response to these results,** and none should be.
Tuning a threshold against the only target truth the project holds would
convert the benchmark from a measurement into a fit.

What this legitimately supports: that the pipeline runs end to end against real
target ground truth; that detection and false-alarm rates are now *measurable*;
and a baseline to improve against. What it does not support: any claim about
soil or utility performance, and any localisation claim at all.

## 5. Verified / inferred / not available

**Verified from files** — raw DZT acquisition and reader compatibility; the
supplied X/Y/Z vectors (401 / 161 / 512, uniform step 5); the volume shape
`(401, 161, 512)`; deterministic exact grid-node association; the control
specimen's presence in the downloaded data; archive integrity (MD5 matched).

**Inferred from documentation** — target identity, geometry, X positions and
depths (transcribed from publications; the repository ships no geometry file);
the emptiness of Pk050; the millimetre unit for X/Y.

**Not available** — the absolute coordinate origin; a machine-readable target
geometry file at source; a CRS; the depth reference surface (ambiguous by
3.5 mm); the DZT→grid mapping; any basis for transferring these results to soil
or utility environments.

## 6. The localisation gate

`benchmark.gates` holds `LOCALIZATION_STATUS = BLOCKED`, reason **"absolute
origin is not verified"**. `require_localization_evidence()` raises
`LocalizationBlocked` naming the unresolved questions, and
`benchmark.scoring.score_localization` refuses for the same reason. Tests fail
if the status is flipped while the questions remain open.

Detection and false-alarm scoring are **independently executable** and do not
call the gate — they ask whether a detection falls inside a footprint defined
in the same grid the detections are indexed by, which the absolute origin does
not affect.

Open questions, carried in code so they cannot be dropped:

| id | blocks | resolution |
|---|---|---|
| `absolute-origin` | localisation in absolute/physical coordinates | BAM appendix drawings, or author contact |
| `depth-reference-surface` | absolute depth accuracy | BAM Table 4 reference surface |
| `coordinate-units` | any metric in physical units rather than grid nodes | a units declaration |
| `dzt-to-grid-mapping` | scoring against the native DZT stream | an acquisition-order statement |

## 7. Reproducing

```bash
python scripts/score_bam_benchmark.py --scan 1_5_GHz_Rot00 \
    --out artifacts/bam/score_1_5_GHz_Rot00.json
```

Full scan is ~161 lines per specimen and takes about a minute. `--lines N`
scores an evenly spaced subset; the processed and available line counts are
both written to the report, so a partial run cannot read as a full one.
