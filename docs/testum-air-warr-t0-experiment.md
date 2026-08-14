# TestUM air-WARR t₀ — **INCONCLUSIVE**

**This is not a successful calibration.** No TestUM t₀ is adopted, and nothing is
transferred to 4TU. The stage is recorded because a reproducible inconclusive
experiment is worth more than an unsupported number.

Reproduce: `python -m scripts.testum_air_warr_t0 --out artifacts/testum/air_warr_t0.json`

## What the experiment does

TestUM publishes 26 air-WARR calibration files (`*_t0_start/mid/end.DZT`) across
13 survey days, with the protocol stated per file in the PANGAEA metadata —
X = 1→3 m in 0.2 m steps (11 traces), or 1.5→3 m in 0.1 m (16 traces). Each
trace is one antenna separation. The model has exactly one unknown:

```
t_measured(X) = t₀ + X / c_air        c_air = 0.299792458 m/ns
```

No subsurface reflector, depth or velocity enters it. That independence is what
Stages 24–28 could never obtain.

## The falsifier, and why it matters more than the answer

Fitting gives an intercept **and** a slope — and the slope is known in advance:

```
expected slope = 1 / c_air = 3.336 ns/m
```

So the experiment can detect that the data has been read wrongly instead of
returning a plausible intercept anyway. Trace ordering, separation assignment,
units and picking all have to be right for the slope to come out at 3.336.

**It rejected the work.** Over the **complete corpus: 25 of 26 files analysed,
2 passed.** Observed slopes span **−5.99 to +17.33 ns/m** against an expected
3.336:

| Observed slope (ns/m) | vs expected 3.336 |
|---|---|
| −5.99 … −0.05 (many) | wrong sign — baseline inflections |
| +1.82, +6.63 | 45%, 99% error |
| **+16.24, +17.33** | **390–420% error** |
| **+3.18, +3.33** | **4.6%, 0.2% — pass** |

Slopes with the wrong sign, or above 16 ns/m, are not noisy measurements of a
3.336 ns/m quantity. The picker is finding turning points in the baseline.

*(An earlier partial run over the 13 files then staged reported 1 of 13; the
figures above supersede it and are the complete result.)*

## The limited positive evidence — **not adopted**

| File | slope | error | t₀ |
|---|---|---|---|
| `20231205_GEWS_t0_end.DZT` | 3.329 | **0.2%** | **22.13 ns** |
| `20230824_GEWS_t0_end.DZT` | 3.181 | 4.6% | **21.01 ns** |

The 2023-12-05 file recovers the air slope to **0.2%**, which is a striking
confirmation that the model and the geometry are right *when the picking works*.
Within the 2023-08-24 file, 8 of 11 observations gave t₀ = 20.25–20.69 ns —
`t − X/c_air` constant across separations, as predicted.

**And these are explicitly NOT adopted as TestUM's t₀.** Two files out of 26
pass, and **the two that pass disagree by 1.12 ns** (21.01 vs 22.13, on days
three months apart). A calibration that cannot be reproduced on 23 of 25 files,
and whose two survivors differ by more than a nanosecond, is not a measurement.
Nothing here is smoothed, reinterpreted or selectively promoted, and day-to-day
variation cannot be quantified from two non-agreeing days.

## A bug in the tooling, recorded

The first version of the picker returned **nothing on every file**. Samples 0–1
carry a marker value (`-469762048` observed) rather than signal; included in the
noise estimate they made the threshold enormous, so no sample ever cleared it.

The GSSI converter already documents this as
**`leading_samples_may_be_markers = 2`** — the platform knew, and this module did
not. It now skips the same two samples (`MARKER_SAMPLES`). The fix is what
produced the one coherent file above.

## Why the picking fails

The traces carry a large, smoothly varying baseline drifting by thousands of
counts across the wavelet (trace 0 runs −43156 → −48517 over ~20 samples). So
amplitude thresholding picks the baseline, and naive turning-point detection
picks its inflections. Both failure modes are visible in the slope table.

## Status

| | |
|---|---|
| Verdict | **INCONCLUSIVE** |
| TestUM t₀ | **not derived** |
| TestUM velocity | **not derived** — needs t₀ |
| 4TU time-zero | **BLOCKED** |
| 4TU propagation velocity | **BLOCKED** |
| 4TU physical depth | **BLOCKED** |
| 4TU absolute subsurface elevation | **BLOCKED** |
| Stages 8–12 | **no change** |
| Transferred to 4TU | **nothing** |

## Recommended next experiment

**Cross-correlation against a reference wavelet**, exploiting a property this
experiment does not yet use: all 11 traces in a file contain *the same* emitted
wavelet at shifting arrival times. So the picking problem is a *relative* shift
problem, which is far better conditioned than absolute onset detection:

1. Detrend each trace (remove the smooth baseline — a high-pass or polynomial
   fit), which is the actual cause of the failures above.
2. Take the X = 3 m trace as the reference wavelet, per the authors' own rule
   that X = 3 m avoids near-field effects.
3. Cross-correlate every other trace against it; the lag gives the *relative*
   arrival time to sub-sample precision.
4. Anchor the sequence by fitting the relative lags against X. **The slope check
   stays**: if the fitted slope is not 3.336 ns/m, the result is still rejected.
5. Only then take the intercept as t₀, and only if the slope passes across
   *many* files and days.

The slope test should be kept as the acceptance gate. It is the only thing in
this line of work that has been able to say "you read the data wrong".
