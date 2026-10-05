/** Interpretation V1 payloads -- mirrors `schemas/region.py` / `api/regions.py`. */
export type RegionReviewStatus = 'unreviewed' | 'confirmed_response' | 'rejected_response' | 'uncertain'

export interface Triple { x: number; y: number; z: number }

export interface RegionReview {
  status: RegionReviewStatus
  reviewer_id?: string
  notes?: string | null
  timestamp?: string
  evidence_grade?: string
  ground_truth_status?: string
}

export interface ResponseRegion {
  id: string
  region_set_id: string
  volume_id: string
  z_domain: string
  z_unit: string
  status: 'proposed' | 'low_support'
  voxel_count: number
  centroid: Triple
  peak_location: Triple
  peak_index: [number, number, number]
  bounds: { x_min: number; x_max: number; y_min: number; y_max: number; z_min: number; z_max: number }
  index_bounds: [number, number, number, number, number, number]
  physical_extent: Triple
  fwhm: Triple
  lines_spanned: number
  support: {
    measured_voxel_fraction: number
    reconstructed_voxel_fraction: number
    interpolated_voxel_fraction: number
    unsupported_voxel_fraction: number
    nearest_measurement_distance_m: Record<string, number>
    peak_support_class: string
  }
  shape: { elongation: number; flatness: number; compactness: number; azimuth_deg?: number | null; dip_deg?: number | null }
  evidence: { modality: string; property_name: string; unit: string; method: string; peak_value: number; peak_robust_z: number; peak_local_contrast: number; integrated_response: number; mean_response: number }[]
  score_components: Record<string, number>
  evidence_score: number
  merged_from: number[]
  flags: string[]
  meaning: string
  review: RegionReview
  review_history?: (RegionReview & { reviewer_id: string; timestamp: string })[]
  generation?: { algorithm: string; version: string; threshold_method: string; config: Record<string, unknown>; created_at: string; migrated_volume: boolean }
}

export interface RegionSet {
  id: string
  volume_id: string
  algorithm: string
  algorithm_version: string
  threshold_method: string
  config: Record<string, unknown>
  z_unit: string
  migrated: boolean
  created_at: string
  regions: ResponseRegion[]
  rejected: Record<string, number>
  merges: unknown[]
  performance: Record<string, number>
  meaning: string
  staleness: { stale: boolean; reasons: string[]; action?: string | null }
}

export interface RegionSetSummary {
  id: string
  created_at: string
  count: number
  migrated: boolean
  z_unit: string
  algorithm: string
  staleness: { stale: boolean; reasons: string[] }
}

export interface RegionPreview {
  possible: boolean
  refusals: string[]
  notes: string[]
  algorithm: string
  threshold_method: string
  estimated_region_count?: number
  rejected?: Record<string, number>
  merges?: number
  preview_seconds?: number
}

export interface RegionSliceLabels {
  orientation: 'xy' | 'xz' | 'yz'
  index: number
  rows: number
  cols: number
  labels_u16_b64: string
  order: string[]
}
