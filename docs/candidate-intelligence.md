# Candidate intelligence

What a candidate is in Subterra, what is known about where it is, how it is
produced reproducibly — and what the method that produces it actually achieves,
which on present evidence is approximately nothing.

## 1. The definition

> A candidate is a region of the processed signal whose measured
> characteristics satisfy a candidate-generation rule.

It is **not** a detected object, a validated detection, or evidence that
anything is buried at that location. The platform is built so that it cannot
become one by accident:

| Protection | Where it lives |
|---|---|
| No field can hold an object class, probability or confidence | `AnomalyCandidate`, `InspectableCandidate` — the fields do not exist |
| Object classification is `BLOCKED` | `CLASSIFICATION_STATUS`, with no code path that sets it otherwise |
| The only score says what it is not | `CANDIDATE_SCORE_MEANING` |
| Measured performance travels with the data | `BenchmarkContext`, in every API payload |
| Acceptance is "worth retaining", not truth | `CandidateStatus`, and the review endpoint's own response |

`tests/test_candidate_intelligence.py` holds each of these as an invariant, and
`frontend/components/candidates/candidate-intelligence.test.tsx` holds the
render-level equivalents.

## 2. The hierarchy this preserves

```text
measurement → processed signal → feature → anomaly → candidate
                                                        ↓
                                        [ human review · validation ]
                                                        ↓
                                            validated detection → classification
```

Stage 13 stops at **candidate**. Everything to the right of the review step is
unimplemented, and deliberately so: no validated classifier exists here, and no
benchmark in this repository supports mapping a candidate to an object identity.

## 3. Measured performance — the honest headline

All three numbers below were reproduced from the current repository, not quoted
from the roadmap. K=1 arms are bit-identical to the committed artifacts.

| Benchmark | Arm | Precision | Recall | F1 | vs chance |
|---|---|---|---|---|---|
| BAM concrete | 1.5 GHz | 0.1351 | 0.0652 | 0.0880 | **1.04×** (chance 0.1297) |
| BAM concrete | 2.6 GHz | 0.1465 | 0.0932 | 0.1139 | **1.13×** |

| Benchmark | Metric | Value | 95% interval | Verdict |
|---|---|---|---|---|
| 4TU utility | separation AUC | 0.4452 | [0.2219, 0.6607] | **spans chance** |
| 4TU utility | count agreement ρ | −0.0619 | — | no relationship |

**The detector is at approximately chance on both benchmarks.** That is a
measured result, it is displayed in the product, and it is the reason this stage
built a trustworthy candidate *layer* rather than claiming a working detector.

One correction to the previous framing: the 4TU result has been described as
"at or below chance". The bootstrap interval above rests on **seven** negatives
and spans chance in both directions, so that benchmark cannot currently
distinguish this method from chance **in either direction**. "Below chance" was
overclaiming a precision the corpus does not have.

## 4. Benchmark leakage — found, measured, and not the explanation

`scripts/audit_benchmark_leakage.py` hashes the whole 4TU corpus and asks which
activities are built from the same bytes. Applying the Stage 7 lesson to a
benchmark rather than a catalogue:

- 759 radargrams, **721 unique** — 34 duplicate groups span more than one activity
- six activities are duplicated **in full** (`02.2/02.4`, `03.5/03.6`,
  `010.11/010.12`, `010.15/010.16`, `013.1/013.2`)
- **activity `09.7` — one of only seven negatives — shares a byte-identical
  radargram with `09.6`, a positive**

Rescoring with each measurement counted exactly once drops 125 activities to
121 and moves the AUC from 0.4452 to 0.4511. So the leakage is real, it is now
recorded in `artifacts/4tu/leakage.json`, and **it does not explain the result**.
Both intervals still span chance.

The audit finds exact duplicates only. Two acquisitions of the same trench on
the same day are near-duplicates no checksum will catch, so a clean report is
evidence that units are not identical — not that they are independent.

## 5. The method experiment: rejected on evidence

**Hypothesis.** An object that occupies space produces a response in several
adjacent traces. The baseline rule can be satisfied by a single trace, so it
admits candidates no physical object could have produced. Requiring a span of at
least K trace columns should discard those.

**Design.** One thing changed — a post-filter on trace span. The estimator,
threshold, 4-connected labelling and `min_cells` are the baseline code called
unchanged. K was chosen on the **Rot90** scans and only then reported on
**Rot00**, the rotation every published number was computed on.

**Result** (`artifacts/experiment/trace_span.json`, test split, 1.5 GHz):

| K | detections | precision | recall | F1 |
|---|---|---|---|---|
| **1 (baseline)** | 333 | 0.1351 | 0.0652 | **0.0880** |
| 2 | 68 | 0.1471 | 0.0155 | 0.0281 |
| 3 | 0 | — | — | — |

