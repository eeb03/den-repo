/**
 * Subterra domain types.
 *
 * These are transcribed from the backend's own schemas, verified against
 * `/api/openapi.json` generated from the running app (51 paths, 38 schemas).
 * The backend is authoritative: where a field is optional here, it is
 * optional there, and that optionality is usually load-bearing.
 *
 * Sources:
 *   schemas/spatial.py      -- Position union, SpatialRef
 *   schemas/provenance.py   -- ProvenanceClass, QuantityProvenance
 *   schemas/views.py        -- ViewKind, Selection, ViewResolution
 *   schemas/objects.py      -- ObservationRef, SubsurfaceObject
 *   schemas/labels.py       -- SemanticLabel
 *   benchmark/gates.py      -- gate statuses and open questions
 *
 * NOTE ON WHAT IS ABSENT. There is no `Scan`, no `Sensor`, no
 * `SystemHealth` and no `Operator` type here, though the v0 design had all
 * four. The platform ingests files, not live instruments; it has no job
 * lifecycle, no telemetry subsystem and no auth. Adding those types would
 * be inventing a data model the backend does not have.
 */

/* ------------------------------- provenance ------------------------------- */

/**
 * How much the data vouches for a value.
 *
 * Transcribed from `schemas.provenance.ProvenanceClass`. Deliberately NOT
 * ordered in the UI: the backend notes that "'assumed' and 'inferred' are
 * different kinds of doubt, not different amounts". A CLASS_STRENGTH map
 * exists server-side for sorting only, and is not mirrored here.
 */
export type ProvenanceClass =
  | 'measured'
  | 'declared_by_source'
  | 'supplied_by_caller'
  | 'derived'
  | 'inferred'
  | 'assumed'
  | 'unavailable'

/** One renderable provenance statement. `basis` is non-empty by contract. */
export interface QuantityProvenance {
  quantity: string
  provenance: ProvenanceClass
  basis: string
  value?: unknown
  verified?: boolean | null
}

/* -------------------------------- position -------------------------------- */

/**
 * A horizontal position, as a discriminated union on `kind`.
 *
 * This mirrors the backend exactly and is the single most important type in
 * this file. There is NO variant carrying an optional lat/lon: a sample
 * either has a geographic position or it has a documented reason for having
 * none. That shape is what makes "default it to (0,0)" unrepresentable
 * rather than merely discouraged.
 */
export type Position =
  | GeographicPosition
  | ProjectedPosition
  | LocalCartesianPosition
  | OdometryPosition
  | NoPosition

/** Latitude/longitude on a geodetic datum (the frame names which one). */
export interface GeographicPosition {
  kind: 'geographic'
  lat: number
  lon: number
}

/**
 * Easting/northing in a projected CRS. The EPSG code lives on the frame's
 * SpatialRef, not here. Deliberately unbounded server-side.
 */
export interface ProjectedPosition {
  kind: 'projected'
  easting: number
  northing: number
}

/**
 * Site-local cartesian coordinates. The frame states origin and
 * orientation; without those this converts to nothing else, which is
 * exactly why its kind is distinct from `projected`.
 */
export interface LocalCartesianPosition {
  kind: 'local_cartesian'
  x: number
  y: number
}

/**
 * Distance travelled along an acquisition path -- a wheel encoder, a cable
 * counter. The honest representation for GPR collected without GNSS: the
 * sensor knows how far it moved and does not know where on Earth it is.
 */
export interface OdometryPosition {
  kind: 'odometry'
  along_track_m: number
  cross_track_m?: number
  path_id?: string | null
}

/**
 * No horizontal position exists for this sample.
 *
 * `reason` is required and non-empty by backend contract -- the whole point
 * of the variant is recording WHY the position is absent.
 */
export interface NoPosition {
  kind: 'none'
  reason: string
}

/** Narrowing helper. The only sanctioned way to ask "can this be mapped?". */
export function isGeographic(p: Position | null | undefined): p is GeographicPosition {
  return p?.kind === 'geographic'
}

/**
 * Why a position cannot be placed on a map, in the backend's own words
 * where it supplied them.
 *
 * Returns null for a geographic position (there is nothing to explain).
 * Never invents a reason it was not given, but does describe the non-
 * geographic kinds, because "odometry" alone is not an explanation to a
 * reader who does not already know the data model.
 */
export function positionUnavailableReason(p: Position): string | null {
  switch (p.kind) {
    case 'geographic':
      return null
    case 'none':
      return p.reason
    case 'odometry':
      return 'position is along-track distance only; the acquisition has no georeference'
    case 'local_cartesian':
      return 'position is site-local cartesian; the frame declares no origin to place it on Earth'
    case 'projected':
      return 'position is in a projected CRS; a reprojection to WGS84 is required to map it'
  }
}

/* ------------------------------- confidence ------------------------------- */

/**
 * A confidence value that may legitimately be unknown.
 *
 * The backend returns `confidence: null` for labels where no confidence was
 * stated, and a test asserts no confidence is invented. `null` here means
 * "not stated" and MUST NOT render as 0%.
 */
export type Confidence = number | null

/* --------------------------------- views ---------------------------------- */

export type ViewKind = 'map' | 'radargram' | 'depth_slice' | 'scene_3d' | 'metadata'

export type SelectionKind = 'candidate' | 'object' | 'label' | 'trace' | 'frame'

/**
 * A view-independent selection identity, built only from identifiers the
 * platform already has. The client must not synthesise one.
 */
export interface Selection {
  kind: SelectionKind
  dataset_id: string
  selection_id: string
  frame_id?: string | null
  source_file?: string | null
  trace_index?: number | null
  trace_range?: [number, number] | null
  depth_range_m?: [number, number] | null
  position?: Position
}

/**
 * Where one view should look, or why it cannot.
 *
 * `resolved: false` is a first-class answer, not an error. The UI renders
 * `reason` and `missing` verbatim and never substitutes its own text.
 */
export interface ViewResolution {
  view: ViewKind
  resolved: boolean
  coordinates: Record<string, unknown>
  reason?: string | null
  missing: string[]
}

