# 4TU corpus: preprocessing and anomaly characterisation

Generated from `artifacts/4tu/characterisation.json` (2026-08-07T11:47:54.717503+00:00). Every figure below is read from that file.

> **This is a characterisation, not an evaluation.** 4TU publishes no
> trench coordinates, so no candidate is matched to a reported utility and
> no accuracy, precision, recall, IoU, depth error or positional F1 is
> reported anywhere. Those metrics are not computable from this source.


## 1. Corpus

- **Source:** `datasets/raw/4tu/96303227-5886-41c9-8607-70fdd2cfe7c1/extracted`
- 4TU.ResearchData, DOI 10.4121/96303227-5886-41c9-8607-70fdd2cfe7c1.v1, CC0-1.0
- Air-launched 500 MHz GPR, Spectre SP80 RTK GNSS + wheel encoder, 0.02 m trace spacing, 512 samples/trace
- **Real data only.** No fixtures contributed to any number in this report.

## 2. Acquisition structure

| | |
|---|---|
| Activities (LocationID) characterised | 125 |
| Radargrams available in those activities | 759 |
| Radargrams processed | 759 |
| Traces | 459,308 |
| Records (trace x sample) | 235,165,696 |

Activities are the dataset's own `LocationID`. Project 13's directories are named `013.N` while its `Metadata.csv` rows say `13.N`; that one-to-one, 6-entry mismatch is normalised and recorded as a source inconsistency, not inferred.

## 3. Preprocessing configuration

- `preprocessing.trace_processing.process_gpr_traces (background removal -> dewow -> gain)`
- `preprocessing.spatial_grid.preprocess_trace_local_anomaly (ring z-score on the trace/depth grid)`

- Ingest: `converters.segy_converter.SEGYConverter`, coordinate encoding `ieee_nmea (caller-declared)`
- **Parameters changed by this run: none**

### Provenance of each quantity

| quantity | status |
|---|---|
| GPR two-way time | **measured** by the instrument |
| Background removal / dewow / gain | **derived** from the measured signal |
| Ring z-score | **derived** statistic, not a physical unit |
| Velocity | **caller-supplied**, derived from the provider's published relative permittivity per activity (`c/sqrt(eps_r)`) — a site estimate, not a subsurface measurement |
| Depth | **assumed**, because it inherits that velocity |
| Vertical datum | **unavailable** — see `docs/vertical-reference-site01.md` |
| Trench information | **source-reported**, joined by LocationID only |

## 4. Detector configuration

- `interpretation.anomaly_candidates.find_anomaly_candidates`
- threshold **3.0**, min_cells **3**, 4-connected components
- threshold sweep: [2.5, 3.0, 3.5, 4.0, 5.0] (counts only, on the grid the detector already built; agreement with the authoritative detector at the default is asserted per radargram)

## 5. Volume processed

| | |
|---|---|
| Radargrams | 759 of 759 |
| Traces | 459,308 |
| Records | 235,165,696 |
| Wall time | 7547.5 s |

### Processing mode

Two paths, proven bit-identical on the z-grid (`artifacts/4tu/arraywise_validation.json`). The array path exists because per-cell records, not the science, dominate memory; it computes the same grid with the same functions but does not produce per-candidate characterisation.

| path | radargrams | records | candidates | per-candidate detail |
|---|---|---|---|---|
| records | 724 | 129,564,160 | 13,274 | yes |
| arraywise | 35 | 105,601,536 | 16,856 | no |

**Ring-background reliability** is measured on the 724 record-path radargrams (129,564,160 cells): **124,204,577 reliable (95.9%)**, **5,359,583 edge-starved (4.1%)**. The array path does not compute it, so those cells are excluded from this percentage rather than counted as either.

## 6. Rejected / skipped, and why

No activity was skipped.

No radargram failed to process.

## 7. Anomaly candidates

| | |
|---|---|
| Candidates at the default threshold | **30,130** |
| Candidates per 1,000 traces | 65.60 |
| Activities with >=1 candidate | 125 of 125 |
| Activities with 0 candidates | 0 |
| Candidate density per activity (per 1k traces) | median 33.11, min 1.72, max 444.11 |

**Geometric class distribution** (a neutral shape description, never an object claim). Covers the 13,274 candidates from record-path radargrams; the 16,856 from array-path radargrams are counted above but not classified.

| class | count |
|---|---|
| depth-elongated | 12,657 |
| diffuse | 542 |
| trace-elongated | 38 |
| compact | 37 |

## 8. Distribution by activity

Full per-activity detail is in the JSON artifact. Extremes shown here.

