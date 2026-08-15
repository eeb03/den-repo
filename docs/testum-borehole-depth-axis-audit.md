# TestUM borehole depth-axis audit

## Correction to Stage 28 — the calibration data IS published

**Stage 28 concluded "the air-WARR calibration measurements are not in the
dataset". That was wrong, and it was a search failure of mine.** I grepped
filenames for `calib|warr|air|zero|test|separat`. The files are named **`t0`** —
which none of those patterns match — and the data matrix files them under
configuration `crosshole`, so they did not stand out in my configuration count
either.

**26 calibration files are published**, across **13 survey days**:

| | |
|---|---|
| Naming | `<date>_GEWS_t0_start.DZT` / `_mid` / `_end` |
| Slots | 12 start, 1 mid, 13 end — the end-of-day repetition the design doc describes |
| Protocol A (22 files) | `t0-measurement / x_receiver_start=1m, x_receiver_end=3m, dx=0.2m` |
| Protocol B (4 files) | `t0-measurement / x_receiver_start=1.5m, x_receiver_end=3m, dx=0.1m` |
| Trace counts | **11** and **16** |

Arithmetic check: 1.0→3.0 m at 0.2 m = **11**; 1.5→3.0 m at 0.1 m = **16**.
Both match the published trace counts exactly. One file was downloaded
(`20230824_GEWS_t0_start.DZT`, 176,128 bytes) and the **existing converter
returns 11 traces × 1024 samples over 150 ns**, unmodified.

**The separations are stated in the metadata, and each trace is one separation.**
This is the independent d≈0 anchor Stages 24–25 said was missing. It is not
derived here — see *Roadmap impact*.

---

## The stage's actual question: what positions a trace?

### The relationship, verified across the whole corpus

For every row carrying the fields, the data matrix satisfies

```
n_traces = (deepest point − uppermost point) / increment + 1
```

**265 rows agree. 0 disagree.** Increment is `0.25` on all 265. So **one trace is
one borehole depth station at 0.25 m spacing** — DATA-MEASURED, verified across
293 published files rather than asserted from one.

The 28 non-conforming rows are not exceptions to this: 26 are the `t0`
calibration files (whose axis is *antenna separation*, not depth) and 2 are
short partial logs.

### 1. What `rhf_spm` represents

`rhf_spm` is the GSSI header's **scans-per-metre** setting — an acquisition
parameter for *surface* wheel-triggered surveys. Measured values here: **20.0**
(reflection, → 0.05 m) and **60.0** (crosshole, → 0.0167 m).

Neither equals 0.25 m, and neither is consistent with the other, while the
*documented and corpus-verified* increment is 0.25 m for both. **`rhf_spm` does
not describe TestUM's trace positioning.** It is an operator setting carried
through from a surface-survey workflow.

This is *not* inferred from magnitude alone: it is established by the 265/265
agreement of an independent relationship that `rhf_spm` plays no part in.

### 2. What `rhf_position` represents — **UNRESOLVED**

`rhf_position` measures **−15.0 ns** in both files. The data matrix's separate
`Radar time delay` column reads **16.3 ns** on reflection rows and is **blank on
crosshole rows** — including blank on every `t0` row.

They are different numbers from different places, one negative and one positive.
**Neither is adopted as t0**, and the meaning of both remains **UNRESOLVED**. The
sign alone should discourage a casual reading.

### 3. What the 0.25 m increment refers to

