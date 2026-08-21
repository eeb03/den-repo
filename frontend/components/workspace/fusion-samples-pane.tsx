'use client'

import { Field, SectionLabel } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { useFusionSamples } from '@/hooks/use-subterra'
import { NO_VALUE, formatCount, formatMetres, formatMetric } from '@/lib/format'

/**
 * Phase 7, slice 26. The first workspace surface for `GET
 * /api/fusion/samples` -- read-only, and filtered client-side to this
 * dataset, since the endpoint itself is global (`useFusionSamples`, no
 * dataset id). A sample whose `dataset_ids` does not include this dataset is
 * not this dataset's fact and is treated as absent here.
 *
 * NOT A RUN CONTROL. There is no button here, and nothing here calls
 * `POST /api/fusion/run`. This pane only names stored samples that already
 * exist; whether or when to compute a new one is a decision this pane does
 * not make and does not invite.
 *
 * A STORED SAMPLE IS NOT A FUSION CLAIM. `sensor_types` is printed verbatim,
 * as stored -- `["gpr", "lidar"]` is a list of what was represented, not a
 * claim that the two were "fused", "aligned", or are "ready for fusion".
 * `has_ground_truth` is printed as the stored boolean, never upgraded to
 * "validated" or "confirmed targets".
 *
 * ZERO STORED SAMPLES IS NOT "HAS NOT BEEN RUN". `ModalityCompositionPane`
 * already names this dataset's recorded modalities; a dataset with several
 * modalities in its frames and zero stored fusion samples still gets the
 * same plain absence a single-modality dataset would -- composition is not
 * fusion, and this pane never implies one is owed because of the other.
 *
 * CENTRE IS SHOWN IN WHATEVER FRAME THE SAMPLE WAS ACTUALLY CLUSTERED IN.
 * `spatial_ref_kind` says which pair is meaningful: `center_lat`/
 * `center_lon` for `"geographic"`, `center_x`/`center_y` otherwise. A
 * missing value renders as the explained absence, never a fabricated
 * geographic centre for a sample that was never geographic.
 *
 * RADIUS AND REPROJECTED COUNT ARE PRINTED, NOT INTERPRETED (Phase 7, slice
 * 28). `radius_m` is the stored clustering radius, not "accuracy" or
 * "tolerance". `n_reprojected` is the stored count of member records that
 * reached this centre through a CRS transform rather than carrying a
 * geographic coordinate of their own -- printed as the integer it is,
 * including a genuine `0`, which is never omitted or read as "native
 * coordinates". Neither field changes how Centre renders: this pane states
 * the fact and leaves the reading of it to whoever looks, the same
 * discipline `ModalityCompositionPane` and the candidate panes already
 * hold.
 */
export function FusionSamplesPane({ datasetId }: { datasetId: string }) {
  const { data, error, isLoading } = useFusionSamples()

  const samples = (data ?? []).filter((s) => s.dataset_ids.includes(datasetId))

  return (
    <>
      <SectionLabel count={data ? samples.length : undefined}>
        Fusion samples
      </SectionLabel>
      <QueryState
        isLoading={isLoading}
        error={error}
        absenceTitle="Fusion samples unavailable"
        errorTitle="Could not load fusion samples"
      />

      {data && samples.length === 0 && (
        <StateBox
          kind="empty"
          title="No fusion samples"
          detail="no stored fusion sample includes this dataset"
        />
      )}

      {data && samples.length > 0 && (
        <ul data-fusion-samples className="space-y-2">
          {samples.map((sample) => (
            <li
              key={sample.id}
              data-fusion-sample={sample.id}
              className="rounded border border-border px-2 py-1.5"
            >
              <dl className="space-y-0">
                <Field label="Sensors">
                  {sample.sensor_types.join(', ') || NO_VALUE}
                </Field>
                <Field label="Reference">{sample.spatial_ref_kind}</Field>
                <Field label="Centre">
                  {sample.spatial_ref_kind === 'geographic' ? (
                    <span className="tabular">
                      {formatMetric(sample.center_lat, 6)},{' '}
                      {formatMetric(sample.center_lon, 6)}
                    </span>
                  ) : (
                    <span className="tabular">
                      {formatMetric(sample.center_x, 2)},{' '}
                      {formatMetric(sample.center_y, 2)}
                    </span>
                  )}
                </Field>
                <Field label="Radius">{formatMetres(sample.radius_m)}</Field>
                <Field label="Reprojected">{formatCount(sample.n_reprojected)}</Field>
                <Field label="Datasets">
                  <span className="font-mono text-[11px]">
                    {sample.dataset_ids.join(', ') || NO_VALUE}
                  </span>
                </Field>
                <Field label="Ground truth">
                  {sample.has_ground_truth ? 'true' : 'false'}
                </Field>
              </dl>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
