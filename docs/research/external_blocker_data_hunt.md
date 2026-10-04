# External Blocker Data Hunt

**Date:** 2026-10-04 · **Branch:** `research/blocked-issues-resolution` · **Production code: not
changed.** All downloads stayed in a scratch directory; nothing large was committed.

Evidence levels used below:

- **AUTHORITATIVE**: original authors or the official dataset.
- **STRONG SECONDARY**: a reputable publication that documents the fact.
- **SUPPORTING**: consistent, but not sufficient alone.
- **HYPOTHESIS**: needs confirmation.

Figure-read values are never promoted above SUPPORTING.

## Executive summary

| Blocker | Classification |
|---|---|
| Yesan target list | **FOUND** (*Sensors* 26:5439 Table 2; recorded earlier this session) |
| Yesan per-line target assignment | **FOUND, at SUPPORTING level.** The testbed's original design paper (Rhee et al. 2021) assigns every Table 2 ascon and concrete target to a line. It is read from a figure. |
| Yesan origin and direction | **PROMISING LEAD.** The design paper defines distances "from the starting point A (or B)" with A→A′ numbering, and Fig. 1 of *Sensors* shows both lines starting at the ascon end. The physical marker is still unknown. |
| Yesan "bridge end" | **FOUND, at SUPPORTING level.** The abutment is mid-line at about 45 m chainage, not at either end. |
| Yesan 27 m calibration | **AUTHOR CONFIRMATION STILL REQUIRED.** Nothing public mentions it. |
| DRC datasets 7 and 13, and trajectories | **STILL MISSING** (exhaustive public search); the paper and preprint are **ACCESS BLOCKED** (bot protection) |
| 4TU velocity method | **FOUND (AUTHORITATIVE).** It is a hyperbola fit in Reflex-W 9.1.3 on the survey data, *not* an independent measurement. Subterra currently labels it `user_declared`; this must change. |
| 4TU time zero and air gap | **STILL MISSING** in the public record. The radar is confirmed **air-coupled**. The author's thesis is **ACCESS BLOCKED** (Cloudflare). |
| Independent time-zero reference | **PROMISING LEAD.** Aletsch firn CMP gathers (pulseEKKO, CC-BY, 2.6 MB, documented geometry); a feasibility check shows careful picking is needed. |

The single most important finding is that the **KEC testbed's own design paper exists and is
public**: Rhee, Park, Cho & Lee (2021), *Remote Sensing* 13:1805. It contains a per-line,
numbered inventory of the exact objects drawn in the Yesan paper, cites the Korean design
report, and states the distance convention. It doesn't give the 27 m calibration or the
physical 0 m marker.

---

## Yesan

### Sources searched

- **The *Sensors* paper:** Oh, Choi & Shin 2026, doi:10.3390/s26175439. Full-text XML from
  Europe PMC (PMC13568322); figures from the PMC open-data bucket (S3).
- **All 29 of its references.** None describes the test site.
- **Citations of the paper (OpenAlex):** 0 as of today.
- **Author histories (Crossref):** too noisy to use; "Chang-Geun Oh" and "Dong-Hoon Shin" are
  shared by many unrelated authors.
- **The Zenodo record 21441974:** one version (1.0.0, 2026-07-19), no related identifiers, and
  no calibration, origin or direction statement.
- **Web and Korean-language searches** on the KEC research institute, the Yesan test facility,
  the testbed, EPS hemispheres and GPR.
- **Rhee et al. 2021** (*Remote Sensing* 13:1805, PDF via Semantic Scholar's open copy).
- **The papers citing Rhee 2021** (Semantic Scholar, 28 citations).
- **Lee & Jang 2019** (KoreaScience PDF).
- **The KGS notice** on opening the KEC testbed (now 404, not archived).
- **The CODIL report RD-19-R3-003** (TLS failure / 503).
- **The ctman.kr news article** (503).

### New evidence

1. **Same testbed (STRONG SECONDARY).** Rhee et al. 2021, all authors KEC or Induk University,
   describe "the KEC testbed". It is 120 m long and 5–6 m wide, built in the latter part of 2018,
   with 30 m asphalt and 30 m concrete sections (plain 0–15 m, CRCP 15–30 m). Buried objects:
   - EPS hemispheres Φ0.5 and Φ1.0 m on line **A–A′**;
   - earthenware, PE bottles, rocks, concrete and asphalt blocks, steel plates, a drainage pipe
     Φ0.9 m at 1.5 m depth, and loosened zones on line **B–B′**.

   Their Fig. 3 is the same design as the *Sensors* paper's Fig. 2, object for object. The
   *Sensors* concrete section (plain 15 m + reinforced 15 m) matches Rhee's (plain 15 m + CRCP
   15 m). The *Sensors* approach-slab section is **not** in Rhee 2021.
