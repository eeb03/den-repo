# Vertical registration evidence audit

**Question.** Can any existing Subterra holding, or any external open dataset,
independently supply the vertical/depth relationship that would turn the
validated GPR + DEM horizontal fusion
([`multimodal-fusion-dataset-selection.md`](multimodal-fusion-dataset-selection.md))
into a genuine 3D subsurface model?

**No platform state was changed.** No declaration, readiness state,
converter, dataset record, schema or production default was touched. This is
a search-and-evaluate stage, not an implementation stage.

**Method.** Reused, not reopened: BHRS, Wurtsmith AFB, TestUM, the
3000-antenna lysimeter, CGISS FMCW, and the RGPR curated index were already
exhaustively audited in
[`external-calibration-dataset-audit.md`](external-calibration-dataset-audit.md)
and are not re-searched here — their findings are carried forward unchanged
in §2. **One lead from that audit was explicitly marked "promising,
unaudited": Grimsel Test Site.** This stage audits it, live, with working web
access this session did not have before. §3 is the new work.

---

## 1. The eight criteria, as a checklist

Every candidate below is scored against exactly these, and a candidate that
fails even one is not treated as complete:

| # | Criterion |
|---|---|
| C1 | Same physical site as the GPR + DEM (4TU + AHN), where possible |
| C2 | Independent surface elevation |
| C3 | Independently measured subsurface depth or reflector position |
| C4 | Documented time-zero or acquisition delay, where applicable |
| C5 | Known propagation velocity, or enough independent geometry to determine it |
| C6 | No fitted value derived from the same GPR reflections being validated |
| C7 | Open raw data, if possible |
| C8 | Capable of entering Subterra's existing provenance/readiness architecture (`VerticalDatum`, `origin_offset`, `CRSProvenance`) |

## 2. Carried forward, unchanged (already audited)

| Candidate | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **BHRS** | ❌ different site | ❌ | publication only | picked, ±2 ns, not independent of signal | porosity-log-derived, genuinely independent | ✅ (porosity logs) | ❌ **site suspended, HTTP 410, zero downloadable files across 1,245 archived URLs** | n/a — no data | **Level 1. Scientifically the strongest case on paper, operationally unusable.** |
| **Wurtsmith AFB Line 1** | ❌ | ❌ | none | stated in EBCDIC header ("first break at near offset") — a pick, not measured | ✅ 25-fold multi-offset, moveout-derived, **depth-independent** | ✅ | ✅ **16.6 MB SEG-Y in hand** | ✅ readable by existing SEG-Y converter | **Validates velocity-from-moveout machinery. No boreholes, no reflector truth. Does not satisfy C3.** |
| **TestUM (PANGAEA 971978)** | ❌ | ✅ geoid+ellipsoid per borehole | controlled freezing front only, **not surveyed discrete targets** | ✅ documented air-WARR procedure; **numeric value INCONCLUSIVE** (Stage 29: 2 of 25 files pass slope check, disagree by 1.12 ns) | constrainable via crosshole traveltime, conditional on t0 | ✅ (air-path, not subsurface) | ✅ **raw DZT files downloaded and converted** | ✅ GSSI converter reads it; borehole position schema does not yet exist | **Best-documented calibration *method* held. Fails C1, C3 (weak), and C4 in practice.** |
| **3000-antenna lysimeter** | ❌ | n/a | n/a | ✅ **measured, t₀ = 30.604 ± 0.004 ns** | 0.4% check | ✅ | ❌ **on request only** | n/a — instrument-specific, not transferable | **The only true measured d≈0 anchor found anywhere. Not obtainable.** |
| **CGISS FMCW** | ❌ | n/a | calibration spheres | n/a | n/a | ✅ | ✅ downloadable | ❌ wrong modality (FMCW, not time-domain) | **Ruled out — modality mismatch.** |
| **RGPR curated index (20 datasets)** | ❌ (all) | varies | **none** carry borehole control or documented depth truth | **none** document time-zero | Frenke has a CMP (depth-independent); rest do not | n/a | mostly open | n/a | **Confirms the negative: no dataset in a curated, community-maintained open-GPR index satisfies C3+C4 together.** |
| **Midtdalsbreen** | ❌ | n/a | ❌ glacier ice, no boreholes, no surveyed targets | ❌ | ❌ | n/a | ✅ Figshare | n/a | **Wrong evidence type.** |
| **Florida / karst / urban hydrogeophysics** | ❌ | — | ❌ nothing found | — | — | — | — | — | **Nothing found, confirmed again as a negative result, not re-searched.** |

