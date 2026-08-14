# TestUM Raw Data Validation

## Correction to Stage 27 first

**Stage 27 said the raw traces "require a free PANGAEA account". That was
wrong.** The HTTP 503 body is not an auth wall — it reads:

> *"The requested file 20221121_GEWS_C05.DZT is **loading from tape**… Download
> will start automatically after a minute in the background."*

PANGAEA stages large files from tape archive. "Not logged in" and "Account" were
navigation elements on the error page, and I read them as an access requirement
without checking the body text. **No registration was needed.** Retrying after
staging returned the files on the first or second attempt.

## Dataset

PANGAEA **[10.1594/PANGAEA.971978](https://doi.org/10.1594/PANGAEA.971978)**,
Jung, Pohle & Werban (2024), CC-BY-4.0. TestUM site, Wittstock/Dosse, Germany.

## PANGAEA access

No account, no credentials, no tokens. Single-file URLs of the form
`https://download.pangaea.de/dataset/971978/files/<filename>`; retry on 503 while
the file stages.

## Files obtained (downloaded 2026-08-14)

| File | Bytes | Raw/processed | SHA-256 (first 16) |
|---|---|---|---|
| `20221121_GEWS_C05.DZT` | 405,504 | **raw** (native GSSI) | `9b9ef0b8b44b7e47` |
| `20230221_GEWS_C07_C10.DZT` | 405,504 | **raw** (native GSSI) | `a0d8d741fe2c0cc9` |
| `GEWS_Deviation_and_GPS.zip` | 188,791 | surveyed geometry, 25 files | `ebe9935affaa6218` |
| `ExperimentDesign_…2022-2023.pdf` | 1,091,609 | documentation | `9a747b16ad660403` |
| `PANGAEA_971978_metadata.txt` | 38,401 | data matrix | `849f1d2db78bd834` |

Full checksums in `CHECKSUMS.sha256` beside the files.

## Repository location

Stored under **`datasets/raw/pangaea/971978/`**, following the existing
`datasets/raw/<source>/<id>/` convention (cf. `datasets/raw/zenodo/1211173/`).
**`datasets/` is gitignored**, so no binary is committed — consistent with how
every other external dataset is held. Reproduce by re-downloading from the URLs
above; nothing here depends on the binaries being in version control.

## DZT format (MEASURED from the files)

| Field | C05 (reflection) | C07_C10 (crosshole) | PANGAEA says |
|---|---|---|---|
| `rh_nsamp` | 1024 | 1024 | 1024 ✅ |
| `rh_bits` | 32 signed | 32 signed | — |
| `rhf_range` | 150.0 ns | 150.0 ns | 150 ns ✅ |
| sample duration | 0.146484375 ns | 0.146484375 ns | 0.146484375 ✅ |
| `rhf_position` | **−15.0 ns** | **−15.0 ns** | *(table says 16.3)* |
| `rhf_epsr` | 5.236 | 12.169 | — |
| `rhf_spm` | 20.0 → 0.05 m | 60.0 → 0.0167 m | **0.25 m** ❌ |
| antenna code | `3207` | `3207` | Tubewave-100 |
| header block | 131,072 bytes (`rh_data` 128 × 1024) | same | — |

**Three findings worth stating separately.**

1. **`rhf_position = −15.0 ns` is not the 16.3 ns** in the PANGAEA `Radar time
   delay` column. Two different numbers from two different places. **Neither is
   adopted as t0**, and this reinforces the Stage 27 caution: the meaning of the
   16.3 ns column remains unestablished.
2. **`rhf_spm` contradicts the documentation.** The header implies 0.05 m and
   0.0167 m increments; the publication states measurements every **0.25 m**.
   This is not a converter defect — the converter faithfully reports the header.
   It is an operator setting that does not describe the borehole increment.
3. **`rhf_epsr` differs per file** (5.236 vs 12.169), which is exactly why the
   converter refuses to treat it as a velocity.

## Existing converter compatibility

`converters/gssi_converter.py`, **unmodified**. `can_convert` → `True` for both.

## Conversion results

| Check | Result |
|---|---|
| Traces | **67** — matches the PANGAEA data matrix exactly for both files |
| Samples per trace | **1024** ✅ |
| Records | **68,608** = 67 × 1024 ✅ |
| Time axis | `two_way_time_ns`, n=1024, **0.146484375 ns** — matches published `Sample dur` to the digit |
| Window | 1024 × 0.146484375 = **150.0 ns** = `rhf_range` ✅ |
| Axis origin | `"instrument time-zero at each trace"` |
| `origin_offset` | **None** — no t0 invented |
| `conversion` | **None** — no velocity invented |
| `depth` | **all None** — no synthetic depth |

**Sample values are bit-identical.** Comparing raw `int32` at the derived data
offset (131,072) against the converted records for trace 0:

```
raw int32 : [0, 0, -56310, -55878, -55242, -54836, -54579, -54373, -54195, -53993]
converted : [0, 0, -56310, -55878, -55242, -54836, -54579, -54373, -54195, -53993]
```

Identical from sample 2 onward, and the first two samples are **genuinely 0 in
the file** — not zeroed by the converter, though it does carry a
`leading_samples_may_be_markers=2` assumption that would have.

Recorded assumptions, all honest:

```
[time_axis] = 0.146484375                    verified=True
[time_zero_offset_not_applied] = -15.0       verified=False   <- recorded, NOT applied
[sample_centring] = '32-bit, signed, unshifted'
[epsr_not_used_for_velocity] = 5.236         verified=True
[depth_conversion] = 'not applied'           verified=True
```

## A modality gap, reported not fixed

The converter assigns **`OdometryPosition`** from `rhf_spm`, treating the survey
as surface along-track. For **borehole-deployed** GPR the third axis is **depth
down a well**, not distance across the ground — and the values disagree with the
documented 0.25 m increment anyway (finding 2 above).

So Subterra *parses* these files correctly but *interprets their geometry* as
something they are not. **This is not a DZT bug and no converter change is
proposed here.** It is a modality the platform does not model. Per the stage's
instruction, it is reported for a separate scoped decision.

## Air-WARR calibration evidence — **the calibration traces are not published**

Searched the data matrix and the downloaded archive. The dataset contains
**123 crosshole + 170 reflection** files and **nothing else** — no calibration,
air-WARR, zero-time, test or separation files, under any naming.

| | |
|---|---|
| Procedure | **documented** in the experiment-design PDF (AUTHOR-STATED) |
| Observations | **not in the dataset** |
| Separations 1–3 m at 0.2 m | described, not recorded |
| Picked arrival times | **absent** |
| Per-day / temperature record | described, not recorded |

## Independent t0 analysis — **not performed, because the inputs do not exist**

Stage 27 established that TestUM's method *would* be independent:
`t0 = t_measured − X/c_air`, with X surveyed and air's velocity a physical
constant, so the result cannot depend on subsurface velocity.

**All four independence conditions hold for the method.** But `t_measured` for
the air path is not published, so **no numerical t0 was derived**. Deriving one
from the borehole traces would mean fitting subsurface reflectors, which is the
circularity this whole line of work exists to avoid.

**No t0 value is adopted. CALCULATION NOT POSSIBLE with published data.**

## Velocity analysis — **not performed**

`v = L/(t − t₀)` needs t₀. Without it, any velocity from these traces would be
jointly fitted, which Stage 24 already showed is not identifiable. The surveyed
separations (1.12–6.10 m, 18 pairs) are in hand and remain usable the moment a t0
exists.

**No velocity value is adopted.**

## 4TU transferability — the method, stated concretely

Nothing numerical transfers: borehole antennas in fluid versus a 500 MHz
air-launched array, and no air gap versus the air gap that *is* 4TU's unknown.

What this stage adds is that the missing measurement can now be specified
exactly. For 4TU to obtain an independent t0, someone with the original
instrument would need to record:

1. both antennas on the ground, **surveyed separation X** (TestUM used 1→3 m in
   0.2 m steps, taking X=3 m to avoid near-field);
2. the **picked first-arrival time** at that separation;
3. then `t0 = t_measured − X/c_air`;
4. repeated **at the end of the survey day**, so antenna and cable temperature
   match the survey.

That is a field procedure requiring the instrument. **It cannot be recovered from
the published 4TU SEG-Y**, and this stage does not claim otherwise.

## Limitations

- Air-WARR observations absent; no t0, therefore no velocity.
- Two files audited, not the full 293.
- Borehole depth axis not modelled by the platform.
- The 16.3 ns column and the −15.0 ns header field remain unexplained, and are
  **different numbers**.
- Raw-vs-processed: the files are native GSSI with an intact 150 ns time axis,
  consistent with raw; no processing history is embedded to confirm it.

## Roadmap impact

**TestUM's classification is unchanged: B — provides a valid calibration
method.** Obtaining the traces confirmed Subterra can read them and preserved
everything, which is a real result about *Subterra*. It did not produce a
calibration, because the calibration observations were never published.

| Stage | Impact |
|---|---|
| 8 — coordinate/geospatial | **no change** |
| 9 — vertical reference | **no change** |
| 10 — depth-axis origin | **no change** — no t0 obtained |
| 11 — velocity/depth conversion | **no change** — no velocity obtained |
| 12 — physical 3D registration | **no change** |

4TU remains **BLOCKED** on time-zero, velocity, physical depth and absolute
subsurface elevation.

## Evidence classification

| Claim | Class |
|---|---|
| 67 traces, 1024 samples, 150 ns, 0.146484375 ns | **MEASURED FROM RAW DATA** |
| Sample values bit-identical through conversion | **MEASURED FROM RAW DATA** |
| `rhf_position` = −15.0 ns | **MEASURED**, meaning unestablished |
| `Radar time delay` = 16.3 ns | **AUTHOR-STATED**, meaning unestablished |
| Air-WARR procedure | **AUTHOR-STATED** |
| t0 independence of subsurface velocity | **INFERRED** from the documented procedure |
| Numerical t0 / velocity | **NOT OBTAINED** |
| `rhf_spm` vs 0.25 m increment | **MEASURED** discrepancy |