export interface SelectionResolution {
  selection: Selection
  views: ViewResolution[]
  resolvable_views: string[]
  unresolvable_views: string[]
}

/* -------------------------------- datasets -------------------------------- */

export type SensorType =
  | 'gpr'
  | 'seismic'
  | 'magnetometer'
  | 'ert'
  | 'gravity'
  | 'lidar'
  | 'dem'
  | 'satellite'
  | 'gps'
  | 'imu'

/** Row shape of `GET /api/datasets/`. */
export interface DatasetSummary {
  id: string
  name: string
  source: string | null
  sensor_type: string | null
  original_format: string | null
  quality_score: number | null
  record_count: number | null
  has_ground_truth: boolean | null
  /**
   * The dataset's own centre, when it has one. Null for a dataset whose
   * records carry no geographic position -- which is the case for most of
   * the corpus held today, and must not be filled in.
   */
  center_lat: number | null
  center_lon: number | null
  version: number | null
  created_at: string | null
  updated_at: string | null

  /* --------------------------- dataset management -------------------------- */

  /**
   * The ORIGINAL file this came from, kept distinct from `name`.
   *
   * Renaming a dataset changes what the user calls it and nothing about what
   * the file was. Collapsing the two would lose the provenance the moment
   * somebody tidied a list.
   */
  source_file: string | null
  checksum: string | null
  /** NULL owner: published reference data, readable by all and writable by none. */
  is_system_dataset: boolean
  /** importing | ready | empty | failed — derived, never stored. */
  status: 'importing' | 'ready' | 'empty' | 'failed'
  status_reason: string
  /** The originating import job's own state, carried through unrenamed. */
  job_state: string | null
  job_id: string | null
  /**
   * Other datasets ingested from the same source bytes.
   *
   * Detection only. Identical bytes are not the same dataset: the four INGV
   * entries in this corpus share a checksum and are four different ingestion
   * events under different converter behaviour.
   */
  shares_source_with: string[]
}

export interface DeletionResult {
  deleted: string
  removed: { artifacts: string[]; fusion_samples: number; versions: number }
  retained: { raw_source: string | null; import_jobs: number; why: string }
}

export interface RescoreResult {
  dataset_id: string
  previous_quality_score: number | null
  quality_score: number
  record_count: number
  issues: string[]
  note: string
}

export interface SpatialRefSummary {
  kind: string
  code?: string | null
  crs_provenance?: ProvenanceClass | string | null
  name?: string | null
  horizontal_units?: string | null
  vertical_datum?: string | null
  origin_description?: string | null
  [key: string]: unknown
}

export interface SurveyFrameSummary {
  frame_id: string
  source_file: string | null
  source_format: string | null
  modality: string
  modality_source: string | null
  n_positions: number
  position_index_name: string | null
  spatial_ref: SpatialRefSummary
  vertical_axis: Record<string, unknown>
  assumptions: Record<string, unknown>[]
}

/**
 * Shape of `GET /api/datasets/{id}/info`.
 *
 * `survey_area_m` and `grid_resolution_m` are null when the dataset has no
 * geographically positioned records -- the backend reports null rather than
 * a fabricated zero-sized survey, and the UI must preserve that.
 */
export interface DatasetInfo {
  dataset_id: string
  name: string
  sensor_type: string | null
  original_format: string | null
  source: string | null
  license: string | null
  record_count: number | null
  quality_score: number | null
  has_ground_truth: boolean | null
  coordinate_system: string | string[]
  position_sources: Record<string, number>
  survey_frames: SurveyFrameSummary[]
  survey_area_m: { lat_span: number; lon_span: number } | null
  geographic_record_count: number
  grid_resolution_m: number | null
  depth_layers: number[] | null
  processing_applied: unknown
  dem_aligned: boolean
  last_preprocessing_mode: string | null
}

/* --------------------------- objects and labels --------------------------- */

export type ObservationKind = 'candidate' | 'detection' | 'label' | 'trace'

export interface ObservationRef {
  kind: ObservationKind
  dataset_id: string
  observation_id: string
  frame_id?: string | null
  source_file?: string | null
  trace_index?: number | null
  position: Position
}

/**
 * A resolved subsurface object.
 *
 * `position` may be `NoPosition` -- association across sensors does not
 * confer a coordinate, and the backend says so explicitly in the reason.
 */
export interface SubsurfaceObject {
  id: string
  dataset_id: string
  status: string
  position: Position
  position_provenance: ProvenanceClass
  position_basis: string
  members: ObservationRef[]
  member_count?: number
}

/** Response envelope of `GET /api/objects/{dataset_id}`. */
export interface ObjectsResponse {
  dataset_id: string
  objects: SubsurfaceObject[]
  count: number
  /** How many carry a geographic position. The rest must not be plotted. */
  placed: number
  by_status?: Record<string, number>
  note?: string
}

/** One format `GET /api/exports/formats` offers, with what it needs and gives up. */
export interface ExportFormatInfo {
  value: string
  requires: string
  carries_full_provenance: boolean
  note?: string
}

export interface ExportFormatsResponse {
  formats: ExportFormatInfo[]
  rule: string
}

/**
 * What an export skipped, and why -- never silently. Fields beyond `id`/
 * `reason` vary by format (see `exports/exporters.py`), so they are kept
 * as unknown rather than typed field-by-field here.
 */
export interface ExportSkipped {
  id?: string | null
  reason: string
  [key: string]: unknown
}

export interface ExportReport {
  written: number
  skipped: ExportSkipped[]
  transformed: number
}

/**
 * The JSON-shaped export response (`json`/`geojson`/`czml`/`3d_tiles`).
 * `csv` is NOT this shape -- the backend returns it as `text/csv`, so
 * `api.exportDatasetObjects` resolves to a plain string for that format,
 * and this type is never assigned when `format === 'csv'`.
 */
export interface ExportResult {
  format: string
  payload: unknown
  report: ExportReport
}

