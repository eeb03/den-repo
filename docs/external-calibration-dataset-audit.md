# External calibration dataset audit

Can an external dataset supply an independently constrained t0 and velocity,
validate Subterra's time→depth machinery, and — separately — legitimately inform
4TU?

## 1. Executive conclusion

**One dataset was acquired and verified in hand. BHRS, the brief's lead
candidate, is not downloadable.**

| | |
|---|---|
| **BHRS** | **Level 1.** Site suspended; its Data Repository held only a *synthetic* aquifer archive and hydraulic-tomography data, both now 404. **No BHRS GPR or seismic is downloadable anywhere.** |
| **Wurtsmith AFB multi-offset GPR** | **Level 2, in hand** — 16.6 MB SEG-Y recovered, 25-fold common-source gathers, t0 method stated in the file's own header |
| **TestUM borehole GPR (PANGAEA)** | **Level 2–3, open CC-BY** — crosshole + reflection, borehole deviation + DGPS |
| **3000-antenna lysimeter** | **Level 1** — the only true d = 0 system-delay measurement found (±4 ps), data by request |
| **IRIS / `ds.iris.edu`** | **Not applicable** — archives no GPR of any kind |

**Nothing found transfers to 4TU.** Subterra's architecture can be externally
validated; 4TU's t0, velocity, physical depth and subsurface elevation remain
BLOCKED.

## 2. Current 4TU blocker state (unchanged by this stage)

| | |
|---|---|
| Acquisition-elevation datum | **established** — WGS84 ellipsoidal, SEG-Y bytes 45–48, attributed to Dr. ter Huurne, `verified=False` |
| Depth-axis origin (t0) | **BLOCKED** — `origin_offset` is `None`; `DelayRecordingTime` formally ruled out in Stage 25 |
| Propagation velocity | **BLOCKED** — still the converter's uncalibrated 0.1 m/ns, labelled `derived` |
| Physical depth | **BLOCKED** |
| Subsurface absolute elevation | **BLOCKED** |

## 3–4. BHRS deep audit

The brief's URL `cgiss.boisestate.edu/bhrs/` is dead (DNS). The current
`boisestate.edu/earth-bhrs/` returns **HTTP 410 with the body "This site has
been archived or suspended"** — confirmed with a browser user-agent, so this is
not bot-blocking. The `wp-content/uploads/` file store still serves (a 1.3 MB
PDF returns 200), so the trail was followed into the archive rather than
abandoned.

**The BHRS Data Repository page** (Wayback, 2015-12-28, HTTP 200) listed exactly
three items:

| Item | Status |
|---|---|
| BHRS Database Management System | page **never archived**; site dead |
| Synthetic BHRS Aquifer (.zip, 17.7 MB) | **404 from Wayback** — and *synthetic*, which Subterra cannot use as field evidence |
| 2010 HT data used in inversion (.zip) | **404 from Wayback**; hydraulic tomography, not GPR |

**The CGISS "Data Downloads" page** — the only page offering data at all —
carried exactly two datasets, and *neither is BHRS*: the FMCW lab data, and the
Wurtsmith AFB GPR. 1,245 archived `earth-bhrs` URLs contain **zero** files with
any data extension.

**Answering A–M:**

