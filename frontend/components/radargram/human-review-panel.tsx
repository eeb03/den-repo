'use client'

import { useEffect, useState } from 'react'
import useSWR from 'swr'
import { ApiError, api } from '@/services/api'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { AnnotationGeometry, CandidateReview, ReviewStatus } from '@/types/subterra'

function geometrySummary(g: AnnotationGeometry): string {
  return g.kind === 'rectangle'
    ? `Rectangle: traces ${g.trace_start}–${g.trace_end}, samples ${g.sample_start}–${g.sample_end}`
    : `Ridge: ${g.trace_indices.length} point(s)`
}

/**
 * Human-in-the-Loop Anomaly Verification V1.
 *
 * DELIBERATELY SEPARATE FROM `EvidencePanel`'s existing Accept/Reject
 * controls. Those answer "is this candidate worth retaining in the list"
 * (`CandidateStatus`, unchanged by this milestone). This panel answers a
 * different question -- "does this represent genuine radar evidence, and
 * what does a human call it" -- and keeps its own vocabulary
 * (`ReviewStatus`: confirmed/rejected/uncertain) so the two are never
 * collapsed into one meaning.
 *
 * A REVIEW NEVER PROMOTES. Every response from this panel prints the
 * backend's own disclaimer verbatim -- see `note`/`ground_truth_status`
 * below -- because this is the one place a reviewer's honest "yes, real"
 * could most easily be read as "Subterra detected this".
 */

const OPERATOR_LABELS: { value: string; label: string }[] = [
  { value: '', label: '(none — real, but unidentified)' },
  { value: 'pipe', label: 'Pipe' },
  { value: 'cable', label: 'Cable' },
  { value: 'void', label: 'Void' },
  { value: 'layer_interface', label: 'Layer / interface' },
  { value: 'geological_feature', label: 'Geological feature' },
  { value: 'buried_object', label: 'Buried object' },
  { value: 'unknown', label: 'Unknown' },
  { value: 'other', label: 'Other' },
]

const STATUS_LABEL: Record<ReviewStatus, string> = {
  unreviewed: 'Unreviewed',
  confirmed: 'Confirmed',
  rejected: 'Rejected',
  uncertain: 'Uncertain',
}

