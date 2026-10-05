'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  type DisplayWindow, type Outline, type VolumeCursor, cursorToPane, decodeF32, decodeU8,
  displayValue, paneExtent, paneToCursor, projectGroundTruth, sliceCount, sliceIndex, stepSlice,
  SUPPORT_VALUE,
} from '@/lib/volume'
import type { GroundTruthOverlay, Orientation, VolumeProduct, VolumeSlice } from '@/types/volume'

const TITLES: Record<Orientation, string> = {
  xy: 'XY — horizontal slice (C-scan)',
  xz: 'XZ — longitudinal section',
  yz: 'YZ — transverse section',
}

/**
 * One orthogonal slice of the volume, drawn to a canvas.
 *
 * The pane owns NO cursor. It draws `cursor` and reports every interaction
 * through `onCursor`, so XY, XZ, YZ and 3D can never disagree about the
 * selected voxel.
 *
 * Interaction: click / drag = move the crosshair; mouse wheel = step the
 * slice (drag through depth in XY); ctrl/cmd + wheel = zoom; shift-drag or
 * middle-drag = pan.
 *
 * Layers are drawn in this order and never mixed: (1) the scientific values
 * through the display window, (2) the support overlay, (3) the ground-truth
 * overlay, in its own colour, dashed and labelled -- it is not part of the
 * reconstruction, and it is not drawn into the value image.
 */