| | Question | Finding |
|---|---|---|
| A | Raw surface GPR downloadable? | **No** |
| B | Raw crosshole GPR downloadable? | **No** |
| C | Level-run / VRP data downloadable? | **No** — never appear in any archived index |
| D | Well logs / core downloadable? | **No.** One `BHRS well data 111607.XLS` exists in the HT area; it is water-level/well-construction data, not geophysical logs |
| E | Numerical t0 published? | **No numerical value** in any accessible source |
| F | How was origin time determined? | In a BHRS surface-GPR paper (GJI 2022): *"the first deflection of the data above the ambient noise level"*, with *"uncertainties … not exceed[ing] ∼2 ns"* — a **first-break pick**, not an independent measurement |
| G | Is that calibration independent of the validating reflector? | **Partially.** The pick is independent of the reflector, but it is a pick on the same signal, not a measured delay. ±2 ns ≈ 0.1 m at 0.1 m/ns |
| H | Velocity independently constrained? | **Yes, in the publication** — from neutron-neutron porosity logs via `v = c/[√εs(1−φ) + √εw·φ]`, 0.08–0.12 m/ns in saturated zones. Genuinely independent of the GPR |
| I | Velocity method | Petrophysical model applied to **borehole porosity logs**; tomography and VRP used elsewhere in the BHRS corpus |
| J | Borehole depth control? | **Yes** — 18 wells; porosity logs at B5, A1, B2 along the profile |
| K | Interfaces tied to both GPR and boreholes? | **Yes, in the publications** |
| L | Coordinates/elevations with a datum? | Not obtainable from anything downloadable |
| M | Can the calibration be reproduced from downloadable material? | **No** |

**BHRS proves the method can be calibrated. It does not provide a dataset
Subterra can execute.** Every BHRS paper checked carries the same statement:
*"The data underlying this paper will be shared on reasonable request to the
corresponding author."* **Evidence Level 1.** An email would move it; nothing
else will.

## 5. Borehole/core-tied GPR

**TestUM, Wittstock (PANGAEA 10.1594/PANGAEA.971978)** — Jung, Pohle & Werban
2024. Borehole-GPR **crosshole and reflection** monitoring of freeze–thaw
cycles, GSSI SIR-4000 with Tubewave-100 antennas, 0.25 m intervals,
Nov 2022–Dec 2023, to 16.75 m depth. Includes borehole **deviation measurements
and DGPS**. **CC-BY-4.0, openly downloadable, no request needed.**

Why it matters: **crosshole travel time between boreholes at surveyed separation
is a direct velocity measurement that never touches a reflector depth** — the
borehole analogue of a CMP, and one of the few genuinely independent velocity
constraints that exists. Metadata mentions neither t0 nor velocity, and no
elevation, so its level cannot be fixed above **2–3** without downloading and
auditing it.

## 6. GPR calibration systems (the d = 0 category)

Stage 25 established that only an observation at d = 0 truly anchors t0. Exactly
one such measurement was found:

**"In situ time-zero correction for a GPR monitoring system with 3000 antennas"**
(*Meas. Sci. Technol.* 33, 075904, 2022). A lysimeter (1.5 m × 1 m²) ringed by
~3000 antennas. t0 is defined as `t₀ = tₐ − d/c₀` and obtained from **reciprocal
WARR measurements in air**, explicitly contrasted with methods that *"require
known reflector depths"*. Reported: **t₀ = 30.604 ± 0.004 ns**, system-delay
accuracy **±4 ps**, velocity check within 0.4%.

This is the textbook realisation of Stage 25's design C. Its limits are equally
clear: it is **instrument-specific** (that antenna array and that electronics),
it is a **laboratory** system, and *"data … available upon reasonable request"*.
**Level 1**, and not transferable to any other instrument.

The CGISS **FMCW lab data** (Marshall & Matsuoka, CRREL 2005) is downloadable and
includes **calibration spheres** — but it is 2–10/12–18 GHz frequency-domain
FMCW in MATLAB `.mat`, measuring scattering from plexiglass targets. Wrong
modality; it cannot calibrate a time-domain GPR t0.

## 7. Well-tied seismic

Not pursued to acquisition, deliberately. Marmousi is **synthetic** — excluded by
Subterra's own rules. Checkshot/sonic well ties do validate the *general* pattern
`time → reference → velocity → depth → verified interface`, but they validate it
for seismic, and the only thing that could carry across is the **architecture**,
which the GPR cases already exercise. Acquiring a seismic volume to prove a
pattern two GPR datasets can prove is not the cheapest path.

