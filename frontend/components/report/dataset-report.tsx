'use client'

import Link from 'next/link'
import { Panel, PanelBody, PanelHeader, Field, SectionLabel } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { useDatasetReport } from '@/hooks/use-subterra'
import { NO_VALUE, formatCount, formatDateTime, formatPercent } from '@/lib/format'
import type { DatasetReport as Report } from '@/types/subterra'
import { CapabilityRow } from './readiness'

/**
 * The Dataset Report.
 *
 * WHAT THIS SCREEN IS FOR. Not "here is everything we know" -- that is a
 * dashboard, and a dashboard is where a limitation goes to be overlooked. This
 * answers one question in order: what is this, what happened to it, how far can
 * it be trusted, and what may Subterra legitimately do with it next. The
 * readiness section is deliberately FIRST after the summary, because it is the
 * answer people actually came for.
 *
 * IT RENDERS THE BACKEND'S WORDS. Every reason and every "requires" line is
 * the API's own sentence, not a local paraphrase. A UI that rewords a
 * scientific limitation eventually softens it -- "vertical datum not declared"
 * becomes "some metadata missing" -- and the softened version is what people
 * remember.
 *
 * NOTHING IS COMPUTED HERE. No score is derived, no coordinate is formatted
 * into a position, no absence is filled with a default. `NO_VALUE` renders an
 * em dash where the backend declared nothing, and the identity section lists
 * what was undeclared by name so a blank cannot be mistaken for a zero.
 */
export function DatasetReportView({ datasetId }: { datasetId: string }) {
  const { data, error, isLoading } = useDatasetReport(datasetId)

  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-10">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Dataset report
          </p>
          <h1 className="mt-1 text-xl font-semibold tracking-tight text-foreground">
            {data?.identity.name ?? datasetId}
          </h1>
        </div>
        <Link
          href={`/datasets/${encodeURIComponent(datasetId)}`}
          className="shrink-0 text-xs text-primary underline-offset-4 hover:underline"
        >
          Open workspace
        </Link>
      </div>

      <QueryState
        isLoading={isLoading}
        error={error}
        absenceTitle="No report available"
        errorTitle="Could not load the dataset report"
        skeletonRows={6}
      />

      {data && (
        <div className="mt-8 space-y-5">
          <ReadinessSection report={data} />
          <SpatialSection report={data} />
          <IdentitySection report={data} />
          <DataSection report={data} />
          <QualitySection report={data} />
          <ProcessingSection report={data} />
          <CandidateSection report={data} />
        </div>
      )}
    </main>
  )
}

function Section({
  title,
  children,
  note,
}: {
  title: string
  children: React.ReactNode
  note?: string
}) {
  return (
    <Panel>
      <PanelHeader title={title} />
      <PanelBody>
        {note && (
          <p className="mb-3 text-xs leading-relaxed text-muted-foreground">{note}</p>
        )}
        {children}
      </PanelBody>
    </Panel>
  )
}

/**
 * What Subterra can legitimately do with this dataset right now.
 *
 * Placed first on purpose. Everything below it is the evidence for what this
 * section says.
 */
function ReadinessSection({ report }: { report: Report }) {
  const blocked = report.readiness.filter((c) => c.readiness === 'blocked').length
  return (
    <Panel>
      <PanelHeader title="What Subterra can do with this" />
      <PanelBody>
        <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
          Readiness is <em>capability</em>, not completion: &ldquo;ready&rdquo; means the
          dataset carries what the stage needs, not that the stage has been run.
          {blocked > 0 && (
            <>
              {' '}
              {blocked} of {report.readiness.length} stages are blocked, each for a
              stated reason.
            </>
          )}
        </p>
        <div data-readiness-list>
          {report.readiness.map((assessment) => (
            <CapabilityRow key={assessment.capability} assessment={assessment} />
          ))}
        </div>
      </PanelBody>
    </Panel>
  )
}

/**
 * Spatial reference.
 *
 * The two questions are kept visibly separate: whether coordinates exist, and
 * whether they are enough to place the survey on Earth. An odometry survey
 * answers yes to the first and no to the second, and collapsing them is how a
 * reconstruction ends up drawn at a coordinate nobody measured.
 */
