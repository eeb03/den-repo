# Radargram display modes

The radargram can show two things: what the detector saw, and the signal it was
computed from. This document says exactly what each one is, and — more
importantly — what neither of them claims.

## 1. Why two modes

`preprocess_trace_local_anomaly` **overwrites** `record.signal` with the
local-anomaly z-score and preserves the value it replaced in
`metadata["pre_anomaly_signal"]`. Until now the viewer could only render
`signal`, so a reviewer asked to accept or reject a candidate saw the statistic
and never the values it was derived from.

Both modes are **projections of the same records onto the same grid**. Nothing is
recomputed, rescaled or reprocessed when a reviewer switches.

## 2. Exact source of each mode

| | Mode A | Mode B |
|---|---|---|
| Label | **Local-anomaly z-score** | **Pre-anomaly signal** |
| `field` | `signal` | `pre_anomaly_signal` |
| Source | `record.signal[0]` | `record.metadata["pre_anomaly_signal"]` |
| Unit | `σ` (standard deviations) | **none** |
| Measured or derived | **derived statistic** | the value held before the anomaly step |
| Reliability mask applies | **yes** | **no** (see §5) |

## 3. What Mode B is, and is not

`pre_anomaly_signal` is *the value `signal` held immediately before the
local-anomaly step replaced it*. What that value **is** depends on what ran
before, and the pipeline decides that:

- `run_pipeline(mode="gpr_local_anomaly")` calls the anomaly step **directly** —
  no background removal, no dewow, no gain. Verified on a real 4TU line:
  `pre_anomaly_signal` is **identical to a fresh conversion of the source file
  in all 160,768 cells**, and its range is exactly int16 (−32,768…32,764), i.e.
  the SEG-Y samples as stored.
- `run_pipeline(mode="gpr_trace_processing")` is a *different* mode that does
  apply background removal, dewow and gain. A dataset put through it first would
  carry a filtered value here.

So the honest name is **"pre-anomaly signal"** and nothing stronger. It is **not**
called raw amplitude, true amplitude, physical amplitude, calibrated amplitude or
ground truth, because the repository establishes none of those.

**No unit is claimed.** `SubterraRecord.signal` is documented as "raw or
processed trace/measurement"; the converters document units for the time axis
(`ns`, `ms`) and never for amplitude. The colour scale in Mode B therefore
carries a number and no unit, and the UI states that no physical calibration is
implied.

## 4. What the toggle cannot change

Both modes share, byte for byte:

- trace indices and depths
- vertical-axis semantics (including the derived-depth caveat)
- horizontal-axis semantics and trace ordering
- the reliability mask
- **candidate footprints**
- per-trace geometry (`trace_lat`, `trace_lon`, `trace_geographic`, along-track)

Verified against the running API: every one of those fields is equal between the
two responses, and only `grid` differs. A candidate found in the anomaly view
therefore sits over exactly the same supporting cells in the pre-anomaly view. A
marker that moved would send a reviewer to inspect traces the detector never
proposed.

The toggle also does not touch velocity, origin, vertical datum, surface
reference, spatial registration, candidate scores or the BLOCKED classification
state.

## 5. Reliability — the mask is not shared

This is the one place where naively reusing Stage 15's behaviour would have been
wrong, and the measurement says so.

The mask marks cells whose **ring** had too few neighbours to estimate a
background from. Measured on a real line:

| | |
|---|---|
| Unreliable cells | 6,886 of 160,768 |
| ...that still hold a valid pre-anomaly value | **6,886 (100%)** |
| ...whose z-score was forced to `0.0` | **6,886 (100%)** |

So the mask is a property of the **anomaly statistic**, not of the signal it was
computed from:

- **Mode A** fades unreliable cells, because their z-score is a `0.0`
  placeholder sitting exactly where a genuine "no anomaly" would sit.
- **Mode B** does not fade them, because those cells hold perfectly good stored
  values. Fading them would present sound measurements as untrustworthy. The UI
  says why instead.

`FieldSemantics.reliability_applies` carries this, so the viewer is told rather
than left to assume. The frontend defaults it to `true`, so an older backend
keeps Stage 15's behaviour rather than silently un-fading.

## 6. Missing values

Unchanged in both modes. A cell with no `pre_anomaly_signal` renders as a **gap**
and is never filled in from `signal` — which after preprocessing is the z-score,
a different quantity. Substituting one for the other would show a statistic under
a signal's label. A dataset that never went through the anomaly step has no
pre-anomaly values at all, and Mode B is entirely empty for it rather than
falling back.

## 7. API

No new endpoint. `GET /api/datasets/{id}/trace_grid` gained a validated `field`
vocabulary:

```
field = signal | pre_anomaly_signal | elevation | absolute_elevation_m
```

An unknown field is **422**, not a silent fallback:

```
unknown field 'amplitude'; this endpoint projects signal,
pre_anomaly_signal, elevation or absolute_elevation_m
```

The response's `semantics.field` carries `label`, `units` (null where none is
established), `description`, `is_statistic`, `reliability_applies` and
`reliability_note`, so the viewer never decides what a projection means.

## 8. Performance

The toggle re-requests the grid, because the projection happens server-side
where the records already are. It does **not** re-read the records: both
projections go through the Stage 16 shared cache, and the candidate set is not
refetched at all (a frontend test asserts `getCandidates` is called exactly once
across a toggle).

Measured on a real 160,768-record line on an idle machine:

| | |
|---|---|
| First radargram (cold cache) | 7.6 s |
| Toggle → pre-anomaly | **1.44 s** |
| Toggle back → anomaly | **1.51 s** |
| Further toggles | 1.17 s, 1.38 s |
| Candidate refetch on toggle | **none** |
| **Record parses across four projections (two toggles)** | **1** |

The parse count is the robust measure and is asserted directly rather than
inferred from a stopwatch: four projections of the same dataset cost **one**
parse, so a toggle re-projects records that are already in memory.

The remaining ~1.4 s is grid construction and JSON serialisation of ~160k cells,
not record loading. Caching the built grids per field would remove it and was not
done: it would add a second staleness surface for a 1.4 s interaction, and Stage
16's discipline was to fix what measurement identified rather than what sounds
faster.

An earlier set of timings for this table was discarded because the backend test
suite was saturating the same cores — the same contamination Stage 16 hit, and
the reason the parse-count assertion exists alongside the clock.

## 9. Known limitations

- **Only two representations.** A dataset processed with `gpr_trace_processing`
  stores its filtered signal in the same slot, and the label cannot currently
  distinguish "converter output" from "filtered output" — it says only
  "pre-anomaly". Distinguishing them would need the pipeline to record which
  steps ran, which it does not.
- **A toggle costs a round trip** (4–6 s on a large line).
- **No unit will ever appear** for Mode B until something in the ingest chain
  establishes one. That is correct, not a gap to be filled with a guess.

## 10. An inconsistency found while auditing, not fixed here

`anomaly_grid_from_traces` — the array path used by the BAM benchmark — applies
`background_removal → dewow → apply_gain` before the ring statistic, and its
docstring states this is "the IDENTICAL functions in the IDENTICAL order that
`preprocess_trace_local_anomaly` does". **It is not**: the record path applies
none of them. The two paths are documented as equivalent and are not.

This is out of scope for a viewer stage and is recorded rather than changed. It
matters because `scripts/characterise_4tu.py --verify-arraywise` asserts the two
produce the same grid, so either that check is passing for a reason other than
the one claimed, or the corpora it runs on make the filters no-ops. Worth
resolving before any future benchmark work relies on the equivalence.