None of these satisfies more than four of the eight criteria simultaneously,
and every one already fails C1.

## 3. New this stage — Grimsel Test Site, audited live

**Flagged "promising, unaudited" in the prior audit. Audited here with live
web access.**

### 3.1 Identity

Doetsch, J. et al. (2020), *Characterizing a decametre-scale granitic
reservoir using ground-penetrating radar and seismic methods*, **Solid
Earth 11, 1441–1455**,
[10.5194/se-11-1441-2020](https://doi.org/10.5194/se-11-1441-2020) — Grimsel
Test Site, Switzerland, operated by Nagra (Swiss radioactive-waste disposal
cooperative), part of the ETH Zurich "In-Situ Stimulation and Circulation"
(ISC) deep underground laboratory programme.

Companion geological data descriptor: Krietsch, H. et al. (2018),
*A comprehensive geological dataset describing a crystalline rock mass for
hydraulic stimulation experiments*, **Scientific Data 5, 180269**,
[10.1038/sdata.2018.269](https://doi.org/10.1038/sdata.2018.269) — read in
full via PMC ([PMC6259022](https://pmc.ncbi.nlm.nih.gov/articles/PMC6259022/)),
open access, CC-BY 4.0.

### 3.2 What is genuinely there — the first GPR+seismic+borehole same-site combination found

| Criterion | Finding | Class |
|---|---|---|
| **C1 — same site as 4TU+AHN** | **No.** Grimsel is an underground rock laboratory in the Swiss Alps; 4TU is a surface utility survey in the Netherlands. **Cannot unblock 4TU regardless of what else it offers.** | — |
| **C2 — independent surface elevation** | **Not applicable in the 4TU/AHN sense.** Grimsel is a tunnel/gallery network, not an open-air survey with a topographic DEM overhead. A Swiss national coordinate origin is stated (X=667400, Y=158800, Z=1700, per the geological descriptor's visualisation tool), but this is a **facility survey control point**, not an independent terrain-surface model of the kind AHN provides. | **different evidence category, not a substitute** |
| **C3 — independently measured subsurface depth/reflector position** | **Yes.** Shear-zone and fracture positions are established from **core logging and optical televiewer (OPTV) imaging** in the boreholes — a physically different measurement from either GPR or seismic, obtained before the geophysical interpretation. Two INJ (injection) boreholes and four GEO (geophysical) boreholes are all geodetically surveyed. | **measured, independent** |
| **C4 — documented time-zero / acquisition delay** | **Partial.** The GPR processing sequence explicitly includes a **"time zero correction"** step (stated in the paper's methods), but **no numeric value is given** in the interpretation paper. Seismic: **no time-zero/instrument-delay value stated**; picking uncertainty is quantified as **~0.04 ms**, which is an uncertainty on a pick, not a system delay. **Fails C4 as a usable number**; the *procedure* exists, the *value* does not, in what is accessible. | **procedure documented, value UNRESOLVED** |
| **C5 — known velocity, or enough geometry to determine it** | **Yes for GPR, weaker for seismic.** GPR velocity (0.12 m/ns) was **derived from cross-hole tomography** between boreholes at surveyed separations, then **cross-checked** by testing migration velocities against diffraction-hyperbola collapse — independent of the reflectors later interpreted. Seismic velocity came from **travel-time inversion of first-arrival picks** — a self-consistent inversion of the seismic data itself, **not** an independent sonic log or CMP measurement. | **GPR: independently constrained (tomography). Seismic: self-inverted, weaker** |
| **C6 — no fitted value from the same reflections being validated** | **Yes for GPR** — the tomographic velocity was obtained before, and confirmed independently of, the reflection interpretation. **Marginal for seismic** — first-arrival travel-time inversion is not literally a fit to the *reflections*, but it is not independent of the seismic dataset either. | **satisfied for GPR; not cleanly satisfied for seismic** |
| **C7 — open raw data** | **Stated as open, CC-BY 4.0, DOI-linked — not independently verified this session.** The geological companion (Krietsch et al.) states raw file formats (`.txt`, `.png`, `.wcl`) in its own published text. **Both** ETH Research Collection dataset pages —<br>`doi.org/10.3929/ethz-b-000420930` (GPR+seismic) and<br>`doi.org/10.3929/ethz-b-000243199` (geological) —<br>returned **HTTP 403, "Access Restricted... due to a high volume of automated traffic (scraping)"** on every retrieval attempt this session (direct fetch, REST API, OAI-PMH endpoint — all blocked at the domain level). **This is a stated anti-scraping measure, not a login wall, a paywall, or evidence the data does not exist** — the papers citing these DOIs are peer-reviewed and describe the data in detail. | **PUBLISHER-STATED open; file-level access UNVERIFIED this session (Level 2)** |
| **C8 — enters Subterra's provenance/readiness architecture** | **Yes, in principle.** A Swiss coordinate system with a stated facility origin and an unstated vertical-datum realisation is architecturally identical in shape to AHN's "NAP documented by PDOK, absent from the file" case — `VerticalDatum(code, provenance=SUPPLIED_BY_CALLER)` already models exactly this. No schema change would be needed to *represent* what is described; representing the actual traces would need the existing SEG-Y/segy-like readers, not new ones (borehole GPR and seismic are both already-supported acquisition patterns in principle, though borehole *position* — as already established for TestUM — is not). | **representable, once obtained** |

### 3.3 Verdict on Grimsel

**The strongest external-validation candidate found across both audits —
and still not sufficient, and not a substitute for 4TU-specific evidence.**

- It is the **first** candidate in either audit search to combine GPR,
  seismic, **and** genuinely independent borehole/core-logged ground truth
  at one site. That is a materially better combination than Wurtsmith
  (GPR only, no boreholes), TestUM (GPR only, weak depth truth), or BHRS
  (unobtainable).
- It fails **C1** outright — it cannot become 4TU's vertical registration
  evidence, only an external proof that Subterra's architecture *can*
  represent this class of data, the same role Wurtsmith and TestUM already
  played.
- It fails **C4** as a usable number — a documented correction step exists,
  no value does, in the accessible text.
- It is **marginal on C5/C6 for the seismic side** — the GPR velocity is
  genuinely independent (tomography); the seismic velocity is a
  self-inversion of the same seismic first arrivals, which is a weaker,
  though not identical, form of the circularity C6 warns against.
- It is **unverified on C7** — not because the data is closed, but because
  the repository actively blocked automated retrieval this session. This is
  recorded as **Level 2**, the same class as CGISS before its files were
  retrieved in the earlier audit: real, cited, described in a peer-reviewed
  data descriptor, and currently not independently confirmable file-by-file.

## 4. Explicit answer to the question asked

**No dataset — held or external — satisfies all eight criteria
simultaneously. This is reported explicitly, as instructed, rather than
forcing a cross-site fusion or treating a partial match as complete.**

- **For 4TU specifically:** unchanged. Nothing found here or in the prior
  audit supplies 4TU's vertical datum, time-zero, or velocity. The
  4TU + AHN horizontal fusion remains `REGISTRATION_REQUIRED`, exactly as
  before this stage.
- **For Subterra's architecture, as an external proof point:** Grimsel is
  the strongest candidate found so far — stronger than Wurtsmith or TestUM —
  but is currently blocked from independent verification by the source
  repository's own anti-scraping measure, not by a scientific gap in the
  evidence it claims to hold. Its GPR-velocity provenance (cross-hole
  tomography, independent of the reflections being interpreted) is
  genuinely the cleanest C5/C6 case found in either audit.
- **Nothing is adopted.** No velocity, datum, or time-zero value from
  Grimsel, TestUM, Wurtsmith or anywhere else is proposed as a 4TU value,
  consistent with the standing rule established in
  [`cross-dataset-evidence-audit.md`](cross-dataset-evidence-audit.md) §3(c).

## 5. What would change this verdict

1. **ETH Research Collection access is restored** (the block is explicitly
   described as temporary — *"temporarily restricted from your location /
   your provider"*). Re-attempting retrieval later, or via a different
   network path, would let this stage's Level 2 finding become either a
   confirmed Level 2–3 (data retrieved, matches description) or a
   downgrade if the files do not match what the papers describe.
2. **A numeric GPR time-zero for Grimsel** is published somewhere not yet
   read (a methods appendix, a companion instrument-log dataset). Not
   established here.
3. **4TU's own missing declaration is supplied** — this remains, as before,
   the only route that actually unblocks 4TU, and it is Track 1 from
   [`multimodal-fusion-dataset-selection.md`](multimodal-fusion-dataset-selection.md):
   author/vendor correspondence, not a dataset search.

## 6. Roadmap impact

**A. Unlocks:** a documented, negative-but-precise answer to "is there
vertical registration evidence Subterra hasn't looked at yet" — with one
genuinely new, substantive lead (Grimsel) fully evaluated against the same
eight criteria the human specified, rather than left as "promising,
unaudited."

**B. 4TU / the selected GPR+DEM pair.** **Unchanged.** `REGISTRATION_REQUIRED`
stands. No blocker in
[`multimodal-fusion-dataset-selection.md`](multimodal-fusion-dataset-selection.md)
§14 was resolved.

**C. Phase 9 (fusion) / Phase 10 (3D reconstruction).** No advance for the
selected pair. Grimsel, if its data is later retrieved and matches its
description, would be a **second, separate, cross-site external-validation
case** — the same non-transferable role Wurtsmith and TestUM already occupy
— not a path to a 4TU 3D model.

**D. Standing recommendation.** Do not spend further search effort looking
for a *fifth* candidate dataset. Two full audits (this one and the prior
external-calibration audit) have now covered BHRS, Wurtsmith, TestUM, the
lysimeter, CGISS, the RGPR curated index (20 datasets), and Grimsel. The
result is consistent and specific: **the missing evidence for 4TU is a
declaration from the 4TU author or instrument vendor, not a dataset that
has not yet been found.**

---

## Sources

- Doetsch, J. et al. (2020), *Characterizing a decametre-scale granitic
  reservoir using ground-penetrating radar and seismic methods*, Solid Earth
  11, 1441–1455,
  [10.5194/se-11-1441-2020](https://doi.org/10.5194/se-11-1441-2020)
- Krietsch, H. et al. (2018), *A comprehensive geological dataset describing
  a crystalline rock mass for hydraulic stimulation experiments*, Scientific
  Data 5, 180269,
  [10.1038/sdata.2018.269](https://doi.org/10.1038/sdata.2018.269), read via
  [PMC6259022](https://pmc.ncbi.nlm.nih.gov/articles/PMC6259022/)
- ETH Zurich Research Collection, dataset DOIs
  `10.3929/ethz-b-000420930` and `10.3929/ethz-b-000243199` — **access
  attempts (direct fetch, REST API, OAI-PMH) all returned HTTP 403 with the
  repository's own stated anti-scraping message, retrieved 2026-08-14; not
  independently verified beyond what the citing papers state**
- Everything in §2 carries forward from
  [`external-calibration-dataset-audit.md`](external-calibration-dataset-audit.md),
  unchanged and not re-searched