2. **Per-line numbered inventory (SUPPORTING; figure-read).** Rhee Fig. 3 numbers each object:
   AP-A01–A10, AP-B01–B21, CP-A01–A14, CP-B01–B23. It also draws plan and depth panels on a
   0–30 m axis per section. Mapping onto *Sensors* Table 2:
   - Ascon chainages 2, 5, 11, 14, 17, 20, 23, 26, 29 m are the Line A EPS hemispheres AP-A01,
     A02 and A04–A10. AP-A03 (~8.5 m) is not in Table 2.
   - The ascon steel plate at 0 m is **AP-B01, Line B.**
   - Concrete chainages 61, 62, 65, 68, 71, 74, 76, 79, 82, 85, 88, 89 m minus 60 m give 1, 2,
     5, 8, 11, 14, 16, 19, 22, 25, 28, 29 m. These match the Line A objects CP-A01–A14
     exactly, including the drains at 5 m and 25 m.
   - So **Table 2 is Line A's list plus the Line B steel plate.** The approach-slab targets
     (31–59 m) appear on Line A in the *Sensors* Fig. 2(b).
3. **Distance convention (STRONG SECONDARY).**
   - "the X-axis is the longitudinal distance from the starting point A (or B) of the survey
     line A-A′ (or B-B′)";
   - "the numbering of buried objects is based on the type of pavement and A and B on the left
     side of the sideline in the order of A to A′ and B to B′ direction";
   - the lines are 2.0 m either side of the centreline (Fig. 3);
   - positions in Rhee's own surveys were tied by "GPS and Distance Measuring Instruments (DMI)".
4. **Design report (AUTHORITATIVE, not obtained).** Rhee's ref. [36]: Yoon W., Jeong J., Lee J.,
   **Shin D.**, Ko M., *A Study on NDT Techniques for Evaluating Subsurface Condition of Road
   Pavement*, EXTRI-2018-40-534.9607, Expressway & Transportation Research Institute, Hwaseong,
   2018, in Korean. Rhee calls it "the detailed view of each section". "Shin, D." may be the
   *Sensors* co-author Dong-Hoon Shin; this is unconfirmed. No public copy was found.
5. **Abutment location (SUPPORTING; figure-read).** In the *Sensors* Fig. 2(b), the approach-slab
   panel uses a section-local axis, so chainage = local + 30 m.
   - A buried **abutment** is drawn at local ~15 m (≈ 45 m chainage).
   - The slab layering changes there, and a cross-drain band runs across at ~14–15.5 m.
   - The 44 m and 46 m cavity-plus-steel-plate targets flank it.

   The "bridge transition" is therefore **mid-line**, at about 45 m, not at an end. That gives
   the 44–46 m radar transition a structural explanation independent of the radar. The axis
   labels skip 18 m, so the panel is schematic.
6. **Materials (STRONG SECONDARY, Rhee Table 1).**
   - EPS top depths 0.27–3.0 m (asphalt) and 0.5–2.5 m (concrete).
   - Earthenware Φ0.4 m; PE bottles 4 L at 0.27–1 m.
   - Ascon and concrete blocks at 0.27–2.5 m; rock Φ0.6 m at 2–2.5 m.
   - Drainage Φ0.9 m at 1.5 m, so the bottom is at ≈ 2.4 m, whereas *Sensors* Table 2 gives
     1.5–2.2 m. The two sources differ on the pipe; record both.
   - The groundwater level is about 2.66 m.
   - The top 1.5 m was excavated and replaced with standard expressway fill.

### 27 m calibration investigation

- **Searched:** the *Sensors* text, figures and appendix; the Zenodo record; Rhee 2021; the web
  (English and Korean) for wheel calibration, trace interval and 27 m.
- **Found:** nothing. The *Sensors* paper gives only a push speed of 1.0–1.1 m/s and 80–90 s per
  90 m pass. Rhee's own surveys used a DMI with GPS.
