# External GPR benchmark acquisition: evidence and verdict

Investigation 2026-08-07/08. Every row below was checked against the primary
repository — repository APIs, ZIP central directories read over HTTP Range, and
for the acquired dataset the actual downloaded bytes. Search-engine snippets
and other models' descriptions were not accepted as evidence anywhere.

## Headline

**No open GPR dataset meeting the Tier A definition was found.**

The strongest is **BAM's concrete step specimens (`doi:10.7910/DVN/FCMUJQ`) —
Tier B**, and it is now **acquired, checksum-verified and adopted as the current
Subterra benchmark**. It falls short of Tier A on two points: the target
coordinates are real, numeric and published, but they live in a journal table
**and not in any machine-readable file in the repository**; and the **coincidence
of the scanner origin with the origin the targets are measured from is
corroborated, not declared**. It carries a licence better than required (CC0)
and a genuine negative-control specimen.

Two claims in the brief that prompted this investigation are **false as stated**
and are corrected in §2. A dedicated validation pass on the target-to-trace
association (§9) confirmed the association is **exact, with zero residual**, and
also found **two claims that do not reach "verified"** — the coordinate-frame
origin and the machine-readability of the target truth. Tier B therefore stands;
it is **not** upgraded to A.

## 1. Evidence table

| Dataset | Raw traces | Target GT | Target XYZ | Machine-readable GT | Trace coordinates | Shared coordinate frame | Licence | Commercial | Access | Size | Tier | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **BAM concrete step specimens** `10.7910/DVN/FCMUJQ` | **yes** — GSSI `.DZT` + CSV + `.npy` | **yes** — tendon ducts, polystyrene cuboids, plus an **empty control specimen** | **X + Z yes**, Y = full width; **in a journal table, not in the repo** | **no** — no DXF, STEP, CAD or target CSV exists in any archive | **yes** — `X/Y/Z-values.npy` and `.csv` in every archive | **same frame, no transform needed; origin coincidence corroborated but NOT declared** (§9) | **CC0 1.0** on the data files | **yes** | immediate, open, MD5 published | 2.54 GB (3 zips) | **B** | Dataverse API; ZIP central directories; **downloaded and MD5-verified** |
| **TU1208 / IFSTTAR** `10.5281/zenodo.1211173` | yes — DZT/RD3/ASCII, already on disk | site has known targets, but **no target file ships** | no | no | no | n/a | CC-BY-4.0 | yes | open | 200.7 MB | **C** | local archive listing — see §3 |
| **4TU Dutch utilities** `10.4121/96303227-…` | yes — SEG-Y ×759 | trench records exist | **withheld** — "geospatial information has been omitted to preserve … confidentiality" | no | yes (RTK, per trace) | n/a | CC0-1.0 | yes | open | 402.6 MB | **C** | article + local corpus, already characterised |
| **Stadler et al. landmine/IED** `10.5281/zenodo.8276600` | yes — ReflexW `.DAT`/`.PAR` | **yes, by type** — canister, grenade shell, mortar shell, metal plate, pressure plate, in 3 soils | type yes; **depth only for the SIMULATED profiles** (in filenames); measured profiles carry none | partial — `ground_objects.py` holds the gprMax target models | **no** | n/a | CC-BY-4.0 | yes | open | 76 MB | **C** | downloaded and extracted — see §4 |
| **CMU-GPR** `rpl-cmu` | yes (CSV) | **none** — GT is the robot's pose | no | no | local total-station only | n/a | CC-BY-NC-SA | **no** | open | 15.5 GB | **D** | [previous assessment](cmugpr-acquisition-assessment.md) |
| **Branco "GPR Dataset"** `10.5281/zenodo.13144711` | **no** — B-scan images | image-space hyperbola boxes | no | YOLO/CVAT boxes, but in **pixels** | no | n/a | metadata says CC-BY-4.0 | — | **restricted — access request required, file list empty via API** | undisclosed | **E** | Zenodo API — see §2 |
| **Morocco utilities/voids** `ww7fd9t325` | no — 2,239 JPEGs | image annotations | no | YOLO/VOC, pixels | no | n/a | CC-BY-NC | no | open | small | **E** | Mendeley + article |
| **MERL-GPR** `10.5281/zenodo.8145084` | synthetic (gprMax) | synthetic | synthetic | yes | n/a | n/a | CC-BY-SA-4.0 | yes | open | 1.6 GB | **E** | Zenodo API |
| **MCG GPR** `10.5281/zenodo.14270869` | no — cropped PNGs | segmentation masks | no | pixels | no | n/a | CC-BY-4.0 | yes | open | 1.4 GB | **E** | Zenodo API |

