# Roadmap and status

The authoritative status of each work area, with the evidence for the claim.
Recorded here because two other documents note that the roadmap "is not
recorded anywhere in this repository", which made every phase claim
unauditable.

Scope note: this is the **work-area** roadmap. The separate *Phase 0–12*
numbering referenced by `dataset-benchmark-plan.md` and
`benchmark-acquisition-plan.md` is still not committed anywhere, so the phase
numbers in those documents remain inferred, exactly as they say.

Last verified against `22b08ba` on 2026-08-22 (browser verification pass).

| Area | Status | Evidence |
|---|---|---|
| Core backend / data platform | ✅ Complete | 2,188 tests pass in Docker, re-verified 2026-08-22; 1,167 files and 749,315 traces ingest across four formats and three vendors (that ingest figure is from 2026-08-08, not re-checked this pass) |
| Open GPR dataset investigation | ✅ Complete | `dataset-inventory.md`, `dataset-benchmark-plan.md`, `cmugpr-acquisition-assessment.md` |
| BAM benchmark acquisition | ✅ Complete | `external-gpr-benchmark-acquisition.md`; acquired and checksum-verified |
| BAM detection benchmark | ✅ Complete | `artifacts/bam/*.json`, 161 lines scored at both frequencies |
| 4TU utility benchmark | ✅ Complete | `artifacts/4tu/benchmark.json`, complete **125**-activity corpus |
| Benchmark test infrastructure | ✅ Strong | GPR regression 26 pass bit-identical (re-verified: 26 tests still collect); baseline identity 12/12 |
| Ground-truth / provenance safeguards | ✅ Established | `provenance.md`; enforced in backend tests and in the UI |
| Localisation / X-Y-Z scoring | 🔒 **BLOCKED** | Both artifacts carry the gate; 4TU publishes no trench coordinates, BAM's absolute origin is unverified. Unaffected by everything below — see "What blocks localisation". **4TU localisation remains blocked; fallback benchmark search complete, none integrated** — `docs/fallback-localisation-dataset-search.md` (2026-08-22) scored a newly-identified candidate (Grimsel ISC, ETH Zurich) at 59/100. **Deep audit follow-up (2026-08-22)** — `docs/grimsel-deep-evidence-audit.md`: re-scored **73/100** on primary-source evidence this pass fetched directly (the borehole/shear-zone dataset's real Swiss-grid-tied coordinate origin, and its separate CC-BY-4.0 license, distinct from the GPR data's own non-commercial-only license). **Geological-model file audit (2026-08-22)** — `docs/grimsel-geological-model-file-audit.md`: downloaded and read the geological-model MATLAB toolkit directly (CC-BY, 2.87 MB, checksummed, deleted after reading). Found the AU tunnel's own path in absolute Swiss-grid coordinates (`AUTunnel.txt`) and the borehole-to-shear-zone computation path (collar + azimuth/dip + intersection depth, `FBS.txt`/`S3_1.txt`), sharpening the score to **78/100** — still below 80. The GPR profile's own placement in the authors' visualization (`plot_GPR.m`) is a manually-fit overlay (Category C, approximate), not a surveyed tie — the one fact still missing is which tunnel point corresponds to the GPR's own position zero. Classified **B — conditional benchmark**, unchanged. Not integrated; author questions sharpened, not sent. TU1208 and BAM remain the strongest already-held partial (X+depth, non-geodetic) candidates. **TU1208 physical-depth validation run (2026-08-22)** — `docs/tu1208-physical-depth-validation-report.md`: X 🔒 blocked (no profile along-line origin published), Y 🔒 blocked (all 36 surveyed targets carry `transverse_offset_m: None`), Z 🔒 blocked for end-to-end validation (ground truth and conversion machinery both exist and are honestly labelled, but 0 of 36 targets could be tied to a measured reflector, so zero depth estimates were produced — Outcome D, insufficient evidence, not a partial success). No dataset has been integrated and no readiness state here has changed |
| Composition honesty — the off-GPR invitation cascade | ✅ Complete for the surfaces audited | 23+ commits (keyword search on `git log`, likely an undercount): every surface that used to say a GPR-only capability "has not been run" for a non-GPR dataset (report, radargram viewer, thin-client, workspace panes, import-report, exports, candidates inspect route, dataset list/switcher/summary, device registration/card) now says it does not apply and names the actual recorded/declared composition instead. `dataset.sensor_type` is labelled "declared" everywhere it surfaces, never presented as the recorded instrument |
| Inventory D — DEM as a first-class modality | ✅ DEM closed; other members open | `SensorType.DEM` added next to `LIDAR` (`schemas/subterra_record.py`); GeoTIFF's undeclared-band elevation inference fires for LIDAR or DEM (`docs/surface-reference.md`); import picker and device registration both offer the full ten-member enum, no pre-selected default, no `other` (a value the backend never accepted). Held reference datasets (COP30, AHN) intentionally not migrated. `ert`/`gravity`/`gps`/`imu` still have no dedicated converter — declarable, not yet ingestable as their own modality |
| Fusion: visibility, redaction, and a run control | ✅ Complete | `GET`/`POST /api/fusion/*` apply the same visibility rule as the dataset list; another user's dataset id inside a shared sample is redacted (`dataset-not-visible`), not shown or dropped; `/fusion` is a real UI (preview then save — `persist` has no dedup against stored samples, so it defaults to `false` and Save is disabled until a preview matches the current configuration by value) |
| Frontend architecture audit | ✅ Complete | `frontend/README.md` |
| V0 frontend migration | 🟡 In progress | workspace, datasets and benchmark pages ship; marketing landing page still not ported (components exist under `components/landing/`, no route mounts them — re-checked 2026-08-22) |
| Real API → new frontend | 🟡 Substantially complete | 9 of 12 backend route groups have UI (`fusion` added: `/fusion`, preview-then-save); `exports`, `sources`, `training` do not |
| Browser verification | ✅ Complete through the Phase 7 sweep | `browser-verification.md` Pass 2 — run 2026-08-22 against `22b08ba`, real Chromium via Playwright MCP. Covers everything Pass 1 (2026-08-08, `0daa3e7`) predated: composition honesty across five surfaces, the full DEM import workflow (enum, no default, elevation-inference checkbox, ready screen), device registration with multi-modality declaration and reload persistence, `/fusion` preview-then-save end to end (200,288 records, 9 samples, redaction confirmed by a second test account plus the passing dedicated test), and the generic 422 serializer confirmed live via a real oversized-password submission. No regressions, no genuine product bugs found; backend 2,188/2,188 and frontend 570/570 pass against a freshly built image/current tree, typecheck/lint/build all clean |
| Detection improvement | ⏳ Open — one candidate tried and **rejected** | `detector-multiscale-experiment.md` |
| Author / evidence requests | 🟡 Open, narrower than before | The 4TU author replied once already and resolved the vertical-datum question (WGS84 ellipsoidal, confirmed by measurement against AHN) — see "External evidence: the 4TU author replied" below. What is still open is two specific questions, not the whole topic: the time-zero/air-gap magnitude, and whether a propagation velocity was ever determined. A follow-up letter draft exists (`docs/4tu-author-letter-draft.md`) |
| Authentication and ownership | ✅ Complete | `docs/authentication.md`; sessions, PBKDF2, dataset ownership, login limiting, password reset with Resend delivery |
| Dataset reports | ✅ Complete | `docs/dataset-report.md`; `GET /api/datasets/{id}/report`, eight capability assessments per dataset |
| Depth-axis origin → ground | ✅ Complete | `docs/depth-origin.md`; a declared offset now participates in the vertical assessment instead of being recorded and ignored |
| Surface reference / vertical anchor | ✅ Complete | `docs/surface-reference.md`; a raster band can be declared elevation, so `surface_reference` can reach `available` for the first time. Extended 2026-08-22: the same inference now covers DEM, not only LIDAR |
| Device abstraction | ✅ Complete, capability extended | `docs/devices.md`; device + session records converging on the Stage 9 acquisition boundary. No hardware integration. Extended 2026-08-22: registration offers the full sensor-type enum with no default (was hardcoded `gpr`), and a device can declare it also produces additional modalities beyond its primary type, both readable on the saved card |
| FileDrop acquisition | ✅ Complete | `docs/filedrop.md`; acquisition boundary, checksum at receipt, identification before ingestion, review hold |
| Spatial reference workflow | ✅ Complete | `docs/spatial-reference.md`; seven-dimension assessment, append-only declaration log, seven declaration kinds. **Multi-point affine registration — implemented, pending real-data exercise** (`schemas/spatial.py::AffineTie`, `ingestion/affine_tie.py`, `tests/test_affine_tie.py`, 24 tests + 8 in `tests/test_spatial_reference.py`, all passing): a genuine 2D counterpart to `GeoTie` for a frame whose native position is `LocalCartesianPosition` (a real (x, y), no along-track axis for GeoTie's 1D interpolation to use) — a gap the schema already anticipated but no converter had a route to close. Fits a full 2D affine map from ≥3 non-collinear surveyed control points, reports RMS/max residual in metres (never a flattering 0.0 for an exact 3-point fit), rejects collinear/duplicate/non-finite/numerically-unstable geometry outright, and is fully reversible. Registration is additive — native coordinates are never touched, only `registered_position` is set — and provenance correctly reports `registered`, not `measured` (a related bug in `assess_horizontal`'s tied-detection, which checked only `geo_tie`, was found and fixed in the same change). Browser-verified end to end on a synthetic, explicitly-labelled test dataset, cleaned up after. **It does not advance the localisation gate below**: the repository currently holds no real dataset with a `LocalCartesianPosition` — no converter produces one — so this closes an architectural gap, not a data one. Recommended next step: a real ingestion path (e.g. total-station or laser-scanner data) that genuinely produces `LocalCartesianPosition` with surveyed control points, so the existing implementation can be residual-validated against real geometry instead of remaining exercised only by fixtures |
| Dataset lifecycle management | ✅ Complete | `docs/dataset-lifecycle.md`; rename, safe delete, derived status, duplicate detection, rescore |
| Production-ready platform | ⏳ Later | no encryption at rest, no dataset signing |
| Velocity model estimation, topographic correction & migration | 📋 Future / advanced GPR processing — investigation only, not implemented, **not required for current product readiness** | Dependency chain, in order: velocity estimation → topographic correction → migration; a later stage is not investigated until the one before it is defensible. Depth today uses a hardcoded typical-soil velocity, tagged `ASSUMED` everywhere it appears; a future per-dataset estimate (hyperbola fitting, CMP analysis, or another method the dataset actually supports) may earn `DERIVED` provenance, carrying its method, source evidence and confidence — but only where the evidence justifies it, never automatically, and `ASSUMED` must remain the honest answer where it does not. Topographic correction, once reliable elevation exists (DEM, GNSS/RTK, the existing vertical-reference infrastructure), needs its own physical/geometric justification, not visual alignment. Migration (Kirchhoff/F-K) is investigated only once a defensible velocity model exists, is not accepted merely for visually cleaner anomalies, and must retain its own provenance (algorithm, velocity model and its provenance, topographic-correction status). Explicitly out of scope for this milestone: spatial interpolation (kriging, splines, deep-learning super-resolution) and mesh/volumetric/isosurface reconstruction, which fabricate continuity between sparse measurements the sensors never recorded, and a renderer replacement (e.g. a game engine) undertaken to make sparse evidence look physically complete — all of which conflict with the composition-honesty principle above. **Declared-permittivity velocity — implemented (f1eef90, `ingestion/four_tu_velocity.py`), not required for current product readiness.** 4TU's 125 activities each publish a relative permittivity in `Metadata.csv`; `v = c/√εᵣ` now resolves it into a dataset-specific, opt-in velocity for `4tu_<LocationID>` SEG-Y ingestion, with correct provenance (`DECLARED_BY_SOURCE` εᵣ → `DERIVED` velocity → `DERIVED` depth, `verified=False` throughout) and zero change to `DEFAULT_GPR_VELOCITY_M_PER_NS` or any other dataset. This is source-integration, not empirical validation: the Pk050 audit (`artifacts/bam/pk050_velocity_audit.json`) has since completed and also classified FAILED — neither BAM specimen breaks Pk266's t0/velocity confound, so no held dataset has produced a `verified=True` velocity. Migration remains gated on that, unchanged |