function SpatialSection({ report }: { report: Report }) {
  const { horizontal: h, vertical: v, geometry: g } = report.spatial

  return (
    <Section title="Spatial reference">
      <SectionLabel>Horizontal</SectionLabel>
      <dl>
        <Field label="Coordinates">
          {h.coordinates_present ? 'Present' : 'None'}
        </Field>
        <Field label="Earth-referenced">
          <span data-earth-referenced={String(h.earth_referenced)}>
            {h.earth_referenced ? 'Yes' : 'No'}
          </span>
        </Field>
        <Field label="Reference">
          {h.declared_refs.length ? (
            <code className="font-mono text-[11px]">{h.declared_refs.join(', ')}</code>
          ) : (
            NO_VALUE
          )}
        </Field>
        <Field label="Declared by">
          {h.crs_provenance.length ? h.crs_provenance.join(', ') : NO_VALUE}
        </Field>
        <Field label="Positioned">
          {formatCount(h.positioned_record_count)} of {formatCount(h.total_record_count)}
        </Field>
      </dl>
      <Reasons items={h.reasons} />

      <SectionLabel>Vertical</SectionLabel>
      <dl>
        <Field label="Axis">
          {v.axis_kinds.length ? v.axis_kinds.join(', ') : NO_VALUE}
        </Field>
        <Field label="Measured from">
          {v.axis_origins.length ? v.axis_origins.join('; ') : NO_VALUE}
        </Field>
        <Field label="Vertical datum">
          <span data-vertical-datum={String(v.vertical_datum_declared)}>
            {v.vertical_datum_declared ? v.vertical_datums.join(', ') : 'Not declared'}
          </span>
        </Field>
        <Field label="Depth axis">
          {v.depth_axis_available ? `Available (${v.depth_basis})` : 'None'}
        </Field>
        {/*
          Stated separately from "a depth axis exists", because they are
          different claims. A velocity turns time into a distance; it does not
          say what that distance is measured from.
        */}
        <Field label="Depth is physical">
          <span data-time-to-depth={String(v.time_to_depth_justified)}>
            {v.time_to_depth_justified ? 'Justified' : 'Not validated'}
          </span>
        </Field>
        <Field label="Surface model">
          {v.surface_model_held ? v.surface_frame_ids.join(', ') : 'None held'}
        </Field>
        <Field label="Absolute elevation">
          <span data-absolute-elevation={String(v.absolute_elevation_available)}>
            {v.absolute_elevation_available ? 'Computable' : 'Not available'}
          </span>
        </Field>
      </dl>
      <Reasons items={v.reasons} />

      <SectionLabel>Survey geometry</SectionLabel>
      <dl>
        <Field label="Frames">{formatCount(g.frame_count)}</Field>
        <Field label="Extent">
          {g.lat_span_m !== null && g.lon_span_m !== null
            ? `${g.lat_span_m} m × ${g.lon_span_m} m`
            : NO_VALUE}
        </Field>
        {Object.entries(g.along_track_extent_m).map(([frame, extent]) => (
          <Field key={frame} label="Along track">
            {extent} m ({frame})
          </Field>
        ))}
      </dl>
      <Reasons items={g.reasons} />
    </Section>
  )
}

/** The backend's own explanations, verbatim. */
function Reasons({ items }: { items: string[] }) {
  if (!items.length) return null
  return (
    <ul className="mt-2 space-y-1" data-reasons>
      {items.map((item) => (
        <li key={item} className="text-xs leading-relaxed text-muted-foreground">
          {item}
        </li>
      ))}
    </ul>
  )
}

function IdentitySection({ report }: { report: Report }) {
  const id = report.identity
  return (
    <Section title="Identity">
      <dl>
        <Field label="Dataset ID">
          <code className="font-mono text-[11px]">{id.dataset_id}</code>
        </Field>
        <Field label="Modality">{id.modality ?? NO_VALUE}</Field>
        <Field label="Format">{id.original_format ?? NO_VALUE}</Field>
        <Field label="Source">{id.source ?? NO_VALUE}</Field>
        <Field label="Licence">{id.license ?? NO_VALUE}</Field>
        <Field label="Manufacturer">{id.manufacturer ?? NO_VALUE}</Field>
        <Field label="Device">{id.device_model ?? NO_VALUE}</Field>
        <Field label="Acquired">{formatDateTime(id.collection_date)}</Field>
        <Field label="Imported">{formatDateTime(id.imported_at)}</Field>
        <Field label="Files">
          {id.source_files.length ? id.source_files.join(', ') : NO_VALUE}
        </Field>
        <Field label="Owner">
          {id.is_system_dataset ? 'System reference dataset' : 'You'}
        </Field>
      </dl>

      {/*
        Named absences. A blank field could be an oversight in the UI; a list
        that says "manufacturer, device model, acquisition date" says the source
        did not declare them, which is a different and more useful fact.
      */}
      {id.undeclared.length > 0 && (
        <p data-undeclared className="mt-3 text-xs leading-relaxed text-muted-foreground">
          Not declared by the source: {id.undeclared.join(', ')}. Subterra does not
          infer these.
        </p>
      )}
    </Section>
  )
}