export interface LabelSource {
  kind: string
  name: string
  version?: string | null
}

export interface LabelTarget {
  kind: string
  dataset_id: string
  target_id: string
  frame_id?: string | null
  source_file?: string | null
  trace_range?: [number, number] | null
}

export interface SemanticLabel {
  id: string
  kind: string
  value: string
  target: LabelTarget
  source: LabelSource
  /** null means "no confidence stated" and must not render as 0%. */
  confidence: Confidence
  provenance: ProvenanceClass
  position: Position
  processing_stage?: string | null
}

export interface LabelsResponse {
  dataset_id: string
  labels: SemanticLabel[]
  summary?: {
    count: number
    by_kind: Record<string, number>
    by_processing_stage: Record<string, number>
    by_source: Record<string, number>
    ground_truth_count: number
    provenance: unknown
  }
  note?: string
}

/* -------------------------------- overlays -------------------------------- */

export interface LayerExtent {
  native_kind?: string | null
  native_crs?: string | null
  wgs84_min_lat?: number | null
  wgs84_max_lat?: number | null
  wgs84_min_lon?: number | null
  wgs84_max_lon?: number | null
  /** Null when the layer has no positions to take an extent from. */
  wgs84_provenance?: ProvenanceClass | null
  wgs84_basis?: string | null
  n_positions_sampled?: number
  [key: string]: unknown
}

export interface OverlayLayer {
  layer_id: string
  dataset_id: string
  frame_id: string
  modality: string
  source_format?: string | null
  spatial_ref: SpatialRefSummary
  extent: LayerExtent
  provenance?: QuantityProvenance[]
}

export interface LayersResponse {
  dataset_id: string
  layer_count: number
  layers: OverlayLayer[]
}

/**
 * Result of `POST /api/overlays/compose`.
 *
 * `spatial_relationship: 'not_relatable'` is a real answer meaning the
 * layers must not be drawn together, and `unplaceable_layers` names the
 * ones that cannot be placed at all. Neither is an error.
 */
export interface Composition {
  layers: OverlayLayer[]
  spatial_relationship: string
  spatial_basis: string
  unplaceable_layers?: string[]
  vertical_relationship?: {
    kind: string
    absolute_elevation_available: boolean
    missing: string[]
  } | null
  suggested_view?: string | null
  notes?: string[]
}

/* --------------------------------- fusion --------------------------------- */

/**
 * `GET /api/fusion/samples`. Global, not scoped to one dataset -- a caller
 * filters `dataset_ids` itself.
 *
 * Deliberately 1:1 with the route's actual response, not the full
 * `FusionSample` database model. Only `spatial_ref_kind` says which centre
 * pair is meaningful -- `center_lat`/`center_lon` for `"geographic"`,
 * `center_x`/`center_y` otherwise. `sensor_types` and `has_ground_truth` are
 * stored facts, not a claim that the sample is "fused", "aligned" or
 * validated. `radius_m` is the stored clustering radius, not an accuracy or
 * tolerance figure. `n_reprojected` is the stored count of member records
 * that reached this centre through a CRS transform rather than carrying a
 * geographic coordinate of their own -- printed as the integer it is, never
 * used here to qualify or hide the centre.
 *
 * `dataset_ids` entries the caller cannot open (another user's dataset that
 * happens to share this sample) come back as the literal string
 * `"dataset-not-visible"` rather than the real id -- the array's length
 * still reports the true dataset count, but that entry is not a usable id.
 */
export interface FusionSample {
  id: string
  spatial_ref_kind: string
  center_lat: number | null
  center_lon: number | null
  center_x: number | null
  center_y: number | null
  sensor_types: string[]
  dataset_ids: string[]
  has_ground_truth: boolean
  radius_m: number
  n_reprojected: number
}

/**
 * A record partition `POST /api/fusion/run` could not fuse -- reported
 * with its reason rather than silently dropped, same discipline as every
 * other absence in this app. `dataset_ids`/`sensor_types` describe what
 * was excluded, not why; `reason` is the backend's own words.
 */
export interface FusionRunExcludedPartition {
  position_kind: string
  record_count: number
  dataset_ids: string[]
  sensor_types: string[]
  reason: string
}

/**
 * One sample from a live `POST /api/fusion/run` call -- NOT the stored
 * `FusionSample` shape. No `id` (nothing is persisted unless `persist`
 * was true) and no `dataset-not-visible` redaction (every input dataset
 * was already the caller's own visible set, enforced server-side). Carries
 * `record_counts`, a per-sensor breakdown the stored GET does not report.
 */
export interface FusionRunSample {
  spatial_ref_kind: string
  center_lat: number | null
  center_lon: number | null
  center_x: number | null
  center_y: number | null
  radius_m: number
  sensor_types: string[]
  dataset_ids: string[]
  has_ground_truth: boolean
  n_reprojected: number
  record_counts: Record<string, number>
}

/** The full response of `POST /api/fusion/run`, `persist` true or false. */
export interface FusionRunResult {
  input_record_count: number
  fusion_sample_count: number
  excluded_from_fusion: FusionRunExcludedPartition[]
  samples: FusionRunSample[]
}

/* ------------------------------- provenance ------------------------------- */

export interface FrameProvenance {
  frame_id: string
  source_file: string | null
  modality: string
  source_format: string | null
  provenance: (QuantityProvenance & { source?: string })[]
}

export interface FrameProvenanceResponse {
  dataset_id: string
  frame_count: number
  frames: FrameProvenance[]
}

/* -------------------------------- radargram ------------------------------- */

/**
 * `GET /api/datasets/{id}/trace_grid`.
 *
 * `depths` is present only when a propagation velocity was supplied at
 * ingest. When it is absent the vertical axis is a sample index and must be
 * labelled as one -- it is not a depth.
 */
