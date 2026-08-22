'use client'

import { useState } from 'react'
import { AppHeader } from '@/components/shell/app-header'
import { Panel, PanelBody, PanelHeader, Field } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { Button } from '@/components/ui/button'
import { useDatasets } from '@/hooks/use-subterra'
import { ApiError, api } from '@/services/api'
import { NO_VALUE, formatCount, formatMetres } from '@/lib/format'
import type { FusionRunResult } from '@/types/subterra'

/**
 * Run spatial fusion across the caller's own datasets.
 *
 * PREVIEW, THEN SAVE -- never one button. `POST /api/fusion/run` with
 * `persist: true` writes new `FusionSample` rows with no check for an
 * existing equivalent: running it twice with the same inputs creates two
 * full sets of stored samples, silently. `persist: false` already IS a
 * safe, repeatable preview -- nothing is written -- so this screen never
 * offers a single control that both computes and saves in one click.
 *
 * SAVE IS DISABLED THE MOMENT ANY CONFIGURATION CHANGES. A save button
 * that stayed enabled after the operator adjusted the radius or the
 * dataset selection would let a click persist a result that was never
 * actually previewed -- the shown numbers and the saved numbers must be
 * the same run, not "close enough".
 *
 * `FusionSamplesPane` (the read-only, dataset-scoped view of what is
 * ALREADY STORED) is a different surface and is untouched by this page.
 */