## The product sequence

The work-area table above records what exists. The **development sequence** is
separate and is reproduced here because it previously lived nowhere in the
repository:

1–5 product shell, upload/import, ownership/auth, password recovery, email
delivery — **complete**. 6 dataset reports — **complete**. 7 dataset
management — **complete**. 8 spatial reference workflow — **complete**. 9 FileDrop acquisition —
**complete**. 10 device abstraction — **complete**. 11 surface reference — **complete**. 12 depth-axis origin — **complete**.
13 candidate intelligence — **complete**: the candidate layer is real,
provenanced, versioned, staleable and inspectable. The detector it exposes is
still at chance, which is a measured result rather than a gap in this stage.
15 radargram inspection — **complete**: the measured B-scan with candidate
overlays mapped exactly to their supporting cells. 16 record-loading performance
— **complete**: the candidate path was parsing its own copy of the corpus, so a
radargram page materialised 384 MB twice; concurrent grid+candidates went from
28.2 s to 4.7 s and candidate retrieval from 22.9 s to 0.27 s. See
`docs/record-loading.md`.
17 amplitude inspection toggle — **complete**: the radargram can now show either
the local-anomaly z-score or the pre-anomaly signal it was computed from, as two
projections of one grid. Candidate footprints, axes and the reliability mask are
identical between them; no unit is claimed for the pre-anomaly values because
none is established. See `docs/radargram-display-modes.md`.
14 ground-truth benchmarks — **complete**, with a negative headline: after the
duplicate audit the 4TU corpus holds 107 independent positives and **6**
independent negatives, which could only distinguish a detector of AUC 0.742 or
better from chance. Six further attested-empty surveys would make a clearly
useful detector (AUC 0.70) recognisable. See `docs/ground-truth-benchmarks.md`.

