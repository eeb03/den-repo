# Subterra — Roadmap to Completion (DRAFT, 2026-10-12)

Status: **draft for the owner's review; zero-budget variant (Part C′) is the active plan.** It does not replace `ROADMAP.md` or
`docs/roadmap.md`. It is written against `main` at `8bbbb69`.

## The goal, restated

1. **Interpret and predict** what is beneath the surface.
2. **Image it in 3D**, as a CT-style volume that you can slice and scroll
   through, not only a set of points.
3. **Bring your own data:** upload a dataset, or connect a sensor and watch a
   live view build up while the prediction updates.
4. **Long term:** planetary exploration (including mineral prediction) and
   underwater scanning.

---

## Part A — Where the project actually stands

### Done, and strong

- **Data platform.** Ingests GPR (IDS, MALÅ, SEG-Y), CSV/XYZ, LAS/LAZ,
  GeoTIFF/DEM and seismic formats. It has provenance, validation, a
  seven-dimension spatial-reference assessment and an append-only declaration
  log. More than 2,600 backend tests pass.
- **Scientific honesty layer.** Candidate ≠ detection. Localisation that
  cannot be backed by evidence is refused. Every surface is checked for
  overclaiming. This is the project's real differentiator, and the roadmap
  below keeps it.
- **SaaS shell.** Accounts, ownership, password reset with email, async import,
  dataset reports, lifecycle management and a Next.js workspace (11 route
  groups, about 25k lines of TSX).
- **Acquisition abstractions.** DeviceProfile, AcquisitionSession, a FileDrop
  watcher and a review hold. No hardware integration yet.
- **Processing.** Time-zero (three explicit methods), recording-delay
  handling, topographic/air-gap correction and depth-origin declarations.
- **Benchmarks.** BAM and 4TU are scored reproducibly to the bit. Gates are
  pre-registered.
- **3D viewer scaffold.** `frontend/components/scene/reconstructed-scene.tsx`
  (three.js) plus `GET /api/scene/{id}`.

### The real blockers (measured, not guessed)

| Blocker | Evidence | Consequence |
|---|---|---|
| **The detector is at chance.** | BAM precision is 1.04–1.13× chance. 4TU AUC is 0.445 (CI 0.22–0.66). The multiscale and trace-span variants were rejected. | There is nothing yet to "predict". |
| **There are almost no labelled data.** | 4 real trace-associated targets in the whole corpus. The learned detector is blocked. | No ML path works until this changes. |
| **No dataset has a vertical/absolute anchor.** | `scene_3d` is unresolved for every dataset. 4TU has no trench coordinates, and BAM's origin is unverified. | The 3D view draws nothing real. |
| **No migration or velocity model.** | Depth uses a hardcoded typical-soil velocity. Migration is listed as "future". | Even with data, the result would be smeared hyperbolas rather than a CT-like image. |
| **Nothing streams.** | No WebSocket/SSE anywhere. A device-panel test asserts there is none. | No real-time view. |
| **GPR only in practice.** | Other `SensorType`s ingest as records, but no inversion or interpretation exists for them. | No mineral prediction and no underwater capability. |

### The honest diagnosis

The code is ahead of the **data**. For about two months most of the effort has
gone into extracting ground truth from public datasets that were never
designed to provide it: 4TU, BAM, Yesan, DRC, Grimsel and TestUM. That work was
rigorous, and the answer it produced is "blocked by evidence". **More code will
not unblock prediction or 3D imaging. Data that we control will.** The roadmap
below therefore puts data generation first.

---

## Part B — What the goal physically requires

These constraints shape the plan, so they come first.

