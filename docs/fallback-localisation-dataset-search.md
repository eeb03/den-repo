# Fallback localisation dataset search

**Question.** Not "find another GPR dataset" — find one that can validate the
chain `GPR measurement → interpretation → X/Y localisation → depth/elevation
localisation → 3D target → comparison against independently known physical
ground truth`, so Phase 9 3D reconstruction has something to be validated
against besides itself.

**Method.** Section 1 inventories what the repository already investigated —
four prior audits, `docs/external-calibration-dataset-audit.md`,
`docs/cross-dataset-evidence-audit.md`, `docs/testum-evidence-audit.md` and
its three follow-ups, spanning BHRS, Wurtsmith, TestUM, a 3000-antenna
lysimeter, Grimsel (flagged unaudited), Midtdalsbreen, Florida, karst, urban
hydrogeophysics and the RGPR curated index of 20 open datasets. Section 2 is
a fresh external search this pass ran to close the gaps that work left open,
particularly the one dataset it explicitly flagged as **promising,
unaudited**.

**No platform state was changed and no dataset was ingested.** This is a
qualification pass, not implementation, per the task's own instruction.

---

## 1. Previous candidates (already in the repository)

| Candidate | Held? | Raw GPR | X/Y | Depth/Z | CRS | License | Why it doesn't close the gate |
|---|---|---|---|---|---|---|---|
| **4TU utility survey** | ✅ ingested, 759/759 | ✅ SEG-Y | GNSS per trace, no EPSG declared | Trench depths **exist** (125 `ground-truth.png`) | ellipsoidal WGS84, `verified=False` | CC0-1.0 | **The only blocking gap left is registration**: no metric tie between the trench-distance table and a trace index. Both halves exist; nothing joins them |
| **TU1208 / IFSTTAR** | ✅ ingested, 67/67, 3 vendors | ✅ `.dzt`/`.rd3`/`.dt` | across-line offset only (1.25/3.75/6.25/8.75 m), no CRS | ✅ **theodolite-surveyed**, 9 pipe depths across 3 media | none | CC-BY-4.0 | No CRS, no absolute elevation. Strong for **local X + depth**, structurally incapable of geographic X/Y |
| **BAM concrete-gpr** | ✅ ingested (DZT reads unmodified) | ✅ `.DZT` | local specimen mm-grid (0–2000×0–800), no CRS by design | ✅ **fabricator-attested**, 4 duct depths + 4 step depths + a negative control | none (lab specimen) | CC0-1.0 | Concrete NDT, not soil; no CRS by design, so it can never supply geographic X/Y. The strongest depth truth held, in a frame that cannot generalise |
| **Hillside (Lancaster)** | ✅ ingested, 321/321 | ✅ `.rd3`/`.rad` | plot corners surveyed EPSG:27700, per-trace GNSS files all 0 bytes | none — no attested target | EPSG:27700 (corners only) | CC-BY-4.0 | Surveyed CRS and elevation exist; **no target of any kind**. A registration/CRS exemplar, not a localisation benchmark |
| **TestUM (PANGAEA)** | audited, not ingested | ✅ `.DZT`, downloaded and converts cleanly | UTM 33U per borehole, DGPS | freezing front only — **no discrete surveyed target** | geoid + ellipsoid heights per borehole | CC-BY-4.0 | The only dataset with a genuinely *independent* t0 procedure (air-WARR at surveyed separations) — but the t0 fit was run and came back **INCONCLUSIVE** (`docs/testum-air-warr-t0-experiment.md`, 2 of 26 files passed a physics falsifier). No discrete target ground truth exists at all |
| **BHRS** | investigated, unobtainable | ❌ no downloadable GPR anywhere | — | 18 wells, porosity-log velocities | — | "on reasonable request" only | **Site suspended.** Every archive link 404s. The strongest scientific case found (borehole-tied velocity, interfaces tied in both GPR and boreholes) and the least accessible |
| **Wurtsmith AFB** | acquired, 16.6 MB SEG-Y | ✅ | headers populated, no CRS declared | none | none | via web archive, terms unclear | Validates multi-offset velocity **machinery** only; no target, no CRS |
| **3000-antenna lysimeter** | investigated | request-only | n/a (lab) | n/a | n/a | "on request" | The only true *d*≈0 system-delay measurement found (±4 ps) — instrument-specific, not obtainable |
| **Grimsel Test Site (tracer)** | flagged **"promising, unaudited"** in the prior audit | unaudited at the time | — | — | — | — | Never followed up until this pass — see §2 |

