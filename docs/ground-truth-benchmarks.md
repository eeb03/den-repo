# Ground-truth benchmarks

What Subterra's benchmarks actually know, how independent that knowledge is, and
whether it is enough to tell a better detector from a lucky one.

Stage 13 asked *can Subterra find useful candidate regions?* This asks the prior
question: **would we know if the answer improved?** On present evidence, mostly
no — and this document says exactly how much more is needed.

## 1. The headline

| | |
|---|---|
| Independent positives | **107** |
| Independent negatives | **6** |
| Smallest improvement distinguishable from chance | **AUC 0.742** |
| Negatives needed for a clearly useful detector (AUC 0.70) | **12** |
| Negatives needed for a modest one (AUC 0.60) | **161** |

**The 4TU benchmark is underpowered for comparing detectors.** A genuine but
moderate improvement would not be recognisable, which means an unchanged score
is *not* evidence that a method failed. That is the fact Stage 14 exists to
establish, and it now travels with every candidate list the product renders.

It is not hopeless. Six further attested-empty trenches would make a clearly
useful detector recognisable. Detecting a marginal improvement would take ~155
more, which is a different order of undertaking.

## 2. Vocabulary

Five labels, extending what each benchmark already modelled rather than
replacing it (`benchmark/ground_truth.py`):

| Label | Meaning |
|---|---|
| `POSITIVE` | a target was independently established to be present |
| `NEGATIVE` | an absence was independently established — somebody looked and found nothing |
| `UNKNOWN` | insufficient evidence either way |
| `AMBIGUOUS` | evidence exists but cannot support a binary label |
| `EXCLUDED` | unsuitable for evaluation, for a stated reason |

Only `POSITIVE` and `NEGATIVE` carry evaluative weight (`EVALUABLE_LABELS`).

**`UNKNOWN` is not `NEGATIVE`.** The 4TU corpus has six activities whose
utility count is blank. A blank field is the absence of an observation, not the
observation of an absence, and folding the two together is the cheapest possible
way to make this benchmark look adequate.

The protection is the **evidence**, not the label. A unit whose label is edited
to `NEGATIVE` while its basis stays `not_recorded` still fails
`contributes_independent_evidence`, because `EvidenceBasis.NOT_RECORDED` is not
an observation. Relabelling by hand does not dig a trench.

## 3. Evidence model

Every label answers who established it, from what, over what ground, and what
remains unresolved — in dimensions, not in a score:

```
label      NEGATIVE
basis      trench_excavation
source     4TU Metadata.csv, field 'Amount of utilities'
by         the corpus publisher (trial-trench excavation records)
coverage   the trial trench only — a small excavation inside a much larger
           surveyed area
independent_of_subterra   true
verified_by_subterra      false
uncertainty  the trench found nothing; ground outside the trench is unobserved
```

There is deliberately **no `confidence` field**. "confidence = 0.92" with no
calibration behind it looks like a measurement and is not one.

`verified_by_subterra` means *Subterra checked* — not that the source sounds
reliable. Every label currently held is `false`: Subterra has excavated nothing
and fabricated nothing.

## 4. No detector may create ground truth

`benchmark/ground_truth.py` imports nothing from `interpretation`,
`preprocessing`, `training`, `models`, `benchmark.detection` or `api`, and
`tests/test_ground_truth.py` enforces that by parsing the module's imports. The
module is structurally unable to ask a detector anything.

"The detector found nothing here" becoming "this place is empty" is the single
most damaging thing a benchmark can do, so the prevention is architectural
rather than a matter of care.

## 5. The evaluation unit

| Corpus | Unit | Why not smaller |
|---|---|---|
| 4TU | **activity** (LocationID) | one activity holds many radargrams of one trench; the truth is stated once for the trench, so a per-radargram label is one observation counted a dozen times |
| BAM | **specimen** | Pk266's 161 lines are 161 passes over the *same* four ducts — one physical arrangement observed repeatedly |

Stage 13 already showed why this matters: 759 radargrams carry 721 unique
checksums. Files are not observations.

Survey lines remain the unit that *detection scoring* iterates over. They are
not units of independent ground-truth evidence, and the two must not be
conflated when a confidence interval is computed.

## 6. Duplicates and contamination

Reusing Stage 13's checksum infrastructure (`benchmark/leakage.py`), with two
rules:

- **Contaminated** — a unit sharing byte-identical measurements with a unit of
  the *opposite* label. Both are excluded from both populations. The same bytes
  cannot be evidence that something is present and that nothing is, and
  half-counting contradictory evidence is worse than admitting the corpus holds
  less.
- **Duplicate** — sharing with the *same* label. Counted once; the retained unit
  is chosen by sort order, arbitrary but not steerable by the data.

Measured on the real corpus:

| | |
|---|---|
| Units | 125 (112 positive, 7 negative, 6 unknown) |
| Independent | 119 |
| Duplicated | 4 (`010.12`, `010.16`, `013.2`, `02.4`) |
| **Contaminated** | **2 — `09.6` (positive) and `09.7` (negative)** |

Activity `09.7` was **one of only seven negatives**. Excluding it is correct and
costly: it drops the negative population to 6 and raises the smallest detectable
improvement from AUC 0.731 to 0.742. Both facts are reported.

No file is deleted and no corpus is modified. De-duplication happens in the
accounting.

## 7. Statistical power

`benchmark/power.py`, using the Hanley & McNeil (1982) variance approximation
for an AUC, two-sided at α = 0.05 and 80% power.

**Why AUC.** The 4TU truth is a per-activity count with no coordinates, so no
candidate can be matched to a utility and precision has no meaningful
denominator (`benchmark.gates` blocks object-level scoring for this reason).
What the corpus supports is whether candidate *density* separates occupied from
empty ground — a rank comparison, whose statistic is the AUC.

