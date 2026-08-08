import { cn } from '@/lib/utils'
import { hyperbola, trace, traceColumns, traceFilled, type Target } from './geometry'

/**
 * A wiggle-plot B-scan, built column by column.
 *
 * This is the shape a radar section actually takes: one vertical trace per
 * antenna position, deflected where energy arrives. The surface pulse runs
 * across the top of every trace; each buried target adds an arrival whose
 * depth on the trace follows its hyperbola, and whose amplitude falls off as
 * the antenna moves away from it.
 *
 * It is drawn from closed-form functions, not from a survey. The `markers`
 * prop is what stage 3 uses to ring ONE apex as a candidate while leaving an
 * equally plausible neighbour unmarked -- the point being that the platform
 * distinguishes a candidate from a detection, and that an unmarked arrival is
 * not thereby declared absent.
 */

const WIDTH = 960
const TOP = 74
const BOTTOM = 430

export const TARGETS: readonly Target[] = [
  { apexX: 250, apexY: 176, spread: 104, depth: 96 },
  { apexX: 528, apexY: 268, spread: 116, depth: 88 },
  { apexX: 786, apexY: 148, spread: 96, depth: 104 },
]

/**
 * PORTRAIT is not a shrunk landscape.
 *
 * At 390px the landscape figure rendered 320x157, scaling its 10px axis type
 * to roughly 3px and compressing the traces into a smear -- the stage's whole
 * point was lost on a phone. Portrait crops to the middle of the section
 * instead of squeezing all of it: fewer traces at full height, larger type,
 * and the same two-target structure. The scientific meaning is identical; only
 * the framing differs, exactly as a narrower plot window would crop a real
 * radargram rather than compress it.
 */
const PORTRAIT = { x: 190, width: 470, height: 500 }

