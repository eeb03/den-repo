'use client'

import { useMemo, useState } from 'react'
import useSWR from 'swr'
import { ApiError, api } from '@/services/api'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { formatCount } from '@/lib/format'
import { RadargramCanvas, RadargramScale } from './radargram-canvas'
import type {
  CandidateIntelligence,
  CandidateFootprint,
  InspectableCandidate,
  RadargramField,
  TraceGrid,
} from '@/types/subterra'

/**
 * The two representations a reviewer can look at.
 *
 * `signal` is what the record holds now — after local-anomaly preprocessing,
 * the z-score. `pre_anomaly_signal` is what that same cell held immediately
 * before. Both are projections of the SAME records onto the SAME grid, so
 * switching cannot move a candidate or change an axis.
 *
 * The labels shown come from the backend's semantics, not from this list: what
 * a projection MEANS is a scientific statement and belongs where it is tested.
 */
const DISPLAY_MODES: { field: RadargramField; short: string }[] = [
  { field: 'signal', short: 'Local-anomaly z-score' },
  { field: 'pre_anomaly_signal', short: 'Pre-anomaly signal' },
]

/**
 * Radargram inspection — the measured signal, with candidates on it.
 *
 * WHY THIS SCREEN EXISTS. Candidate intelligence could already say
 * "Path8.sgy · traces 301–302, score 4.85". Nobody can inspect that. A reviewer
 * asked to accept or reject a candidate needs to see the region it came from,
 * and until this screen there was no way to. The review states have existed
 * since Stage 13 and recorded a judgement the user had no means to form.
 *
 * TWO REQUESTS, DELIBERATELY. The grid arrives first and is rendered
 * immediately; candidate detail follows. The measured signal is the primary
 * content and should not wait on the detector's output — and if candidate
 * retrieval fails, a radargram with no overlays is still a true picture,
 * whereas a blank page would be no picture at all. The overlay state is stated
 * while it loads so an empty radargram is never mistaken for one with nothing
 * on it.
 *
 * EVERY LABEL COMES FROM THE BACKEND'S SEMANTICS. The vertical axis is called
 * whatever `semantics.vertical.label` says — "Two-way time", "Derived depth
 * (default velocity)", "Sample" — and its caveat is printed beside it. This
 * component contains no rule for deciding what an axis means, because that
 * decision is a scientific claim and belongs where it can be tested.
 */
