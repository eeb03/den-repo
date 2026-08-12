import { cn } from '@/lib/utils'
import { terrain } from './geometry'

/**
 * The two vertical axes that do not meet, and the fact that they do not.
 *
 * WHAT CHANGED. The first version placed a `RELATIONSHIP: UNDECLARED` chip on
 * top of the dashed line joining the axes, so the border cut through the word
 * -- a plain defect. More importantly the chip read as an afterthought rather
 * than as the subject.
 *
 * Here the undeclared relationship is drawn as what it actually is: a MEASURED
 * GAP. Each axis terminates in a bracket, and between the two brackets sits an
 * open span with no value in it, because no source states one. The chip is
 * centred inside that span with the dashes stopping at its edges, so nothing
 * overlaps and the composition reads as an instrument's unfilled field.
 *
 * The claim is the platform's real, current state: no dataset held declares a
 * vertical datum, so elevation and travel time cannot be related.
 */

const W = 620
const H = 400
const SURFACE = 168
const AXIS_X = 148
const GAP_X = 396

export function BreakFigure({ className }: { className?: string }) {
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className={cn('h-full w-full', className)}
      role="img"
      aria-label="Illustration contrasting an elevation axis measured downward from above with a radar travel-time axis measured downward from the surface, and the gap between them labelled as an undeclared relationship."
    >
      {/* the surface, continuing the horizon language from the hero */}
      <path
        d={terrain(W, SURFACE, 5, 3.3, 60)}
        fill="none"
        stroke="var(--primary)"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <text
        x="16"
        y={SURFACE - 12}
        className="fill-primary font-mono text-[11px] uppercase tracking-[0.2em]"
      >
        surface
      </text>

      {/* above: elevation, referenced to a datum that must be declared */}
      <g stroke="var(--prov-measured)" strokeWidth="1.5">
        <line x1={AXIS_X} y1="52" x2={AXIS_X} y2={SURFACE - 4} />
        <line x1={AXIS_X - 8} y1="52" x2={AXIS_X + 8} y2="52" />
      </g>
      <text
        x={AXIS_X + 18}
        y="58"
        className="fill-muted-foreground font-mono text-[10px] uppercase tracking-[0.16em]"
      >
        elevation
      </text>
      <text
        x={AXIS_X + 18}
        y="74"
        className="fill-muted-foreground/70 font-mono text-[10px] uppercase tracking-[0.16em]"
      >
        needs a datum
      </text>

      {/* below: two-way time, referenced to instrument zero */}
      <g stroke="var(--prov-derived)" strokeWidth="1.5">
        <line x1={AXIS_X} y1={SURFACE + 4} x2={AXIS_X} y2={H - 52} />
        <line x1={AXIS_X - 8} y1={H - 52} x2={AXIS_X + 8} y2={H - 52} />
      </g>
      <text
        x={AXIS_X + 18}
        y={H - 56}
        className="fill-muted-foreground font-mono text-[10px] uppercase tracking-[0.16em]"
      >
        travel time
      </text>
      <text
        x={AXIS_X + 18}
        y={H - 40}
        className="fill-muted-foreground/70 font-mono text-[10px] uppercase tracking-[0.16em]"
      >
        from instrument zero
      </text>

      {/*
       * The gap itself. Two brackets, and between them a span with nothing in
       * it -- the dashes stop short of the chip on both sides so the label sits
       * in clear air rather than across a line.
       */}
      <g stroke="var(--prov-unavailable)" strokeWidth="1.25">
        <line x1={GAP_X} y1="96" x2={GAP_X} y2="154" />
        <line x1={GAP_X - 10} y1="96" x2={GAP_X + 10} y2="96" />
        <line x1={GAP_X} y1={H - 150} x2={GAP_X} y2={H - 92} />
        <line x1={GAP_X - 10} y1={H - 92} x2={GAP_X + 10} y2={H - 92} />
      </g>
      <line
        x1={GAP_X}
        y1="154"
        x2={GAP_X}
        y2="182"
        stroke="var(--prov-unavailable)"
        strokeWidth="1"
        strokeDasharray="3 5"
      />
      <line
        x1={GAP_X}
        y1={H - 178}
        x2={GAP_X}
        y2={H - 150}
        stroke="var(--prov-unavailable)"
        strokeWidth="1"
        strokeDasharray="3 5"
      />

      <g transform={`translate(${GAP_X - 92} ${H / 2 - 26})`}>
        <rect
          width="184"
          height="52"
          rx="3"
          fill="var(--background)"
          stroke="var(--prov-unavailable)"
          strokeWidth="1"
          strokeOpacity="0.7"
        />
        <text
          x="92"
          y="21"
          textAnchor="middle"
          className="fill-muted-foreground font-mono text-[10px] uppercase tracking-[0.18em]"
        >
          relationship
        </text>
        <text
          x="92"
          y="39"
          textAnchor="middle"
          className="fill-foreground font-mono text-[13px] uppercase tracking-[0.16em]"
        >
          undeclared
        </text>
      </g>
    </svg>
  )
}