export function BScanFigure({
  className,
  scrubbed = false,
  markers = [],
  showHyperbolae = true,
  portrait = false,
}: {
  className?: string
  /** Build column-by-column on scroll instead of appearing complete. */
  scrubbed?: boolean
  /** Indices into TARGETS that receive a CANDIDATE ring. */
  markers?: number[]
  showHyperbolae?: boolean
  /** Crop to a tall window with larger type, for narrow viewports. */
  portrait?: boolean
}) {
  const columns = portrait
    ? traceColumns(PORTRAIT.width, 18, 28).map((x) => x + PORTRAIT.x)
    : traceColumns(WIDTH, 40, 60)
  const viewBox = portrait
    ? `${PORTRAIT.x} 8 ${PORTRAIT.width} ${PORTRAIT.height}`
    : `0 0 ${WIDTH} 470`
  const label = portrait ? 22 : 11
  const uid = portrait ? 'p' : 'l'

  return (
    <svg
      viewBox={viewBox}
      className={cn('h-full w-full', className)}
      role="img"
      aria-label="Illustration of a ground-penetrating radar B-scan: vertical wiggle traces showing a surface reflection and the hyperbolic arrivals produced by buried point targets."
    >
      <defs>
        <linearGradient id={`bs-depth-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.09" />
          <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
        </linearGradient>
        {/*
          The portrait crop cuts through traces at its edges. Hard-cutting a
          trace mid-oscillation reads as damage rather than as a window, so the
          acquisition fades at both sides -- exactly how a narrower plot window
          would present a real radargram. No geometry is moved or distorted;
          only its visibility at the edge changes.
        */}
        <linearGradient id={`bs-edge-${uid}`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="white" stopOpacity="0" />
          <stop offset="7%" stopColor="white" stopOpacity="1" />
          <stop offset="93%" stopColor="white" stopOpacity="1" />
          <stop offset="100%" stopColor="white" stopOpacity="0" />
        </linearGradient>
        <mask id={`bs-mask-${uid}`}>
          <rect
            x={portrait ? PORTRAIT.x : 0}
            y="0"
            width={portrait ? PORTRAIT.width : WIDTH}
            height="640"
            fill={`url(#bs-edge-${uid})`}
          />
        </mask>
      </defs>

      <rect y={TOP} width={WIDTH} height={BOTTOM - TOP} fill={`url(#bs-depth-${uid})`} />

      {/* time/depth ticks -- unnumbered, because nothing here is measured */}
      {[0, 1, 2, 3, 4].map((i) => (
        <line
          key={i}
          x1={portrait ? PORTRAIT.x : 40}
          x2={portrait ? PORTRAIT.x + PORTRAIT.width : WIDTH - 40}
          y1={TOP + ((BOTTOM - TOP) / 4) * i}
          y2={TOP + ((BOTTOM - TOP) / 4) * i}
          stroke="currentColor"
          strokeWidth="1"
          className="text-foreground/[0.06]"
        />
      ))}

      {/* the acquisition itself, revealed left to right */}
      <g
        className={scrubbed ? 'descent-acquire' : undefined}
        mask={portrait ? `url(#bs-mask-${uid})` : undefined}
      >
        {/* filled lobes first: neighbouring traces merge into reflector bands */}
        {columns.map((x) => (
          <path
            key={`fill-${x}`}
            d={traceFilled(x, TOP, BOTTOM, TARGETS, 15)}
            fill="var(--primary)"
            fillOpacity="0.16"
            stroke="none"
          />
        ))}
        {columns.map((x) => (
          <path
            key={x}
            d={trace(x, TOP, BOTTOM, TARGETS, 15)}
            fill="none"
            stroke="currentColor"
            strokeWidth="0.9"
            strokeLinecap="round"
            className="text-foreground/55"
          />
        ))}

        {showHyperbolae &&
          TARGETS.map((t) => (
            <path
              key={t.apexX}
              d={hyperbola(t.apexX, t.apexY, t.spread, t.depth, 210)}
              fill="none"
              stroke="var(--primary)"
              strokeWidth="1.25"
              strokeDasharray="3 6"
              opacity="0.75"
            />
          ))}

        {markers.map((i) => {
          const t = TARGETS[i]
          if (!t) return null
          return (
            <g key={`marker-${t.apexX}`}>
              <circle
                cx={t.apexX}
                cy={t.apexY}
                r="13"
                fill="none"
                stroke="var(--primary)"
                strokeWidth="1.25"
              />
              <circle cx={t.apexX} cy={t.apexY} r="2.5" fill="var(--primary)" />
              <line
                x1={t.apexX + 13}
                y1={t.apexY}
                x2={t.apexX + 44}
                y2={t.apexY}
                stroke="var(--primary)"
                strokeWidth="1"
              />
              <text
                x={t.apexX + (portrait ? 24 : 50)}
                y={t.apexY - (portrait ? 24 : -3.5)}
                style={{ fontSize: `${label}px` }}
                className="fill-primary font-mono uppercase tracking-[0.18em]"
              >
                candidate
              </text>
            </g>
          )
        })}
      </g>

      {/* the antenna, riding the same scroll range as the build */}
      {scrubbed && (
        <g
          className="descent-antenna"
          style={{ '--descent-travel': '848px' } as React.CSSProperties}
        >
          <rect x="42" y={TOP - 34} width="28" height="13" rx="3" fill="var(--primary)" />
          <line
            x1="56"
            y1={TOP - 21}
            x2="56"
            y2={BOTTOM + 8}
            stroke="var(--primary)"
            strokeWidth="1"
            opacity="0.45"
          />
        </g>
      )}

      <text
        x={portrait ? PORTRAIT.x + 6 : 40}
        y={TOP - (portrait ? 26 : 44)}
        style={{ fontSize: `${label}px` }}
        className="fill-muted-foreground font-mono uppercase tracking-[0.2em]"
      >
        antenna position →
      </text>
      <text
        x={portrait ? PORTRAIT.x + 6 : 40}
        y={BOTTOM + (portrait ? 44 : 30)}
        style={{ fontSize: `${label}px` }}
        className="fill-muted-foreground font-mono uppercase tracking-[0.2em]"
      >
        ↓ two-way travel time
      </text>
    </svg>
  )
}