## 8–9. Evidence-level table

| Dataset | Repo | Raw data | GPR | Boreholes | Coords | Datum | t0 evidence | t0 value | t0 method | Velocity evidence | Velocity method | Indep. depth | Reproducible | **Level** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Wurtsmith AFB Line 1** | CGISS (via archive) | **yes, in hand** | yes, 100 MHz PE100A | not in file | headers populated, ft | none declared | **in the file's EBCDIC header** | none | *"time zero correction based on first break at near offset"* | **25-fold multi-offset** | moveout/semblance, depth-independent | no | **partly** | **2** |
| **TestUM (PANGAEA)** | PANGAEA | **yes, CC-BY** | crosshole + reflection | **yes** | lat/lon + DGPS | none stated | none in metadata | — | — | crosshole traveltime possible | direct, depth-independent | **yes** | unknown | **2–3** |
| **BHRS** | none | **no** | — | 18 wells | — | — | publication only | none | first break, ±2 ns | publication only | porosity logs + tomography/VRP | yes | **no** | **1** |
| **3000-antenna lysimeter** | none | **no** | lab array | n/a | n/a | n/a | **measured system delay** | **30.604 ± 0.004 ns** | reciprocal WARR in air | 0.4% check | — | n/a | **no** | **1** |
| **CGISS FMCW** | CGISS (archive) | yes | FMCW only | no | lab | n/a | calibration spheres | — | sphere calibration | — | — | plexiglass targets | wrong modality | **1** |
| **IRIS** | — | — | **archives no GPR** | — | — | — | — | — | — | — | — | — | **n/a** |

## 10. Stage 8–12 mapping

| Requirement | 4TU | Classification | Why |
|---|---|---|---|
| CRS / horizontal datum | PARTIAL | **PARTIALLY UNBLOCKED** | positions decoded; EPSG undeclared. Needs no external dataset |
| Vertical datum (acquisition elevation) | established | **UNBLOCKED** | Stage 21 |
| Surface elevation | PARTIAL | **PARTIALLY UNBLOCKED** | GNSS + AHN over project 01 |
| Depth-axis origin (t0) | BLOCKED | **BLOCKED** | no external dataset supplies a 4TU-applicable t0; the one true measurement is instrument-specific to a lysimeter array |
| Propagation velocity | BLOCKED | **VALIDATED EXTERNALLY (machinery only)** | Wurtsmith's multi-offset gathers can exercise depth-independent velocity estimation. **This does not give 4TU a velocity** |
| Physical depth | BLOCKED | **BLOCKED** | needs both |
| Subsurface absolute elevation | BLOCKED | **BLOCKED** | needs all of the above |
| Spatial registration | PARTIAL | **PARTIALLY UNBLOCKED** | horizontal registration works; vertical does not |

**No readiness state was changed and none should be.** An external validation
case changes what Subterra has *demonstrated*, not what 4TU *is*.

## 11–13. Validated / transferable / blocked

**Can legitimately be validated now:** that Subterra reads and frames a
multi-offset SEG-Y correctly; that a velocity can be estimated from moveout
without using a reflector depth; that a documented t0 correction is represented
as an `origin_offset` rather than folded into the signal. All on Wurtsmith, in
hand.

**Can legitimately be transferred to 4TU: nothing.** No dataset found shares
4TU's acquisition system (a 500 MHz air-launched array with a Spectre SP80 RTK),
and none carries an author or vendor statement linking its calibration to 4TU's.
Wurtsmith is a Sensors & Software PE100A at 100 MHz; the lysimeter is a bespoke
laboratory array. Similarity of frequency, soil or manufacturer is explicitly
not sufficient, and none of these even offers that.

**Remains blocked:** 4TU t0, velocity, physical depth, subsurface absolute
elevation — for the same reason as before: nobody measured the system delay of
that instrument on that survey, and no correspondence or third-party dataset can
substitute for the measurement.

