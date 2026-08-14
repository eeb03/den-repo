# BHRS as a depth-calibration dataset — investigation

## 1. Executive verdict

**BHRS has the best calibration *geometry* of anything investigated, and its
data is not obtainable.** The two findings are independent and both matter.

| | |
|---|---|
| **Verdict** | **D — INSUFFICIENT / DATA INACCESSIBLE**, with a strong caveat below |
| Raw data | **Class 4 — PAPER-ONLY EVIDENCE.** No BHRS GPR, seismic or log data is downloadable anywhere located |
| Its published time-zero | **jointly fitted with velocity — category C.** Not independent evidence |
| Its level runs | **potentially the independent anchor**, but only secondary statements found; no numbers |
| Transfers to 4TU | **NO — category 3**, generic machinery validation at most |

The caveat that stops this being a flat "no": **crosshole geometry is the design
Stage 25 said was missing**, and BHRS is the first dataset encountered that has
it. That is a finding about *what to look for next*, not about BHRS.

**Confidence: HIGH** on inaccessibility and on the fitted-t0 classification (both
from primary sources). **MEDIUM** on the level runs, which rest on a secondary
statement.

## 2–4. Inventory, downloadable resources, raw-data availability

Established in `external-calibration-dataset-audit.md` §3–4 and unchanged:

- `boisestate.edu/earth-bhrs/` → **HTTP 410, "This site has been archived or
  suspended"** (verified with a browser user-agent; not bot-blocking).
- Wayback holds **1,245 `earth-bhrs` URLs containing zero data files**.
- The archived **BHRS Data Repository** listed three items: a Database
  Management System page (never archived), a **synthetic** aquifer ZIP, and
  hydraulic-tomography data. **Both ZIPs return 404.**
- The CGISS **Data Downloads** page offered two datasets, **neither BHRS**.
- Every BHRS paper checked: *"data … shared on reasonable request to the
  corresponding author."*

**What IS retrievable is literature.** The `wp-content/uploads/` file store still
serves, and `Yang-etal-2013-JAG-full-waveform-BHRS-1.pdf` (2,229,326 bytes) was
downloaded and read for this stage. That is the primary source below.

**No file inventory can be produced** — there are no files. Classification:
**4 — PAPER-ONLY**.

## 5. Acquisition system (DIRECT, from Yang et al. 2013)

| | |
|---|---|
| System | **MALÅ RAMAC Ground Vision** |
| Centre frequency | **250 MHz nominal in air**; dominant **~80 MHz** observed, lowered by borehole fluid and saturated sediment |
| Dominant wavelength | ~1 m in the low-velocity sediments |
| Borehole depth | ~20 m |
| **Borehole separation (C5–C6)** | **~8.5 m** |
| Casing diameter | 0.1 m |
| Water table | ~3 m depth |
| Geometry | 40 transmitter positions, up to 311 receivers |
| Antennas | vertical dipole type |

## 6. Borehole / control geometry

18 research wells (13 within the central radar grid, on a ~20 × 30 m surface
grid). Crosshole tomography ran between named boreholes (C5, C6, and others).
Independent logs exist: **neutron–neutron porosity** and **capacitive
conductivity** (1 MHz tool). Yang et al. compare FWI results against those logs
at specific depths — e.g. porosity features at ~5.7 m in C5 and ~6.0 and ~14.8 m
in C6.

**Borehole collar coordinates, elevations and a vertical datum were not located
in any accessible source.** Absence of evidence, recorded as such.

## 7. Time-zero evidence — the highest-priority question

Two distinct mechanisms exist and they must not be conflated.

### 7a. The FWI source wavelet — **NOT independent**

Yang et al. 2013, verbatim:

> *"a source wavelet needs to be estimated using a deconvolution approach … that
> uses the **ray-based inversion results as starting model**."*

The source wavelet absorbs the system's time origin. It is estimated by
deconvolution **against a velocity model derived from the same traveltimes**.
Answering the brief's A–I:

| | |
|---|---|
| A. What was measured? | nothing — the wavelet is *estimated* |
| B. Instrument | MALÅ RAMAC |
| C. **Independent of subsurface velocity?** | **NO** — the starting model *is* a velocity inversion |
| D. Numerical t0 | **none published** |
| E. Available? | no |
| F. System-specific? | yes |
| G. Transferable? | no |
| H. Reproducible by Subterra? | no — requires the raw gathers |
| I. **Constrains t0 independently of velocity?** | **NO** |

**This is precisely the "fitted intercept from a velocity/depth inversion" the
brief forbids treating as independent.** Category **C — JOINTLY FITTED**.
**Confidence: HIGH** (primary source, quoted).

### 7b. Level runs — the real candidate, unverified

The claim that *"level runs provide quality control and help calibrate origin
times in the tomography data"* is **corroborated but only from secondary
description**; the primary BHRS page carrying it is the suspended site.

Why it would matter if verified: a level run places transmitter and receiver at
the **same depth in two boreholes whose separation is surveyed**. Travel time
over a *known distance* — not a fitted one. With **several borehole pairs at
different separations**, t0 and velocity separate, because the design finally
varies distance rather than depth.

**Not verified. No numerical t0, no procedure, no data.** Confidence: **MEDIUM**
that the mechanism exists; **ZERO** on any value.

## 8. Velocity evidence

| Method | Classification | Notes |
|---|---|---|
| Crosshole traveltime tomography | **B — independently constrained** *in principle* — travel time over surveyed borehole separation | no numerical values obtained |
| **VRP (vertical radar profiles)** | **B**, reported to "help constrain tomographic inversions" | secondary statement only |
| FWI | **C — jointly fitted** with the wavelet | excluded as independent |
| Petrophysical from porosity logs (GJI 2022, same site) | **B — independently constrained** | **0.08–0.12 m/ns** in saturated zones, via `v = c/[√εs(1−φ) + √εw·φ]`, c = 0.3 m/ns |

The porosity-log velocity is genuinely independent of the GPR — it comes from
neutron logs and a petrophysical model. **It is site-specific to a saturated
fluvial sand-and-gravel aquifer.** Value/units recorded; uncertainty not
published; **not transferable** (see §13).

## 9–10. Physical depth and absolute elevation

Independent depth control exists as **borehole logs**, with features at stated
depths below surface (§6). What could not be established from any accessible
source:

- borehole collar **elevations**;
- a **vertical datum**;
- an explicit, published **reflector-to-borehole-feature association** of the
  kind that would let a GPR arrival be tied to a logged interface without
  visual judgement.

Yang et al. compare FWI *tomograms* with logs and report a **"static shift"**
between ~9.5–12 m in C5 and below ~16 m in C6 — i.e. the two disagree in places.
That is honest reporting by the authors, and it is also a warning: the
tomogram-to-log correspondence is **not** a clean depth truth.

**Absolute reflector elevation cannot be assembled** — surface elevation and
datum are both missing. Confidence: HIGH.

## 11. Reproducibility

**Class 4.** Nothing to ingest, nothing to inspect, no headers, no sampling
interval, no geometry file. The published calibration **cannot be reproduced**,
and no experiment can be run. No isolated conversion script was written, because
there is nothing to convert.

## 12. Proposed validation experiment — **not proposable on BHRS**

The brief's stop condition asks me to propose an experiment *if raw data are
available and suitable*. **They are not**, so I propose none on BHRS.

What BHRS does supply is the **experiment design** to look for elsewhere:

```
surveyed borehole separation (a KNOWN distance, not a fitted one)
        ↓
level-run / crosshole travel time at several separations
        ↓
t0 and velocity separate, because DISTANCE varies
        ↓
compare derived depth against borehole-logged interfaces
```

## 13. Transferability to 4TU — **NO**