export default function FusionPage() {
  const { data: datasets, error: datasetsError, isLoading: datasetsLoading } = useDatasets()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [radiusInput, setRadiusInput] = useState('')
  const [multimodalOnly, setMultimodalOnly] = useState(true)
  const [running, setRunning] = useState(false)
  const [preview, setPreview] = useState<FusionRunResult | null>(null)
  const [previewedParams, setPreviewedParams] = useState<string | null>(null)
  const [saved, setSaved] = useState<FusionRunResult | null>(null)
  const [runError, setRunError] = useState<string | null>(null)

  const currentParams = JSON.stringify({
    ids: Array.from(selected).sort(),
    radius: radiusInput,
    multimodalOnly,
  })
  const canSave = preview !== null && previewedParams === currentParams && !saved && !running

  function resetRunState() {
    setPreview(null)
    setPreviewedParams(null)
    setSaved(null)
    setRunError(null)
  }

  function toggleDataset(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
    resetRunState()
  }

  async function run(persist: boolean) {
    setRunning(true)
    setRunError(null)
    try {
      const result = await api.runFusion({
        datasetIds: selected.size > 0 ? Array.from(selected) : undefined,
        radiusM: radiusInput === '' ? undefined : Number(radiusInput),
        multimodalOnly,
        persist,
      })
      if (persist) {
        setSaved(result)
      } else {
        setPreview(result)
        setPreviewedParams(currentParams)
        setSaved(null)
      }
    } catch (err) {
      setRunError(err instanceof ApiError ? err.detail : `run failed: ${String(err)}`)
    } finally {
      setRunning(false)
    }
  }

  const shown = saved ?? preview

  return (
    <>
      <AppHeader
        title="Fusion"
        subtitle="Cluster records from your datasets into spatial fusion samples"
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="mx-auto max-w-3xl space-y-4">
          <Panel>
            <PanelHeader title="Configure" />
            <PanelBody>
              <div>
                <h3 className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  Datasets
                </h3>
                <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                  Leave everything unchecked to include every dataset visible to
                  you. Checking one or more restricts fusion to exactly those.
                </p>
                <QueryState
                  isLoading={datasetsLoading}
                  error={datasetsError}
                  absenceTitle="Datasets unavailable"
                  skeletonRows={3}
                />
                {datasets && datasets.length === 0 && (
                  <StateBox
                    kind="empty"
                    title="No datasets ingested"
                    detail="Nothing has been ingested into this registry yet."
                    className="mt-2"
                  />
                )}
                {datasets && datasets.length > 0 && (
                  <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto">
                    {datasets.map((dataset) => (
                      <li key={dataset.id}>
                        <label className="flex items-center gap-2 text-xs text-muted-foreground">
                          <input
                            type="checkbox"
                            data-dataset-checkbox={dataset.id}
                            checked={selected.has(dataset.id)}
                            onChange={() => toggleDataset(dataset.id)}
                          />
                          {dataset.name}
                          {dataset.sensor_type && (
                            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                              declared {dataset.sensor_type}
                            </span>
                          )}
                        </label>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="mt-3">
                <label
                  htmlFor="fusion-radius"
                  className="block font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground"
                >
                  Radius (m)
                </label>
                <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                  How close two records must be to cluster into the same sample.
                  Leave blank to use the platform default.
                </p>
                <input
                  id="fusion-radius"
                  data-fusion-radius
                  type="number"
                  min={0}
                  step="any"
                  value={radiusInput}
                  onChange={(e) => {
                    setRadiusInput(e.target.value)
                    resetRunState()
                  }}
                  className="mt-1 w-32 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                />
              </div>

              <label className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  data-fusion-multimodal-only
                  checked={multimodalOnly}
                  onChange={(e) => {
                    setMultimodalOnly(e.target.checked)
                    resetRunState()
                  }}
                />
                Keep only samples that combine two or more sensor types
              </label>

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  data-action="preview-fusion"
                  disabled={running}
                  onClick={() => run(false)}
                >
                  Preview
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  data-action="save-fusion"
                  disabled={!canSave}
                  onClick={() => run(true)}
                >
                  Save these samples
                </Button>
                {saved && (
                  <span className="text-xs text-muted-foreground">
                    Saved. Change a setting and preview again to run another
                    fusion.
                  </span>
                )}
              </div>

              {runError && (
                <StateBox
                  kind="error"
                  className="mt-3"
                  title={saved === null ? 'Run failed' : 'Save failed'}
                  detail={runError}
                />
              )}
            </PanelBody>
          </Panel>

          {shown && (
            <Panel>
              <PanelHeader
                title={saved ? 'Saved' : 'Preview'}
                count={shown.fusion_sample_count}
              />
              <PanelBody>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                  <Field label="Input records">
                    {formatCount(shown.input_record_count)}
                  </Field>
                  <Field label="Fusion samples">
                    {formatCount(shown.fusion_sample_count)}
                  </Field>
                </dl>

                {shown.excluded_from_fusion.length > 0 && (
                  <div className="mt-3">
                    <h3 className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                      Excluded, not fused
                    </h3>
                    <ul className="mt-1 space-y-1.5">
                      {shown.excluded_from_fusion.map((excluded, i) => (
                        <li
                          key={i}
                          data-fusion-excluded
                          className="rounded-lg border border-border px-3 py-2 text-xs"
                        >
                          <span className="text-foreground">
                            {formatCount(excluded.record_count)} record
                            {excluded.record_count === 1 ? '' : 's'}, position kind{' '}
                            {excluded.position_kind}
                          </span>
                          <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                            {excluded.reason}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {shown.samples.length === 0 ? (
                  <StateBox
                    kind="empty"
                    className="mt-3"
                    title="No fusion samples"
                    detail="Nothing in the selected input clustered into a fusion sample with these settings."
                  />
                ) : (
                  <ul className="mt-3 space-y-2">
                    {shown.samples.map((sample, i) => (
                      <li
                        key={i}
                        data-fusion-run-sample
                        className="rounded-lg border border-border px-3 py-2"
                      >
                        <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
                          <Field label="Sensors">{sample.sensor_types.join(', ')}</Field>
                          <Field label="Reference">{sample.spatial_ref_kind}</Field>
                          <Field label="Centre">
                            {sample.spatial_ref_kind === 'geographic'
                              ? sample.center_lat !== null && sample.center_lon !== null
                                ? `${sample.center_lat.toFixed(5)}, ${sample.center_lon.toFixed(5)}`
                                : NO_VALUE
                              : sample.center_x !== null && sample.center_y !== null
                                ? `${sample.center_x.toFixed(2)}, ${sample.center_y.toFixed(2)}`
                                : NO_VALUE}
                          </Field>
                          <Field label="Radius">{formatMetres(sample.radius_m)}</Field>
                          <Field label="Reprojected">{formatCount(sample.n_reprojected)}</Field>
                          <Field label="Ground truth">
                            {sample.has_ground_truth ? 'yes' : 'no'}
                          </Field>
                        </dl>
                        <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                          {Object.entries(sample.record_counts)
                            .map(([sensor, count]) => `${sensor}: ${count}`)
                            .join(', ')}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </PanelBody>
            </Panel>
          )}
        </div>
      </div>
    </>
  )
}
