import type { Confidence, ViewKind } from '@/types/subterra'

/**
 * Formatters.
 *
 * Every function here has the same obligation: an absent value must format
 * as an absence, never as a zero. `formatConfidence(null)` returning "0.0%"
 * would be a fabricated measurement, which is the specific failure this
 * module exists to prevent.
 */

/** The single em-dash used everywhere for "no value". */
export const NO_VALUE = '—'

/**
 * Formats a confidence that may legitimately be unknown.
 *
 * `null` means the source stated no confidence. It renders as an em-dash,
 * NOT as 0% -- those mean opposite things (unknown vs. certainly wrong).
 */
export function formatConfidence(value: Confidence): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE
  return `${(value * 100).toFixed(1)}%`
}

/** Human wording for an absent confidence, for use where space allows. */
export const NO_CONFIDENCE_STATED = 'no confidence stated'

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE
  return `${(value * 100).toFixed(digits)}%`
}

/** Formats a count with thousands separators; null stays an em-dash. */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE
  return value.toLocaleString('en-GB')
}

/**
 * Formats a metric to a fixed precision without rounding away meaning.
 *
 * Benchmark figures pass through here unchanged in value -- this only
 * controls displayed digits. It never rescales, clamps or re-derives.
 */
export function formatMetric(
  value: number | null | undefined,
  digits = 3,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE
  return value.toFixed(digits)
}

export function formatMetres(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE
  return `${value.toFixed(digits)} m`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return NO_VALUE
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return NO_VALUE
  return d.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Display names for the five views the backend resolves. */
export const viewMeta: Record<ViewKind, { label: string; requires: string }> = {
  map: { label: 'Map', requires: 'a geographic position' },
  radargram: { label: 'Radargram', requires: 'a frame and a trace index' },
  depth_slice: {
    label: 'Depth slice',
    requires:
      'a depth axis (a caller-supplied velocity); across frames, also a shared vertical reference',
  },
  scene_3d: {
    label: '3D scene',
    requires: 'an absolute elevation (X, Y and Z in one frame)',
  },
  metadata: { label: 'Metadata', requires: 'identifiers only' },
}
