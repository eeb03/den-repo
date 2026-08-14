# Dataset reports

`GET /api/datasets/{id}/report` answers one question, in order:

> What is this dataset, what happened to it, how far can it be trusted, and
> what may Subterra legitimately do with it next?

The last clause is the one that matters. Everything above it is evidence for it.

## Why this is a domain value, not a UI response

Four later stages need the same answers — the spatial workflow needs to know
what registration is missing, candidate intelligence needs to know whether a
radargram can be reconstructed, reconstruction needs to know whether an
absolute elevation exists, and the non-expert mode needs all of it in one
sentence each. Deciding that in a route handler would mean deciding it four
more times, differently.

```
schemas/dataset_report.py     what a report MEANS      pure, no I/O
        ↑
api/reports.py                what is STORED           loads records, frames, labels
        ↑
api/routes/datasets.py        one endpoint
```

Stage 8 and stage 17 call `api.reports.build_dataset_report` directly. The route
is one consumer, not the interface.

## What it reuses

Nothing about readiness is newly invented. The report **consumes** judgements
that already existed and were only reachable per-selection or per-frame-pair:

| Existing | Was answerable for | The report adds |
|---|---|---|
| `schemas/views.resolve` | one selection, one view | — |
| `fusion.vertical_reference.assess` | one frame pair | the dataset's weakest pair |
| `schemas/provenance.frame_provenance` | one frame | every frame, projected |
| `validators.dataset_validator` | one score | the dimensions behind it |

The quality score is **unchanged**. `validate_dataset` now computes it *from*
`quality_dimensions` rather than beside it, so the number the report shows and
the number stored on the dataset row are the same arithmetic and cannot drift. A
test pins them together.

## Readiness means capability, not completion

`candidate_analysis: ready` says the dataset carries what candidate analysis
needs — not that candidates have been found. The two failure modes are
different: *not run yet* is a scheduling fact, *cannot be run* is a property of
the evidence. Only the second is a blocker.

Three states, deliberately not four. There is no `unknown`: if the report cannot
establish that a capability is available, that **is** a blocker, and calling it
unknown would let an unanswerable question look like a pending one.

**Every non-ready state carries `missing`.** A blocker with no enumerated cause
is indistinguishable from a bug and cannot be acted on. A test asserts no
capability may be non-ready with an empty `missing` list.

### The eight capabilities

| Capability | Ready when |
|---|---|
| `ingestion` | records were converted and stored |
| `validation` | the dataset has been scored |
| `signal_processing` | records carry sample values |
| `horizontal_registration` | every frame is Earth-referenced *and* records are positioned |
| `vertical_registration` | `assess` returns `absolute_elevation` |
| `candidate_analysis` | traces can be grouped by frame — **no position required** |
| `object_classification` | never, currently |
| `reconstruction_3d` | never, currently |

`candidate_analysis` being ready on a dataset whose horizontal registration is
blocked is correct, not a bug: an anomaly lives in a trace. Requiring a position
would block the one thing an unpositioned GPR line *can* support.

**`object_classification` is blocked for every dataset, and not because of any
dataset.** Subterra has no validated classifier: the baseline detector scores at
or below chance on both benchmarks and no model has passed validation. This is
the structural guard against candidate becoming detection, and it is a property
of the platform, so no dataset can unblock it.

## What the report may never say

Enforced by the model's shape, not by copy:

- `CandidateSummary` has **no field** for an object class, a probability or a
  confidence. The wire format cannot carry a detection.
- `classified_object_count` is structurally 0.
- Survey extent is `None` where no record carries a geographic position — never
  a zero-sized survey at (0, 0), the exact failure the `Position` union was
  built to prevent.
- A quality dimension with no defensible normalisation reports `value: null`
  and says why. `null` and `0.0` are opposite claims: one says nothing is known,
  the other says something bad is known.
- Identity fields are never inferred. A `.dt` file implies IDS to a human; it
  must not imply it to the report. Undeclared fields are **listed by name** so a
  blank cannot be read as a zero.

## Report shape

```
report_version, generated_at
identity      what it is; `undeclared[]` names the absences
volume        counts, frames, samples per trace, position kinds
spatial       horizontal | vertical | geometry, each with reasons[] and missing[]
processing    stage, status (completed | not_run | unavailable), detail
quality       stored_score, computed_score, dimensions[], score_is_stale
candidates    counts and neutral shape classes; never objects
readiness     eight CapabilityAssessments
provenance    the frame-level projection
```

`volume.record_count` is counted **live**, not read from `datasets.record_count`
— that column is stored and can go stale, and a report repeating it would be
describing a dataset that no longer exists. `quality.score_is_stale` surfaces
the same class of drift for the score rather than hiding it. Two of the six held
datasets are currently stale (stored 0.30, computed 0.80): they were scored
before `NoPosition` replaced the `(0, 0)` placeholder, so their coordinate
dimension was being penalised for coordinates the format never had.

Unlike `/info`, a dataset with **no records is not a 404**. "This produced
nothing" is one of the most useful things a report can say, and a 404 would make
an empty dataset indistinguishable from a missing one.

---

# Stage 8 dependency report

What the spatial reference workflow will need, measured against the six datasets
currently held rather than assumed.