export interface TraceGrid {
  /** (depth x trace). `null` means the acquisition recorded no sample there. */
  grid: (number | null)[][]
  trace_indices: number[]
  depths?: number[] | null
  source_file?: string | null
  available_source_files?: string[]
  field?: string
  /** What the numbers and axes are. Present since the radargram viewer. */
  semantics?: RadargramSemantics
  /** Per-cell reliability, same shape as `grid`. Only when requested. */
  reliability?: (boolean | null)[][] | null
  /** Candidate positions on THIS grid. Only when requested. */
  candidate_footprints?: CandidateFootprint[] | null
  trace_geographic?: boolean[]
  trace_along_track?: (number | null)[]
  velocity_m_per_ns?: number | number[] | null
  velocity_note?: string | null
  [key: string]: unknown
}

/* -------------------------------- benchmark ------------------------------- */

/** `benchmark.gates` uses exactly these two values. */
export type GateStatus = 'BLOCKED' | 'RESOLVED'

export interface OpenQuestion {
  id: string
  statement: string
  blocks: string
  resolution_route: string
  status: GateStatus
}

/** A run recorded by `POST /api/benchmark/score`, listed by `GET /runs`. */
export interface BenchmarkRun {
  id: string
  model_name: string
  dataset_id: string | null
  metrics: Record<string, number | null>
}

/** One entry of `GET /api/benchmark/artifacts`. */
export interface BenchmarkArtifactEntry {
  name: string
  group: string
  filename: string
  size_bytes: number
}

export interface BenchmarkArtifactsResponse {
  artifacts: BenchmarkArtifactEntry[]
  count: number
  note?: string
}

/**
 * A scoring artifact, as stored.
 *
 * Typed loosely on purpose. The artifact is the scoring script's output and
 * this UI is a reader of it: narrowing it to a fixed interface here would
 * silently drop any field a future scoring run adds, and dropping a field
 * from a scientific result is exactly the failure mode to avoid. The known
 * keys are declared for convenience; everything else passes through.
 */
export interface BenchmarkArtifact {
  benchmark?: string
  scope?: string
  localization_status?: GateStatus
  localization_blocked_reason?: string
  object_level_status?: GateStatus
  object_level_blocked_reason?: string
  activity_level_status?: GateStatus
  open_questions?: string[]
  threshold?: number
  min_cells?: number
  parameters_changed_for_this_benchmark?: string
  detection?: Record<string, unknown>
  score?: Record<string, unknown>
  provenance?: Record<string, unknown>
  grid?: Record<string, unknown>
  [key: string]: unknown
}


/* ------------------------------ dataset import ----------------------------- */

/**
 * The four states an import can be in. Deliberately finite and explicit: a job
 * is queued, running, or finished one way or the other. There is no
 * "processing…" catch-all that could hide a job the server has actually lost.
 */
export type ImportJobState =
  // The acquisition boundary, before anything is ingested. See
  // api/acquisition.py: one state machine, extended -- everything from QUEUED
  // onward is the original ingestion job, untouched.
  | 'RECEIVED'
  | 'IDENTIFIED'
  | 'NEEDS_INPUT'
  | 'REJECTED'
  // The ingestion pipeline, unchanged.
  | 'QUEUED'
  | 'RUNNING'
  | 'SUCCEEDED'
  | 'FAILED'

/**
 * Which pipeline step the job is in. NOT a percentage: the ingest pipeline
 * cannot measure fractional completion, and a number derived from a step index
 * would be a fabricated measurement.
 */
export type ImportStage =
  | 'queued'
  | 'converting'
  | 'validating'
  | 'preprocessing'
  | 'persisting'
  | 'registering'
  | 'complete'

/** How the converter registry classified the file. */
export type FormatStatus = 'supported' | 'recognized_unsupported' | 'unknown'

export interface ImportJob {
  id: string
  job_type: string
  state: ImportJobState
  stage: ImportStage | null
  original_filename: string | null
  stored_filename: string | null
  size_bytes: number | null
  sensor_type: string | null
  detected_format: string | null
  format_status: FormatStatus | null
  dataset_id: string | null
  error_stage: string | null
  error_message: string | null
  owner_id: string | null
  /* acquisition fields — see api/acquisition.py */
  checksum?: string | null
  content_type?: string | null
  identification?: AcquisitionIdentification | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
}

/** The registry's own answer about what can be read. Never duplicated in the UI. */
export interface ImportFormats {
  supported: string[]
  recognized_unsupported: { extension: string; description: string }[]
  max_upload_bytes: number
  note: string
}


/* --------------------------------- accounts -------------------------------- */

/**
 * The signed-in account, as the API reports it. Deliberately minimal: an
 * account exists to own datasets, and the password hash never leaves the
 * server.
 */
export interface AuthUser {
  id: string
  email: string
  display_name: string | null
  created_at: string | null
}

/* ------------------------------ dataset report ----------------------------- */

/**
 * The Dataset Report, from `GET /api/datasets/{id}/report`.
 *
 * Mirrors `schemas/dataset_report.py` exactly. Every field the backend may
 * leave undeclared is `| null` here rather than optional, so the UI has to
 * decide what to render for an absence instead of silently printing
 * `undefined` — which is how "not declared" quietly becomes a blank that
 * reads like zero.
 */
export type Readiness = 'ready' | 'partial' | 'blocked'

export type Capability =
  | 'ingestion'
  | 'validation'
  | 'signal_processing'
  | 'horizontal_registration'
  | 'vertical_registration'
  | 'candidate_analysis'
  | 'object_classification'
  | 'reconstruction_3d'

export interface CapabilityAssessment {
  capability: Capability
  readiness: Readiness
  reason: string
  missing: string[]
  depends_on: Capability[]
}

export interface QualityDimension {
  name: string
  /** null means deliberately unmeasured, never zero. */
  value: number | null
  weight: number
  basis: string
  counts: Record<string, number>
}

/* ---------------------------- candidates -------------------------------- */

/**
 * A candidate is NOT a detection.
 *
 * These types deliberately have no field for an object class, a probability or
 * a confidence, because the backend has none to send. `candidate_score` is a
 * peak anomaly magnitude that orders candidates within one dataset and means
 * nothing outside it — never render it as a percentage.
 */