1. **A "CT scan" of the ground requires dense 3D acquisition plus migration.**
   Medical CT sees each voxel from many angles. GPR sees the ground from one
   side. A CT-like volume comes from:
   - a **dense grid of parallel lines** (or an antenna array), about ≤ ¼
     wavelength spacing;
   - an **estimated velocity** (from hyperbola fitting or CMP);
   - **3D migration** (Kirchhoff or F-K), which focuses hyperbolas back to
     their reflectors;
   - **amplitude/envelope volume.** You then slice it as axial (depth
     slices / C-scans), sagittal and coronal views, exactly like a DICOM
     viewer, and add volume rendering.

   Single 2D lines can only give a "fence diagram", never a true volume.
   Migration therefore moves from "future, not required" to **core path**.
2. **Prediction needs labels, and labels need a controlled site or
   simulation.** The realistic route combines three things:
   - **physics simulation at scale** with gprMax FDTD, where every voxel's
     truth is known;
   - a **test bed we own or rent**, with buried objects of known position,
     depth and material;
   - **self-supervised pretraining** on unlabelled real data. The SSL encoder
     is already rated "promising but variable".
3. **Minerals cannot be predicted from GPR alone.** Mineral prospecting
   relies on magnetics, gravity, EM, induced polarisation/ERT, gamma
   spectrometry and surface spectroscopy, combined through **joint
   inversion** and geological priors. This is a separate product track. It is
   built on the same data model, which is why the modality-agnostic core
   matters.
4. **Underwater: GPR does not work in seawater** because the water is too
   conductive. It works in fresh water and ice. Marine subsurface work uses
   **sub-bottom profilers** (acoustic, usually exported as **SEG-Y**, which
   Subterra already reads), side-scan sonar and magnetometers. The path is to
   add acoustic modalities, not to stretch GPR.
5. **Planetary has public, real GPR data with known acquisition geometry.**
   Two examples are Perseverance **RIMFAX** (NASA PDS) and Chang'e-3/4
   **Lunar Penetrating Radar** (CNSA/CLPDS). These are good long-term
   validation sets, and they serve the north star directly.

---

## Part C — The roadmap

The roadmap has eight milestones. Each one has an **exit criterion** that is
measured, in keeping with the project's standard. Some milestones run in
parallel tracks, as noted.

### M1 — Own the ground truth (data track) · *unblocks everything*

- **M1a: gprMax simulation corpus.** Containerised gprMax. Scenario generator
  covering soil (permittivity/conductivity/heterogeneity), objects (pipe,
  cable, void, rock, rebar, foundation), depth, antenna frequency and 3D grids.
  Thousands of B-scans and C-volumes with voxel truth. This replaces
  `training/synthetic_gpr.py`'s first-order physics.
- **M1b: Controlled test bed.** One site (a sandbox, university yard or rented
  test pit) with surveyed buried objects, an RTK-GNSS-registered grid, and
  documented velocity (CMP or known-depth target). One afternoon of
  acquisition yields more scoreable truth than the entire current corpus.
- **M1c: Ingest RUP-FS (Gustave Eiffel 3D GPR)**, which is already noted as
  deferred. It is the only held lead on public **3D grid** data.
- **Exit:** ≥ 500 scoreable real targets with absolute X/Y/Z, ≥ 1 site whose
  vertical gate opens, and a simulation corpus with a fixed train/val/test
  split.

### M2 — Velocity, migration, volume (imaging track) · *the CT-scan core*

- Hyperbola-fit velocity estimation, with provenance and uncertainty, that
  replaces the hardcoded velocity.
- 2D then 3D migration (Kirchhoff first, F-K for speed).
- Grid-to-volume builder: interpolation between lines, with a per-voxel
  **coverage/evidence channel** so empty space is never painted as data.
- Output: a `SubsurfaceVolume` object (voxels + amplitude + envelope +
  uncertainty + CRS + provenance), stored as chunked arrays (Zarr).
- **Exit:** on gprMax volumes, migrated reflector position error is below a
  pre-registered tolerance. On the test bed, known objects appear at measured
  depth ±X cm.

### M3 — CT-style viewer (product track, can start in parallel on synthetic volumes)

