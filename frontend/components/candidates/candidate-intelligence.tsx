'use client'

import { useState } from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import { ApiError, api } from '@/services/api'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { formatCount } from '@/lib/format'
import type {
  CandidateIntelligence,
  DepthCertainty,
  ExportFormatInfo,
  ExportReport,
  ExportResult,
  InspectableCandidate,
  LocalisationCertainty,
} from '@/types/subterra'

/**
 * Candidate intelligence.
 *
 * THIS SCREEN'S ENTIRE JOB IS TO STOP A LIST FROM READING AS A FINDING. The
 * detector performs at approximately chance on both benchmarks it has been
 * scored against. A ranked list of regions, rendered without that fact, is a
 * page that says "we found twelve things" — which is false, and would be the
 * most damaging thing this platform could display. So the measured performance
 * is rendered ABOVE the candidates, not below them and not behind a link, and
 * it comes from the payload rather than from a constant in this file, because a
 * number typed here could drift away from the one the benchmark actually
 * produced.
 *
 * NO FIELD IS RENDERED AS A PERCENTAGE OR A CONFIDENCE. `candidate_score` is a
 * peak anomaly magnitude and is shown as a bare number with its meaning beside
 * it. There is no progress bar, no colour ramp from red to green, and no sort
 * control offering "most likely" — every one of those would assert a
 * calibration that does not exist.
 *
 * DEPTH AND POSITION ARE SHOWN AS CERTAINTY LEVELS FIRST. A candidate whose
 * depth is `unavailable` shows the word unavailable, never a number: the
 * instrument-axis position exists, but it is not a physical depth, and Stage 12
 * established that relating the origin to the ground does not make it one.
 */

const LOCALISATION_LABEL: Record<LocalisationCertainty, string> = {
  spatially_registered: 'Spatially registered',
  frame_relative: 'Frame-relative',
  trace_relative: 'Trace-relative',
  unknown: 'Unknown',
}

const DEPTH_LABEL: Record<DepthCertainty, string> = {
  measured: 'Measured',
  derived: 'Derived from an assumed velocity',
  unavailable: 'Unavailable',
}