export type LocalisationCertainty =
  | 'spatially_registered'
  | 'frame_relative'
  | 'trace_relative'
  | 'unknown'

export type DepthCertainty = 'measured' | 'derived' | 'unavailable'

export type CandidateReviewStatus = 'proposed' | 'reviewed' | 'accepted' | 'rejected'

export interface CandidateSummary {
  candidate_count: number
  analysed: boolean
  frames_with_candidates: string[]
  shape_classes: Record<string, number>
  evidence_available: boolean
  classified_object_count: number
  note: string
  status: 'available' | 'limited' | 'blocked'
  status_reason: string
  missing: string[]
  method: string | null
  method_version: string | null
  generated_at: string | null
  is_stale: boolean
  stale_reasons: string[]
  localisation_breakdown: Record<string, number>
  depth_breakdown: Record<string, number>
  classification_status: string
}

export interface CandidateGeneration {
  method: string
  method_version: string
  parameters: { threshold: number; min_cells: number; min_trace_span: number }
  generated_at: string
  dataset_id: string
  input_fingerprint: string
  declared_reference_at: string | null
  n_source_files: number
  n_records: number
  seed: number | null
  deterministic: boolean
  determinism_note: string
}

export interface AnomalyCandidate {
  id: string
  dataset_id: string
  evidence: {
    source_file: string
    trace_range: [number, number]
    depth_range: [number, number]
    n_supporting_cells: number
    peak_value: number
    peak_trace: number
    peak_depth: number
    mean_value: number
  }
  characteristics: {
    elongation: number | null
    compactness: number | null
    area_cells: number
    continuity_across_traces: number
    continuity_across_depth: number
    approx_lateral_extent_m: number | null
    lateral_extent_source: string | null
    approx_depth_extent_m: number
    centroid_lat: number | null
    centroid_lon: number | null
    centroid_elevation_m: number | null
  }
  /** Neutral geometry only. Never an object identity. */
  interpretation: { anomaly_class: string; note: string }
  confidence: {
    reliable_fraction: number
    touches_trace_boundary: boolean
    touches_depth_boundary: boolean
    kmz_direction_verified: boolean | null
    dem_vertical_datum_verified: boolean | null
    velocity_m_per_ns: number | null
  }
}

export interface InspectableCandidate {
  candidate: AnomalyCandidate
  candidate_score: number
  candidate_score_meaning: string
  localisation: LocalisationCertainty
  localisation_basis: string
  depth: DepthCertainty
  depth_basis: string
  status: CandidateReviewStatus
  classification_status: string
  classification_blocked_reason: string
}

export interface BenchmarkContext {
  method: string
  method_version: string
  summary: string
  measurements: {
    benchmark: string
    arm: string
    precision?: number
    recall?: number
    f1?: number
    chance_precision?: number
    times_chance?: number
    auc?: number
    ci95?: [number, number]
    contains_chance?: boolean
    n_negative?: number
    source: string
  }[]
  caveat: string
  /** The versioned ground-truth definition these numbers were computed under. */
  definition_version?: string | null
  /** What the ground truth genuinely supports scoring. */
  evaluated?: string[]
  /** Named explicitly — an unstated absence reads as a pass. */
  not_evaluated?: string[]
  /** Whether the benchmark could recognise an improvement if one happened. */
  adequacy?: string
}

/* ----------------------------- radargram -------------------------------- */

/**
 * What a radargram's numbers and axes actually are.
 *
 * These are not formatting hints. `derived_depth_default_velocity` is a
 * different quantity from `derived_depth_declared_velocity`, and both differ
 * from a measured depth; rendering any of them as "Depth (m)" would state a
 * measurement that was never made.
 */
export type VerticalAxisKind =
  | 'sample_index'
  | 'two_way_time_ns'
  | 'derived_depth_default_velocity'
  | 'derived_depth_declared_velocity'
  | 'measured_depth_m'
  | 'unknown'

export type VelocitySource = 'none' | 'converter_default' | 'declared'

export interface RadargramSemantics {
  vertical: {
    kind: VerticalAxisKind
    label: string
    units: string | null
    basis: string
    is_derived: boolean
    velocity_source: VelocitySource
    velocity_m_per_ns: number | null
    caveat: string | null
  }
  horizontal: {
    kind: 'trace_index' | 'along_track_m' | 'geographic'
    label: string
    units: string | null
    basis: string
    geographic_available: boolean
  }
  field: {
    field: string
    label: string
    /** null means no physical unit is established. Never print one anyway. */
    units: string | null
    description: string
    /** True when the values are a statistic computed FROM the signal. */
    is_statistic: boolean
    /**
     * Whether the reliability mask describes THESE values. It describes the
     * anomaly statistic, so it does not apply to the pre-anomaly signal —
     * an unreliable cell still holds a perfectly good stored value.
     */
    reliability_applies?: boolean
    reliability_note?: string | null
  }
  unreliable_cells: number | null
  total_cells: number | null
  reliability_note: string
  missing_note: string
}

/** The signal representations the radargram can project. */
export type RadargramField = 'signal' | 'pre_anomaly_signal'

/** Where one candidate sits on one grid — or why it cannot be placed. */
export interface CandidateFootprint {
  candidate_id: string
  placeable: boolean
  reason: string
  first_column: number | null
  last_column: number | null
  first_row: number | null
  last_row: number | null
  peak_column: number | null
  peak_row: number | null
}

/* ------------------------ ground-truth benchmark ------------------------ */

export type TruthLabel = 'positive' | 'negative' | 'unknown' | 'ambiguous' | 'excluded'

export type DuplicateStatus =
  | 'independent'
  | 'duplicate_of'
  | 'contaminated'
  | 'unknown'

export interface BenchmarkReadinessDimension {
  name: string
  readiness: 'ready' | 'partial' | 'blocked'
  reason: string
  missing: string[]
}

