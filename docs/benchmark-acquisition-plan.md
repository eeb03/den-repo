# Benchmark acquisition plan (finalized)

Companion to [dataset-benchmark-plan.md](dataset-benchmark-plan.md), which
holds the research and the per-dataset detail. This document is the
decision: what to download, in what order, and what it costs.

**Status: Hillside (T1.3) acquired and checksum-verified.** 4TU (T1.1) and
TU1208 (T1.2) await approval. No converter implementation has begun.

Every classification below reflects the 2026-08-07 verification pass, which
read the candidate archives' own ZIP central directories over HTTP Range.
Three datasets moved tier as a result.

## Roadmap phase mapping

The Phase 0–12 master roadmap is not recorded in this repository, so
"phases validated" is expressed as **named Subterra capabilities**, which
are checkable against the code, plus the repo's own Phase 1/Phase 2 split
from `README.md`. Re-map once the roadmap is committed.

---

## Tier 1 — download now

Total: **684 MB**. Everything here is permissively licensed, and two of the
three are partly or wholly ingestible with existing code.

### T1.1 · 4TU Netherlands utility surveying — 403 MB

| | |
|---|---|
| **Download size** | 402,553,534 bytes, single streamed ZIP (no range support, no partial fetch) |
| **Storage impact** | ≈403 MB raw + ≈403 MB extracted ≈ **0.8 GB** |
| **License** | **CC0 1.0** — verified via JSON-LD. No restrictions, no attribution required. Redistributable. |
| **Phases validated** | `SEGYConverter` · `GeographicPosition` · `NoPosition` · **`CRSProvenance.NONE`** · mixed-position frames · `preprocessing` + anomaly detection against excavated truth · `interpretation/` |
| **Benchmark value** | **Highest per byte in the survey.** The only dataset combining SEG-Y, RTK GNSS trajectories, and utility ground truth confirmed by trial trench (depth, material, diameter). |
| **Preprocessing effort** | **Low — no new code.** SEG-Y reads today. Work is (a) confirm the trace-header position convention per file rather than assuming INGV's, (b) decide CRS handling for a dataset that declares none, (c) route GNSS-obstructed lines to `NoPosition`. |

Watch: ground truth **withholds coordinates** for confidentiality, linked
to radargrams only by activity ID. This caps how quantitative a detection
benchmark can be — see "What this suite cannot claim".

### T1.2 · TU1208 / IFSTTAR database — 201 MB · **promoted from Tier 3, identity verified**

| | |
|---|---|
| **Download size** | 200,679,334 bytes, single ZIP (Zenodo, range-capable) |
| **Storage impact** | ≈201 MB raw + ≈710 MB extracted ≈ **0.9 GB** (the 24 `.asc` files expand to 437 MB) |
| **License** | **CC-BY-4.0** — attribution only. Redistributable. |
| **Phases validated** | `IDSDTConverter` **on a second, independent instrument** · `converters/registry.py` multi-vendor dispatch · future `.dzt` / `.rd3` readers · anomaly detection against a controlled site |
| **Benchmark value** | **Four vendor formats in one 201 MB archive**: GSSI `.DZT`×80, MALÅ `.rd3`×30, IDS `.DT`×24, ASCII `.asc`×24. Verified: the existing IDS parser reads its `.DT` files **unchanged** (1,079 × 1,024 traces). Cross-instrument agreement over the same ground is the cleanest available test that preprocessing is not instrument-dependent. |
| **Preprocessing effort** | **None for the 24 IDS files.** Medium for the rest — one GSSI and one MALÅ reader. `.asc` may route through `CSVConverter`. |