The old list's "11 acquisition sessions" is obsolete: stage 10 implemented
them. Stage 11 was chosen by dependency instead — the surface anchor was the
only blocker toward reconstruction that needed no external evidence. What
remains: a hardware adapter (blocked: no instrument or protocol identified),
15 validated object detection,
16 multi-modal fusion, 17 3D reconstruction, 18 interactive underground model,
19 real-time scanning, 20 non-expert interpretation.

Stages 17–18 depend on 8 far more than on 13–16, and stage 8 is blocked by
evidence rather than effort. `docs/dataset-report.md` carries the measured
dependency report.

## The product was running an unbenchmarked detector (stage 18)

`run_pipeline(mode="gpr_local_anomaly")` applied the ring statistic WITHOUT the
trace filters that every benchmarked path applies. On a real 4TU line the two
compositions disagree about 95.7% of cells, and the count of cells that become
candidates differs 4.2x (39 unfiltered against 164 filtered).

The two anomaly IMPLEMENTATIONS were always equivalent — `validate_arraywise`
measures them bitwise identical and was never wrong. What diverged was the
composition the ingest pipeline used. `--verify-arraywise`, referenced in three
docstrings as though it were a CLI flag, has never existed.

The owner is the ingest COMPOSITION, not either anomaly function: every ingest
route applies exactly ONE `run_pipeline` mode, so the validated two-step chain
the regression baseline has pinned since the interpretation baseline was
unreachable through the API. A new `gpr_full` mode composes it; the single-step
modes are unchanged, and BAM is bit-identical. Stage 19 then made `gpr_full` the
GPR ingest DEFAULT — a GPR dataset ingested with no mode named now gets the
benchmark-aligned chain, the resolved mode is recorded on the dataset, explicit
choices still win, no other modality moves and no historical dataset is
reprocessed. Verified on a real 4TU line: the defaulted ingest is bit-identical
to the BAM array path and candidate generation succeeds where UI-ingested GPR
previously reported BLOCKED. See `docs/anomaly-path-equivalence.md`.