`TARGET_GROUND_TRUTH` — the identity, geometry, position and depth of a thing
in the ground — exists only in the BAM row (and by type in Stadler).
`SENSOR_PLATFORM_GROUND_TRUTH` — where the instrument was — is what CMU-GPR
offers and what 4TU's RTK offers. **They are not interchangeable, and no row
above was promoted on the strength of platform pose.**

## 2. Claims in the brief, adjudicated

| Claim | Verdict |
|---|---|
| 2026 dataset Dataverse DOI is `10.7910/DVN/FCMUJQ` | **True.** Released 2026-04-22; Crossref records it as `is-supplemented-by` of `10.1016/j.dib.2026.113103` |
| "raw pulse-echo GPR signals" | **True.** Native GSSI `.DZT` ×4 per specimen, plus per-line CSV and 3-D `.npy` |
| "scanner coordinates" | **True.** `X-values`, `Y-values`, `Z-values` as both `.npy` and `.csv` |
| "embedded-object geometry" | **Only as prose.** In the Dataverse description and the articles. **No geometry file exists** |
| "DXF/STEP geometry" | **FALSE — absent.** All 667 files in each archive (674 entries including directories) are radar data or coordinate vectors |
| "CSV/structured target coordinates" | **FALSE — absent** |
| "trace-to-target mapping" | **FALSE — absent.** It is *computable* (same frame) but is not shipped |
| "CC-BY 4.0" | **FALSE — it is CC0 1.0**, which is strictly more permissive |
| Some investigations called it Tier A | **Not supported.** Downgraded to **B** on the machine-readable criterion |
| Branco raw data downloadable? | **No.** `access_right: "restricted"`; the API returns an **empty file list**. Contents are B-scan *images* with pixel-space YOLO/CVAT annotations, not raw traces. **Tier E** |
| TU1208 target coordinates | **Not in the archive** — and the reason is more specific than "absent"; see §3 |

## 3. TU1208: the missing spreadsheet

The Zenodo supplementary archive is already on disk. Its listing contains a
file named:

```
Database_2018/.~lock.List_Database_V1.ods#
```

That is a **LibreOffice lock file** for `List_Database_V1.ods` — and
`List_Database_V1.ods` **is not in the archive**. The spreadsheet that would
list the database was open on someone's desktop when the archive was built; the
lock file was captured and the spreadsheet itself was not.

This is a packaging omission, not a confidentiality decision. It makes the
author request concrete and small: **ask for `List_Database_V1.ods`**, rather
than asking open-endedly for "target coordinates". Whether that file carries
target positions is unknown until it is seen — it may only be an index of
radargrams. TU1208 stays **Tier C** until it is.

## 4. Stadler et al.: measured, but position-free

Downloaded (76 MB) and extracted. It is the only other candidate with genuinely
emplaced targets: five target types across three soils, 400 MHz, with a README
naming each. But:

- The bulk is **simulated** (`NEW_PROFILES_*`, gprMax). Only ~11 profiles are
  measured (`WTD_*`, from a German military test facility).
- Depth appears in the **simulated** filenames (`PLUS_0CM`, `PLUS_7CM`,
  `PLUS_16CM`). The **measured** files are numbered (`WTD_SEPT_2021__092`) and
  carry **no depth and no position**.
- No trace coordinates at all.
- Format is **ReflexW `.DAT` + binary `.PAR`** — a fourth vendor format, with
  the parameter file not being ASCII.

Target identity without target position is not scoreable. **Tier C.** It would
become B if the article maps `WTD_*` file numbers to target depths.

## 5. Search performed

Zenodo REST API (6 query formulations, 75 distinct dataset records reviewed by
licence, access right and file extension), DataCite REST API (52 hits),
Harvard Dataverse API, Mendeley Data, Europe PMC, Crossref, GitHub, and the
twelve datasets in the [earlier survey](dataset-benchmark-plan.md). Additional
searching after the BAM verdict did not surface a Tier A candidate.