export function RadargramInspector({ datasetId }: { datasetId: string }) {
  const [selectedLine, setSelectedLine] = useState<string | null>(null)
  // Defaults to the anomaly view: the candidates were found in it, and
  // changing what a reviewer sees first is not this toggle's job.
  const [field, setField] = useState<RadargramField>('signal')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showUnreliable, setShowUnreliable] = useState(true)
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [reviewing, setReviewing] = useState(false)

  const gridQuery = useSWR<TraceGrid>(
    ['trace-grid', datasetId, selectedLine, field],
    () =>
      api.getTraceGrid(datasetId, {
        field,
        sourceFile: selectedLine,
        reliability: true,
        candidateFootprints: true,
      }),
    // `keepPreviousData` holds the current image on screen while the other
    // projection loads, so a toggle does not blank the radargram.
    { revalidateOnFocus: false, keepPreviousData: true },
  )

  /*
   * DEFERRED UNTIL THE GRID HAS LANDED, and measured rather than assumed.
   * Both endpoints deserialise every record in the dataset. Fired together
   * against a 160,768-record line they took 66 s each; run one after the other
   * they take 12 s and 17 s. The contention is superlinear because two full
   * record sets are resident at once, so the fix is to not do that -- which
   * also matches what this screen is for: the measured signal is the primary
   * content and should be on screen before the detector's output is asked for.
   */
  const candidateQuery = useSWR<CandidateIntelligence>(
    gridQuery.data ? ['candidates', datasetId] : null,
    () => api.getCandidates(datasetId),
    { revalidateOnFocus: false },
  )

  const grid = gridQuery.data
  const footprints: CandidateFootprint[] = useMemo(
    () => grid?.candidate_footprints ?? [],
    [grid],
  )
  const byId = useMemo(() => {
    const map = new Map<string, InspectableCandidate>()
    for (const c of candidateQuery.data?.candidates ?? []) map.set(c.candidate.id, c)
    return map
  }, [candidateQuery.data])

  const selected = selectedId ? byId.get(selectedId) ?? null : null
  const selectedFootprint = selectedId
    ? footprints.find((f) => f.candidate_id === selectedId) ?? null
    : null

  async function review(status: 'accepted' | 'rejected') {
    if (!selectedId) return
    setReviewing(true)
    setReviewError(null)
    try {
      await api.reviewCandidate(datasetId, selectedId, status)
      await candidateQuery.mutate()
    } catch (err) {
      setReviewError(
        err instanceof ApiError
          ? err.detail
          : 'could not reach the Subterra API. Is the backend running?',
      )
    } finally {
      setReviewing(false)
    }
  }

  if (gridQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading the measured radargram…</p>
  }

  if (gridQuery.error || !grid) {
    // An absent trace grid is a legitimate state: not every dataset is a
    // multi-sample survey line. Say which, using the backend's own reason.
    const detail =
      gridQuery.error instanceof ApiError
        ? gridQuery.error.detail
        : 'Could not load the trace grid for this dataset.'
    return (
      <div data-radargram-unavailable className="space-y-2">
        <h2 className="text-base font-medium text-foreground">Radargram inspection</h2>
        <p className="text-xs leading-relaxed text-muted-foreground">{detail}</p>
      </div>
    )
  }

  const semantics = grid.semantics
  const vertical = semantics?.vertical
  const horizontal = semantics?.horizontal
  const fieldSemantics = semantics?.field
  const lines = grid.available_source_files ?? []
  // Defaults to true so a backend that has not yet been updated keeps Stage 15's
  // behaviour rather than silently un-fading unreliable cells.
  const reliabilityApplies = fieldSemantics?.reliability_applies !== false
  const unplaceable = footprints.filter((f) => !f.placeable)

  const domain = (() => {
    let max = 0
    for (const row of grid.grid) {
      for (const v of row) {
        if (v === null || !Number.isFinite(v)) continue
        if (Math.abs(v) > max) max = Math.abs(v)
      }
    }
    return max
  })()

  return (
    <div data-radargram-inspector className="space-y-4">
      <header className="space-y-1">
        <h2 className="text-base font-medium text-foreground">Radargram inspection</h2>
        <p className="text-xs text-muted-foreground">
          {String(grid.name ?? '')} · {grid.source_file}
        </p>
      </header>

      {/*
        WHAT YOU ARE LOOKING AT. Placed above the image: a reader who scrolls
        straight to the picture must already know that these are z-scores and
        that the vertical axis is not a measured depth.
      */}
      <section
        data-radargram-semantics
        className="rounded-lg border border-border px-4 py-3 text-xs leading-relaxed"
      >
        <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-3">
          <Field label="Values">
            <span data-field-label>{fieldSemantics?.label ?? 'unknown'}</span>
            {fieldSemantics?.units ? ` (${fieldSemantics.units})` : ''}
          </Field>
          <Field label="Vertical axis">
            <span data-vertical-label>{vertical?.label ?? 'unknown'}</span>
            {vertical?.units ? ` (${vertical.units})` : ''}
          </Field>
          <Field label="Horizontal axis">
            <span data-horizontal-label>{horizontal?.label ?? 'unknown'}</span>
          </Field>
        </dl>

        {fieldSemantics?.description && (
          <p data-field-description className="mt-2 text-muted-foreground">
            {fieldSemantics.description}
          </p>
        )}

        {/* The derived-axis caveat is never optional when the axis is derived. */}
        {vertical?.is_derived && vertical.caveat && (
          <p data-vertical-caveat className="mt-2 text-foreground">
            {vertical.caveat}
          </p>
        )}

        {!horizontal?.geographic_available && (
          <p data-no-georeference className="mt-2 text-muted-foreground">
            No geographic registration: this view is trace-relative. {horizontal?.basis}.
          </p>
        )}
      </section>

      {/*
        THE DISPLAY-MODE TOGGLE. It changes which stored value is projected into
        each cell and nothing else -- not the grid, not the axes, not the
        candidate footprints. `keepPreviousData` leaves the current image up
        while the other projection loads, so the toggle never blanks the view.
      */}
      <div className="flex flex-wrap items-center gap-2 text-xs" data-display-modes>
        <span className="text-muted-foreground">Showing:</span>
        {DISPLAY_MODES.map((mode) => (
          <button
            key={mode.field}
            type="button"
            data-display-mode={mode.field}
            data-selected={mode.field === field ? 'true' : 'false'}
            aria-pressed={mode.field === field}
            onClick={() => setField(mode.field)}
            className={cn(
              buttonVariants({
                variant: mode.field === field ? 'default' : 'ghost',
                size: 'sm',
              }),
            )}
          >
            {mode.short}
          </button>
        ))}
        {gridQuery.isValidating && (
          <span data-mode-loading className="text-muted-foreground">
            loading…
          </span>
        )}
      </div>

      {lines.length > 1 && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">Survey line:</span>
          {lines.map((line) => (
            <button
              key={line}
              type="button"
              data-line-option={line}
              onClick={() => {
                setSelectedLine(line)
                setSelectedId(null)
              }}
              className={cn(
                buttonVariants({ variant: line === grid.source_file ? 'default' : 'ghost', size: 'sm' }),
              )}
            >
              {line}
            </button>
          ))}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-2">
          <div className="overflow-x-auto">
            <RadargramCanvas
              grid={grid}
              footprints={footprints}
              selectedId={selectedId}
              onSelect={setSelectedId}
              showUnreliable={showUnreliable && reliabilityApplies}
            />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <RadargramScale
              domain={domain}
              units={fieldSemantics?.units ?? null}
              label={fieldSemantics?.label ?? ''}
            />
            {reliabilityApplies && (
              <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
                <input
                  type="checkbox"
                  data-toggle-unreliable
                  checked={showUnreliable}
                  onChange={(e) => setShowUnreliable(e.target.checked)}
                />
                Fade unreliable cells
              </label>
            )}
          </div>

          {/* Missing and unreliable, stated as counts rather than left to the eye. */}
          <p data-cell-quality className="text-[11px] leading-relaxed text-muted-foreground">
            {semantics?.unreliable_cells !== null && semantics?.unreliable_cells !== undefined
              ? `${formatCount(semantics.unreliable_cells)} of ${formatCount(
                  semantics.total_cells ?? 0,
                )} cells are unreliable. ${semantics.reliability_note}`
              : 'No reliability information is available for this dataset.'}{' '}
            {semantics?.missing_note}
          </p>

          {/*
            The mask marks cells whose RING had too few neighbours, which is a
            property of the anomaly statistic. In the pre-anomaly view those
            same cells hold perfectly good stored values, so fading them would
            present sound measurements as untrustworthy.
          */}
          {!reliabilityApplies && fieldSemantics?.reliability_note && (
            <p
              data-reliability-not-applicable
              className="text-[11px] leading-relaxed text-muted-foreground"
            >
              Not faded here: {fieldSemantics.reliability_note}.
            </p>
          )}
        </div>

        <aside className="min-w-0 space-y-3">
          <CandidateList
            footprints={footprints}
            byId={byId}
            selectedId={selectedId}
            onSelect={setSelectedId}
            loading={candidateQuery.isLoading}
            failed={Boolean(candidateQuery.error)}
          />

          {unplaceable.length > 0 && (
            <div data-unplaceable className="rounded-lg border border-border px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
              <p className="text-foreground">
                {unplaceable.length} candidate(s) cannot be placed on this grid.
              </p>
              {unplaceable.map((f) => (
                <p key={f.candidate_id} data-unplaceable-reason className="mt-1">
                  {f.reason}
                </p>
              ))}
            </div>
          )}

          {selected && (
            <EvidencePanel
              candidate={selected}
              footprint={selectedFootprint}
              intelligence={candidateQuery.data ?? null}
              onReview={review}
              reviewing={reviewing}
              error={reviewError}
            />
          )}
        </aside>
      </div>
    </div>
  )
}

