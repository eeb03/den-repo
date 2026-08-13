# Anomaly path equivalence

Are the record path and the array path the same detector? **The two
implementations always were. The product was running neither of them.**

## 1. The question, and the answer that was not expected

`anomaly_grid_from_traces` (array) and `preprocess_trace_local_anomaly` (record)
were documented as identical. They are not — but the discrepancy is not where the
docstring put it, and the equivalence validator was never wrong.

| Caller | Composition | Cells over \|z\|>3 on a real 4TU line |
|---|---|---|
| BAM benchmark | `anomaly_grid_from_traces` — filters + ring | **164** |
| 4TU characterisation | `process_gpr_traces` → `preprocess_trace_local_anomaly` | **164** |
| Regression baseline | `gpr_trace_processing` → `gpr_local_anomaly` | (pinned) |
| **Product ingest** | `gpr_local_anomaly` **alone** | **39** |

**The product computed candidates from a detector no benchmark had ever
measured.** Every published number describes the filtered detector; every
candidate a user saw in the radargram viewer came from the unfiltered one.

## 2. Measured divergence

Same converted input, `01.1/Path8.sgy`, 160,768 cells, ingest composition against
benchmark composition:

| | |
|---|---|
| Shape / dtype | (512, 314) / float64 — identical |
| Exactly equal cells | 6,886 (**4.28%**) |
| Cells differing > 1e-9 | 153,882 (**95.72%**) |
| Cells differing > 0.5σ | 53,317 (**33.16%**) |
| Max absolute difference | **4.470409 σ** |
| Mean absolute difference | 0.438753 σ |
| z range | ingest −4.854…4.123 · benchmark −4.773…5.419 |
| Cells over \|z\|>3 | **39 vs 164 — 4.2×** |

The 6,886 exactly-equal cells are precisely the unreliable ones, which both paths
force to 0.0. Everything the ring statistic actually computed disagreed.

## 3. What `--verify-arraywise` verifies

**Nothing — it does not exist.** Three docstrings referenced it as a CLI flag;
`scripts/characterise_4tu.py` has no such argument and never did. The real tool
is `scripts/validate_arraywise.py`.

That tool is **correct and remains unchanged**. It compares

```
preprocess_trace_local_anomaly(process_gpr_traces(recs))   vs   anomaly_grid_from_traces(...)
```

and measures them **bitwise identical** (`max_abs_difference: 0.0`,
`candidate_sets_identical: true`, `threshold_sweep_identical: true`). It was
never testing the wrong thing — it was testing a composition the product did not
use, and nothing pointed that out.

So of the five possibilities the brief listed, the answer is the last one: **a
real implementation discrepancy**, located in the ingest pipeline rather than in
either anomaly function.

## 4. Which side is correct, and why

The **filtered** side, and not because it preserves benchmark numbers.

But note carefully **where** the error is. `preprocess_trace_local_anomaly` being
filter-free is CORRECT: `run_pipeline`'s modes are single steps, and composing
them is the caller's job. `tests/test_gpr_regression_baseline.py` has pinned
exactly that composition since the interpretation baseline:

```python
records = run_pipeline(records, mode="gpr_trace_processing")
records = run_pipeline(records, mode="gpr_local_anomaly")
```

The bug is that **every ingest route applies exactly one mode** —
`run_pipeline(records, mode=preprocessing_mode)` — so the validated two-step
chain was *unreachable through the API*. A GPR ingest could ask for the filters
or for the anomaly statistic, never both.

(The first attempt at this fix made `gpr_local_anomaly` filter internally. The
regression baseline caught it immediately: that composition then double-filters.
The pin did its job.)

Background removal strips the direct wave and ground bounce — the coherent
horizontal energy present in every trace at the same time. A ring statistic
computed *without* that removal estimates each cell's background from that
coherent energy, which is exactly the width-saturation mechanism this project has
already measured and documented. Dewow removes low-frequency drift; gain
compensates geometric spreading. Applying a local-anomaly statistic to unfiltered
GPR is the less defensible of the two, independently of what any benchmark says.