- Tri-planar slice viewer (depth slice / inline / crossline) with a scroll
  bar through depth. This is the "CT" experience.
- GPU volume rendering (three.js ray-marching), transfer-function editor,
  isosurfaces for candidates, and an uncertainty overlay (fade or hatching
  where evidence is low).
- Click a voxel or object → candidate → radargram → raw trace (the existing
  Phase 10 evidence chain).
- **Exit:** a gprMax volume and a real test-bed volume render in the browser
  at interactive frame rates. Every rendered object links back to its traces.

### M4 — Prediction engine v1 (AI track)

- Pretrain the SSL encoder on all real unlabelled data plus simulation.
- Fine-tune a 3D detector/segmenter (U-Net-style) on simulation, then adapt
  to test-bed data (sim-to-real domain adaptation).
- Classes are introduced only as evidence allows: anomaly → hyperbolic point
  target → linear utility-like → planar interface → void-like.
- Calibrated uncertainty (ensembles or MC-dropout), reported per voxel and
  per object.
- **Exit:** on the held-out test bed and BAM, the detector beats the
  pre-registered chance baseline with a bootstrap CI that excludes chance.
  Without that, nothing is labelled "prediction" in the UI.

### M5 — Live sensor streaming (real-time track) · *partly unblocked today*

- **M5a (unblocked now): a replay device.** It streams any stored dataset
  trace-by-trace over WebSocket, as a real instrument would. This lets the
  whole real-time UI be built and tested with no hardware.
- Streaming ingest, incremental processing, a live radargram, a live position
  track and a progressive volume that fills in as lines arrive.
- **M5b:** First real adapter. Choose one instrument with an open protocol or
  SDK, and buy or borrow it (owner decision; see below). Then NMEA GNSS + IMU
  fusion.
- **Exit:** walking a grid with a real unit produces a live radargram (<1 s
  latency) and a progressive 3D volume on screen.

### M6 — Platform hardening for outside users

- Object storage for large uploads (resumable/chunked), a GPU job workers
  queue for migration and inference, and encryption at rest.
- Public API keys and an SDK for device makers. Billing and quotas only if
  commercialising.
- Expert/standard/non-expert views (Phase 12) on top of the volume.
- **Exit:** an outside user uploads a 3D survey and gets a volume plus
  candidates without help.

### M7 — Multi-physics & minerals (long-term track A)

- Add magnetometry, gravity, EM/ERT and gamma as *interpreted* modalities,
  with forward models and inversion (via SimPEG, open source), not just
  ingest.
- Joint inversion into a shared 3D property model (density, susceptibility,
  conductivity, permittivity).
- Mineral prospectivity is a probabilistic map from that model plus
  geological priors. It is **never** a "mineral detected" label. Validate on
  public survey areas that have drill-hole truth (geological-survey open
  data).
- **Exit:** prospectivity scored against held-out drill holes.

### M8 — Underwater & planetary (long-term track B)

- **Underwater:** sub-bottom profiler (SEG-Y, acoustic velocity model),
  side-scan sonar and marine magnetometer ingest. Freshwater/ice GPR mode.
- **Planetary:** ingest RIMFAX and Chang'e LPR from the public archives.
  Planetary dielectric models (regolith, ice) and rover-trajectory spatial
  frames (a non-Earth CRS). Reproduce published stratigraphy interpretations
  as the benchmark.
- **Exit:** Subterra reproduces a published RIMFAX/LPR subsurface
  interpretation from raw archive data, with uncertainty.

### Ordering

```
M1 (data) ──┬──► M2 (migration/volume) ──► M3 (CT viewer) ──► M6 (hardening)
            └──► M4 (prediction) ──────────────────────────────┘
M5a (replay streaming) can start immediately; M5b needs hardware.
M3 can start on gprMax volumes as soon as M1a produces them.
M7 and M8 start after M2–M4 prove the core on GPR.
```

---

## Part C′ — Zero-budget plan (ACTIVE: chosen by the owner 2026-10-12)

