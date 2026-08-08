import { ApiError } from '@/services/api'
import { StateBox } from './state-box'
import { Skeleton } from '@/components/ui/skeleton'

/**
 * Renders the non-success outcomes of a request, or null when there is data.
 *
 * The distinction this exists to preserve: a 400 or 404 from Subterra is
 * usually a *statement about the data* -- "this dataset's records carry no
 * trace metadata, so there is no radargram" -- not a failure. Those render
 * as an explained absence, in the backend's own words. Only a real failure
 * (5xx, or the API being unreachable) renders as an error.
 *
 * Collapsing the two would either dress up a normal state as a fault, or
 * hide a genuine outage behind a shrug. Both mislead.
 */
export function QueryState({
  isLoading,
  error,
  absenceTitle = 'Not available',
  errorTitle = 'Request failed',
  skeletonRows = 2,
}: {
  isLoading: boolean
  error: unknown
  /** Heading for the "the backend says this cannot be shown" case. */
  absenceTitle?: string
  errorTitle?: string
  skeletonRows?: number
}) {
  if (isLoading) {
    return (
      <div className="space-y-2" aria-busy="true" aria-live="polite">
        {Array.from({ length: skeletonRows }).map((_, i) => (
          <Skeleton key={i} className="h-9 w-full" />
        ))}
        <span className="sr-only">Loading</span>
      </div>
    )
  }

  if (error instanceof ApiError) {
    return error.isAbsence ? (
      <StateBox kind="unavailable" title={absenceTitle} detail={error.detail} />
    ) : (
      <StateBox
        kind="error"
        title={errorTitle}
        detail={
          error.status === 0
            ? error.detail
            : `HTTP ${error.status} — ${error.detail}`
        }
      />
    )
  }

  if (error) {
    return <StateBox kind="error" title={errorTitle} detail={String(error)} />
  }

  return null
}
