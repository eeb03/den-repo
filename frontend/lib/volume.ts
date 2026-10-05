/**
 * Volume viewer maths: ONE canonical cursor, slice <-> pane mapping, display
 * window/level, and ground-truth projection. Pure functions, unit-tested.
 *
 * THE CURSOR. Every pane (XY, XZ, YZ, 3D) reads and writes the same
 * `VolumeCursor`; no pane keeps a cursor of its own. Indices are the source
 * of truth and the coordinates are derived from the volume's axes, so a
 * cursor can never point between voxels in one pane and at a voxel in another.
 *
 * DISPLAY IS NOT DATA. `displayValue` maps a scientific value through
 * window / level / gain / polarity for drawing only; nothing here writes a
 * value back.
 */
import type {
  GroundTruthObject, Orientation, SupportClassName, VolumeAxis, VolumeProduct,
} from '@/types/volume'

export interface VolumeCursor {
  i: number
  j: number
  k: number
  x_m: number
  y_m: number
  /** depth (m) for a depth volume, two-way time (ns) for a time volume */
  z: number
  zUnit: string
}

type Geometry = Pick<VolumeProduct, 'shape' | 'x_axis' | 'y_axis' | 'z_axis'>

const clampInt = (v: number, n: number) => Math.min(n - 1, Math.max(0, Math.round(v)))
const at = (ax: VolumeAxis, i: number) => ax.origin + i * ax.step

export function cursorFromIndex(vol: Geometry, i: number, j: number, k: number): VolumeCursor {
  const [nx, ny, nz] = vol.shape
  const ii = clampInt(i, nx), jj = clampInt(j, ny), kk = clampInt(k, nz)
  return { i: ii, j: jj, k: kk, x_m: at(vol.x_axis, ii), y_m: at(vol.y_axis, jj), z: at(vol.z_axis, kk), zUnit: vol.z_axis.unit }
}

export function cursorFromCoord(vol: Geometry, x_m: number, y_m: number, z: number): VolumeCursor {
  return cursorFromIndex(
    vol,
    (x_m - vol.x_axis.origin) / vol.x_axis.step,
    (y_m - vol.y_axis.origin) / vol.y_axis.step,
    (z - vol.z_axis.origin) / vol.z_axis.step,
  )
}

export function centreCursor(vol: Geometry): VolumeCursor {
  return cursorFromIndex(vol, vol.shape[0] / 2, vol.shape[1] / 2, vol.shape[2] / 4)
}

/** Which slice index a pane shows for a cursor. */
export function sliceIndex(o: Orientation, c: VolumeCursor): number {
  return o === 'xy' ? c.k : o === 'xz' ? c.j : c.i
}

/** Number of slices along a pane's normal. */
export function sliceCount(o: Orientation, vol: Geometry): number {
  return o === 'xy' ? vol.shape[2] : o === 'xz' ? vol.shape[1] : vol.shape[0]
}

/** (col, row) of the cursor in a pane's slice image. Rows/cols match the API. */
export function cursorToPane(o: Orientation, c: VolumeCursor): { col: number; row: number } {
  if (o === 'xy') return { col: c.i, row: c.j }
  if (o === 'xz') return { col: c.i, row: c.k }
  return { col: c.j, row: c.k }
}

/** A click at (col, row) in a pane moves the two in-plane indices; the third is the slice. */
export function paneToCursor(o: Orientation, vol: Geometry, c: VolumeCursor, col: number, row: number): VolumeCursor {
  if (o === 'xy') return cursorFromIndex(vol, col, row, c.k)
  if (o === 'xz') return cursorFromIndex(vol, col, c.j, row)
  return cursorFromIndex(vol, c.i, col, row)
}

/** Move the slice a pane shows (drag through depth, step through lines). */
export function stepSlice(o: Orientation, vol: Geometry, c: VolumeCursor, delta: number): VolumeCursor {
  if (o === 'xy') return cursorFromIndex(vol, c.i, c.j, c.k + delta)
  if (o === 'xz') return cursorFromIndex(vol, c.i, c.j + delta, c.k)
  return cursorFromIndex(vol, c.i + delta, c.j, c.k)
}

/** Physical extent (width, height) of a pane, in its own axis units, for aspect ratio. */
export function paneExtent(o: Orientation, vol: Geometry): { w: number; h: number; wAxis: VolumeAxis; hAxis: VolumeAxis } {
  const [nx, ny, nz] = vol.shape
  if (o === 'xy') return { w: nx * vol.x_axis.step, h: ny * vol.y_axis.step, wAxis: vol.x_axis, hAxis: vol.y_axis }
  if (o === 'xz') return { w: nx * vol.x_axis.step, h: nz * vol.z_axis.step, wAxis: vol.x_axis, hAxis: vol.z_axis }
  return { w: ny * vol.y_axis.step, h: nz * vol.z_axis.step, wAxis: vol.y_axis, hAxis: vol.z_axis }
}

export function decodeF32(b64: string): Float32Array {
  const bin = atob(b64)
  const buf = new ArrayBuffer(bin.length)
  const u8 = new Uint8Array(buf)
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i)
  return new Float32Array(buf)
}

