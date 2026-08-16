'use client'

import Link from 'next/link'
import { ArrowRight, RotateCcw } from 'lucide-react'
import { buttonVariants } from '@/components/ui/button'
import { QueryState } from '@/components/subterra/query-state'
import { useCandidates, useDatasetInfo } from '@/hooks/use-subterra'
import { NO_VALUE, formatCount, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ImportJob, SurveyFrameSummary } from '@/types/subterra'

/**
 * What arrived, and what did not.
 *
 * NOT "Upload successful!". A dataset that imported cleanly can still be
 * missing the things that decide what can be done with it -- a declared CRS, a
 * vertical datum, any geographic position at all. Reporting only success would
 * hand the user a green tick and let them discover in the workspace that half
 * the views are unavailable.
 *
 * So the report states each property as one of four things:
 *
 *   AVAILABLE     the platform has it
 *   MISSING       the data does not contain it
 *   NOT DECLARED  nobody stated it; it is not inferable
 *   BLOCKED       a gate refuses it for want of evidence
 *
 * Every value is read from `GET /api/datasets/{id}/info` and
 * `GET /api/candidates/{id}`. Nothing is computed here, and no field is
 * filled in from an assumption -- including the ones that are absent for
 * every dataset today (vertical datum, candidate generation). A fact that
 * happens to be constant across the corpus so far is still read, not
 * hardcoded, so the day it stops being constant this screen does not lie.
 */
type Status = 'AVAILABLE' | 'MISSING' | 'NOT DECLARED' | 'BLOCKED'

const TONE: Record<Status, string> = {
  AVAILABLE: 'text-prov-measured border-prov-measured/40',
  MISSING: 'text-muted-foreground border-border',
  'NOT DECLARED': 'text-prov-unavailable border-prov-unavailable/40',
  BLOCKED: 'text-destructive border-destructive/40',
}

function Row({
  label,
  value,
  status,
  note,
}: {
  label: string
  value?: string
  status?: Status
  note?: string
}) {
  return (
    <div
      data-report-row={label}
      className="grid gap-1 border-b border-border/60 py-2.5 sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)] sm:gap-4"
    >
      <dt className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </dt>
      <dd className="min-w-0">
        <span className="flex flex-wrap items-baseline gap-2">
          {value && <span className="tabular text-sm text-foreground">{value}</span>}
          {status && (
            <span
              data-status={status}
              className={cn(
                'rounded border px-1.5 py-px font-mono text-[10px] uppercase tracking-[0.14em]',
                TONE[status],
              )}
            >
              {status}
            </span>
          )}
        </span>
        {note && (
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{note}</p>
        )}
      </dd>
    </div>
  )
}