## External evidence: the 4TU author replied

Dr. ter Huurne, author of the 4TU dataset, answered a direct enquiry. It is the
first evidence request in this project to produce an answer, and it resolves the
vertical-datum question that has been open since stage 8: **the GNSS elevations
in the exported SEG-Y are ellipsoidal WGS84, not NAP.**

It does not unblock depth. The author is explicit that no time-zero correction
and no air-gap removal were applied, so the ground surface does not necessarily
correspond to depth zero and an air path remains in the data — and gives no
magnitude for it. Physical depth and absolute elevation stay BLOCKED.

The author named neither of the two per-trace elevation fields, which differ by
42.2–45.2 m — attaching the datum to the wrong one is a ~44 m error. **That
question has now been answered by measurement rather than by asking.** Both
fields were compared against AHN, the Dutch national terrain model (PDOK, NAP
orthometric), across 366,019 traces in 107 activities and 12 sites: bytes 41–44
track AHN to −0.83 m, bytes 45–48 sit +43.38 m above it, and that difference
correlates with latitude at −0.999 (planar R² 0.998, residual sd 0.034 m) —
geoid behaviour, not a constant instrument offset, matching the published NL
separation range of 41 m (Groningen) to 47 m (Limburg) in magnitude and
gradient. **Bytes 45–48 hold the ellipsoidal GNSS height; bytes 41–44 an
orthometric NAP-like height.** No platform state was changed. See
`docs/4tu-elevation-field-identification.md` and `docs/4tu-author-evidence.md`.