export function decodeU8(b64: string): Uint8Array {
  const bin = atob(b64)
  const u8 = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i)
  return u8
}

export type Polarity = 'signed' | 'inverted' | 'absolute'

export interface DisplayWindow {
  window: number
  level: number
  gain: number
  polarity: Polarity
}

/** A sensible starting window from the field's robust statistics. */
export function defaultWindow(stats: Record<string, number>, signed: boolean): DisplayWindow {
  const p99 = stats.abs_p99 || stats.abs_max || 1
  return signed
    ? { window: 2 * p99, level: 0, gain: 1, polarity: 'signed' }
    : { window: p99, level: p99 / 2, gain: 1, polarity: 'absolute' }
}

/** Scientific value -> 0..1 grey. NaN (empty voxel) -> null: never drawn as a value. */
export function displayValue(v: number, w: DisplayWindow): number | null {
  if (!Number.isFinite(v)) return null
  let x = v * w.gain
  if (w.polarity === 'inverted') x = -x
  else if (w.polarity === 'absolute') x = Math.abs(x)
  const lo = w.level - w.window / 2
  const t = (x - lo) / (w.window || 1)
  return Math.min(1, Math.max(0, t))
}

export const SUPPORT_VALUE: Record<SupportClassName, number> = {
  UNSUPPORTED: 0, INTERPOLATED: 1, RECONSTRUCTED: 2, MEASURED: 3,
}

/** A ground-truth object's outline in one pane, in the pane's own (physical) coordinates. */
export type Outline =
  | { kind: 'circle'; id: string; cx: number; cy: number; r: number }
  | { kind: 'rect'; id: string; x0: number; y0: number; x1: number; y1: number }
  | { kind: 'hline'; id: string; x0: number; x1: number; y: number }
  | { kind: 'vband'; id: string; x0: number; x1: number }
  | { kind: 'mark'; id: string; x: number; y: number }

/**
 * Where each drawn object intersects a pane's plane. Coordinates: xy -> (x, y);
 * xz -> (x, z); yz -> (y, z). Objects that do not cut the plane are omitted.
 */
export function projectGroundTruth(o: Orientation, objs: GroundTruthObject[], c: VolumeCursor): Outline[] {
  const out: Outline[] = []
  for (const g of objs) {
    if (g.kind === 'duct') {
      if (o === 'xz') out.push({ kind: 'circle', id: g.id, cx: g.x_m, cy: g.z_centre_m, r: g.radius_m })
      else if (o === 'yz') {
        const dx = Math.abs(c.x_m - g.x_m)
        if (dx <= g.radius_m) {
          const h = Math.sqrt(g.radius_m ** 2 - dx ** 2)
          out.push({ kind: 'rect', id: g.id, x0: g.y_range_m[0], x1: g.y_range_m[1], y0: g.z_centre_m - h, y1: g.z_centre_m + h })
        }
      } else {
        const dz = Math.abs(c.z - g.z_centre_m)
        if (c.zUnit === 'm' && dz <= g.radius_m) {
          const h = Math.sqrt(g.radius_m ** 2 - dz ** 2)
          out.push({ kind: 'vband', id: g.id, x0: g.x_m - h, x1: g.x_m + h })
        }
      }
    } else if (g.kind === 'box') {
      const inX = c.x_m >= g.x_range_m[0] && c.x_m <= g.x_range_m[1]
      const inY = c.y_m >= g.y_range_m[0] && c.y_m <= g.y_range_m[1]
      const inZ = c.z >= g.z_range_m[0] && c.z <= g.z_range_m[1]
      if (o === 'xz' && inY) out.push({ kind: 'rect', id: g.id, x0: g.x_range_m[0], x1: g.x_range_m[1], y0: g.z_range_m[0], y1: g.z_range_m[1] })
      if (o === 'yz' && inX) out.push({ kind: 'rect', id: g.id, x0: g.y_range_m[0], x1: g.y_range_m[1], y0: g.z_range_m[0], y1: g.z_range_m[1] })
      if (o === 'xy' && inZ) out.push({ kind: 'rect', id: g.id, x0: g.x_range_m[0], x1: g.x_range_m[1], y0: g.y_range_m[0], y1: g.y_range_m[1] })
    } else if (g.kind === 'plane') {
      const inX = c.x_m >= g.x_range_m[0] && c.x_m <= g.x_range_m[1]
      if (o === 'xz') out.push({ kind: 'hline', id: g.id, x0: g.x_range_m[0], x1: g.x_range_m[1], y: g.z_m })
      if (o === 'yz' && inX) out.push({ kind: 'hline', id: g.id, x0: g.y_range_m[0], x1: g.y_range_m[1], y: g.z_m })
    } else if (g.kind === 'surface_marker') {
      if (o === 'xy') out.push({ kind: 'mark', id: g.id, x: g.x_m, y: g.y_m })
    }
  }
  return out
}

export function formatZ(z: number, unit: string): string {
  return unit === 'm' ? `${(z * 1000).toFixed(1)} mm depth` : `${z.toFixed(3)} ns two-way time`
}
