import { describe, expect, it } from 'vitest'
import { decodeLabels, formatLength, outline, regionAt } from './regions'

const enc = (a: number[]) => btoa(String.fromCharCode(...new Uint8Array(new Uint16Array(a).buffer)))

describe('region label helpers', () => {
  // 4 x 5 slice: region 1 fills a 3x3 block, region 2 one pixel
  const raw = [
    0, 1, 1, 1, 0,
    0, 1, 1, 1, 0,
    0, 1, 1, 1, 2,
    0, 0, 0, 0, 0,
  ]
  const l = decodeLabels({ orientation: 'xy', index: 0, rows: 4, cols: 5, labels_u16_b64: enc(raw), order: ['rA', 'rB'] })

  it('decodes uint16 labels and maps pixels to region ids', () => {
    expect(regionAt(l, 2, 1)).toBe('rA')
    expect(regionAt(l, 4, 2)).toBe('rB')
    expect(regionAt(l, 0, 0)).toBeNull()
    expect(regionAt(l, 99, 0)).toBeNull()
  })

  it('outlines boundaries and leaves interiors open', () => {
    const o = outline(l)
    expect(o[1 * 5 + 2]).toBe(0)        // the 3x3 block's centre
    expect(o[0 * 5 + 1]).toBe(1)        // its corner
    expect(o[2 * 5 + 4]).toBe(1)        // a one-pixel region is all boundary
    expect(o[3 * 5 + 0]).toBe(0)        // background is never outlined
  })

  it('formats lengths without turning time into metres', () => {
    expect(formatLength(0.067, 'm')).toBe('67 mm')
    expect(formatLength(1.5, 'ns')).toBe('1.50 ns')
  })
})
