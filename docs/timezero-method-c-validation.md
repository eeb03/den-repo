# Method C time-zero validation: **experimental**

Method C (`preprocessing.time_zero.direct_wave_consensus_time_zero`) was run
unchanged, through the production path, against a pre-registered corpus of
first-break references on held radar lines. Its thresholds were not touched.

**Verdict: experimental.** Where a line has a clean pre-arrival window it lands
within a few samples of an operator's first break. But it also returns a
confident `derived` on lines that have **no direct wave at all**, so a `derived`
status is not by itself evidence that anything was found. No uncertainty can be
assigned: there is no independent reference in the holdings. It stays
operationally available and scientifically insufficient; the benchmark depth
gate is unchanged.

Reproduce:

```
python -m scripts.timezero_operator_view --out <dir> --table-samples 90 <kind:path> ...   # picking aid, no Method C
python -m scripts.validate_timezero_method_c --out artifacts/timezero/method_c_baseline.json
```

## 1. The references, and what they are worth

`validation/timezero_references.json` -- a timing corpus kept out of
`benchmark/` (object truth); the loader refuses target, label, depth and
velocity keys.

- **No documented or independent reference exists in the holdings.** The best
  route is Falerii's *processed* profiles: the authors aligned time zero by
  cross-correlation, "defined as the first break position", so matching
  processed to raw traces would recover the authors' own first break. They are
  not held. TestUM's air-WARR calibration is independent of the subsurface but
  passes its own slope falsifier on 2 of 26 files
  (`docs/testum-air-warr-t0-experiment.md`). MALA `SIGNAL POSITION` and GSSI
  `rhf_position` remain refused.
- **Every reference is an `operator_reference`**, `independent: false`: one
  picker (Claude, acting as operator), one reading, from
  `scripts/timezero_operator_view.py`, which does not import Method C (a test
  checks its imports). Files were chosen by a fixed rule **before** any Method
  C output was seen for them; the five files whose Method C picks the picker
  had already seen (Falerii 0001, 4TU 01.1 Path8 and 010.9 Path1, MALA Grimsel,
  IDS 600 MHz limestone) are deliberately excluded.
- **Definition:** first break = the first sample of a sustained departure of
  the median trace from its pre-arrival baseline, on the raw axis. Method C
  instead marks the first 3-sample run above 5 sigma of the first 8 samples.
  The two are not the same event; part of every error below is that
  difference, not a mistake by either.

20 references (6 Falerii, 7 4TU, 3 MALA, 3 IDS, 1 GSSI) and 6 files with **no
reference** (Falerii 0800 -- the recording starts inside the direct wave; four
INGV lines -- no coherent direct wave; one GSSI profile -- no sharp onset).

## 2. Results (operator references only; never pooled with other evidence)

| | value |
|---|---|
| references | 20 (16 high/medium confidence) |
| Method C `derived` | 18 / 20 (2 inconclusive) |
| median absolute error | **0.47 ns** (2.8 samples) |
| mean absolute error | 0.85 ns |
| maximum absolute error | **6.32 ns** (65 samples) |
| bias, median signed (pick - reference) | **+0.36 ns** (late) |
| within the reference's own uncertainty | 6 / 18 |
| 95th percentile | **not estimated** -- 18 errors, fewer than 20 |
| uncertainty | **not yet established** -- 0 independent references |

By format (signed error, ns; positive = Method C late):

| format / dataset | n | errors | median abs |
|---|---|---|---|
| SEG-Y, Falerii (pulseEKKO) | 6 | +0.43 +0.95 +0.52 +1.08 +0.50 +0.59 | 0.56 |
| SEG-Y, 4TU | 7 | +0.19 +0.15 -0.45 **+1.42** +0.44 +0.05 +0.80 | 0.44 |
| MALA, TU1208 (250 MHz) | 3 | +0.28 -0.00 -0.23 | 0.23 |
| IDS, TU1208 | 3 | -0.85, **-6.32**, inconclusive | 3.59 |
| GSSI, TestUM | 1 | inconclusive | -- |