**The prior audit's own conclusion stands unchanged by anything this pass
found**: *"Absolute subsurface elevation in a geodetic datum… needs surveyed
surface elevation and a vertical datum and an attested subsurface depth and a
defensible velocity, all on the same ground. Nothing held meets all three."*
This pass's job was to check whether anything **outside** the repository
does.

---

## 2. Search performed

Ten searches across the categories the task specified, run this pass:

1. Grimsel Test Site raw GPR downloadability (the one explicitly unaudited
   lead from the prior work)
2. Buried-utility test sites with surveyed coordinates, general web search
3. Recent (2024–2026) academic GPR-with-ground-truth papers, ScienceDirect/MDPI/PMC
4. The RGPR curated free-GPR-data index, re-checked for anything added since
   the prior audit
5. University/professional utility test beds (Poland, Malaysia, generic)
6. Archaeological GPR with excavation-confirmed targets, open repositories
7. IEEE DataPort GPR listings
8. Zenodo/OSF/PANGAEA direct searches for controlled-burial + RTK GPS + raw
   SEG-Y/DZT, 2024–2026
9. US military/countermine buried-threat GPR (a different target category —
   controlled test lanes with known object positions — the task's own
   acceptance criteria do not require the target be a utility)
10. Follow-through on the strongest concrete lead found (§4) into ETH
    Zurich's Research Collection, including its parent data collection

Sources actually fetched and read (not just search snippets): the ETH
Zurich Research Collection dataset and data-collection pages for the Grimsel
ISC experiment, the GPR README bitstream (fetched directly — see §4), the
`rightsstatements.org` license text, three PMC-hosted papers, and the RGPR
index page.

**Papers behind bot-protection (MDPI, ScienceDirect abstract pages) could not
be read directly** — the same limitation `dataset-benchmark-plan.md` already
recorded for TU1208's own paper. Where a paper could not be read, its dataset
is recorded as unverified rather than assumed favourable or unfavourable.

---

## 3. Top candidates

| Candidate | Raw GPR | X/Y | Z | CRS/elevation | Independent target truth | License | Access |
|---|---|---|---|---|---|---|---|
| **Grimsel ISC (GPR+seismic dataset)** | ✅ MALÅ `.rd3`/`.rad`/`.rd7` — **format Subterra already reads, zero converter work** | odometry (trigger-wheel) along 2 tunnel profiles; borehole/tunnel coordinates live in a **separate linked dataset**, not bundled | fracture-zone geometry is a 3D surface, not a scalar depth | Swiss national grid presumed for boreholes (unconfirmed from what was fetched); general site lat/long only in the metadata read | ✅ **the S3 shear zone**, mapped by optical televiewer + core logs + tunnel-wall mapping, explicitly independent of the GPR (Krietsch et al. 2018a) | **In Copyright – Non-Commercial Use Permitted** — permission required for commercial use | Open download, ETH Research Collection, confirmed working |
| **TU1208-IFSTTAR** | ✅ 3 vendors, already ingested | across-line offset only, no CRS | ✅ theodolite-surveyed, 9 depths / 3 media | none | ✅ published, transcribable | CC-BY-4.0 | Already on disk |
| **BAM concrete-gpr** | ✅ already ingested | local mm-grid only | ✅ fabricator-attested | none (by design) | ✅ already transcribed in-repo | CC0-1.0 | Already on disk |

No candidate scores as a clean Category A (full X/Y/Z, geographic). Grimsel
is the only one offering a genuinely **3D** (not scalar-depth) independent
target, which is structurally closer to what Phase 9 needs than either held
dataset — but it arrives with a licensing question TU1208 and BAM do not
have, and its coordinate assembly is not a single download.

