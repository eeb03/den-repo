import { cn } from '@/lib/utils'

/**
 * A benchmark metric, rendered exactly as the artifact stores it.
 *
 * `String(value)` and nothing else. No rounding, no percentage conversion,
 * no unit inference, no sign flipping. A recall of 0.06521739130434782 is
 * shown at full precision; rendering it as "6.5%" would be a transformation
 * of a scientific result, and small transformations are how a number stops
 * matching the run that produced it.
 *
 * A metric the artifact does not carry renders as an explicit "not
 * reported" rather than being omitted. Silently dropping it would leave a
 * reader unable to tell a metric that was not computed from one that was
 * computed and happened to be absent from the layout.
 */
export function Metric({
  label,
  value,
  note,
  emphasis = false,
  className,
}: {
  label: string
  value: number | string | boolean | null | undefined
  /** Wording from the artifact where it has some; never invented here. */
  note?: string | null
  emphasis?: boolean
  className?: string
}) {
  const missing = value === null || value === undefined
  return (
    <div
      data-metric={label}
      className={cn(
        'grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-3 border-b border-border/60 py-1.5 last:border-0',
        className,
      )}
    >
      <dt className="text-xs leading-relaxed text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          'tabular text-right font-mono',
          missing
            ? 'text-[11px] italic text-muted-foreground'
            : emphasis
              ? 'text-sm font-medium text-foreground'
              : 'text-xs text-foreground',
        )}
      >
        {missing ? 'not reported' : String(value)}
      </dd>
      {note && (
        <p className="col-span-2 -mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
          {note}
        </p>
      )}
    </div>
  )
}

/**
 * A block of interpretation, always attributed to its source.
 *
 * `source` is required: an interpretive claim on this page must be
 * traceable to the artifact or to a document in the repository, so a reader
 * can check it. An unattributed claim would be this UI's opinion dressed as
 * a result.
 */
export function Interpretation({
  title,
  source,
  uncertain = false,
  children,
  className,
}: {
  title: string
  /** e.g. "docs/bam-benchmark-detection.md §4" or "artifact: score.activity_level_note". */
  source: string
  /** Marks a reading the evidence does not settle. */
  uncertain?: boolean
  children: React.ReactNode
  className?: string
}) {
  return (
    <section
      data-interpretation={title}
      data-uncertain={uncertain ? 'true' : 'false'}
      className={cn(
        'rounded-lg border px-3 py-2.5',
        uncertain
          ? 'subterra-hatch border-prov-inferred/40'
          : 'border-border bg-muted/20',
        className,
      )}
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <h4 className="text-xs font-medium text-foreground">{title}</h4>
        {uncertain && (
          <span className="rounded border border-prov-inferred/40 px-1.5 py-px text-[10px] uppercase tracking-wider text-prov-inferred">
            uncertain
          </span>
        )}
      </div>
      <div className="mt-1.5 space-y-1.5 text-xs leading-relaxed text-muted-foreground">
        {children}
      </div>
      <p className="mt-2 font-mono text-[10px] text-muted-foreground/70">
        source: {source}
      </p>
    </section>
  )
}
