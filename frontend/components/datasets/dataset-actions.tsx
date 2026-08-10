'use client'

import { useState } from 'react'
import { useSWRConfig } from 'swr'
import { ApiError, api } from '@/services/api'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { DatasetSummary, DeletionResult } from '@/types/subterra'

/**
 * Rename and delete, for one dataset.
 *
 * DELETION IS DELIBERATELY AWKWARD. The confirm step requires typing the
 * dataset's name, not clicking "OK". This is data somebody may have spent a day
 * acquiring and cannot be re-derived — a modal that a fast double-click can
 * dismiss is the wrong shape of control for it. Typing the name also forces a
 * look at WHICH dataset is selected, which is the mistake that actually
 * happens: not "I didn't mean to delete", but "I didn't mean to delete THAT
 * one". The corpus has two datasets with identical names for exactly this
 * reason, so the id is shown alongside.
 *
 * WHAT SURVIVES IS STATED BEFORE AND AFTER. The confirmation says the raw
 * source is kept; the result says what was actually removed. "Deleted" alone
 * would leave a user unsure whether their original file is gone, which for
 * scientific data is the difference between an inconvenience and a loss.
 *
 * SYSTEM DATASETS OFFER NEITHER ACTION. The backend refuses both with a 403;
 * rendering buttons that always fail would be a worse way to learn that.
 */
export function DatasetActions({
  dataset,
  onDeleted,
}: {
  dataset: DatasetSummary
  onDeleted?: () => void
}) {
  const { mutate } = useSWRConfig()
  const [mode, setMode] = useState<'idle' | 'renaming' | 'confirming'>('idle')
  const [name, setName] = useState(dataset.name)
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<DeletionResult | null>(null)

  if (dataset.is_system_dataset) {
    return (
      <p data-system-dataset className="text-xs leading-relaxed text-muted-foreground">
        Published reference data. Readable by everyone and modifiable by no one, so
        it cannot be renamed or deleted. Import your own copy to work on it.
      </p>
    )
  }

  function fail(err: unknown) {
    setError(
      err instanceof ApiError
        ? err.detail
        : 'could not reach the Subterra API. Is the backend running?',
    )
  }

  async function rename(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.renameDataset(dataset.id, name)
      // Both the list and this dataset's own views read the new name.
      await mutate('datasets')
      await mutate(['dataset-info', dataset.id])
      await mutate(['dataset-report', dataset.id])
      setMode('idle')
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    setError(null)
    try {
      // THE LIST IS NOT REFRESHED HERE, deliberately. Revalidating `datasets`
      // immediately removes this row from the DOM -- and this component lives
      // inside it, so the outcome panel below unmounts before anybody reads
      // it. The whole argument for reporting what was removed and what was
      // kept collapses if the report flashes for 200ms. Browser verification
      // caught exactly that. The refresh happens when the user dismisses.
      setResult(await api.deleteDataset(dataset.id))
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  async function dismiss() {
    await mutate('datasets')
    onDeleted?.()
  }

  if (result) {
    return (
      <div data-deleted className="text-xs leading-relaxed text-muted-foreground">
        <p className="text-foreground">Deleted.</p>
        <p className="mt-1">
          {result.removed.artifacts.length} derived artifact
          {result.removed.artifacts.length === 1 ? '' : 's'} removed
          {result.removed.fusion_samples > 0 &&
            `, ${result.removed.fusion_samples} fusion sample${
              result.removed.fusion_samples === 1 ? '' : 's'
            } removed`}
          .
        </p>
        {result.retained.raw_source && (
          <p className="mt-1" data-retained>
            The original source file was kept:{' '}
            <code className="font-mono text-[11px] text-foreground">
              {result.retained.raw_source}
            </code>
          </p>
        )}
        {result.retained.import_jobs > 0 && (
          <p className="mt-1">
            The record of {result.retained.import_jobs === 1 ? 'the' : 'each'} import
            was kept.
          </p>
        )}
        <button
          type="button"
          data-action="dismiss-deleted"
          onClick={dismiss}
          className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'mt-2.5')}
        >
          Dismiss
        </button>
      </div>
    )
  }

  return (
    <div className="text-xs">
      {mode === 'idle' && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            data-action="rename"
            onClick={() => {
              setName(dataset.name)
              setMode('renaming')
              setError(null)
            }}
            className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
          >
            Rename
          </button>
          <button
            type="button"
            data-action="delete"
            onClick={() => {
              setConfirmation('')
              setMode('confirming')
              setError(null)
            }}
            className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
          >
            Delete
          </button>
        </div>
      )}

      {mode === 'renaming' && (
        <form onSubmit={rename} data-rename-form className="space-y-2">
          <label
            htmlFor={`rename-${dataset.id}`}
            className="block font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground"
          >
            Dataset name
          </label>
          <input
            id={`rename-${dataset.id}`}
            value={name}
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          {/*
            Stated explicitly, because a user has no way to know it otherwise
            and the answer is the whole point of keeping the two separate.
          */}
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Only the display name changes. The dataset ID, the source file
            {dataset.source_file ? ` (${dataset.source_file})` : ''} and all provenance
            stay as they are.
          </p>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={busy}
              className={cn(buttonVariants({ variant: 'default', size: 'sm' }))}
            >
              {busy ? 'Saving…' : 'Save name'}
            </button>
            <button
              type="button"
              onClick={() => setMode('idle')}
              className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }))}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {mode === 'confirming' && (
        <div data-delete-confirm className="space-y-2">
          <p className="leading-relaxed text-foreground">
            Delete this dataset and everything derived from it?
          </p>
          <p className="leading-relaxed text-muted-foreground">
            Its records, survey frames, labels and resolved objects are removed and
            cannot be recovered. The original source file
            {dataset.source_file ? ` (${dataset.source_file})` : ''} is kept, and so is
            the record that it was imported.
          </p>
          <label
            htmlFor={`confirm-${dataset.id}`}
            className="block font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground"
          >
            Type the dataset name to confirm
          </label>
          <input
            id={`confirm-${dataset.id}`}
            value={confirmation}
            placeholder={dataset.name}
            onChange={(e) => setConfirmation(e.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          <div className="flex gap-2">
            <button
              type="button"
              data-action="confirm-delete"
              disabled={busy || confirmation.trim() !== dataset.name}
              onClick={remove}
              className={cn(
                buttonVariants({ variant: 'destructive', size: 'sm' }),
                'disabled:opacity-40',
              )}
            >
              {busy ? 'Deleting…' : 'Delete dataset'}
            </button>
            <button
              type="button"
              onClick={() => setMode('idle')}
              className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }))}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <p
          data-action-error
          role="alert"
          className="mt-2 rounded-lg border border-destructive/40 px-3 py-2 leading-relaxed text-foreground"
        >
          {error}
        </p>
      )}
    </div>
  )
}