---

## 4. Primary recommendation

**No dataset in this search qualifies as a Category A (full geodetic X/Y/Z)
benchmark**, and none should be reported as one. What follows is the
strongest **new** lead found, offered as the next thing to *qualify*, not as
a dataset already fit to build on.

### Newly identified: Grimsel ISC GPR dataset (ETH Zurich)

**Doetsch, J., Krietsch, H., Schmelzbach, C., Jalali, M., Gischig, V.,
Villiger, L., Amann, F., Maurer, H. (2020).** *GPR and seismic data for
characterizing the ISC rock volume at the Grimsel Test Site.* ETH Zurich
Research Collection, [10.3929/ethz-b-000420930](https://doi.org/10.3929/ethz-b-000420930).
Companion paper: *Characterizing a decametre-scale granitic reservoir using
GPR and seismic methods*, Solid Earth 11, 1441–1461 (2020),
[10.5194/se-11-1441-2020](https://doi.org/10.5194/se-11-1441-2020).

This was the prior audit's one explicitly **unaudited** lead
("promising, unaudited… whether raw GPR traces are downloadable was not
established"). This pass established it directly:

- The dataset page lists, and this pass confirmed by fetching the bitstream
  directly (not just its listing): **`GPR README`**, **`GPR AU parameter
  file`**, **`GPR AU raw data`** (2.59 MB), **`GPR VE parameter file`**,
  **`GPR VE raw data`** (2.85 MB, plus a second 5.70/5.18 MB pair).
- The README, fetched and quoted verbatim: *"GPR data recored at the Grimsel
  Test Site on 10.06.2015 as part of the In-situ stimulation and circulation
  experiment. Data were acquired using Malå GX160 HDR antennas, triggered by
  a trigger wheel. The two profiles were recorded in the AU and VE tunnels,
  looking towards the experimental volume… For each profile, the `.rad` file
  contains the parameters… and the `.rd3` and `.rd7` files are the Malå
  specific files with the raw data."*
- **`.rad`/`.rd3`/`.rd7` is exactly the format `converters/mala_converter.py`
  already reads**, exercised on two other held datasets (`hillside-lancaster`,
  `tu1208-ifsttar`). Ingesting this would need **no new converter code**.

## 5. Evidence: where the X/Y/Z ground truth comes from

The target is not a buried pipe but a mapped **shear zone (the S3 structure)**
inside the ISC experimental rock volume. Its geometry was established, per
the companion paper (fetched and read directly):

> *"Fractures were mapped along the boreholes using a combination of optical
> borehole televiewer images and core logs"* — geological mapping and
> structural characterisation independently published by Krietsch et al.
> (2018a); *"independent stress measurements [were] conducted separately by
> Krietsch et al. (2019)."* The GPR/seismic characterisation was then
> **compared against** this pre-existing geological model, and the authors
> report it needed only *"minor updates."*

This is the evidence chain the task's rule 11 demands: the fracture geometry
is attested by boreholes and cores, not read off the GPR image being
validated. It is the same structural pattern as TU1208 (an independently
surveyed target under a measured time axis) but in three dimensions rather
than a single depth number per pipe, and with boreholes precisely located at
a real engineered test facility rather than a soil trench.

**What is not yet established, and must not be assumed:**

- **Whether borehole/tunnel coordinates tie to a geographic CRS.** The
  fetched dataset page gives only the site's general lat/long
  (46.578°N, 8.319°E) as descriptive metadata, not per-borehole coordinates.
  Per-borehole positions live in a **separate, linked dataset**
  (`10.3929/ethz-b-000243199`, Krietsch et al. 2018b, cited in the paper's
  own data-availability statement) that this pass did not fetch. Grimsel is
  an engineered Swiss facility, so a national-grid tie almost certainly
  exists — but "almost certainly" is not evidence, and none is claimed here.
- **The along-profile position of each GPR trace.** The parameter file
  (`GPR AU parameter file`, 773 B) was not read in this pass; the README
  states trigger-wheel triggering (odometry), the same modality Subterra
  already models for `hillside-lancaster`.
- **Only two profiles were confirmed in this pass** (AU and VE tunnels, one
  acquisition day, 2015-06-10). The parent "Data collection for the Grimsel
  ISC experiment" record lists at least ten further linked sub-datasets,
  not individually opened here.

## 6. Score

Using the task's own rubric:

| Criterion | Points available | Awarded | Basis |
|---|---|---|---|
| X/Y ground truth | 25 | **10** | The target's lateral position is established (boreholes + tunnels, independently surveyed at an engineered facility) but this pass did not confirm a geographic/national-grid tie — only a general site coordinate |
| Z/depth ground truth | 25 | **20** | The fracture zone's 3D geometry is independently established by televiewer + core logs, explicitly cross-checked against, not derived from, the GPR — stronger evidence than TU1208's theodolite offsets, weaker than a direct depth number because it is a modelled surface fit to borehole intersections |
| Surface elevation / vertical reference | 10 | **0** | Not established in what was fetched; likely exists in the linked geological dataset, not confirmed |
| Acquisition coordinates | 10 | **5** | Along-profile odometry confirmed by format; borehole/tunnel absolute coordinates not confirmed in this pass |
| Raw data | 10 | **10** | Confirmed: `.rd3`/`.rad`/`.rd7`, a format Subterra already converts |
| Acquisition metadata | 5 | **4** | Antenna model, trigger method, acquisition date all confirmed from the README; full parameter file not read |
| Time axis metadata | 5 | **3** | Format implies a standard MALÅ time axis (as read for two other held datasets); not measured directly from this file in this pass |
| Original public source | 5 | **5** | ETH Zurich institutional repository, DOI-resolved, confirmed reachable |
| Clear documentation/license | 5 | **2** | Documentation is clear; the license is clear but **restrictive** (non-commercial), which is a real cost, not merely a formality |
| **Total** | **100** | **59** | |

**59/100 — below the 80 threshold for a primary Phase 9 benchmark**, honestly
scored rather than rounded up. It does not score below the 4TU/TU1208
partial candidates by accident: what it has (a genuine independent 3D
target) is real and new; what drags the score down (unconfirmed geographic
tie, unconfirmed elevation, a non-commercial licence) are gaps this pass
could not close from the outside and says so rather than assuming
favourably.

## 7. 4TU comparison

| Requirement | 4TU | Grimsel ISC (as confirmed this pass) |
|---|---|---|
| Raw GPR | ✅ SEG-Y, ingested | ✅ MALÅ `.rd3`, format already supported |
| X/Y trace coordinates | GNSS per trace, no EPSG declared | odometry per trace; borehole/tunnel absolute position not yet confirmed |
| Target X/Y ground truth | trench truth exists, **unregistered to any trace** | shear-zone geometry independently mapped; registration to the GPR profile is the paper's own subject, not a gap Subterra must close itself |
| Surface elevation | ✅ WGS84 ellipsoidal, `verified=False` | not confirmed in this pass |
| Target depth/Z | ✅ trench depths, 0.40–1.40 m typical | ✅ 3D shear-zone geometry from boreholes, independent of GPR |
| Time-zero | author confirms none applied | not confirmed in this pass |
| Velocity | declared permittivity only, no method | not confirmed in this pass |
| Physical 3D validation | **Blocked** — registration, t0, velocity all missing | **Not yet qualified** — the target and raw format are confirmed; the geodetic tie, t0 and velocity are not yet checked |

Grimsel does not unblock 4TU — nothing does; that was never in question.
What it offers 4TU does not: an independently mapped **three-dimensional**
target (a surface, not a point depth) that Subterra's existing converter
already reads without new code. What it lacks that this pass could not
supply from outside: confirmation that the same rigor extends to a
geographic coordinate tie, and clarity on whether Subterra's use case
(training/validating a product) falls inside "non-commercial."

## 8. Integration feasibility

If pursued past qualification:

1. **No new converter work.** `converters/mala_converter.py` already handles
   `.rd3`/`.rad`; `Preprocessing`, `SensorType` and the import pipeline need
   no changes to read the four raw-data files confirmed in this pass.
2. **Fetch and read the linked geological/borehole dataset**
   (`10.3929/ethz-b-000243199`) to establish whether borehole coordinates
   carry a national-grid (Swiss LV95) or geographic tie, and whether a
   vertical datum is declared.
3. **Read the `GPR AU`/`GPR VE` parameter files** (773–776 B each, already
   located) to confirm the time axis and trigger-wheel spacing the same way
   Subterra already measured for `hillside-lancaster`.
4. **Resolve the license question before any commercial use.** Email the
   listed contact (Doetsch, ETH Zurich) to ask whether Subterra's intended
   use falls under "non-commercial," exactly as the existing 4TU
   correspondence already does for a different question — this is the same
   kind of evidence-gathering step, not a purchase or a data-sharing
   agreement.
5. **Only two profiles exist in the specific bundle read here.** The parent
   collection lists ten-plus related parts; whether any of them add more
   GPR profiles (rather than seismic, stress, or hydraulic data) was not
   checked.

**None of this was done in this pass.** Per the task's explicit instruction,
this is dataset qualification, not implementation, and nothing above should
be read as already complete.

## 9. Remaining uncertainty

Before Grimsel — or anything else — could be called a qualified Phase 9
benchmark:

- Geographic/national-grid coordinate tie for the boreholes and tunnel
  antenna positions: **not confirmed**.
- Vertical datum / surface elevation reference: **not confirmed**.
- Whether Subterra's use (validating/training a commercial platform) is
  permitted under "non-commercial": **not confirmed** — requires asking, not
  assuming.
- The `GPR AU`/`VE` parameter file contents (time window, sample interval,
  trigger-wheel spacing): **not read** in this pass, only inferred from
  format family.
- Whether the ten-plus other parts of the parent ISC data collection contain
  additional GPR profiles beyond the two confirmed here: **not checked**.
- Whether a defensible propagation velocity for this specific crystalline
  rock volume exists in the companion paper (it very likely does, since the
  paper's subject is exactly this characterisation) — **not extracted** in
  this pass.

For the two already-held partial candidates, the uncertainty is much
smaller and was already resolved by prior stages: TU1208's target depths and
BAM's target depths are both already transcribed or transcribable, and both
are ready to run against **today**, with no external dependency.

## 10. Recommended next engineering task

**Not Phase 9 implementation**, per the task's explicit instruction, and not
a Grimsel integration either — the license and coordinate questions above are
not yet answered. In order of cost:

1. **Run Route A from the existing `cross-dataset-evidence-audit.md`**, which
   this search did not supersede: transcribe TU1208's theodolite-surveyed
   target geometry and acquisition-line offsets into a
   `benchmark/`-style truth file (`provenance_class:
   transcribed_from_publication`, the same pattern `bam_pk266_targets.json`
   already uses), then fit t0 and velocity per material against three or
   more surveyed depths and report the residuals. This is real,
   already-held evidence, zero new licensing risk, and it is the first time
   Subterra would test its own time→depth conversion against a number
   someone else surveyed.
2. **Fetch and read the Grimsel geological/borehole dataset**
   (`10.3929/ethz-b-000243199`) and the two GPR parameter files, to turn
   §9's open questions into answered ones. This is a research task, not an
   engineering one, and should produce an update to this document before any
   ingestion is attempted.
3. **Ask ETH Zurich (Doetsch) whether Subterra's use qualifies as
   non-commercial**, in parallel with the existing outstanding 4TU
   correspondence — the same kind of external evidence request, not a new
   process.

Do not begin Phase 9 3D reconstruction on the strength of this document.
Nothing here closes the localisation gate; it narrows where the next
evidence should come from.

---

## Roadmap language

Per the task's own instruction not to turn the gate green without
integration and validation evidence, `docs/roadmap.md`'s "Localisation /
X-Y-Z scoring" row now also records: **4TU localisation remains blocked; a
fallback candidate (Grimsel ISC) was identified and scored 59/100 — not yet
qualified — with TU1208 and BAM remaining the best already-held partial
(X+depth, non-geodetic) benchmarks.** No readiness state was changed.
