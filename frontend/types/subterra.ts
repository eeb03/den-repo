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
  grid: number[][]
  trace_indices: number[]
  depths?: number[] | null
  source_file?: string | null
  field?: string
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

export interface DatasetReport {
  report_version: string
  generated_at: string
  identity: {
    dataset_id: string
    name: string | null
    source: string | null
    source_url: string | null
    license: string | null
    modality: string | null
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
  quality: {
    stored_score: number | null
    computed_score: number | null
    dimensions: QualityDimension[]
    issues: string[]
    score_is_stale: boolean
  }
  candidates: {
    candidate_count: number
    analysed: boolean
    frames_with_candidates: string[]
    shape_classes: Record<string, number>
    evidence_available: boolean
    classified_object_count: number
    note: string
  }
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
  | 'surface_reference'

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

export interface SpatialReference {
  contract_version: string
  dataset_id: string
  dimensions: DimensionState[]
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
    notes?: string | null
  }
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