**Why promoted — identity now verified.** Promotion was held pending proof
that the archive is the dataset the paper describes. It is. The paper's
abstract (via the OpenAlex API) states that "an archive containing all
profiles (raw data) is enclosed to this paper as supplementary material",
and every countable claim matches: **67 profiles ↔ 67 native radargram
files**, three producers ↔ three vendor formats, 200–900 MHz ↔ the exact
frequency set in the filenames. Header timestamps resolve into three
coherent campaigns (1999 GSSI, **2005-03-24 IDS in a single field day**,
2017 GSSI SIR-4000) over one unchanging set of material zones — a test
site reused for device comparison across two decades. Full evidence in
[the survey](dataset-benchmark-plan.md#tu1208-identity-verification-2026-08-07).

It also **retires the unlicensed NSGeophysics dependency** for GSSI.

**Watch — the one thing verification did not settle.** The buried-target
inventory (what objects, where, what depth) lives in the paper *body*,
which is behind bot walls. **TU1208's format value is verified; its
ground-truth value is not.** Plan no detection score against it until
someone reads the paper. The index spreadsheet `List_Database_V1.ods` is
also still missing from the archive.

### T1.3 · Hillside, Lancaster — 80 MB · **ACQUIRED 2026-08-07**

| | |
|---|---|
| **Download size** | 80,291,265 bytes + 151 kB PDF (Zenodo, range-capable) |
| **Storage impact** | ≈80 MB raw + ≈112 MB extracted ≈ **0.2 GB** |
| **License** | **CC-BY-4.0** — attribution only. Redistributable. |
| **Phases validated** | **`.rd3`/`.rad` MALÅ reader** (new) · `OdometryPosition` · `LocalCartesianPosition` · `Assumption` on caller-supplied survey geometry · multi-frequency consistency (250/500/800 MHz on identical ground) · 3D reconstruction on orthogonal 0.4 m grids |
| **Benchmark value** | 321 raw MALÅ lines under a real license — this **closes the MALA gap** the survey first reported as unfillable. Orthogonal two-direction grids make it genuinely 3D-capable at 80 MB. |
| **Preprocessing effort** | **Blocked, then low.** No MALÅ reader exists. Building one is modest: `.rad` is plain-text `KEY:value`, `.rd3` is raw int16, and the vendor spec is public — materially simpler than the IDS reader already built here. |

**Acquisition record.** Downloaded to
`datasets/raw/zenodo/8253179/` on 2026-08-07 and verified against the
Zenodo record's published MD5s:

    Hillside GPR data.zip                          80,291,265 B  md5 5aa777103d5b7b9b67d84ea86d2e82bf  OK
    Hillside GPR file structure and description.pdf   151,126 B  md5 b3a33ece6a689c8ccef07bdb730147e7  OK

Extracted inventory matches the pre-download remote reading exactly:
**321 `.rd3` + 321 `.rad` + 321 `.mrk` + 321 `.em` + 321 `.cor` + 321
`.add`**, 110 MB, across 10 plot/frequency directories — `HA(500)`,
`HB(500)`, `HC(500)`, `HD(500)`, `HE(250)`, `HE(500)`,
`HE(800 Transects)`, `HF(250)`, `HF(500)`, `HF(800)`. **All 321 `.cor`
files are 0 bytes**, confirming no satellite positioning. Covered by
`.gitignore:12` (`datasets/`), so no raw data enters git.

**Ingestion is still blocked** — no MALÅ reader exists. Per instruction
this is an acquisition task only; no converter work has started.

Also settled, per instruction: Hillside **fits the existing spatial
abstractions** for acquisition geometry — `OdometryPosition` with zero
assumptions, or `LocalCartesianPosition` with a caller-supplied line-spacing
assertion. Promoting it to EPSG:27700 via the surveyed corners needs a 2D
tie, which is **recorded as a future enhancement and not built**.

---

## Tier 2 — download after Tier 1 validation

Gated on Tier 1 passing the Tier 0 regression baseline.

### T2.1 · AHN LiDAR, AOI-clipped

| | |
|---|---|
| **Download size** | ≈200 MB–1 GB depending on tile count. **AOI-clipped, never national.** |
| **Storage impact** | ≈0.5–2 GB (LAZ expands substantially on decompression) |
| **License** | **CC0 / open data**, unrestricted |
| **Phases validated** | `LASConverter` · `ProjectedPosition` · `SpatialRef` with `declared_by_source` · **`ingestion/crs_transform.py` + cross-CRS fusion on real data** · `dem_alignment` |
| **Benchmark value** | **The highest-value Tier 2 item.** Cross-CRS fusion is currently fixture-tested only, because nothing in the repo has a projected frame with a declared CRS. AHN is EPSG:28992 `declared_by_source` over the same ground as T1.1. |
| **Preprocessing effort** | Low. LAZ decompression, AOI tile selection. Derive AOIs from T1.1 radargram RTK tracks — the trench records have no coordinates. |

**Sequencing note:** depends on T1.1 having produced usable RTK tracks, so
it cannot start earlier.

### T2.2 · Copernicus DEM, AOI-clipped

| | |
|---|---|
| **Download size** | Negligible AOI-clipped |
| **Storage impact** | < 100 MB |
| **License** | Copernicus free-and-open, commercial use permitted |
| **Phases validated** | `GeoTIFFConverter` · `dem_alignment` · multi-CRS fusion |
| **Benchmark value** | Moderate. Makes any AOI multimodal at near-zero cost. Contextual at 30 m, not co-registered with metre-scale GPR. |
| **Preprocessing effort** | Low. OpenTopography API key; 50–200 calls/day. |

### T2.3 · Roman Republican Cities (ADS) subset

| | |
|---|---|
| **Download size** | **UNVERIFIED — blocking.** Cloudflare JS challenge; DataCite returns empty `sizes`. Needs a human browser session. |
| **Storage impact** | Unknown; likely multi-GB. Take **one field**, not both cities. |
| **License** | **ADS Terms and Conditions** (verified via DataCite) — *not* Creative Commons. Attribution, no resale; commercial research use permitted. The Cambridge companion is CC-BY-**NC**-SA and is the more restrictive of the two. |
| **Phases validated** | `SEGYConverter` at scale · dense multi-line `frame_id` scoping · time-slice / volume reconstruction · `interpretation/` against expert delineations |
| **Benchmark value** | **The only genuine dense-3D candidate** — 0.06–0.12 m traverse separation over 27 + 23 ha, RTK-GNSS and robotic total station. |
| **Preprocessing effort** | Medium–high. Large-volume SEG-Y; time-slice generation. |

Cost control: take only the **12.86 kB metadata ZIP** from the Cambridge
copy, not its 1.035 GB of time-slices — Subterra should generate those from
raw SEG-Y. Confirm first whether the anomaly shapefiles live inside those
time-slice ZIPs; if so, this changes.

**Do not schedule until the manual size check is done.**

---

## Tier 3 — optional or future

| Dataset | Size | Storage | License | Phases validated | Value | Preprocessing |
|---|---|---|---|---|---|---|
| **CMU-GPR** | ~12 GB (15 seq.) | 12–24 GB | CC-BY-**NC**-SA — blocks commercial use | `OdometryPosition` at scale · along-track `GeoTie` · repeat-pass consistency | Low-moderate. Along-track GeoTie is already covered by Guangzhou; traces are CSV, so it advances no native format. | Low (CSV) |
| **NSGeophysics/GPRdata** | 59 MB | 0.1 GB | **None declared** — no redistribution rights | Sensors & Software `.dt1`/`.hd` reader only | **Superseded for GSSI by T1.2.** Unique value now: 2 `.dt1` files. | Low |
| **Sentinel-2** | AOI | < 1 GB | Copernicus free-and-open | Satellite modality in `SensorType` | Deferred — no satellite modality is built | Low |
| **Morocco utilities/voids** | Small | < 0.1 GB | None declared | Image-domain detection only | Low — annotated B-scan images, no traces, no coordinates | N/A |
| **SERDP/ESTCP UXO** | Gated | — | US Gov, programme-mediated | None for GPR | **Out of scope.** EMI, not GPR — a new modality, not a new dataset | High |

**Tier 3 policy:** take CMU-GPR or NSGeophysics **only** in response to a
specific need, one or two sequences at a time, and never commit either to
git — CMU-GPR is non-commercial and NSGeophysics is unlicensed.

---

## Tier 0 — already local, 0 new bytes

INGV-UNISA SEG-Y + KMZ, and the Guangzhou IDS `.dt` archive
(`datasets/raw/zenodo/14637589/`).

These are the **regression gate**, not a benchmark: shapes 482×72 / 482×66,
depth 0→7.04665 m at 0.01465, z_std 0.904066 / 0.845445, |z|max 4.273256 /
4.361468, cells≥3 121/73, candidates 25/12, digests `23845e0a…` /
`2027a323…`. **No tier is permitted to change these numbers.** A change is
a scientific regression, not a result.

---

## Storage summary

| Tier | Download | On disk | Cumulative |
|---|---|---|---|
| 0 | 0 | already present | — |
| **1** | **684 MB** | **≈1.9 GB** | **≈1.9 GB** |
| 2 | ≈0.3–2 GB + ADS | ≈0.6–3 GB + ADS | ≈2.5–5 GB + ADS |
| 3 | opt-in | 0.1–24 GB | opt-in |

Tiers 0–2 fit comfortably in the ~42 GB available, with the ADS archive the
only real uncertainty. Tier 1 at ≈1.9 GB on disk is not a storage decision
at all.

---

## Execution order

1. **T1.1 (4TU)** — highest value per byte, and needs no new code. Ingest,
   confirm header conventions, decide the no-CRS representation.
2. **T1.2 (TU1208), IDS subset only** — 24 files through the existing
   reader. This is a real cross-instrument test of `ids_dt_converter` at
   near-zero cost.
3. **Run the Tier 0 regression gate.** Both of the above must leave it
   bit-identical.
4. **MALÅ `.rd3`/`.rad` reader** — validated against TU1208's 30 files and
   Hillside's 321.
5. **T1.3 (Hillside)** — ingest as `OdometryPosition`; add
   `LocalCartesianPosition` only with an explicit line-spacing `Assumption`.
6. **Manual browser check on ADS** to size T2.3, and on the TU1208 paper to
   settle the target inventory. Both are blocked on bot walls, not on effort.
7. **T2.1 (AHN)** once T1.1 has produced RTK tracks to derive AOIs from.

## What this suite cannot claim

Unchanged by verification, and worth restating because Tier 1 makes it
tempting to overreach:

- **No detection benchmark against excavated truth is possible from these
  datasets alone.** 4TU has trench truth but withholds its coordinates;
  ADS has positions but only expert interpretation. TU1208 is the sole
  candidate for a quantitative score, and only if its target inventory
  turns out to be published — which verification left in doubt.
  Until then, detection can be **characterised** (false-alarm rates, null
  comparisons) but **not scored against truth**.
- **Anomaly delineations are interpretation.** They belong in
  `interpretation/`, never in a ground-truth table.
- **A controlled test site is ground truth about the site, not about the
  detector.** Agreement there does not transfer to field surveys.
