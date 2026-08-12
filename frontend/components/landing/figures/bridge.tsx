import { cn } from '@/lib/utils'
import { arrivalAt, path, terrain } from './geometry'

/**
 * A seam between two stages, drawn so a motif survives the boundary.
 *
 * THE PROBLEM THIS SOLVES. Measured, the descent read as nine sections with
 * black gaps: only surface→break carried anything across a boundary, and
 * candidate→frame was a hard cut with ~200px of nothing. A page whose whole
 * claim is "one continuous descent" cannot afford that.
 *
 * Each bridge interpolates between the motif that just ended and the one about
 * to begin -- contours become traces, traces become axes, axes become frames,
 * frames become chips, chips become gate bars, bars become panes, panes become
 * terrain again. The interpolation is a closed-form blend, so a bridge is
 * deterministic like every other figure here and carries no data.
 *
 * These are deliberately quiet. They are connective tissue, not events: thin,
 * low-contrast, and drifting at a rate between the two stages so the seam
 * reads as continuous rather than as a third thing competing for attention.
 */

const W = 1440
const H = 132

/** t=0 renders the leaving motif, t=1 the arriving one. */
type Motif = 'contour' | 'trace' | 'axes' | 'frames' | 'chips' | 'bars' | 'panes'

function contourPaths(): React.ReactNode {
  return [0.28, 0.5, 0.72].map((f, i) => (
    <path
      key={f}
      d={terrain(W, H * f, 7, 0.6 + i * 0.9, 70)}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.1"
      className="text-muted-foreground"
      opacity={0.18 + i * 0.1}
    />
  ))
}

function tracePaths(): React.ReactNode {
  return Array.from({ length: 34 }, (_, i) => {
    const x = 40 + (i * (W - 80)) / 33
    const a = arrivalAt(x, W / 2, H * 0.34, 260, 60)
    const d = path(
      Array.from({ length: 22 }, (_, j) => {
        const y = 12 + (j / 21) * (H - 24)
        const env = Math.exp(-(((y - a) / 17) ** 2))
        return [x + Math.sin((y - 12) / 6) * 6.5 * env, y] as const
      }),
    )
    return (
      <path
        key={x}
        d={d}
        fill="none"
        stroke="currentColor"
        strokeWidth="0.9"
        className="text-foreground/35"
      />
    )
  })
}

function axesPaths(): React.ReactNode {
  return Array.from({ length: 7 }, (_, i) => {
    const x = 130 + i * 195
    return (
      <g key={x} stroke="var(--primary)" strokeWidth="1.1" opacity="0.4">
        <line x1={x} y1={H * 0.68} x2={x + 34} y2={H * 0.68} />
        <line x1={x} y1={H * 0.68} x2={x} y2={H * 0.68 - 34} />
      </g>
    )
  })
}

function framePaths(): React.ReactNode {
  return [140, 560, 980].map((x, i) => (
    <rect
      key={x}
      x={x}
      y={26 + i * 8}
      width="320"
      height={H - 60 - i * 10}
      rx="3"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.1"
      strokeDasharray={i === 2 ? '5 5' : undefined}
      className={i === 2 ? 'text-prov-unavailable' : 'text-prov-declared'}
      opacity="0.4"
    />
  ))
}

function chipPaths(): React.ReactNode {
  return Array.from({ length: 7 }, (_, i) => (
    <rect
      key={i}
      x={120 + i * 176}
      y={H / 2 - 11}
      width="132"
      height="22"
      rx="4"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.1"
      className="text-muted-foreground"
      opacity={i === 4 ? 0.75 : 0.22}
    />
  ))
}

function barPaths(): React.ReactNode {
  return [220, 780].map((x) => (
    <g key={x}>
      <rect
        x={x}
        y={H / 2 - 26}
        width="440"
        height="52"
        rx="4"
        fill="none"
        stroke="var(--destructive)"
        strokeWidth="1.1"
        opacity="0.35"
      />
      {Array.from({ length: 10 }, (_, i) => (
        <line
          key={i}
          x1={x + 10 + i * 44}
          y1={H / 2 + 22}
          x2={x + 34 + i * 44}
          y2={H / 2 - 22}
          stroke="currentColor"
          strokeWidth="1"
          className="text-foreground/12"
        />
      ))}
    </g>
  ))
}

function panePaths(): React.ReactNode {
  return [150, 570, 990].map((x) => (
    <g key={x}>
      <rect
        x={x}
        y="24"
        width="300"
        height={H - 48}
        rx="3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
        className="text-border"
      />
      {[0, 1, 2].map((r) => (
        <line
          key={r}
          x1={x + 16}
          x2={x + 284}
          y1={48 + r * 22}
          y2={48 + r * 22}
          stroke="currentColor"
          strokeWidth="1"
          className="text-foreground/12"
        />
      ))}
    </g>
  ))
}

const RENDER: Record<Motif, () => React.ReactNode> = {
  contour: contourPaths,
  trace: tracePaths,
  axes: axesPaths,
  frames: framePaths,
  chips: chipPaths,
  bars: barPaths,
  panes: panePaths,
}

/**
 * Renders the leaving motif fading out over the arriving one fading in, both
 * drifting. The overlap is the point: for a moment the visitor sees the
 * previous stage's object still present while the next concept appears.
 */
export function Bridge({
  from,
  to,
  className,
  label,
}: {
  from: Motif
  to: Motif
  className?: string
  /** Optional seam caption, e.g. what the motif becomes. */
  label?: string
}) {
  return (
    <div
      aria-hidden
      className={cn('descent-bleed pointer-events-none relative select-none', className)}
    >
      <svg viewBox={`0 0 ${W} ${H}`} className="h-[132px] w-full" preserveAspectRatio="none">
        <defs>
          <linearGradient id={`br-out-${from}-${to}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="white" stopOpacity="0.9" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </linearGradient>
          <linearGradient id={`br-in-${from}-${to}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="white" stopOpacity="0" />
            <stop offset="100%" stopColor="white" stopOpacity="0.9" />
          </linearGradient>
          <mask id={`br-mo-${from}-${to}`}>
            <rect width={W} height={H} fill={`url(#br-out-${from}-${to})`} />
          </mask>
          <mask id={`br-mi-${from}-${to}`}>
            <rect width={W} height={H} fill={`url(#br-in-${from}-${to})`} />
          </mask>
        </defs>

        <g className="descent-bridge" mask={`url(#br-mo-${from}-${to})`}>
          {RENDER[from]()}
        </g>
        <g className="descent-bridge" mask={`url(#br-mi-${from}-${to})`}>
          {RENDER[to]()}
        </g>
      </svg>

      {label && (
        <span className="absolute inset-x-0 top-1/2 -translate-y-1/2 text-center font-mono text-[10px] uppercase tracking-[0.28em] text-muted-foreground/60">
          {label}
        </span>
      )}
    </div>
  )
}
