'use client'

import { useState } from 'react'
import { useSWRConfig } from 'swr'
import { ApiError, api } from '@/services/api'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { formatPercent } from '@/lib/format'

/**
 * Correcting a stale quality score.
 *
 * WHAT STALE MEANS. The score stored on a dataset row was computed when the
 * dataset was ingested. The report recomputes it from the records as they are
 * now, and says so when the two disagree. Two of the datasets held disagree by
 * a lot — stored 0.30 against a computed 0.80 — because they were scored before
 * `NoPosition` replaced the `(0, 0)` placeholder, so they were being penalised
 * for coordinates their format never had.
 *
 * WHY THIS IS OFFERED AS A BUTTON AND `reprocess` IS NOT. `POST /reprocess`
 * re-runs the preprocessing pipeline and saves the result back — dewow, gain,
 * normalisation. It changes the measurements. Offering that as the fix for a
 * wrong number ABOUT the measurements would let a tidy-up quietly rewrite the
 * science. `POST /rescore` reads the records, runs the existing validator, and
 * writes one derived scalar; running it twice changes nothing the first run did
 * not. That is the whole reason it is safe to put behind a button.
 *
 * The copy says what it will and will not touch, because "Re-score" alone does
 * not distinguish it from the operation that would.
 */
export function RescoreAction({
  datasetId,
  storedScore,
  computedScore,
}: {
  datasetId: string
  storedScore: number | null
  computedScore: number | null
}) {
  const { mutate } = useSWRConfig()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  async function rescore() {
    setBusy(true)
    setError(null)
    try {
      await api.rescoreDataset(datasetId)
      await mutate(['dataset-report', datasetId])
      await mutate(['dataset-info', datasetId])
      await mutate('datasets')
      setDone(true)
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.detail
          : 'could not reach the Subterra API. Is the backend running?',
      )
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <p data-rescored className="mt-2 text-xs leading-relaxed text-muted-foreground">
        The stored score has been recomputed. No record, frame, label or source file
        was modified.
      </p>
    )
  }

  return (
    <div data-rescore className="mt-2">
      <p className="text-xs leading-relaxed text-muted-foreground">
        The stored score ({formatPercent(storedScore)}) does not match a fresh
        computation ({formatPercent(computedScore)}). The dataset changed after it was
        last scored — most often because the record schema improved, not because the
        data got worse.
      </p>
      <button
        type="button"
        data-action="rescore"
        disabled={busy}
        onClick={rescore}
        className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'mt-2')}
      >
        {busy ? 'Recomputing…' : 'Recompute score'}
      </button>
      <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
        Only the derived score is recomputed. Records, frames, labels and the original
        source file are not touched — this is not reprocessing.
      </p>
      {error && (
        <p
          data-action-error
          role="alert"
          className="mt-2 rounded-lg border border-destructive/40 px-3 py-2 text-xs leading-relaxed text-foreground"
        >
          {error}
        </p>
      )}
    </div>
  )
}
