/** Subterra Volume V1 payloads -- mirrors `schemas/volume.py` and `api/volumes.py`. */

export type ZDomain = 'depth' | 'two_way_time'
export type SupportClassName = 'UNSUPPORTED' | 'INTERPOLATED' | 'RECONSTRUCTED' | 'MEASURED'

export interface VolumeAxis {
  name: string
  n: number
  origin: number
  step: number
  unit: string
  description: string
}

export interface VolumeConfig {
  frame_id?: string | null
  z_domain?: 'auto' | 'depth' | 'time'
  migration?: 'none' | 'stolt_fk_3d'
  interpolation?: 'nearest_no_fill' | 'linear_bounded'
  output_line_spacing_m?: number | null
  max_gap_line_spacings?: number
  dewow?: boolean
  background_removal?: 'none' | 'line_mean'
}

export interface PropertyField {
  property_name: string
  unit: string
  value_kind: string
  description: string
  method: string
  uncertainty?: string | null
  evidence_sources: string[]
  stats: Record<string, number>
}

export interface Staleness {
  stale: boolean
  changed_components?: string[]
  reasons: string[]
  action?: string | null
}

export interface VolumeCoordinateFrame {
  kind: 'local_volume' | 'georeferenced_volume'
  description: string
  x_meaning: string
  y_meaning: string
  z_meaning: string
  z_origin: string
  horizontal_registration?: Record<string, unknown> | null
  absolute_elevation: boolean
  notes: string[]
}

export interface VolumeProduct {
  id: string
  dataset_id: string
  frame_ids: string[]
  coordinate_frame: VolumeCoordinateFrame
  x_axis: VolumeAxis
  y_axis: VolumeAxis
  z_axis: VolumeAxis
  z_domain: ZDomain
  shape: [number, number, number]
  voxel_spacing: [number, number, number]
  fields: PropertyField[]
  primary_field: string
  support_summary: Record<SupportClassName, number>
  reconstruction_method: string
  processing: { name: string; applied: boolean; parameters: Record<string, unknown>; note: string }[]
  migration: {
    method: string
    velocity_m_per_ns?: number | null
    velocity_source?: string | null
    time_zero_ns?: number | null
    time_zero_source?: string | null
    assumptions: string[]
    parameters: Record<string, unknown>
  }
  interpolation: { mode: string; output_line_spacing_m: number; max_gap_m: number; max_gap_rule: string }
  calibration_provenance: Record<string, unknown>
  created_at: string
  validation_status: string
  what_it_is_not: string
  performance: Record<string, number>
  notes: string[]
  staleness: Staleness
  support_class_meaning: Record<SupportClassName, string>
  support_class_values: Record<SupportClassName, number>
}

export interface VolumeListItem {
  id: string
  created_at: string
  z_domain: ZDomain
  reconstruction_method: string
  shape: [number, number, number]
  coordinate_frame: string
  staleness: Staleness
}

export interface VolumePreview {
  possible: boolean
  refusals: string[]
  notes: string[]
  missing: string[]
  resolved: Record<string, unknown>
  depth?: {
    z_domain: ZDomain
    depth_scientifically_sufficient: boolean
    velocity_m_per_ns?: number | null
    time_zero_ns?: number | null
    readiness?: { reasons?: string[] }
  }
  estimated_shape?: [number, number, number]
  voxel_spacing?: [number, number, number]
  voxel_spacing_units?: [string, string, string]
  estimated_bytes?: number
  interpolation_required?: boolean
}

export type Orientation = 'xy' | 'xz' | 'yz'
export type FieldName = 'radar_response' | 'response_envelope'

export interface VolumeSlice {
  volume_id: string
  orientation: Orientation
  index: number
  field: FieldName
  thickness_voxels: number
  rows: number
  cols: number
  axes: { rows: string; cols: string }
  values_f32_b64: string
  support_u8_b64: string
  stats: Record<string, number>
  note?: string | null
}

export interface VoxelInfo {
  i: number
  j: number
  k: number
  x_m: number
  y_m: number
  z: number
  z_unit: string
  z_domain: ZDomain
  z_meaning: string
  values: Record<string, number | null>
  support_class: SupportClassName
  support_meaning: string
  support_count: number
  support_count_meaning: string
  nearest_measurement_distance_m: number | null
  interpolation_distance_m: number | null
  reconstruction_method: string
  migration: Record<string, unknown>
  depth_calibration: Record<string, unknown>
  source_frames: string[]
  coordinate_frame: string
  validation_status: string
}

export interface VolumeRender3D {
  volume_id: string
  field: FieldName
  display_only: true
  note: string
  original_shape: [number, number, number]
  shape: [number, number, number]
  block_factors: [number, number, number]
  scale: number
  data_u8_b64: string
  support_u8_b64: string
}

export type GroundTruthObject =
  | { id: string; kind: 'duct'; role: string; axis: 'y'; x_m: number; z_centre_m: number; z_top_m: number; radius_m: number; y_range_m: [number, number] }
  | { id: string; kind: 'box'; role: string; x_range_m: [number, number]; y_range_m: [number, number]; z_range_m: [number, number]; material?: string }
  | { id: string; kind: 'surface_marker'; role: string; x_m: number; y_m: number; note?: string }
  | { id: string; kind: 'plane'; role: string; x_range_m: [number, number]; y_range_m: [number, number]; z_m: number }

export interface GroundTruthOverlay {
  label: string
  available: boolean
  reason?: string
  specimen_id?: string
  source?: string
  objects: GroundTruthObject[]
}
