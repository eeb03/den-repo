import { cn } from '@/lib/utils'
import type { DatasetSummary } from '@/types/subterra'

/**
 * A dataset's lifecycle state.
 *
 * DERIVED, NOT STORED, and the backend says so: the status comes from whether
 * an import is in flight and whether records exist, so it cannot disagree with
 * either. This component renders that answer and computes nothing.
 *
 * `empty` and `failed` are drawn the same weight as `ready` rather than as
 * alarms. A dataset that produced no records is a real outcome worth reading,
 * not a fault to apologise for — and the reason is always shown next to it, in
 * the backend's own words.
 */
const STATUS_STYLE: Record<DatasetSummary['status'], { label: string; dot: string }> = {
  ready: { label: 'Ready', dot: 'bg-primary' },
  importing: { label: 'Importing', dot: 'bg-primary/50 ring-1 ring-primary/70 animate-pulse' },
  empty: { label: 'Empty', dot: 'border border-muted-foreground/60' },
  failed: { label: 'Failed', dot: 'border border-muted-foreground/60' },
}

export function DatasetStatusBadge({ dataset }: { dataset: DatasetSummary }) {
  const style = STATUS_STYLE[dataset.status] ?? STATUS_STYLE.empty
  return (
    <span
      data-status={dataset.status}
      title={dataset.status_reason}
      className="inline-flex shrink-0 items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground"
    >
      <span className={cn('size-1.5 rounded-full', style.dot)} aria-hidden="true" />
      {style.label}
    </span>
  )
}