export function ImportReport({ job, onReset }: { job: ImportJob; onReset: () => void }) {
  const { data, error, isLoading } = useDatasetInfo(job.dataset_id ?? undefined)
  const { data: candidates } = useCandidates(job.dataset_id ?? undefined)

  // Slices 10-12's exact signal, reused verbatim: no second fetch (still the
  // same useCandidates hook), no composition parsing, no new API field.
  // MISSING means "the data does not contain it" in this screen's own
  // vocabulary -- the wrong word for an inapplicable GPR capability, which
  // is what this reason describes.
  const doesNotApply =
    candidates?.status === 'blocked' && candidates.status_reason.includes('does not apply')

  const positioned = data?.geographic_record_count ?? 0
  const total = data?.record_count ?? 0
  const crs = Array.isArray(data?.coordinate_system)
    ? data?.coordinate_system.join(', ')
    : data?.coordinate_system
  const crsDeclared = Boolean(crs && crs !== 'unknown')
  const issues = Array.isArray(
    (data?.processing_applied as { validation_issues?: unknown })?.validation_issues,
  )

  // Read straight off each stored SurveyFrame's vertical axis -- never
  // assumed. `vertical_datum` is a VerticalDatum object ({code, provenance,
  // name}), not a string: `code` may be set without a real declaration only
  // when provenance is "none", so both must hold for this to count as
  // declared (mirrors the dataset report's own extraction).
  const verticalDatums = (data?.survey_frames ?? [])
    .map(
      (f: SurveyFrameSummary) =>
        (f.vertical_axis as { vertical_datum?: { code?: string | null; provenance?: string } })
          ?.vertical_datum,
    )
    .filter((d): d is { code?: string | null; provenance?: string } =>
      Boolean(d?.code && d.provenance !== 'none'),
    )
    .map((d) => d.code as string)
  const verticalDatumDeclared = verticalDatums.length > 0
  const surveyFrameCount = data?.survey_frames?.length ?? 0

  return (
    <section data-import-report className="max-w-3xl">
      <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-prov-measured">
        Dataset ready
      </p>
      <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
        {data?.name ?? job.original_filename}
      </h2>

      <QueryState
        isLoading={isLoading}
        error={error}
        absenceTitle="Dataset details unavailable"
        errorTitle="Imported, but the dataset could not be read back"
        skeletonRows={4}
      />

      {data && (
        <>
          <dl className="mt-6 border-t border-border/60">
            <Row label="Source" value={job.original_filename ?? NO_VALUE} />
            <Row
              label="Format"
              value={data.original_format ?? job.detected_format ?? NO_VALUE}
            />
            <Row
              label="Records"
              value={formatCount(data.record_count)}
              status={total > 0 ? 'AVAILABLE' : 'MISSING'}
            />
            <Row
              label="Validation"
              value={issues ? 'report attached' : 'completed'}
              status="AVAILABLE"
              note="Coordinate, range and signal checks ran during import."
            />
            <Row
              label="Quality"
              value={
                data.quality_score === null ? NO_VALUE : formatPercent(data.quality_score)
              }
              status={data.quality_score === null ? 'MISSING' : 'AVAILABLE'}
            />
            <Row
              label="Positioned"
              value={`${formatCount(positioned)} of ${formatCount(total)}`}
              status={positioned > 0 ? 'AVAILABLE' : 'MISSING'}
              note={
                positioned === 0
                  ? 'No record carries a geographic position, so map, heatmap and surface views have nothing to place. The B-scan is indexed by trace and depth and is unaffected.'
                  : undefined
              }
            />
            <Row
              label="Coordinate frame"
              value={crsDeclared ? String(crs) : undefined}
              status={crsDeclared ? 'AVAILABLE' : 'NOT DECLARED'}
              note={
                crsDeclared
                  ? undefined
                  : 'No coordinate reference system is declared, so this layer cannot be related to another without a geo-tie.'
              }
            />
            <Row
              label="Vertical datum"
              value={verticalDatumDeclared ? verticalDatums.join(', ') : undefined}
              status={verticalDatumDeclared ? 'AVAILABLE' : 'NOT DECLARED'}
              note={
                verticalDatumDeclared
                  ? undefined
                  : 'No stored survey frame declares what its vertical axis is measured from. Elevation and radar travel time therefore stay separate quantities; the platform will not infer the offset.'
              }
            />
            <Row
              label="Survey frame"
              value={surveyFrameCount > 0 ? `${formatCount(surveyFrameCount)} stored` : undefined}
              status={surveyFrameCount > 0 ? 'AVAILABLE' : 'MISSING'}
              note={
                surveyFrameCount === 0
                  ? 'No survey frame was recorded for this import, so acquisition geometry and provenance are unavailable.'
                  : undefined
              }
            />
            <Row
              label="Candidates"
              value={
                candidates?.generation
                  ? `${formatCount(candidates.candidate_count)} candidate region(s)`
                  : undefined
              }
              status={
                doesNotApply
                  ? 'BLOCKED'
                  : !candidates?.generation
                    ? 'MISSING'
                    : candidates.status === 'blocked'
                      ? 'BLOCKED'
                      : 'AVAILABLE'
              }
              note={
                !candidates
                  ? 'Candidate detection has not been run for this dataset. It is a separate, explicit step from the dataset workspace, not something import performs.'
                  : candidates.status !== 'available'
                    ? candidates.status_reason
                    : undefined
              }
            />
            <Row
              label="Processing"
              value={data.last_preprocessing_mode ?? 'trace'}
              status="AVAILABLE"
              note={
                doesNotApply
                  ? 'Preprocessing ran at import.'
                  : 'Preprocessing ran at import. Candidates are generated on demand and are not detections.'
              }
            />
          </dl>

          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Link
              href={`/datasets/${encodeURIComponent(job.dataset_id as string)}`}
              className={buttonVariants({ variant: 'default', size: 'lg' })}
            >
              Open dataset
              <ArrowRight aria-hidden />
            </Link>
            {/*
              The report is the authoritative description of what was created --
              what it is, how far it can be trusted, and what Subterra may do
              with it next. Offered here because the question a person has just
              after an import is exactly the one it answers.
            */}
            <Link
              data-open-report
              href={`/datasets/${encodeURIComponent(job.dataset_id as string)}/report`}
              className={buttonVariants({ variant: 'outline', size: 'lg' })}
            >
              Open dataset report
            </Link>
            <button
              type="button"
              onClick={onReset}
              className={buttonVariants({ variant: 'outline', size: 'lg' })}
            >
              <RotateCcw aria-hidden />
              Import another
            </button>
          </div>
        </>
      )}
    </section>
  )
}

/**
 * Why it failed, and where.
 *
 * The backend's own message is rendered verbatim. A scientific tool that
 * replaces "Conversion failed: trace length does not divide the body exactly"
 * with "Something went wrong" has told the user nothing they can act on, and
 * has thrown away the one piece of information the platform actually had.
 */
export function ImportFailure({ job, onReset }: { job: ImportJob; onReset: () => void }) {
  return (
    <section data-import-failure className="max-w-3xl">
      <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-destructive">
        Import failed
      </p>
      <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
        {job.original_filename ?? 'Import'}
      </h2>

      <dl className="mt-6 border-t border-border/60">
        <Row label="Stage" value={job.error_stage ?? NO_VALUE} />
        <Row label="Filename" value={job.original_filename ?? NO_VALUE} />
        {job.detected_format && <Row label="Detected as" value={job.detected_format} />}
      </dl>

      <div className="subterra-hatch mt-5 rounded-lg border border-destructive/40 p-4">
        <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-destructive">
          Reason
        </p>
        <p
          data-error-message
          className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-foreground"
        >
          {job.error_message ?? 'The backend reported no message.'}
        </p>
      </div>

      <div className="mt-7">
        <button
          type="button"
          onClick={onReset}
          className={buttonVariants({ variant: 'outline', size: 'lg' })}
        >
          <RotateCcw aria-hidden />
          Try another dataset
        </button>
      </div>
    </section>
  )
}
