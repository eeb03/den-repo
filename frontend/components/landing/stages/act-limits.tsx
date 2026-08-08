import Link from 'next/link'
import { ArrowRight, ArrowUp } from 'lucide-react'
import { SubterraLogo } from '@/components/brand/logo'
import { BlockedGate } from '@/components/subterra/gate-status'
import { buttonVariants } from '@/components/ui/button'
import { Stage, StageMark } from '../descent'
import { terrain } from '../figures/geometry'

/**
 * Stage 7 — GATES, and Stage 8 — VIEW.
 *
 * Stage 7 deliberately stops moving. Every other stage has something in
 * motion; this one is still, because it is the part of the descent where the
 * platform says what it cannot do, and animating that would trivialise it.
 *
 * It reuses `BlockedGate` -- the same component the workspace renders these
 * with -- rather than a landing-page lookalike. If a gate's presentation ever
 * changes in the product, it changes here too, and this page cannot keep a
 * more flattering version of the truth than the application shows.
 */

export function StageGates() {
  return (
    <Stage id="gates" index={7}>
      <div className="max-w-2xl">
        <StageMark index={7}>Gates</StageMark>
        <h2
          id="gates-heading"
          className="text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
        >
          The platform knows what it does not know
        </h2>
        <p className="mt-5 text-pretty text-sm leading-relaxed text-muted-foreground sm:text-base">
          An evidence gate is a control, not a defect. It exists so a claim the
          evidence does not support cannot be made later by accident. Two are
          closed today, both for want of evidence from the dataset publishers,
          and requests for that evidence are outstanding.
        </p>
      </div>

      <div className="mt-12 grid gap-4 md:grid-cols-2">
        <BlockedGate
          label="Localisation scoring"
          status="BLOCKED"
          reason="The specimen's absolute coordinate origin is corroborated but not declared by any published file, so reported positions would carry an unquantified offset. Detection scoring does not depend on the origin and is unaffected."
        />
        <BlockedGate
          label="Object-level utility scoring"
          status="BLOCKED"
          reason="The utility survey publishes no trench coordinates, so no detector candidate can be matched to a specific buried utility. Activity-level scoring needs no coordinates and is available."
        />
      </div>

      <div className="mt-8 grid gap-8 border-t border-border pt-8 sm:grid-cols-2 lg:grid-cols-3">
        {[
          {
            title: 'Corroboration is not declaration',
            body: 'Evidence that merely fits is recorded as corroborating. Only a source that states a fact makes it declared, and the gates read the difference.',
          },
          {
            title: 'Absence is not zero',
            body: 'A quantity nobody recorded renders as unavailable with a reason. It never becomes 0, a default, or a plausible-looking estimate.',
          },
          {
            title: 'Negative results are kept',
            body: 'Experiments that failed stay in the record with their measurements. A rejected approach is documented as rejected, not deleted.',
          },
        ].map((item) => (
          <div key={item.title}>
            <h3 className="text-sm font-semibold tracking-tight text-foreground">
              {item.title}
            </h3>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              {item.body}
            </p>
          </div>
        ))}
      </div>
    </Stage>
  )
}

const PANES = [
  { name: 'Dataset', rows: ['Metadata', 'Layers', 'Objects', 'Provenance'] },
  { name: 'Spatial', rows: ['Point cloud', 'Heatmap', 'Surface', 'B-scan'] },
  { name: 'Selection', rows: ['Map', 'Radargram', 'Depth slice', '3D scene'] },
]

export function StageView() {
  return (
    <Stage id="view" index={8} className="pb-32">
      <div className="max-w-2xl">
        <StageMark index={8}>View</StageMark>
        <h2
          id="view-heading"
          className="text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
        >
          Only now is it something you can look at
        </h2>
        <p className="mt-5 text-pretty text-sm leading-relaxed text-muted-foreground sm:text-base">
          Signal, frame, provenance and gates resolve into the workspace. Which
          views a selection supports is answered by the backend, not guessed by
          the interface — and a view that cannot resolve renders the reason it
          cannot, rather than an empty canvas.
        </p>
      </div>

      <div className="mt-12 overflow-hidden rounded-xl border border-border bg-card/40">
        <div className="flex items-center gap-2.5 border-b border-border px-4 py-2.5">
          <span aria-hidden className="size-2 rounded-full bg-prov-unavailable/60" />
          <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            Dataset workspace
          </span>
        </div>
        <div className="grid gap-px bg-border/60 md:grid-cols-3">
          {PANES.map((pane) => (
            <div key={pane.name} className="bg-card/50 p-5">
              <h3 className="font-mono text-[10px] uppercase tracking-[0.2em] text-primary">
                {pane.name}
              </h3>
              <ul className="mt-3.5 space-y-1.5">
                {pane.rows.map((row) => (
                  <li
                    key={row}
                    className="flex items-center justify-between gap-3 rounded border border-border/70 px-2.5 py-1.5 text-[11px] text-muted-foreground"
                  >
                    <span>{row}</span>
                    <span aria-hidden className="h-px w-8 bg-foreground/10" />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
      <p className="mt-3 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        Layout schematic — open the workspace for live data
      </p>

      {/*
       * THE ASCENT.
       *
       * The stage previously said "back to the surface" and never returned to
       * it, which left the descent without a close. The terrain language from
       * stage 0 now genuinely comes back: the subsurface hatching recedes
       * upward, relief reassembles above it, and the horizon reappears beneath
       * the final call to action -- so the page closes the loop it opened
       * rather than merely asserting one.
       */}
      <div className="descent-bleed relative mt-24 h-[300px] overflow-hidden sm:h-[360px]">
        <div className="descent-ascend absolute inset-x-0 bottom-0">
          <svg
            viewBox="0 0 1440 360"
            className="h-[360px] w-full"
            preserveAspectRatio="none"
            aria-hidden
          >
            {[18, 56, 94].map((y, i) => (
              <line
                key={y}
                x1="0"
                x2="1440"
                y1={y}
                y2={y}
                stroke="currentColor"
                strokeWidth="1"
                strokeDasharray="1 9"
                className="text-foreground/25"
                opacity={0.8 - i * 0.25}
              />
            ))}
            <path
              d={terrain(1440, 168, 13, 3.3, 110)}
              fill="none"
              stroke="var(--primary)"
              strokeWidth="2.25"
              strokeLinecap="round"
            />
            {[236, 274, 310, 342].map((base, i) => (
              <path
                key={base}
                d={terrain(1440, base, 16, 2.2 - i * 0.6, 90)}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.3"
                className="text-muted-foreground"
                opacity={0.42 - i * 0.09}
              />
            ))}
          </svg>
        </div>
        <span className="absolute inset-x-0 top-4 text-center font-mono text-[10px] uppercase tracking-[0.28em] text-muted-foreground/70">
          surface regained
        </span>
      </div>

      <div className="border-t border-border pt-14 text-center">
        <SubterraLogo size="lg" className="justify-center" />
        <p className="mx-auto mt-7 max-w-xl text-pretty text-base leading-relaxed text-muted-foreground">
          Subterra is built on the assumption that the honest answer is worth
          more than the impressive one. Everything above is what the platform
          does today — including the parts it refuses to do.
        </p>
        <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
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
            Read the benchmarks
          </Link>
        </div>
        <p className="mt-10 flex items-center justify-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
          <ArrowUp className="size-3.5" aria-hidden />
          Back to the surface
        </p>
      </div>
    </Stage>
  )
}
