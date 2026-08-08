'use client'

import { useCallback, useRef, useState } from 'react'
import { FileUp, Upload } from 'lucide-react'
import { AppHeader } from '@/components/shell/app-header'
import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { StateBox } from '@/components/subterra/state-box'
import { buttonVariants } from '@/components/ui/button'
import { FormatVerdict, classify, type Verdict } from '@/components/import/format-check'
import { ImportFailure, ImportReport } from '@/components/import/import-report'
import { JobState, StageTrack } from '@/components/import/job-progress'
import { useImportFormats, useImportJob } from '@/hooks/use-subterra'
import { api, ApiError } from '@/services/api'
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
const SENSOR_TYPES = ['gpr', 'lidar', 'seismic', 'magnetometer', 'satellite', 'other']

export default function ImportPage() {
  const { data: formats, error: formatsError, isLoading } = useImportFormats()
  const [file, setFile] = useState<File | null>(null)
  const [sensorType, setSensorType] = useState('gpr')
  const [jobId, setJobId] = useState<string | undefined>()
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: job } = useImportJob(jobId)

  const verdict: Verdict | null = file && formats ? classify(file, formats) : null
  const canImport = verdict?.kind === 'supported' && !submitting

  const reset = useCallback(() => {
    setFile(null)
    setJobId(undefined)
    setSubmitError(null)
    if (inputRef.current) inputRef.current.value = ''
  }, [])

  const submit = useCallback(async () => {
    if (!file) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const { job: created } = await api.createImport(file, sensorType)
      setJobId(created.id)
    } catch (err) {
      setSubmitError(
        err instanceof ApiError ? err.detail : `upload failed: ${String(err)}`,
      )
    } finally {
      setSubmitting(false)
    }
  }, [file, sensorType])

  // A job that was refused at the format gate comes back already FAILED.
  const shown: ImportJob | undefined = job
  const finished = shown?.state === 'SUCCEEDED' || shown?.state === 'FAILED'

  return (
    <>
      <AppHeader
        title="Import dataset"
        subtitle="Upload a survey file. It is converted, validated and registered by the same pipeline the platform uses everywhere else."
      />

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="mx-auto max-w-4xl space-y-4">
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

              {shown && !finished && (
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
