import { cn } from '@/lib/utils'
import { terrain } from './geometry'

/**
 * Coordinate frames, and what happens when they cannot be related.
 *
 * Three acquisitions. Two declare a coordinate reference system, so one can be
 * reprojected onto the other and they come into register. The third declares
 * none and has no geo-tie, so nothing can place it -- it stays where it is and
 * is labelled `not_relatable`, which is the platform's own term for it.
 *
 * The refusal is the point of the figure. Forcing that third layer into
 * alignment would produce a picture that looks more finished and means less,
 * which is exactly the failure this platform exists to avoid. It is therefore
 * given as much visual weight as the pair that succeeds, and set apart in its
 * own column so the two outcomes read side by side.
 */

const WIDTH = 900
const HEIGHT = 430
const SW = 300
const SH = 132

function Swath({
  x,
  y,
  hue,
  label,
  sublabel,
  labelOffset = 0,
  dashed = false,
  className,
  style,
}: {
  x: number
  y: number
  hue: string
  label: string
  sublabel: string
  /** Lifts a label clear of the one it will land on top of. */
  labelOffset?: number
  dashed?: boolean
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <g className={className} style={style} transform={`translate(${x} ${y})`}>
      <rect
        width={SW}
        height={SH}
        rx="3"
        fill={hue}
        fillOpacity="0.06"
        stroke={hue}
        strokeWidth="1.25"
        strokeOpacity="0.75"
        strokeDasharray={dashed ? '5 5' : undefined}
      />
      {[26, 52, 78, 104].map((ly) => (
        <path
          key={ly}
          d={terrain(SW, ly, 3.5, ly / 15, 36)}
          fill="none"
          stroke={hue}
          strokeWidth="1"
          strokeOpacity="0.4"
        />
      ))}
      {/* frame origin: the corner its coordinates are measured from */}
      <g stroke={hue} strokeWidth="1.5">
        <line x1="0" y1="0" x2="20" y2="0" />
        <line x1="0" y1="0" x2="0" y2="20" />
      </g>
      {/*
        Labels sit on a solid backing plate rather than directly on the
        geometry. Frame B flies across frame A's contour lines, and grey type
        on grey lines was unreadable for most of the scroll range; a plate is
        the plain instrument-panel fix and costs nothing visually.
      */}
      <g transform={`translate(0 ${labelOffset})`}>
        <rect
          x="-4"
          y="-21"
          width={label.length * 6.6 + 12}
          height="17"
          rx="2"
          fill="var(--background)"
          opacity="0.92"
        />
        <text
          x="0"
          y="-9"
          fill={hue}
          className="font-mono text-[11px] uppercase tracking-[0.16em]"
        >
          {label}
        </text>
      </g>
      {/* A frame in flight would collide its sublabel with the one it is
          landing on, so a frame may carry a label alone. */}
      {sublabel && (
        <text
          x="0"
          y={SH + 18}
          className="fill-muted-foreground font-mono text-[10px] uppercase tracking-[0.14em]"
        >
          {sublabel}
        </text>
      )}
    </g>
  )
}