- **Status:** the arithmetic result stands; dx = 27/3116 m exactly
  (`scripts/yesan_scale_hypotheses.py`). Which physical 27 m (or 9 m, or 90 m) defined it is
  **AUTHOR CONFIRMATION STILL REQUIRED.**

  One candidate, **HYPOTHESIS only**: a span between drawn testbed features. For example,
  27 m separates the first and last Line A EPS in the ascon section (AP-A01 at 2 m and AP-A10
  at 29 m). This is numerology, not evidence, and must not be used.

### Target list search

Done. *Sensors* Table 2 has 34 targets. Rhee Fig. 3 adds the full per-line inventory, which
confirms Table 2 is **not exhaustive**. Rhee's object numbering would be the natural stable ID
scheme.

### Origin/direction search

- Lines run from start point A (or B) on the ascon side towards A′ (or B′), concrete last
  (*Sensors* Fig. 1; Rhee Fig. 3).
- The per-file 0 m trace (65/96/107 and 80/60/60) is consistent with operators starting the
  cart before a start mark. The physical mark (peg, paint, kerb line) is **not stated anywhere
  public.**

### Registration implications

1. Table 2 targets can now carry a **line assignment**: ascon and concrete EPS and the drains on
   Line A; the 0 m steel plate on Line B. The approach-slab targets are probably Line A (from the
   *Sensors* Fig. 2(b)). This is figure-derived, so record it as SUPPORTING evidence with the
   source, not as tabulated truth.
2. The KEC distance convention ("from the starting point A/B") and the section-local axes give
   the chainage frame a documented definition. Its tie to the radar's per-file 0 m trace and to
   the 27/3116 m scale is still undocumented.
3. Because the abutment sits at about 45 m, a structural feature at 44–46 m is expected
   independently of the targets.
4. **None of this may be "improved" by fitting radar responses.** Any anchor test must be
   pre-registered with its anchors held out of scoring.

### Remaining unknowns

- the physical 0 m marker on each line;
- the 27 m calibration distance and how it was measured;
- whether Table 2 chainages are design values or as-built survey values;
- the depth reference surface (inferred: pavement surface);
- the approach-slab section's design (not in Rhee 2021);
- the design report EXTRI-2018-40-534.9607.

---

## DRC

### Dataset 7

- GSSI 400 MHz UtilityScan cart, Field 1, 12–16 June 2023, group "Maryland – Heidi".
- Heidi Myers (University of Maryland) is a creator of Zenodo 19100554 and a co-author of the
  2026 paper.
- No file exists in either version of the Zenodo concept record (15324498, 19100554), in the
  supplemented record 8323244, or on the web map (`Raster: No`).
- Zenodo searches by creator (Myers) return only 19100554.
- **STILL MISSING.**

### Dataset 13

- Radarteam Cobra on a DJI M600, Field 2, "June 12–16" 2023, group "Binghamton – TdS & AN"
  (Timothy de Smet, Alex Nikulin).
- No file anywhere public.
- Zenodo creator searches for Nikulin and de Smet return unrelated people.
- Field 2 was freshly seeded by 15 June 2023: the MD5-identical image with a 150/150-cell
  footprint shows this (recorded earlier).
- **STILL MISSING;** the flight date relative to seeding is open.

### Trajectory search

- No trajectory, GNSS or positioning file for 7 or 13 exists in Zenodo, on the web map, or in
  any repository searched.
- The web map holds only per-item human interpretation (`AIU.csv`).
- **STILL MISSING.**

### Mirrors/archives

| Source | Result |
|---|---|
| Zenodo: both versions; 8323244; searches (demining, seeded minefield, landmine GPR, Radarteam Cobra, UtilityScan, the creators) | no GPR |
| de-mine.com web map: `datasets.json`, `1.csv`, `2.csv` | unchanged since 2026-09-29 (SHA-256 identical); the bundle loads no GPR file |
| Figshare, OSF, Harvard Dataverse, Mendeley Data | nothing relevant |
| arXiv | Lekhak (RIT) hyperspectral papers only; no GPR preprint |
| Preprint of the 2026 paper (Preprints.org, doi 10.20944/preprints202605.0758.v1) | **403**, bot protection |
| MDPI article (doi 10.3390/rs18132182) | **403**; Unpaywall lists only the publisher copy; not in PMC |
| GitHub | public search API unavailable; the session is bound to `eeb03/den-repo` |
| The Cobra web map tiles | could not be enumerated: tiles use layer names, and known-raster datasets also return 403 under guessed names (probing stopped) |

