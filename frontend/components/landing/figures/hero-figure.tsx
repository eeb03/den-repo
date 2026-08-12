import { cn } from '@/lib/utils'
import { arrivalAt, hyperbola, terrain } from './geometry'

/**
 * The opening viewport, as one composition rather than a decorative strip.
 *
 * WHAT CHANGED AND WHY. The first version drew five faint contours across the
 * bottom third and left the top and right of the viewport empty; measured, the
 * hero filled 47% of its own height and the strongest element -- the surface
 * line -- was cropped by the bottom edge. The visitor remembered the sentence,
 * not the site.
 *
 * This version treats the whole viewport as a section through the ground:
 * relief above a deliberately placed horizon, and beneath it the first hint of
 * the motifs the descent will develop -- a depth grid, two diffraction
 * hyperbolae, and a trace. So the page states "subsurface" visually before a
 * word is read, and the hero stops being decoration and becomes the first
 * frame of the narrative.
 *
 * The right third, previously dead space, carries an instrument scale. Its
 * ticks are DELIBERATELY UNNUMBERED: the platform has no established vertical
 * datum for any dataset it holds, so a numbered depth axis would be the page's
 * first fabricated measurement. Words only.
 *
 * Everything is closed-form geometry -- sums of sines, and the textbook
 * hyperbola -- so it is identical on every render.
 */

const W = 1440
const H = 900
const HORIZON = 548

/** Relief above the horizon, drifting at fixed rates so the eye reads depth. */
const BANDS = [
  { base: 168, amp: 20, phase: 0.3, opacity: 0.1, rate: 4.2 },
  { base: 214, amp: 21, phase: 0.85, opacity: 0.14, rate: 3.6 },
  { base: 262, amp: 22, phase: 1.4, opacity: 0.18, rate: 3.0 },
  { base: 312, amp: 23, phase: 1.95, opacity: 0.24, rate: 2.5 },
  { base: 362, amp: 24, phase: 2.5, opacity: 0.3, rate: 2.0 },
  { base: 412, amp: 25, phase: 3.05, opacity: 0.38, rate: 1.5 },
  { base: 462, amp: 26, phase: 3.6, opacity: 0.46, rate: 1.05 },
  { base: 506, amp: 27, phase: 4.15, opacity: 0.56, rate: 0.6 },
]

/** Two targets below the horizon: the motif stage 2 develops into a B-scan. */
const SEEDS = [
  { apexX: 386, apexY: 690, spread: 150, depth: 120 },
  { apexX: 1004, apexY: 754, spread: 168, depth: 108 },
]