| Dataset | Records | Horizontal | Vertical axis | Datum | H | V |
|---|---:|---|---|---|---|---|
| Lazaresti COP30 DEM | 196 | EPSG:4326 | none | — | ready | blocked |
| Lazaresti GPR depth slice | 157,040 | EPSG:4326 | `depth_m` | — | ready | partial |
| INGV-UNISA Site 1 GPR | 10,727 | unknown | none | — | blocked | blocked |
| INGV-UNISA Site 1 GPR v2 | 10,727 | unknown | none | — | blocked | blocked |
| INGV-UNISA Site 1 GPR v3 | 10,727 | EPSG:4326 | none | — | ready | blocked |
| INGV-UNISA Site 1 GPR v3 (dup) | 10,727 | EPSG:4326 | none | — | ready | blocked |

### Already available

- **Horizontal registration for four of six datasets.** EPSG:4326, declared,
  with positioned records. This is genuinely done — stage 8 does not need to
  solve it for these.
- **A depth axis on one dataset** (Lazaresti, `depth_m`), derived from time by a
  caller-supplied velocity. Depth *below the acquisition surface* is known.
- **The vocabulary to express every missing piece.** `VerticalDatum`,
  `GeoTie`, `Assumption`, `CRSProvenance` and `VerticalRelationshipKind` already
  exist and are enforced. Stage 8 is largely about **populating** these, not
  designing them.
- **A refusal that is already correct.** `assess` computes no Z and says what is
  missing. Nothing needs to be undone.

### Missing

1. **A vertical datum on every frame.** Not one of the six declares one. This is
   the single blocker on `vertical_registration` everywhere.
2. **A usable surface model.** This is worse than the table suggests. The
   Lazaresti COP30 DEM is held, but:
   - it has **no stored `SurveyFrame`** — its frame is *reconstructed* from
     records, with origin `"unrecorded (reconstructed frame)"`;
   - its vertical axis is `none`, not `elevation_m`;
   - **0 of its 196 records carry an elevation.**

   So Subterra holds a DEM that cannot anchor anything. It was ingested before
   frames existed and its elevations were not preserved as elevations. **This is
   the most actionable finding in this report**: it is a re-ingestion, not a
   research problem.
3. **The offset from the depth-axis origin to the ground.** GPR time zero is
   when the instrument fired, not the surface. For an air-launched antenna this
   is an air path a constant ground velocity does not model.
4. **A horizontal reference for the two INGV v1/v2 datasets** — no record carries
   a position at all.

### Ambiguous

- **The 4TU per-trace elevations.** They agree with the AHN surface to
  −0.70 ± 0.41 m, which is close enough to look tempting. The residual mean
  varies from +0.43 m to −1.33 m *between* the nine activities of the same site
  while staying tight *within* each one (sd 0.04–0.28 m). A fixed antenna height
  would be constant. Terrain change, pole setup, GNSS vertical error and geoid
  model are all consistent with what is observed, and nothing in the data
  separates them. **Declaring a datum on this basis would be inventing
  provenance.**
- **Whether the four INGV datasets are the same survey.** Four rows, three
  names, two of them byte-identical in record count. `v3` appears twice.
  Duplicate management is stage 7, but it affects any per-site registration.
- ~~**SEG-Y header positions vs the KMZ.**~~ **Resolved 2026-08-06**, and kept
  here because the earlier entry said the opposite. The headers are a genuine
  per-trace track, not the static placeholder this project once recorded them
  as: 67/72 and 66/66 distinct positions, track lengths agreeing with the KMZ to
  ~0.02%, mean residuals 0.74 m and 1.22 m. **SEG-Y header positions are
  authoritative where usable**; the KMZ is the fallback, used only when the
  headers cannot yield a geographic position. See the CORRECTION in
  `ingestion/kmz_georeference.py`.

### Required evidence

- From **4TU**: the vertical datum of the SEG-Y trace elevations, and the antenna
  height or time-zero convention used per activity.
- From **BAM**: confirmation of the absolute origin of the test-field coordinate
  system.
- From **PDOK/AHN**: NAP is documented but absent from the GeoTIFF; it must be
  supplied explicitly rather than assumed from documentation.
- Author requests for the first two are already drafted and outstanding.

### Required user input

Stage 8's workflow is, concretely, a way for a person to **declare** what the
file does not:

1. A vertical datum per frame, with `CRSProvenance.SUPPLIED_BY_CALLER` and an
   attribution — who asserted it, on what authority.
2. A depth-axis origin offset (antenna height above ground), same treatment.
3. A propagation velocity where depth is wanted from time — already supported,
   already recorded as an assumption.
4. A `GeoTie` for unpositioned frames: at least two surveyed control points at
   distinct along-track distances.

Every one of these already has a schema. None requires a new concept. What is
missing is a route and a UI to write them, and the report is what tells the user
which of them their dataset needs.

### Potential acquisition strategy

The cheapest path to a dataset that reaches `vertical_registration: ready` is
almost certainly **to acquire one**, not to recover a datum from published data:

- A short controlled survey over a known target, with the antenna height
  measured, the time-zero convention recorded, and GNSS elevations tied to a
  declared datum, would produce the first dataset in the corpus that can be
  vertically registered — and therefore the first that could support a 3D
  reconstruction at all.
- This is also what stages 9–12 build toward. **Controlled acquisition is not a
  detour from the spatial blocker; it is one of the few routes that produces the
  evidence the blocker needs**, and it simultaneously produces the ground truth
  stage 14 requires.

Re-ingesting the COP30 DEM with a declared elevation axis is the smaller,
immediate win and should not wait for any of the above.
