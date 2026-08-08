import { cn } from '@/lib/utils'
import { StateBox } from './state-box'
import { viewMeta } from '@/lib/format'
import type { ViewResolution } from '@/types/subterra'

/**
 * A view the backend could not resolve, rendered as a deliberate state.
 *
 * This is the component that keeps rule 4 and rule 5 true in the UI. When
 * `POST /api/views/resolve` returns `resolved: false`, the answer is not an
 * error and not an empty panel -- it is a specific, explained refusal, and
 * it is displayed as such.
 *
 * `scene_3d` is currently unresolved for every dataset the platform holds,
 * because absolute elevation needs a vertical registration that
 * `docs/vertical-reference-site01.md` established does not exist. That is
 * not a gap to paper over: a 3D scene drawn anyway would be fabricating the
 * one number the whole vertical investigation established we do not have.
 *
 * The reason and missing list come from the backend and are never
 * substituted, paraphrased or defaulted here. If the backend supplies no
 * reason, this says so rather than inventing one.
 */
export function UnavailableView({
  resolution,
  className,
}: {
  resolution: ViewResolution
  className?: string
}) {
  const meta = viewMeta[resolution.view]
  const label = meta?.label ?? resolution.view

  return (
    <div
      className={cn(
        'flex h-full w-full flex-col items-center justify-center p-6',
        className,
      )}
      data-view={resolution.view}
      data-resolved="false"
    >
      <div className="w-full max-w-md space-y-3">
        <StateBox
          kind="unavailable"
          title={`${label} — unavailable`}
          detail={
            resolution.reason ??
            'The backend reported this view as unresolved and supplied no reason.'
          }
          missing={resolution.missing}
        />
        {meta && (
          <p className="px-1 text-xs leading-relaxed text-muted-foreground">
            <span className="font-medium text-foreground">{label}</span> requires{' '}
            {meta.requires}.
          </p>
        )}
      </div>
    </div>
  )
}
