'use client'

import { Suspense, useCallback, useRef, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { FileUp, Upload } from 'lucide-react'
import { AppHeader } from '@/components/shell/app-header'
import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { AcquisitionReview } from '@/components/import/acquisition-review'
import { buttonVariants } from '@/components/ui/button'
import { FormatVerdict, classify, type Verdict } from '@/components/import/format-check'
import { ImportFailure, ImportReport } from '@/components/import/import-report'
import { JobState, StageTrack } from '@/components/import/job-progress'
import { useImportFormats, useImportJob, useSession } from '@/hooks/use-subterra'
import { api, ApiError } from '@/services/api'
import { NO_VALUE } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ImportJob } from '@/types/subterra'

/**
 * IMPORT DATASET.
 *
 * The first path by which a user can put their own data into Subterra. It is
 * deliberately NOT called "New Scan": that would imply a choice between
 * uploading and acquiring, and no hardware adapter exists. When one does, this
 * page gains a second source; until then it advertises exactly what it can do.
 *
 * The format verdict is decided before upload, from the registry the backend
 * serves. Nothing here keeps its own list of extensions.
 */
// 'other' used to be offered here. The backend's sensor_type is a real enum
// (schemas/subterra_record.py SensorType) with no OTHER member, so choosing
// it always failed the upload with a 422 the UI could not render sensibly --
// FastAPI's validation `detail` for an enum mismatch is a list of objects,
// and this page's error path does `String(detail)`, which prints
// "[object Object]", not an explanation. Every choice offered here must be
// a value the backend actually accepts.
const SENSOR_TYPES = ['gpr', 'lidar', 'dem', 'seismic', 'magnetometer', 'satellite']

export default function ImportPage() {
  // Suspense because the page reads the session id from the query string.
  return (
    <Suspense>
      <ImportPageContent />
    </Suspense>
  )
}