### Remaining unknowns

- the GPR files, trajectories and settings for 7 and 13;
- the dataset 13 flight date;
- the paper's Data Availability Statement and Supplemental Table 1 (blocked).

---

## 4TU

### Velocity

**FOUND (AUTHORITATIVE).** ter Huurne et al., *Data in Brief* (PMC10973596), the dataset's data
paper, states:

> "The ground relative permittivity was calculated using the velocity of GPR waves determined
> through the hyperbola fit function in Reflex-W software (version 9.1.3)."

So the `Metadata.csv` permittivity is a **same-survey hyperbola-fit estimate**, not an
independent measurement. The repository's open question about this method
(`evidence/fourtu_author.py`, "by what method (CMP, hyperbola fitting, …)") is answered.

**Implication:** Subterra resolves it through `ingestion/four_tu_velocity.py` into a SEG-Y
conversion marked `velocity_basis: user_declared`, which passes the scientific depth gate. It
should be `estimated_from_same_survey` with `velocity_method = "hyperbola fit (Reflex-W 9.1.3),
per data paper"`. Depth scoring against trench depths with it would be partly circular, because
the velocity was fitted to the same utilities' hyperbolas.

### Time zero

Nothing in the data paper, DataCite metadata (one version, CC0, no related identifiers) or
abstracts. The author previously confirmed no time-zero or air-gap correction was applied
(`docs/4tu-author-evidence.md`). **STILL MISSING.**

### Antenna/air gap

- **Confirmed (AUTHORITATIVE):** "an **air-coupled** Ground Penetrating Radar with a 500 MHz
  frequency antenna, a GNSS RTK receiver, and a measuring wheel encoder".
- The antenna height above ground is not stated publicly.
- The existing audit measured a 5–16 cm along-line height variation from GNSS versus AHN.
- **STILL MISSING** for the absolute air gap.

### Processing evidence

- Processing used Reflex-W 9.1.3; MapXact supplied the GPR equipment.
- The PhD thesis, ter Huurne 2024, "Navigating the Underground…", University of Twente
  (doi 10.3990/1.9789036561952; public, 19 MB), may document field settings. Its PDF is behind a
  Cloudflare challenge: **ACCESS BLOCKED.**
- data.4tu.nl returned **502** throughout; this is a server-side fault, not a policy block.

### Remaining unknowns

- the antenna height and air-gap geometry;
- the time-zero offset;
- an independent velocity (CMP, cores, or trench depths with coordinates);
- the GNSS accuracy (RTK confirmed, accuracy not stated).

---

## Independent time-zero validation datasets

### Candidate dataset 1: Aletsch firn CMP gathers (Zenodo 17077546)

- Patil et al., CC-BY-4.0, `CMP_AletschMay2024.zip`, 2.6 MB.
- pulseEKKO PRO, 500 MHz, `.HD`/`.DT1`: four CMP gathers of 9–200 traces, 0.2 ns sampling,
  128 stacks. A sibling record, 22026601 (214 MB), has 2025 CMPs plus snow-pit and firn-core
  densities.
- **Geometry (STRONG SECONDARY,** *The Cryosphere* 19:5547, 2025): "initial offset of 20 cm over
  a length of 20 m, with a step size of 10 cm on either side of a common mid-point".
- **Independence:** air-wave moveout (slope 1/c) gives an instrument time zero from physics, not
  from the reflection data. Snow-pit and firn-core density gives a velocity independent of the
  radar.
- **Feasibility check** (scratch script, not committed):
  - The header's 0.2 m/trace position steps are twice the paper's separation increment.
  - Under the paper's geometry, a 10%-threshold first break gives slopes of 3.9–4.1 ns/m,
    15–20% slower than the air wave (3.34 ns/m). These are probably the firn direct wave.
  - A proper air-wave pick (a weak, earlier event) is needed.
- The vendor `TIMEZERO AT POINT` field is a declared value, not a reference. The authors also
  "moved the start time to get the first arrival at the surface", so their processed time zero
  is not independent.
- Subterra has **no DT1 reader**.
- **PROMISING LEAD.**

### Candidate dataset 2: Shar Shaw Tagà CMP (Zenodo 10689923)

- Baraer, CC-BY-4.0, 2023.
- Radar Systems Zond SEG-Y (Prism2: time values in **picoseconds**; marks in bytes 237–240).
- 50/100/200 MHz CMP gathers of 39 traces, about 0.1 MB each; ground and drone transects.
- The SEG-Y offset field is 0, and positions are marker counts, so the geometry must come from
  `GPR transects map.jpg`.