**Borehole depth sampling.** Author-stated (*"measurements were taken every 0.25
meters starting at a maximum of 16.75 m up to 0.25 m depth"*) and confirmed by
the 265/265 corpus check. For crosshole it is the depth of **both** antennas,
lowered simultaneously to the same depth (zero-offset profiling).

### 4. How traces are physically positioned

| Acquisition | Trace axis | Lateral position | Source |
|---|---|---|---|
| Reflection | borehole depth, 0.25 m steps, deep→shallow | the single borehole's collar (DGPS) + deviation | author + corpus |
| Crosshole | *shared* depth of both antennas, 0.25 m | the Tx and Rx borehole collars; ray path ≈ their separation | author + corpus |
| **`t0` calibration** | **antenna separation, 0.2 or 0.1 m steps** | both antennas on the ground | metadata comment |

Three different meanings for "trace index" in one dataset — and the third is not
a depth at all.

### 5. Can `OdometryPosition` represent this? **No.**

`OdometryPosition(along_track_m, path_id)` models distance travelled along a
surface line. A borehole log needs at minimum a **depth below collar**, a
**borehole identity**, and — for crosshole — a **second borehole** and the
**separation**. Deviation makes the depth-to-3D mapping non-vertical, which
`along_track_m` cannot express either.

Forcing depth into `along_track_m` would also be *silently* wrong: the number is
plausible and monotonic, so nothing downstream would object.

### 6. Converter status: **technically correct, semantically incomplete**

| Layer | Verdict |
|---|---|
| Binary parsing | **correct** — 67 traces × 1024 samples, matching the publication |
| Numerical decoding | **correct** — samples bit-identical (Stage 28) |
| Time axis | **correct** — 0.146484375 ns, 150 ns window |
| Coordinate interpretation | **wrong for this modality** — depth read as surface odometry |
| Physical meaning | **not modelled** |

The converter faithfully reports `rhf_spm`; the header is what misleads. **This
is not a DZT bug.**

### 7. Validation fixture potential — **yes**

The corpus supplies an independently checkable oracle: depth(trace) =
`deepest − 0.25 × index`, with `deepest`, `uppermost`, increment and trace count
all published per file, and the relationship verified 265/265. A borehole-aware
implementation could be tested against it without inventing anything.

**No test was written in this stage**, because with no production change a test
could only assert a fact about the dataset or restate current behaviour — both
of which the brief excludes.

### 8. Does this affect 4TU? **No.**

It does not touch 4TU time-zero, velocity, physical depth or absolute subsurface
elevation. 4TU is surface air-launched; it has no borehole axis. What this work
does is **prevent a category of silent misinterpretation** and establish
validation infrastructure for any future borehole dataset.

### 9. Broader architecture

The assumption "a GPR trace position is a surface along-track distance" is
structural, not local: `OdometryPosition` is the only non-geographic,
non-projected position type available, so **every** converter with a
distance-like quantity funnels into it. `gssi_converter`, `mala_converter` and
`ids_dt_converter` all do this. **Identified, not changed.**

---

## Evidence table

| Quantity | Meaning | Evidence | Confidence | Current Subterra representation | Correct? |
|---|---|---|---|---|---|
| Trace index (borehole logs) | depth station, 0.25 m | 265/265 corpus check + author | **INDEPENDENTLY-VERIFIED** | `OdometryPosition.along_track_m` from `rhf_spm` | **No** |
| `rhf_spm` (20 / 60) | surface scans-per-metre operator setting | DATA-MEASURED; contradicts verified 0.25 m | **DATA-MEASURED** | used as trace spacing | **No** |
| 0.25 m increment | borehole depth sampling | AUTHOR-STATED + corpus | **INDEPENDENTLY-VERIFIED** | absent | **No** |
| `rhf_position` = −15.0 ns | unknown | DATA-MEASURED | **UNRESOLVED** | recorded, not applied | correct to withhold |
| `Radar time delay` = 16.3 ns | unknown; blank on crosshole/t0 | AUTHOR-STATED | **UNRESOLVED** | not used | correct to withhold |
| `t0` files, 26 across 13 days | air-path calibration at stated separations | DATA-MEASURED + AUTHOR-STATED | **INDEPENDENTLY-VERIFIED** *(exists)* | none | n/a — not yet used |
| Trace index (`t0` files) | **antenna separation**, not depth | metadata comment + trace count | **INDEPENDENTLY-VERIFIED** | `OdometryPosition` | **No** |
| Sample values | raw amplitudes | bit-identical (Stage 28) | **INDEPENDENTLY-VERIFIED** | preserved | **Yes** |

## Roadmap impact

| Roadmap blocker | Before | After | Evidence |
|---|---|---|---|
| 4TU time-zero | BLOCKED | **BLOCKED** | nothing here concerns 4TU |
| 4TU propagation velocity | BLOCKED | **BLOCKED** | unchanged |
| 4TU physical depth | BLOCKED | **BLOCKED** | unchanged |
| 4TU absolute subsurface elevation | BLOCKED | **BLOCKED** | unchanged |
| TestUM t0 derivable? | believed impossible (Stage 28) | **possible — data located** | 26 `t0` files, verified readable |
| Borehole depth semantics | unknown | **established** | 265/265 |
| Borehole modality in Subterra | unrecognised | **identified, unmodelled** | this audit |

**A. Unblocks:** the meaning of TestUM's trace axis, and — via the Stage 28
correction — the existence of the independent calibration observations.

**B. Does not unblock:** any 4TU blocker; no t0 or velocity is derived here.

**C. Stages 8–12:** no change.

**D. 4TU blockers:** all four remain BLOCKED.

**E. TestUM as a calibration dataset:** **materially improved.** It was
"documented method, no observations"; it is now "documented method **with** 26
published calibration measurements across 13 days".

**F. New modality/schema stage required:** **Yes** — see below.

**G. Highest-value next action:** **derive the independent t0 from the 26 `t0`
files.** That is the measurement four stages have been looking for, it is in
hand, and it needs no schema change: the calibration axis is antenna separation
in air, so it can be analysed as an isolated experiment exactly as Stage 24 was.

## Verdict

**A — directly usable / unblocked**, for the question this stage asked. The
borehole depth semantics are established by independent verification, not
inference.

## Proposed production change — **STOPPING BEFORE IT, as instructed**

The brief's five conditions are **not all met**, so nothing was changed:

| Condition | Met? |
|---|---|
| 1. Meaning established by authoritative evidence | ✅ 265/265 + author |
| 2. Implementation demonstrably violates it | ✅ 0.05/0.0167 m vs 0.25 m |
| 3. Correct representation clear | ❌ **no borehole position type exists**; adding one is a schema change |
| 4. Isolatable without affecting unrelated GPR | ❌ `rhf_spm` handling is shared with TU1208, BAM and hillside GSSI files |
| 5. Regression tests protect the change | ⚠️ partial |

**Conditions 3 and 4 fail, so this is deferred to its own stage.** The eventual
change would need a borehole-aware position concept carrying depth below collar,
borehole identity, and (for crosshole) the second borehole and separation — plus
a way for a converter to know it is reading a borehole log at all, which the DZT
header does not say. That is a schema stage, not a converter patch.

## Limitations

- Two borehole files and one calibration file inspected, not all 293.
- `rhf_position` and the 16.3 ns column remain **UNRESOLVED**.
- No t0 or velocity derived — deliberately out of scope.
- Deviation data downloaded but not used; depth→3D mapping is non-vertical and
  unquantified here.
