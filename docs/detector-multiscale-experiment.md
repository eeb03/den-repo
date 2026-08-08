# Multi-scale estimator experiment

A pre-registered A/B test of one hypothesis:

> Does evaluating the existing ring statistic at multiple spatial scales reduce
> the fixed-scale width-saturation failure measured in the baseline?

**Verdict: the mechanism is addressed; general detection capability is not
established.** The candidate is **not** promoted to baseline.

Every number below comes from `artifacts/experiment/*.json`, produced by
`scripts/experiment_multiscale.py`.

---

## 0. Corrections to the scientific record

Two claims made during this experiment did not survive checking. Both are
recorded here rather than in a footnote, because both changed what the
experiment is entitled to conclude.

### 0.1 The SNR claim is withdrawn

It was stated mid-experiment that the two estimators have near-identical noise
floors, and that the candidate therefore improves signal-to-noise. **That is
not supported.** The measurement behind it used *pure Gaussian noise*, which is
not representative of a radargram.

Measured on real data, fraction of cells above |z| > 3 **before calibration**:

| data | baseline | candidate | ratio |
|---|---|---|---|
| BAM Pk050 control line | 0.0031 | 0.0108 | **3.5×** |
| 4TU survey line | 0.0006 | 0.0090 | **17×** |

| synthetic pure noise | baseline | candidate |
|---|---|---|
| mean max abs z | 4.58 | 4.64 |
| mean fraction > 3 | 0.00389 | 0.00453 |

The floors match on white noise and diverge sharply on real radargrams, because
real data carries structure at many scales and a max-over-scales statistic
responds to whichever scale that structure fits.

The defensible statement, which replaces the withdrawn one:

> The synthetic width experiment demonstrates that the multi-scale estimator
> retains a non-collapsed response at target widths where the fixed-scale
> estimator has collapsed. Real-radargram noise behaviour does not support the
> earlier claim of near-identical noise floors, so SNR improvement has not been
> established.

This pre-calibration firing difference is **a result, not an inconvenience**: it
is the direct reason calibration drove the candidate to τ = 6.8, and the reason
that threshold does not transfer to 4TU. See §3 and §6.

### 0.2 The first 4TU run traversed 123 of 125 activities

- The initial corpus glob matched `*/*/*/Radargrams/*.sgy` and returned **123**
  activities.
- Two activities — **03.7** and **08.1** — store their SEG-Y under
  **`Radarmaps/`**, not `Radargrams/`. The glob matched one spelling only.
- This was **detected before the result was accepted**, by comparing the
  baseline arm against the frozen artifact: AUC came out 0.4429 where the frozen
  value is 0.4452.
- The traversal was corrected to match any subdirectory of the activity.
- The complete **125-activity** corpus was recomputed.
- The corrected baseline now reproduces the frozen artifact **to full
  precision**: AUC `0.4451530612244898`, ρ `-0.06186218355635493`, and the two
  recovered activities give exactly the frozen counts (03.7 = 34, 08.1 = 150).

**The 123-activity run is an implementation error that was found and fixed. It
is not an experimental result and is not reported as one.** All 4TU figures in
this document come from the complete 125-activity corpus.

This is the second source naming inconsistency in this corpus, after
`13.N` / `013.N`.

### 0.3 Calibration was NOT redone because of either correction

The threshold protocol stands as pre-registered: baseline τ = 3.0, candidate
τ = 6.8, calibrated once on Pk050, frozen before any benchmark was evaluated.
The divergence between synthetic and real noise behaviour is part of the
result, not a reason to recalibrate.

## 0.4 Scientific status

**Established**

- The baseline width-saturation mechanism exists, in the synthetic controlled
  experiment.
- The multi-scale candidate avoids that specific synthetic collapse over a
  substantially wider width range.
- The baseline benchmark reproduction is valid, on both BAM and 4TU.
- The corrected 4TU corpus is complete at 125 activities.

