# 4TU pipeline diagnostics: performance and the null comparison

Investigation date 2026-08-07. Written before the full characterisation run,
as a gate on it.

Two premises from the milestone brief needed correcting before any work was
useful. Both corrections are below with the measurements behind them.

---

## Part A — performance

### Premise correction

> "The current pipeline appears to rebuild the grid approximately six times
> per file. The current estimate is roughly 20 hours."

**The 6× rebuild was real, and was already fixed before that estimate was
taken.** It lived in `scripts/characterise_4tu.py`, not in the pipeline:
the threshold sweep called `find_anomaly_candidates` once per threshold, and
that function rebuilds the z-grid on every call. Five sweep thresholds plus
the default meant six grid builds per radargram.

The ~20 h figure came from the first launch, which ran the unoptimised
sweep *and* competed with a concurrently running test-suite container. The
optimised run, measured alone, projects to **~2.5 h** for the full corpus.

### Root cause

`interpretation.anomaly_candidates.find_anomaly_candidates` is a
self-contained entry point: given records and a `source_file`, it builds the
trace/depth grid, thresholds it, labels components and characterises them.
That is correct for its contract — but it means N threshold values cost N
grid builds. **No fix was needed inside the pipeline.**

### Fix

The characterisation script now follows the requested shape:

```
raw -> preprocessing -> ONE shared z-grid -> authoritative detector
                                          -> sweep counts
```

- the **authoritative** detection still calls `find_anomaly_candidates` at
  the real default, producing real `AnomalyCandidate` objects with full
  provenance — unchanged;
- the **sweep** counts components on the grid that call already built, via
  `count_components`, which mirrors the detector's own two steps exactly
  (`|z| > threshold`, `ndimage.label` at its default 4-connectivity, then
  the `min_cells` filter).

Every radargram checks the mirror against the authoritative detector at the
default threshold and records the result as
`sweep_agrees_with_detector_at_default`. A test additionally checks
agreement at **every** swept threshold on real files.

### Benchmark (5 real radargrams, activity 01)

| file | traces | old (s) | new (s) | speedup | sweep identical |
|---|---|---|---|---|---|
| Path13.sgy | 34 | 0.37 | 0.09 | 4.1× | yes |
| Path17.sgy | 44 | 0.42 | 0.13 | 3.3× | yes |
| Path16.sgy | 45 | 0.69 | 0.14 | 4.9× | yes |
| Path25.sgy | 46 | 0.40 | 0.12 | 3.5× | yes |
| Path26.sgy | 47 | 0.40 | 0.12 | 3.4× | yes |
| **total** | | **2.28** | **0.59** | **3.8×** | **yes** |

**No scientific output changed.** No threshold, window, normalisation or
preprocessing stage was altered, and no data was excluded.

---

## Part B — the "553 vs 44" comparison

### Premise correction

> "The current null/background subset produces approximately 553 anomaly
> candidates versus approximately 44 in the observed/target-containing
> subset."

**These are not two subsets.** They are the *same single radargram*. The
number came from a 3-file smoke test of the permutation null: for one file,
the detector found 44 candidates, and the mean over 5 permuted copies **of
that same file** was 553. There is no background subset, no second group of
activities, and no different acquisition conditions.

4TU in fact contains **no background or control activity at all** — every
survey was walked where a trench was planned — which is why a permutation
null was reached for in the first place.

### Are the populations comparable?

**Exactly, by construction.** A trace permutation reorders whole traces and
changes nothing else. Measured on `01.4/Path1.sgy`:

| quantity | observed | permuted null |
|---|---|---|
| activities | 1 | 1 (same) |
| files | 1 | 1 (same) |
| traces | 291 | 291 (same) |
| samples/trace | 512 | 512 (same) |
| cells | 148,992 | 148,992 (same) |
| processed value multiset | sum 0.0000 | sum 0.0000 (identical) |
| **adjacent-trace correlation** | **0.9582** | **−0.0174** |
| z \|mean\| | 0.3906 | 0.3801 |
| z std | 0.6889 | 0.7403 |
| cells \|z\|>3 | 333 | 2,317 |
| candidates (≥3 cells) | 46 | 466 |
| **candidates per trace** | **0.158** | **1.601** |

Coverage, dimensions, and the exact multiset of processed values are
identical. The **only** thing that differs is lateral coherence.

### Explanation

The detector's statistic is a *ring* z-score: each cell is compared against a
ring of neighbouring cells. Its behaviour depends entirely on how well
neighbours predict the centre.

- **Observed:** adjacent traces correlate at **0.96**. At 0.02 m trace
  spacing, reflectors continue smoothly across traces, so the ring
  background is an excellent predictor, residuals are small, and few cells
  exceed |z| > 3.
- **Permuted:** adjacent traces correlate at **−0.02**. The ring background
  now predicts nothing, residuals inflate, and 7× as many cells cross the
  threshold — producing 10× the components.

So **removing structure raises the statistic.** The permutation null is not
a false-alarm floor for this detector on this corpus; it is an *upper* bound
on the detector's response to incoherent data.

`validation/null_models.py` already carried exactly this warning for
`lateral_permutation`. The measurement above shows it applies to
`trace_permutation` too, and the docstring has been corrected (documentation
only — no behaviour changed).

### Why INGV was different

| corpus | trace spacing | adjacent-trace corr | null/observed candidates |
|---|---|---|---|
| 4TU | 0.02 m | 0.958 | **10.6×** |
| INGV | 0.246 m | 0.522 | **2.6×** |

The inflation scales with how much coherence there is to destroy. INGV's
trace spacing is 12× coarser, so its lines are far less laterally coherent
and the null distorts less. It still inflates — the earlier INGV work used
this null for a *width* statistic, which is much less sensitive to ring
quality than a raw candidate count.

### Consequence for the p-value

The observed p = 1.000 on every file is **not a finding and must not be
reported as one**. A one-sided permutation p asks "is the observed count
higher than an incoherent version of itself?" For real, coherent data the
answer is always no. The p-value is measuring the mis-specification, not the
detector.

### Classification of the counts

Per the milestone's rule, and asserting nothing beyond it:

| count | classification |
|---|---|
| 46 candidates on the observed radargram | **candidate** — detector output, unscored |
| 466 candidates on the permuted copy | **background/null candidate** — an artefact of a mis-specified null, not a false-positive rate |
| the utilities reported for activity 01.4 | **observed/source-supported** — no coordinates, joined by LocationID only |
| everything else | **unscored/unknown** |

Neither number is evidence about detector accuracy. Nothing here says the 46
are true or the 466 are false.

---

## What was NOT done

- No threshold was tuned, chosen, or changed.
- No detector code was modified.
- No preprocessing stage was removed or weakened.
- No data was excluded to improve a number.
- The only non-test change outside the characterisation script is a
  **docstring** in `validation/null_models.py` recording the measurement
  above.

## What a usable background baseline would need

A false-alarm rate requires ground that is known to contain nothing — a
control survey over verified-empty ground, or a physical model. 4TU provides
neither. The realistic options are:

1. a synthetic null from `validation/synthetic_targets.py`, which preserves
   lateral coherence by construction;
2. a corpus containing designated control lines;
3. a null that permutes *within* a coherence length rather than globally,
   which would need to be designed and justified — a research task, not a
   configuration change.
