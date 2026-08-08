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
  center_lat: number | null
  center_lon: number | null
  version: string | null
  created_at: string | null
}

export interface SpatialRefSummary {
  kind: string
  code?: string | null
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
  objects: SubsurfaceObject[]
  count: number
  /** How many carry a geographic position. The rest must not be plotted. */
  placed: number
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
  labels: SemanticLabel[]
  count?: number
  summary?: Record<string, unknown>
}

/* -------------------------------- overlays -------------------------------- */

export interface LayerExtent {
  native_kind?: string | null
  native_crs?: string | null
  wgs84_provenance?: ProvenanceClass | null
  wgs84_basis?: string | null
  [key: string]: unknown
}

export interface OverlayLayer {
  layer_id: string
  modality: string
  extent: LayerExtent
}

/**
 * Result of `POST /api/overlays/compose`.
 *
 * `spatial_relationship: 'not_relatable'` is a real answer meaning the
 * layers must not be drawn together.
 */
export interface Composition {
  spatial_relationship: string
  spatial_basis: string
  vertical_relationship?: {
    kind: string
    absolute_elevation_available: boolean
    missing: string[]
  } | null
  notes?: string[]
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