Calibration selected **K = 1 — the baseline**. The hypothesis is **rejected**:
precision rises trivially while recall collapses fourfold, and by K=3 there is
nothing left at all. `min_trace_span` ships with a default of 1, which
reproduces the baseline exactly, and the parameter is retained only so the
finding can be re-derived.

**What the failure revealed is worth more than the change would have been.**
Detections fall 333 → 68 → 0 across K = 1, 2, 3. Essentially **no candidate this
detector produces spans three traces**. A buried duct crossed by a survey line
must produce a laterally continuous response; this method is responding to
near-point excursions instead. That is a concrete, measured account of *why* it
sits at chance, and it points at the estimator rather than the threshold.

## 6. Location and depth — only what is known

Localisation is a level of **evidence**, not of precision:

| Level | Meaning |
|---|---|
| `spatially_registered` | the supporting traces carry geographic positions |
| `frame_relative` | along-track distance is measured; no geographic position |
| `trace_relative` | locatable as traces within a named file — a real location, not a coordinate |
| `unknown` | no defensible location exists |

Depth has no `measured` path from a velocity. A velocity is an assumption about
the ground, so a depth converted with one is `derived` and is labelled that way
everywhere it appears. With no velocity the answer is `unavailable`: the
candidate has a position on the instrument's own axis, which is not a depth. The
UI prints no depth number in that state — Stage 12 established that relating the
depth-axis origin to the ground does not by itself create a physical depth, and
this stage does not quietly undo it.

## 7. Provenance, reproducibility and staleness

Every stored set carries a `CandidateGeneration`: method, version, parameters,
input fingerprint, the newest spatial declaration at generation time, record and
source-file counts, and a determinism note. The method uses no randomness, so
`seed` is null and `deterministic` is true — the field exists so a method that
does use randomness has somewhere honest to record it.

A set is reported **stale**, never silently refreshed, when:

- the method version changed, or
- the records changed (count, source files, preprocessing), or
- a spatial declaration was recorded after generation — Stage 8's rule, since a
  CRS, datum, tie or velocity changes what the data means, or
- the requested parameters differ from the stored ones.

`CandidateStaleness` also reports which checks it **could not** run. The report
has no database session, so it cannot see declarations; "not stale" and "not
known to be stale" are different claims and the payload distinguishes them.

Nothing is recomputed automatically. Re-running the detector to hide a change
would conceal exactly the thing being reported.

## 8. Where it lives

| Concern | Module |
|---|---|
| Candidate generation (unchanged) | `interpretation/anomaly_candidates.py` |
| Semantics, certainty, provenance, staleness | `interpretation/candidate_intelligence.py` |
| Storage | `database/candidates_store.py` (`.candidates.json`) |
| Generation service and blocked states | `api/candidates.py` |
| HTTP surface | `api/routes/candidates.py` |
| Report summary | `schemas/dataset_report.py::CandidateSummary` |
| UI | `frontend/components/candidates/candidate-intelligence.tsx` |
| Leakage audit | `benchmark/leakage.py`, `scripts/audit_benchmark_leakage.py` |
| Span experiment | `scripts/experiment_trace_span.py` |

`CandidateSummary` was **extended, not replaced**. Its existing protections
already prevented a candidate from claiming an object; what it could not answer
was whether a set is still trustworthy — which method produced it and whether
the dataset has since changed. A count with no generation record cannot be
reproduced or invalidated, and `method: null` is how the report says that has
happened.

Candidates are stored rather than recomputed per request because generation over
a real corpus is minutes of work. The original on-demand design existed to avoid
serving a cached result that no longer matches the data; storing the generation
record alongside the candidates satisfies that concern rather than overriding it.

## 9. Computational cost

| Operation | Measured |
|---|---|
| BAM scan scored (161 lines, 2 specimens) | ~48–54 s |
| Trace-span experiment (8 detection passes, 4 scans × 2 rotations) | 196 s |
| 4TU leakage audit (759 files hashed, 1.3 GB) | ~90 s |
| Candidate generation, 2 400-record synthetic line | < 1 s |

CPU only. No GPU, no trained model, no model file — `models/` is empty and
nothing in this path loads one. Memory is dominated by records rather than by
the science: the array path exists because a 14,516 × 512 radargram is a 59 MB
float array but roughly 5 GB of pydantic objects.

## 10. What comes next

The measured result points somewhere specific. The estimator's contrast
definition is the candidate for replacement, not its threshold:

- candidates almost never span three traces (§5), so the rule is not responding
  to laterally extended structure at all;
- the 4TU corpus cannot resolve the question — seven negatives give an interval
  0.44 wide. **A benchmark with more attested-empty units is a prerequisite for
  evaluating any replacement**, and without one a better detector could not be
  recognised as better.

Those are the two dependencies. Neither is a candidate-layer problem, which is
why this stage stopped where it did.
