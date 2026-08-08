import { cn } from '@/lib/utils'
import { NO_CONFIDENCE_STATED, formatConfidence } from '@/lib/format'
import type { Confidence } from '@/types/subterra'

/**
 * A confidence readout that can represent "not stated".
 *
 * The v0 design had a `ConfidenceMeter` taking `value: number`, because in
 * the prototype every target had a confidence. In Subterra a label may
 * carry `confidence: null`, and
 * `tests/test_thin_client.py::test_labels_reach_the_client_with_their_identity_and_provenance`
 * asserts `confidence is None` survives to the client -- "no confidence
 * invented".
 *
 * So the null case renders as an explicit absence with NO bar drawn. A
 * zero-length bar would read as "confidence 0%", which is a measurement,
 * and the opposite of what null means.
 */
export function ConfidenceValue({
  value,
  className,
  showBar = true,
}: {
  value: Confidence
  className?: string
  showBar?: boolean
}) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return (
      <span
        data-confidence="unstated"
        className={cn(
          'inline-flex items-center gap-1.5 text-xs text-muted-foreground',
          className,
        )}
      >
        <span
          aria-hidden
          className="h-1.5 w-8 rounded-full border border-dashed border-prov-unavailable/50"
        />
        <span className="italic">{NO_CONFIDENCE_STATED}</span>
      </span>
    )
  }

  const clamped = Math.max(0, Math.min(1, value))
  const pct = Math.round(clamped * 100)
  const color =
    clamped >= 0.9 ? 'var(--success)' : clamped >= 0.75 ? 'var(--primary)' : 'var(--warning)'

  return (
    <span
      data-confidence="stated"
      className={cn('inline-flex items-center gap-2', className)}
    >
      {showBar && (
        <span className="h-1.5 w-full min-w-16 overflow-hidden rounded-full bg-muted">
          <span
            className="block h-full rounded-full"
            style={{ width: `${pct}%`, backgroundColor: color }}
          />
        </span>
      )}
      <span className="tabular shrink-0 text-right font-mono text-xs text-muted-foreground">
        {formatConfidence(value)}
      </span>
    </span>
  )
}
