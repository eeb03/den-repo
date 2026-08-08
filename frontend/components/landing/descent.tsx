'use client'

import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

/**
 * The descent shell: a fixed substrate, a depth rail, and the stages that
 * travel over them.
 *
 * THE ONLY JAVASCRIPT ON THIS PAGE lives here, and it does exactly one thing
 * CSS cannot: name the stage the visitor is currently in, so the rail can
 * indicate it and the substrate can shift tint. It is a single
 * IntersectionObserver with no scroll listener, so there is no per-frame
 * handler and nothing reads layout during scroll.
 *
 * Everything else -- parallax, the scrubbed acquisition, the 2.5D tip, the
 * reprojection -- is CSS scroll-driven animation, and every one of those is
 * an enhancement over a base state that is already complete. If this
 * component never mounted, the page would still read start to finish.
 */

export interface StageMeta {
  id: string
  /** Rail label. Short: this is an instrument readout, not a nav menu. */
  label: string
  /** Which substrate tint this stage sits in. */
  depth: 'surface' | 'shallow' | 'deep' | 'return'
}

export const STAGES: readonly StageMeta[] = [
  { id: 'surface', label: 'Surface', depth: 'surface' },
  { id: 'break', label: 'Break', depth: 'surface' },
  { id: 'signal', label: 'Signal', depth: 'shallow' },
  { id: 'candidate', label: 'Candidate', depth: 'shallow' },
  { id: 'frame', label: 'Frame', depth: 'deep' },
  { id: 'fusion', label: 'Fusion', depth: 'deep' },
  { id: 'provenance', label: 'Provenance', depth: 'deep' },
  { id: 'gates', label: 'Gates', depth: 'deep' },
  { id: 'view', label: 'View', depth: 'return' },
] as const

export function Descent({ children }: { children: React.ReactNode }) {
  const [active, setActive] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const root = rootRef.current
    if (!root) return

    const stages = Array.from(root.querySelectorAll<HTMLElement>('[data-stage]'))
    if (stages.length === 0) return

    /*
     * TWO OBSERVERS, because they answer different questions.
     *
     * Entrance is "has this stage appeared at all" -- a normal threshold.
     *
     * Active stage is "which stage is the visitor in", and that CANNOT use
     * intersectionRatio: the ratio is a fraction of the TARGET's area, so a
     * stage taller than the viewport never reaches a high ratio and the rail
     * silently stops advancing. That is exactly what happened on a 390px-wide
     * phone, where the rail froze three stages in. Collapsing the root to a
     * thin band across the middle of the viewport makes the test
     * "does this stage cross the centre line", which is independent of both
     * stage height and viewport height.
     */
    const entrance = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            ;(entry.target as HTMLElement).dataset.entered = 'true'
          }
        }
      },
      { threshold: 0.08 },
    )

    const centreBand = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          const index = stages.indexOf(entry.target as HTMLElement)
          if (index >= 0) setActive(index)
        }
      },
      { threshold: 0, rootMargin: '-45% 0px -50% 0px' },
    )

    for (const stage of stages) {
      // Only mark un-entered once observed, so a script failure leaves the
      // page fully visible rather than blank.
      if (!stage.dataset.entered) stage.dataset.entered = 'false'
      entrance.observe(stage)
      centreBand.observe(stage)
    }
    return () => {
      entrance.disconnect()
      centreBand.disconnect()
    }
  }, [])

  const depth = STAGES[active]?.depth ?? 'surface'

  return (
    <div
      ref={rootRef}
      className="descent-root relative"
      data-depth={depth}
      data-active-stage={STAGES[active]?.id}
    >
      <div className="descent-backdrop" aria-hidden />
      <DepthRail activeIndex={active} />
      <div className="relative z-10">{children}</div>
    </div>
  )
}

/**
 * The persistent depth indicator.
 *
 * It reports position in the descent by STAGE NAME, never in metres. The
 * platform has no established vertical datum for any dataset it holds, so a
 * depth scale in real units would be the page's first fabricated measurement.
 */
function DepthRail({ activeIndex }: { activeIndex: number }) {
  const progress = ((activeIndex + 1) / STAGES.length) * 100

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed left-0 top-0 z-20 flex h-svh items-center pl-3 sm:pl-6"
    >
      {/* mobile: a bare progress edge. desktop: the full readout. */}
      <div className="relative h-[46svh] w-px bg-border sm:h-[54svh]">
        <div
          className="absolute left-0 top-0 w-px bg-primary transition-[height] duration-700 ease-out"
          style={{ height: `${progress}%` }}
        />
      </div>

      <ol className="ml-3 hidden flex-col gap-3 md:flex">
        {STAGES.map((stage, i) => {
          const isActive = i === activeIndex
          const isPast = i < activeIndex
          return (
            <li
              key={stage.id}
              className={cn(
                'flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] transition-colors duration-500',
                isActive
                  ? 'text-primary'
                  : isPast
                    ? 'text-muted-foreground/70'
                    : 'text-muted-foreground/30',
              )}
            >
              <span
                className={cn(
                  'h-px transition-all duration-500',
                  isActive ? 'w-4 bg-primary' : 'w-2 bg-current',
                )}
              />
              {stage.label}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

/**
 * One stage of the descent.
 *
 * `defer` opts a stage into content-visibility so far-below-fold geometry is
 * not laid out until it is approached; it carries an intrinsic size so the
 * scrollbar stays stable and the scrubbing ranges do not shift underneath the
 * visitor as stages materialise.
 */
export function Stage({
  id,
  index,
  className,
  defer = true,
  children,
}: {
  id: string
  index: number
  className?: string
  defer?: boolean
  children: React.ReactNode
}) {
  return (
    <section
      data-stage={id}
      data-stage-index={index}
      aria-labelledby={`${id}-heading`}
      className={cn(
        'descent-stage relative flex min-h-svh flex-col justify-center px-5 py-24 pl-12 sm:px-8 sm:pl-20 md:pl-40',
        defer && 'descent-defer',
        className,
      )}
    >
      <div className="mx-auto w-full max-w-5xl">{children}</div>
    </section>
  )
}

/** The small-caps stage marker that opens each stage. */
export function StageMark({ index, children }: { index: number; children: React.ReactNode }) {
  return (
    <p className="mb-4 flex items-center gap-3 font-mono text-[11px] uppercase tracking-[0.24em] text-primary">
      <span className="tabular text-muted-foreground">
        {String(index).padStart(2, '0')}
      </span>
      <span className="h-px w-6 bg-primary/40" />
      {children}
    </p>
  )
}

/** Figure caption used wherever geometry is drawn rather than measured. */
export function IllustrativeNote({ children }: { children?: React.ReactNode }) {
  return (
    <p className="mt-3 font-mono text-[10px] uppercase leading-relaxed tracking-[0.18em] text-muted-foreground">
      {children ?? 'Illustrative geometry — not measured data'}
    </p>
  )
}
