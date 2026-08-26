/**
 * Canvas-based review annotation (Section 6/18's follow-up to Human-in-the-
 * Loop Anomaly Verification V1).
 *
 * THE PROPERTY UNDER TEST: drawing is strictly additive. The default
 * 'select' mode is byte-for-byte the original behaviour (no draw surface
 * exists at all), and every drawn value is a REAL (trace, sample) pair --
 * converted through `grid.trace_indices`, never a raw pixel offset a
 * caller would have to re-derive.
 */
import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RadargramCanvas } from './radargram-canvas'
import type { TraceGrid } from '@/types/subterra'

function grid(): TraceGrid {
  return {
    dataset_id: 'd1',
    source_file: 'Path8.sgy',
    grid: [
      [1, 2, 3, 4],
      [5, 6, 7, 8],
    ],
    trace_indices: [100, 101, 102, 103],
    candidate_footprints: [],
  }
}

function stubCanvas() {
  const proto = globalThis.HTMLCanvasElement?.prototype
  if (!proto) return
  proto.getContext = vi.fn(() => ({
    imageSmoothingEnabled: true,
    createImageData: (w: number, h: number) => ({ width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }),
    putImageData: vi.fn(),
    clearRect: vi.fn(),
    drawImage: vi.fn(),
  })) as unknown as HTMLCanvasElement['getContext']
}

/** width=400, height=200 in the tests below -> scaleX=100/col, scaleY=100/row (4 columns, 2 rows). */
function stubBoundingRect() {
  const proto = globalThis.HTMLDivElement?.prototype
  if (!proto) return
  proto.getBoundingClientRect = vi.fn(() => ({
    left: 0, top: 0, right: 400, bottom: 200, width: 400, height: 200, x: 0, y: 0, toJSON: () => {},
  })) as unknown as typeof proto.getBoundingClientRect
}

beforeEach(() => {
  stubCanvas()
  stubBoundingRect()
})

afterEach(() => cleanup())

describe('the default select mode is unaffected', () => {
  it('renders no draw surface at all', () => {
    const { container } = render(
      <RadargramCanvas
        grid={grid()} footprints={[]} selectedId={null} onSelect={() => {}}
        showUnreliable={false} width={400} height={200}
      />,
    )
    expect(container.querySelector('[data-radargram-draw-surface]')).toBeNull()
  })

  it('mode="select" explicitly is identical to omitting mode', () => {
    const { container } = render(
      <RadargramCanvas
        grid={grid()} footprints={[]} selectedId={null} onSelect={() => {}}
        showUnreliable={false} width={400} height={200} mode="select"
      />,
    )
    expect(container.querySelector('[data-radargram-draw-surface]')).toBeNull()
  })
})