export interface BenchmarkPower {
  benchmark: string
  n_positive: number
  n_negative: number
  alpha: number
  power: number
  /** null means no estimate is possible at this size — never render as 0. */
  smallest_detectable_auc: number | null
  negatives_required: Record<string, number | null>
  se_at_chance: number | null
  adequate_for_a_useful_detector: boolean
  adequacy_anchor: string
  method: string
  caveat: string
}

export interface BenchmarkOpenQuestion {
  id: string
  statement: string
  blocks: string
  resolution_route: string
  status: string
  request_status: string
}

export interface BenchmarkEvaluationUnit {
  unit_id: string
  benchmark: string
  label: TruthLabel
  duplicate_status: DuplicateStatus
  shares_with: string[]
  contributes_independent_evidence: boolean
  exclusion_reason: string
  evidence: {
    basis: string
    source: string
    established_by: string
    coverage: string
    independent_of_subterra: boolean
    verified_by_subterra: boolean
    uncertainty: string
  }
  target: {
    count: number | null
    footprint_known: boolean
    location_known: boolean
    depth_known: boolean
    class_known: boolean
    described_as: string[]
  }
}

export interface BenchmarkDefinition {
  benchmark: string
  version: string
  schema_version: string
  content_hash: string
  counts: {
    units: number
    by_label: Record<string, number>
    by_duplicate_status: Record<string, number>
    independent_positives: number
    independent_negatives: number
  }
  policies: {
    duplicate: string
    exclusion: string
    metric: string
    threshold: string
  }
  power: BenchmarkPower | null
  readiness: BenchmarkReadinessDimension[]
  open_questions: BenchmarkOpenQuestion[]
  units: BenchmarkEvaluationUnit[]
}

export interface BenchmarkDefinitionArtifact {
  generated_by: string
  reads_detector_output: boolean
  corpus_unmodified: boolean
  benchmarks: Record<string, BenchmarkDefinition | { unavailable: true; reason: string }>
  bootstrap_cross_check: Record<string, unknown>
}

export interface CandidateIntelligence {
  dataset_id: string
  status: 'available' | 'limited' | 'blocked'
  status_reason: string
  missing: string[]
  definition: string
  generation: CandidateGeneration | null
  staleness: {
    is_stale: boolean
    reasons: string[]
    checks_performed: string[]
    checks_skipped: string[]
    note: string
  }
  candidate_count: number
  candidates: InspectableCandidate[]
  ranking_basis: string
  candidate_burden: number | null
  candidate_burden_basis: string
  localisation_breakdown: Record<string, number>
  depth_breakdown: Record<string, number>
  shape_classes: Record<string, number>
  classification_status: string
  classification_blocked_reason: string
  classified_object_count: number
  benchmark: BenchmarkContext
}

/**
 * `time_zero` comes first, always present once the chain is `recorded` --
 * a property of the acquisition itself, independent of whether
 * `process_gpr_traces` ran. The next three are the order `process_gpr_traces`
 * actually applies them in: background removal (needs the whole line at
 * once), then dewow, then gain, both per trace. `local_anomaly` is last and,
 * unlike the other four, only present at all when
 * `preprocess_trace_local_anomaly` actually ran -- it is not a property of
 * every GPR record.
 */
export type SignalProcessingStepName =
  | 'time_zero' | 'background_removal' | 'dewow' | 'gain' | 'local_anomaly'

export interface SignalProcessingStep {
  step: SignalProcessingStepName
  ran: boolean
  /** Only what was actually recorded for a step that ran; empty otherwise. */
  parameters: Record<string, unknown>
  /**
   * Populated for `time_zero` (ran=false alone cannot say whether a
   * converter recorded and withheld an offset, or nothing was recorded at
   * all) and for `local_anomaly` (its overwritten signal must not be read as
   * amplitude). `background_removal` / `dewow` / `gain` are self-explanatory
   * from name + `ran` and carry no reason.
   */
  reason: string | null
}

/**
 * The recorded Phase 5 signal chain, read from `processing_applied`, any
 * stored time-zero claim, and any local-anomaly stamp -- never re-run,
 * never a synthetic default chain. `recorded` is false only when NONE of
 * those exist; `steps` stays empty then.
 */
export interface SignalProcessingChain {
  recorded: boolean
  reason: string
  steps: SignalProcessingStep[]
}

export interface DatasetReport {
  report_version: string
  generated_at: string
  identity: {
    dataset_id: string
    name: string | null
    source: string | null
    source_url: string | null
    license: string | null
    /** The single recorded modality when the frames agree on exactly one; null when several, or none. */
    modality: string | null
    /** Sorted distinct `frame.modality` values actually recorded; empty when none. */
    recorded_modalities: string[]
    /** `dataset.sensor_type` verbatim, the ingest declaration -- independent of `recorded_modalities`. */
    declared_sensor_type: string | null
    original_format: string | null
    source_files: string[]
    manufacturer: string | null
    device_model: string | null
    collection_date: string | null
    imported_at: string | null
    updated_at: string | null
    checksum: string | null
    version: number | null
    owner_id: string | null
    is_system_dataset: boolean
    has_ground_truth: boolean
    undeclared: string[]
  }
  volume: {
    record_count: number
    frame_count: number
    positions_per_frame: Record<string, number | null>
    samples_per_trace: number[] | null
    sample_interval: number[] | null
    sample_interval_units: string | null
    records_with_signal: number
    records_with_timestamp: number
    records_with_depth: number
    records_with_position: number
    invalid_signal_count: number
    position_kinds: Record<string, number>
  }
  spatial: {
    horizontal: {
      coordinates_present: boolean
      earth_referenced: boolean
      declared_refs: string[]
      crs_kinds: string[]
      crs_provenance: string[]
      positioned_record_count: number
      total_record_count: number
      geo_tie_frames: string[]
      reasons: string[]
      missing: string[]
    }
    vertical: {
      axis_kinds: string[]
      axis_units: string[]
      axis_origins: string[]
      vertical_datum_declared: boolean
      vertical_datums: string[]
      depth_axis_available: boolean
      depth_basis: string
      time_to_depth_justified: boolean
      surface_model_held: boolean
      surface_frame_ids: string[]
      relationship_kind: string | null
      absolute_elevation_available: boolean
      reasons: string[]
      missing: string[]
    }
    geometry: {
      frame_count: number
      bounds: Record<string, number> | null
      lat_span_m: number | null
      lon_span_m: number | null
      along_track_extent_m: Record<string, number>
      reasons: string[]
    }
  }
  processing: {
    stage: string
    status: string
    detail: string | null
    parameters: Record<string, unknown>
    at: string | null
  }[]
  signal_chain: SignalProcessingChain
  quality: {
    stored_score: number | null
    computed_score: number | null
    dimensions: QualityDimension[]
    issues: string[]
    score_is_stale: boolean
  }
  candidates: CandidateSummary
  readiness: CapabilityAssessment[]
  provenance: {
    quantity: string
    provenance: string
    basis: string
    value: unknown
    verified: boolean | null
    source: string | null
  }[]
}

