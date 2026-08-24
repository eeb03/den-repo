# TU1208 physical depth validation — final report

**Question asked.** Can Subterra's current depth machinery recover physically
meaningful target depths when compared against the independently measured
TU1208 target depths?

**This is a confirmation pass, not new research.** The experiment this
report validates was already designed, built and run in a prior stage
(`docs/tu1208-target-transcription.md`, `docs/tu1208-depth-calibration.md`,
`scripts/tu1208_depth_calibration.py`, `benchmark/tu1208_truth.py`,
70 passing tests). This report re-runs it against the current commit,
confirms it is unchanged, traces the production depth pipeline the earlier
work assumed but did not narrate end-to-end, states the outcome in the
vocabulary this task asked for, and updates the roadmap's granular X/Y/Z
gate. **No new calibration, fit, or estimate was produced. No source file
was changed.**

---

## 1. Ground-truth source

Dérobert, X. & Pajewski, L. (2018), *TU1208 Open Database of Radargrams: The
Dataset of the IFSTTAR Geophysical Test Site*, **Remote Sensing 10(4), 530**,
[10.3390/rs10040530](https://doi.org/10.3390/rs10040530), CC-BY-4.0. Target
depths are printed in Figures 6, 9, 11 and 13; file-to-line associations in
Tables 3–7; the location method in §3.4. The Zenodo archive
([10.5281/zenodo.1211173](https://doi.org/10.5281/zenodo.1211173)) holds the
67 raw radargrams and **no target geometry** — the geometry exists only in
the paper, and was transcribed by hand into
`benchmark/tu1208_targets.json` with `provenance_class:
transcribed_from_publication` and `verified_by_subterra: false` throughout
(never elevated, because Subterra has no way to check a printed figure
against reality).

**How target position was established, per the paper (§3.4), quoted:**
theodolite survey, two points per pipe on the pipe's upper side, more points
for larger objects. This is genuinely independent of the GPR measurement —
a surveyor's instrument, not a radar reading.

## 2. What "depth" means here — established before any comparison

Per rule 4 of the task, the two quantities below must never be compared
without a stated conversion, and none is available, so they are kept apart:

| Quantity | What TU1208 states | What Subterra would need to compare it to a prediction |
|---|---|---|
| Reference for the printed 0.00 | **Not established to be the antenna/ground surface.** The paper states the transversal schemes omit a 10 cm limestone surface layer and the asphalt wearing course site-wide, and ~30 cm more of limestone in the silt section specifically | An unquantified surface offset, at least 0.10–0.40 m depending on region, that is not in the printed number |
| Crown vs. centre | Theodolite points were taken on the pipe's **upper side**; the paper never states whether the printed depth is to the crown or the centre, and no pipe diameter is published | Cannot be resolved without a diameter, which does not exist in this source |
| Vertical datum / CRS | **Absent.** No datum, no EPSG, no absolute elevation anywhere in the source | Depth here is a **local, relative** quantity (metres below an unquantified surface reference), never an absolute elevation |

None of these was invented or assumed away. They are recorded as open
questions in `tu1208-target-transcription.md` §5 and reproduced here because
they bound what "validated" could even mean on this dataset: at best, a
**crown-or-centre, surface-relative** depth, never an absolute one.

## 3. Targets validated (evidence-backed measurements)

**36 pipe targets**, 4 regions × 3 layers × 3 pipes per layer (all three
pipes in a layer share one theodolite-surveyed depth), condensed here by
layer — the full 36-row list is in `benchmark/tu1208_targets.json` and was
printed directly from `benchmark.tu1208_truth.pipe_targets()` for this
report:

| Region | Figure | Layer 1 depth (m) | Layer 2 depth (m) | Layer 3 depth (m) | Pipes/layer | Evidence type |
|---|---|---|---|---|---|---|
| silt | Fig. 6 | −0.80 | −1.20 | −1.83 | 3 (steel / water-filled PVC / empty PVC) | surveyed (theodolite) |
| limestone | Fig. 9 | −1.20 | −1.70 | −2.40 | 3 | surveyed (theodolite) |
| gneiss 14/20 | Fig. 11 | −0.90 | −1.50 | −2.10 | 3 | surveyed (theodolite) |
| gneiss 0/20 | Fig. 13(a) | −1.15 | −1.56 | −2.20 | 3 | surveyed (theodolite) |

Every one of the 36 `PipeTarget` records carries `transverse_offset_m:
None` — **X (across-line) position is unavailable for every target,
without exception**, confirmed by reading the truth objects directly
(§6 below shows the mechanism). A further 18 non-pipe depths (dolmens,
blocks, a cavity, masonry) and 5 derived multilayer interface depths exist
in the same truth file but were excluded from the quantitative baseline
below because most carry an uncertain object identity (`object_certain:
false` on several — e.g. three printed depths for two described masonry
walls) and the task's rule 2 forbids assuming a target identifier where the
source itself does not settle it.

## 4. Baseline results — the unmodified pipeline against all 36 targets

```
target_id                    ground_truth_m   subterra_estimate_m   absolute_error_m   match_confidence
tu1208-silt-L1-*  (×3)             -0.80             None                  N/A            UNRESOLVED
tu1208-silt-L2-*  (×3)             -1.20             None                  N/A            UNRESOLVED
tu1208-silt-L3-*  (×3)             -1.83             None                  N/A            UNRESOLVED
tu1208-limestone-L1-* (×3)         -1.20             None                  N/A            UNRESOLVED
tu1208-limestone-L2-* (×3)         -1.70             None                  N/A            UNRESOLVED
tu1208-limestone-L3-* (×3)         -2.40             None                  N/A            UNRESOLVED
tu1208-gneiss1420-L1-* (×3)        -0.90             None                  N/A            UNRESOLVED
tu1208-gneiss1420-L2-* (×3)        -1.50             None                  N/A            UNRESOLVED
tu1208-gneiss1420-L3-* (×3)        -2.10             None                  N/A            UNRESOLVED
tu1208-gneiss0-20-L1-* (×3)        -1.15             None                  N/A            UNRESOLVED
tu1208-gneiss0-20-L2-* (×3)        -1.56             None                  N/A            UNRESOLVED
tu1208-gneiss0-20-L3-* (×3)        -2.20             None                  N/A            UNRESOLVED
```

**36 of 36 targets: unmatched. 0 predictions produced. 0 errors computable.**
Re-run in this pass (`python -m scripts.tu1208_depth_calibration`) and
confirmed bit-identical to the committed artifact
(`artifacts/tu1208/depth_calibration.json`) but for the run timestamp and a
single last-significant-digit floating-point difference in one correlation
coefficient (platform BLAS variation, the same pattern already documented
in `docs/test-environment.md`).

**Every one of the 36 carries the identical reason**, read directly from
`association[i]["missing"]` in the artifact:

```
"missing": [
  "the target's transverse offset from a named site reference",
  "the profile's along-line origin in that same reference"
]
```

This is not 36 independent failures. It is **one structural gap** — the
paper never publishes a coordinate system in which both a target and a
trace can be located — that happens to apply identically to every target.

### Why zero predictions is the correct baseline, not a missing feature

Producing a number here would require picking *which* reflector in *which*
trace corresponds to *which* target. With no published association, the
only way to choose would be to try candidate reflectors and keep whichever
one reproduces the surveyed depth — which is exactly the "select the
best-performing target" and "resolve ambiguity by best numerical result"
practice rule 7 and rule 10 of this task forbid. The existing script
enforces this by construction: it is checked (with docstrings stripped) to
contain no `argmax`, `find_peaks`, `hilbert`, `correlate`, or any signal
picking call at all, and it never imports `interpretation`, `preprocessing`
or the candidate-scoring modules.

## 5. Depth methodology — the current Subterra pipeline, traced

This is a narrative this pass produced, from reading the production code
directly (`converters/segy_converter.py`), not from documentation, to close
the task's rule-5 requirement (the prior stages assumed this pipeline was
understood but never wrote it as one linear trace):

```
1. Time axis:      segyio reads each trace's per-sample times directly from the
                    SEG-Y binary header (BinField.Interval) and trace geometry.
                    sample_time = samples[sample_idx], in nanoseconds,
                    ORIGIN = INSTRUMENT TIME ZERO — not the ground surface.

2. Time-zero:       NOT applied. No quantity resembling a recording delay or
                    an air-gap is subtracted anywhere in this step. A
                    header-derived delay (e.g. 4TU's DelayRecordingTime) is
                    recorded elsewhere as a frame Assumption and never used
                    arithmetically (docs/depth-origin.md; the earlier 4TU
                    audit in docs/dataset-inventory.md T1.1).

3. Velocity:        DEFAULT_GPR_VELOCITY_M_PER_NS = 0.1 m/ns
                    (converters/segy_converter.py) — "typical near-surface
                    soil GPR velocity, relative permittivity ~9" — applied
                    ONLY when sensor_type is GPR (a seismic SEG-Y is left
                    with depth=None, precisely because a soil velocity would
                    be a wrong number for a different modality). Recorded on
                    the frame with provenance "derived", and flagged
                    explicitly whenever it differs from this default.

4. Depth conversion: depth_m = two_way_time_ns * velocity_m_per_ns / 2.0
                    (converters/segy_converter.py, verified by reading the
                    executing line directly). A single constant-velocity,
                    single-medium model. No antenna-height/air-gap
                    correction, no per-region velocity (even though TU1208's
                    own FDTD permittivities span a factor of ~2 across its
                    four media).

5. Surface elevation: an entirely separate mechanism (a declared DEM/LIDAR
                    band, docs/surface-reference.md) — never automatically
                    joined to a GPR depth.

6. Absolute Z:      "Nothing performs that arithmetic yet"
                    (docs/depth-origin.md, verbatim) — converting a record's
                    depth into an elevation needs a vertical-datum tie, an
                    axis-origin offset AND a defensible velocity, together,
                    on the same survey. The sign convention is written down
                    (schemas/spatial.py::OFFSET_POSITIVE_MEANS) but nothing
                    consumes it.
```

**What this means for TU1208 specifically:** even where a reflector could be
matched to a target (it cannot, per §4), the resulting `depth_m` would carry
an assumed 0.1 m/ns velocity that TU1208's own authors say is wrong by up to
a factor of ~2 depending on material (permittivity 3 to 13 across the four
regions) — so a "successful" match under the current pipeline would not by
itself demonstrate a *correct* depth, only a *produced* one. This is a
second, independent reason the baseline could not have produced a
defensible number even if association existed.

## 6. Time-zero / velocity status

| Parameter | Status | Evidence |
|---|---|---|
| Time-zero (t0) | **Unknown, not independently measurable from this source** | 1 of 67 files carries a plausible header value (4.5 ns, one file, one operator setting, unverified against anything); 22 files carry a header value (93.7–100.1 ns) longer than their own recording window, which the converter already refuses to apply as physically meaningless; MALÅ's sidecar has no time-zero field; IDS's transmitter-receiver separation is stated confidential by the paper itself |
| Propagation velocity | **Not independently measured; a modelled cross-check exists and was deliberately not used as one** | FDTD-matched relative permittivities (silt 13, limestone 6, gneiss 14/20 3, gneiss 0/20 5.5) are published, with the authors' own caveat that "such estimations must be taken with care." They are stored as `ModelledPermittivity` with `is_a_velocity=False` and are never converted to a velocity anywhere in the truth or calibration modules — checked directly against the source for `m/ns`, `sqrt`, `299792458`, none of which appear |
| Separability, if both existed | **94–97% confounded on every real (surveyed) grouping** | Computed directly from the published depth sets (a property of the depths alone, independent of §4's association failure): `corr(t0, slope)` ranges −0.949 to −0.967 across the four material groupings, and pooling all 12 pipe-layer depths does not improve the correlation (−0.952), only its precision. Only the multilayer interfaces (5 points, span 3.10 m) reach a marginal −0.892 — and those are **derived** by cumulative sum, not surveyed, and cross five different materials, so a single velocity is wrong there by construction |

**No calibration was attempted and none is proposed here.** Per rule 8, a
parameter that had to be tuned against these same depths to make the
pipeline "work" would be a calibration experiment, not independent
validation — and this report does not perform one, because gate 1 (§4)
already makes it moot: there are no observations to calibrate against.

## 7. Validation classification

### Outcome D — Insufficient evidence

*"The apparent theodolite measurements cannot be reliably connected to the
GPR targets."* This is not a judgement call — it is what the association
gate measured directly: **0 of 36 targets could be tied to a specific
reflector in a specific trace**, because the paper publishes neither a
target's across-line offset from a named reference nor a profile's
along-line origin in that same reference. Two independent lines of evidence
also rule out **Outcome C (calibration only)**: even setting aside
association, the depth sets themselves are 94–97% t0/velocity-confounded
(§6), so TU1208 could not cleanly calibrate the pipeline either, only
jointly under-determine two parameters at once.

This is **not** Outcome A or B. Not one target reached a comparable estimate,
so there is no partial success to report — reporting "partial" would imply
some targets validated and others did not, when in fact the blocking
condition is structural and applies uniformly.

## 8. Localisation status — X, Y, Z reported independently

| Dimension | Status | Basis |
|---|---|---|
| **X** (along-line position) | 🔒 **Blocked** | No profile's along-line origin is published; 45 of 67 files carry a trace *spacing* (fixing scale) but none fixes a zero point |
| **Y** (across-line / transverse position) | 🔒 **Blocked** | Every one of 36 targets carries `transverse_offset_m: None`; sections print scale-bar segment lengths with no stated tie to the site's longitudinal axis |
| **Z** (depth) | 🔒 **Blocked for end-to-end validation** | The ground truth exists and is real (theodolite-surveyed); the conversion machinery exists and is honestly labelled (§5); but zero comparable estimates were produced because X and Y block the association a depth comparison depends on. Depth is not "partially validated" — it was never reached |

**The overall Localisation / X-Y-Z gate stays BLOCKED**, unchanged from
before this validation, on all three axes. TU1208 supplies the strongest
*geometry* Subterra holds — three-per-medium theodolite-surveyed depths,
over-determined enough to fit a velocity if association existed — but
supplies zero of the coordinate information needed to use it.

## 9. Code changes

**None.** The existing pipeline (`converters/segy_converter.py`), the
existing truth module (`benchmark/tu1208_truth.py`) and the existing
calibration script (`scripts/tu1208_depth_calibration.py`) were read,
re-run, and their 70 associated tests re-executed — all pass, unmodified.
**No implementation defect was found.** The 0.1 m/ns default and the absent
time-zero correction are documented, honestly labelled assumptions, not
bugs: `record.axis_metadata` and the frame's `Assumption` mechanism both
name them as such rather than presenting them as measurements.

## 10. Documentation changes

- **New**: this file (`docs/tu1208-physical-depth-validation-report.md`) —
  consolidates the confirmation run, the pipeline trace, and the explicit
  Outcome/X-Y-Z classification this task requested in a form the prior
  three TU1208 documents did not individually provide.
- **Updated**: `docs/roadmap.md` — the "Localisation / X-Y-Z scoring" row
  now names TU1208 explicitly with the per-axis breakdown above, rather than
  only referring to "both artifacts" (4TU, BAM).
- **Unchanged, cited as evidence**: `docs/tu1208-target-transcription.md`,
  `docs/tu1208-depth-calibration.md`, `docs/depth-origin.md`,
  `docs/stage25-shallow-time-zero-audit.md`, `docs/dataset-inventory.md`,
  `docs/cross-dataset-evidence-audit.md`.

## 11. Recommended next step

**Continue the 4TU evidence track and treat TU1208 as closed for now.**
Reasoning, strictly from what this pass measured:

- **Not "proceed to Phase 9."** Zero of X, Y, Z validated; Phase 9's own
  entry criteria (a defensible localisation path) are unmet.
- **Not "investigate depth calibration" on TU1208 specifically.** §6 already
  shows the depth sets are structurally confounded regardless of
  association; more work on this dataset's numbers would not change that
  property, which depends on the *shape* of the depth set, not on effort
  spent.
- **Not "integrate another benchmark" right now.** The one candidate this
  search identified outside the repository (Grimsel ISC,
  `docs/fallback-localisation-dataset-search.md`) scored 59/100 and carries
  an unresolved non-commercial licence question — not ready to integrate,
  and integrating it now would not be justified by this pass's findings.
- **Obtaining additional X/Y ground truth is the actual bottleneck**, and
  the cheapest concrete version of that is already named in
  `docs/tu1208-depth-calibration.md`'s own next-step list: **contact the
  TU1208 authors** for the along-line profile origin and per-target
  transverse offset — the two specific missing quantities identified in
  §4, not a vague request for "more data." This is the same kind of
  evidence-request action already under way for 4TU (the ter Huurne
  correspondence), applied to a second author.
- Continue the outstanding **4TU author correspondence** in parallel — it
  remains the only held dataset with both excavated depths and a declared
  vertical datum, and its own blocker (trench-to-trace registration) is the
  same *category* of gap TU1208 hit, so a reply that helps one may suggest
  what to ask the other.

---

## Reproduction

```bash
python -m scripts.tu1208_depth_calibration --out artifacts/tu1208/depth_calibration.json
python -m pytest tests/test_tu1208_target_truth.py tests/test_tu1208_depth_calibration.py -q
```

Both were re-run for this report against commit `ae2843d` and after. Backend
tests require the Docker environment documented in
`docs/test-environment.md`; the calibration script itself has no such
dependency and runs directly on the host.