export function HeroFigure({ className }: { className?: string }) {
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className={cn('h-full w-full', className)}
      preserveAspectRatio="xMidYMid slice"
      role="img"
      aria-label="Illustration of a section through the ground: layered terrain relief above a surface horizon, and beneath it a depth grid with the hyperbolic signatures two buried targets would leave."
    >
      <defs>
        <linearGradient id="hf-sub" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.13" />
          <stop offset="70%" stopColor="var(--primary)" stopOpacity="0.02" />
          <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="hf-edge" x1="0" y1="0" x2="1" y2="0">
          {/*
            The left fade is wide on purpose: the depth rail lives in the first
            ~170px and the relief now has enough contrast to compete with it.
            Fading the geometry out behind the rail keeps the readout legible
            without dimming the composition everywhere else.
          */}
          <stop offset="0%" stopColor="white" stopOpacity="0" />
          <stop offset="7%" stopColor="white" stopOpacity="0" />
          <stop offset="17%" stopColor="white" stopOpacity="1" />
          <stop offset="93%" stopColor="white" stopOpacity="1" />
          <stop offset="100%" stopColor="white" stopOpacity="0" />
        </linearGradient>
        <mask id="hf-mask">
          <rect width={W} height={H} fill="url(#hf-edge)" />
        </mask>
      </defs>

      <g mask="url(#hf-mask)">
        {/* --- below the horizon: the ground the page is about ------------- */}
        <rect y={HORIZON} width={W} height={H - HORIZON} fill="url(#hf-sub)" />

        {[624, 700, 776, 852].map((y) => (
          <line
            key={y}
            x1="0"
            x2={W}
            y1={y}
            y2={y}
            stroke="currentColor"
            strokeWidth="1"
            strokeDasharray="1 9"
            className="text-foreground/25"
          />
        ))}

        {SEEDS.map((s) => (
          <g key={s.apexX}>
            <path
              d={hyperbola(s.apexX, s.apexY, s.spread, s.depth, 300)}
              fill="none"
              stroke="var(--primary)"
              strokeWidth="1.5"
              opacity="0.34"
            />
            <path
              d={hyperbola(s.apexX, s.apexY + 16, s.spread, s.depth, 300)}
              fill="none"
              stroke="var(--primary)"
              strokeWidth="1"
              opacity="0.16"
            />
            <circle cx={s.apexX} cy={s.apexY} r="3" fill="var(--primary)" opacity="0.8" />
          </g>
        ))}

        {/* --- the horizon: the one line that separates air from ground ---- */}
        <path
          className="descent-parallax"
          style={{ '--descent-rate': 0.25 } as React.CSSProperties}
          d={terrain(W, HORIZON, 13, 3.3, 120)}
          fill="none"
          stroke="var(--primary)"
          strokeWidth="2.25"
          strokeLinecap="round"
        />

        {/* --- relief above ------------------------------------------------ */}
        {BANDS.map((b) => (
          <path
            key={b.base}
            className="descent-parallax text-muted-foreground"
            style={{ '--descent-rate': b.rate } as React.CSSProperties}
            d={terrain(W, b.base, b.amp, b.phase, 120)}
            fill="none"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
            opacity={b.opacity}
          />
        ))}
      </g>

      {/* --- the instrument scale: the right third earns its space -------- */}
      <g transform={`translate(${W - 132} 0)`}>
        <line
          x1="0"
          y1="150"
          x2="0"
          y2={H - 60}
          stroke="currentColor"
          strokeWidth="1"
          className="text-foreground/15"
        />
        {/* unnumbered ticks: no vertical datum exists to number them against */}
        {Array.from({ length: 15 }, (_, i) => 168 + i * 48).map((y) => (
          <line
            key={y}
            x1="0"
            x2={y === HORIZON - 4 ? 22 : 10}
            y1={y}
            y2={y}
            stroke="currentColor"
            strokeWidth="1"
            className="text-foreground/25"
          />
        ))}
        <line
          x1="-8"
          x2="30"
          y1={HORIZON}
          y2={HORIZON}
          stroke="var(--primary)"
          strokeWidth="1.5"
        />
        <text
          x="36"
          y={HORIZON - 10}
          className="fill-primary font-mono text-[11px] uppercase tracking-[0.2em]"
        >
          surface
        </text>
        <text
          x="36"
          y={HORIZON + 26}
          className="fill-muted-foreground font-mono text-[11px] uppercase tracking-[0.2em]"
        >
          depth
        </text>
        <text
          x="36"
          y="176"
          className="fill-muted-foreground font-mono text-[11px] uppercase tracking-[0.2em]"
        >
          air
        </text>

        {/* a single trace, the third motif the descent picks up */}
        <path
          d={`M ${Array.from({ length: 70 }, (_, i) => {
            const y = HORIZON + (i / 69) * (H - HORIZON - 40)
            const a = arrivalAt(58, SEEDS[0]!.apexX, SEEDS[0]!.apexY, SEEDS[0]!.spread, SEEDS[0]!.depth)
            const env = Math.exp(-(((y - a) / 40) ** 2))
            return `${(-64 + Math.sin((y - HORIZON) / 9) * 9 * env).toFixed(1)},${y.toFixed(1)}`
          }).join(' L ')}`}
          fill="none"
          stroke="var(--chart-2)"
          strokeWidth="1.25"
          opacity="0.45"
        />
      </g>
    </svg>
  )
}