**Not established**

- Improved SNR.
- Improved real-world noise behaviour.
- Improved BAM detection.
- Improved 4TU detection.
- Generalised subsurface detection.

## 1. The failure being addressed

`_local_anomaly_grid` estimates a cell's background from an annulus reaching
1–3 traces laterally. Once a target is wider than the outer trace window, the
annulus lies **inside** the target, the background estimate becomes the
target's own amplitude, and the numerator collapses. Measured on a noiseless
top-hat, z falls 3.87 → 0.775 as width goes 1 → 6 and never recovers, against a
threshold of 3.0 — and it is amplitude-invariant there (z = 0.774597 at
amplitude 0.1 **and** at 1000), so contrast cannot rescue it.

## 2. The candidate

The same statistic at four scales, per-cell **max |z|** over scales where the
cell is reliable, NaN only where every scale is unreliable.

| scale | inner (depth,trace) | outer (depth,trace) | lateral support |
|---|---|---|---|
| S0 = baseline | (5, 2) | (15, 6) | 6 traces |
| S1 | (11, 4) | (31, 12) | 12 |
| S2 | (21, 8) | (61, 24) | 24 |
| S3 | (41, 16) | (121, 48) | 48 |

An octave ladder anchored on the measured baseline geometry, **fixed before any
benchmark ran** and never changed afterwards. Reliability thresholds use the
baseline's own convention generalised (`outer − inner` per axis, 25 % of the
joint interior count), which reproduces its hard-coded 20/10/4 exactly at S0.

**The candidate changes spatial scale only; the baseline ring's lateral
asymmetry is intentionally preserved.** Fixing it would add a second variable
and make attribution impossible. A symmetric-ring candidate is a separate
experiment.

## 3. Calibration

The frozen baseline uses **one global threshold (3.0)** for both BAM
frequencies and 4TU — it has no per-frequency calibration. The candidate
therefore gets **one** global threshold too, or it would enjoy more free
parameters.

Chosen on **Pk050 alone** (the attested-empty specimen) to match the baseline's
**pooled** control detections-per-line, then frozen: **τ = 6.800**.

| | baseline | candidate |
|---|---|---|
| threshold | 3.0 | **6.800** |
| control detections / 322 lines | 723 | 682 |
| control rate per line | 2.2453 | 2.1180 |

The match is one grid step off, landing **below** the baseline rate — the
candidate is very slightly handicapped, not favoured. Pk266 and 4TU were not
read during calibration.

**Why the threshold had to move so far.** Before calibration the candidate
fires 3.5× more often than the baseline on the BAM control and 17× more on a
4TU line (§0.1). Matching the control rate therefore forced τ from 3.0 to 6.8.
That is a measured property of the estimator on real data, not a tuning
artefact.

## 4. Synthetic falsification — passed

|z| at target centre:

| width (traces) | 1 | 3 | 6 | 13 | 24 | 48 | 64 |
|---|---|---|---|---|---|---|---|
| baseline | 2.52 | 1.30 | **0.74** | 0.74 | 0.75 | 0.77 | 0.79 |
| candidate | 19.13 | 18.77 | 18.02 | 15.63 | 5.36 | 2.94 | 2.98 |

The baseline flattens at 0.74 from width 6. The candidate holds well past it and
collapses just beyond **48 — its largest scale**, as predicted.

**The retention metric is reported unchanged: baseline 0.406, candidate 0.398.**
It is nearly identical between arms because it normalises each arm by its own
narrow-target response while ignoring the threshold; it is kept here rather than
dropped.

**Raw |z| is not a fair cross-estimator performance metric before calibration** —
the arms use different window sizes and therefore different z scales.

Amplitude at saturated width 13: baseline asymptotes at 0.645, candidate at
29.3. This shows the baseline's saturated-width response stays **below its
detection threshold** while the candidate retains a stronger response. It does
**not** by itself establish real-world sensitivity.

