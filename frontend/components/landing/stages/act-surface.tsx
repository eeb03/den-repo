import Link from 'next/link'
import { ArrowDown, ArrowRight } from 'lucide-react'
import { buttonVariants } from '@/components/ui/button'
import { IllustrativeNote, Stage, StageMark } from '../descent'
import { BreakFigure } from '../figures/break-figure'
import { HeroFigure } from '../figures/hero-figure'
import { terrain } from '../figures/geometry'

/**
 * Stage 0 — SURFACE, and Stage 1 — BREAK THE SURFACE.
 *
 * These two now function as ONE event. Previously the horizon finished
 * crossing the viewport in the gap above stage 1, which left the stage itself
 * with nothing to show and made it the emptiest on the page. The horizon is
 * now driven across stage 1's own scroll range, so the visitor experiences
 * surface → break → subsurface in sequence, and the undeclared-datum point
 * emerges after the crossing rather than competing with it.
 */

export function StageSurface() {
  return (
    <Stage id="surface" index={0} defer={false} className="justify-end pb-16 sm:pb-24">
      {/* the hero occupies the whole viewport, not a decorative strip */}
      <div className="pointer-events-none absolute inset-0 -z-10">
        <HeroFigure />
      </div>

      <div className="descent-headline max-w-3xl">
        <StageMark index={0}>Surface</StageMark>

        <h1
          id="surface-heading"
          className="text-balance text-4xl font-semibold leading-[1.06] tracking-tight text-foreground sm:text-6xl lg:text-7xl"
        >
          Everything interesting
          <br />
          is under the surface.
        </h1>

        <p className="mt-6 max-w-xl text-pretty text-base leading-relaxed text-muted-foreground">
          Subterra ingests ground-penetrating radar, terrain models and survey
          ground truth into one record model — and keeps every value attached to
          how it was known. Scroll to descend through the pipeline.
        </p>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <Link
            href="/datasets"
            className={buttonVariants({ variant: 'default', size: 'lg' })}
          >
            Enter the workspace
            <ArrowRight aria-hidden />
          </Link>
          <Link
            href="/benchmark"
            className={buttonVariants({ variant: 'outline', size: 'lg' })}
          >
            Evidence and benchmarks
          </Link>
        </div>

        <p className="mt-8 flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
          <ArrowDown className="size-3.5" aria-hidden />
          Descend
        </p>
      </div>
    </Stage>
  )
}

/**
 * The crossing itself: a full-width horizon with relief above and depth
 * hatching below, translated across the viewport over this stage's range.
 */
function CrossingBand() {
  return (
    <svg
      viewBox="0 0 1440 420"
      className="h-[420px] w-full"
      preserveAspectRatio="none"
      aria-hidden
    >
      {[96, 132, 168].map((base, i) => (
        <path
          key={base}
          d={terrain(1440, base, 12, 0.7 + i, 90)}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.3"
          className="text-muted-foreground"
          opacity={0.16 + i * 0.12}
        />
      ))}
      <path
        d={terrain(1440, 212, 13, 3.3, 110)}
        fill="none"
        stroke="var(--primary)"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      {[252, 290, 328, 366].map((y, i) => (
        <line
          key={y}
          x1="0"
          x2="1440"
          y1={y}
          y2={y}
          stroke="currentColor"
          strokeWidth="1"
          strokeDasharray="1 9"
          className="text-foreground/30"
          opacity={0.9 - i * 0.18}
        />
      ))}
    </svg>
  )
}

export function StageBreak() {
  return (
    <Stage id="break" index={1} className="overflow-hidden">
      {/* THE BREAK: driven across the viewport over this stage's own range */}
      <div className="descent-bleed pointer-events-none absolute inset-x-0 top-1/2 -z-10 -translate-y-1/2">
        <div className="descent-break">
          <CrossingBand />
        </div>
      </div>

      <div className="descent-emerge grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.95fr)] lg:items-center lg:gap-16">
        <div>
          <StageMark index={1}>Break the surface</StageMark>
          <h2
            id="break-heading"
            className="text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
          >
            Above and below are different kinds of knowledge
          </h2>
          <p className="mt-5 max-w-lg text-pretty text-sm leading-relaxed text-muted-foreground sm:text-base">
            A terrain model is measured from above and carries an elevation. A
            radar section is measured from a surface downward and carries a
            travel time. Relating them needs a declared vertical datum — and no
            dataset held today declares one.
          </p>
          <p className="mt-4 max-w-lg text-pretty text-sm leading-relaxed text-muted-foreground">
            So elevation and depth stay separate, and the platform says so
            rather than guessing the offset.
          </p>
        </div>

        <figure>
          <BreakFigure />
          <IllustrativeNote>
            Illustrative — the undeclared vertical relationship is the
            platform&rsquo;s real, current state
          </IllustrativeNote>
        </figure>
      </div>
    </Stage>
  )
}