describe('draw-rectangle', () => {
  it('reports the real (trace, sample) extent on mouse-up, converted through trace_indices', () => {
    const onRectangleDrawn = vi.fn()
    const { container } = render(
      <RadargramCanvas
        grid={grid()} footprints={[]} selectedId={null} onSelect={() => {}}
        showUnreliable={false} width={400} height={200}
        mode="draw-rectangle" onRectangleDrawn={onRectangleDrawn}
      />,
    )
    const surface = container.querySelector('[data-radargram-draw-surface]')!
    // column 1 (x=150 -> col 1 of 4, scaleX=100), row 0 (y=50 -> row 0 of 2, scaleY=100)
    fireEvent.mouseDown(surface, { clientX: 150, clientY: 50 })
    // drag to column 2 (x=250), row 1 (y=150)
    fireEvent.mouseMove(surface, { clientX: 250, clientY: 150 })
    fireEvent.mouseUp(surface)

    expect(onRectangleDrawn).toHaveBeenCalledWith({
      traceStart: 101, traceEnd: 102, // trace_indices[1], trace_indices[2]
      sampleStart: 0, sampleEnd: 1,
    })
  })

  it('does not fire while merely hovering (no mouse-down first)', () => {
    const onRectangleDrawn = vi.fn()
    const { container } = render(
      <RadargramCanvas
        grid={grid()} footprints={[]} selectedId={null} onSelect={() => {}}
        showUnreliable={false} width={400} height={200}
        mode="draw-rectangle" onRectangleDrawn={onRectangleDrawn}
      />,
    )
    const surface = container.querySelector('[data-radargram-draw-surface]')!
    fireEvent.mouseMove(surface, { clientX: 250, clientY: 150 })
    fireEvent.mouseUp(surface)
    expect(onRectangleDrawn).not.toHaveBeenCalled()
  })

  it('renders a live preview rectangle while dragging', () => {
    const { container } = render(
      <RadargramCanvas
        grid={grid()} footprints={[]} selectedId={null} onSelect={() => {}}
        showUnreliable={false} width={400} height={200}
        mode="draw-rectangle"
      />,
    )
    const surface = container.querySelector('[data-radargram-draw-surface]')!
    fireEvent.mouseDown(surface, { clientX: 50, clientY: 50 })
    fireEvent.mouseMove(surface, { clientX: 250, clientY: 150 })
    expect(container.querySelector('[data-drawn-rectangle]')).toBeTruthy()
  })

  it('shows a savedRectangle even with no drag in progress', () => {
    const { container } = render(
      <RadargramCanvas
        grid={grid()} footprints={[]} selectedId={null} onSelect={() => {}}
        showUnreliable={false} width={400} height={200}
        savedRectangle={{ traceStart: 101, traceEnd: 102, sampleStart: 0, sampleEnd: 1 }}
      />,
    )
    expect(container.querySelector('[data-drawn-rectangle]')).toBeTruthy()
  })
})

describe('draw-ridge', () => {
  it('adds one real point per click', () => {
    const onRidgePointAdded = vi.fn()
    const { container } = render(
      <RadargramCanvas
        grid={grid()} footprints={[]} selectedId={null} onSelect={() => {}}
        showUnreliable={false} width={400} height={200}
        mode="draw-ridge" onRidgePointAdded={onRidgePointAdded}
      />,
    )
    const surface = container.querySelector('[data-radargram-draw-surface]')!
    fireEvent.click(surface, { clientX: 50, clientY: 50 })   // col 0, row 0
    fireEvent.click(surface, { clientX: 150, clientY: 150 }) // col 1, row 1

    expect(onRidgePointAdded).toHaveBeenNthCalledWith(1, { trace: 100, sample: 0 })
    expect(onRidgePointAdded).toHaveBeenNthCalledWith(2, { trace: 101, sample: 1 })
  })

  it('renders the accumulated points as a visible path', () => {
    const { container } = render(
      <RadargramCanvas
        grid={grid()} footprints={[]} selectedId={null} onSelect={() => {}}
        showUnreliable={false} width={400} height={200}
        mode="draw-ridge" ridgePoints={[{ trace: 100, sample: 0 }, { trace: 101, sample: 1 }]}
      />,
    )
    expect(container.querySelectorAll('[data-ridge-point]').length).toBe(2)
    expect(container.querySelector('[data-drawn-ridge] polyline')).toBeTruthy()
  })
})

describe('candidate markers still work in select mode alongside drawing state', () => {
  it('selecting a candidate is unaffected when a saved rectangle also exists', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <RadargramCanvas
        grid={grid()}
        footprints={[{ candidate_id: 'c1', placeable: true, reason: '', first_column: 0, last_column: 0, first_row: 0, last_row: 0, peak_column: 0, peak_row: 0 }]}
        selectedId={null} onSelect={onSelect}
        showUnreliable={false} width={400} height={200}
        savedRectangle={{ traceStart: 101, traceEnd: 102, sampleStart: 0, sampleEnd: 1 }}
      />,
    )
    fireEvent.click(container.querySelector('[data-candidate-marker="c1"]')!)
    expect(onSelect).toHaveBeenCalledWith('c1')
  })
})