- **PROMISING LEAD (weaker).**

### Candidate dataset 3: Rüdersdorf limestone quarry (Zenodo 13866430)

- Rieß, CC-BY-4.0, 720 MB.
- Repeated GPR monitoring with a CMP-derived velocity.
- Not inspected beyond metadata.
- **Lead.**

### Rejected

- **Zenodo 20784616** (road cavities): published as images after zero-time correction; no raw
  traces.
- **Lee & Jang 2019:** a different testbed (Seoul-style cavities, permittivity 5.73); not
  applicable to Yesan or KEC.

---

## Blocked domains

| Domain | URL | What was expected | Failure |
|---|---|---|---|
| www.mdpi.com | doi 10.3390/rs18132182; doi 10.3390/infrastructures10060140 | DRC paper Data Availability Statement and Supplemental Table 1; a KEC-testbed void-detection paper | 403, bot protection (not network policy) |
| www.preprints.org | /manuscript/202605.0758/v1 | DRC paper preprint | 403, bot protection |
| www.sciencedirect.com | S2666165922000254 (doi 10.1016/j.dibe.2022.100091) | KEC cavity-management paper (open access) | 403, bot protection |
| research.utwente.nl | /files/454962951/TerHuurne_NavigatingTheUnderground.pdf | 4TU author thesis: antenna height, processing | Cloudflare JavaScript challenge |
| www.codil.or.kr | /filebank/original/RK/OTKCRK211043/OTKCRK211043.pdf | 2019 Korean 3D-GPR testbed report | TLS chain unverifiable; 503 via fetch |
| www.ctman.kr | /24138 | news article on the KEC testbed | connection reset / 503 |
| www.kgshome.org | /74/2850448 | KEC testbed opening notice | 404; no Wayback snapshot |
| web.archive.org | CDX queries | archived KGS notice | connection reset mid-exchange |
| data.4tu.nl | /v2/articles/96303227-… | 4TU record and files | 502 (server-side) |
| api.openalex.org | author and citation queries | citation chains | shared-IP daily quota exhausted |
| api.github.com/search | repository search | DRC / Cobra code or data | session bound to `eeb03/den-repo` |

No additional domains need enabling for network-policy reasons. The failures are publisher bot
protection, server faults or quotas. Opening these pages in a normal browser is the route.

## Exact external files worth obtaining

1. **Yoon et al. 2018, EXTRI-2018-40-534.9607** (KEC Expressway & Transportation Research
   Institute, in Korean). This is the testbed design report, and may hold coordinate tables and
   the survey-line origin. Source: the KEC research institute library or the authors.
2. **Rhee et al. 2021 Fig. 3 at full resolution.** MDPI supplies it with the article
   (doi 10.3390/rs13091805), to digitise per-line positions properly.
3. **ter Huurne 2024 thesis PDF** from the University of Twente research portal (19 MB).
4. **Baur et al. 2026** (doi 10.3390/rs18132182): the Data Availability Statement, the
   Supplementary Materials and Supplemental Table 1.
5. **Lee et al. 2022** (doi 10.1016/j.dibe.2022.100091) and **Shin et al. 2025**
   (doi 10.3390/infrastructures10060140), to check whether they reuse the KEC testbed with
   coordinates.
6. **Zenodo 22026601**: `Patil_Firn_GPR_CMP_Snowpit_Firncore_Aletsch_Glacier_Dataset_2025_2026.zip`
   (214 MB, CC-BY-4.0, `https://zenodo.org/records/22026601`). Download it separately and don't
   commit it.

## Evidence table

