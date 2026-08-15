'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import type { CandidateFootprint, TraceGrid } from '@/types/subterra'

/**
 * The measured radargram, drawn cell for cell.
 *
 * THIS COMPONENT'S ONLY JOB IS TO NOT LIE. A radargram is the one surface in
 * Subterra where a fabrication would be invisible: a reader cannot sanity-check
 * a pixel the way they can check a number with units. So every rendering
 * decision here is constrained to preserve what was measured:
 *
 * NO INTERPOLATION. The grid is written into an ImageData of exactly
 * (n_traces x n_depths) pixels and scaled up with `imageSmoothingEnabled =
 * false`. Every screen pixel therefore shows exactly one measured cell.
 * Bilinear smoothing would invent values between traces that no antenna
 * position ever recorded, and it would make the result look BETTER -- which is
 * precisely why it is forbidden rather than merely avoided.
 *
 * MISSING IS NOT ZERO. A `null` cell is a sample the acquisition did not
 * record. It is left fully transparent so the page shows through as an
 * explicit gap. Painting it mid-grey would place it at the centre of the colour
 * scale, which is where a genuine zero sits -- the strongest possible false
 * statement about a measurement that does not exist.
 *
 * UNRELIABLE IS NOT ABSENT. A cell whose ring had too few neighbours carries a
 * z-score that is arithmetically defined and statistically untrustworthy. It is
 * drawn at reduced opacity, and optionally hatched, so it reads as "not to be
 * trusted" rather than as "nothing here". Rendering it identically to a
 * confident value would discard information the preprocessing recorded on
 * purpose.
 *
 * THE COLOUR SCALE IS SYMMETRIC AND UNCLIPPED. The domain is +/- the largest
 * magnitude actually present, printed beside the scale. No percentile clipping,
 * no gamma, no auto-contrast: each of those changes which structures a reviewer
 * notices, and a detector that is at chance does not need help looking
 * convincing.
 */

/** Diverging blue-white-red. Signed data needs a scale with a real zero. */
function colourFor(value: number, domain: number): [number, number, number] {
  const t = Math.max(-1, Math.min(1, domain > 0 ? value / domain : 0))
  if (t >= 0) {
    // white -> red
    return [255, Math.round(255 * (1 - t)), Math.round(255 * (1 - t))]
  }
  // white -> blue
  const m = Math.round(255 * (1 + t))
  return [m, m, 255]
}

export interface RadargramCanvasProps {
  grid: TraceGrid
  footprints: CandidateFootprint[]
  selectedId: string | null
  onSelect: (candidateId: string | null) => void
  showUnreliable: boolean
  /** Rendered pixel size of the plot area. */
  width?: number
  height?: number
}

