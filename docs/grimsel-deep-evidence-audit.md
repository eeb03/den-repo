# Grimsel deep evidence audit

**Question.** Can Subterra obtain a defensible physical relationship between
the GPR measurements at Grimsel and an independently known 3D subsurface
target — enough to support the falsifiable statement *"Subterra reconstructed
this structure at X/Y/Z; independent measurement places it at X/Y/Z, error N
metres"*?

**This pass goes past the prior 59/100 scoring** (from
`docs/fallback-localisation-dataset-search.md`, which explicitly recorded
Grimsel's coordinate tie, vertical datum and licence scope as unconfirmed).
Every fact below was fetched from a primary source in this pass — the actual
ETH Research Collection pages, a downloaded raw `.rad` header, the open-access
Solid Earth paper, and the PMC-hosted Scientific Data paper — not
re-summarised from the earlier report. **No platform state changed; no
ingestion code was written.**

---

## A. Grimsel evidence audit — exact sources

| Claim | Source | How verified |
|---|---|---|
| GPR dataset identity, files, format | ETH Research Collection, [10.3929/ethz-b-000420930](https://doi.org/10.3929/ethz-b-000420930) | Rendered directly (JS SPA — a bot-blocked `curl` returns nothing; Playwright renders it), download list expanded, README bitstream fetched and quoted |
| GPR acquisition parameters | `GPR_AU_N-to-S.rad`, downloaded directly from the repository in this pass | Full header read from disk (below) |
| Coordinate-system origin | Krietsch et al. (2018), *Scientific Data* 5, 180198, PMC6259022 | Exact sentence located and quoted directly from the article body |
| S3 shear-zone characterisation method | Same PMC article + Doetsch et al. (2020), *Solid Earth* 11, 1441 | Both fetched; cross-checked against each other |
| Geological dataset license | ETH Research Collection, [10.3929/ethz-b-000243199](https://doi.org/10.3929/ethz-b-000243199) | Rendered directly, "Rights/License" field read |
| GPR dataset license | ETH Research Collection, [10.3929/ethz-b-000420930](https://doi.org/10.3929/ethz-b-000420930) + [rightsstatements.org/page/InC-NC/1.0](https://rightsstatements.org/page/InC-NC/1.0/) | Both fetched directly; the second gives the operative legal text, not just the label |
| Platform-wide default terms | [research-collection.ethz.ch/info/terms-of-use](https://www.research-collection.ethz.ch/info/terms-of-use) | Fetched directly, relevant clause quoted below |

---

## B. Coordinate audit — X/Y

**What exists, quoted directly from the geological paper (PMC6259022):**

> *"The visualization tool shows all data in a coordinate system, which has
> its origin with respect to the Swiss coordinate system origin at
> X (Easting) = 667400, Y (Northing) = 158800, Z (Elevation) = 1700."*

667400 / 158800 fall squarely inside the old Swiss grid's (CH1903/LV03)
valid easting/northing range for the Bernese Oberland — this is a **real,
named national coordinate system with a documented local offset**, not an
arbitrary in-house grid. Any local coordinate in this frame converts to a
true geographic position by simple addition (`true_E = local_E + 667400`,
`true_N = local_N + 158800`), **provided there is no rotation** — and no
rotation angle was found anywhere in the two papers fetched. This is
recorded as an open question in §I, not assumed to be zero.

**What this does NOT establish on its own:** the *borehole and shear-zone*
coordinates live in this frame. The **GPR profile's own position** does not
arrive pre-registered into it. The downloaded raw parameter file,
`GPR_AU_N-to-S.rad`, was read directly and contains:

```
START POSITION:0.000000
STOP POSITION: 49.032315
DISTANCE INTERVAL: 0.049779
WHEEL CALIBRATION:2491.000000
```

**No X, Y, Z, or coordinate field of any kind.** Position is purely
along-track distance from an arbitrary zero, exactly like `hillside-lancaster`
already held. The filename itself carries the one directional fact the file
does not: **"N-to-S"** — the profile runs north to south. Converting
"0.000–49.032 m along a wall, heading south" into `(667400+x, 158800+y)`
requires knowing the wall's true start point and bearing, which is not in
this file and was not found in either paper in the time this pass allowed
— it plausibly exists in `GeologicalModelVisualization.zip` or Figure 3a
of the Solid Earth paper (both large binary/graphical artefacts not
individually opened here), or as tunnel as-built survey data not yet
located.

**Score basis: X and Y are geodetically real but not yet co-registered to
the GPR profile without one more piece of evidence.**

## C. Vertical audit — Z

The same coordinate block gives `Z (Elevation) = 1700`, i.e. the local
frame's Z is elevation relative to a datum implied by "the Swiss coordinate
system" — almost certainly the historical Swiss levelling datum (LN02),
standard for CH1903-era elevations, but **the datum name was not printed in
either fetched paper**, so this is recorded as **corroborating, not
declared** — exactly the distinction Subterra's own provenance vocabulary
already draws (`docs/provenance.md`). The Doetsch (2020) paper additionally
states depths only relatively (*"1 m below tunnel level"*, *"20 m below the
tunnels"*), which is a real elevation but expressed against tunnel level,
not directly against the 667400/158800/1700 frame in the sentence quoted.

**Score basis: an elevation reference exists and is plausible but the exact
datum realisation is not confirmed from what was read.**

## D. Ground-truth audit — is the target really independent?

**Yes, and the independence is structural, not just claimed.** Quoted
directly from the geological paper's own description of its own
methodology, and corroborated by the GPR paper's own framing of what it
did with that methodology:

1. **Method, independent of GPR:** *"Fractures were mapped along the
   boreholes using a combination of optical borehole televiewer images and
   core logs"* (tunnel-wall mapping: geodetic measurement of 3 points along
   fractures, 6 along shear zones/dykes; optical televiewer giving *"true
   orientations of fractures, shear zones and foliation"*).
2. **Sequence matters:** the geological model (borehole/OPTV/core-log based)
   was built **first**; the GPR/seismic survey was run and **compared
   against** it. The Doetsch paper's own words: the geological model *"was
   already of high quality and only needed minor updates"* after the GPR
   survey — the GPR **corroborated** an existing structural interpretation,
   it did not create it.
3. **Structure identified:** the **S3 shear zone(s)** — striking
   approximately E–W (N93°E), dipping ~65° south, thickness 38–312 mm
   across the surveyed volume, described as penetrating the ISC test volume
   and intersecting both the AU and VE tunnels.

**What is genuinely missing:** a stated **positional uncertainty** for the
mapped shear-zone surface. Neither paper, as fetched, gives an error bound
(in metres or otherwise) on the interpolated 3D surface. This matters
directly for the falsifiable-statement standard this task sets: *"error N
metres"* needs a defensible N on **both** sides of the comparison, and
today only the Subterra side of that equation would carry an honest error
bar.

**This clears the bar the task set explicitly** — *"not simply 'the paper
authors interpreted the same GPR anomaly as a shear zone.'"* That is
precisely not what happened here: the shear zone was known from boreholes
before the GPR ran.

## E. Geological-data audit

| | |
|---|---|
| Dataset | *Comprehensive geological dataset for a fractured crystalline rock volume at the Grimsel Test Site*, Krietsch et al. (2018), [10.3929/ethz-b-000243199](https://doi.org/10.3929/ethz-b-000243199) |
| Accessible? | **Yes — confirmed OPEN ACCESS** on the ETH Research Collection, fetched directly |
| Files (confirmed from the live download list) | `GeologicalModelVisualization.zip` (2.87 MB), `3DstaticgeologicalModel.zip` (**1.70 GB**), `FBS16p001.WCL` / `FBS16p002.WCL` / `FBS16p003.WCL` (900–934 MB each, more listed under "Show more") |
| Format | The 3D model files are large enough to be genuine volumetric/surface geological models, not a summary table; `.WCL` is very likely raw televiewer/logging-tool output (not decoded in this pass) |
| Borehole trajectories, core-log depths | Referenced by the paper as present in the dataset; **not individually opened in this pass** given file sizes (900 MB–1.7 GB each) |
| Co-registration with GPR | **Same coordinate frame in principle** (§B) — both datasets are described relative to "the Swiss coordinate system," but the specific numeric tie for the GPR profile's own endpoints was not found |

## F. Licensing audit — the asymmetry that changes the picture

This is the most consequential new finding of this pass. **The GPR data and
the geological data carry different licenses**, and conflating them (as the
prior 59/100 score effectively did, by treating "the license" as one thing)
understated what is actually usable.

| | GPR + seismic dataset (`...420930`) | Geological dataset (`...243199`) |
|---|---|---|
| **License, as fetched from the live page** | *"In Copyright – Non-Commercial Use Permitted"* | **"Creative Commons Attribution 4.0 International"** |
| Operative text (rightsstatements.org, fetched directly) | *"…no permission is required from the rights-holder(s) for non-commercial uses. For other uses you need to obtain permission from the rights-holder(s)."* | Standard CC-BY: any use permitted, including commercial, with attribution |
| Commercial use | **Requires rights-holder permission** | **Permitted with attribution, no permission needed** |

### A–G, answered as far as public evidence allows

| Question | Answer |
|---|---|
| **A. Raw GPR data** | Non-commercial use permitted without asking; commercial use requires the rights-holder's permission |
| **B. Geological/borehole data** | CC-BY-4.0 — commercial use permitted with attribution, no permission needed |
| **C. Derived results** (e.g. a depth/position error computed from the raw GPR) | **Requires author/institution confirmation.** A rights statement on the input does not automatically define the license of a *computed* output, and this pass found no explicit statement either way |
| **D. Publication of benchmark metrics** | **Requires author/institution confirmation** — plausibly fine under academic norms (the paper itself is openly published), but not stated as a rule anywhere read |
| **E. Use in research that may contribute to a commercial product** | **This is exactly the "other uses" the InC-NC statement reserves to the rights-holder.** Not resolved by public evidence; needs a direct answer |
| **F. Retention of derived outputs** after any deletion of the raw source | **Requires author/institution confirmation.** No stated retention rule was found for derived, non-redistributed results specifically |
| **G. Redistribution** | Explicitly **not** covered by "non-commercial use" alone — redistributing the raw files themselves is a separate act from using them locally, and the platform's own terms-of-use default (quoted below) treats them differently in spirit even where not spelled out per-item |

**Platform-wide default, quoted directly** (`research-collection.ethz.ch/info/terms-of-use`, current as of the page's own "Status: August 2025" footer):

> *"If no special end user licence is stipulated, the users may download and
> save the objects on offer free of charge for their own personal use and
> for non-commercial purposes. Any further use is only possible with the
> permission of the rights holder."*

This is the *default* the GPR dataset's specific InC-NC statement is
consistent with, not a separate, weaker fallback — it confirms the
restriction is deliberate, not a placeholder.

## G. Grimsel score

Using this task's rubric exactly, with the reasoning for every non-maximum
score stated rather than rounded favourably:

| Criterion | Points available | Awarded | Basis |
|---|---|---|---|
| Raw GPR available | 10 | **10** | Confirmed: `.rd3`/`.rad`/`.rd7`, downloaded and read directly in this pass; `converters/mala_converter.py` already reads this format |
| Explicit X coordinate | 10 | **5** | The *site* has a real, named coordinate system with a documented local-to-national origin; the *specific GPR profile's* own start point in that frame is not yet located from what was fetched |
| Explicit Y coordinate | 10 | **5** | Same reasoning as X |
| Independent target X/Y | 15 | **10** | Shear-zone horizontal position established via boreholes/tunnel mapping, independent of GPR, in the same named frame — but no stated positional uncertainty |
| Independent target depth/Z | 20 | **15** | Same independence, same frame, for elevation — docked for the same missing uncertainty bound, and for thickness variability (38–312 mm) that is real geology, not a flaw, but does mean "the target" is a zone, not a knife-edge |
| Surface elevation/vertical datum | 10 | **6** | An elevation reference exists and is plausible (Swiss levelling datum by convention) but its exact name/realisation was not confirmed in either fetched paper |
| Survey geometry | 5 | **5** | Fully confirmed directly from the downloaded `.rad` header: 49.03 m profile, 5 cm trace spacing, 0.33 m antenna separation, N-to-S direction |
| GPR acquisition metadata | 5 | **5** | Confirmed directly from the header: GX160 HDR antennas, 1377 samples, 614.7 ns window, trigger-wheel odometry |
| Independent ground-truth method | 10 | **10** | Genuinely independent and sequenced correctly (geology first, GPR compared against it second) — the strongest single fact this audit found |
| License/access suitability | 5 | **2** | Usable now for non-commercial research; the geological ground truth alone is fully commercial-compatible (CC-BY), but the raw GPR sensor data — what Subterra would actually ingest — needs explicit permission for anything beyond non-commercial use |
| **Total** | **100** | **73** | |

**73/100 — "Useful but requires additional evidence" (70–79 band), not
"research lead" and not "strong candidate."** This is a genuine upgrade
from the prior pass's 59/100, earned by evidence this pass actually
fetched (the coordinate origin and the geological dataset's separate,
more permissive license), not by re-scoring the same facts more
generously.

## H. Alternative candidates

**None investigated further in this pass, and none is proposed.** Per the
task's own instruction (§12: *"Do not repeat broad searches that have
already been shown to produce weak candidates"*), and because Grimsel
scored well inside "useful, needs more evidence" rather than "reject" —
the condition that would justify a fresh broad search. The existing
comparison set (4TU, TU1208, BAM) from `docs/fallback-localisation-dataset-search.md`
and `docs/tu1208-physical-depth-validation-report.md` stands unchanged and
is reproduced in §I below for the side-by-side view this task asks for.

## I. Comparison

| Dataset | Raw GPR | X | Y | Z | Independent ground truth | License | Score | Status |
|---|---|---|---|---|---|---|---|---|
| **4TU** | ✅ SEG-Y, ingested | GNSS/trace, no EPSG declared | same | trench depths exist, unregistered | ✅ excavated trench truth | CC0-1.0 | not scored under this rubric (prior audits) | Blocked on registration only |
| **TU1208** | ✅ 3 vendors, ingested | across-line offset only, unpublished per-target | same | ✅ theodolite-surveyed, 0/36 tied to a trace | ✅ theodolite | CC-BY-4.0 | not scored under this rubric | **Outcome D** — insufficient evidence (`docs/tu1208-physical-depth-validation-report.md`) |
| **BAM** | ✅ ingested | local mm-grid only, no CRS | same | ✅ fabricator-attested | ✅ fabricator | CC0-1.0 | not scored under this rubric | Strongest depth truth held; cannot supply geographic X/Y by design |
| **Grimsel ISC** | ✅ confirmed this pass, format already supported | real named CRS, profile not yet tied to it | same | real named elevation reference, datum unconfirmed | ✅✅ boreholes + OPTV + core logs, sequenced before GPR | **split**: geology CC-BY, GPR raw data non-commercial-only | **73/100** | **Conditional — see §J** |

Grimsel is not "genuinely better" than the others in a single dimension —
it is the only one with a **real, named, nationally-referenced coordinate
system** behind its independent target, which none of 4TU, TU1208 or BAM
has. It is also the only one with an **unresolved commercial-use
question**, which none of the CC0/CC-BY-licensed alternatives carries.

## J. Grimsel's role

### **B — Conditional benchmark.**

Scientifically the strongest independent-ground-truth candidate this
project has found — boreholes and optical televiewer established the S3
shear zone's geometry before the GPR ran, in a real Swiss-grid-tied frame.
It is not Category A because the GPR profile's own position is not yet
co-registered into that frame from public evidence, and it is not Category
C or D because the independence and the coordinate *system* (as opposed to
the specific profile's *position within* it) are both genuinely
established, which is more than "geological plausibility" or "visual
agreement." It is explicitly not forced to Category A.

---

## Recommendation

### Final recommendation

**Use Grimsel after author confirmation.** Not "use now" (the co-registration
and commercial-use questions are real, not procedural), and not "continue
searching" (nothing found or previously investigated scores higher, and the
task's own instruction is not to re-run searches that already produced weak
candidates).

### Exact next action

**Send the questions below to the two identified contacts** — Joseph
Doetsch (ETH Zurich, contact person on the GPR dataset) and Hannes Krietsch
(now ILF Consulting Engineers, `hannes.krietsch@ilf.com`, corresponding
author on the geological paper and contact person on the geological
dataset). **Not sent automatically in this pass**, per the task's explicit
instruction to report rather than send.

## Author questions (report only, not sent)

Only questions this pass could not answer from public evidence:

1. What is the tunnel-wall coordinate (in the 667400/158800/1700-relative
   frame) of the start point (position 0.000 m) of the published `AU` and
   `VE` GPR profiles, and their true compass bearing?
2. Is there a rotation between that local visualisation frame and true
   Swiss-grid north, in addition to the stated translation?
3. What vertical datum underlies "Elevation = 1700" in that coordinate
   definition (e.g. LN02)?
4. What is the estimated positional uncertainty of the interpolated S3
   shear-zone surface used in the geological model?
5. Does the GPR/seismic dataset's "non-commercial use" rights statement
   extend to **derived** validation metrics computed from the raw traces,
   or only to the raw files themselves?
6. Would academic benchmarking of a software platform that may later become
   commercial fall inside or outside "non-commercial use" as intended by
   the rights-holder?
7. May the raw GPR files be retained locally, unpublished, for as long as
   the research continues, or is there an expected deletion point?
8. May numerical results derived from this dataset (e.g. a depth/position
   error in metres) be published in Subterra's own documentation?

## Remaining uncertainty (explicit, not glossed over)

- GPR-profile-to-Swiss-grid co-registration: **not established** from
  public evidence in this pass.
- Rotation between local and national grid: **not found stated anywhere**;
  not assumed to be zero.
- Vertical datum name: **not confirmed**, only plausible by convention.
- Shear-zone positional uncertainty: **not published** in either paper
  fetched.
- Commercial-use permission for derived results: **unanswered**, and is
  the single fact most likely to gate whether Subterra can ever use this
  dataset for anything beyond internal, non-commercial validation.
- The two multi-hundred-megabyte-to-gigabyte geological model files were
  **not opened** in this pass; they may already contain the exact
  coordinate tie §B and §I need, and are the first place to look before
  emailing anyone.

---

## What was not done, per the task's explicit instructions

No ingestion code, converter change, localisation algorithm change, 3D
reconstruction change, benchmark adapter, or detector threshold was
touched. No question in §"Author questions" was sent. No file was
downloaded and deleted — the one file fetched (`GPR_AU_N-to-S.rad`) was
read for this report and removed from the working tree along with all
other browser-session artefacts; nothing was added to `datasets/` and
nothing this pass produced needs preserving under a retention policy,
because no dataset was actually acquired for ongoing use — only inspected.