It is also what every docstring, the array implementation and both benchmark
paths already intended. The ingest mode was the only caller that disagreed.

**Outcome C** in the brief's terms, with the owner precisely located: not the
record ANOMALY FUNCTION, which is right, but the ingest COMPOSITION, which could
never assemble the validated chain. Tracing the array path exposed it.

## 5. The fix

A **new** mode in `preprocessing/pipeline.py`, leaving every existing mode's
semantics untouched:

```python
if mode == "gpr_full":
    records = process_gpr_traces(records, ...)
    return preprocess_trace_local_anomaly(records, ...)
```

Verified bitwise identical to the array path — max difference `0.0000000000`,
164 cells over \|z\|>3 on both sides, on the synthetic fixture and on a real
4TU line.

Added rather than folded into `gpr_local_anomaly` because that mode's
filter-free behaviour is correct, is what the regression baseline pins, and is
what the composition itself depends on. Nothing else changed: no threshold, no
scoring, no truth, no candidate semantics, and `pre_anomaly_signal` still means
exactly what Stage 17 established for each mode.

**What this does not do.** It does not change any default. A caller must ask for
`gpr_full`; the ingest routes still apply whichever single mode they are given.
Changing the API's default preprocessing would affect every modality and is a
product decision outside this stage's scope. The chain is now *reachable*, which
it was not.

## 6. Benchmark impact

**None.** Both benchmarks already used the filtered composition, so correcting
ingest cannot move them. Verified by re-running BAM 1.5 GHz before and after:

| | before | after |
|---|---|---|
| true positives | 45 | 45 |
| false positives | 288 | 288 |
| false negatives | 602 | 602 |
| precision | 0.1351351351 | 0.1351351351 |
| recall | 0.0652173913 | 0.0652173913 |
| detections | 333 | 333 |

Bit-identical. No threshold, scoring rule or truth corpus was touched.

**What did change is the product**, and it changed a great deal: a dataset
ingested after this fix produces candidates from a materially different — and
now benchmarked — detector. Stage 13's "approximately at chance" finally
describes the detector the product actually runs. It did not before.

## 7. The one difference that remains, deliberately

The record path stores **0.0** where z is non-finite; the array path leaves
**NaN**. Measured: 6,886 cells, **100% at a ring-window boundary**.

This is not a bug and is not being unified. `SubterraRecord` rejects NaN by
construction — a decision made so that "no value" and "zero" cannot be confused
in stored data — while a numpy array has no such constraint. It does not affect
detection, because `detect_line` maps NaN to 0.0 before thresholding, which is
why `candidate_sets_identical` holds. It is now asserted by a test rather than
left for the next reader to rediscover.

## 8. Regression tests

`tests/test_anomaly_path_equivalence.py`, 15 tests. The important design point:

**The fixture is asserted to be non-trivial before any equivalence is claimed on
it.** A B-scan on which background removal, dewow and gain happen to do nothing
would let a broken equivalence test pass by proving that neither side did
anything. So the fixture carries a constant horizontal band, a low-frequency
drift and depth-decaying amplitudes, and two tests assert the filters change
>90% of cells *and* change the anomaly result, before anything else runs.

Also pinned: `gpr_local_anomaly` **stays filter-free** (so the composition the
regression baseline pins cannot start double-filtering); `gpr_full` matches the
array path bitwise; `gpr_full` is **not** the
unfiltered statistic (the explicit negative, so a silent revert fails loudly);
the validator still compares the filtered composition (checked by parsing the
call, not the text); no module presents `--verify-arraywise` as a real flag; and
`characterise_4tu` still filters.

## 9. What remains

- **Existing ingested datasets hold unfiltered z-scores.** They are correctly
  reported stale, and nothing recomputes them automatically — regenerating is a
  decision for somebody who can see why. Any candidate set produced before this
  fix describes the unbenchmarked detector.
- **The 4TU characterisation artifact was produced with filters** and is
  unaffected, so the 4TU benchmark numbers stand.
- This stage changed no threshold, no scoring, no truth and no candidate
  semantics.
