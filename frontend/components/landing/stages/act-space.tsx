import { provenanceMeta, provenanceOrder } from '@/lib/provenance'
import { IllustrativeNote, Stage, StageMark } from '../descent'
import { FrameFigure } from '../figures/frame-figure'

/**
 * Stage 4 — FRAME, Stage 5 — FUSION, Stage 6 — PROVENANCE.
 *
 * The middle act is where the platform's actual differentiator lives. Stage 5
 * ends on a refusal, and stage 6 explains why a number alone is not an answer.
 */

export function StageFrame() {
  return (
    <Stage id="frame" index={4}>
      <div className="max-w-2xl">
        <StageMark index={4}>Frame</StageMark>
        <h2
          id="frame-heading"
          className="text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
        >
          Two surveys that look alike are not therefore comparable
        </h2>
        <p className="mt-5 text-pretty text-sm leading-relaxed text-muted-foreground sm:text-base">
          Every acquisition carries a frame: what its coordinates mean, which
          reference system they are in, and how that was known. In Subterra a
          position is a discriminated union — geographic, projected, odometry,
          local-cartesian, or explicitly none. There is no variant with an
          optional latitude, so &ldquo;defaulting to zero&rdquo; is not
          expressible.
        </p>
      </div>

      <figure className="descent-bleed mt-10" style={{ perspective: '1400px' }}>
        <FrameFigure tip className="max-h-[54svh]" />
        <div className="mx-auto max-w-6xl px-5 sm:px-8">
          <IllustrativeNote>
            Illustrative frames — the position kinds and CRS provenance shown are
            the platform&rsquo;s real vocabulary
          </IllustrativeNote>
        </div>
      </figure>
    </Stage>
  )
}

export function StageFusion() {
  return (
    <Stage id="fusion" index={5}>
      <div className="grid gap-10">
        <div className="max-w-2xl">
          <StageMark index={5}>Fusion</StageMark>
          <h2
            id="fusion-heading"
            className="text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
          >
            Some layers align. One does not, and stays where it is.
          </h2>
          <p className="mt-5 text-pretty text-sm leading-relaxed text-muted-foreground sm:text-base">
            Where two frames declare coordinate reference systems, Subterra
            reprojects one onto the other and fuses them. Where a layer declares
            no CRS and carries no geo-tie, nothing can place it on Earth — and
            no amount of processing changes that.
          </p>
          <p className="mt-4 text-pretty text-sm leading-relaxed text-muted-foreground">
            So it is not placed. It is returned as{' '}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12px] text-destructive">
              not_relatable
            </code>{' '}
            with the reason attached, and drawn as unplaced. A tool that snapped
            it into the picture anyway would produce something that looks
            finished and means nothing.
          </p>

          <div className="mt-8 space-y-2.5 border-l border-border pl-4">
            {[
              ['Declared CRS on both sides', 'reproject and fuse'],
              ['Declared CRS on one side only', 'geo-tie required, or unplaced'],
              ['No CRS, no geo-tie', 'not_relatable — rendered as unplaced'],
            ].map(([condition, outcome]) => (
              <p key={condition} className="text-xs leading-relaxed">
                <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                  {condition}
                </span>
                <span className="mx-2 text-muted-foreground/40">→</span>
                <span className="text-foreground">{outcome}</span>
              </p>
            ))}
          </div>
        </div>

      </div>

      {/* The refusal gets the width. No box: this is not a readout panel. */}
      <figure className="descent-bleed mt-10">
        <FrameFigure aligned className="max-h-[56svh]" />
        <div className="mx-auto max-w-6xl px-5 sm:px-8">
          <IllustrativeNote>
            Illustrative frames — the refusal shown is the platform&rsquo;s real
            behaviour on layers with no declared CRS
          </IllustrativeNote>
        </div>
      </figure>
    </Stage>
  )
}

/**
 * Stage 6 drives entirely off `provenanceMeta` / `provenanceOrder`, the same
 * vocabulary the workspace renders. If the backend's classes ever change, this
 * section changes with them rather than keeping a flattering copy.
 *
 * The active class here is `inferred`, chosen because it is the honest answer
 * for a reconstructed frame on the datasets actually held — not the most
 * impressive one available.
 */
const ACTIVE = 'inferred'
const BASIS =
  'inferred from stored records; this dataset predates SurveyFrame'

export function StageProvenance() {
  return (
    <Stage id="provenance" index={6}>
      <div className="max-w-2xl">
        <StageMark index={6}>Provenance</StageMark>
        <h2
          id="provenance-heading"
          className="text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
        >
          A number is not an answer until you know where it came from
        </h2>
        <p className="mt-5 text-pretty text-sm leading-relaxed text-muted-foreground sm:text-base">
          Every quantity carries one of seven provenance classes and a written
          basis. The classes are not a ranking — &ldquo;assumed&rdquo; and
          &ldquo;inferred&rdquo; are different kinds of doubt, not different
          amounts — so each gets its own hue and always renders its label.
        </p>
      </div>

      {/*
        Denser composition, same vocabulary. The stage previously ran a narrow
        value card beside a single column of chips and filled about half its
        height. The card now carries the full record it belongs to -- quantity,
        value, class, basis -- and the seven classes sit in two columns beside
        it. Nothing here is new information: every string comes from
        `provenanceMeta`, which is the same source the workspace renders.
      */}
      <div className="mt-10 grid gap-8 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:gap-12">
        <div className="flex flex-col rounded-xl border border-border bg-background/50 p-6">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            quantity
          </p>
          <p className="mt-1.5 font-mono text-sm text-foreground">horizontal_crs</p>

          <p className="mt-5 font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            value
          </p>
          <p className="mt-1.5 font-mono text-3xl text-foreground">EPSG:4326</p>

          <div className="mt-5 border-t border-border pt-4">
            <span
              className="inline-flex items-center gap-2 rounded-md border px-2 py-1 font-mono text-[11px] uppercase tracking-[0.14em]"
              style={{
                borderColor: provenanceMeta[ACTIVE].color,
                color: provenanceMeta[ACTIVE].color,
              }}
            >
              <span
                aria-hidden
                className="size-1.5 rounded-full"
                style={{ background: provenanceMeta[ACTIVE].color }}
              />
              {provenanceMeta[ACTIVE].label}
            </span>
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
              <span className="text-foreground">Basis. </span>
              {BASIS}
            </p>
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
              The value alone would read as fact. With its class and basis it
              reads as what it is: a reconstruction, usable but not authoritative.
            </p>
          </div>
        </div>

        <ul className="grid grid-cols-1 gap-1.5 self-center sm:grid-cols-2">
          {provenanceOrder.map((klass) => {
            const meta = provenanceMeta[klass]
            const active = klass === ACTIVE
            return (
              <li
                key={klass}
                data-provenance={klass}
                data-active={active}
                className={`flex items-baseline gap-2.5 rounded-md border px-3 py-2.5 transition-opacity duration-500 ${
                  active
                    ? 'border-border bg-card/60 sm:col-span-2'
                    : 'border-border/40 opacity-45'
                }`}
              >
                <span
                  aria-hidden
                  className="size-1.5 shrink-0 rounded-full"
                  style={{ background: meta.color }}
                />
                <span
                  className="font-mono text-[11px] uppercase tracking-[0.14em]"
                  style={{ color: active ? meta.color : undefined }}
                >
                  {meta.label}
                </span>
                <span className="text-[11px] leading-relaxed text-muted-foreground">
                  {meta.meaning}
                </span>
              </li>
            )
          })}
        </ul>
      </div>
    </Stage>
  )
}