export function SlicePane({
  orientation, volume, slice, cursor, onCursor, display, showSupport, showInterpolated,
  groundTruth, showGroundTruth, view, onView,
}: {
  orientation: Orientation
  volume: VolumeProduct
  slice: VolumeSlice | undefined
  cursor: VolumeCursor
  onCursor: (c: VolumeCursor) => void
  display: DisplayWindow
  showSupport: boolean
  showInterpolated: boolean
  groundTruth?: GroundTruthOverlay
  showGroundTruth: boolean
  view: { zoom: number; panX: number; panY: number }
  onView: (v: { zoom: number; panX: number; panY: number }) => void
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 320, h: 240 })
  const drag = useRef<{ mode: 'cursor' | 'pan'; x: number; y: number; panX: number; panY: number } | null>(null)

  useEffect(() => {
    const el = wrapRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect
      if (!r) return
      setSize({ w: Math.max(80, Math.floor(r.width)), h: Math.max(80, Math.floor(r.height)) })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // the value image, rebuilt only when the slice or display settings change
  const image = useMemo(() => {
    if (!slice || typeof document === 'undefined') return null
    const vals = decodeF32(slice.values_f32_b64)
    const sup = decodeU8(slice.support_u8_b64)
    const off = document.createElement('canvas')
    off.width = slice.cols
    off.height = slice.rows
    const ctx = off.getContext('2d')
    if (!ctx) return null
    const img = ctx.createImageData(slice.cols, slice.rows)
    for (let p = 0; p < vals.length; p++) {
      const s = sup[p]
      const hidden = s === SUPPORT_VALUE.UNSUPPORTED || (!showInterpolated && s === SUPPORT_VALUE.INTERPOLATED)
      const g = hidden ? null : displayValue(vals[p] ?? NaN, display)
      const o = p * 4
      if (g === null) {
        // empty: a checker of two dark greys, so "no data" never reads as "zero"
        const r = Math.floor(p / slice.cols), c = p % slice.cols
        const chk = ((r >> 2) + (c >> 2)) % 2 ? 46 : 30
        img.data[o] = chk; img.data[o + 1] = chk; img.data[o + 2] = chk + 6; img.data[o + 3] = 255
        continue
      }
      let R = 255 * (1 - g), G = 255 * (1 - g), B = 255 * (1 - g)
      if (showSupport && s === SUPPORT_VALUE.INTERPOLATED) { R = R * 0.6 + 255 * 0.4; G = G * 0.6 + 170 * 0.4; B = B * 0.6 }
      img.data[o] = R; img.data[o + 1] = G; img.data[o + 2] = B; img.data[o + 3] = 255
    }
    ctx.putImageData(img, 0, 0)
    return off
  }, [slice, display, showSupport, showInterpolated])

  const ext = paneExtent(orientation, volume)
  // fit the physical extent into the pane, then apply zoom / pan
  const fit = Math.min(size.w / ext.w, size.h / ext.h) * 0.94
  const scale = fit * view.zoom
  const drawW = ext.w * scale, drawH = ext.h * scale
  const ox = (size.w - drawW) / 2 + view.panX
  const oy = (size.h - drawH) / 2 + view.panY

  const toPx = (u: number, v: number) => ({
    x: ox + ((u - ext.wAxis.origin) / ext.w) * drawW + 0.5 * (drawW / (ext.w / ext.wAxis.step)),
    y: oy + ((v - ext.hAxis.origin) / ext.h) * drawH + 0.5 * (drawH / (ext.h / ext.hAxis.step)),
  })

  useEffect(() => {
    const cv = canvasRef.current
    const ctx = cv?.getContext('2d')
    if (!cv || !ctx) return
    const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1
    cv.width = size.w * dpr
    cv.height = size.h * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.fillStyle = '#111214'
    ctx.fillRect(0, 0, size.w, size.h)
    if (image) {
      ctx.imageSmoothingEnabled = false
      ctx.drawImage(image, ox, oy, drawW, drawH)
    }
    // ground truth: separate layer, magenta, dashed
    if (showGroundTruth && groundTruth?.available) {
      const outlines = projectGroundTruth(orientation, groundTruth.objects, cursor)
      ctx.save()
      ctx.beginPath()
      ctx.rect(ox, oy, drawW, drawH)
      ctx.clip()
      ctx.strokeStyle = '#e040fb'
      ctx.lineWidth = 1.5
      ctx.setLineDash([5, 4])
      for (const o of outlines) drawOutline(ctx, o, toPx, scale)
      ctx.restore()
    }
    // crosshair
    const { col, row } = cursorToPane(orientation, cursor)
    const cx = ox + (col + 0.5) * (drawW / (ext.w / ext.wAxis.step))
    const cy = oy + (row + 0.5) * (drawH / (ext.h / ext.hAxis.step))
    ctx.strokeStyle = '#22d3ee'
    ctx.lineWidth = 1
    ctx.setLineDash([])
    ctx.beginPath()
    ctx.moveTo(ox, cy); ctx.lineTo(ox + drawW, cy)
    ctx.moveTo(cx, oy); ctx.lineTo(cx, oy + drawH)
    ctx.stroke()
    ctx.beginPath()
    ctx.arc(cx, cy, 4, 0, Math.PI * 2)
    ctx.stroke()
  })

  const eventToCell = (e: React.MouseEvent) => {
    const r = canvasRef.current!.getBoundingClientRect()
    const px = e.clientX - r.left, py = e.clientY - r.top
    const col = Math.floor(((px - ox) / drawW) * (ext.w / ext.wAxis.step))
    const row = Math.floor(((py - oy) / drawH) * (ext.h / ext.hAxis.step))
    return { col, row }
  }

  const n = sliceCount(orientation, volume)
  const idx = sliceIndex(orientation, cursor)
  return (
    <div className="flex min-h-0 flex-col" data-testid={`pane-${orientation}`}>
      <div className="flex items-center justify-between gap-2 px-2 py-1 text-[11px] text-muted-foreground">
        <span className="font-medium text-foreground">{TITLES[orientation]}</span>
        <span data-testid={`pane-${orientation}-index`}>
          slice {idx + 1}/{n}{slice && slice.thickness_voxels > 1 ? ` · slab ${slice.thickness_voxels}` : ''}
        </span>
      </div>
      <div ref={wrapRef} className="relative min-h-0 flex-1">
        <canvas
          ref={canvasRef}
          aria-label={`${TITLES[orientation]} slice`}
          className="absolute inset-0 h-full w-full cursor-crosshair touch-none"
          onMouseDown={(e) => {
            e.preventDefault()
            if (e.shiftKey || e.button === 1) {
              drag.current = { mode: 'pan', x: e.clientX, y: e.clientY, panX: view.panX, panY: view.panY }
              return
            }
            drag.current = { mode: 'cursor', x: 0, y: 0, panX: 0, panY: 0 }
            const { col, row } = eventToCell(e)
            onCursor(paneToCursor(orientation, volume, cursor, col, row))
          }}
          onMouseMove={(e) => {
            const d = drag.current
            if (!d) return
            if (d.mode === 'pan') onView({ ...view, panX: d.panX + e.clientX - d.x, panY: d.panY + e.clientY - d.y })
            else {
              const { col, row } = eventToCell(e)
              onCursor(paneToCursor(orientation, volume, cursor, col, row))
            }
          }}
          onMouseUp={() => { drag.current = null }}
          onMouseLeave={() => { drag.current = null }}
          onWheel={(e) => {
            if (e.ctrlKey || e.metaKey) {
              onView({ ...view, zoom: Math.min(20, Math.max(0.5, view.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15))) })
            } else {
              onCursor(stepSlice(orientation, volume, cursor, e.deltaY < 0 ? -1 : 1))
            }
          }}
        />
        {showGroundTruth && groundTruth?.available && (
          <span className="pointer-events-none absolute left-1 top-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-semibold text-[#e040fb]">
            {groundTruth.label}
          </span>
        )}
      </div>
      <input
        type="range"
        min={0}
        max={n - 1}
        value={idx}
        aria-label={`${orientation.toUpperCase()} slice position`}
        onChange={(e) => onCursor(stepSlice(orientation, volume, cursor, Number(e.target.value) - idx))}
        className="mx-2 my-1"
      />
    </div>
  )
}

function drawOutline(ctx: CanvasRenderingContext2D, o: Outline,
                     toPx: (u: number, v: number) => { x: number; y: number }, scale: number) {
  ctx.beginPath()
  if (o.kind === 'circle') {
    const c = toPx(o.cx, o.cy)
    ctx.arc(c.x, c.y, o.r * scale, 0, Math.PI * 2)
  } else if (o.kind === 'rect') {
    const a = toPx(o.x0, o.y0), b = toPx(o.x1, o.y1)
    ctx.rect(a.x, a.y, b.x - a.x, b.y - a.y)
  } else if (o.kind === 'hline') {
    const a = toPx(o.x0, o.y), b = toPx(o.x1, o.y)
    ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y)
  } else if (o.kind === 'vband') {
    const a = toPx(o.x0, 0), b = toPx(o.x1, 0)
    ctx.moveTo(a.x, 0); ctx.lineTo(a.x, 10000)
    ctx.moveTo(b.x, 0); ctx.lineTo(b.x, 10000)
  } else {
    const c = toPx(o.x, o.y)
    ctx.moveTo(c.x - 5, c.y - 5); ctx.lineTo(c.x + 5, c.y + 5)
    ctx.moveTo(c.x + 5, c.y - 5); ctx.lineTo(c.x - 5, c.y + 5)
  }
  ctx.stroke()
}