**The conclusion of the earlier survey still stands, now on wider evidence:**
the best excavated truth withholds location, the best-positioned data has
interpretation rather than truth, and the datasets that publish target geometry
publish it in prose and drawings. *No open dataset ships machine-readable
target coordinates alongside raw traces.*

## 6. What was acquired, and verified

`datasets/raw/bam_concrete/` — **1.76 GB of the 2.54 GB record.**

| file | bytes | MD5 vs published | files |
|---|---|---|---|
| `Pk266_Dataset.zip` | 888,611,774 | **match** | 667 |
| `Pk050_Dataset.zip` | 869,357,088 | **match** | 667 |

`Pk401_Dataset.zip` (782.2 MB) was **deliberately not taken**: its cuboid X/Y
exist only in drawings, so its target truth cannot be transcribed without
digitising, and a digitised coordinate is an estimate, not a published value.

Provenance is at `datasets/raw/bam_concrete/PROVENANCE.json` — source URLs,
both DOIs, licence *and where the licence statement was read*, retrieval
method and timestamp, per-file MD5 (published and recomputed), SHA-256, and all
1,334 members with CRC32. **Raw data is not committed**; `datasets/` is
gitignored, as for every other corpus.

### What the files actually contain — read, not assumed

Per specimen: 4 × `.DZT`, 656 × `.csv`, 4 × 3-D `.npy`, plus coordinate vectors
in both `.npy` and `.csv`.

```
X-values.npy   int64    401 values   0 → 2000 mm   step 5 mm    uniform
Y-values.npy   int64    161 values   0 →  800 mm   step 5 mm    uniform
Z-values.npy   float64  512 values   0 →   15 ns   step 0.029354207 ns  uniform
```

**This is the finding that decides the tier.** The scanner grid is expressed in
the same specimen frame as the published target X (250 / 750 / 1250 / 1750 mm).
Target X = 250 mm is grid index 50 exactly. Trace-to-target association is
therefore **directly computable, with no transformation and nothing fabricated**
— which is what no other dataset offers. §9 validates this in detail and states
precisely which parts of it are read from the files and which are not.

Subterra's existing GSSI reader opens the `.DZT` unmodified:
`n_samples 512`, `range_ns 15.0`, `bits 16`, `epsr 5.5` — all agreeing with the
publisher's description. **No new converter is required for the DZT.**

Three things found in the files that the description does not mention, recorded
because they will matter:

1. **The DZT header's antenna name says `2.6GHz` in a file named
   `..._1_5_GHz_...`.** Header and filename disagree. Not resolved here.
2. **`scans_per_metre` is 1.0 and `metres_per_mark` is 0.0** in the DZT. The
   DZT's own along-track scaling is *not* the 5 mm grid — the coordinate
   vectors are authoritative, the DZT header is not.
3. **The DZT holds 152,222 traces; the grid is 401 × 161 = 64,561.** They are
   not 1:1. The DZT is the raw instrument stream; the **CSV/NPY products are
   the coordinate-registered ones**, and any benchmark must be built on those
   unless a documented DZT→grid mapping turns up.

## 7. Target truth, transcribed

`benchmark/bam_pk266_targets.json`, marked `provenance_class:
transcribed_from_publication` — **typed in by hand from publications, read from
no file in the repository.**

Pk266: four tendon ducts, inner Ø 60 mm / outer Ø 67 mm, axes parallel to Y
spanning the full 800 mm width, at X = 250 / 750 / 1250 / 1750 mm, centre
depths 274.5 / 214.6 / 151.4 / 94.4 mm below the measuring surface.

