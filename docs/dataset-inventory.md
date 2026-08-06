# Dataset inventory

Authoritative human-readable view of every dataset available to Subterra.
The machine-readable source of truth is
[`datasets/metadata/benchmark_manifest.json`](../datasets/metadata/benchmark_manifest.json);
this document is generated from the same facts and should be updated with it.

**Inventory date:** 2026-08-07 · **Total on disk: 2.65 GB**

Each entry describes **what is actually on disk**, which is not always what
the publisher's record describes — `guangzhou-ids` is a 2.9 MB subset of a
3.8 GB archive, and saying otherwise once already led this plan astray.

Every dataset below carries a `PROVENANCE.json` beside its archive
recording source URL, DOI, citation, license and its source, acquisition
timestamp, retrieval method, archive SHA-256, and a full member list with
per-file CRC32.

---

## Summary

| Tier | ID | Name | License | Download | On disk | Status |
|---|---|---|---|---|---|---|
| T1 | `4tu-nl-utility` | NL utility surveying + trench ground truth | **CC0-1.0** | 402.6 MB | 1,430.5 MB | acquired |
| T1 | `tu1208-ifsttar` | TU1208 / IFSTTAR test site | **CC-BY-4.0** | 200.7 MB | 897.7 MB | acquired |
| T1 | `hillside-lancaster` | Hillside GPR (Lancaster) | **CC-BY-4.0** | 80.4 MB | 200.4 MB | acquired |
| T0 | `guangzhou-ids` | Guangzhou IDS `.dt` — **subset** | CC-BY-4.0 | 2.9 MB | 4.9 MB | **partial** |
| T0 | `ingv-unisa` | INGV-UNISA Site 1 | **UNVERIFIED** | — | 119.6 MB | local |

On-disk exceeds download because archives are kept alongside their
extraction; 4TU additionally nests 13 inner ZIPs that are also extracted.

---

## T1.1 · `4tu-nl-utility`