**Verified, not assumed.** The analytic standard error is cross-checked against
a 4,000-draw bootstrap on a corpus of the same shape drawn from one
distribution, where the true AUC is 0.5 by construction:

| | |
|---|---|
| Bootstrap 95% interval half-width | 0.2399 |
| Analytic 1.96 × SE | 0.2384 |

Agreement within 0.6%. The recommendation to collect more data does not rest on
an untested approximation.

**A variance floor.** With fewer than two units in a group the formula is
degenerate, not merely imprecise: both conditional-variance terms are multiplied
by (n − 1), so a group of one contributes no variance. Applied naively to BAM's
two specimens it claimed AUC 0.97 was distinguishable from chance. The module
now refuses to estimate below two per group and returns `None`, which the UI
renders as "no estimate is possible" and never as zero.

## 8. Benchmark versioning

A version is a **hash of the truth**: labels, evidence bases, sources,
duplicate statuses, independence and the four policies. Change any of them and
the version changes on its own.

```
4tu-nl-utility     1.a5669dcdc9d8e9d2
bam-concrete-gpr   1.c305a93f0e290376
```

It deliberately excludes **anything about a detector**. Thresholds and
parameters belong to the thing being measured, not the instrument; a benchmark
whose identity changed with the detector could not be used to compare detectors,
which is its only purpose. Reordering the inventory does not change the version;
relabelling one unit does.

## 9. Readiness

Reusing the platform's existing READY / PARTIAL / BLOCKED vocabulary. There is
no benchmark score, because fitness is per-question: this corpus is fine for
asking whether candidates appear at all and unfit for asking whether one
detector beats another.

| Dimension | 4TU | BAM |
|---|---|---|
| positive evidence | ready | ready |
| negative evidence | partial | partial |
| duplicate audit | ready | ready |
| independent units | partial | ready |
| localisation truth | blocked | partial |
| depth truth | blocked | blocked |
| detection evaluation | partial | partial |
| **detector comparison** | **partial** | **blocked** |

BAM is `blocked` for detector comparison because two specimens cannot support a
variance estimate at all — its value is per-(target, line) detection counting on
controlled material, not choosing between methods.

Every non-ready dimension names what is missing.

## 10. The evaluation protocol

There is no trained model, so no conventional ML split is invented. What is
fixed is the order of operations:

1. **Development** — synthetic data and BAM's controlled specimen, where a
   mechanism can be examined. Synthetic data is labelled synthetic and never
   enters real-world metrics.
2. **Calibration** — a held-out arm chosen before scoring. Stage 13's trace-span
   experiment used the Rot90 rotation for exactly this.
3. **Locked test** — the 4TU activity population, scored once per method.

**The test set must not become a tuning environment.** Thresholds are not part
of the benchmark definition and are never chosen against it: a detector arrives
with its parameters already fixed. Where several variants are evaluated, the
existing Benjamini-Hochberg machinery in `validation/null_models.py` controls
the false-discovery rate; repeated unrecorded probing of the test set is the
failure mode this rule exists to prevent, and no amount of correction repairs
it after the fact.

## 11. What is blocked on external evidence

Recorded in `benchmark.gates` and surfaced in the definition artifact. **No
request has been sent** — the repository holds no correspondence with any
dataset author, and every entry is marked `OUTSTANDING -- no request recorded in
this repository`. Claiming otherwise would invent a fact about the outside
world; inventing a reply would be worse.

| Question | Blocks | Would be resolved by |
|---|---|---|
| `attested-zero-population-is-small` | a false-alarm rate on real ground | **more zero-utility trenches, or another real-world corpus** |
| `trench-coordinates` | per-object precision/recall, IoU, positional F1 | author contact (University of Twente); a confidentiality decision |
| `trench-is-a-subset-of-the-survey` | calling an unmatched response a false positive | trench extents, not published |
| `absolute-origin` | localisation in physical coordinates | BAM appendix drawings, or author contact |
| `depth-reference-surface` | absolute depth accuracy | BAM Table 4 reference surface |
| `coordinate-units` | any metric in physical units | a units declaration from the publisher |
| `dzt-to-grid-mapping` | scoring against the native DZT stream | an acquisition-order statement |

The first is Stage 14's binding constraint.

## 12. What would actually fix this

Six further **independently attested-empty** surveys — different activities,
locations and acquisition conditions — would make a clearly useful detector
(AUC 0.70) recognisable. They must be real: duplicating one negative radargram
to raise the count would inflate the number and change nothing about the
evidence, which is why the duplicate audit runs before the counts are taken.

Sources that would qualify:

- more zero-utility trial trenches from the 4TU publisher
- another published corpus with attested-empty ground
- a survey over ground independently established to be clear

Synthetic negatives do **not** qualify and must never enter real-world metrics.

## 13. Where it lives

| Concern | Module |
|---|---|
| Vocabulary, evidence, evaluation units | `benchmark/ground_truth.py` |
| Statistical power | `benchmark/power.py` |
| Versioned definition and readiness | `benchmark/definition.py` |
| Duplicate detection (Stage 13) | `benchmark/leakage.py` |
| Corpus truth (unchanged) | `benchmark/fourtu_truth.py`, `benchmark/bam_truth.py` |
| Evidence gates and open questions | `benchmark/gates.py` |
| Build the definition | `scripts/build_benchmark_definition.py` |
| UI | `frontend/components/benchmark/ground-truth-panel.tsx` |

Regenerate with:

```
python scripts/build_benchmark_definition.py --out artifacts/benchmark/definition.json
```

`artifacts/` is gitignored and regenerable; tests that read the definition skip
when it is absent.
