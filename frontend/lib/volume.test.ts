/**
 * Volume viewer maths: one canonical cursor, consistent slice indexing,
 * display-only windowing, and ground-truth projection.
 */
import { describe, expect, it } from 'vitest'
import {
  cursorFromCoord, cursorFromIndex, cursorToPane, decodeF32, decodeU8, defaultWindow, displayValue,
  paneExtent, paneToCursor, projectGroundTruth, sliceCount, sliceIndex, stepSlice,
} from './volume'
import type { GroundTruthObject, VolumeAxis } from '@/types/volume'

const ax = (name: string, n: number, step: number, unit = 'm', origin = 0): VolumeAxis =>
  ({ name, n, origin, step, unit, description: '' })
const vol = { shape: [401, 161, 475] as [number, number, number], x_axis: ax('x', 401, 0.005), y_axis: ax('y', 161, 0.005), z_axis: ax('depth', 475, 0.0019) }

describe('the canonical cursor', () => {
  it('derives coordinates from indices, and clamps to the volume', () => {
    const c = cursorFromIndex(vol, 50, 80, 100)
    expect(c).toMatchObject({ i: 50, j: 80, k: 100, zUnit: 'm' })
    expect(c.x_m).toBeCloseTo(0.25)
    expect(c.y_m).toBeCloseTo(0.4)
    expect(c.z).toBeCloseTo(0.19)
    expect(cursorFromIndex(vol, -5, 999, 1e6)).toMatchObject({ i: 0, j: 160, k: 474 })
  })

  it('round-trips through coordinates', () => {
    const c = cursorFromIndex(vol, 123, 45, 67)
    expect(cursorFromCoord(vol, c.x_m, c.y_m, c.z)).toEqual(c)
  })

  it('each pane shows the slice through the cursor, and reports in-plane clicks into the same cursor', () => {
    const c = cursorFromIndex(vol, 10, 20, 30)
    expect(sliceIndex('xy', c)).toBe(30)
    expect(sliceIndex('xz', c)).toBe(20)
    expect(sliceIndex('yz', c)).toBe(10)
    expect(cursorToPane('xy', c)).toEqual({ col: 10, row: 20 })
    expect(cursorToPane('xz', c)).toEqual({ col: 10, row: 30 })
    expect(cursorToPane('yz', c)).toEqual({ col: 20, row: 30 })
    // clicking in XY moves x and y and keeps depth; XZ keeps y; YZ keeps x
    expect(paneToCursor('xy', vol, c, 5, 6)).toMatchObject({ i: 5, j: 6, k: 30 })
    expect(paneToCursor('xz', vol, c, 5, 6)).toMatchObject({ i: 5, j: 20, k: 6 })
    expect(paneToCursor('yz', vol, c, 5, 6)).toMatchObject({ i: 10, j: 5, k: 6 })
  })

  it('a click in one pane moves the slices the other panes show', () => {
    const c0 = cursorFromIndex(vol, 10, 20, 30)
    const c1 = paneToCursor('xy', vol, c0, 200, 100)
    expect(sliceIndex('xz', c1)).toBe(100)
    expect(sliceIndex('yz', c1)).toBe(200)
    expect(sliceIndex('xy', c1)).toBe(30)
  })

  it('stepping a slice moves only that pane’s normal', () => {
    const c = cursorFromIndex(vol, 10, 20, 30)
    expect(stepSlice('xy', vol, c, 5)).toMatchObject({ i: 10, j: 20, k: 35 })
    expect(stepSlice('xz', vol, c, -5)).toMatchObject({ i: 10, j: 15, k: 30 })
    expect(stepSlice('yz', vol, c, 1)).toMatchObject({ i: 11, j: 20, k: 30 })
    expect(sliceCount('xy', vol)).toBe(475)
  })

  it('pane aspect follows physical extent, not voxel counts', () => {
    const e = paneExtent('xz', vol)
    expect(e.w).toBeCloseTo(2.005)
    expect(e.h).toBeCloseTo(0.9025)
  })
})

describe('display is not data', () => {
  it('maps values through window/level/gain/polarity and never draws an empty voxel', () => {
    const w = { window: 2, level: 0, gain: 1, polarity: 'signed' as const }
    expect(displayValue(0, w)).toBe(0.5)
    expect(displayValue(1, w)).toBe(1)
    expect(displayValue(-1, w)).toBe(0)
    expect(displayValue(-1, { ...w, polarity: 'inverted' })).toBe(1)
    expect(displayValue(-1, { ...w, polarity: 'absolute' })).toBe(1)
    expect(displayValue(0.5, { ...w, gain: 2 })).toBe(1)
    expect(displayValue(NaN, w)).toBeNull()
  })

  it('default windows come from robust statistics', () => {
    expect(defaultWindow({ abs_p99: 10 }, true)).toEqual({ window: 20, level: 0, gain: 1, polarity: 'signed' })
    expect(defaultWindow({ abs_p99: 10 }, false)).toMatchObject({ window: 10, level: 5, polarity: 'absolute' })
  })

  it('decodes little-endian float32 (NaN kept) and uint8', () => {
    const f = new Float32Array([1.5, NaN, -2])
    const b64 = btoa(String.fromCharCode(...new Uint8Array(f.buffer)))
    const back = decodeF32(b64)
    expect(back[0]).toBe(1.5)
    expect(Number.isNaN(back[1])).toBe(true)
    expect(back[2]).toBe(-2)
    expect(Array.from(decodeU8(btoa('\u0000\u0003')))).toEqual([0, 3])
  })
})

describe('ground truth projects onto each plane separately', () => {
  const duct: GroundTruthObject = { id: 'd', kind: 'duct', role: 'target', axis: 'y', x_m: 0.25, z_centre_m: 0.2745, z_top_m: 0.241, radius_m: 0.0335, y_range_m: [0, 0.8] }
  const box: GroundTruthObject = { id: 'b', kind: 'box', role: 'target', x_range_m: [0.19, 0.31], y_range_m: [0.338, 0.458], z_range_m: [0.24, 0.30] }

  it('a duct along y is a circle in XZ, a band in YZ only when x cuts it, and a band in XY only at its depth', () => {
    const c = cursorFromCoord(vol, 0.25, 0.4, 0.27)
    expect(projectGroundTruth('xz', [duct], c)[0]).toMatchObject({ kind: 'circle', cx: 0.25, r: 0.0335 })
    expect(projectGroundTruth('yz', [duct], c)[0]).toMatchObject({ kind: 'rect' })
    expect(projectGroundTruth('xy', [duct], c)[0]).toMatchObject({ kind: 'vband' })
    const far = cursorFromCoord(vol, 0.6, 0.4, 0.5)
    expect(projectGroundTruth('yz', [duct], far)).toEqual([])
    expect(projectGroundTruth('xy', [duct], far)).toEqual([])
  })

  it('a box appears only in the planes that intersect it', () => {
    expect(projectGroundTruth('xz', [box], cursorFromCoord(vol, 0.25, 0.4, 0.27))).toHaveLength(1)
    expect(projectGroundTruth('xz', [box], cursorFromCoord(vol, 0.25, 0.6, 0.27))).toHaveLength(0)
    expect(projectGroundTruth('xy', [box], cursorFromCoord(vol, 0.25, 0.4, 0.1))).toHaveLength(0)
  })
})