| LocationID | files | traces | candidates | per 1k traces |
|---|---|---|---|---|
| 06.6 | 12 | 2,013 | 894 | 444.113 |
| 06.1 | 12 | 2,795 | 1115 | 398.927 |
| 06.2 | 10 | 2,126 | 667 | 313.735 |
| 06.3 | 11 | 2,733 | 767 | 280.644 |
| 09.6 | 4 | 5,197 | 1182 | 227.439 |
| 09.7 | 9 | 33,406 | 7352 | 220.08 |
| 08.4 | 10 | 2,354 | 461 | 195.837 |
| 012.2 | 7 | 2,695 | 517 | 191.837 |
| 08.3 | 6 | 2,008 | 378 | 188.247 |
| 08.8 | 3 | 716 | 131 | 182.961 |
| ... | | | | |
| 011.3 | 4 | 2,224 | 5 | 2.248 |
| 011.8 | 1 | 2,464 | 5 | 2.029 |
| 011.1 | 4 | 4,563 | 9 | 1.972 |
| 011.16 | 9 | 3,661 | 7 | 1.912 |
| 011.9 | 4 | 1,744 | 3 | 1.72 |

## 9. Relationship to trench information

The join is **LocationID only**. 4TU withholds trench coordinates for confidentiality, so a candidate cannot be matched to a reported utility and none is.

- Activities where the source reports at least one utility discipline: **111**
- Activities where that field is blank: **14**
- Candidate density where utilities are reported: median 33.11 per 1k traces
- Candidate density where the field is blank: median 30.25 per 1k traces

**A blank field is not a known-empty activity.** The dataset states that material and diameter are not recorded for every utility, so absence in the table is missing information, not absence of a utility. No activity here can serve as a negative control.

## 10. Background / null observations

- Null model: `trace_permutation`, 8 draws over 12 radargram(s), seed 20260807
- Observed candidates in the sample: **1,900**
- Null mean over the same radargrams: **14188.9**
- Files whose observed count exceeds their own null p95: 0/12

**The permutation null is mis-specified for this corpus and gives no false-alarm rate.** Measured on `01.4/Path1.sgy`: adjacent traces correlate at 0.958 observed versus -0.017 permuted; permuting raises supra-threshold cells from 333 to 2,317 and candidates from 46 to 466. Removing lateral coherence *raises* the ring z-score, because the ring background stops resembling its centre cell. The null is therefore an upper bound on the detector's response to incoherent data, not a floor, and the resulting p-values (1.000 everywhere) measure the mis-specification rather than the detector. Full diagnosis in `docs/4tu-diagnostics.md`.

4TU contains **no control or background activity**: every survey was walked where a trench was planned. A false-alarm rate cannot be measured from it.

## 11. Threshold sensitivity

| threshold | candidates | vs default |
|---|---|---|
| 2.5 | 112,209 | 3.72x |
| 3.0 | 30,130 | 1.00x  <- default |
| 3.5 | 12,132 | 0.40x |
| 4.0 | 6,482 | 0.22x |
| 5.0 | 2,200 | 0.07x |

The count falls steeply with threshold, so the default is **not** in a stable plateau: a small change in threshold changes the candidate count substantially. The default is provisional, as the detector's own module docstring states, and nothing in this run justifies changing it.

## 12. Failure modes observed

- **Edge starvation.** 4.1% of measured cells lack enough ring neighbours and are flagged `anomaly_reliable=False` rather than given a misleading extreme value. Candidates touching a boundary carry `touches_trace_boundary` / `touches_depth_boundary`.
- **Threshold instability** (section 11).
- **Width saturation**, previously measured: the ring z-score saturates with target width, so a broad laterally coherent target scores no higher than a narrow one and can sit below |z|>=3 regardless of contrast. Broad targets are structurally hard for this detector.
- **Null mis-specification** (section 10).

## 13. What this data can legitimately support

- That the pipeline runs end to end on a real, independent corpus at scale.
- Counts and densities of detector candidates per activity, per trace, per file.
- The geometric and statistical properties of those candidates.
- How candidate counts respond to threshold.
- How the detector responds to loss of lateral coherence.
- Coverage and failure accounting.

## 14. What it cannot support

- Any coordinate-level metric: precision, recall, IoU, positional F1, detection distance, depth accuracy.
- Whether any individual candidate corresponds to a real buried object.
- A false-alarm rate (no control ground).
- Whether a candidate-dense activity is dense because of utilities, ground conditions, or acquisition differences.
- Any depth claim beyond 'derived from a provider site estimate of permittivity'.

## 15. Ground truth required for spatial scoring

1. **Trench positions in a declared CRS** — the single blocking item. Without them, candidate-to-target matching is impossible in principle.
2. **Per-utility depth in a declared vertical datum**, plus the offset from the GPR depth-axis origin to the ground.
3. **Verified-empty control ground**, for a false-alarm rate.
4. **Trench extent**, not just presence, for anything IoU-like.

Items 1 and 3 are properties of the source dataset and cannot be produced by any amount of processing here.