export function CandidateIntelligenceView({ datasetId }: { datasetId: string }) {
  const { data, error, isLoading, mutate } = useSWR<CandidateIntelligence>(
    ['candidates', datasetId],
    () => api.getCandidates(datasetId),
  )
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)

  async function generate() {
    setBusy(true)
    setActionError(null)
    try {
      await mutate(await api.generateCandidates(datasetId), { revalidate: false })
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? err.detail
          : 'could not reach the Subterra API. Is the backend running?',
      )
    } finally {
      setBusy(false)
    }
  }

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading candidate intelligence…</p>
  }
  if (error && !data) {
    return (
      <p role="alert" className="text-sm text-muted-foreground">
        Could not load candidate intelligence.
      </p>
    )
  }
  if (!data) return null

  // Slice 4's exact sentence: "candidate analysis is a GPR-trace capability
  // and does not apply to it". No other blocked reason (has not been run, no
  // records, preprocessing not run, wrong geometry) contains this phrase, so
  // it is the one signal this component needs -- not a second fetch of
  // recorded_modalities, not a composition list parsed out of the reason.
  const doesNotApply =
    data.status === 'blocked' && data.status_reason.includes('does not apply')

  return (
    <div data-candidate-intelligence={data.status} className="space-y-6">
      <header>
        <h2 className="text-base font-medium text-foreground">Candidate intelligence</h2>
        {/*
          The list says WHERE a candidate is; the radargram shows WHAT it came
          from. A reviewer asked to accept or reject one needs the second --
          unless candidate analysis does not apply to this dataset at all, in
          which case a radargram does not apply either (slices 5-6), and
          linking to one would repeat the exact lie this platform has spent
          slices 4-9 removing everywhere else.
        */}
        {!doesNotApply && (
          <Link
            href={`/datasets/${encodeURIComponent(datasetId)}/radargram`}
            data-radargram-link
            className="mt-1 inline-flex text-xs text-primary underline-offset-4 hover:underline"
          >
            Inspect these candidates on the measured radargram
          </Link>
        )}
        {/*
          The definition is the vocabulary of a processed-signal /
          generation-rule capability. When that capability does not apply to
          this dataset's composition, showing its definition would frame the
          status_reason below as a footnote under a method that still
          applies -- the same misdirection slice 10 removed from the
          generate button and the radargram link.
        */}
        {!doesNotApply && (
          <p data-candidate-definition className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {data.definition}
          </p>
        )}
      </header>

      {/*
        ABOVE THE CANDIDATES, DELIBERATELY. This is the context that decides how
        everything below it should be read -- UNLESS the method's context is
        not this dataset's context at all. "Measured performance of this
        method" is gpr_local_anomaly's score; showing it on a dataset whose
        composition does not apply to that method dresses up an inapplicable
        capability as a footnoted one, the same class of lie as slice 10's
        Generate button.
      */}
      {!doesNotApply && (
        <section
          data-benchmark-context
          className="rounded-lg border border-border px-4 py-3"
        >
          <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
            Measured performance of this method
          </p>
          <p className="mt-1.5 text-xs leading-relaxed text-foreground">
            {data.benchmark.summary}
          </p>
          <ul className="mt-2 space-y-1">
            {data.benchmark.measurements.map((m) => (
              <li key={`${m.benchmark}-${m.arm}`} className="text-xs text-muted-foreground">
                <span className="text-foreground">
                  {m.benchmark} · {m.arm}
                </span>
                {m.precision !== undefined && (
                  <>
                    {' '}
                    — precision {m.precision.toFixed(4)}, recall {m.recall?.toFixed(4)}, F1{' '}
                    {m.f1?.toFixed(4)} ({m.times_chance}× the {m.chance_precision} chance rate)
                  </>
                )}
                {m.auc !== undefined && (
                  <>
                    {' '}
                    — AUC {m.auc.toFixed(4)}, 95% interval [{m.ci95?.[0].toFixed(4)},{' '}
                    {m.ci95?.[1].toFixed(4)}] on {m.n_negative} negatives
                    {m.contains_chance ? ', which spans chance' : ''}
                  </>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            {data.benchmark.caveat}
          </p>

          {/*
            STAGE 14. The block above says how this method SCORED. This says
            whether that score could have come out differently — a property of
            the ground truth, not of the detector. Without it, "no measured
            improvement" reads as "no improvement", when the corpus cannot
            currently resolve one.
          */}
          {data.benchmark.adequacy && (
            <p
              data-benchmark-adequacy
              className="mt-2 text-xs leading-relaxed text-foreground"
            >
              {data.benchmark.adequacy}
            </p>
          )}

          {(data.benchmark.evaluated?.length || data.benchmark.not_evaluated?.length) && (
            <div className="mt-2 grid gap-2 text-xs leading-relaxed text-muted-foreground sm:grid-cols-2">
              {data.benchmark.evaluated?.length ? (
                <div>
                  <p className="text-foreground">The ground truth supports scoring:</p>
                  <ul className="mt-1 space-y-0.5">
                    {data.benchmark.evaluated.map((item) => (
                      <li key={item} data-benchmark-evaluated>
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {data.benchmark.not_evaluated?.length ? (
                <div>
                  <p className="text-foreground">Not evaluated, and why:</p>
                  <ul className="mt-1 space-y-0.5">
                    {data.benchmark.not_evaluated.map((item) => (
                      <li key={item} data-benchmark-not-evaluated>
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          )}

          {data.benchmark.definition_version && (
            <p className="mt-2 font-mono text-[10px] text-muted-foreground">
              ground-truth definition {data.benchmark.definition_version}
            </p>
          )}
        </section>
      )}

      {data.status === 'blocked' ? (
        <section data-candidates-blocked className="space-y-2">
          <p className="text-sm text-foreground">{data.status_reason}.</p>
          <div className="text-xs leading-relaxed text-muted-foreground">
            <p>This needs:</p>
            <ul className="mt-1 space-y-0.5">
              {data.missing.map((item) => (
                <li key={item} data-candidates-missing className="flex gap-2">
                  <span aria-hidden className="select-none text-primary">
                    &middot;
                  </span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
          {/*
            Generating cannot make a GPR-trace capability apply to a dataset
            that does not record gpr. The button is correct for "has not been
            run" and wrong for "does not apply" -- offering it there would
            invite a request the backend already refuses for a reason no
            retry fixes.
          */}
          {!doesNotApply && <GenerateButton busy={busy} onClick={generate} />}
          {actionError && <ActionError message={actionError} />}
        </section>
      ) : (
        <>
          {data.staleness.is_stale && (
            <section
              data-candidates-stale
              className="rounded-lg border border-border px-4 py-3 text-xs leading-relaxed text-muted-foreground"
            >
              <p className="text-foreground">
                This candidate set no longer matches the dataset.
              </p>
              <ul className="mt-1 space-y-0.5">
                {data.staleness.reasons.map((reason) => (
                  <li key={reason} data-stale-reason>
                    {reason}
                  </li>
                ))}
              </ul>
              <p className="mt-1.5">{data.staleness.note}</p>
            </section>
          )}

          <section className="space-y-3">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
              <Field label="Candidate regions">{formatCount(data.candidate_count)}</Field>
              <Field label="Inspection burden">
                {data.candidate_burden === null
                  ? 'not computable'
                  : `${data.candidate_burden.toFixed(1)} per 1000 traces`}
              </Field>
              <Field label="Object classification">
                <span data-classification-status className="text-foreground">
                  {data.classification_status}
                </span>
              </Field>
              <Field label="Method">
                {data.generation
                  ? `${data.generation.method} v${data.generation.method_version}`
                  : 'unrecorded'}
              </Field>
              <Field label="Parameters">
                {data.generation
                  ? `|z| > ${data.generation.parameters.threshold}, ` +
                    `min ${data.generation.parameters.min_cells} cells, ` +
                    `min ${data.generation.parameters.min_trace_span} trace(s)`
                  : 'unrecorded'}
              </Field>
              <Field label="Reproducible">
                {data.generation?.deterministic ? 'Yes — no randomness is used' : 'Not guaranteed'}
              </Field>
            </dl>
            <p className="text-xs leading-relaxed text-muted-foreground">
              {data.classification_blocked_reason}.
            </p>
            <GenerateButton busy={busy} onClick={generate} label="Regenerate candidates" />
            {actionError && <ActionError message={actionError} />}
          </section>

          <section className="space-y-2">
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Candidates, ranked
            </p>
            <p className="text-xs leading-relaxed text-muted-foreground">
              {data.ranking_basis}
            </p>
            {data.candidates.length === 0 ? (
              <p data-no-candidates className="text-xs text-muted-foreground">
                This method produced no candidates for this dataset. That is a result, not
                a failure: it means no region satisfied the rule.
              </p>
            ) : (
              <ul className="space-y-2">
                {data.candidates.slice(0, 50).map((c) => (
                  <CandidateRow
                    key={c.candidate.id}
                    candidate={c}
                    open={openId === c.candidate.id}
                    onToggle={() =>
                      setOpenId(openId === c.candidate.id ? null : c.candidate.id)
                    }
                  />
                ))}
              </ul>
            )}
            {data.candidates.length > 50 && (
              <p className="text-xs text-muted-foreground">
                Showing the 50 highest-scoring of {formatCount(data.candidates.length)}.
              </p>
            )}
          </section>

          {/*
            Export follows CLASSIFIED OBJECTS, not raw candidates -- a
            distinct, downstream store (`database.objects_store`) that a
            dataset can hold zero of even with candidates present. Gating on
            `classified_object_count` (already in this payload) means no
            extra request decides whether to show the panel at all.
          */}
          {data.classified_object_count > 0 && (
            <ExportPanel datasetId={datasetId} objectCount={data.classified_object_count} />
          )}
        </>
      )}
    </div>
  )
}

function GenerateButton({
  busy,
  onClick,
  label = 'Generate candidates',
}: {
  busy: boolean
  onClick: () => void
  label?: string
}) {
  return (
    <button
      type="button"
      data-action="generate-candidates"
      disabled={busy}
      onClick={onClick}
      className={cn(buttonVariants({ variant: 'default', size: 'sm' }))}
    >
      {busy ? 'Generating…' : label}
    </button>
  )
}

function ActionError({ message }: { message: string }) {
  return (
    <p
      data-candidate-error
      role="alert"
      className="rounded-lg border border-destructive/40 px-3 py-2 text-xs leading-relaxed text-foreground"
    >
      {message}
    </p>
  )
}

/**
 * One candidate.
 *
 * The collapsed row shows what it IS — a region of a named file, spanning named
 * traces — and never what it might be. Expanding reveals the evidence chain,
 * which is the point: a person should be able to go and look at the
 * measurements rather than trust this list.
 */
function CandidateRow({
  candidate,
  open,
  onToggle,
}: {
  candidate: InspectableCandidate
  open: boolean
  onToggle: () => void
}) {
  const c = candidate.candidate
  const [from, to] = c.evidence.trace_range
  return (
    <li data-candidate={c.id} className="rounded-lg border border-border">
      <button
        type="button"
        data-action="inspect-candidate"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-start justify-between gap-4 px-4 py-3 text-left"
      >
        <span className="min-w-0">
          <span className="block truncate text-sm text-foreground">
            {c.evidence.source_file} · traces {from}–{to}
          </span>
          <span className="mt-0.5 block text-xs text-muted-foreground">
            {c.interpretation.anomaly_class} · {LOCALISATION_LABEL[candidate.localisation]} ·
            depth {DEPTH_LABEL[candidate.depth].toLowerCase()}
          </span>
        </span>
        <span className="shrink-0 text-right">
          <span className="block font-mono text-xs text-foreground">
            {candidate.candidate_score.toFixed(2)}
          </span>
          <span className="block font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
            score
          </span>
        </span>
      </button>

      {open && (
        <div data-candidate-detail className="space-y-3 border-t border-border px-4 py-3">
          <p className="text-xs leading-relaxed text-muted-foreground">
            {candidate.candidate_score_meaning}
          </p>

          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
            <Field label="Source file">{c.evidence.source_file}</Field>
            <Field label="Traces">
              {from}–{to}
            </Field>
            <Field label="Supporting cells">{formatCount(c.evidence.n_supporting_cells)}</Field>
            <Field label="Peak |z|">{Math.abs(c.evidence.peak_value).toFixed(2)}</Field>
            <Field label="Shape class">{c.interpretation.anomaly_class}</Field>
            <Field label="Continuity across traces">
              {c.characteristics.continuity_across_traces.toFixed(2)}
            </Field>
          </dl>

          <div className="text-xs leading-relaxed text-muted-foreground">
            <p className="text-foreground">Position: {LOCALISATION_LABEL[candidate.localisation]}</p>
            <p data-localisation-basis>{candidate.localisation_basis}.</p>
          </div>

          {/*
            The depth line never prints a number when depth is unavailable. The
            candidate has a position on the instrument's own axis, which is not
            a depth, and showing it as one is the exact error Stage 12 closed.
          */}
          <div className="text-xs leading-relaxed text-muted-foreground">
            <p className="text-foreground">Depth: {DEPTH_LABEL[candidate.depth]}</p>
            <p data-depth-basis>{candidate.depth_basis}.</p>
            {candidate.depth === 'derived' && (
              <p data-depth-interval>
                Interval {c.evidence.depth_range[0].toFixed(2)}–
                {c.evidence.depth_range[1].toFixed(2)} m, derived — not measured.
              </p>
            )}
          </div>

          <p data-candidate-classification className="text-xs leading-relaxed text-muted-foreground">
            Object classification: {candidate.classification_status}.{' '}
            {candidate.classification_blocked_reason}.
          </p>

          <p className="text-xs leading-relaxed text-muted-foreground">
            {c.interpretation.note}
          </p>
        </div>
      )}
    </li>
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

/** `format -> file extension`. `3d_tiles` is JSON (a tileset document); it
 * has never succeeded on any held dataset (`GET /api/exports/formats`
 * documents it as refused for all of them), so the extension is a small
 * honesty gap, not a live one. */
const EXPORT_EXTENSION: Record<string, string> = {
  json: 'json',
  csv: 'csv',
  geojson: 'geojson',
  czml: 'czml',
  '3d_tiles': 'json',
}

const EXPORT_MIME: Record<string, string> = {
  json: 'application/json',
  csv: 'text/csv',
  geojson: 'application/geo+json',
  czml: 'application/json',
  '3d_tiles': 'application/json',
}

/**
 * Objects, in a real downloadable format.
 *
 * NEVER RENDERS THE PAYLOAD. This triggers a real file download and shows
 * only the write/skip REPORT the backend returns alongside it -- the same
 * "nothing silently dropped" contract `GET /api/exports/formats` states,
 * surfaced rather than swallowed. CSV has no inline report: the backend
 * carries its written/skipped counts in response HEADERS
 * (`X-Subterra-Written`/`X-Subterra-Skipped`), which `services/api.ts`'s
 * `request()` does not expose to callers -- the file itself is still
 * complete and correct, this panel just cannot summarise it without a
 * second request the backend does not offer.
 */
function ExportPanel({ datasetId, objectCount }: { datasetId: string; objectCount: number }) {
  const { data: formatsData } = useSWR<{ formats: ExportFormatInfo[] }>(
    ['export-formats'],
    () => api.getExportFormats(),
  )
  const [format, setFormat] = useState('json')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastReport, setLastReport] = useState<ExportReport | null>(null)

  async function runExport() {
    setBusy(true)
    setError(null)
    setLastReport(null)
    try {
      const result = await api.exportDatasetObjects(datasetId, format)
      const isCsv = format === 'csv'
      const text = isCsv ? (result as string) : JSON.stringify((result as ExportResult).payload, null, 2)
      const blob = new Blob([text], { type: EXPORT_MIME[format] ?? 'application/octet-stream' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${datasetId}.${EXPORT_EXTENSION[format] ?? 'json'}`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      if (!isCsv) setLastReport((result as ExportResult).report)
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

  const formats = formatsData?.formats ?? []
  const selected = formats.find((f) => f.value === format)

  return (
    <section data-export-panel className="space-y-2 border-t border-border pt-4">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        Export
      </p>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {formatCount(objectCount)} classified object{objectCount === 1 ? '' : 's'} available.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          data-export-format
          value={format}
          onChange={(e) => setFormat(e.target.value)}
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {(formats.length > 0 ? formats : [{ value: 'json' } as ExportFormatInfo]).map((f) => (
            <option key={f.value} value={f.value}>
              {f.value}
            </option>
          ))}
        </select>
        <button
          type="button"
          data-action="export-objects"
          disabled={busy}
          onClick={runExport}
          className={cn(buttonVariants({ variant: 'default', size: 'sm' }))}
        >
          {busy ? 'Exporting…' : 'Export'}
        </button>
      </div>
      {selected?.note && (
        <p className="text-xs leading-relaxed text-muted-foreground">{selected.note}</p>
      )}
      {selected && !selected.carries_full_provenance && (
        <p className="text-xs leading-relaxed text-muted-foreground">
          This format does not carry full provenance — requires {selected.requires}.
        </p>
      )}
      {lastReport && (
        <p data-export-report className="text-xs leading-relaxed text-foreground">
          Wrote {formatCount(lastReport.written)}
          {lastReport.skipped.length > 0
            ? `, skipped ${formatCount(lastReport.skipped.length)} (see the file for why each was skipped)`
            : ''}
          .
        </p>
      )}
      {error && <ActionError message={error} />}
    </section>
  )
}
