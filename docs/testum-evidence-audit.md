# TestUM Evidence Audit

## Dataset identity

Jung, P.; Pohle, M.; Werban, U. (2024): *Borehole-GPR crosshole and reflection
data from monitoring of freeze-thaw cycles in a geological latent heat storage
system.* Helmholtz Centre for Environmental Research – UFZ, PANGAEA.
**[10.1594/PANGAEA.971978](https://doi.org/10.1594/PANGAEA.971978)** ·
**CC-BY-4.0** · 3,885 data points · curation level: enhanced.

Companion paper (open access): Jung et al. (2024), *Combining crosshole and
reflection borehole ground-penetrating radar (GPR) for imaging controlled
freezing in shallow aquifers*, **Solid Earth 15(12), 1465–1477**,
[10.5194/se-15-1465-2024](https://doi.org/10.5194/se-15-1465-2024).

Site: TestUM, Wittstock/Dosse, Brandenburg, Germany — a former airfield over
quaternary glacial sediments. 53.1938–53.1939 N, 12.5047–12.5048 E.

## Data accessibility — the one real limitation

| Resource | Status | Verified |
|---|---|---|
| PANGAEA metadata / data matrix | **open**, 38,401 bytes | ✅ retrieved |
| **Borehole deviation + DGPS** (`GEWS_Deviation and GPS.zip`) | **open**, 188,791 bytes, 25 files | ✅ retrieved and parsed |
| **Experiment design PDF** | **open**, 1,091,609 bytes, 7 pages | ✅ retrieved and read |
| Companion paper | open access (Copernicus) | ✅ located |
| **Raw `.DZT` traces** | **HTTP 503 — "Account" / "login"** | ❌ two files, two attempts |

**Raw traces require a free PANGAEA account.** This is not inaccessibility of the
BHRS kind (where the data does not exist publicly at all) — it is a registration
step. Registering is an external-account decision and was **not** taken
unilaterally.

Everything below is therefore derived from **open metadata, open surveyed
geometry, and open author documentation** — not from traces.

## Primary sources

All conclusions here rest on: the PANGAEA record (`?format=textfile`), the
`ExperimentDesign_BoreholeGPR_Wittstock_2022-2023.pdf`, and
`GPS_Wittstock_GEWS_2Z.xlsx` from the deviation/GPS archive. Quoted verbatim
where it matters.

## Acquisition geometry

| | |
|---|---|
| Instrument | **GSSI SIR 4000** |
| Antennas | **Tubewave-100** (Radarteam Sweden AB) — 1 for reflection, 2 for crosshole |
| Reflection | one antenna as Tx+Rx, lowered in a borehole, every **0.25 m** from ≤16.75 m up to 0.25 m |
| **Crosshole** | **zero-offset profiles** — two antennas in two boreholes, **lowered simultaneously, measuring at the same depth** every 0.25 m |
| Samples / window | **1024 samples over 150 ns**, sample duration **0.146484375 ns** |
| Stacks | 60 (one file at 240) |
| Site | 16 heat-exchanger probes 18 m deep on a 1×1 m grid; 22 2-inch wells; 8 multilevel wells |
| Deviation | measured per borehole with a **DevProbe1** (Geotomographie), tilt + direction, giving the well path |

**Zero-offset crosshole is the geometrically important part.** Both antennas sit
at the same depth, so the ray path is the (near-)horizontal borehole separation —
a quantity surveyed by DGPS and refined by the deviation logs, **not** fitted
from the data.

### Measured separations (SUBTERRA MEASUREMENT, from the open GPS file)

19 crosshole well pairs were acquired; 18 have surveyed coordinates. Separations
computed from UTM 33U eastings/northings:

```
C04-C05 1.12   D04-D05 1.52   C12-C09 2.01   U06-U05 2.04   U05-C10 2.04
U04-C09 2.07   D05-C12 2.22   C07-C10 2.80   C04-C12 2.91   D04-C08 3.04
U06-C08 3.08   C05-C12 3.13   D05-C10 3.97   D05-U05 6.01   D04-U04 6.08
D04-U06 6.10                                            (metres)
```

**Range 1.12 – 6.10 m.** The transmitter–receiver distance genuinely varies
across independently surveyed baselines — the property Stage 25 identified as
necessary and BHRS suggested to look for.

## Time-zero evidence — **INDEPENDENTLY MEASURED**

The experiment design document states the procedure verbatim:

> *"For determination of zero-time both antennas are placed on the ground
> perpendicular to each other. **Distance between antennas is increased from
> X=1 m to X=3 m measuring each dx=0.2 m.** Maximum of first arrivals are picked
> … **Zero-time is calculated subtracting the expected travel time in air from
> the measured travel time.** Value at X=3 m is used to avoid near field effects
> that may occur for shorter distances. **Measurements at the end of each
> survey-day were used for zero-time correction to minimize temperature
> effects**, as antennas and cables still have the same temperature as during
> borehole measurements."*

This is an **air-WARR calibration over 11 surveyed separations**, and it is the
d≈0-class anchor Stages 24–25 concluded was missing everywhere else:

| Question | Answer |
|---|---|
| What was measured? | first-arrival time in **air** at surveyed antenna separations 1.0–3.0 m |
| Independent of *subsurface* velocity? | **YES — entirely.** The propagation medium is air, whose velocity is a physical constant, not a fitted parameter |
| Is it a fitted intercept? | **NO.** t0 = t_measured − X/c_air, computed directly |
| Temperature control | yes — repeated at the end of each survey day |
| Classification | **INDEPENDENTLY MEASURED** (procedure: AUTHOR-STATED documentation) |

**On the numerical value — deliberate caution.** The PANGAEA data matrix carries
a column **`Radar time delay [ns] = 16.3`**, populated on the **reflection** rows
and **blank on every crosshole row**. Whether 16.3 ns *is* the measured zero-time,
or a separate acquisition-time delay setting, **is not established by anything
read here** — and the blank-for-crosshole pattern argues against a simple reading.
Per rule 5 it is classified **AUTHOR-STATED PARAMETER, meaning unverified**, and
no t0 value is adopted.

So: **the procedure is independently measured and documented; a confirmed
numerical t0 was not extracted.** Confidence HIGH on the former, and the latter
would most likely be settled by the raw traces plus the companion paper.

## Velocity evidence

Velocity is **independently constrainable by construction**, and this is the
dataset's real strength:

```
t0            measured in air, independent of the ground   (air-WARR)
L             surveyed borehole separation, DGPS + deviation
t_measured    crosshole zero-offset first arrival
  ⇒  v = L / (t_measured − t0)      — no joint fit required
```

Because t0 comes from a *different experiment in a different medium*, it is not
co-estimated with v. That is the distinction Stage 24 could not achieve on
TU1208 and Yang et al. did not achieve at BHRS, where the source wavelet was
deconvolved from a ray-based velocity model.

Classification: **INDEPENDENTLY CONSTRAINED** (category B), conditional on
obtaining the traces. No numerical velocity is adopted here.

## Identifiability experiment (SUBTERRA MEASUREMENT)

Applying the Stage 25 law to the crosshole design, `t = t0 + L/v`, using the 18
surveyed separations:

| | |
|---|---|
| n | 18 |
| L range | 1.12 – 6.10 m |
| CV | 0.538 |
| **corr(t0, slope)** | **−0.881** |
| Check against −1/√(1+CV²) | −0.881 ✓ exact |
| TU1208 silt / BAM ducts | −0.949 / −0.939 |

**Two honest readings, and the second is the one that matters.**

1. Taken alone, −0.881 is better than anything previously examined but still
   high — crosshole geometry by itself does not fully separate the parameters.
2. **It does not have to.** t0 is measured in air *before* any subsurface fit, so
   it enters as a known constant rather than a free parameter. The degeneracy
   metric applies to a joint fit that this design never performs.

That is the substantive difference between TestUM and every prior candidate: not
a better-conditioned fit, but **one fewer parameter to fit**.

**This experiment used surveyed geometry only.** No traces, so no t0, velocity,
residuals or sensitivity analysis were computed — those require the raw data and
are deliberately not estimated.

## Physical-depth truth

Weaker than the timing evidence, and it should be said plainly. TestUM's targets
are a **controlled freezing front** and aquifer structure, not surveyed discrete
objects. What exists: known heat-exchanger geometry (16 probes, 18 m deep, 1×1 m
grid), borehole depths to 16.75 m, and reflection profiles at 0.25 m steps.

There is **no published list of reflectors at attested depths tied to specific
traces** of the kind BAM has. The freezing front is a *controlled and monitored*
subsurface change, which is different evidence — strong for time-lapse
validation, weak for absolute depth truth.

## Coordinate and vertical reference

From `GPS_Wittstock_GEWS_2Z.xlsx`, per 2-inch borehole: latitude, longitude,
**UTM north/east (Zone 33U)**, `ID_2inch_borehole`, and **both**:

| | measured range (22 wells) |
|---|---|
| **Geoidheight [m asl]** | 69.313 – 69.601 m |
| **Ellipsoidheight [m asl]** | 109.265 – 109.553 m |
| mean separation | **39.95 m** |

A ~40 m ellipsoid-to-geoid separation is consistent with northern Germany, an
independent sanity check that the two columns mean what they say.

**TestUM therefore ships both vertical references per borehole** — better than
4TU, where identifying which SEG-Y field held the ellipsoidal height took a whole
stage of AHN comparison. The specific geoid model / realisation is **not named**
in what was read, so "geoid height" is author-stated rather than a confirmed
named datum.

## Raw vs processed status

The `.DZT` files are the **native GSSI acquisition format** and the data matrix
records acquisition parameters (traces, stacks, samples, recording duration)
rather than processing steps — consistent with raw or minimally processed data
retaining its original time axis. **Not verified**, because the files are behind
the account gate. Recorded as *probable raw, unconfirmed*.

## 4TU transferability

| Property | TestUM | 4TU | Transferability |
|---|---|---|---|
| Acquisition geometry | borehole crosshole + borehole reflection | surface, along-track | **NOT TRANSFERABLE** |
| Antenna | Tubewave-100 borehole, 2 units | 500 MHz air-launched array | **NOT TRANSFERABLE** |
| Raw time axis | 1024 samples / 150 ns / 0.1465 ns | 512 samples / ~50 ns / 97 ps | NOT TRANSFERABLE |
| **t0 evidence** | **measured in air over surveyed X** | none | **METHODOLOGICALLY TRANSFERABLE** |
| Velocity evidence | crosshole over surveyed L | none | **METHODOLOGICALLY TRANSFERABLE** |
| Independent geometry | DGPS + deviation probe | GNSS track only | METHODOLOGICALLY TRANSFERABLE |
| Borehole control | 22 wells + 8 multilevel | none | NOT TRANSFERABLE |
| Surface control | DGPS per borehole | per-trace GNSS | UNKNOWN |
| CRS | UTM 33U | undeclared (EPSG absent) | NOT TRANSFERABLE |
| Vertical datum | geoid + ellipsoid heights | ellipsoidal, declared Stage 21 | NOT TRANSFERABLE |
| **Air gap** | **none — antenna in borehole fluid** | **the blocker itself** | **NOT TRANSFERABLE** |
| Ground contact | borehole-coupled | air-launched, uncoupled | NOT TRANSFERABLE |
| Processing | zero-time correction applied | none applied | NOT TRANSFERABLE |
| Physical depth truth | freezing front, no discrete targets | trench depths, unregistered | NOT TRANSFERABLE |

**No value transfers.** The decisive rows are the same two that ruled out BHRS:
borehole-deployed versus air-launched, and **no air gap versus an air gap that is
precisely 4TU's unknown**.

**What does transfer is the method**, and it transfers usefully: an air-path
calibration over surveyed antenna separations is *exactly* the measurement 4TU
lacks, and it is instrument-agnostic in principle. It is a **field procedure**,
so applying it to 4TU would require the original instrument — it cannot be
recovered from published files.

## Stage 8–12 impact

| Stage | Does TestUM satisfy the acceptance condition? |
|---|---|
| **8 — coordinate/geospatial** | **No.** Its UTM 33U is TestUM's; 4TU's EPSG remains undeclared |
| **9 — vertical reference** | **No** for 4TU. TestUM has geoid+ellipsoid heights of its own |
| **10 — depth-axis origin** | **No for 4TU.** TestUM demonstrates a valid independent t0 *method*; a method is not a 4TU measurement |
| **11 — velocity/depth conversion** | **No for 4TU.** Potentially validatable on TestUM itself, once traces are obtained |
| **12 — physical 3D registration** | **No.** No discrete depth truth tied to traces |

**No stage is unblocked. No readiness state changed.**

## Evidence classification

| Item | Class |
|---|---|
| Zero-time procedure (air-WARR at surveyed X) | **AUTHOR-STATED documentation of an INDEPENDENTLY MEASURED quantity** |
| `Radar time delay = 16.3 ns` | **AUTHOR-STATED parameter, meaning UNVERIFIED** |
| Borehole separations 1.12–6.10 m | **SUBTERRA MEASUREMENT** from open surveyed coordinates |
| corr(t0, slope) = −0.881 | **SUBTERRA MEASUREMENT** (geometry only) |
| Geoid/ellipsoid heights | **MEASURED**, datum realisation not named |
| Raw-vs-processed status | **UNKNOWN** — files gated |
| Velocity | **NOT OBTAINED** — no value adopted |

## The ten questions

1. **Independently known t0?** A documented, genuinely independent **procedure** —
   yes. A confirmed **number** — no.
2. **Independently known velocity?** Not published; **independently constrainable**
   from surveyed L and measured t0, once traces are obtained.
3. **Enough geometry to estimate both separately?** **Yes** — and by removing t0
   from the fit, not by conditioning it better.
4. **Physical-depth truth tied to traces?** **No.** A controlled freezing front,
   not surveyed discrete targets.
5. **Absolute elevation / vertical datum?** **Yes** — geoid and ellipsoid heights
   per borehole; geoid realisation unnamed.
6. **Calibration transferable to 4TU's air-launched acquisition?** **The method,
   yes; the values, no.** And the method is a field procedure needing the
   instrument.
7. **Reduces questions for the 4TU author?** **Yes, one — and sharpens it.** It
   shows the right question is not "what was the time zero" but "was an
   air-path calibration at a measured antenna separation ever recorded, and if
   so what was the separation and the picked time".
8. **Unblocks Stages 8–12?** **No.**
9. **Missing evidence?** For 4TU: an actual air-path calibration measurement on
   that instrument. For TestUM: the raw traces (account) and confirmation of what
   the 16.3 ns column means.
10. **Next highest value?** Register a free PANGAEA account, obtain the traces,
    and run the real identifiability experiment on TestUM — the first dataset
    encountered where it can actually be run.

## Remaining blockers

4TU t0, velocity, physical depth and absolute subsurface elevation **all remain
BLOCKED**, unchanged.

## Recommended next action

**Not an implementation stage.** Two options, both requiring a decision:

1. **Register a free PANGAEA account** and download the `.DZT` traces. Subterra's
   GSSI converter already reads DZT. This would enable the first genuine
   end-to-end validation: measured time → independently measured t0 → velocity
   from surveyed L → depth. *Requires your authorisation — it is an external
   account registration.*
2. **Ask the 4TU author the sharpened question** from §7 above.

---

## Verdict

**B — PROVIDES A VALID CALIBRATION METHOD.**

TestUM documents a calibration that is genuinely independent of subsurface
velocity — an air-path measurement over surveyed antenna separations, repeated
per survey day for temperature control. That is the first such procedure found in
four stages of searching, and it is the design Stages 24–25 proved was necessary.

It is **not A**, because nothing transfers to 4TU: the antennas are borehole-
deployed with no air gap, and the air gap is 4TU's blocker.
It is **not E**, because the geometry and documentation are open and were
retrieved and analysed here — only the traces are gated, and only by a free
account.

| Capability | Independent? | Usable by Subterra? | Transfers to 4TU? | Status |
|---|---|---|---|---|
| Time-zero | **YES — measured in air** | method yes, value unverified | method only | **procedure established** |
| Velocity | constrainable | needs traces | **no** | pending data |
| Physical depth | freezing front only | limited | **no** | weak |
| Reflector association | zero-offset crosshole geometry | yes | **no** | good |
| Surface elevation | DGPS per borehole | yes | **no** | established |
| Vertical datum | geoid + ellipsoid | yes | **no** | established, unnamed realisation |
| Absolute subsurface elevation | not demonstrated | no | **no** | **BLOCKED** |
| End-to-end validation | **possible, pending traces** | **pending account** | **no** | **not yet run** |
