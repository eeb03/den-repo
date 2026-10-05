/**
 * Region layer helpers. A region label image is uint16 per slice pixel:
 * 0 = no region, n = the set's n-th region (`order[n - 1]`).
 */
import type { RegionSliceLabels } from '@/types/region'

export interface DecodedLabels { rows: number; cols: number; data: Uint16Array; order: string[] }

export function decodeLabels(s: RegionSliceLabels): DecodedLabels {
  const bin = atob(s.labels_u16_b64)
  const buf = new ArrayBuffer(bin.length)
  const u8 = new Uint8Array(buf)
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i)
  return { rows: s.rows, cols: s.cols, data: new Uint16Array(buf), order: s.order }
}

/** The region id at a slice pixel, or null. */
export function regionAt(l: DecodedLabels, col: number, row: number): string | null {
  if (row < 0 || col < 0 || row >= l.rows || col >= l.cols) return null
  const n = l.data[row * l.cols + col] ?? 0
  return n ? (l.order[n - 1] ?? null) : null
}

/** 1 where a pixel is on a region boundary (4-neighbour change), else 0. */
export function outline(l: DecodedLabels): Uint8Array {
  const out = new Uint8Array(l.rows * l.cols)
  for (let r = 0; r < l.rows; r++) {
    for (let c = 0; c < l.cols; c++) {
      const p = r * l.cols + c
      const v = l.data[p] ?? 0
      if (!v) continue
      const up = r > 0 ? l.data[p - l.cols] : 0
      const dn = r < l.rows - 1 ? l.data[p + l.cols] : 0
      const lf = c > 0 ? l.data[p - 1] : 0
      const rt = c < l.cols - 1 ? l.data[p + 1] : 0
      if (up !== v || dn !== v || lf !== v || rt !== v) out[p] = 1
    }
  }
  return out
}

export function formatLength(v: number, unit: string): string {
  return unit === 'm' ? `${(v * 1000).toFixed(0)} mm` : `${v.toFixed(2)} ${unit}`
}