| | BHRS | 4TU |
|---|---|---|
| Manufacturer | MALÅ RAMAC Ground Vision | Spectre / RadarMap-exported SEG-Y |
| Frequency | 250 MHz nominal, **~80 MHz dominant** | 500 MHz |
| Mode | **crosshole, borehole-deployed, vertical dipole** | **surface, air-launched** |
| Coupling | borehole fluid + saturated sediment | air gap above ground |
| Material | saturated fluvial sand and gravel below a 3 m water table | Dutch urban subsurface, variable |
| Time-zero convention | absorbed in an estimated source wavelet | none applied at all |

Every axis differs, and the two most important — **borehole-deployed versus
air-launched**, and **8.5 m of saturated sediment versus a few centimetres of
air** — make the systems physically incomparable for t0. A borehole antenna has
no air gap; the 4TU blocker *is* the air gap.

**Classification: 3 — GENERIC SUBTERRA MACHINERY VALIDATION.** Not even
category 2, because no data exists to validate methodology against.

## 14. Comparison with TU1208 and BAM

| | Association | Depth truth | Independent t0 | Data in hand |
|---|---|---|---|---|
| **TU1208** | ✗ no transverse offset, no along-line origin | ✓ surveyed | ✗ confounded −0.95 | ✓ 67 files |
| **BAM** | ✓ **published X in the scanner frame** | ✓ attested | ✗ confounded −0.94 | ✓ held |
| **4TU** | ✗ trench↔line unregistered | ✓ trench depths | ✗ none | ✓ held |
| **BHRS** | ✓ **borehole logs at known depth** | ✓ logs | **~ level runs, unverified** | ✗ **none** |

**What BHRS has that the others do not: a geometry in which distance varies.**
TU1208, BAM and 4TU all vary *depth* at roughly fixed acquisition geometry, which
Stage 25 proved cannot separate t0 from velocity regardless of how many targets
are added. Crosshole level runs vary the *distance* between transmitter and
receiver over surveyed baselines. **That is a different design, not more of the
same one** — and it is the only place this project has found it.

**What BHRS lacks that all three others have: retrievable data.**

## 15. Stage 8–12 impact

Using the repository's own dimensions (`schemas/spatial_reference.py`) rather
than definitions invented here:

| Dimension | Current blocker | BHRS evidence | Satisfies? | Machinery only? | Removes 4TU blocker? |
|---|---|---|---|---|---|
| CRS / horizontal | 4TU EPSG undeclared | none | no | — | **no** |
| Vertical datum | established for 4TU acquisition elevation | none | no | — | **no** |
| Surface elevation | 4TU partial (GNSS + AHN) | **not located** | no | — | **no** |
| **Depth-axis origin** | no t0 anywhere | **fitted, not measured** | **no** | — | **no** |
| **Propagation velocity** | none measured | 0.08–0.12 m/ns, site-specific | **no** | — | **no** |
| Physical depth | needs both above | borehole logs, no data | no | — | **no** |
| Absolute subsurface elevation | needs all above | no datum, no elevations | no | — | **no** |
| Spatial registration | 4TU horizontal works | none | no | — | **no** |

**No dimension changes. No readiness state was altered.**

## 16. Remaining blockers

Unchanged and verified against live state this session: 4TU `origin_offset`
`None`, axis `vertical_datum` `None`, conversion still the uncalibrated
0.1 m/ns labelled `derived`. **t0, velocity, physical depth and absolute
subsurface elevation all remain BLOCKED.**

## 17. Recommended next stage

**Not a BHRS implementation stage** — there is nothing to implement against.

**Smallest scientifically defensible next stage BHRS enables:** *search open
repositories specifically for a **crosshole or borehole GPR dataset with
surveyed borehole separations and downloadable raw traces***. BHRS's
contribution is having identified **which acquisition geometry can break the
t0/velocity degeneracy** — vary the distance, not the depth. Stage 26 already
surfaced one live candidate matching that description: **TestUM
(PANGAEA 10.1594/PANGAEA.971978, CC-BY, openly downloadable)** — crosshole plus
reflection borehole GPR with **borehole deviation measurements and DGPS**.