## 14. Ranked recommendation

**#1 — Wurtsmith AFB Line 1 multi-offset GPR.** *Already retrieved: 16.6 MB
SEG-Y, IBM float big-endian, format code 1, 750 samples at 0.8 ns, 25 traces per
common source point, offsets populated in the trace headers.* Subterra's
big-endian SEG-Y path already reads this format. It addresses the **velocity**
blocker at the level of machinery: multi-offset moveout estimates velocity
*without* assuming a reflector depth, which is precisely the independence
Stages 24–25 could not obtain. Its own EBCDIC header documents the t0 handling
(*first break at near offset*), so Subterra can test whether it represents a
documented correction honestly.
→ **Validates Subterra externally. Does not unblock 4TU.**

**#2 — TestUM borehole GPR (PANGAEA, CC-BY).** Open, no request, crosshole plus
reflection with borehole deviation and DGPS. Crosshole traveltime over a surveyed
borehole separation is a **direct, depth-independent velocity measurement**, and
borehole depths give independent physical-depth control — the two things
Wurtsmith lacks. Needs a download-and-audit before its level is fixed.
→ **Validates Subterra externally; potentially the first complete end-to-end GPR
case. Does not unblock 4TU.**

**#3 — Email BHRS and the lysimeter authors.** Both say "on reasonable request",
and BHRS is the strongest scientific case found: 18 wells, porosity-log
velocities independent of the GPR, interfaces tied in both GPR and boreholes. The
lysimeter would supply the only genuine d = 0 system-delay measurement located.
Zero acquisition cost, unknown latency.
→ **Informs future architecture; BHRS would validate externally if granted.**

**And the cheapest 4TU-specific action remains outside this audit**: ask the 4TU
author or the GPR vendor for the instrument's system delay. That is the only
route found that could unblock 4TU itself, and no external dataset substitutes
for it.

## 15. Sources and evidence classes

**DIRECT EVIDENCE (measured/retrieved here)** — `wurtsmith_line1.sgy`, 16,579,440
bytes, HTTP 200 via `web.archive.org/web/2id_/http://cgiss.boisestate.edu/data_downloads/data/wurtsmith_line1.sgy`;
EBCDIC lines C1–C21 and binary/trace headers read directly. `boisestate.edu/earth-bhrs/`
HTTP 410 body *"This site has been archived or suspended"*. Wayback CDX: 1,245
`earth-bhrs` URLs, zero data files; both BHRS repository ZIPs HTTP 404.

**AUTHOR/PUBLISHER EVIDENCE** — GJI 230(1) 131 (BHRS): data availability, t0
method, ±2 ns, porosity-log velocities 0.08–0.12 m/ns.
*Meas. Sci. Technol.* 33 075904: t₀ = 30.604 ± 0.004 ns, ±4 ps, reciprocal WARR in
air, availability on request. PANGAEA 10.1594/PANGAEA.971978 metadata and licence.
CGISS `wurtsmith_1.php` acquisition description; `FMCW_data/readme.txt`.

**EXTERNAL REFERENCE** — `ds.iris.edu` archived data types (no GPR).

**SUBTERRA MEASUREMENT** — SEG-Y header decode of the Wurtsmith file.

**INFERENCE** — that crosshole traveltime at TestUM would yield a
depth-independent velocity. Reasoning from the acquisition geometry, not from
anything the dataset states; flagged as the reason its level is a range.

Sources: [BHRS](https://www.boisestate.edu/earth-bhrs/) ·
[GJI 230(1) 131](https://academic.oup.com/gji/article/230/1/131/6526313) ·
[MST 33 075904](https://iopscience.iop.org/article/10.1088/1361-6501/ac632b) ·
[PANGAEA 971978](https://doi.pangaea.de/10.1594/PANGAEA.971978) ·
[IRIS data types](https://ds.iris.edu/ds/nodes/dmc/data/)