Depth remains blocked regardless: the author is explicit that no time-zero
correction and no air-gap removal were applied, so a surface elevation does not
locate depth zero. The two remaining external questions are the time-zero/air-gap
magnitude and whether a propagation velocity was ever determined.

## Where detection actually stands

The baseline detector is the scientific reference and remains unchanged in the
default path. It is at approximately chance on both benchmarks:

- BAM: recall 0.065 (1.5 GHz) and 0.093 (2.6 GHz); precision 0.135 and 0.147
  against a 0.1297 chance rate — 1.04× and 1.13× chance.
- 4TU: AUC 0.4452, Spearman ρ −0.0619.

Stage 13 reproduced all three of those numbers bit-identically from the current
repository rather than trusting this file, and **corrected one claim**: "at or
below chance" overstated the 4TU result. The separation rests on seven
negatives, and its bootstrap 95% interval is [0.2219, 0.6607] — it spans chance
in both directions, so that benchmark cannot distinguish this method from
chance *either way*. See `docs/candidate-intelligence.md`.

Stage 13 also audited the 4TU corpus for duplicate evaluation units and found
them: 759 radargrams carry 721 unique checksums, six activities are duplicated
in full, and activity 09.7 — one of the seven negatives — shares a
byte-identical radargram with 09.6, a positive. Counting each measurement once
gives 121 activities and AUC 0.4511. The leakage is real and recorded in
`artifacts/4tu/leakage.json`; it is **not** the explanation.

Two candidates have now been tried and both were rejected on evidence.

The **trace-span filter** (Stage 13) required a candidate to span at least K
trace columns, on the physical argument that an object occupying space produces
a laterally continuous response. K was chosen on the Rot90 rotation and reported
on Rot00. Calibration selected K=1 — the baseline. Detections fall 333 → 68 → 0
across K = 1, 2, 3, so **essentially no candidate this detector produces spans
three traces**. That is the most specific account yet of why it sits at chance:
the estimator is responding to near-point excursions, not to laterally extended
structure. `artifacts/experiment/trace_span.json`.

The **multi-scale ring estimator** was designed
against the *measured* width-saturation mechanism, demonstrated that it escapes
that collapse synthetically, and was **rejected**: its BAM gain is concentrated
entirely in duct-4 while ducts 1–3 fall to zero, and 4TU AUC did not improve
(0.4452 → 0.4216, bootstrap ΔAUC interval spanning zero). An earlier claim of
improved SNR and noise behaviour was **withdrawn** — it had been measured on
pure Gaussian noise, and on real radargrams the candidate fires 3.5×–17× more.

Two practices from that experiment are now load-bearing for any future one:

1. **Bit-identical baseline reproduction.** The baseline arm must reproduce the
   frozen artifacts to full precision through the new code path. This is what
   caught a traversal bug that had silently scored 123 of 125 activities and
   produced a plausible wrong answer (AUC 0.4429 vs a true 0.4452).
2. **Pre-registered calibration**, never tuned against benchmark truth.

## What blocks localisation

Not effort — evidence. 4TU publishes no trench coordinates, so no candidate can
be matched to a utility. BAM's absolute origin is unverified. No dataset held
has an established vertical relationship: the GPR time axis starts at
instrument time-zero, not the ground surface, and no source declares a vertical
datum. The backend states this itself when asked to resolve a 3D scene, which
is why `scene_3d` is unavailable for every dataset and why the workspace draws
no subsurface geometry.

Detection scoring does not depend on any of this and is unaffected. A blocked
localisation gate does not make the detection numbers invalid, and the
detection numbers do not make the gate any less blocked.
