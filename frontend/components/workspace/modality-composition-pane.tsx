'use client'

import { SectionLabel } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { useDatasetInfo } from '@/hooks/use-subterra'
import { formatCount } from '@/lib/format'

/**
 * The Phase 7 recorded modality composition of this dataset's survey
 * frames, from the same `GET /api/datasets/{id}/info` payload
 * `DatasetSummaryPane` already fetches -- through the same `useDatasetInfo`
 * hook, so SWR dedupes the two rather than issuing a second request.
 *
 * A DATASET-LEVEL FACT, NOT THE INGEST DECLARATION. `DatasetSummaryPane`'s
 * "Sensor" field is `dataset.sensor_type`, what the dataset claimed at
 * ingest; this pane follows `survey_frames[].modality`, what each frame was
 * actually recorded as. The two can disagree -- a dataset declared `gpr`
 * that also carries a `lidar` frame is not corrected here, and the extra
 * modality is not hidden. Neither field is touched or collapsed into the
 * other.
 *
 * COMPOSITION, NOT FUSION. This names which modalities this dataset's
 * frames record, verbatim, with a frame count per modality (a stored count,
 * not a new claim). It never says "fused", "multi-modal sample", "aligned",
 * or "ready for fusion" -- Phase 7 is that the core model is not tied to one
 * sensor, not that any spatial agreement between modalities has been
 * computed. No fusion GET or POST, no `/api/fusion/samples` read.
 *
 * ONE RECORDED MODALITY IS A COMPLETE, HONEST ANSWER. It is the common case
 * and not a failure: never rendered as "GPR-only", "incomplete", or
 * "waiting for" another modality.
 *
 * NO FRAMES, OR NO FRAME NAMES A MODALITY, IS AN EXPLICIT ABSENCE -- never a
 * synthetic `gpr`.
 *
 * READ-ONLY. No fusion control, no generate control here.
 */
export function ModalityCompositionPane({ datasetId }: { datasetId: string }) {
  const { data, error, isLoading } = useDatasetInfo(datasetId)

  const frames = data?.survey_frames ?? []
  const counts = new Map<string, number>()
  for (const frame of frames) {
    if (!frame.modality) continue
    counts.set(frame.modality, (counts.get(frame.modality) ?? 0) + 1)
  }
  const modalities = Array.from(counts.keys()).sort()

  return (
    <>
      <SectionLabel count={data ? modalities.length : undefined}>
        Modality composition
      </SectionLabel>
      <QueryState
        isLoading={isLoading}
        error={error}
        absenceTitle="Modality composition unavailable"
        errorTitle="Could not load modality composition"
      />

      {data && modalities.length === 0 && (
        <StateBox
          kind="empty"
          title="No recorded modality"
          detail={
            frames.length === 0
              ? 'this dataset has no survey frames'
              : 'no survey frame in this dataset records a modality'
          }
        />
      )}

      {data && modalities.length > 0 && (
        <ul data-modality-composition className="space-y-1">
          {modalities.map((modality) => (
            <li
              key={modality}
              data-modality={modality}
              className="flex items-baseline justify-between gap-3"
            >
              <span className="text-xs text-foreground">{modality}</span>
              <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                {formatCount(counts.get(modality))} frame(s)
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