X and the concrete-cover depths come from Table 4 of the **ultrasound** Data in
Brief paper on the *same physical specimens*
([PMC10294002](https://pmc.ncbi.nlm.nih.gov/articles/PMC10294002/), CC BY 4.0);
centre depths come from the Dataverse record itself.

**One discrepancy is recorded rather than smoothed over.** Centre depth minus
published cover is exactly 30.0 mm for all four ducts — the *inner* radius. Had
cover been measured to the outer surface facing the antenna it would be 33.5 mm.
The two sources therefore use different reference surfaces, and which one Table 4
means is not settled by anything read. The centre depths are treated as primary
(same institution as the radar data); the cover values are kept verbatim beside
them; **neither was adjusted to fit the other.** A 3.5 mm ambiguity is trivial
for detection and decisive for millimetre localisation scoring, so it is logged
as an open question with author contact as the resolution route. The companion
article's full text could not be retrieved — Elsevier returns HTTP 403 and it is
not yet in Europe PMC.

### The negative control

**Pk050 contains no embedded elements**, stated positively by the fabricator.
That is *attested absence*, not a blank field — the distinction the 4TU
characterisation had to make when it recorded that no activity there could serve
as a negative control, and that a false-alarm rate was therefore not measurable.

With Pk050, **a false-alarm rate becomes measurable for the first time.** One
caveat is written into the file: Pk050 is not featureless. Its step back walls
are real reflectors and any detector will respond to them. It is a control for
*embedded objects*, not for *no reflector*.

## 8. What this does and does not unblock

**Now genuinely possible, for the first time:**

- Detection scoring against attested targets, with a measurable false-alarm rate.
- Localisation scoring in X and depth, against published numeric positions.
- Association of a candidate to a named target, in a shared frame, computed
  rather than assumed.

**Still not possible, and not to be claimed:**

- **This is concrete NDT, not soil geophysics.** Targets are in 2 m lab
  specimens on an automated scanner. It exercises nothing geographic: no CRS,
  no georeferencing, no cross-CRS fusion, no map view, no soil clutter, and no
  utility-scale geometry. Detector performance here **does not transfer** to the
  4TU utility corpus, and must never be reported as if it did.
- Vertical registration remains unresolved. Depth here is measured from a
  physical surface, which is why it needs no datum — and why it says nothing
  about the AHN/GPR question.
- No repeat surveys, no temporal tracking.
- Y localisation is untestable: the ducts span the full width, so every Y is
  on-target.

## 9. Association validation pass

Run by `scripts/verify_bam_association.py` against the acquired archives. Every
claim below carries **how it is known**, and nothing was promoted to verified
because a paper says it.

| tag | meaning |
|---|---|
| **VERIFIED FROM FILES** | read out of the acquired bytes |
| **VERIFIED FROM REPOSITORY METADATA** | read from Dataverse's structured metadata, the legal authority for the data files — not inside the archives, but not prose either |
| **INFERRED FROM DOCUMENTATION** | stated by the publisher or an article, not contradicted by the files, not readable from them |
| **NOT AVAILABLE** | neither |

### The ten checks

| # | Question | Finding | Status |
|---|---|---|---|
| 1 | Why nodes 50/150/250/350? | `X-values.npy` is 401 values, `0 → 2000`, uniform step `5.0`. `node = x / 5`, remainder **zero** for all four targets | **VERIFIED FROM FILES** |
| 2 | Units of those coordinates | **mm** (X/Y) and **ns** (Z) | **INFERRED FROM DOCUMENTATION** — see below |
| 3 | Same frame and origin? | Scanner spans 0–2000; targets are measured from a drawing origin | **INFERRED** — see the blocker below |
| 4 | Exact or nearest-neighbour? | **Exact**, residual **0.000 mm** on all four, plus a computed 13-node footprint | **VERIFIED FROM FILES** |
| 5 | Which target at which node | table below | **VERIFIED FROM FILES** (arithmetic) |
| 6 | Is depth independent of GPR? | **Yes** — specimen construction, no travel time, no velocity | **INFERRED FROM DOCUMENTATION** |
| 7 | Machine-readable geometry? | A scan for `.dxf/.step/.stl/.dwg/.json/.xml/.txt/.pdf` in the archive returns **the empty list** | **NOT AVAILABLE** |
| 8 | Control present in the data? | Pk050 downloaded: 4 DZT, 656 CSV, 7 NPY, **identical grid vectors** to Pk266 | **VERIFIED FROM FILES** |
| 9 | Licence and permitted use | **CC0 1.0** — commercial, derivatives, model training, redistribution, no attribution condition | **VERIFIED FROM REPOSITORY METADATA** |
| 10 | Originals unchanged + manifest | Both MD5s still match; SHA-256 recorded; 1,334 members with CRC32 | **VERIFIED FROM FILES** |

### Target-to-node association

| node | target | type | X | centre depth | footprint (67 mm OD) | residual |
|---|---|---|---|---|---|---|
| **50** | `Pk266-duct-1` | tendon duct | 250 mm | 274.5 mm | nodes 44–56 (13) | 0.000 mm |
| **150** | `Pk266-duct-2` | tendon duct | 750 mm | 214.6 mm | nodes 144–156 (13) | 0.000 mm |
| **250** | `Pk266-duct-3` | tendon duct | 1250 mm | 151.4 mm | nodes 244–256 (13) | 0.000 mm |
| **350** | `Pk266-duct-4` | tendon duct | 1750 mm | 94.4 mm | nodes 344–356 (13) | 0.000 mm |

This is **exact coincidence, not nearest-neighbour matching**: the target centre
falls *on* a grid node with zero residual, and the duct's outer diameter gives a
deterministic 13-node footprint around it. Because the ducts run parallel to Y
across the full width, **every one of the 161 CSV lines crosses all four ducts**,
so each line yields four known target crossings at fixed trace indices.

Supporting checks that also passed: the X/Y/Z vectors are **byte-identical
between Pk266 and Pk050** (the control sits on the same grid), and the `.npy`
and `.csv` copies of each vector agree.

### Three things that did NOT reach "verified", and what they cost

**1 · The units are documentation, not data.** A NumPy integer array carries no
unit and **no file in either archive declares one**. "mm" and "ns" come from the
Dataverse description. Nanoseconds are *corroborated from an independent file* —
the DZT header gives `range_ns = 15.0` and `n_samples = 512`, matching the Z
vector exactly. **Millimetres have no such corroboration.**

**2 · The origin coincidence is unproven.** The archives contain no drawing, no
origin marker and no statement of where X = 0 sits on the specimen. The target X
values are measured from an origin the geometry article places with "a circle
containing a cross" in an appendix drawing. That the two origins are the same
physical corner is strongly corroborated — both run 0–2000 over a specimen
documented as 2000 mm long, and all four targets land on exact multiples of the
5 mm step, which a shifted origin would generally break — **but corroboration is
not a declaration.**

*Consequence, stated precisely:* **detection scoring and the false-alarm rate are
unaffected**, because they do not depend on the absolute origin. **Localisation
scoring inherits an unquantified origin offset** and must not be reported as
millimetre-accurate until the origin is confirmed.

**3 · The depth reference surface is still ambiguous by 3.5 mm** — the
cover-vs-centre discrepancy of §7, unchanged by this pass.

### Verdict: **Tier B stands. This is NOT Tier A.**

Against the stop condition — licence, Z/depth, coordinate frame,
target ground truth — the licence is fully resolved and the depth is confirmed
independent of GPR, but **two blockers remain**:

- **Coordinate frame:** origin coincidence is corroborated, not declared.
- **Target ground truth:** exists and is numeric, but is **not machine-readable
  at source**; Subterra's copy is a hand transcription, and that is what the
  Tier A definition excludes.

Both resolve the same way: **author contact with BAM**, asking for the appendix
drawings or a coordinate file, and for the reference surface used in Table 4.
That is now the third open author request, alongside TU1208's
`List_Database_V1.ods` and the 4TU vertical datum.

**It is nonetheless adopted as the current Subterra benchmark** — it is the only
dataset held with target ground truth at all, and its limitations are bounded
and written down. What it can support today is detection scoring and a
false-alarm rate; what it cannot yet support is millimetre localisation scoring.

## 10. Detection scoring is now implemented

The ingestion path and detection/false-alarm scoring were built on top of this
acquisition — see **[`bam-benchmark-detection.md`](bam-benchmark-detection.md)**
for the pipeline, the matching rule and the measured results.

Headline: over all 161 lines, the existing detector reaches **recall 0.065 /
precision 0.135 (1.5 GHz)** and **recall 0.093 / precision 0.147 (2.6 GHz)**,
and fires **2.79 / 1.70 times per line** on the attested-empty control. That is
a poor result, consistent with the previously measured width saturation of the
ring z-score, and **no threshold was changed in response to it**.

Localisation scoring is blocked in code, for the reason recorded in §9.

## 11. Status of each candidate

| Dataset | Tier | Status |
|---|---|---|
| BAM concrete | **B** | **acquired, verified, target truth transcribed** |
| TU1208 | C | on disk; author request narrowed to one named file |
| 4TU | C | characterised; target coordinates withheld at source |
| Stadler | C | inspected; not acquired into the corpus |
| CMU-GPR | D | not acquired; NC licence unresolved |
| Branco | E | restricted; images only |
| Morocco / MERL / MCG | E | ruled out |