export function FrameFigure({
  className,
  aligned = false,
  tip = false,
}: {
  className?: string
  /** Whether the relatable frame reprojects into register on scroll. */
  aligned?: boolean
  /** Apply the scroll-driven 2.5D tip into plan view. */
  tip?: boolean
}) {
  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className={cn('h-full w-full', className)}
      role="img"
      aria-label="Illustration of three survey acquisitions: two that declare coordinate reference systems and come into register after reprojection, and a third that declares none and is marked not relatable."
    >
      <defs>
        <pattern
          id="ff-hatch"
          width="7"
          height="7"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <line
            x1="0"
            y1="0"
            x2="0"
            y2="7"
            stroke="currentColor"
            strokeWidth="1"
            className="text-foreground/[0.09]"
          />
        </pattern>
      </defs>

      {/* divider: relatable on the left, not relatable on the right */}
      <line
        x1={WIDTH / 2 + 10}
        y1="30"
        x2={WIDTH / 2 + 10}
        y2={HEIGHT - 30}
        stroke="currentColor"
        strokeWidth="1"
        strokeDasharray="2 8"
        className="text-foreground/15"
      />

      <g className={cn(tip && 'descent-tip')} style={{ transformOrigin: '50% 55%' }}>
        {/*
         * DIRECTION, made unambiguous at every scroll position.
         *
         * Previously frame B simply drifted, and mid-scroll you could not tell
         * whether it was arriving or departing. Now its origin is drawn as a
         * fixed ghost outline with an arrow running from there to the
         * reference frame: wherever B happens to be, the ghost says where it
         * started and the arrow says which way it is going.
         */}
        {aligned && (
          <g>
            {/*
              Opacity is applied per element, not to the group. A group-level
              0.5 dimmed the labels and their backing plates together with the
              ghost outline, which defeated the plates entirely: the two words
              naming the transformation were the hardest thing in the figure to
              read while it was happening.
            */}
            <rect
              x={54 + 74}
              y={150 - 96}
              width={SW}
              height={SH}
              rx="3"
              fill="none"
              stroke="var(--prov-declared)"
              strokeWidth="1"
              strokeDasharray="3 6"
              opacity="0.28"
            />
            <g>
              <rect
                x={54 + 70}
                y={150 - 96 - 21}
                width="132"
                height="17"
                rx="2"
                fill="var(--background)"
                opacity="0.92"
              />
              <text
                x={54 + 74}
                y={150 - 96 - 9}
                className="fill-foreground/80 font-mono text-[10px] uppercase tracking-[0.14em]"
              >
                frame b · as acquired
              </text>
            </g>

            <g stroke="var(--prov-declared)" strokeWidth="1.25" opacity="0.75">
              <line x1={54 + 74 + 22} y1={150 - 96 + SH + 8} x2={54 + 26} y2={150 - 14} />
              <polygon
                points={`${54 + 26},${150 - 14} ${54 + 40},${150 - 22} ${54 + 36},${150 - 6}`}
                fill="var(--prov-declared)"
                stroke="none"
              />
            </g>

            {/*
              REPROJECT rides beside the arrow on its own plate. It previously
              sat bare on top of frame B's contour lines, which made the one
              word naming the transformation the hardest thing in the figure to
              read while that transformation was happening.
            */}
            <g>
              <rect
                x={54 + 84}
                y={150 - 56}
                width="86"
                height="17"
                rx="2"
                fill="var(--background)"
                opacity="0.92"
              />
              <text
                x={54 + 90}
                y={150 - 44}
                className="fill-prov-declared font-mono text-[10px] uppercase tracking-[0.18em]"
              >
                reproject
              </text>
            </g>
          </g>
        )}

        {/* --- relatable pair: B reprojects onto A ------------------------- */}
        <Swath
          x={54}
          y={150}
          hue="var(--prov-measured)"
          label="frame a · epsg declared"
          sublabel="reference frame · frame b reprojects onto this"
        />
        <Swath
          className={aligned ? 'descent-align' : undefined}
          style={
            {
              '--descent-offset-x': '74px',
              '--descent-offset-y': '-96px',
              '--descent-offset-r': '-5deg',
              transformOrigin: '204px 216px',
            } as React.CSSProperties
          }
          x={54}
          y={150}
          hue="var(--prov-declared)"
          label="frame b · epsg declared"
          labelOffset={-22}
          sublabel=""
        />

        {/* --- not relatable: no declared CRS, no geo-tie ------------------ */}
        <g transform={`translate(${WIDTH / 2 + 56} 150)`}>
          <rect
            width={SW}
            height={SH}
            rx="3"
            fill="url(#ff-hatch)"
            stroke="var(--prov-unavailable)"
            strokeWidth="1.25"
            strokeDasharray="5 5"
            strokeOpacity="0.8"
          />
          {[26, 52, 78, 104].map((ly) => (
            <path
              key={ly}
              d={terrain(SW, ly, 3.5, ly / 15, 36)}
              fill="none"
              stroke="var(--prov-unavailable)"
              strokeWidth="1"
              strokeOpacity="0.3"
            />
          ))}
          {/* no origin marker is drawn: there is no frame to draw one in */}
          <text
            x="0"
            y="-10"
            className="fill-muted-foreground font-mono text-[11px] uppercase tracking-[0.16em]"
          >
            frame c · no crs declared
          </text>

          {/*
           * The verdict, sized as a verdict. It was previously a 148px chip
           * and read as a footnote; the refusal is the most important claim in
           * this figure and now carries the weight to say so -- without glow,
           * because an instrument states a fault, it does not advertise one.
           */}
          <g transform={`translate(${SW / 2 - 116} ${SH / 2 - 25})`}>
            <rect
              width="232"
              height="50"
              rx="3"
              fill="var(--background)"
              stroke="var(--destructive)"
              strokeOpacity="0.75"
              strokeWidth="1.25"
            />
            <text
              x="116"
              y="21"
              textAnchor="middle"
              className="fill-destructive font-mono text-[16px] uppercase tracking-[0.14em]"
            >
              not_relatable
            </text>
            <text
              x="116"
              y="39"
              textAnchor="middle"
              className="fill-muted-foreground font-mono text-[9.5px] uppercase tracking-[0.14em]"
            >
              no crs · no geo-tie
            </text>
          </g>

          <text
            x="0"
            y={SH + 18}
            className="fill-muted-foreground font-mono text-[10px] uppercase tracking-[0.14em]"
          >
            left where it is — not placed on earth
          </text>
        </g>
      </g>
    </svg>
  )
}
