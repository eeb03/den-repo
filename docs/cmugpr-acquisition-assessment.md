# CMU-GPR acquisition assessment

Investigation date 2026-08-07. **Nothing was downloaded.** Every fact below
comes from the authoritative sources named in §1; where a fact is absent from
those sources this document says so rather than supplying a plausible value.

## Classification: **C — useful validation corpus, not coordinate-scored ground truth**

CMU-GPR contains **no buried-target ground truth of any kind**. It is a robot
*localization* dataset: the ground truth is the **robot's own pose**, not the
position of anything underground. There is no annotation of what lies beneath
any trace, no target inventory, and no excavation record. It therefore cannot
be promoted to A or B — no amount of manual preparation creates target truth
that was never collected.

It is not D either. It supplies one thing the current corpus genuinely lacks:
**repeated observation of the same ground by the same instrument, with an
independent metric measurement of where each observation was taken.**

## 1. Identity and authoritative sources

| | |
|---|---|
| **Exact name** | CMU-GPR Dataset |
| **Repository** | https://github.com/rpl-cmu/CMU-GPR-Dataset (Robot Perception Lab, Carnegie Mellon University) |
| **Publication** | Baikovitz, Sodhi, Dille, Kaess, *CMU-GPR Dataset: Ground Penetrating Radar Dataset for Robot Localization and Mapping*, arXiv:[2107.07606](https://arxiv.org/abs/2107.07606), 2021 |
| **Companion method paper** | Baikovitz et al., *Ground Encoding: Learned Factor Graph-based Models for Localizing Ground Penetrating Radar*, arXiv:[2103.15317](https://arxiv.org/abs/2103.15317), IROS 2021 |
| **Institution** | Carnegie Mellon University, Robotics Institute |
| **License** | **CC-BY-NC-SA 4.0**, "intended for non-commercial academic use". Commercial enquiries are directed to `data@mach9.io` |
| **Access** | Open, no registration. Per-sequence ZIPs on **Google Drive**, linked from the README |
| **Persistent identifier** | **None for the data.** No DOI, no Zenodo/institutional archive. The only DOI-like identifiers are the two arXiv IDs, which cover the papers |
| **Publisher checksums** | **None published.** No MD5/SHA in the README, and Google Drive exposes none through the share link |

### On "Branco GPR"

**No dataset by that name was found.** Searches against the literature and the
open data repositories return nothing matching "Branco" as a GPR dataset,
author, or site. The nearest hits are unrelated: the Morocco utilities/voids
Mendeley set (Mojahid, El Ouai, El Amraoui, El-Hami, Aitbenamer — annotated
JPEG radargram *images*, no traces, no coordinates, CC-BY-NC), already surveyed
as item 11 of [`dataset-benchmark-plan.md`](dataset-benchmark-plan.md). The
repository contains no reference to "Branco" either. Treated here as CMU-GPR
only. If a specific dataset was meant, it needs a DOI or URL to be assessed.

## 2. Contents

Sensor rig ("SuperVision", manually pulled): Sensors & Software OEM **Noggin
500** single-channel GPR · XSENS MTi-30 IMU · YUMO 1024-PRR quadrature wheel
encoder · Intel RealSense D435 (RGB, 15 Hz) · **Leica TS15 robotic total
station** for ground truth.

### Files and formats

Per sequence directory: `gpr_meas.csv`, `we_odom.csv`, `imu_meas.csv`,
`ts_meas.csv`, and a `camera/` directory of PNGs. **CSV and PNG only — no
vendor-native format.** Column layout, from the repository's own data-format
figure (`misc/data_type.png`):

| file | columns | units |
|---|---|---|
| `gpr_meas.csv` | `t_stamp, amp_1 … amp_201` | **201 samples per trace**, amplitude → mV as `/32767 × 50` |
| `we_odom.csv` | `t_stamp, dist_x` | signed distance traversed, **m** |
| `imu_meas.csv` | `t_stamp, a_x a_y a_z, g_x g_y g_z, w x y z` | m/s², rad/s, magnetometer |
| `ts_meas.csv` | `t_stamp, p_x, p_y, p_z` | ground-truth position, **m** |

### Sequences and size

| group | count | locations | size |
|---|---|---|---|
| **A** — with total-station ground truth | 11 (A.0–A.10) | `gates_g` ×7, `nsh_b` ×4 | 89.2 – 1,193.0 MB, **6,960.4 MB total** |
| **B** — full unprocessed aggregates | 3 (B.0–B.2) | `gates_g`, `nsh_b`, `nsh_h` | 1,258.4 – 3,997.1 MB, **8,460.8 MB total** |
| **C** — odometry only, no ground truth | 3 (C.0–C.2) | `nrec` ×2, `smith` | 11 – 32.3 MB, **75.6 MB total** |

**≈15.5 GB in total**, with A largely contained in B. *This corrects
[`dataset-benchmark-plan.md`](dataset-benchmark-plan.md) §8 and
[`benchmark-acquisition-plan.md`](benchmark-acquisition-plan.md), which both
record "≈12 GB".*

Sequence filenames are Unix timestamps. Decoded: **every A and B sequence was
recorded on 2021-02-11 between 16:01 and 17:39 UTC** — a single 98-minute
session. C.0/C.1 are 2021-01-29, C.2 is 2021-02-01.

## 3. The required determinations

| question | answer | basis |
|---|---|---|
| Raw radar data downloadable? | **Yes**, openly | README links |
| File formats | CSV + PNG | data-format figure |
| Number of files/profiles | 11 ground-truthed sequences + 3 aggregates + 3 odometry-only | README tables |
| **Geographic coordinates exist?** | **No.** "3 GPS-denied, **indoor** environments" — a parking garage (`gates_g`), a basement (`nsh_b`), a factory floor (`nsh_h`) | paper §I, §III |
| **Any CRS?** | **None.** `ts_meas` is metres in an undeclared local total-station frame with no stated origin or orientation | data-format figure |
| **Buried targets known/emplaced?** | **No.** Nothing was emplaced; the subsurface is whatever is under a CMU building | paper |
| **Target coordinates exist?** | **No** | paper, README |
| **Machine-readable target locations?** | **No — none exist in any form** | — |
| **Trace-to-target mapping?** | **No** | — |
| **Depth information?** | **No.** 201 samples/trace, but **neither paper nor README states the time window, sampling interval, or an assumed velocity.** The vertical axis is sample index; it cannot be converted to time, let alone depth | both papers, README — verified absent |
| **Surface elevation?** | `p_z` from the total station, in metres, in the same undeclared local frame. **Not an elevation in any datum** | data-format figure |
| **Multiple surveys?** | **Yes, in one sense.** "Each sequence contains revisitation events, where subsurface features are observed more than once" — forward-backward motion and loop closures **within** a sequence. The README's *Correlated Sequences* column is **empty for every row**, so cross-sequence overlap is **not declared by the source**. All of it is one 98-minute session, so there is **no temporal separation** | README, paper |
| **Suitable for quantitative detection scoring?** | **No.** No target truth | — |
| **Suitable for object localisation scoring?** | **No.** No target truth, and no frame to localise into | — |
| **Suitable for repeat-survey tracking?** | **Partly — and this is its one real contribution.** Same instrument, same ground, observed more than once, with an *independent measurement* of where. But same-day only, so it validates re-observation mechanics, **not temporal change detection** | README, timestamps |
| **Adds a capability 4TU/TU1208 cannot?** | **Yes, one** — see §4 | — |

## 4. What it would and would not add

### Would add

1. **Repeat observation with independent positional truth.** The manifest
   records repeat-survey tracking as infrastructure with no dataset behind it,
   and the platform has been explicit that adjacent profiles are not repeat
   surveys. Within-sequence revisitation is **declared by the source**, and the
   total station makes "these two observations are at the same place" a
   **measured** statement rather than an assumed one. This is the only
   candidate found that offers it.
2. **`LocalCartesianPosition` where x/y/z are measured.** Hillside sits at
   `available` in the manifest only because constructing x/y still needs a
   caller-supplied line-spacing assumption. `ts_meas.csv` is a direct measured
   local cartesian position — the abstraction exercised on data rather than on
   a fixture.
3. **`OdometryPosition` at scale** from a second, independent source.
4. A fourth manufacturer's instrument (Sensors & Software) — **but only as
   exported CSV**, so it advances no native-format support.

### Would not add

- Any target truth, so it does not unblock detection or localisation scoring.
- Anything geographic: nothing from CMU-GPR can be placed on a map, so the map
  view, cross-CRS fusion, GeoJSON/CZML export and overlay composition all stay
  where they are.
- Any vertical datum. `p_z` is a local metric coordinate, not an elevation.
- Any depth axis at all, absent an externally supplied time window.

### It does **not** exercise `GeoTie`, contrary to the earlier survey

[`dataset-benchmark-plan.md`](dataset-benchmark-plan.md) §8 records "GeoTie
available — **effectively yes**". **That is wrong**, and this assessment
supersedes it. `ControlPoint` in `schemas/spatial.py` requires `lat` and `lon`:
a GeoTie is defined as the route from a frame with no Earth reference **to a
geographic one**. CMU-GPR is GPS-denied and indoors; there is no lat/lon
anywhere in it. Applying a GeoTie would mean inventing the control-point
coordinates — precisely what the abstraction exists to prevent. The manifest's
`geotie_along_track: gap` therefore **stays open**; CMU-GPR does not close it.

## 5. Costs and constraints

- **CC-BY-NC-SA 4.0 is a hard constraint, and the decision is yours.**
  Non-commercial restricts use; **ShareAlike** additionally propagates to
  adaptations. Derived artifacts — processed records, candidate sets, figures,
  published benchmark numbers — would carry that encumbrance. If Subterra has
  any commercial path, CMU-GPR must be quarantined from anything shipped or
  published commercially, or skipped.
- **No DOI, no archive, no publisher checksum.** Google Drive links can rot,
  and there is nothing to verify a download against beyond a hash we compute
  ourselves.
- **Weakest joint in the chain is that the total-station frame is undeclared.**
  No source states the frame's origin/orientation, its accuracy, or whether two
  sequences at one location share a setup. Within a single sequence the frame
  is necessarily self-consistent, which is why the plan below stays inside one.

---

# Acquisition plan (Phase C) — **conditional, not yet authorised**

Gated on one decision: **is CC-BY-NC-SA acceptable for this project?** If not,
stop here; nothing below should happen.

### What to download

Within-sequence revisitation is the only same-ground repetition the source
declares, so **one sequence is the unit of validation** and cross-sequence
pairing is out of scope (it would assume an undeclared shared frame).

| step | files | size | purpose |
|---|---|---|---|
| **minimum** | **A.6** `1613065150-0-gates_g-cmu-gpr.zip` | **89.2 MB** | smallest sequence carrying ground truth; proves the format end to end |
| **recommended** | A.6 + **A.1** `1613063708-0-gates_g-cmu-gpr.zip` | **469.4 MB** | a second, independent within-sequence test rather than one anecdote |

**Not** the B aggregates (8.5 GB, and A is contained in them). **Not** the C
sequences (no ground truth). **Not** the full 15.5 GB — this buys ~3% of the
archive for 100% of the capability identified.

### Storage, provenance, checksums

- Local path `datasets/raw/cmu_gpr/<sequence>/`, matching existing layout.
- **Raw data must not be committed to git** — NC licence and size. Add
  `datasets/raw/cmu_gpr/` to `.gitignore` alongside the existing raw exclusions.
- `PROVENANCE.json` beside each archive, as for every other dataset: source
  URL, both citations, licence **and its source**, retrieval timestamp and
  method, archive SHA-256, per-member CRC32. It must record explicitly that
  **the publisher provides no checksum**, so our hash attests our copy only,
  not the publisher's intent.
- `PROVENANCE.json` and the manifest entry **are** committable — they are facts
  about the dataset, not the dataset.

### Converter capability required

New `converters/cmugpr_converter.py`, reusing the existing abstractions:

- `gpr_meas.csv` → traces of 201 samples; amplitude → mV by the published
  constant, recorded as **declared_by_source**.
- `we_odom.csv` → `OdometryPosition(along_track_m=…)`, joined on timestamp.
- `ts_meas.csv` → `LocalCartesianPosition`, **measured**, with `SpatialRef`
  carrying `CRSProvenance.NONE`; the frame's origin and orientation are
  recorded as undeclared.
- **No depth axis.** The time window is unpublished, so `VerticalAxis` is
  sample index. A depth would require the caller to declare **both** a sampling
  interval and a velocity, and the sampling interval is not a property anyone
  has stated — the converter must refuse to default it, exactly as
  `validate_velocity` refuses a default velocity.
- No `GeoTie`, no geographic position, no elevation.

### Validation capability required

Reuse `schemas/associations.py` and `interpretation/tracking.py` unchanged.
The test is whether two observations the **total station** places at the same
local coordinate, from different passes within one sequence, associate — and
whether that association earns `corroborated` under the existing rule requiring
two independent acquisitions. Association thresholds stay caller-declared; none
is to be tuned to make the result look better.

### Roadmap items advanced

- Repeat-observation association/tracking: **infrastructure-only → validated on
  real data**, with the honest limit that all repeats are same-day, so temporal
  change detection remains unvalidated.
- `local_cartesian_position`: `available` → `working`, on measured coordinates.
- `odometry_position`: a second independent corpus.

### Explicitly not advanced

Detection scoring, localisation scoring, vertical registration, geographic
placement, native-format support, temporal change detection.
