# Public dataset survey and benchmark suite design

Research date: 2026-08-07. **Verification pass 2026-08-07** — see
[Verification results](#verification-results-2026-08-07), which corrected
several conclusions below. Nothing has been downloaded beyond ZIP central
directories and one 2.2 MB sample file used to test an existing reader.

## How to read this

Every fact below was checked against the source page, repository API, or
the dataset's own documentation during this survey. Where a field could
not be confirmed, it says **UNVERIFIED** rather than a plausible value.
Sizes, licenses and formats change; re-check before committing storage.

Two things this document deliberately does not do:

- **It does not invent a CRS for any dataset.** Several of the best
  datasets ship no CRS declaration at all. That is recorded as a property
  of the dataset, not smoothed over. It is also, usefully, exactly the
  condition Subterra's `CRSProvenance` model exists to represent.
- **It does not treat a detection dataset as ground truth.** Only three
  datasets here contain independently-verified subsurface truth (trial
  trenches, a controlled test site, and surveyed control points). Expert
  anomaly delineations are interpretation, and are labelled as such.

### A note on roadmap phase numbering

The Phase 0–12 master roadmap is not recorded anywhere in this repository
— `README.md` uses a different, coarser Phase 1/Phase 2 split, and
`docs/architecture.md` follows it. Rather than guess at the mapping, each
dataset below is keyed to the **named Subterra capabilities** it
exercises, which are verifiable against the code. Re-map to phase numbers
once the roadmap lives in the repo.

---

## Ranked summary

Rank is by value **to Subterra specifically** — capability unlocked per
gigabyte downloaded, weighted by whether the capability is otherwise
untestable. It is not a ranking of scientific quality.

| # | Dataset | Size | License | Why it ranks here |
|---|---------|------|---------|-------------------|
| 1 | [4TU Netherlands utility surveying](#1-4tu-netherlands-utility-surveying-ground-truth) | 403 MB | CC0 | Only dataset with SEG-Y **+** RTK GNSS **+** excavated ground truth. Tiny. |
| 2 | [AHN LiDAR (+ PDOK ortho)](#2-ahn--pdok-netherlands-national-lidar-and-orthophoto) | AOI-clipped | CC0 / CC-BY | Co-located with #1 in a **declared projected CRS** — the only way to test cross-CRS fusion on real data. |
| 3 | [TU1208 / IFSTTAR Nantes test site](#3-tu1208--ifsttar-nantes-geophysical-test-site) | 201 MB | CC-BY-4.0 | **Four formats in one archive** (GSSI, MALÅ, IDS, ASCII); the IDS files parse **today**, unchanged. |
| 4 | [Hillside, Lancaster](#4-hillside-lancaster-uk) | 80 MB | CC-BY-4.0 | 321 raw **MALÅ** lines on orthogonal 0.4 m grids, 3 frequencies, corners surveyed to EPSG:27700. |
| 5 | [Roman Republican Cities (ADS)](#5-beneath-the-surface-of-roman-republican-cities-ads) | UNVERIFIED | ADS Terms | Raw SEG-Y at 0.06–0.12 m line spacing — genuine 3D reconstruction. |
| 6 | [Guangzhou IDS `.dt`](#6-guangzhou-gpr-dataset-ids-dt) | 3.8 GB | CC-BY-4.0 | **Already local.** Tunnels, pipelines, rebar. Odometry. |
| 7 | [INGV-UNISA SEG-Y + KMZ](#7-ingv-unisa-segy--kmz) | local | see notes | **Already local.** The pinned regression baseline. |
| 8 | [CMU-GPR](#8-cmu-gpr) | **15.5 GB** | CC-BY-NC-SA | Odometry + total-station *robot-pose* truth. **No target truth at all.** NC license. See [`cmugpr-acquisition-assessment.md`](cmugpr-acquisition-assessment.md). |
| 9 | [Copernicus DEM / Sentinel-2](#9-copernicus-dem-and-sentinel-2) | AOI-clipped | free/open | Global DEM and satellite fill-in for any AOI. |
| 10 | [NSGeophysics/GPRdata](#10-nsgeophysicsgprdata) | 59 MB | **none** | Superseded for GSSI by #3; unique only for 2 Sensors & Software `.dt1`. Unlicensed. |
| 11 | [Morocco utilities/voids](#11-morocco-subsurface-utilities-and-voids) | small | none stated | Annotated **images**, not traces. ML labels, not geophysics. |
| 12 | [SERDP/ESTCP UXO](#12-serdpestcp-uxo-live-sites) | gated | US Gov | EMI, not GPR. Access is not a clean download. |

---

## Dataset detail

### 1. 4TU Netherlands utility surveying ground truth

**Official source** Delft University of Technology / 4TU.ResearchData, published alongside a *Data in Brief* article.
**Download** https://data.4tu.nl/datasets/96303227-5886-41c9-8607-70fdd2cfe7c1 — DOI [10.4121/96303227-5886-41c9-8607-70fdd2cfe7c1.v1](https://doi.org/10.4121/96303227-5886-41c9-8607-70fdd2cfe7c1.v1)
**License** CC0 1.0 — no restrictions, no attribution required.
**Size** 402,553,534 bytes (≈403 MB) across 16 files: `Readme.txt`, `Codebook.pdf`, `Metadata.csv`, and 13 archives `01.zip`–`013.zip` (5.8–97.4 MB each).
**Formats** `.sgy` (SEG-Y radargrams), `.png` (survey maps, trench cross-sections), `.csv` (metadata), `.pdf` (codebook).
**CRS** **None declared.** RTK GNSS x/y/z are present per radargram, but the dataset documentation states no EPSG code. Some radargrams have no georeference at all where the GNSS signal was obstructed.
**Survey geometry** 959 radargrams over 125 surveying activities at 13 construction sites, 2–26 radargrams per activity. 0.02 m trace spacing, 512 samples/trace, 50 ns range. Air-launched 500 MHz antenna, Spectre SP80 RTK receiver plus wheel encoder.
**Preprocessing required** Standard SEG-Y read; then the missing-CRS decision. Trace-header position conventions must be checked per file — do not assume they match the INGV convention.
**GeoTie available** No tie needed for georeferenced lines (RTK is already geographic). The lines *without* GNSS are a natural `NoPosition` / GeoTie-candidate population.
**True 3D reconstruction** Partial. Some activities have up to 26 lines; most have too few for volumetric reconstruction.
**Capabilities validated** `SEGYConverter`; `GeographicPosition`; `NoPosition` on obstruction; `CRSProvenance.NONE` (a real dataset that declares nothing); mixed-position frames; anomaly detection against real excavated truth; the interpretation layer.
**Strengths** The single highest-value item in this survey. CC0, tiny, SEG-Y, RTK, and — uniquely — **utilities confirmed by trial trench**, with depth, material and diameter.
**Weaknesses** Two serious ones. (a) The ground-truth records **exclude geospatial information for confidentiality**, so trench truth cannot be directly spatially joined to radargrams; the link is via activity ID, which constrains how quantitative a detection benchmark can be. (b) Material and diameter are not present for every utility. Also: one antenna, one frequency, one manufacturer.

### 2. AHN + PDOK: Netherlands national LiDAR and orthophoto

**Official source** Actueel Hoogtebestand Nederland, served via PDOK.
**Download** https://www.ahn.nl/dataroom and PDOK ATOM download services; orthophoto WMTS at `https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0`.
**License** AHN: CC0 / open data, free and unrestricted. PDOK orthophoto: CC-BY 4.0 (verify per product year).
**Size** National coverage is very large; **must be AOI-clipped to the 4TU site tiles.** Budget a few hundred MB, not the national set.
**Formats** LAZ point clouds (classified: ground, water, buildings, structures); DEM rasters; orthophoto via WMS/WMTS.
**CRS** **Declared and unambiguous** — Rijksdriehoek, EPSG:28992 horizontal, EPSG:7415 for the compound RD + NAP height.
**Survey geometry** Airborne LiDAR, sub-metre, >950 billion returns nationally.
**Preprocessing required** LAZ decompression; tile selection by AOI. Orthophoto needs a WMTS→GeoTIFF step because bulk file download is not offered.
**GeoTie available** Not applicable — natively georeferenced.
**True 3D reconstruction** Surface only. This is the *surface* half of a subsurface/surface pairing.
**Capabilities validated** `LASConverter`; `ProjectedPosition`; `SpatialRef` with `declared_by_source`; **`ingestion/crs_transform.py` and cross-CRS fusion on real data** — currently the only realistic route to that; `dem_alignment`; `GeoTIFFConverter`.
**Strengths** Co-located with dataset #1 by construction, since both cover the Netherlands. Declared projected CRS + CC0. This pairing turns cross-CRS fusion from tested-in-fixtures into tested-on-data.
**Weaknesses** Orthophoto is service-only, not files. Requires knowing where the 4TU sites are — and 4TU withholds trench coordinates, so site AOIs must come from the radargram RTK tracks rather than the ground truth.

### 3. TU1208 / IFSTTAR Nantes geophysical test site

**Official source** COST Action TU1208, "Civil engineering applications of GPR"; site operated by IFSTTAR (now Université Gustave Eiffel), Nantes, France. Paper: *Remote Sensing* 10(4):530.
**Download** https://zenodo.org/records/1211173 — DOI [10.5281/zenodo.1211173](https://doi.org/10.5281/zenodo.1211173)
**License** CC-BY-4.0.
**Size** 200,679,334 bytes (200.7 MB) compressed, 250 entries. The record also cites a 467.6 GB total data volume; the relationship between that figure and this archive is **UNVERIFIED**.
**Formats** **VERIFIED — four, in one archive.** `.DZT` + `.DZX` (GSSI, 80 + 28 files, 222 MB), `.rd3` + `.rad` (MALÅ, 30 + 30, 15.2 MB), `.DT` (IDS, 24, 19.4 MB), `.asc` (ASCII export, 24, 436.6 MB uncompressed). Also `readgssi.m`, a reference MATLAB GSSI reader.
**CRS** UNVERIFIED. A purpose-built test site normally uses a local site grid.
**Survey geometry** 67 profiles along **eleven parallel lines** crossing the site transversely. Three pulsed radar systems from **different manufacturers**, antennas from 200 MHz to 900 MHz.
**Preprocessing required** **Partly none.** The existing `converters/ids_dt_converter.py` parses the `.DT` files **unchanged** — verified against `GNEISS0-20/200MHz_gneiss0-20_1_rev.DT`, which reads as 1,079 traces × 1,024 samples with a clean ASCII header block. GSSI and MALÅ need new readers.
**GeoTie available** Probably needed (local grid → real coordinates), but UNVERIFIED.
**True 3D reconstruction** Limited — 11 lines over a controlled site supports pseudo-3D time-slicing, not dense volumetric imaging.
**Capabilities validated** Multi-vendor ingestion and `converters/registry.py`; `LocalCartesianPosition`; anomaly detection against **designed, known targets**; cross-instrument consistency — the same buried object seen by three radars is the cleanest possible test that preprocessing is not instrument-dependent.
**Strengths** A fully controlled subsurface: objects and obstacles reproducing the urban subsurface, emplaced deliberately. This is the only dataset here where "ground truth" means *we put it there*. Multi-manufacturer is otherwise very hard to obtain.
**Weaknesses** Two real ones found on inspection. (a) **The archive's own index spreadsheet is absent** — `Database_2018/` contains the stale lock file `.~lock.List_Database_V1.ods#` but not `List_Database_V1.ods` itself, so the authoritative inventory did not survive packaging. (b) **The directory structure does not match the paper's description.** Contents are grouped by material — `GNEISS0-20`, `GNEISS14-20`, `LIMESTONE`, `MULTI-LAYER`, `SILT`, `GPR3_ASCII` — not by the 67 profiles along 11 parallel lines the paper describes, so **whether this archive is the IFSTTAR profile set or a different TU1208 contribution is UNVERIFIED**. The target inventory and site grid remain unconfirmed, and the paper text is unreachable (MDPI, HAL and the Sapienza repository all serve bot challenges).

### 4. Hillside, Lancaster (UK)

**Official source** Andrew Binley, Lancaster University, 2022 archaeological geophysical survey.
**Download** https://zenodo.org/records/8253179 — DOI [10.5281/zenodo.8253179](https://doi.org/10.5281/zenodo.8253179)
**License** CC-BY-4.0.
**Size** 80,291,265 bytes (80.3 MB) compressed; 111.5 MB uncompressed, 1,950 entries. Plus a 151 kB description PDF.
**Formats** **VERIFIED — MALÅ.** 321 lines × 6 files each: `.rd3` (raw int16, 111.1 MB), `.rad` (plain-text key:value header), `.cor` (GPS), `.mrk` (markers), `.add`, `.em`.
**CRS** **Declared, and unusually well documented.** Six plots (HA–HF), each with its own **local X/Y coordinate system** with a defined origin and axis convention, and each plot's four corners **surveyed to British National Grid** (EPSG:27700) with elevation in m aOD. Corner coordinates are tabulated in the PDF, e.g. HA(1) = 347289.47 E, 461931.93 N, 32.09 m aOD.
**Survey geometry** **VERIFIED.** Six plots (2.8 × 8.4 m to 7.6 × 24 m), each surveyed in **two orthogonal directions** (`Dir1`/`Dir2`) on a **≈0.4 m line grid**. 321 lines total. HA: 33 lines of 7.41 m + 20 lines of 11.73 m. Per `.rad`: 500 MHz shielded, 336 samples, 66.33 ns window, 0.019 m trace spacing, distance-triggered measuring wheel. Plots HE and HF were additionally surveyed at **250 and 800 MHz** — multi-frequency over identical ground.
**Preprocessing required** **A MALÅ `.rd3`/`.rad` reader, which does not exist yet** — `.rd3` is in `KNOWN_UNSUPPORTED_FORMATS`. Then a 2D tie from four corner control points per plot.
**GeoTie available** **Yes — and it is the best example found.** Four control points per plot relating a local grid to a declared projected CRS.
**True 3D reconstruction** Likely within plots (dense grids over small areas), pending line-spacing confirmation.
**Capabilities validated** `LocalCartesianPosition`; `ControlPoint` / `GeoTie` / `apply_geo_tie`; `registered_position` and the native/registered/derived provenance tiers; `SpatialRef` with EPSG:27700 `supplied_by_caller`; cross-CRS fusion 27700→4326; a real `VerticalAxis` origin (m aOD, i.e. ODN).
**Strengths** 80 MB for the complete control-point story, **plus** it turns out to be the openly-licensed raw MALÅ dataset this survey initially reported as not existing. Orthogonal 0.4 m grids make it genuinely 3D-capable, and the 250/500/800 MHz repeats on HE/HF are a controlled frequency comparison over identical ground. Elevation data means the vertical datum is real rather than assumed.
**Weaknesses** Three, all now precise. (a) **No reader exists** — MALÅ support is the gating work item. (b) **All 321 `.cor` GPS files are 0 bytes**, so there is no satellite positioning of any kind; the surveyed corners in the PDF are the only route to real coordinates. (c) **The current `GeoTie` cannot consume those corners.** `ingestion/geo_tie.py:66` interpolates against `along_track_m` — a 1D along-a-line model — and Hillside's control points are 2D plot corners. Per instruction, this is recorded as a future enhancement rather than built.

### 5. Beneath the Surface of Roman Republican Cities (ADS)

**Official source** Millett, Verdonck, Leone & Launaro (2019), Archaeology Data Service, York. Cambridge/Ghent AHRC project.
**Download** https://archaeologydataservice.ac.uk/archives/view/romancities_ahrc_2019/ — DOI [10.5284/1052663](https://doi.org/10.5284/1052663). Processed companion at Cambridge: [10.17863/CAM.113175](https://doi.org/10.17863/CAM.113175).
**License** **VERIFIED via DataCite** (`10.5284/1052663`): *"ADS Terms and Conditions apply to reuse"* — **not a Creative Commons license.** Use and adaptation for historic-environment research is permitted, including commercially, with attribution and no resale of the data. Cambridge companion is CC-BY-NC-SA. **Read both before ingesting; the ADS terms are the more permissive of the two for commercial work, and the CC-BY-NC-SA on the Cambridge copy would restrict it.**
**Size** **Still UNVERIFIED and not resolvable here.** ADS serves a Cloudflare managed JS challenge to automated fetches, and the DataCite record returns empty `sizes` and `formats` arrays. This needs a human browser session; no legitimate API exposes it. Cambridge companion is ≈1.07 GB, of which 1.035 GB is two time-slice ZIPs and 12.86 kB is the metadata ZIP.
**Formats** ADS: raw **and** processed GPR profiles in **SEG-Y**, plus georeferenced GeoTIFF time-slices. Cambridge: GeoTIFF time-slices, shapefiles delineating GPR anomalies, CSV acquisition/processing metadata.
**CRS** Georeferenced (Italian national grid or UTM 33N expected); **exact EPSG UNVERIFIED.**
**Survey geometry** The best in this survey. ~27 ha at Falerii Novi and ~23 ha at Interamna Lirenas. **Traverse separation 0.06–0.12 m**, reading interval ≈0.05 m, positioned by **RTK-GNSS or robotic total station**.
**Preprocessing required** SEG-Y read; large-volume handling; time-slice generation if reproducing the published product.
**GeoTie available** Not needed — surveyed positioning throughout. The total-station-positioned lines are a good `ProjectedPosition` source.
**True 3D reconstruction** **Yes — the strongest candidate here.** 6–12 cm line spacing over hectares is genuine dense 3D coverage.
**Capabilities validated** `SEGYConverter` at scale; dense multi-line frame handling and `frame_id` scoping; time-slice/volume reconstruction; `GeoTIFFConverter`; the `interpretation/` layer against expert anomaly delineations.
**Strengths** Dense parallel lines, professional positioning, raw SEG-Y publicly archived, and expert anomaly shapefiles. Exactly the geometry 3D reconstruction needs.
**Weaknesses** ADS blocks automated access, so size and file inventory need a manual visit — this is the main unknown blocking a storage estimate. The anomaly shapefiles are **archaeological interpretation, not excavated ground truth**; treating them as truth would violate the platform's own layering. Bulk likely large. Two licenses to reconcile.

### 6. Guangzhou GPR dataset (IDS `.dt`)

**Official source** GPR Group of Guangzhou University (Prof. Hai Liu and team).
**Download** https://zenodo.org/records/14637589 — DOI [10.5281/zenodo.14637589](https://doi.org/10.5281/zenodo.14637589)
**License** CC-BY-4.0.
**Size** 3.8 GB (`Data Set.zip`), 4,572 members. **Only a 2.9 MB subset is local.** `datasets/raw/zenodo/14637589/` holds **10 `.dt` files** in three acquisition directories — `pipe/2020wate`, `pipe/1030`, `rebar/yangben` — fetched by HTTP Range against the archive's central directory, per `PROVENANCE.json`. **No tunnel data is held locally.**
**Formats** Raw `.dt`, IDS GeoRadar proprietary — decoded by `converters/ids_dt_converter.py`.
**CRS** None. Positioning is wheel odometry only.
**Survey geometry** The published record covers three tunnels (Liangjiaying, Pingdingshan, Niujianzi), pipelines at University Town Guangzhou, and rebar in a Foshan residential area. **Locally: pipelines and rebar only.**
**Preprocessing required** Already implemented, including the acquisition time axis recovered from the H record and cross-checked against `Ini000N.ini`. Depth requires a caller-supplied velocity.
**GeoTie available** No control points published. Odometry is terminal for this dataset.
**True 3D reconstruction** No — single lines, no cross-line geometry.
**Capabilities validated** `IDSDTConverter`; `OdometryPosition`; caller-supplied velocity and the measured-time / assumed-velocity / derived-depth separation; `AxisKind.TWO_WAY_TIME_NS`; **tunnels** as a target class.
**Strengths** The local subset already works end to end. The published record is the only tunnel GPR data found in this survey.
**Weaknesses** No ground-truth annotations confirmed in the record. No coordinates of any kind, so it can never participate in fusion. Velocity must be asserted by the caller, so all depths are derived. **Tunnel coverage requires the full 3.8 GB download** — it is a record-level capability, not a local one.

### 7. INGV-UNISA SEG-Y + KMZ

**Official source** INGV / University of Salerno survey lines already in `datasets/`.
**License** See the original acquisition record — **verify before any redistribution.**
**Formats** SEG-Y with per-trace header positions; KMZ track fallback.
**CRS** Header positions are projected; KMZ is WGS84. Authority resolved by measurement: headers win, KMZ is fallback.
**Survey geometry** 50 lines; header positions verified as a real per-trace acquisition track (67/72 and 66/66 distinct positions; track lengths agree with KMZ to 0.02%; residuals 0.74 and 1.22 m).
**Capabilities validated** The **pinned regression baseline** — shapes 482×72 / 482×66, depth 0→7.04665 m, z_std 0.904066/0.845445, record digests `23845e0a…`/`2027a323…`. Also `kmz_georeference`, direction verification, and the false-alarm baseline (2,551 candidates, 12 two-trace, 0 three-trace, matching the permutation null).
**Strengths** Zero new bytes, and it already encodes hard-won measured facts.
**Weaknesses** No ground truth. Establishes false-alarm rates only, and — per the ring z-score width-saturation result — broad coherent targets are structurally undetectable at |z|≥3 in this data.

### 8. CMU-GPR

> **Superseded in three places by
> [`cmugpr-acquisition-assessment.md`](cmugpr-acquisition-assessment.md)
> (2026-08-07), which read the repository's own data-format figure and both
> papers.** (a) The size is **15.5 GB**, not ≈12 GB. (b) **GeoTie is not
> available**: `ControlPoint` requires lat/lon, and all three sites are
> GPS-denied *indoor* environments, so there is no geographic coordinate to
> tie to — the `geotie_along_track` gap stays open. (c) Revisitation is
> declared **within** a sequence only; the *Correlated Sequences* column is
> empty for every row, and all ground-truthed sequences come from a single
> 98-minute session on 2021-02-11.

**Official source** Robot Perception Lab, Carnegie Mellon University.
**Download** https://github.com/rpl-cmu/CMU-GPR-Dataset (per-sequence Google Drive links).
**License** CC-BY-NC-SA 4.0 — **non-commercial.** A hard constraint if Subterra has any commercial path.
**Size** ≈12 GB across 15 sequences (11 MB – 1,193 MB each).
**Formats** CSV for GPR traces, IMU and odometry; PNG imagery; ZIP distribution. **Not** native Sensors & Software format.
**CRS** None specified.
**Survey geometry** 15 sequences at three locations, plus odometry-only data from two more. Includes deliberate **revisitation events** where the same subsurface is re-observed.
**Preprocessing required** CSV ingestion; no proprietary decoding.
**GeoTie available** **Effectively yes** — 10 sequences carry Leica TS15 total-station positions alongside wheel odometry, which is precisely the along-track control-point structure `apply_geo_tie` already implements.
**True 3D reconstruction** No. Built for localization/SLAM, not imaging.
**Capabilities validated** `OdometryPosition` at scale; along-track `GeoTie` with dense control; `registered_position` provenance; repeat-pass consistency.
**Strengths** Sensors & Software Noggin 500 — a fourth manufacturer. Synchronized odometry + independent ground-truth positions is rare. Revisitation is a genuine repeatability test.
**Weaknesses** 12 GB for one capability that Hillside tests at 80 MB and the existing Guangzhou data partly covers. NC license. Traces are CSV, so it does *not* advance native-format support. No GPS/RTK.

### 9. Copernicus DEM and Sentinel-2

**Official source** ESA/Copernicus; served by OpenTopography (DEM) and the Copernicus Data Space Ecosystem (imagery).
**Download** https://portal.opentopography.org (Global Datasets API; free key, 200 calls/24 h academic, 50 non-academic); https://dataspace.copernicus.eu (STAC, OData, OpenSearch, openEO, Sentinel Hub; access token required).
**License** Copernicus free-and-open for all users including commercial. OpenTopography serves under "open and permissible licenses" — check per dataset. Large-scale download/processing on CDSE has commercial conditions.
**Size** AOI-clipped; negligible if scoped to benchmark sites.
**Formats** GeoTIFF rasters; Sentinel-2 SAFE/COG.
**CRS** Declared throughout — Copernicus DSM in EPSG:4326, Sentinel-2 in UTM per tile.
**Capabilities validated** `GeoTIFFConverter`; `dem_alignment`; satellite modality in `SensorType`; multi-CRS fusion (Sentinel-2 UTM against geographic GPR).
**Strengths** Available for *any* AOI, so it makes every other dataset multimodal at near-zero storage cost. Well-declared CRS everywhere.
**Weaknesses** Surface only, and at 10–30 m resolution it is contextual rather than co-registered with metre-scale GPR. API keys and rate limits add a dependency. Contributes nothing to subsurface truth.

### 10. NSGeophysics/GPRdata

**Official source** GitHub, companion data for GPRPy.
**Download** https://github.com/NSGeophysics/GPRdata
**License** **None declared.** Default copyright applies — no redistribution or derivative rights granted. Verified via the GitHub API: the repository has no license field.
**Size** 58.7 MB of blobs (46 MB repo size).
**Formats** Verified by tree listing: **95 `.dzt`** (GSSI), **2 `.dt1` + 2 `.hd`** (Sensors & Software), 102 `.txt`, 2 `.csv`, 8 `.py`. Directories: `ExampleDuneInterface`, `ExampleDuneProfile`, `ExampleVelocityAnalysis`, `exampleCommonOffset`, `exampleDataCube`.
**CRS** None. **No GPS sidecars of any kind** — no `.dzg`, `.cor`, or GPS files; the only positional files are two topography CSVs.
**Capabilities validated** `.dzt` and `.dt1` reader development — the two formats currently in `KNOWN_UNSUPPORTED_FORMATS`.
**Strengths** Real Sensors & Software `.dt1`/`.hd` bytes, which no other dataset here supplies.
**Weaknesses** **The missing license is a genuine blocker** for anything beyond local development; it cannot be redistributed or committed. No positioning at all. **Largely superseded for GSSI**: TU1208 (#3) supplies 80 `.DZT` files under CC-BY-4.0, which is strictly better than 95 unlicensed ones. Its remaining unique value is the two Sensors & Software files.

### 11. Morocco subsurface utilities and voids

**Official source** *Data in Brief* / ScienceDirect, with a GitHub companion at https://github.com/LCSkhalid/GPR_Data.
**License** None declared on the repository (verified via API).
**Size** The GitHub repo is 486 kB and — verified by tree listing — contains only 2 `.py`, 1 `.md`, 1 `.png` and a `.gitignore`. **The actual data is not in the repository**; it is hosted with the article.
**Formats** Images with YOLO and VOC XML annotations. 2,239 annotated images, 400 MHz and 200 MHz antennas, Morocco, 2019–2024.
**CRS** None.
**Capabilities validated** Little. Subterra ingests traces and builds statistical evidence from them; this dataset starts downstream of that, at rendered B-scan images.
**Strengths** Large annotated corpus if image-domain detection is ever in scope.
**Weaknesses** No raw traces, no coordinates, no license, and the annotations are analyst interpretation rather than excavated truth. Ranked low on relevance, not quality.

### 12. SERDP/ESTCP UXO live sites

**Official source** US DoD SERDP/ESTCP, https://serdp-estcp.mil
**License** US Government work; access is programme-mediated rather than a public download.
**Formats** EMI sensor data (TEMTADS, MetalMapper), processed in UXAnalyze/UXOLab.
**Capabilities validated** Essentially none for a GPR platform.
**Strengths** Real dig-verified ground truth — genuine UXO/clutter labels, which is rare and valuable in principle.
**Weaknesses** **This is electromagnetic induction, not GPR.** Supporting it means a new modality and new readers, not a new dataset for existing code. No clean bulk download. **UXO is the one requested capability with no good open GPR dataset** — see gaps below.

---

## Coverage of the requested attributes

✅ covered · ⚠️ partial or unverified · ❌ not found openly

| Requested | Status | Best source |
|---|---|---|
| Ground Penetrating Radar | ✅ | all of #1–#8 |
| IDS GeoRadar | ✅ | #6 Guangzhou (already local) |
| MALA | ✅ | **#4 Hillside — 321 raw `.rd3`/`.rad` lines, CC-BY-4.0**; #3 adds 30 more |
| GSSI | ✅ | **#3 TU1208 — 80 `.DZT` + 28 `.DZX` under CC-BY-4.0** (#10 is unlicensed) |
| Sensors & Software | ⚠️ | #10 (2 `.dt1`), #8 CMU (Noggin 500 but CSV-exported) |
| SEG-Y | ✅ | #1, #5, #7 |
| Survey control points | ✅ | #4 Hillside (4/plot), #8 CMU (total station) |
| GeoTie information | ✅ | #4 (2D corners), #8 (along-track) |
| CRS/EPSG definitions | ✅ | #2 (28992/7415), #4 (27700), #9 |
| GPS or RTK trajectories | ✅ | #1 (Spectre SP80 RTK), #5 (RTK-GNSS) |
| Multiple parallel lines | ✅ | #5 (0.06–0.12 m spacing), #3 (11 lines) |
| Buried utilities | ✅ | #1 (trench-verified), #3 (emplaced), #6 |
| Archaeological targets | ✅ | #5, #4 |
| Tunnels | ⚠️ | #6 covers three tunnels **in the published record**; the local 2.9 MB subset holds none. Needs the full 3.8 GB. |
| UXO | ❌ | **no open GPR UXO dataset found**; #12 is EMI and gated |
| Pipes | ✅ | #1, #3, #6 |
| Ground-truth annotations | ⚠️ | #1 trenches (but **no coordinates**), #3 emplaced targets; #5 is interpretation |
| LiDAR | ✅ | #2 AHN (CC0, LAZ) |
| DEM | ✅ | #2, #9 |
| Orthophotos | ⚠️ | #2 PDOK — **WMTS service only, no bulk file download** |
| Satellite imagery | ✅ | #9 Sentinel-2 |

### The four real gaps

1. ~~**MALA.**~~ **CLOSED by verification.** Hillside (#4) is 321 raw MALÅ lines under CC-BY-4.0, and TU1208 (#3) adds 30 more from a different site. Both were reported here as format-UNVERIFIED before the ZIP directories were read. A reader can now be written *and* validated against real field data from two independent sources.
2. **UXO by GPR.** Does not appear to exist openly. UXO detection is dominated by EMI, and the good ground truth (ESTCP dig results) is EMI ground truth. Treat UXO as out of scope for GPR validation, or accept a modality expansion.
3. **Ground truth with coordinates.** The best excavated truth (#1) deliberately withholds location. The best-positioned data (#5) has interpretation, not truth. **No single open dataset has both.** #3 IFSTTAR is the closest, being a controlled site, and is the reason it ranks 3rd despite the unverified fields.
4. **Orthophotos as files.** Service-only from PDOK; needs a tile-fetch step or a different provider.

A fifth gap emerged during verification: **`.rd3` and `.dzt` readers do not
exist**, and the two best newly-verified datasets are written in them. That
is a code gap rather than a data gap, and it is now the binding constraint
on Tier 1 — see the acquisition plan.

---

## Benchmark suite design

Design rule: **each tier must unlock a capability the previous tiers cannot
test, and no dataset is downloaded twice for the same reason.** Tiers are
independently useful — stopping after any tier leaves a coherent suite.

### Tier 0 — Regression floor · 0 new bytes

INGV-UNISA (#7) and Guangzhou (#6), both already local.

Pins existing numeric behaviour: array shapes, depth axis, z-statistics,
candidate counts, record digests, and the false-alarm baseline. Every
later tier runs against this gate. **No tier is allowed to change these
numbers**; if one does, that is a scientific regression, not a benchmark
result.

### Tier 1 — Spatial truth · ≈ 483 MB

4TU Netherlands (#1, 403 MB) + Hillside (#4, 80 MB).

The single highest-value download in the plan. Together they give:
excavated utility ground truth; RTK geographic positioning; a dataset
that **declares no CRS** (exercising `CRSProvenance.NONE` and the refusal
to infer); a dataset that declares EPSG:27700 with surveyed control
points; local site grids; and a real vertical datum (m aOD).

Blocks Tier 1 partially: Hillside needs a **2D control-point tie**, which
`ingestion/geo_tie.py` does not implement — it interpolates against
`along_track_m`. Decide before starting whether to extend GeoTie to a 2D
similarity transform or to use Hillside for `LocalCartesianPosition` only.

### Tier 2 — Real cross-CRS fusion · ≈ 200 MB–1 GB, AOI-clipped

AHN LiDAR tiles (#2) over the 4TU sites + Copernicus DEM (#9) for the
same AOIs.

This is the tier that matters most for recently-built code. Cross-CRS
fusion is currently tested only against fixtures, and **nothing in the
repository has a projected frame with a declared CRS**. AHN supplies
exactly that — EPSG:28992, declared by source, over the same ground as
Tier 1's GPR. Derive AOIs from the 4TU radargram RTK tracks, since the
trench records carry no coordinates.

Clip to AOI. Do not mirror national coverage.

### Tier 3 — Multi-vendor and 3D · ≈ 200 MB + ADS (unknown)

TU1208/IFSTTAR (#3, 201 MB) + a **subset** of the Roman Cities ADS
archive (#5).

IFSTTAR gives three manufacturers over designed targets — the only clean
test that preprocessing is instrument-independent. The ADS archive gives
6–12 cm line spacing for genuine 3D reconstruction.

Two cost controls on #5: take **one city, or even one field**, not both;
and from the Cambridge companion take only the **12.86 kB metadata ZIP**,
not the 1.035 GB of time-slice archives — Subterra should generate
time-slices from raw SEG-Y rather than ingest someone else's. Confirm
whether the anomaly shapefiles live inside the time-slice ZIPs before
skipping them; if so, that changes the calculus.

Requires a manual visit to ADS first (403 to automated fetch) to size the
archive and confirm the EPSG.

### Tier 4 — Optional, only if a specific need arises

- **NSGeophysics (#10)** — only if `.dzt`/`.dt1` readers are being
  written. Local development only; the missing license bars redistribution
  and it must not be committed.
- **CMU-GPR (#8)** — only if along-track GeoTie needs dense validation
  beyond what Guangzhou and Hillside provide. 12 GB and NC-licensed;
  take one or two sequences, not the set.
- **Sentinel-2 (#9)** — only when a satellite modality is actually built.

### Storage budget

| Tier | New bytes | Cumulative |
|---|---|---|
| 0 | 0 | 0 |
| 1 | ≈ 483 MB | ≈ 483 MB |
| 2 | ≈ 200 MB – 1 GB | ≈ 0.7–1.5 GB |
| 3 | ≈ 200 MB + ADS subset | ≈ 1–5 GB (ADS-dependent) |
| 4 | ≈ 59 MB – 12 GB | opt-in |

Tiers 0–3 should land comfortably inside 5 GB — well within the ~42 GB
available — with the ADS archive the only real uncertainty.

### What the suite deliberately does not claim

- **No detection benchmark against excavated truth is possible from these
  datasets alone.** #1 has trench truth but withholds its coordinates;
  #5 has positions but only interpretation. #3 is the only candidate for
  a quantitative detection score, and only if its target inventory and
  site grid turn out to be published. Until then, detection performance
  can be characterised (false-alarm rates, null comparisons) but **not
  scored against truth** — which is the same conclusion the 50-line
  false-alarm work reached, now confirmed to be a property of the
  available public data rather than of the INGV data specifically.
- **Anomaly shapefiles are interpretation.** They belong in the
  `interpretation/` layer, never in a ground-truth table.

### Suggested order

1. Manually visit ADS and the IFSTTAR record to close the UNVERIFIED
   fields. Cheap, and it determines whether Tier 3 is affordable.
2. Tier 1 — 4TU first; it is the highest value per byte in the survey.
3. Decide the 2D-GeoTie question that Hillside forces.
4. Tier 2 — the one that converts cross-CRS fusion from fixture-tested to
   data-tested.
5. Tier 3 only after 1–2 are green against the Tier 0 regression gate.

---

## Verification results (2026-08-07)

Requested follow-up on the ADS and MDPI records, plus a Tier 1 readiness
check. Method, since it matters for how much to trust the results: ZIP
**central directories were read over HTTP Range**, so file inventories are
the archives' own, not a description of them. No bulk data was downloaded.
One 2.2 MB member was extracted to test an existing reader.

**What could not be verified, and why.** `archaeologydataservice.ac.uk`,
`mdpi.com`, `hal.science` and `iris.uniroma1.it` all serve Cloudflare or
equivalent **JS bot challenges**. These are anti-automation walls, not
authentication, and were not circumvented. Consequently the ADS archive
size and file inventory, and the TU1208 paper text, **remain unverified
and need a human browser session.** DataCite supplied the ADS license but
returns empty `sizes` and `formats`.

**What the archives themselves answered, better than the papers would
have:**

| Finding | Consequence |
|---|---|
| Hillside is **MALÅ `.rd3`/`.rad`**, 321 lines | Closes the "no open MALA dataset" gap |
| Hillside `.cor` GPS files are **all 0 bytes** | No satellite positioning; surveyed corners are the only route to coordinates |
| Hillside is an **orthogonal 0.4 m grid**, two directions, 250/500/800 MHz on HE/HF | 3D-capable and a controlled frequency comparison |
| TU1208 holds **GSSI + MALÅ + IDS + ASCII** in one 201 MB archive | Supersedes the unlicensed NSGeophysics repo for GSSI |
| **`converters/ids_dt_converter.py` parses TU1208 `.DT` unchanged** — 1,079 × 1,024 traces | 24 files ingestible today, zero new code |
| TU1208's `List_Database_V1.ods` index is **missing** (only its stale lock file was packaged) | The archive's own inventory is unavailable |
| TU1208 is grouped by **material**, not the paper's 11 parallel lines | Whether this is the IFSTTAR profile set is now genuinely in doubt |
| 4TU confirmed **CC0** via JSON-LD; download is a **streamed ZIP** with no `Content-Length` and no range support | All-or-nothing 403 MB; cannot preview or partially fetch |

### TU1208 identity verification (2026-08-07)

**Question asked:** does the Zenodo archive genuinely correspond to the
IFSTTAR dataset the paper describes? The previous pass flagged this as
doubtful because the directory structure is grouped by material rather
than by the paper's 11 parallel lines.

**Verdict: VERIFIED with high confidence.** The doubt was unfounded.

The paper's abstract, retrieved from the **OpenAlex API** (the publisher
site, HAL and the Sapienza mirror are all bot-walled), states verbatim:

> Overall, **67 profiles** were recorded along **eleven parallel lines**
> crossing the test site in the transverse direction; **three pulsed radar
> systems** were used to perform the measurements, manufactured by
> **different producers** and equipped with various antennas having central
> frequencies **from 200 MHz to 900 MHz**. **An archive containing all
> profiles (raw data) is enclosed to this paper as supplementary material.**

Every countable claim matches the archive:

| Paper | Archive | |
|---|---|---|
| 67 profiles | **67 native radargram files** (79 data files − 12 ASCII exports, each with a native counterpart; 64 unique stems, 3 recorded in two formats) | ✅ exact |
| Three systems, different producers | **Three vendor formats**: GSSI `.DZT`, MALÅ `.rd3`, IDS `.DT` | ✅ exact |
| 200 MHz to 900 MHz | Filename tokens 200/250/270/350/400/500/600/800/900 MHz | ✅ exact |
| Raw data enclosed as supplementary material | Native vendor binaries, no processing applied | ✅ |
| Site reused "over the years" for device comparison | See campaigns below | ✅ |

**Independent provenance evidence.** Acquisition timestamps decoded from
the file headers themselves resolve into three internally coherent
campaigns over a constant set of five material zones:

| Campaign | System | Files | Evidence of coherence |
|---|---|---|---|
| 1998-09-24 → 1999-08-19 | GSSI (16-bit, older) | 26 | Lines 1–4 at 13:43/13:50/14:09/14:15; 900 MHz set at 09:10/09:15/09:21/09:27 — consecutive traverses minutes apart |
| **2005-03-24** | IDS | **all 12** | **One field day, 09:40 → 15:07**, progressing silt → limestone → gneiss |
| 2017-10-25 → 2017-11-27 | GSSI SIR-4000, 32-bit | 14 | Same-session clusters, e.g. 14:50/14:55/15:15/15:18/15:39/15:41 |

Three campaigns, three vintages of instrument, one unchanging set of
material zones, spanning 1998–2017 — which is precisely a purpose-built
test site "used for various needs over the years, such as tests or
comparisons of devices." Timestamps this internally consistent are not
corrupted clocks.

**Correction to the previous pass.** The 467.6 GB figure read off the
Zenodo page is a site-wide statistic, not this record's volume. The
archive is self-contained; the paper says so explicitly. The earlier
worry that "the location of the full database is UNVERIFIED" was
misplaced.

**What remains unverified, and it matters:**

- **The buried-target inventory** — what objects are emplaced, where, of
  what material, at what depth — is in the paper *body*, not the abstract,
  and the body is unreachable behind bot walls. So TU1208's **format value
  is verified; its ground-truth value is not.** Do not plan a detection
  score against it until someone reads the paper.
- **"Eleven parallel lines"** is not derivable from the archive. Filename
  line labels are `1`, `2`, `3`, `4`, `h1`, `h2` within five material
  zones — consistent with transverse lines crossing several zones, but not
  independently counted.
- `List_Database_V1.ods` is still absent (only its stale lock file).
- **No embedded metadata names IFSTTAR or Nantes.** MALÅ `SITE`,
  `OPERATOR`, `CUSTOMER` and `COMMENT` fields are empty; the GSSI `.DZX`
  records only `<system>SIR4K</system>` and `<gridId>Grid</gridId>`.
  Identity rests on the publisher-level assertion plus the content match
  above, not on a self-identifying file.

### Can Hillside use the existing `LocalCartesianPosition`?

**Yes for acquisition geometry, no for georeferencing** — and the split
falls exactly on the boundary the instruction drew.

*Works today, no new abstraction:*

- Each `.rad` records `START POSITION`, `STOP POSITION` and
  `DISTANCE INTERVAL` from a distance-triggered measuring wheel. A trace is
  therefore `OdometryPosition(along_track_m=…, path_id=<line file stem>)`
  with **zero assumptions** — the same representation the Guangzhou `.dt`
  data already uses.
- `LocalCartesianPosition(x, y, origin_description=…)` is also
  constructible: the plot corners define the origin and axes, `x` is the
  along-track distance, and `y` is the line's cross-line offset. Line
  lengths corroborate the layout — HA `Dir1` lines stop at 7.41 m against a
  7.6 m `Xlength`, `Dir2` at 11.73 m against a 12.8 m `Ylength`.

  The catch is that cross-line offset is **not recorded in any machine-readable
  field**. It has to be derived from line count, plot width and file
  ordering — 33 lines across 12.8 m ⇒ ≈0.4 m. That is a **caller-supplied
  survey-geometry assertion**, directly analogous to the existing
  caller-supplied velocity and caller-supplied CRS mechanisms, and it
  belongs in an `Assumption` on the frame rather than in a heuristic.
  Fits the architecture as implemented; no new type needed.

*Does not work, recorded as a future enhancement per instruction:*

- **Promoting either representation to EPSG:27700 using the four surveyed
  corners.** `ingestion/geo_tie.py` interpolates control points against
  `along_track_m`, a 1D model along a single line. Hillside's control
  points are 2D plot corners, which needs a 2D similarity or affine tie.
  **Not built.** Until it is, Hillside's real-world coordinates stay in the
  PDF and its data stays in local/odometry space — which is a correct and
  honest terminal state, not a defect.

*Blocking either path:* **no MALÅ reader exists.** `.rd3` is in
`KNOWN_UNSUPPORTED_FORMATS`. The format is undemanding — `.rad` is
plain-text `KEY:value` and `.rd3` is raw int16 — and the vendor
specification is public, so this is substantially simpler than the IDS
`.dt` reader that was reverse-engineered for this platform. It is
nonetheless real work that must precede any Hillside ingestion.

---

## Sources

Ranked datasets: [4TU](https://data.4tu.nl/datasets/96303227-5886-41c9-8607-70fdd2cfe7c1) ·
[4TU article (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10973596/) ·
[AHN](https://www.ahn.nl/dataroom) · [PDOK AHN](https://www.pdok.nl/introductie/-/article/actueel-hoogtebestand-nederland-ahn) ·
[PDOK orthophoto](https://www.pdok.nl/introductie/-/article/pdok-luchtfoto-rgb-open-) ·
[TU1208 Zenodo](https://zenodo.org/records/1211173) · [TU1208 paper](https://www.mdpi.com/2072-4292/10/4/530) ·
[Hillside](https://zenodo.org/records/8253179) ·
[Roman Cities ADS](https://archaeologydataservice.ac.uk/archives/view/romancities_ahrc_2019/) ·
[Falerii Novi (Cambridge)](https://www.repository.cam.ac.uk/items/b7ba59d7-fda7-4f44-8853-daf393e6db45) ·
[Interamna Lirenas (Cambridge)](https://www.repository.cam.ac.uk/items/3cc14482-bc94-4abe-b0ab-af0cab4cc019) ·
[ADS terms of use](https://archaeologydataservice.ac.uk/about/policies/use-access-to-data/ads-terms-of-use-and-access/) ·
[Guangzhou](https://zenodo.org/records/14637589) ·
[CMU-GPR](https://github.com/rpl-cmu/CMU-GPR-Dataset) ·
[OpenTopography](https://opentopography.org/developers) ·
[Copernicus Data Space](https://dataspace.copernicus.eu/) ·
[NSGeophysics/GPRdata](https://github.com/NSGeophysics/GPRdata) ·
[Morocco GPR_Data](https://github.com/LCSkhalid/GPR_Data) ·
[SERDP/ESTCP UXO](https://serdp-estcp.mil/focusareas/9f7a342a-1b13-4ce5-bda0-d7693cf2b82d/uxo)

Reference: [RGPR free GPR data list](https://emanuelhuber.github.io/RGPR/80_RGPR_GPR-data-free-to-download/) ·
[MALA RD3/RD7/RAD format spec](https://wwwguidelinegeoc.cdn.triggerfish.cloud/uploads/2021/03/MALA-formats-rd3-and-rd7.pdf)