/* ----------------------------- spatial reference --------------------------- */

/**
 * The spatial contract, from `GET /api/spatial/{id}`.
 *
 * Seven dimensions, each with its OWN state vocabulary. They are not unified
 * into one enum because the distinctions differ — a CRS can be `inferred`, a
 * position cannot; depth can be `derived`, a datum cannot — and a shared
 * vocabulary would have to drop whichever distinction did not generalise.
 * Those are the distinctions that matter.
 */
export type SpatialDimensionName =
  | 'horizontal_position'
  | 'crs'
  | 'vertical_reference'
  | 'surface_reference'
  | 'orientation'
  | 'depth_conversion'
  | 'survey_geometry'

export type DeclarationKind =
  | 'crs'
  | 'vertical_datum'
  | 'antenna_offset'
  | 'depth_conversion'
  | 'geo_tie'
  | 'affine_tie'
  | 'surface_reference'
  | 'orientation'
  | 'time_zero'

export interface DimensionState {
  dimension: SpatialDimensionName
  state: string
  reason: string
  missing: string[]
  /** The declaration that would resolve this, or null when no declaration can. */
  action: DeclarationKind | null
  provenance: string | null
  detail: Record<string, unknown>
}

export interface SpatialDeclaration {
  id: string
  dataset_id: string
  frame_id: string | null
  kind: DeclarationKind
  value: Record<string, unknown>
  supplied_by: string
  note: string | null
  created_at: string | null
  superseded_at: string | null
  superseded_by: string | null
  active: boolean
}

/**
 * Whether the Phase 4 inputs are each individually resolved -- NOT whether a
 * common spatial frame has been computed. `state` is deliberately narrow:
 * `incomplete` or `inputs_present`, never `available` / `declared` /
 * `registered` / `ready`, none of which this ever asserts. Not a
 * `SpatialDimension` and not one of `SpatialReference.dimensions` -- a
 * statement about the seven dimensions, not an eighth one.
 */
export interface CommonFrameComposition {
  state: string
  reason: string
  inputs: SpatialDimensionName[]
  /** Distinct recorded CRS / vertical-datum codes from RESOLVED inputs only, sorted, verbatim. */
  crs_codes: string[]
  vertical_datum_codes: string[]
  /** Sibling of `state`: `agree` / `disagree` / `undetermined` only. `undetermined` unless `state === 'inputs_present'`. */
  agreement: string
}

export interface SpatialReference {
  contract_version: string
  dataset_id: string
  dimensions: DimensionState[]
  common_frame: CommonFrameComposition
  declarations: SpatialDeclaration[]
  has_stale_products: boolean
  stale_products: string[]
}

/* ------------------------------- acquisition ------------------------------- */

/**
 * What identification established about an arriving file, before ingestion.
 *
 * `spatial_expectation` is what the FORMAT can carry — not what this file
 * declares. The dataset report answers the second question, once the file has
 * actually been read.
 */
export interface AcquisitionIdentification {
  original_filename: string | null
  stored_filename: string | null
  size_bytes: number | null
  checksum: string | null
  content_type_claimed: string | null
  classification: string
  detected_format: string
  parser_available: boolean
  declared_modality: string | null
  modality_source: string
  ambiguous_format: boolean
  ambiguity_note: string | null
  spatial_expectation: {
    horizontal: string
    vertical: string
    missing: string[]
  }
  spatial_expectation_note: string
  duplicates: {
    checked: boolean
    is_duplicate?: boolean
    datasets?: { dataset_id: string; name: string }[]
    acquisitions?: { acquisition_id: string; original_filename: string | null }[]
    note?: string
    reason?: string
  }
  ingestion_ready: boolean
  rejection_reason?: string
  supported_formats?: string[]
}

/* --------------------------------- devices --------------------------------- */

/**
 * A record of an instrument somebody says they used.
 *
 * `identity_source` is currently always `user_declared`: every field was typed
 * by a person. A future adapter that genuinely reads a serial off hardware will
 * write `device_reported`, and the two must stay distinguishable.
 */
export interface Device {
  id: string
  owner_id: string | null
  is_system_device: boolean
  manufacturer: string | null
  model: string | null
  device_type: string
  serial_number: string | null
  firmware_version: string | null
  capabilities: {
    modalities?: string[]
    reports_position?: boolean
    reports_orientation?: boolean
    reports_absolute_time?: boolean
    /** Declared operating/antenna frequency in MHz. Absent means undeclared. */
    frequency_mhz?: number | null
    /** Declared channel count. Absent means undeclared. */
    channels?: number | null
    /** Free-form, e.g. { sample_interval_ns, samples_per_trace }. */
    sampling_configuration?: Record<string, unknown>
    /** File formats this instrument can write, from the platform's own read registry. */
    supported_export_formats?: string[]
    notes?: string | null
  }
  /**
   * HOW this device's evidence is meant to arrive -- not a connection, a
   * session, or a capability. `null` means undeclared; a device with no
   * adapter is valid and this must never be filled in with `file_drop`.
   */
  adapter: { transport: 'file_drop' | 'network' | 'serial' } | null
  identity_source: 'user_declared' | 'device_reported'
  kind: 'physical' | 'simulated'
  is_simulated: boolean
  label: string | null
  created_at: string | null
}