export function HumanReviewPanel({
  datasetId,
  candidateId,
  annotationGeometry = null,
  onSaved,
}: {
  datasetId: string
  candidateId: string
  /** A geometry drawn on the canvas (Section 6/18), controlled by the parent -- `null` means "no marked region", the existing, still-valid Section 4 state. */
  annotationGeometry?: AnnotationGeometry | null
  onSaved?: () => void
}) {
  const { data, error, isLoading, mutate } = useSWR<CandidateReview>(
    ['candidate-review', datasetId, candidateId],
    async () => {
      try {
        return await api.getCandidateReview(datasetId, candidateId)
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null as unknown as CandidateReview
        throw err
      }
    },
    { revalidateOnFocus: false },
  )

  const [status, setStatus] = useState<ReviewStatus>('unreviewed')
  const [operatorLabel, setOperatorLabel] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    if (data) {
      setStatus(data.review_status)
      setOperatorLabel(data.operator_label ?? '')
      setNotes(data.notes ?? '')
    }
  }, [data])

  async function save(nextStatus: ReviewStatus) {
    setSaving(true)
    setSaveError(null)
    try {
      const saved = await api.submitCandidateReview(datasetId, candidateId, {
        review_status: nextStatus,
        operator_label: operatorLabel || null,
        notes: notes || null,
        annotation_geometry: annotationGeometry,
      })
      setStatus(saved.review_status)
      await mutate(saved, { revalidate: false })
      onSaved?.()
    } catch (err) {
      setSaveError(
        err instanceof ApiError ? err.detail : 'could not reach the Subterra API.',
      )
    } finally {
      setSaving(false)
    }
  }

  if (isLoading) {
    return <p className="text-xs text-muted-foreground">Loading review…</p>
  }
  if (error) {
    return (
      <p role="alert" className="text-xs text-muted-foreground">
        Could not load the human review for this candidate.
      </p>
    )
  }

  return (
    <div data-human-review-panel className="space-y-3 rounded-lg border border-border px-3 py-3 text-xs">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        Human review
      </p>

      {data && data.review_status !== 'unreviewed' && (
        <p data-current-review-status className="text-foreground">
          Current: {STATUS_LABEL[data.review_status]}
          {data.operator_label ? ` · ${data.operator_label}` : ' · no identity claimed'}
          {data.history.length > 0 ? ` · ${data.history.length} prior revision(s)` : ''}
          {data.annotation_geometry ? ` · ${geometrySummary(data.annotation_geometry)}` : ''}
        </p>
      )}

      {annotationGeometry && (
        <p data-pending-geometry className="text-foreground">
          Will save with: {geometrySummary(annotationGeometry)}
        </p>
      )}

      <div className="flex flex-wrap gap-2" data-review-status-controls>
        {(['confirmed', 'uncertain', 'rejected'] as ReviewStatus[]).map((s) => (
          <button
            key={s}
            type="button"
            data-action={`review-${s}`}
            disabled={saving}
            aria-pressed={status === s}
            onClick={() => {
              setStatus(s)
              void save(s)
            }}
            className={cn(
              buttonVariants({ variant: status === s ? 'default' : 'ghost', size: 'sm' }),
            )}
          >
            {saving && status === s ? 'Saving…' : STATUS_LABEL[s]}
          </button>
        ))}
      </div>

      <label className="block space-y-1">
        <span className="block text-[11px] text-muted-foreground">
          Optional identity — a human interpretation, never a detection
        </span>
        <select
          data-operator-label
          value={operatorLabel}
          onChange={(e) => setOperatorLabel(e.target.value)}
          className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs"
        >
          {OPERATOR_LABELS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      <label className="block space-y-1">
        <span className="block text-[11px] text-muted-foreground">Notes</span>
        <textarea
          data-review-notes
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs"
        />
      </label>

      <button
        type="button"
        data-action="save-review"
        disabled={saving}
        onClick={() => void save(status === 'unreviewed' ? 'confirmed' : status)}
        className={cn(buttonVariants({ variant: 'default', size: 'sm' }))}
      >
        {saving ? 'Saving…' : 'Save review'}
      </button>

      <p data-review-disclaimer className="leading-relaxed text-muted-foreground">
        A review records a human judgement about real evidence. It does not make this
        candidate a detection, an object, or independently validated ground truth.
      </p>

      {saveError && (
        <p data-review-error role="alert" className="text-foreground">
          {saveError}
        </p>
      )}
    </div>
  )
}

/**
 * Section 12: a candidate-INDEPENDENT annotation for a real event the
 * detector never proposed. A numeric trace-range input, not a canvas
 * click-drag interaction -- see this milestone's own final report for why:
 * this is temporary development infrastructure, and a working, honest
 * numeric form carries materially less risk to the existing, tested
 * `RadargramCanvas` than adding freehand/drag interaction to it would.
 */
