# Validation protocol v1: sample-size audit, tolerance review and integrity checks (readiness R1(c))

**Status: DRAFT. Not frozen.**
- Protocol file: `benchmark/protocols/validation-protocol-v1.draft.json`.
- Code: `benchmark/validation_protocol.py`. Tests: `tests/test_validation_protocol.py`.
- No data have been received or evaluated. Every revision below was made **before** any new test data existed, as the approval required.
- **No detector, no simulation, no production detection change.**

The draft cannot be frozen yet, for two reasons:
1. No partner site is confirmed (R0).
2. `check_freezable()` refuses the draft until each test and holdout site's truth digest is sealed.

---

## 1. What the code enforces

| Check | Function | Refuses |
|---|---|---|
| Exact recall bound | `recall_lower_bound` | one-sided Clopper–Pearson |
| Exact false-alarm bound | `rate_upper_bound` | one-sided Poisson, per m² |
| **Gate feasibility at freeze** | `check_freezable(protocol, planned)` | any gate that **no outcome** on the planned test data could pass; fewer objects than `min_n`; too little verified-empty area; unsealed truth digests; two sites sharing a digest; freezing a non-draft |
| Frozen-file integrity | `git_blob_sha1`, `verify_committed_file` | a frozen file whose bytes are not the committed blob (the PR #13 pattern, now shared and needing no git) |
| Protocol identity | `protocol_digest` | content changes, while ignoring key order and whitespace |
| **One-shot testing** | `Ledger.open_site` | opening a test or holdout site under a draft, under a digest other than the committed one, a second time, or opening a development site through the ledger |
| Exposure labels | `exposure_label`, inside `evaluate` | anything not ledgered under the frozen digest is labelled **EXPLORATORY** or **DEVELOPMENT** and gets the verdict "NOT A VALIDATION RESULT", whatever its numbers |

`evaluate()` reads only matching **counts** (a plain dict). It has no dependency on the matching implementation (R1(b)) or the truth schema (R1(a)), and a test checks that it imports nothing from `benchmark`.

## 2. Sample-size audit, separately for linear and compact targets

**Units are objects** (brief §6.2). Lines crossing an object are repeated measures, so crossing more lines does not add sample size.

**Gate form:** the one-sided (1 − α) Clopper–Pearson lower bound on recall must be ≥ 0.6.

### 2.1 What the brief's §1.2 counts would allow

The brief planned 7 linear and 5 compact scored objects **per site**, with one test site.

| Group | n on the test site | Best possible outcome | One-sided 95% lower bound | Gate passable? | P(pass) if true recall = 0.9 |
|---|---|---|---|---|---|
| linear | 7 | 7/7 | 0.652 | only at 7/7 | **0.48** |
| compact | 5 | 5/5 | 0.549 | **no: infeasible** | **0** |

The brief's own numbers in §6.4 were two-sided 95% (0.735 at 12/12). On a per-site basis they were **infeasible for compact objects, and underpowered for linear ones.** This is the most important finding of the audit, and it is why REV-1 to REV-3 exist.

### 2.2 Power at the gate (one-sided α = 0.05, threshold 0.6)

Each cell is P(pass); k_min is the number of detections needed to pass.

| n | k_min | true recall 0.7 | 0.8 | 0.9 | 0.95 |
|---|---|---|---|---|---|
| 6 | 6 | 0.12 | 0.26 | 0.53 | 0.73 |
| 10 | 9 | 0.15 | 0.38 | 0.74 | 0.91 |
| 12 | 11 | 0.09 | 0.28 | 0.66 | 0.88 |
| **16** | **14** | 0.10 | 0.35 | **0.79** | 0.96 |
| 20 | 17 | 0.11 | 0.41 | 0.87 | 0.98 |
| 24 | 19 | 0.23 | 0.66 | 0.97 | 1.00 |
| 30 | 23 | 0.28 | 0.76 | 0.99 | 1.00 |

These come from `power_table()` and are reproducible. **The power is not monotone in n**, because k_min steps up discretely; this is a known property of exact binomial gates.

### 2.3 Linear and compact are not the same problem

| | Linear (pipes, cables, ducts) | Compact (stones, rubble, voids) |
|---|---|---|
| Unit | one object; detected if the covered axis fraction is ≥ `min_length_fraction` | one object; detected if one candidate lies within tolerance |
| Cost of adding units | high: trenching, a long target, an orientation mix | low: small pits |
| Expected difficulty | lower for metallic, higher for plastic | **higher**: BAM cuboids 1 and 2 were never detected under any arm (PR #17) |
| Main confound | parallel or crossing utilities that share a response | natural stones that are not in the truth list. **The rule that only verified-empty ground can produce false alarms is what protects against this** |

**Recommendation (REV-2):**
- `min_n = 16` per group **in the test data**. Pooling over pre-registered test sites is allowed, and each site is also reported separately.
- Compact objects are cheap, so **20 is preferred** for that group: P(pass) rises to 0.87 at a true recall of 0.9.
- **Consequence for the survey:** at least 32 scored test objects plus development objects. That is roughly **double the brief's §1.2 count.** The brief's minimal survey is therefore a **development** survey; a test needs either more objects per site or ≥ 2 test sites.

### 2.4 False alarms

| False alarms observed | Verified-empty area needed for a one-sided 95% upper bound ≤ 0.25 per m² |
|---|---|
| 0 | 12.0 m² |
| 1 | 19.0 m² |
| 2 | 25.2 m² |

**REV-3:** at least 20 m² in the test data. The brief's 12 m² would fail on a single false alarm.

### 2.5 Multiplicity

The verdict is the **intersection** of three one-sided gates (linear recall, compact recall, false alarms). An intersection–union test needs no α adjustment: each gate must pass at its own α. The verdict is conservative, not anti-conservative.

## 3. Positional tolerances against utility-investigation standards

**Sources.** I could not read the primary texts (BSI PAS 128:2022; ASCE/UESI 38-22) this pass. Everything below is from **secondary sources** and is recorded as uncertainty **U-1 / U-2**.

| Standard / level | Horizontal | Depth | Source (secondary) |
|---|---|---|---|
| PAS 128 QL-B1 (multiple methods, position and depth) | ±150 mm | ±15% of depth | Surveybase FAQ; Castle Surveys |
| PAS 128 QL-B2 (single method, position and depth) | ±250 mm | ±40% of depth | Surveybase FAQ; Castle Surveys |
| PAS 128 QL-B3 (single method, position only) | ±500 mm | not determined | Surveybase FAQ; Select Surveys |
| ASCE 38-22 QL-B | 0.2 ft (≈ 60 mm). Reported as the accuracy with which the **interpreted position is tied to the project survey datum**; QL-B is generally a horizontal-only determination | ambiguous (0.1 ft is attributed to QL-A by most sources) | TxDOT 2023 slides; McKissock guide; Bess Utility Solutions |

**Review of the brief's proposal**, max(0.15 m, 0.15 × depth) horizontal and max(0.10 m, 0.15 × depth) depth:

1. **Horizontal (REV-4).**
   - As reported, PAS 128 QL-B1 has **no depth-proportional horizontal term**; the 15% belongs to depth. The brief merged the two.
   - **Revised:** a fixed 0.15 m (the QL-B1 reading). QL-B2 (0.25 m) and QL-B3 (0.50 m) are **reported tiers**, not gates.
2. **Depth.**
   - **Revised:** 15% of depth (QL-B1 reading), with 40% (QL-B2) reported. The 0.10 m floor is removed, because neither standard was reported to have one.
   - **Depth never gates detection** (brief §6.3).
3. **ASCE 38 QL-B is not used as a gate.**
   - Its 60 mm figure, as reported, is a survey-tie accuracy for a mark, not an allowance for detector position error.
   - Using it would conflate the two, and would be far stricter than any GPR detection standard reported here.
4. **Compact objects (U-3).**
   - Neither standard covers stones, rubble or voids.
   - The draft uses 0.15 m **plus half the object's largest dimension**, because the truth point is the object's centre. This is a **project choice** and is stated as one.
5. **The truth uncertainty is small by comparison.** It is ≤ 0.02 m (brief §1.4): about 13% of the 0.15 m tolerance. It is not added to the tolerance; it is reported.

**Before freezing:** read the PAS 128:2022 primary text (U-1). If it has to be bought, that needs separate approval under the zero-budget rule.

## 4. Recorded revisions and uncertainties (copied in the protocol file)

**Revisions:**
- **REV-1:** recall bounds are one-sided at α = 0.05.
- **REV-2:** `min_n` = 16 per group in the test data; 20 preferred for compact objects.
- **REV-3:** at least 20 m² of verified-empty area.
- **REV-4:** horizontal tolerance fixed at 0.15 m; depth 15%, reported only.

**Uncertainties:**
- **U-1:** the PAS 128 primary text has not been read.
- **U-2:** ASCE 38 QL-B semantics.
- **U-3:** the compact-object tolerance is a project choice.
- **U-4:** gate power. At n = 16, a detector with a true recall of 0.8 passes only 35% of the time. The gate certifies "≥ 0.6 with confidence"; it does not estimate recall.
- **U-5:** the coverage radius (0.05 m, half of the 0.10 m line spacing) and `min_length_fraction` (0.5) must be fixed from the acquisition actually performed.
- **U-6:** site ids are placeholders.

## 5. Decisions needed before freezing

1. Accept REV-1 to REV-4, or amend them. **That includes accepting that a test needs about twice the brief's object count.**
2. Approve reading, or if necessary obtaining, the PAS 128:2022 primary text.
3. Bind real site ids and seal truth digests when a partner site exists. Then `check_freezable()` must return no reasons, and the freeze is committed with its digest.