Conservative statement: **the candidate has not been mechanistically falsified.
It substantially extends the width range over which the estimator retains a
non-collapsed response, consistent with the intended scale-space mechanism.**

## 5. BAM — improves, but narrowly and unevenly

| metric | 1.5 base | 1.5 cand | Δ | 2.6 base | 2.6 cand | Δ |
|---|---|---|---|---|---|---|
| TP | 45 | 153 | +108 | 63 | 299 | +236 |
| FP | 288 | 915 | +627 | 367 | 1315 | +948 |
| FN | 602 | 491 | −111 | 584 | 488 | −96 |
| Recall | 0.0652 | 0.2376 | +0.1724 | 0.0932 | 0.2422 | +0.1490 |
| Precision | 0.1351 | 0.1433 | +0.0082 | 0.1465 | 0.1853 | +0.0388 |
| F1 | 0.0880 | 0.1787 | +0.0907 | 0.1139 | 0.2099 | +0.0960 |
| Control det/line | 2.789 | 0.932 | −1.857 | 1.702 | 3.304 | +1.602 |

**The pooled FA match hides a per-frequency imbalance**: at 1.5 GHz the
candidate fires a third as often on the control, at 2.6 GHz nearly twice as
often. The frequencies are not on equal FA terms.

### The chance baseline

Target footprints cover 52 of 401 nodes, so **randomly placed detections score
precision 0.1297**:

| arm | precision | TP ÷ chance |
|---|---|---|
| baseline 1.5 GHz | 0.1351 | **1.04** |
| candidate 1.5 GHz | 0.1433 | 1.10 |
| baseline 2.6 GHz | 0.1465 | 1.13 |
| candidate 2.6 GHz | 0.1853 | **1.43** |

**The baseline's BAM detection was essentially chance.** The candidate is only
modestly above it, clearly so at 2.6 GHz alone. Much of the recall gain is the
mechanical consequence of producing 3–4× more detections. (Approximate: real
detections are not uniform over nodes — there is a specimen-edge concentration
near nodes 382–389 present in *both* specimens.)

### Per-duct — the gain is confined to one target

Lines with a match, of 161:

| duct | depth | 1.5 base → cand | 2.6 base → cand |
|---|---|---|---|
| duct-1 | 274.5 mm | 8 → **0** | 10 → **0** |
| duct-2 | 214.6 mm | 9 → **0** | 13 → **0** |
| duct-3 | 151.4 mm | 21 → **0** | 15 → 4 |
| duct-4 | 94.4 mm | 4 → **153** | 22 → **152** |

The candidate finds duct-4 on ~95 % of lines and **loses ducts 1–3 entirely**.
There is a partial mechanistic defence — an independent energy analysis found
duct-4 is the only duct with demonstrable signal contrast — but the deeper ducts
regressed, and the baseline's hits on them were themselves near chance.

### One measure that favours the candidate unambiguously

Detections on the target specimen vs the attested-empty one (both numbers from
the frozen scoring; this is their ratio, not a new metric):

| arm | Pk266 | Pk050 | ratio |
|---|---|---|---|
| baseline 1.5 GHz | 333 | 449 | **0.74** |
| candidate 1.5 GHz | 1068 | 150 | **7.12** |
| baseline 2.6 GHz | 430 | 274 | 1.57 |
| candidate 2.6 GHz | 1614 | 532 | 3.03 |

The baseline at 1.5 GHz fires *less* on the specimen containing targets than on
the empty one — no specimen-level discrimination at all. The candidate fires 7×
more, while firing *fewer* times on the control, so this is not explained by
detection volume.

## 6. 4TU — no generalisation

Complete corpus, 125 activities, identical preprocessing, truth, scoring and
detection semantics. **The baseline arm bit-reproduces the frozen benchmark**
(AUC 0.4451530612244898, ρ −0.06186218355635493), which is the integrity proof
that this is the committed protocol and not a re-implementation.