That is the stage: audit TestUM against the criteria this investigation
developed, because it is BHRS's design with BHRS's missing property — the data.

A zero-cost parallel action: **email the BHRS corresponding author.** Every
paper invites it, and BHRS would become genuinely valuable if granted.

## 18. Sources

**PRIMARY / DIRECT** — Yang, X. et al. (2013), *Improvements in crosshole GPR
full-waveform inversion and application on data measured at the Boise
Hydrogeophysics Research Site*, J. Appl. Geophys. 99, 201–212 — downloaded from
[boisestate.edu](https://www.boisestate.edu/wp-content/uploads/sites/290/2020/01/Yang-etal-2013-JAG-full-waveform-BHRS-1.pdf)
(2,229,326 bytes, 11 pages read). Supplies §5, §7a, §9.

**AUTHOR/PUBLISHER** — [GJI 230(1) 131](https://academic.oup.com/gji/article/230/1/131/6526313):
data availability, porosity-log velocities. Dafflon, Irving & Barrash (2011),
crosshole inversion. Tronicke et al. (2004); Mwenifumbo et al. (2009), logging.

**EXTERNAL REFERENCE** — [BHRS site](https://www.boisestate.edu/earth-bhrs/)
(HTTP 410, suspended); Wayback CDX enumeration; secondary description of level
runs and VRPs.

**SUBTERRA MEASUREMENT** — HTTP status checks, Wayback enumeration, PDF
retrieval and text extraction performed in this stage.

**INFERENCE** — that surveyed borehole separations would break the t0/velocity
degeneracy. Follows from Stage 25's `corr = −1/√(1+CV²)` applied to a design
where *distance* varies; **not** a statement BHRS makes.

## 19. Final verdict

| Capability | BHRS evidence | Independent? | Usable by Subterra? | Transfers to 4TU? | Status |
|---|---|---|---|---|---|
| Time-zero | source wavelet from deconvolution on a ray-based starting model; level runs described but unverified | **No** (wavelet) / unknown (level runs) | **No — no data** | **No** | **BLOCKED** |
| Velocity | 0.08–0.12 m/ns from porosity logs; crosshole tomography; VRP | **Yes** (porosity logs) | **No — no data** | **No** — saturated gravel, borehole-deployed | **BLOCKED** |
| Physical depth | borehole logs; authors report a static shift vs tomograms | Yes | **No — no data** | **No** | **BLOCKED** |
| Reflector association | log features at stated depths; no published arrival-to-feature tie | Partial | **No — no data** | **No** | **BLOCKED** |
| Surface elevation | not located | — | **No** | **No** | **BLOCKED** |
| Vertical datum | not located | — | **No** | **No** | **BLOCKED** |
| Absolute subsurface elevation | no datum, no collar elevations | — | **No** | **No** | **BLOCKED** |
| End-to-end validation | none possible | — | **No** | **No** | **BLOCKED** |

**BHRS ROADMAP VERDICT: D — INSUFFICIENT / DATA INACCESSIBLE.**

Justified because every row above fails on the same cause: **Class 4,
paper-only.** It is not C (partial calibration evidence), because partial
evidence would still require a number or a file, and BHRS yields neither — its
one published time-zero mechanism is explicitly fitted against a velocity model,
which the brief excludes by name. It is not B, because validating machinery
requires data to run the machinery on.

**The smallest scientifically defensible next stage BHRS enables:** audit
**TestUM** — the openly downloadable crosshole borehole-GPR dataset with surveyed
borehole geometry — against the criteria developed here. BHRS's real contribution
is diagnostic: it identified that **varying the transmitter–receiver distance
over surveyed baselines**, not adding more targets at more depths, is the
acquisition geometry that can break the t0/velocity degeneracy Stage 25 proved
is otherwise structural.