function ImportPageContent() {
  // `?session=<id>` is Stage 10's convergence with FileDrop: a device
  // session's "Import" link carries its id here so the acquisition this page
  // produces is attributed to that session rather than landing as an
  // ordinary, unattributed drop. Bare /import (no param) is unchanged.
  const sessionId = useSearchParams().get('session') ?? undefined
  const { data: session, error: sessionError, isLoading: sessionLoading } =
    useSession(sessionId)
  const { data: formats, error: formatsError, isLoading } = useImportFormats()
  const [file, setFile] = useState<File | null>(null)
  // No pre-selected type. The panel says this is supplied by the operator,
  // not read from the file, and that the platform will not guess it -- a
  // default of 'gpr' would have made that copy false for every drop nobody
  // clicked a button for.
  const [sensorType, setSensorType] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | undefined>()
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  // The acquisition as first returned. `useImportJob` only polls once there is
  // a job id, and a held acquisition never changes on its own, so the first
  // response is what the review renders.
  const [held, setHeld] = useState<ImportJob | null>(null)

  const { data: job } = useImportJob(jobId)

  const verdict: Verdict | null = file && formats ? classify(file, formats) : null
  const canImport = verdict?.kind === 'supported' && !submitting && !!sensorType

  const reset = useCallback(() => {
    setFile(null)
    setSensorType(null)
    setJobId(undefined)
    setHeld(null)
    setSubmitError(null)
    if (inputRef.current) inputRef.current.value = ''
  }, [])

  const submit = useCallback(async () => {
    if (!file || !sensorType) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      // review=true: the acquisition stops at the boundary and reports what
      // arrived, so the decision to spend an ingestion is made by somebody who
      // has been told what the file is.
      const { job: created } = await api.createImport(file, sensorType, true, sessionId)
      setJobId(created.id)
      setHeld(created)
    } catch (err) {
      // The backend's own refusal, verbatim -- e.g. a session that has ended
      // (409) or one that is not yours (404). No new refusal vocabulary here.
      setSubmitError(
        err instanceof ApiError ? err.detail : `upload failed: ${String(err)}`,
      )
    } finally {
      setSubmitting(false)
    }
  }, [file, sensorType, sessionId])

  // A job that was refused at the format gate comes back already FAILED.
  const shown: ImportJob | undefined = job ?? held ?? undefined
  const finished = shown?.state === 'SUCCEEDED' || shown?.state === 'FAILED'
  // Held at the acquisition boundary: identified, but not yet ingested.
  const awaitingReview =
    shown?.state === 'IDENTIFIED' || shown?.state === 'NEEDS_INPUT'

  return (
    <>
      <AppHeader
        title="Import dataset"
        subtitle="Upload a survey file. It is converted, validated and registered by the same pipeline the platform uses everywhere else."
      />

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="mx-auto max-w-4xl space-y-4">
          {/*
            THE ATTRIBUTION, STATED ONCE, UP FRONT. A session declares no
            evidence at creation, and a file dropped here without this banner
            would look identical to an ordinary drop -- the whole point of
            carrying `session_id` through is that it does not. This is not a
            connection or a permission check: any open session may still
            receive an acquisition even with no declared adapter, and a
            closed one is refused by the backend at submit time, in its own
            words, via the ordinary error path below.
          */}
          {sessionId && (
            <Panel>
              <PanelBody>
                <QueryState
                  isLoading={sessionLoading}
                  error={sessionError}
                  absenceTitle="Session unavailable"
                  errorTitle="Could not load the session"
                  skeletonRows={1}
                />
                {session && (
                  <div
                    data-session-attribution
                    className="flex flex-wrap items-center gap-x-2 gap-y-1"
                  >
                    <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-prov-measured">
                      Attributed to session
                    </span>
                    <span className="text-sm text-foreground">
                      {[session.device?.manufacturer, session.device?.model]
                        .filter(Boolean)
                        .join(' ') ||
                        session.device?.device_type ||
                        NO_VALUE}
                    </span>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      ({session.session.state})
                    </span>
                    <Link
                      href="/import"
                      className="ml-auto text-xs text-primary underline-offset-4 hover:underline"
                    >
                      Import without a session
                    </Link>
                  </div>
                )}
              </PanelBody>
            </Panel>
          )}

          {shown?.state === 'SUCCEEDED' && shown.dataset_id ? (
            <Panel>
              <PanelBody>
                <ImportReport job={shown} onReset={reset} />
              </PanelBody>
            </Panel>
          ) : shown?.state === 'FAILED' ? (
            <Panel>
              <PanelBody>
                <ImportFailure job={shown} onReset={reset} />
              </PanelBody>
            </Panel>
          ) : (
            <>
              <Panel>
                <PanelHeader title="Source file" />
                <PanelBody>
                  {formatsError && (
                    <StateBox
                      kind="error"
                      title="Could not read the format registry"
                      detail={
                        formatsError instanceof ApiError
                          ? formatsError.detail
                          : String(formatsError)
                      }
                    />
                  )}

                  {!formatsError && (
                    <>
                      <div
                        data-dropzone
                        onDragOver={(e) => {
                          e.preventDefault()
                          setDragging(true)
                        }}
                        onDragLeave={() => setDragging(false)}
                        onDrop={(e) => {
                          e.preventDefault()
                          setDragging(false)
                          const dropped = e.dataTransfer.files?.[0]
                          if (dropped) setFile(dropped)
                        }}
                        className={cn(
                          'subterra-grid flex flex-col items-center justify-center rounded-lg border border-dashed px-6 py-12 text-center transition-colors',
                          dragging
                            ? 'border-primary bg-primary/5'
                            : 'border-border hover:border-primary/40',
                        )}
                      >
                        <FileUp
                          className="size-6 text-muted-foreground"
                          aria-hidden
                        />
                        <p className="mt-3 text-sm text-foreground">
                          Drop a dataset here
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          or
                        </p>
                        <label
                          className={cn(
                            buttonVariants({ variant: 'outline', size: 'sm' }),
                            'mt-2 cursor-pointer',
                          )}
                        >
                          Choose file
                          <input
                            ref={inputRef}
                            type="file"
                            className="sr-only"
                            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                          />
                        </label>
                        {isLoading && (
                          <p className="mt-4 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                            reading format registry…
                          </p>
                        )}
                        {formats && (
                          <p className="mt-4 max-w-md font-mono text-[10px] uppercase leading-relaxed tracking-[0.14em] text-muted-foreground">
                            {formats.supported.join(' · ')}
                          </p>
                        )}
                      </div>

                      {file && (
                        <dl className="mt-5 grid gap-3 sm:grid-cols-2">
                          <div>
                            <dt className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                              Filename
                            </dt>
                            <dd
                              data-filename
                              className="mt-1 truncate text-sm text-foreground"
                            >
                              {file.name}
                            </dd>
                          </div>
                          <div>
                            <dt className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                              Size
                            </dt>
                            <dd className="tabular mt-1 text-sm text-foreground">
                              {(file.size / (1024 * 1024)).toFixed(2)} MB
                            </dd>
                          </div>
                          <div className="sm:col-span-2">
                            <dt className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                              Recognition
                            </dt>
                            <dd className="mt-2">
                              {verdict && <FormatVerdict verdict={verdict} />}
                            </dd>
                          </div>
                        </dl>
                      )}
                    </>
                  )}
                </PanelBody>
              </Panel>

              {file && verdict?.kind === 'supported' && (
                <Panel>
                  <PanelHeader title="Declared sensor type" />
                  <PanelBody>
                    <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
                      This is <span className="text-foreground">supplied by you</span>,
                      not read from the file, and is recorded with that provenance. The
                      platform will not guess it.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {SENSOR_TYPES.map((type) => (
                        <button
                          key={type}
                          type="button"
                          onClick={() => setSensorType(type)}
                          className={cn(
                            'rounded-md border px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.14em] transition-colors',
                            sensorType === type
                              ? 'border-primary text-primary'
                              : 'border-border text-muted-foreground hover:text-foreground',
                          )}
                        >
                          {type}
                        </button>
                      ))}
                    </div>

                    {submitError && (
                      <StateBox
                        kind="error"
                        className="mt-4"
                        title="Upload refused"
                        detail={submitError}
                      />
                    )}

                    <button
                      type="button"
                      disabled={!canImport}
                      onClick={submit}
                      className={cn(
                        buttonVariants({ variant: 'default', size: 'lg' }),
                        'mt-5',
                      )}
                    >
                      <Upload aria-hidden />
                      {submitting ? 'Uploading…' : 'Import dataset'}
                    </button>
                  </PanelBody>
                </Panel>
              )}

              {/*
                Held at the acquisition boundary. Nothing has been ingested and
                nothing will be until this is accepted -- so the stage track,
                which describes an ingestion in flight, would be describing
                something that is not happening.
              */}
              {shown && awaitingReview && (
                <Panel>
                  <PanelHeader title="What arrived" />
                  <PanelBody>
                    <AcquisitionReview
                      job={shown}
                      onAccepted={(queued) => setHeld(queued)}
                    />
                  </PanelBody>
                </Panel>
              )}

              {shown && !finished && !awaitingReview && (
                <Panel>
                  <PanelHeader title="Import job" />
                  <PanelBody>
                    <div className="mb-4 flex flex-wrap items-center gap-3">
                      <JobState job={shown} />
                      <code className="font-mono text-[11px] text-muted-foreground">
                        {shown.id}
                      </code>
                    </div>
                    <StageTrack job={shown} />
                  </PanelBody>
                </Panel>
              )}
            </>
          )}
        </div>
      </div>
    </>
  )
}
