import { cn } from '@/lib/utils'
import { asProvenanceClass, provenanceMeta } from '@/lib/provenance'
import type { ProvenanceClass } from '@/types/subterra'

/**
 * A provenance chip.
 *
 * Two invariants, both deliberate:
 *
 * 1. The text label is ALWAYS rendered. Colour is a secondary channel, so
 *    the encoding survives greyscale printing and colour-vision deficiency.
 *    There is no icon-only or dot-only variant of this component.
 *
 * 2. An unrecognised value is shown as itself, in a neutral outline, rather
 *    than being coerced to a known class. If the backend gains a new
 *    provenance class, it appears as unstyled text someone will notice --
 *    which is much better than being silently absorbed into `unavailable`
 *    and thereby asserting something about the data that nobody claimed.
 */
export function ProvenanceTag({
  provenance,
  basis,
  className,
  size = 'default',
}: {
  provenance: ProvenanceClass | string | null | undefined
  /**
   * The backend's justification sentence. Rendered as a native tooltip.
   * `schemas/provenance.py` requires a non-empty basis precisely so that a
   * provenance label is never decoration.
   */
  basis?: string | null
  className?: string
  size?: 'default' | 'sm'
}) {
  const known = asProvenanceClass(provenance)

  if (!known) {
    const raw = provenance == null ? 'unclassified' : String(provenance)
    return (
      <span
        data-provenance="unrecognised"
        title={basis ?? undefined}
        className={cn(
          'inline-flex items-center gap-1.5 rounded-md border border-dashed border-border px-1.5 py-0.5 font-mono text-muted-foreground',
          size === 'sm' ? 'text-[10px]' : 'text-xs',
          className,
        )}
      >
        {raw}
      </span>
    )
  }

  const meta = provenanceMeta[known]
  return (
    <span
      data-provenance={known}
      title={basis ? `${meta.meaning} — ${basis}` : meta.meaning}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 font-medium',
        size === 'sm' ? 'text-[10px]' : 'text-xs',
        className,
      )}
      style={{
        color: meta.color,
        borderColor: `color-mix(in oklch, ${meta.color} 32%, transparent)`,
        backgroundColor: `color-mix(in oklch, ${meta.color} 12%, transparent)`,
      }}
    >
      <span
        aria-hidden
        className="size-1.5 rounded-full"
        style={{ backgroundColor: meta.color }}
      />
      {meta.label}
    </span>
  )
}

/**
 * The provenance legend.
 *
 * Presented as a flat list, never as a scale or gradient: the backend notes
 * that "'assumed' and 'inferred' are different kinds of doubt, not
 * different amounts", so any visual ordering would assert a ranking the
 * platform refuses to make.
 */
export function ProvenanceLegend({ className }: { className?: string }) {
  return (
    <dl className={cn('grid gap-2', className)}>
      {(Object.keys(provenanceMeta) as ProvenanceClass[]).map((key) => (
        <div key={key} className="flex items-start gap-2.5">
          <dt className="shrink-0">
            <ProvenanceTag provenance={key} size="sm" />
          </dt>
          <dd className="text-xs leading-relaxed text-muted-foreground">
            {provenanceMeta[key].meaning}
          </dd>
        </div>
      ))}
    </dl>
  )
}