| | |
|---|---|
| **Name** | Ground Penetrating Radar dataset with ground-truth data of utility surveying activities |
| **Source** | 4TU.ResearchData · [10.4121/96303227-…v1](https://doi.org/10.4121/96303227-5886-41c9-8607-70fdd2cfe7c1.v1) · ter Huurne, R. (2023) |
| **License** | **CC0-1.0**, verified from the record's JSON-LD and corroborated by DataCite. No restrictions. |
| **Download size** | 402,555,260 B · SHA-256 `4281e108a440a191…` |
| **On-disk size** | 1,430.5 MB (archive + outer extract + 13 inner extracts) |
| **File formats** | `.sgy` ×759, `.png` ×247, `.csv` ×1, `.pdf` ×1, `.txt` ×1 |
| **Number of files** | 1,009 |
| **CRS** | **None declared.** Trace headers carry WGS84 geographic coordinates as **float32 in NMEA `ddmm.mmmm`** at SourceX/SourceY (bytes 73–80). The SEG-Y coordinate-units code is `2` ("arc seconds"), which is **wrong** for that encoding. Subterra asserts no EPSG. |
| **Survey geometry** | 125 activities across 13 sites; 2–26 lines each, ~1 m apart, perpendicular to utilities; 0.02 m trace spacing; 512 samples/trace; air-launched 500 MHz; Spectre SP80 RTK GNSS + wheel encoder. **716 files georeferenced at trace 0, 43 not.** |
| **Supported phases** | `SEGYConverter` (needs a little-endian path) · `GeographicPosition` · `NoPosition` · `CRSProvenance` · `preprocessing` · anomaly detection · `interpretation/` |
| **Benchmark role** | Primary spatial-truth dataset — the only one combining SEG-Y, RTK GNSS, and utilities confirmed by trial trench. |

**Verified header facts** (all 759 files scanned):

- **Little-endian** SEG-Y, uniformly. Format code `3` (int16), 512 samples.
- Sample-interval field is in **picoseconds**, not the standard microseconds:
  97 ps ×92 files, 98 ps ×582, 195 ps ×83, 117 ps ×2 → time ranges of
  **49.7, 50.2, 99.8 and 59.9 ns**. The Readme's "50 ns" is the majority
  case, not universal.
- `GroupX` is **odometer distance in millimetres** (0, 20, 40, …), i.e. an
  along-track measure.
- All 716 georeferenced positions fall inside the Netherlands bounding box.

**Limitations**

- **759 `.sgy` present, but the article abstract states 959 radargrams.**
  Unexplained; the archive is internally consistent and complete per its
  own Readme, so this is a discrepancy in the publication, not a truncated
  download.
- **The existing `SEGYConverter` fails on these files** (`segyio`
  `RuntimeError: trace count inconsistent with file size`) because it
  assumes big-endian. This corrects the earlier "reads today" estimate.
- **Ground truth carries no coordinates** — withheld for confidentiality,
  joined to radargrams only by `LocationID`.
- Utility material blank for 82/125 activities; diameter blank for 65/125.
- One antenna, one frequency, one manufacturer.

**Assumptions**

- The NMEA `ddmm.mmmm` decoding is **inferred**, not declared. It is
  corroborated by the GNSS track length agreeing with the odometer length
  (6.3 m vs 6.08 m on the probe line) and by every position landing in the
  Netherlands — but the file does not say so.
- `Metadata.csv` publishes **ground relative permittivity per activity**
  (8.16–19.46, mode 9.00). That is the only defensible basis for a
  velocity here, and it is a **site estimate supplied by the data
  provider**, not a measurement of the subsurface. Any depth derived from
  it is derived, not measured.

---

## T1.2 · `tu1208-ifsttar`

| | |
|---|---|
| **Name** | Supplementary Files: TU1208 Open Database of Radargrams — The Dataset of the IFSTTAR Geophysical Test Site |
| **Source** | Zenodo · [10.5281/zenodo.1211173](https://doi.org/10.5281/zenodo.1211173) · Dérobert, X. & Pajewski, L. (2018) |
| **License** | **CC-BY-4.0**, from Zenodo record metadata. Attribution only. |
| **Download size** | 200,679,334 B · MD5 **verified** against Zenodo (`5992698c…`) · SHA-256 `997b2fd2d3157e8c…` |
| **On-disk size** | 897.7 MB |
| **File formats** | `.dzt` ×40, `.rd3` ×15, `.rad` ×15, `.dzx` ×14, `.dt` ×12, `.asc` ×12, `.mgp` ×1, `.m` ×1 |
| **Number of files** | 110 |
| **CRS** | **None.** A local site grid is implied but is not recorded in any file. Subterra asserts no EPSG. |
| **Survey geometry** | **67 native radargrams** (64 unique stems, 3 in two formats) across 5 material zones — GNEISS0-20, GNEISS14-20, LIMESTONE, MULTI-LAYER, SILT. Frequencies 200/250/270/350/400/500/600/800/900 MHz. Three vendors: GSSI, MALÅ, IDS. |
| **Supported phases** | **`IDSDTConverter` — works unchanged on the 12 `.DT` files** · `converters/registry` multi-vendor dispatch · future `.dzt` and `.rd3` readers |
| **Benchmark role** | Multi-vendor format coverage and cross-instrument consistency over a controlled site. |

**Identity: verified 2026-08-07.** The paper's abstract (OpenAlex API)
states the raw-profile archive is enclosed as supplementary material, and
every countable claim matches — 67 profiles, three producers, 200–900 MHz.
Header timestamps resolve into three coherent campaigns over one constant
set of material zones: 1998/99 GSSI (26 files), **2005-03-24 IDS (all 12,
one field day 09:40→15:07)**, 2017 GSSI SIR-4000 (14 files).

**Limitations**

- **The buried-target inventory is NOT verified.** It lives in the paper
  body, which is behind bot protection. TU1208's *format* value is
  established; its *ground-truth* value is not. **Plan no detection score
  against it.**
- `List_Database_V1.ods`, the archive's own index, is **missing** — only
  its stale lock file was packaged.
- No embedded metadata names IFSTTAR or Nantes. MALÅ `SITE`, `OPERATOR`,
  `CUSTOMER` and `COMMENT` fields are empty; the GSSI `.DZX` records only
  `SIR4K` and `gridId=Grid`.
- The paper's "eleven parallel lines" is not derivable from the archive.

---

## T1.3 · `hillside-lancaster`

| | |
|---|---|
| **Name** | Hillside GPR dataset |
| **Source** | Zenodo · [10.5281/zenodo.8253179](https://doi.org/10.5281/zenodo.8253179) · Binley, A., Lancaster University |
| **License** | **CC-BY-4.0**. Attribution only. |
| **Download size** | 80,291,265 B (+151,126 B PDF) · both MD5s **verified** · SHA-256 `66f13b28e4ff6379…` |
| **On-disk size** | 200.4 MB |
| **File formats** | `.rd3` ×321, `.rad` ×321, `.mrk` ×321, `.em` ×321, `.cor` ×321, `.add` ×321 |
| **Number of files** | 1,926 |
| **CRS** | **EPSG:27700 declared for the plot corners only**, tabulated in the description PDF with elevations in m aOD (ODN). Per-trace positions are **local grid only** — all 321 `.cor` GNSS files are 0 bytes. Provenance would be `supplied_by_caller`. |
| **Survey geometry** | 6 plots, 321 lines, **two orthogonal directions per plot** on a **≈0.4 m grid**. 0.019011 m trace spacing, 336 samples, 66.335 ns window, distance-triggered measuring wheel. Plots HE and HF additionally at 250 and 800 MHz. 4 surveyed control points per plot. |
| **Supported phases** | future `.rd3`/`.rad` MALÅ reader · `OdometryPosition` · `LocalCartesianPosition` · `Assumption` |
| **Benchmark role** | MALÅ format coverage; local-grid acquisition with surveyed control points. |

**Limitations**

- **No reader exists.** `.rd3` is in `KNOWN_UNSUPPORTED_FORMATS`; ingestion
  is blocked until a MALÅ converter is written.
- **No satellite positioning of any kind** — every `.cor` is 0 bytes.
- Promoting local coordinates to EPSG:27700 requires a **2D similarity or
  affine tie**. `ingestion/geo_tie.py` interpolates against `along_track_m`
  only. **Not implemented, by instruction.**

**Assumptions**

- Cross-line offset is **not recorded in any machine-readable field**.
  Building `LocalCartesianPosition` requires a caller-supplied
  line-spacing assertion recorded as an `Assumption` on the frame.
  `OdometryPosition` needs no assumption at all.

---

## T0 · `guangzhou-ids` — **partial holding**

| | |
|---|---|
| **Source** | Zenodo · [10.5281/zenodo.14637589](https://doi.org/10.5281/zenodo.14637589) · GPR Group, Guangzhou University |
| **License** | CC-BY-4.0 |
| **Download size** | **2,927,533 B of a 3,784,747,664 B archive** (HTTP Range subset) |
| **On-disk size** | 4.9 MB · **10 `.dt` files**, 70 members |
| **CRS** | None. Wheel odometry only. |
| **Benchmark role** | IDS `.dt` format reference; part of the Tier 0 regression corpus. |

**Limitations** — **No tunnel data is held locally.** The published record
covers three tunnels; the local subset is `pipe` and `rebar` only. Tunnels
would require the full ~3.8 GB download. No coordinates, so it can never
participate in fusion; every depth is derived from a caller-supplied
velocity.

## T0 · `ingv-unisa` — pinned regression baseline

**License UNVERIFIED** — check the original acquisition record before any
redistribution. 119.6 MB local. SEG-Y headers carry projected positions
(authoritative), KMZ track is the WGS84 fallback.

**No tier may change these numbers:** shapes 482×72 / 482×66 · depth
0→7.04665 m @ 0.01465 · z_std 0.904066 / 0.845445 · |z|max 4.273256 /
4.361468 · cells≥3 121/73 · candidates 25/12 · digests `23845e0a…` /
`2027a323…`.

Establishes false-alarm rates only — no ground truth. The ring z-score
saturates with target width, so broad coherent targets are structurally
undetectable at |z|≥3.

---

## Roadmap coverage

Capability → which datasets can exercise it, given what is on disk today.

| Capability | Covered by | Status |
|---|---|---|
| SEG-Y ingestion (big-endian) | `ingv-unisa` | ✅ working |
| SEG-Y ingestion (**little-endian**) | `4tu-nl-utility` | ❌ **converter gap** |
| IDS `.dt` ingestion | `guangzhou-ids`, `tu1208-ifsttar` | ✅ working, now on two instruments |
| MALÅ `.rd3`/`.rad` ingestion | `hillside-lancaster` (321), `tu1208-ifsttar` (15) | ❌ **converter gap** |
| GSSI `.dzt` ingestion | `tu1208-ifsttar` (40) | ❌ converter gap |
| `GeographicPosition` | `4tu-nl-utility`, `ingv-unisa` | ✅ |
| `ProjectedPosition` | `ingv-unisa` | ⚠️ no *declared* CRS anywhere on disk |
| `OdometryPosition` | `guangzhou-ids`, `hillside-lancaster` | ✅ |
| `LocalCartesianPosition` | `hillside-lancaster` | ⚠️ needs a line-spacing assumption |
| `NoPosition` | `4tu-nl-utility` (43 files) | ✅ |
| `CRSProvenance.NONE` | `4tu-nl-utility`, `tu1208-ifsttar` | ✅ |
| GeoTie (along-track) | — | ⚠️ no dataset on disk supplies along-track control points |
| GeoTie (**2D corners**) | `hillside-lancaster` | ❌ **not implemented, by instruction** |
| **Cross-CRS fusion** | — | ❌ **no dataset on disk has a declared projected CRS** — still fixture-only |
| LiDAR / DEM / orthophoto | — | ❌ Tier 2 (AHN, Copernicus) |
| Excavated ground truth | `4tu-nl-utility` | ⚠️ present but **without coordinates** |
| Controlled-site ground truth | `tu1208-ifsttar` | ⚠️ target inventory unverified |
| Tunnels | — | ❌ in the Guangzhou record, not in the local subset |
| 3D reconstruction | `hillside-lancaster` (0.4 m orthogonal grids) | ⚠️ blocked on the MALÅ reader |
| Multi-frequency comparison | `hillside-lancaster` (250/500/800), `tu1208-ifsttar` (200–900) | ⚠️ blocked on readers |
| Multi-vendor consistency | `tu1208-ifsttar` | ⚠️ 1 of 3 vendors readable today |

### What Tier 1 changed

**Gained:** real MALÅ and GSSI corpora under permissive licenses; a second
independent IDS instrument; the first dataset with excavated ground truth;
a genuine `NoPosition` population; two datasets that declare no CRS.

**Still missing after Tier 1** — and the reason Tier 2 exists:

1. **No dataset on disk has a declared projected CRS**, so cross-CRS
   fusion remains fixture-tested only. AHN LiDAR (T2.1) is the fix.
2. **No along-track control points**, so the implemented GeoTie path has
   no real data to run against.
3. **No surface modality at all** — no LiDAR, DEM, or imagery.
4. **No coordinate-bearing ground truth**, so detection can be
   characterised but not scored.

### Immediate consequence for implementation

Three converter gaps now block Tier 1 ingestion, in priority order:

1. **Little-endian SEG-Y** — unblocks 759 files and the highest-value
   dataset. Smallest change: an endianness-aware read path plus
   picosecond sample-interval handling and NMEA coordinate decoding.
2. **MALÅ `.rd3`/`.rad`** — unblocks 336 files across two independent
   sites. `.rad` is plain-text `KEY:value`, `.rd3` is raw int16.
3. **GSSI `.dzt`** — unblocks 40 files; `readgssi.m` in the TU1208 archive
   is a reference implementation of the header layout.

Per instruction, none of these has been started.