Trace level: Method C picks every trace independently. There is no per-trace
reference, so per-trace picks are reported only as a distribution and as
"per-trace pick minus the file reference" (in the artifact), never as per-trace
accuracy.

**Determinism:** every file gave an identical status, pick, spread and pick
count on repeated runs; shuffled input gives the same answer; the module holds
no randomness (tests).

## 3. Failure modes, each with its mechanism

1. **Threshold-crossing bias (Falerii, all 6 late by 0.43-1.08 ns).** Quiet
   sigma is ~5.5 counts, so 5 sigma is ~27 counts; the small precursor takes
   2-5 samples to grow that far. Definitional and systematic -- not a bug.
2. **Arrival inside the quiet window (4TU 06.1 +1.42 ns, 07.1 +0.44).** Only
   3.5 pre-arrival samples, fewer than the 8 the quiet window assumes; quiet
   sigma is 1,991 against ~5 of real noise, so the pick lands late. Method C
   cannot detect that its own assumption failed.
3. **Slow drift read as an onset -- false `derived` (INGV, GSSI).** Three INGV
   lines with no laterally coherent direct wave (ground cart and UAV) all return
   `derived` at **3.809 ns, spread 0.586** -- a smooth low-frequency drift
   crosses 5 sigma of a small 8-sample window at about the same time on every
   trace, so the consensus is tight and wrong. The same mechanism puts IDS
   200 MHz gneiss 6.3 ns early (pre-arrival wobble), 4TU 04.1 0.45 ns early
   (drifting baseline), GSSI C05's traces ~8.7 ns early (hence inconclusive),
   and returns a false `derived` 7.9 ns on GSSI D05_C12, which has no sharp
   onset. **The spread gate does not catch this, because the artefact is as
   consistent across traces as a real arrival.** INGV's sections are consistent
   with gain and background removal before export (which erase a direct wave),
   a hypothesis, not established.
4. **Truncated window (Falerii 0800).** The recording starts inside the direct
   wave; Method C returns inconclusive. Safe.
5. **Arrival varies across traces (GSSI C05).** The single-shift model does not
   hold on that line; inconclusive. Safe.

Why INGV is inconclusive on C1T_0001: its per-trace picks span 2.93 ns, over
the 2.0 ns consistency bound -- and on the other three INGV lines the same
drift happens to be more uniform, which is exactly why they pass when they
should not.

## 4. Two correctness bugs found and fixed (separate commits)

- **IDS `.dt` samples were decoded unsigned** (`fix(ids): decode .dt samples as
  signed int16`). 162,572 adjacent-sample jumps > 32768 unsigned, 0 signed,
  across the 20 readable held files. This corrupted every IDS waveform the
  platform held. Method C's IDS 600 MHz limestone pick is unchanged at 2.7333
  ns (it lies before the first zero crossing, where both readings agree).
- **GSSI marker samples entered Method C's quiet window** (`fix(gpr): exclude
  converter-declared marker samples from Method C`). The converter declared
  them (`leading_samples_may_be_markers` = 2); Method C ignored the
  declaration. Quiet sigma 23,992 vs 214 (C05) and 155,346,820 vs 22.5 (D05).
  Before: C05 `derived` +2.24 ns late, D05 0/67 picks. After: C05
  inconclusive (drift, mode 3), D05 false `derived` 7.9 ns (mode 3). Fixing the
  bug removed one wrong answer and exposed the underlying weakness; both are
  reported, neither is tuned away.

No threshold, window length or picking rule changed. Held Falerii, 4TU, INGV
and MALA picks are identical before and after both fixes.

## 5. What would move this

- A **documented** reference: Falerii's processed profiles (authors' first
  break), or a vendor/system-delay measurement.
- A **second, independent operator** reading the same pre-registered files,
  to measure reader disagreement -- the floor under every number above.
- Only then: a validity check for Method C (for example, refusing a pick whose
  amplitude is small relative to the trace's direct-wave peak, or a quiet window
  that visibly contains signal), developed on files outside this corpus and
  re-scored here once.
