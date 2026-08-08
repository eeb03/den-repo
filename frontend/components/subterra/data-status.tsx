import { cn } from '@/lib/utils'
import { ProvenanceTag } from './provenance-tag'
import { NO_VALUE } from '@/lib/format'
import type { Position, SpatialRefSummary } from '@/types/subterra'
import { positionUnavailableReason } from '@/types/subterra'

/**
 * Whether a dataset carries ground truth.
 *
 * Three-valued on purpose. `has_ground_truth` is nullable in the registry,
 * and "not recorded" is not the same claim as "no ground truth exists".
 * Rendering an unknown as "No" would assert something the registry never
 * said.
 */
export function GroundTruthStatus({
  hasGroundTruth,
  className,
}: {
  hasGroundTruth: boolean | null | undefined
  className?: string
}) {
  if (hasGroundTruth === null || hasGroundTruth === undefined) {
    return (
      <span
        data-ground-truth="unknown"
        className={cn('text-xs italic text-muted-foreground', className)}
      >
        not recorded
      </span>
    )
  }
  return (
    <span
      data-ground-truth={hasGroundTruth ? 'present' : 'absent'}
      className={cn(
        'inline-flex items-center gap-1.5 text-xs',
        hasGroundTruth ? 'text-success' : 'text-muted-foreground',
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          'size-1.5 rounded-full',
          hasGroundTruth ? 'bg-success' : 'bg-muted-foreground',
        )}
      />
      {hasGroundTruth ? 'Ground truth available' : 'No ground truth'}
    </span>
  )
}

/**
 * A position's status, with its reason when it has none.
 *
 * Renders coordinates only for a `geographic` position. Every other kind —
 * projected, site-local, odometry, none — is shown as a named,
 * *unmappable* state with an explanation, because none of them locates
 * anything on Earth without information the frame does not carry.
 */
export function CoordinateStatus({
  position,
  className,
  showCoordinates = true,
}: {
  position: Position | null | undefined
  className?: string
  showCoordinates?: boolean
}) {
  if (!position) {
    return (
      <span className={cn('text-xs italic text-muted-foreground', className)}>
        {NO_VALUE}
      </span>
    )
  }

  if (position.kind === 'geographic') {
    return (
      <span
        data-position-kind="geographic"
        className={cn('inline-flex items-baseline gap-2', className)}
      >
        <span className="rounded border border-success/30 bg-success/10 px-1.5 py-px text-[10px] font-medium uppercase tracking-wider text-success">
          geographic
        </span>
        {showCoordinates && (
          <code className="tabular font-mono text-xs text-foreground">
            {position.lat.toFixed(6)}, {position.lon.toFixed(6)}
          </code>
        )}
      </span>
    )
  }

  return (
    <span
      data-position-kind={position.kind}
      className={cn('inline-flex flex-col gap-1', className)}
    >
      <span className="inline-flex items-baseline gap-2">
        <span className="rounded border border-prov-unavailable/40 bg-prov-unavailable/10 px-1.5 py-px text-[10px] font-medium uppercase tracking-wider text-prov-unavailable">
          {position.kind}
        </span>
        <span className="text-[11px] text-muted-foreground">not mappable</span>
      </span>
      <span className="text-xs leading-relaxed text-muted-foreground">
        {positionUnavailableReason(position)}
      </span>
    </span>
  )
}

/**
 * A frame's declared spatial reference, with the provenance of that claim.
 *
 * `kind: "unknown"` and `crs_provenance: "none"` are common and honest
 * answers in this corpus, and a CRS that was *inferred* is a materially
 * weaker claim than one *declared by the source*. Showing the code without
 * showing how it was arrived at would flatten that difference.
 */
export function SpatialRefStatus({
  spatialRef,
  className,
}: {
  spatialRef: SpatialRefSummary | null | undefined
  className?: string
}) {
  if (!spatialRef) {
    return (
      <span className={cn('text-xs italic text-muted-foreground', className)}>
        no spatial reference declared
      </span>
    )
  }

  const code = spatialRef.code ?? null
  const kind = spatialRef.kind ?? 'unknown'

  return (
    <span className={cn('inline-flex flex-wrap items-center gap-2', className)}>
      <code className="font-mono text-xs text-foreground">
        {code ?? (kind === 'unknown' ? 'no CRS declared' : kind)}
      </code>
      <ProvenanceTag
        provenance={spatialRef.crs_provenance}
        basis={spatialRef.name}
        size="sm"
      />
    </span>
  )
}