| Blocker | Source | URL/DOI | Evidence found | Evidence level | Unblocks Subterra? | Confidence | Next action |
|---|---|---|---|---|---|---|---|
| Yesan target list | Oh et al. 2026, Table 2 | 10.3390/s26175439 | 34 targets, chainage and depth | AUTHORITATIVE | partly (already in manifest) | high | — |
| Yesan per-line assignment | Rhee et al. 2021, Fig. 3 | 10.3390/rs13091805 | Table 2 = Line A list + Line B steel plate | SUPPORTING (figure) | partly (line_id) | medium-high | record line_id with this source; obtain report [36] |
| Yesan distance convention | Rhee et al. 2021, §3.1, §4 | 10.3390/rs13091805 | "from the starting point A (or B)"; A→A′ numbering | STRONG SECONDARY | no (origin marker still unknown) | high | ask authors for the marker |
| Yesan bridge end | Oh et al. 2026, Fig. 2(b) | 10.3390/s26175439 | abutment at about 45 m (local 15 + 30) | SUPPORTING (figure) | partly (explains 44–46 m) | medium | record in manifest |
| Yesan 27 m | all of the above | — | nothing | — | no | — | author letter |
| Yesan design report | Rhee ref. [36] | EXTRI-2018-40-534.9607 | exists; not public | AUTHORITATIVE (not held) | potentially | — | request from KEC |
| DRC 7/13 data | Zenodo, web map, repositories | 10.5281/zenodo.19100554 | absent everywhere | AUTHORITATIVE absence | no | high | request from Myers / de Smet / Nikulin |
| DRC 13 timing | Zenodo 8323244 = 19100554 file 19-1 | 10.5281/zenodo.8323244 | Field 2 seeded by 15 June 2023 | AUTHORITATIVE (data) | partly | high | ask for the flight date |
| DRC paper statements | Baur et al. 2026 | 10.3390/rs18132182 | not readable | — | — | — | open in a browser |
| 4TU velocity method | ter Huurne et al., *Data in Brief* | PMC10973596 | Reflex-W hyperbola fit (same survey) | AUTHORITATIVE | yes (as a provenance fix) | high | relabel the velocity basis |
| 4TU antenna | same | PMC10973596 | air-coupled 500 MHz, GNSS RTK, wheel | AUTHORITATIVE | no (height unknown) | high | thesis; author |
| 4TU time zero / air gap | data paper, DataCite | 10.4121/96303227-… | nothing | — | no | — | thesis; author |
| Time-zero reference | Patil et al. CMP | 10.5281/zenodo.17077546; 10.5194/tc-19-5547-2025 | CMP geometry documented; air-wave pick feasible but not clean | STRONG SECONDARY (geometry) | potentially | medium | DT1 reader + pre-registered air-wave pick |
| Time-zero reference | Baraer CMP | 10.5281/zenodo.10689923 | CMP SEG-Y, geometry not in headers | SUPPORTING | potentially | low-medium | read the transect map |

## Conclusions

**Final classification per blocker**

| Blocker | Classification |
|---|---|
| Yesan target list | **FOUND** |
| Yesan per-line assignment and "which end is the bridge" | **FOUND at SUPPORTING level** (figure-derived) |
| Yesan origin / 0 m marker | **PROMISING LEAD** (convention documented; marker not) |
| Yesan 27 m calibration | **AUTHOR CONFIRMATION STILL REQUIRED** |
| DRC datasets 7 and 13 and their trajectories | **STILL MISSING** (public), with the paper text **ACCESS BLOCKED** |
| 4TU velocity method | **FOUND**; it is not independent |
| 4TU time zero / air gap | **STILL MISSING**; the thesis is **ACCESS BLOCKED** |
| Independent time-zero reference | **PROMISING LEAD** (Aletsch CMP) |

**Implementation changes that should follow** (none made in this session):

1. `benchmark/manifests/yesan-fullscale.targets.json`:
   - Add `line_id` to T2 targets: ascon and concrete EPS and the drains on A; T2-01 on B;
     approach slab on A, flagged as figure-derived.
   - Each assignment's evidence must cite Rhee et al. 2021 Fig. 3 / Oh et al. 2026 Fig. 2 as
     SUPPORTING.
   - Record the abutment at about 45 m.
   - Note the drain-depth disagreement (1.5–2.2 m vs Φ0.9 m at 1.5 m).
   - Keep every metric blocked until the 0 m marker and scale are confirmed.
2. 4TU velocity provenance:
   - `ingestion/four_tu_velocity.py` and the SEG-Y conversion basis should become
     `estimated_from_same_survey` with method "hyperbola fit (Reflex-W 9.1.3)", sourced to the
     data paper.
   - Close the open question in `evidence/fourtu_author.py`.
   - Expected effect: 4TU depth readiness stays approximate, and the depth gate refuses it.
3. Time-zero validation:
   - Add a pulseEKKO DT1/HD reader.
   - Run a pre-registered air-wave pick on the Aletsch CMP gathers. Accept a time-zero reference
     only if the fitted slope is within a stated tolerance of 1/c.