The owner has no budget, so the plan changes. M1b (a test bed we own) and
M5b (bought hardware) are **deferred**. They are replaced by simulation, free
public data and borrowed access. Everything else in Part C stands.

### Free substitutes

| Need | Zero-cost route |
|---|---|
| Labelled training data | **gprMax** (open source FDTD). 2D runs on the local Mac CPU; for 3D, use free GPU time on Kaggle (~30 h/week) or Colab. |
| Real 3D GPR grid | **RUP-FS** (Gustave Eiffel), already noted as deferred |
| Real data with known geometry | **NASA PDS RIMFAX** (Mars), **Chang'e-3/4 LPR** (Moon) |
| Minerals (M7) | Public magnetics, gravity and drill-hole data from Geoscience Australia, USGS and BGS. Inversion via **SimPEG**. |
| Underwater (M8) | Sub-bottom profiler SEG-Y from NOAA NCEI and USGS |
| A real live sensor (M5) | **The owner's phone.** Magnetometer, GPS and IMU streamed via phyphox or browser sensor APIs. |
| Field truth (replaces M1b) | **University partnership.** Borrowed GPR and test-pit access in exchange for a student project or co-authorship. Costs only email. |

### Re-ordered work

1. **M1a gprMax corpus.** CPU locally, then Kaggle for 3D. *(slice 1
   done 2026-10-12: gprMax 4.0.0 image, scene → input → B-scan → truth →
   validation. The reference scene validates within 5 ps RMS. The
   pre-registered mean-trace picker failed, and that failure is recorded.
   See `docs/simulation.md`.)*
2. **M2 volume schema + M3 CT slice viewer**, built on simulated volumes.
   This is the demo.
3. **M2 velocity + migration**, validated on simulation.
4. **M5a replay device + phone-sensor live stream.** This is real hardware at
   zero cost.
5. **M8-planetary moves forward:** RIMFAX/LPR as the first real benchmark.
   Reproduce a published interpretation.
6. **M4 detector**: trained on simulation, with SSL pretraining on free real
   data.
7. **M7/M8 later**, using the free survey data listed above.

### Cost risks that remain

- **AI tool usage is the actual spend.** Keep tasks one milestone at a time,
  and avoid giant report-backs. The 2026-08-22 Grok report-back alone cost
  about $4.
- **Hosting:** stay local (Docker) until an outside user needs access.
- **Free credit programmes:** cloud startup credits (Google, AWS, Microsoft),
  university partnerships, and ESA/NASA open challenges.

---

## Part D — Recommended next six tasks (each a small branch)

1. **gprMax container + scenario generator.** Produce 1 B-scan and 1 small 3D
   volume with truth, and add them to tests.
2. **`SubsurfaceVolume` schema + Zarr storage.** Include a coverage channel
   and provenance.
3. **Tri-planar slice viewer** fed by the synthetic volume. This is the first
   visible "CT scan".
4. **Hyperbola-fit velocity estimation.** Validate it on gprMax (known
   velocity), then on BAM.
5. **Kirchhoff 2D migration.** Validate it on gprMax, using point-target
   focusing error.
6. **Replay-device WebSocket stream + live radargram panel.**

The test-bed acquisition (M1b) runs alongside these. It needs a person,
hardware and a site, not code.

## Decisions the owner needs to make

1. **Hardware:** which GPR unit can we access? Buying, renting or a university
   partnership decides M1b and M5b.
2. **Test site:** is there access to land where objects can be buried and
   surveyed?
3. **Compute:** is GPU budget available for gprMax and training? A cloud GPU
   or a local machine changes M1a's scale.
4. **Focus:** should the next quarter target the **CT viewer demo**
   (M1a→M2→M3, visible fast) or **real prediction** (M1→M4, slower but the
   real moat)? The recommendation is the CT viewer first, because it produces
   the volumes and tooling that M4 needs anyway.