export type SessionState =
  | 'CREATED'
  | 'READY'
  | 'ACQUIRING'
  | 'COMPLETED'
  | 'CANCELLED'
  | 'FAILED'

export interface AcquisitionSession {
  id: string
  device_id: string
  owner_id: string | null
  state: SessionState
  label: string | null
  operator: string | null
  notes: string | null
  /**
   * Where the operator said this scan happened, in their own words. NOT a
   * geometry, a CRS or a bounding box, and not `DatasetInfo.survey_area_m`
   * (a computed lat/lon span) -- this is declared, that is derived.
   */
  survey_area: string | null
  /**
   * What the operator said this scan was referenced to, in their own words
   * -- "EPSG:32633", "local site grid", "tape measure only". NOT a spatial
   * registration and never defaulted (in particular, never `EPSG:4326`,
   * `Dataset.coordinate_system`'s legacy default). Stage 8
   * (SpatialDeclaration, the seven-dimension assessment) remains the only
   * thing that settles a CRS.
   */
  coordinate_system: string | null
  /**
   * What the operator said this scan's verticals were measured from, in
   * their own words -- "NAP", "ground surface", "tape from the slab". NOT
   * a vertical registration and never defaulted. Stage 8's
   * `vertical_reference` dimension and `fusion.vertical_reference.assess`
   * remain the only things that settle a vertical registration.
   */
  vertical_reference: string | null
  /**
   * What the operator said was applied to this scan before it entered
   * Subterra, in their own words -- "raw, no onboard processing", "RADAN
   * 7.6 time-zero applied". NOT Subterra's own pipeline mode
   * (`DatasetInfo.last_preprocessing_mode`) and never defaulted.
   */
  processing_version: string | null
  evidence: {
    position_provided?: boolean
    position_source?: string | null
    orientation_provided?: boolean
    orientation_source?: string | null
    absolute_time_provided?: boolean
    acquisition_parameters?: Record<string, unknown>
  }
  failure_stage: string | null
  failure_message: string | null
  created_at: string | null
  started_at: string | null
  ended_at: string | null
}

export interface SessionPayload {
  session: AcquisitionSession
  device: Device | null
  /** What the device can produce and this session did not. */
  capability_gap: string[]
  acquisitions: {
    acquisition_id: string
    state: string
    original_filename: string | null
    dataset_id: string | null
  }[]
  datasets: string[]
}

/**
 * Where a dataset came from, from `GET /api/datasets/{id}/acquisition`.
 *
 * THREE STATES, never collapsed: `acquisition` is null for a dataset that
 * predates the acquisition boundary (`reason` explains why); `session` and
 * `device` are null for an ordinary FileDrop, which is a source in its own
 * right, not a session with a missing device; otherwise all three are
 * present and the dataset came from a device session.
 */
export interface DatasetAcquisition {
  dataset_id: string
  acquisition: ImportJob | null
  session: AcquisitionSession | null
  device: Device | null
  /** Present only when `acquisition` is null. */
  reason?: string
}

/**
 * The reconstructed-scene payload, from `GET /api/scene/{datasetId}`.
 *
 * THREE CLAIMS, never collapsed (see `schemas/scene.py`): DECLARED (an
 * operator supplied a value), DERIVED (Subterra computed one from declared
 * inputs), VALIDATED (independent external evidence confirms a physical
 * position). This payload only ever carries the first two.
 * `validation_status` says so explicitly on every response, resolved or
 * not — render it, do not paraphrase it.
 */
export type VerticalRelationshipKind =
  | 'absolute_elevation' | 'relative_depth_only' | 'registration_required' | 'unrelated'

export interface ScenePosition {
  available: boolean
  lat: number | null
  lon: number | null
  basis: LocalisationCertainty
  reason: string
}

export interface SceneElevation {
  available: boolean
  elevation_m: number | null
  depth_m: number | null
  depth_certainty: DepthCertainty
  provenance: string
  reason: string
}

export interface SceneSurfacePoint {
  lat: number
  lon: number
  elevation_m: number
}

export interface SceneSurface {
  frame_id: string
  dataset_id: string
  modality: string
  vertical_datum_code: string | null
  vertical_datum_provenance: string | null
  points: SceneSurfacePoint[]
  point_count_total: number
  downsampled: boolean
}

export interface SceneCandidate {
  id: string
  position: ScenePosition
  elevation: SceneElevation
  score: number
  score_meaning: string
  anomaly_class: string
  note: string
  source_file: string
  trace_range: [number, number]
  depth_range: [number, number]
  evidence_reference: string
}

/**
 * Stage A: one individual measurement whose processed signal exceeded the
 * same anomaly-evidence threshold candidate generation uses -- placed
 * individually, never grouped, never connected to a neighbour. NOT a
 * candidate and NOT a structure: no shape, no class, no claim beyond "this
 * one measurement's value was this strong, here".
 */
export interface SceneEvidenceSample {
  source_file: string
  trace_index: number
  depth_m: number
  evidence_value: number
  reliable: boolean
  position: ScenePosition
  elevation: SceneElevation
  evidence_reference: string
}

export interface SceneEvidenceField {
  samples: SceneEvidenceSample[]
  threshold: number
  point_count_total: number
  downsampled: boolean
  excluded_unpositioned_count: number
  reason: string | null
}

export interface SceneVerticalRelationship {
  kind: VerticalRelationshipKind
  subsurface_frame_id: string | null
  surface_frame_id: string | null
  reasons: string[]
  missing: string[]
}

export interface ScenePayload {
  dataset_id: string
  resolved: boolean
  resolution_reason: string | null
  missing: string[]
  vertical_relationship: SceneVerticalRelationship | null
  surface: SceneSurface | null
  candidates: SceneCandidate[]
  evidence: SceneEvidenceField | null
  validation_status: string
  diagnostic_views: Record<string, string>
}