function CandidateList({
  footprints,
  byId,
  selectedId,
  onSelect,
  loading,
  failed,
}: {
  footprints: CandidateFootprint[]
  byId: Map<string, InspectableCandidate>
  selectedId: string | null
  onSelect: (id: string | null) => void
  loading: boolean
  failed: boolean
}) {
  if (loading) {
    return (
      <p data-candidates-loading className="text-xs text-muted-foreground">
        Loading candidates. The radargram above is complete; overlays will appear when
        the candidate set arrives.
      </p>
    )
  }
  if (failed) {
    return (
      <p data-candidates-failed role="alert" className="text-xs text-muted-foreground">
        Could not load candidates. The radargram above is the measured signal and is
        unaffected; no overlay is shown because none could be retrieved.
      </p>
    )
  }
  if (footprints.length === 0) {
    return (
      <p data-no-candidates className="text-xs leading-relaxed text-muted-foreground">
        No candidates on this survey line. That is a result, not a failure: no region
        satisfied the generation rule.
      </p>
    )
  }

  return (
    <div className="space-y-1">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        Candidates on this line
      </p>
      <ul className="space-y-1">
        {footprints.map((f) => {
          const candidate = byId.get(f.candidate_id)
          return (
            <li key={f.candidate_id}>
              <button
                type="button"
                data-candidate-row={f.candidate_id}
                disabled={!f.placeable}
                onClick={() => onSelect(f.candidate_id === selectedId ? null : f.candidate_id)}
                className={cn(
                  'w-full rounded-md border px-2 py-1.5 text-left text-xs',
                  f.candidate_id === selectedId
                    ? 'border-primary text-foreground'
                    : 'border-border text-muted-foreground',
                  !f.placeable && 'opacity-50',
                )}
              >
                <span className="block truncate">
                  {f.placeable
                    ? `Traces ${f.first_column}–${f.last_column}, rows ${f.first_row}–${f.last_row}`
                    : 'Not placeable on this grid'}
                </span>
                {candidate && (
                  <span className="block font-mono text-[10px]">
                    score {candidate.candidate_score.toFixed(2)} ·{' '}
                    {candidate.candidate.interpretation.anomaly_class} · {candidate.status}
                  </span>
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/**
 * One candidate's evidence, and the two things a reviewer may do about it.
 *
 * ACCEPT DOES NOT PROMOTE. The wording under the buttons is the backend's own
 * contract: a review records what a reviewer thought worth retaining. It does
 * not make the candidate a detection, an object, or ground truth, and this
 * panel says so next to the button rather than in documentation.
 */
function EvidencePanel({
  candidate,
  footprint,
  intelligence,
  onReview,
  reviewing,
  error,
}: {
  candidate: InspectableCandidate
  footprint: CandidateFootprint | null
  intelligence: CandidateIntelligence | null
  onReview: (status: 'accepted' | 'rejected') => void
  reviewing: boolean
  error: string | null
}) {
  const e = candidate.candidate.evidence
  const generation = intelligence?.generation
  return (
    <div data-evidence-panel className="space-y-3 rounded-lg border border-border px-3 py-3 text-xs">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        Candidate evidence
      </p>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
        <Field label="Source file">{e.source_file}</Field>
        <Field label="Traces">
          {e.trace_range[0]}–{e.trace_range[1]}
        </Field>
        <Field label="Supporting cells">{formatCount(e.n_supporting_cells)}</Field>
        <Field label="Peak |z|">{Math.abs(e.peak_value).toFixed(2)}</Field>
        <Field label="Shape class">{candidate.candidate.interpretation.anomaly_class}</Field>
        <Field label="Grid rows">
          {footprint?.placeable ? `${footprint.first_row}–${footprint.last_row}` : 'not placeable'}
        </Field>
      </dl>

      <div className="leading-relaxed text-muted-foreground">
        <p className="text-foreground">Position: {candidate.localisation}</p>
        <p data-evidence-localisation>{candidate.localisation_basis}.</p>
      </div>
      <div className="leading-relaxed text-muted-foreground">
        <p className="text-foreground">Depth: {candidate.depth}</p>
        <p data-evidence-depth>{candidate.depth_basis}.</p>
      </div>

      <p data-evidence-score className="leading-relaxed text-muted-foreground">
        {candidate.candidate_score_meaning}
      </p>

      <p data-evidence-classification className="leading-relaxed text-muted-foreground">
        Object classification: {candidate.classification_status}.{' '}
        {candidate.classification_blocked_reason}.
      </p>

      {generation && (
        <p data-evidence-provenance className="leading-relaxed text-muted-foreground">
          Generated by {generation.method} v{generation.method_version} · |z| &gt;{' '}
          {generation.parameters.threshold}, min {generation.parameters.min_cells} cells.
        </p>
      )}

      {intelligence?.staleness.is_stale && (
        <p data-evidence-stale className="leading-relaxed text-foreground">
          This candidate set no longer matches the dataset:{' '}
          {intelligence.staleness.reasons.join('; ')}.
        </p>
      )}

      {intelligence?.benchmark.adequacy && (
        <p data-evidence-benchmark className="leading-relaxed text-muted-foreground">
          {intelligence.benchmark.adequacy}
        </p>
      )}

      <div className="space-y-1.5 border-t border-border pt-2">
        <div className="flex gap-2">
          <button
            type="button"
            data-action="accept-candidate"
            disabled={reviewing}
            onClick={() => onReview('accepted')}
            className={cn(buttonVariants({ variant: 'default', size: 'sm' }))}
          >
            {reviewing ? 'Recording…' : 'Accept'}
          </button>
          <button
            type="button"
            data-action="reject-candidate"
            disabled={reviewing}
            onClick={() => onReview('rejected')}
            className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }))}
          >
            Reject
          </button>
        </div>
        <p data-review-meaning className="leading-relaxed text-muted-foreground">
          A review records what a reviewer thought worth retaining. It does not make this
          candidate a detection, an object, or ground truth.
        </p>
        {error && (
          <p data-review-error role="alert" className="text-foreground">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 text-foreground">{children}</dd>
    </div>
  )
}
