# Hunt for the original KEC 2017–18 GPR survey data (EXTRI-2018-40-534.9607)

**Date:** 2026-10-05 · **Branch:** `research/yesan-kec-testbed-ground-truth` · **Scope:** find the raw (or minimally processed) GPR files from the 2017–18 MALA ProEx surveys of the KEC testbed, and the GPS coordinates taken when the objects were installed. No production code, manifest or scoring gate was changed.

## Result: `ONLY_PROCESSED_DATA_FOUND`

- **No raw trace data** (`.rd3`/`.rad`/`.mrk`/`.cor`/SEG-Y, or 3D-Radar files) from the 2017–18 surveys is publicly available anywhere I could reach. There is no sign it was ever released.
- **Processed radargrams do exist**, as images only:
  - 29 high-resolution B-scan figures (~2800×700 px) in the KEC report itself;
  - the processed figures in a paywalled 2019 paper from Seoul National University that used the same testbed's data.
- **No installation GPS coordinates** were found.
- **One new independent fact, outside the brief:** a 2021 journal paper places the KEC test site at **Yesan, near Sudeoksa IC**. Its construction plan gives design stationing for the testbed (below), which independently confirms the site identity and the abutment position.

---

## 1. Sources searched

| # | Source | Query / action | Outcome |
|---|---|---|---|
| 1 | The KEC report itself (216 pp., text extracted) | scanned for `.rd3`, `.rad`, `.mrk`, `.cor`, SEG-Y, 원시 (raw), 원자료, DB, 부록 (appendix), 첨부 (attachment), 과제번호 (project no.), 용역 (contract), file names | **No data appendix, no file names, no project/grant number** (the bibliographic page leaves "Contract or Grant No." and "Work Unit Code" blank, PDF p. 213). Credits (PDF p. 214): lead **윤완석 Yoon Wan-seok**; KEC Quality Test Center **정진덕 Jeong Jin-deok** (ch. 1, 5–7), **이진호**, **신동훈**, **고민재**; contractors **㈜지오스캔 Geoscan Co., 유영호 Yoo Young-ho** (ch. 2, 3, 5) and **서울대 산학협력단 (SNU), 민동주 Min Dong-joo** (ch. 5). Rights notice (PDF p. 215): no reuse of the contents "without the Corporation's approval" (공사의 승인없이 … 이용할 수 없습니다) |
| 2 | CODIL record OTKCRK190187 (detail page, in Chrome) | attachments | **The report PDF only.** No supplementary files |
| 3 | CODIL, related records | Google `codil.or.kr` + 534.9607 series + GPR/공동/포장하부 (under-pavement), 2015–2021 | Other KEC 534.9607-series reports (pavement-data integration 2020, bridge decks 2020, etc.): none is a follow-up on this testbed and none carries GPR data. RD-19-R3-003 (KISTEC 3D-GPR manual, OTKCRK211043) was **downloaded and checked**: a different organisation (Korea Infrastructure Safety Corp.) and a different testbed; no KEC or Yesan content |
| 4 | Zenodo API | 5 queries (KEC GPR, MALA ProEx cavity pavement, Korea cavity road, Yesan GPR, …) | Only Zenodo **21441974**, the 2021 survey already held. Nothing from 2017–18 |
| 5 | AI-Hub (Korea's national AI-data portal) | 3 GPR datasets (dataSetSn 71327, 71457, 71676) | Seoul roads 2015–22; Busan soft ground; building/tunnel/bridge rebar. **JPG/PNG images with bounding boxes only, no raw radar**; "내국인만 데이터 신청이 가능합니다" (Korean nationals only). None is the KEC testbed |
| 6 | data.ex.co.kr (KEC open data portal) and data.go.kr | GPR / 탐사 (survey) | Traffic, toll, construction, route GIS. **No GPR data** |
| 7 | ScienceON / DBpia / KCI / AURIC (Korean literature) | KEC authors (윤완석, 정진덕, 신동훈, 이진호), Geoscan 유영호, 실대형 테스트베드 (full-scale testbed), 수덕사 (Sudeoksa) | Conference papers only (below), with no data release |
| 8 | MDPI: Rhee et al. 2021 (*Remote Sens.* 13:1805) | Data Availability Statement, Acknowledgments | **No Data Availability Statement.** Funded by KECRI; field support "KECRI, GK engineering corporation and SHERPA E&C". Uses vehicle multichannel systems (Systems A and B), not the 2017–18 MALA cart |
| 9 | JEEG: Hwang, Kim, Li & Min 2019 (doi 10.2113/JEEG24.3.419), in Chrome via Crossref → SEG → GeoScienceWorld | abstract, availability | **Paywalled** ("Available to Purchase"). The abstract: "a 2D field data set acquired in a testbed in Sudeoksa, Korea". Not bought (a purchase is the user's decision) |
| 10 | SNU S-Space (institutional repository) | 13 queries: GPR/공동/테스트베드/수덕사/Sudeoksa, author names (Hwang Jongha, Kim Donggeon, Li Xiangyue, 황종하, 김동건) | **No GPR thesis from Min's group.** The authors' theses are seismic full-waveform inversion |
| 11 | Semantic Scholar | the JEEG paper and its 10 citing papers | None reuses or releases the Sudeoksa data |
| 12 | Google / web | EXTRI-2018-40-534.9607 (exact); KEC + testbed + GPR in Korean and English; Sudeoksa/Sodeoksa test site; 매설물 좌표 GPS 준공도 (buried-object coordinates, GPS, as-built drawings) | The exact report number finds no other host. The Sudeoksa query surfaced the JEEG paper. The KEC/Yesan query surfaced Bae 2021 (§6) |
| 13 | koreascience: Bae 2021, J. Korean Soc. Surveying, Geodesy, Photogrammetry and Cartography (JAKO202104851450470), PDF downloaded and rendered | site location and plan | **Site identity and design stationing found** (§6). The text layer is garbled (broken font encoding), so it was read from the rendered page |

**Blocked or limited:**
- GeoScienceWorld/SEG (JEEG full text) is a **paywall**.
- AI-Hub is **restricted to Korean nationals** (and irrelevant anyway).
- MDPI blocks WebFetch (HTTP 403) but was read in Chrome.
- KISTI DataON was searched only through the web (no API key); no hit.
- No dead links were hit for the candidate sources.

## 2. Raw datasets discovered

**None.** No file in `.rd3/.rad/.mrk/.cor/.gps`, MALA project, SEG-Y or 3D-Radar (`.3dra`/Examiner) format from the 2017–18 campaigns was found in any repository, publisher supplement or institutional archive listed above.

## 3. Processed datasets discovered

| Item | Where | What it is | Benchmark use |
|---|---|---|---|
| **29 B-scan images**, ~2800×700–1240 px JPEG (KEC Figs. 5.3–5.20: single-channel 100/250/500 MHz, lines A and B, campaigns 1 and 4, per section) | KEC report PDF pp. 112–126; extracted to `datasets/raw/references/kec_extri_2018_40/ch5_bscans/` (git-ignored) | **Processed** (Table 5.4: time-zero muting, bandpass, background removal, Kirchhoff migration at 0.075 m/ns, gain), **depth-converted**, with a 0–30 m per-section "Distance (m)" axis and the **design target outlines drawn over the data by the authors** | **Qualitative only.** The images carry the authors' own registration (outlines placed on the radargram), so scoring against them would test the overlay, not a detector. The colour scale is not calibrated, the traces are not recoverable, and the depth axis embeds an assumed velocity |
| 3D-Radar DXG1820 B-scans and depth slices (KEC Figs. 5.22–5.30) | KEC PDF pp. 128–134 | **Processed** (3D-Radar Examiner, Table 5.6); ~1400–1600 px | Qualitative only |
| Rhee 2021 Figs. 6–9 | MDPI | plan views / B-scans from vehicle Systems A and B (not MALA) | Qualitative only; a different survey |
| Hwang et al. 2019 figures | JEEG (paywalled) | "2D field data set … Sudeoksa", processed for polarity analysis | Not inspected (paywall) |

Nothing here is raw data. Image-derived radar values are not raw data and are not treated as such.

## 4. File formats

| Survey | System (KEC report) | Native format | Public? |
|---|---|---|---|
| Single-channel, 4 campaigns 2017-06 → 2018-08 | MALA ProEx + 100/250/500 MHz shielded antennas, wheel encoder, cart (Tables 5.1–5.3) | MALA `.rd3` + `.rad` header (+ `.mrk` markers if used; `.cor` only with GPS) | **No** |
| Multichannel, same 4 campaigns | 3D-Radar DXG1820, step-frequency 200–3000 MHz, 20 channels at 75 mm, 1.5 m swath (Table 5.5) | 3D-Radar Examiner project (`.3dra`) | **No** |
| Processed figures | — | JPEG inside the PDF | yes (images only) |

## 5. Acquisition metadata (from the report; no file exists to confirm it)

| Field | Value | Source (PDF p.) |
|---|---|---|
| Dates | 1: 2017-06-09/15 (before paving) · 2: 2017-09-20/23 (just after) · 3: 2018-04-25/27 (after winter) · 4: 2018-08-06/08 (age 1 yr) | Table 5.2, 110 |
| Antennas / separation | 100 MHz 0.5 m · 250 MHz 0.36 m · 500 MHz 0.18 m; 100 MHz only in campaigns 3–4 | Tables 5.2–5.3, 110–111 |
| Trace spacing | 0.05 m (0.02 m in campaign 2 for 250/500 MHz) | Table 5.3 |
| Time window / samples | ~60 ns (120.1 ns for 100 MHz, campaign 4); 230–898 samples | Table 5.3 |
| Stacks | 4–16 | Table 5.3 |
| Lines | **A, B and C** in campaign 1 (line C is not described further); A and B thereafter, "two lines set centred on the buried objects" | survey matrix, PDF p. 74 (printed 52); 110 |
| Direction | not stated; figures plot 0 → 30 m per section | — |
| Trace 0 = testbed start? | not stated. The processed images' axis starts at 0 m per section, and a strong shallow reflection sits at ~0.3 m on line B, where the start steel plate is (0.0–0.5 m). That suggests, but does not prove, that profiles start at the section start | Fig. 5.4 (p. 113) |
| Time zero | applied in processing as a muting offset of −separation/c | Table 5.4, 112 |
| Migration velocity | 0.075 m/ns (processing parameter) | Table 5.4 |
| Coordinates | none recorded for GPR; positioning by wheel odometer | Table 5.1 |
| Number of traces / profile length | not stated (implied ~600 traces per 30 m section at 0.05 m) | — |

## 6. Registration evidence

**New and independent (Bae 2021).** Bae, K.H. (2021), "지하공간탐사기기 성능검사 테스트베드 구축 연구" (A study on the construction of a testbed for performance inspection of underground surveying equipment), *J. Korean Soc. Surveying, Geodesy, Photogrammetry and Cartography*, koreascience JAKO202104851450470, p. 527. Held git-ignored at `datasets/raw/references/Bae2021_JAKO202104851450470.pdf` (Fig. 5 extracted as `Bae2021_fig5_test_road_plan.png`); public at https://koreascience.kr/article/JAKO202104851450470.pdf.

- **Site identity:** "한국도로공사 '도로안전시설 성능시험장'은 고속도로 유휴부지인 충남 예산군 수덕사IC 인근에 위치한다". In English: KEC's road-safety-facility performance test site is on idle expressway land near **Sudeoksa IC, Yesan-gun, Chungnam**. The paper describes the same testbed: asphalt 30 m, approach slab 30 m, concrete 30 m, bridge deck 20 m asphalt + 10 m LMC; depth to 3 m; 5.0–6.6 m wide. This is an independent published source tying the KEC report's anonymised "00000IC" site to Yesan, and so to the Zenodo "Yesan full-scale test site".
- **Design stationing (Fig. 5, construction plan):**
  - the testbed runs **STA 0+104.47 → 0+194.47** (90 m); testbed 0 m = STA 0+104.47;
  - asphalt pavement 0+104.47–0+149.22 (44.75 m, including the 9 m asphalt-side approach slab);
  - **abutment 0+149.22–0+149.72**, i.e. testbed **44.75–45.25 m**. This independently confirms the 44.7–45.3 m read off KEC Fig. 4.7;
  - approach + buffer slab 0+149.72–0+164.47 (14.75 m);
  - plain concrete 0+164.47–0+179.47; CRCP 0+179.47–0+194.47.

  These are **design stations**, not installation GPS.

**What is still missing for a 2017–18 registration:** the raw files and a statement of where each profile started and in which direction. The report's per-section 0–30 m axes and the start-plate reflection are consistent with "profile 0 = section start, run A→A′ / B→B′". They are not a statement.

The steel plate was installed **as a survey-start fiducial** (PDF p. 84). Using it to fix trace 0 would therefore not be circular, provided it is then **excluded from every evaluated target**. Any other alignment to target hyperbolas would be circular and is ruled out.

## 7. Target-coordinate evidence

Unchanged. Targets come from KEC Tables 4.6–4.8 and Figs. 4.5/4.7/4.10, transcribed in `evidence/yesan/`; positions are ±0.1 m figure readings, **grade B**. Bae 2021 confirms the section layout and the abutment from an independent construction plan. It gives no per-object coordinates, so **no grade change**.

## 8. GPS evidence

- KEC Table 4.22 (PDF p. 98) says plan positions were measured with GPS during installation ("GPS수신 좌표를 이용하여 매설물 평면위치 측정"). The coordinates themselves are **not published**:
  - not in the report or its CODIL record;
  - not in Bae 2021 (design stations only);
  - not on data.ex.co.kr or data.go.kr;
  - not in any SHP/DXF/DWG/CSV/XLSX found online.
- They presumably sit with the installation contractor (the report's 용역/contract part: Geoscan Co. for design and construction) and the KEC Quality Test Center.
- **Evidence grade stays B.**

## 9. Benchmark suitability (if the raw files were obtained)

| Capability | Ground truth that would support it | Status today |
|---|---|---|
| A. Detection precision/recall | **Recall:** KEC table/figure targets per line, grade B, ±0.1 m. **Precision:** only if the list is exhaustive, which it isn't yet (approach slab 34/36/38; moisture sensors) | no raw data |
| B. Longitudinal localisation error | targets ±0.1 m (figure readings), so errors below ~0.15 m are not resolvable; needs trace 0 tied to the start fiducial and the direction stated | no raw data |
| C. Depth error | depths below the pavement surface (text / table / figure); `measured_to` unresolved except EPS tops; also needs time zero and an **independent** velocity (the report's 0.075 m/ns is a processing choice) | no raw data |
| D. Candidate-generation validation | same as A, per line, per frequency, per campaign. Four campaigns × 3 frequencies × 2 lines is an unusually rich design | no raw data |
| E. Time-zero validation | raw traces with a known air/ground wavelet; the shielded antennas' direct wave; pavement surface at depth 0. Possible with raw data; impossible from the images (already time-zero-muted) | no raw data |
| F. Line-specific false positives | needs exhaustiveness per line, lateral placement (several "line B" objects sit 0.5–1.0 m off line), and the 1.5 m line spacing (A objects may appear on B) | no raw data |

The processed images support **none** of A–F quantitatively. They are suitable only for **qualitative** comparison (e.g. whether a detector's output looks like the authors' published B-scan), and they already carry the authors' target overlay.

## 10. Remaining uncertainties

- Whether the raw 2017–18 files still exist and with whom: KEC Quality Test Center (Jeong Jin-deok), Geoscan Co. (Yoo Young-ho), or SNU (Min Dong-joo's lab, which certainly processed a Sudeoksa 2D line for JEEG 2019).
- Which campaign and frequency the JEEG paper used.
- Line C (campaign 1) is undocumented.
- Whether objects changed between the 2017 surveys (campaign 1 was **before paving**) and later campaigns.
- KEC's reuse restriction: data or contents may need KEC's written approval for use and publication.

## 11. Exact download / reproduction instructions

```bash
# KEC report (public; CODIL serves it directly; earlier failures were a TLS-chain issue only)
curl -L -o KEC_EXTRI-2018-40-534.9607.pdf \
  https://www.codil.or.kr/filebank/original/RK/OTKCRK190187/OTKCRK190187.pdf
# processed B-scan figures = embedded JPEGs on PDF pp. 112-126 (and 128-134 for 3D-Radar);
# extract with pypdf: PdfReader(...).pages[p-1].images, keeping images >= 2700 px wide.

# Bae 2021 (site identity + design stationing; text layer garbled -> render the page)
curl -L -o Bae2021.pdf https://koreascience.kr/article/JAKO202104851450470.pdf
#   p. 3 (journal p. 527): §3.2 text and Fig. 5 (embedded image, 1114x664)

# JEEG 2019 (paywalled): https://doi.org/10.2113/JEEG24.3.419
```

The raw survey data cannot be downloaded; it has to be requested (below).

### Who to contact

1. **KEC Research Institute (도로교통연구원), Quality Test Center:** Jeong Jin-deok (정진덕; wrote ch. 5) and Yoon Wan-seok (윤완석; project lead). Address: 경기도 화성시 동부대로 922번길 208-96; tel +82-31-8098-6161 (report colophon). They own the data and its reuse approval.
2. **Prof. Min Dong-joo (민동주), Dept. of Energy Systems Engineering, Seoul National University:** SNU contractor for ch. 5 and senior author of the JEEG 2019 Sudeoksa paper. Most likely to hold a cleanly organised copy of at least one line.
3. **Geoscan Co. (㈜지오스캔), Yoo Young-ho (유영호):** the survey contractor; likely holds the raw MALA project files and the installation GPS.
4. **Dr Chang-Geun Oh (Hanseo Univ.):** already the 2021 contact, and may be able to route to KEC.

**Minimum request:** for one campaign (ideally 4, 2018-08), line A and line B at 250 and 500 MHz:
- the raw `.rd3` + `.rad` (+ `.mrk`) files;
- where each profile started (the start steel plate on B?) and the direction;
- whether the wheel was calibrated;
- the installation GPS coordinates of the objects;
- permission to use the data in a published benchmark.

## Implementation plan (only if raw data arrives; nothing enabled now)

1. Ingest with the existing MALA converter; record campaign, frequency, line and `.rad` metadata; compare against KEC Tables 5.2–5.3. Reject any file whose separation, window or interval contradicts them.
2. Build a **2017–18 frame** per line. Origin = the start fiducial, by **author statement** or, failing that, by the steel-plate reflection on line B. In the second case the plate becomes a calibration point, is excluded from evaluation, and line A gets no origin until stated. Scale = the wheel calibration, checked against the plate-to-abutment design distance only as a *consistency* test, never a fit.
3. Score recall/localisation against the grade-B targets with a radius ≥ 0.15 m (the figure-reading floor), per line and per campaign. Precision and per-metre false alarms stay off until the list is attested exhaustive.
4. Depth: off until `measured_to` is resolved and a velocity independent of the evaluated hyperbolas exists.
5. A verification script would sit in `scripts/` and read only the git-ignored raw files. **The Yesan gate is not touched by any of this**: a 2017–18 dataset would get its own manifest.

## Final question

> *Can Subterra use the original KEC 2017–2018 survey as a scientifically defensible quantitative benchmark without relying on the unresolved 2021 Yesan registration?*

**Not today.** The ground truth is good enough (grade B, ±0.1 m, independently corroborated layout), and a 2017–18 benchmark would sidestep the 2021 registration problem. But **the raw radar traces are not publicly available**, and the published radargrams are processed, depth-converted images with the authors' target overlay drawn on them. Using them quantitatively would score the authors' interpretation, not a detector.

**The smallest missing piece:** the raw MALA files (`.rd3`/`.rad`) for at least one campaign, line A and line B, together with a one-line statement of where each profile started and in which direction. With those, the start steel plate (an installed survey fiducial) would give a non-circular origin on line B. If KEC/Geoscan/SNU supply that, a 2017–18 recall-and-localisation benchmark becomes possible without any reference to the 2021 files.

### Side finding to fold into the Yesan manifest later (not done here)

Bae 2021 independently places the KEC testbed at Yesan (Sudeoksa IC) and gives design stationing with the abutment at testbed 44.75–45.25 m. This **strengthens `yesan-site-identity`** (the KEC testbed is at Yesan). It does not say that the Zenodo 2021 files were recorded on the same lines, or that the objects were unchanged in 2021, and it does nothing for the 2021 trace registration. Updating that open question's wording is a separate, explicitly approved change.