| metric | baseline τ=3.0 | candidate τ=6.8 | Δ |
|---|---|---|---|
| **AUC** | 0.4452 | 0.4216 | **−0.0236** |
| **Spearman ρ** | −0.0619 | −0.0576 | +0.0043 |
| candidates, utility-bearing | 20,718 | 1,197 | −19,521 |
| candidates, trench-empty | 8,261 | 616 | −7,645 |
| median /1k, utility-bearing | 31.18 | 1.89 | −29.29 |
| median /1k, trench-empty | 24.34 | 4.49 | −19.85 |
| positive activities with 0 candidates | 0 | 15 | +15 |
| activity-level response rate | 1.000 | 0.866 | −0.134 |
| unexplained response rate | not computed | not computed | — |
| object-level metrics | blocked | blocked | — |

Paired bootstrap over activities, 5,000 resamples: **ΔAUC 95 % interval
[−0.296, +0.194]**, with 46 % of resamples favouring the candidate.

**The difference is not distinguishable from zero.** With only **7** attested-zero
activities the AUC denominator rests on 7 independent negative units, so the
interval is wide and fragile. This analysis is **exploratory**.

The honest reading: **4TU discrimination is unchanged — both arms sit at or
below chance (AUC < 0.5), and neither shows a relationship between candidate
counts and utilities found.** "Not worse" is not evidence of improvement.

Note the candidate's median density is **higher on trench-empty ground (4.49)
than on utility-bearing ground (1.89)** — the wrong way round, consistent with
AUC below 0.5.

## 7. Against the pre-registered falsifiers

| # | falsifier | outcome |
|---|---|---|
| 1 | synthetic still collapses | **No** — retained response to width ≈48 |
| 2 | improvement only after tuning scales to benchmarks | **No** — ladder fixed in advance, never changed |
| 3 | BAM gain only via increased false alarms | **Mixed** — at 2.6 GHz FA rose 1.9×; at 1.5 GHz it *fell* to a third and recall still rose |
| 4 | BAM improves while 4TU materially deteriorates | **Partly** — BAM improves, 4TU is unchanged within noise |
| 5 | gains confined to one frequency/target without mechanism | **Triggered on target** — the entire gain is duct-4, though a partial mechanism exists |
| 6 | changes benchmark semantics | **No** — truth, scoring, gates and thresholds untouched |

## 8. Conclusion

The candidate **addresses the width-saturation mechanism** it was designed for:
that is established on synthetic data and is not in doubt.

It **does not establish general subsurface detection capability**. The BAM gain
is real but concentrated on the single duct with demonstrable signal, comes with
regression on the other three, and is only 1.10–1.43× chance in placement. The
4TU generalisation test shows no improvement, with both arms at chance.

**Recommendation: do not promote the candidate to baseline.** Keep it as a
separately selectable estimator for further investigation. The most informative
next step would be a target-scale-stratified analysis on a corpus with more than
7 negative units — the current 4TU negative population cannot resolve
differences of this size.

## 9. What was not changed

Baseline estimator, BAM/4TU truth, benchmark scoring, gates, provenance, tier,
artifact schemas, and the frozen artifacts themselves. The only edit to existing
code is a one-parameter `estimator=` hook on `benchmark.detection.detect_line`/
`detect_scan`, whose default path is **verified bit-identical to the committed
pre-hook file** (12/12 cases). Localisation remains BLOCKED and was not
attempted.

### Artifact reading note

`activities_walked` in `multiscale_4tu_complete.json` reads **2**, because that
run computed the two activities recovered by the traversal fix (§0.2) and merged
the rest. The scored corpus is **125** (`n_activities_scored`). Merging is
exactly equivalent to a full re-run because each activity's counts depend only
on its own files — proven by the baseline arm reproducing the frozen AUC and ρ
to full precision.