export function MissedEventForm({
  datasetId,
  sourceFile,
  annotationGeometry = null,
  onSaved,
}: {
  datasetId: string
  sourceFile: string
  /** When present, the trace range is DERIVED from the drawing, not typed -- the manual inputs below become read-only. */
  annotationGeometry?: AnnotationGeometry | null
  onSaved?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [traceStart, setTraceStart] = useState('')
  const [traceEnd, setTraceEnd] = useState('')
  const [status, setStatus] = useState<'confirmed' | 'uncertain'>('confirmed')
  const [operatorLabel, setOperatorLabel] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedId, setSavedId] = useState<string | null>(null)

  const geometryRange: [number, number] | null =
    annotationGeometry?.kind === 'rectangle' &&
    annotationGeometry.trace_start != null && annotationGeometry.trace_end != null
      ? [annotationGeometry.trace_start, annotationGeometry.trace_end]
      : annotationGeometry?.kind === 'ridge_path' && annotationGeometry.trace_indices.length > 0
        ? [Math.min(...annotationGeometry.trace_indices), Math.max(...annotationGeometry.trace_indices)]
        : null

  async function submit() {
    const start = geometryRange ? geometryRange[0] : Number(traceStart)
    const end = geometryRange ? geometryRange[1] : Number(traceEnd)
    if (!Number.isFinite(start) || !Number.isFinite(end) || start > end) {
      setError('trace start/end must be numbers, with start ≤ end')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const saved = await api.createMissedEvent(datasetId, {
        source_file: sourceFile,
        trace_range: [start, end],
        review_status: status,
        operator_label: operatorLabel || null,
        notes: notes || null,
        annotation_geometry: annotationGeometry,
      })
      setSavedId(saved.id)
      onSaved?.()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'could not reach the Subterra API.')
    } finally {
      setSaving(false)
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        data-action="open-missed-event-form"
        onClick={() => setOpen(true)}
        className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }), 'w-full')}
      >
        + Add a missed event (real evidence the detector did not flag)
      </button>
    )
  }

  return (
    <div data-missed-event-form className="space-y-2 rounded-lg border border-border px-3 py-3 text-xs">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        Missed-event annotation — {sourceFile}
      </p>
      <p className="leading-relaxed text-muted-foreground">
        Use this only for a real event you can see in the radargram above that has no
        candidate marker. {geometryRange
          ? 'The trace range below comes from what you drew.'
          : 'Enter the exact trace range the event spans, or draw it above.'}
      </p>

      {annotationGeometry && (
        <p data-pending-geometry className="text-foreground">
          {geometrySummary(annotationGeometry)}
        </p>
      )}

      <div className="flex gap-2">
        <label className="flex-1 space-y-1">
          <span className="block text-[11px] text-muted-foreground">Trace start</span>
          <input
            type="number"
            data-missed-trace-start
            value={geometryRange ? geometryRange[0] : traceStart}
            disabled={Boolean(geometryRange)}
            onChange={(e) => setTraceStart(e.target.value)}
            className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs disabled:opacity-60"
          />
        </label>
        <label className="flex-1 space-y-1">
          <span className="block text-[11px] text-muted-foreground">Trace end</span>
          <input
            type="number"
            data-missed-trace-end
            value={geometryRange ? geometryRange[1] : traceEnd}
            disabled={Boolean(geometryRange)}
            onChange={(e) => setTraceEnd(e.target.value)}
            className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs disabled:opacity-60"
          />
        </label>
      </div>

      <div className="flex gap-2" data-missed-status-controls>
        {(['confirmed', 'uncertain'] as const).map((s) => (
          <button
            key={s}
            type="button"
            data-action={`missed-${s}`}
            aria-pressed={status === s}
            onClick={() => setStatus(s)}
            className={cn(buttonVariants({ variant: status === s ? 'default' : 'ghost', size: 'sm' }))}
          >
            {STATUS_LABEL[s]}
          </button>
        ))}
      </div>

      <select
        data-missed-operator-label
        value={operatorLabel}
        onChange={(e) => setOperatorLabel(e.target.value)}
        className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs"
      >
        {OPERATOR_LABELS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>

      <textarea
        data-missed-notes
        placeholder="Why this looks like a real event"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        rows={2}
        className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs"
      />

      <div className="flex gap-2">
        <button
          type="button"
          data-action="save-missed-event"
          disabled={saving}
          onClick={() => void submit()}
          className={cn(buttonVariants({ variant: 'default', size: 'sm' }))}
        >
          {saving ? 'Saving…' : 'Create missed-event annotation'}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }))}
        >
          Cancel
        </button>
      </div>

      {savedId && (
        <p data-missed-event-saved className="text-foreground">
          Saved. This is a candidate-independent annotation, not a detection.
        </p>
      )}
      {error && (
        <p data-missed-event-error role="alert" className="text-foreground">
          {error}
        </p>
      )}
    </div>
  )
}