function DataSection({ report }: { report: Report }) {
  const v = report.volume
  return (
    <Section title="Data">
      <dl>
        <Field label="Records">{formatCount(v.record_count)}</Field>
        <Field label="Frames">{formatCount(v.frame_count)}</Field>
        <Field label="Samples per trace">
          {v.samples_per_trace?.length ? v.samples_per_trace.join(', ') : NO_VALUE}
        </Field>
        <Field label="Sample interval">
          {v.sample_interval?.length
            ? `${v.sample_interval.join(', ')} ${v.sample_interval_units ?? ''}`.trim()
            : NO_VALUE}
        </Field>
        <Field label="With signal">{formatCount(v.records_with_signal)}</Field>
        <Field label="With timestamp">{formatCount(v.records_with_timestamp)}</Field>
        <Field label="With depth">{formatCount(v.records_with_depth)}</Field>
        <Field label="Invalid samples">{formatCount(v.invalid_signal_count)}</Field>
        <Field label="Position kinds">
          {Object.entries(v.position_kinds).length
            ? Object.entries(v.position_kinds)
                .map(([kind, count]) => `${kind}: ${formatCount(count)}`)
                .join(', ')
            : NO_VALUE}
        </Field>
      </dl>
    </Section>
  )
}

/**
 * Quality, with the dimensions behind the score.
 *
 * A dimension whose value is null is rendered as "not measured" and never as
 * 0 %. The two are opposite claims: one says nothing is known, the other says
 * something bad is known.
 */
function QualitySection({ report }: { report: Report }) {
  const q = report.quality
  return (
    <Section title="Quality">
      <dl>
        <Field label="Score">
          {q.stored_score === null ? NO_VALUE : formatPercent(q.stored_score)}
        </Field>
      </dl>

      {q.score_is_stale && (
        <p data-stale-score className="mt-2 text-xs leading-relaxed text-muted-foreground">
          The stored score ({formatPercent(q.stored_score)}) does not match a fresh
          computation ({formatPercent(q.computed_score)}). The dataset changed after it
          was last scored.
        </p>
      )}

      <div className="mt-3 space-y-2.5">
        {q.dimensions.map((d) => (
          <div key={d.name} data-dimension={d.name}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-xs text-foreground">{d.name.replace(/_/g, ' ')}</span>
              <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                {d.value === null ? 'not measured' : formatPercent(d.value)}
                {d.weight === 0 && d.value !== null && ' (reported only)'}
              </span>
            </div>
            <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
              {d.basis}
            </p>
          </div>
        ))}
      </div>

      {q.issues.length > 0 && <Reasons items={q.issues} />}
    </Section>
  )
}

function ProcessingSection({ report }: { report: Report }) {
  return (
    <Section
      title="Processing history"
      note="What actually happened to this dataset, read from what the platform recorded. A stage nobody ran says so."
    >
      <div className="space-y-2.5">
        {report.processing.map((stage) => (
          <div key={stage.stage} data-stage={stage.stage} data-status={stage.status}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-xs text-foreground">
                {stage.stage.replace(/_/g, ' ')}
              </span>
              <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                {stage.status.replace(/_/g, ' ')}
              </span>
            </div>
            {stage.detail && (
              <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                {stage.detail}
              </p>
            )}
          </div>
        ))}
      </div>
    </Section>
  )
}

/**
 * Candidates.
 *
 * THE WORD "DETECTED" DOES NOT APPEAR IN THIS SECTION, and the backend cannot
 * send anything that would justify it. A candidate is an anomalous region; the
 * shape classes below describe the geometry of a response, not the identity of
 * a buried thing. `frontend/components/subterra/honesty.test.tsx` and the
 * report's own tests both hold that line.
 */
function CandidateSection({ report }: { report: Report }) {
  const c = report.candidates
  return (
    <Section title="Candidates">
      {c.analysed ? (
        <>
          <dl>
            <Field label="Candidate regions">{formatCount(c.candidate_count)}</Field>
            <Field label="In frames">
              {c.frames_with_candidates.length
                ? c.frames_with_candidates.join(', ')
                : NO_VALUE}
            </Field>
            <Field label="Shape classes">
              {Object.entries(c.shape_classes)
                .map(([shape, count]) => `${shape}: ${count}`)
                .join(', ') || NO_VALUE}
            </Field>
            <Field label="Evidence">
              {c.evidence_available
                ? 'Each candidate traces to its source file and trace range'
                : 'Not addressable'}
            </Field>
          </dl>
          <p data-candidate-note className="mt-3 text-xs leading-relaxed text-muted-foreground">
            {c.note}
          </p>
        </>
      ) : (
        <p className="text-xs leading-relaxed text-muted-foreground">
          No candidate analysis has been run on this dataset. {c.note}
        </p>
      )}
    </Section>
  )
}