export function RadargramCanvas({
  grid,
  footprints,
  selectedId,
  onSelect,
  showUnreliable,
  width = 900,
  height = 520,
}: RadargramCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)

  const rows = grid.grid.length
  const columns = rows ? (grid.grid[0]?.length ?? 0) : 0

  /** Symmetric domain from the values actually present. */
  const domain = useMemo(() => {
    let max = 0
    for (const row of grid.grid) {
      for (const value of row) {
        if (value === null || !Number.isFinite(value)) continue
        const magnitude = Math.abs(value)
        if (magnitude > max) max = magnitude
      }
    }
    return max
  }, [grid])

  const missingCount = useMemo(() => {
    let n = 0
    for (const row of grid.grid) for (const v of row) if (v === null) n += 1
    return n
  }, [grid])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !rows || !columns) return
    const context = canvas.getContext('2d')
    if (!context) return

    // One ImageData pixel per measured cell, then a nearest-neighbour blit.
    const image = context.createImageData(columns, rows)
    const reliability = grid.reliability ?? null

    for (let row = 0; row < rows; row += 1) {
      for (let column = 0; column < columns; column += 1) {
        const offset = (row * columns + column) * 4
        const value = grid.grid[row]?.[column] ?? null

        if (value === null || !Number.isFinite(value)) {
          image.data[offset + 3] = 0 // an explicit gap, never a colour
          continue
        }

        const [r, g, b] = colourFor(value as number, domain)
        const unreliable = reliability ? reliability[row]?.[column] === false : false
        image.data[offset] = r
        image.data[offset + 1] = g
        image.data[offset + 2] = b
        // Washed out rather than recoloured: the value is still shown, but it
        // cannot be mistaken for one the statistic actually supports.
        image.data[offset + 3] = unreliable && showUnreliable ? 70 : 255
      }
    }

    const buffer = document.createElement('canvas')
    buffer.width = columns
    buffer.height = rows
    buffer.getContext('2d')?.putImageData(image, 0, 0)

    context.clearRect(0, 0, canvas.width, canvas.height)
    context.imageSmoothingEnabled = false
    context.drawImage(buffer, 0, 0, columns, rows, 0, 0, canvas.width, canvas.height)
  }, [grid, rows, columns, domain, showUnreliable])

  const scaleX = columns ? width / columns : 0
  const scaleY = rows ? height / rows : 0

  const boxFor = (footprint: CandidateFootprint) => {
    const c0 = footprint.first_column ?? 0
    const c1 = footprint.last_column ?? c0
    const r0 = footprint.first_row ?? 0
    const r1 = footprint.last_row ?? r0
    return {
      left: c0 * scaleX,
      top: r0 * scaleY,
      // At least 6px so a single-trace candidate stays clickable. This pads the
      // MARKER, never the reported extent -- the evidence panel prints the true
      // trace and sample range.
      width: Math.max((c1 - c0 + 1) * scaleX, 6),
      height: Math.max((r1 - r0 + 1) * scaleY, 6),
    }
  }

  const placeable = footprints.filter((f) => f.placeable)

  return (
    <div className="relative" style={{ width, height }} data-radargram-plot>
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        className="absolute inset-0 h-full w-full rounded-md border border-border"
        data-radargram-canvas
        data-columns={columns}
        data-rows={rows}
        data-domain={domain.toFixed(4)}
        data-missing-cells={missingCount}
      />

      {/*
        Candidate markers. Stroked rectangles over the exact supporting cells --
        no fill that would hide the data, no rounded "object" shape, no ellipse
        implying an extent the evidence does not state.
      */}
      {placeable.map((footprint) => {
        const box = boxFor(footprint)
        const isSelected = footprint.candidate_id === selectedId
        const isHovered = footprint.candidate_id === hovered
        return (
          <button
            key={footprint.candidate_id}
            type="button"
            data-candidate-marker={footprint.candidate_id}
            data-selected={isSelected ? 'true' : 'false'}
            aria-label={`Candidate region, traces ${footprint.first_column}–${footprint.last_column}`}
            onClick={() => onSelect(isSelected ? null : footprint.candidate_id)}
            onMouseEnter={() => setHovered(footprint.candidate_id)}
            onMouseLeave={() => setHovered(null)}
            className="absolute cursor-pointer bg-transparent p-0"
            style={{
              left: box.left,
              top: box.top,
              width: box.width,
              height: box.height,
              outline: `2px solid ${
                isSelected ? 'var(--color-primary)' : isHovered ? '#f59e0b' : '#0f172a'
              }`,
              outlineOffset: '1px',
            }}
          />
        )
      })}
    </div>
  )
}

/**
 * The colour scale, printed with its real domain.
 *
 * Shown because a diverging scale is only interpretable if the reader knows
 * what the extremes are and where zero sits.
 */
export function RadargramScale({
  domain,
  units,
  label,
}: {
  domain: number
  units: string | null
  label: string
}) {
  return (
    <div className="flex items-center gap-2 text-[11px] text-muted-foreground" data-radargram-scale>
      <span className="font-mono">
        −{domain.toFixed(2)}
        {units ?? ''}
      </span>
      <span
        aria-hidden
        className="h-2 w-28 rounded-sm border border-border"
        style={{
          background:
            'linear-gradient(to right, rgb(0,0,255), rgb(255,255,255), rgb(255,0,0))',
        }}
      />
      <span className="font-mono">
        +{domain.toFixed(2)}
        {units ?? ''}
      </span>
      <span>{label}</span>
    </div>
  )
}
