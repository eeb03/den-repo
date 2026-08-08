'use client'

import { Field, SectionLabel } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { GroundTruthStatus } from '@/components/subterra/data-status'
import { useDatasetInfo } from '@/hooks/use-subterra'
import { NO_VALUE, formatCount, formatMetres, formatPercent } from '@/lib/format'

/**
 * Dataset metadata, from `GET /api/datasets/{id}/info`.
 *
 * The endpoint's own docstring notes it "deliberately does NOT include
 * fields like 'ground conditions' or 'estimated penetration depth' that
 * would require domain assumptions we have no basis for". This pane keeps
 * that discipline: it shows what the endpoint returns and nothing more.
 *
 * `survey_area_m` and `grid_resolution_m` are null for a dataset with no
 * geographically positioned records. Null renders as an explained absence,
 * never as a zero-sized survey.
 */
export function DatasetSummaryPane({ datasetId }: { datasetId: string }) {
  const { data, error, isLoading } = useDatasetInfo(datasetId)

  return (
    <>
      <SectionLabel>Metadata</SectionLabel>
      <QueryState
        isLoading={isLoading}
        error={error}
        absenceTitle="Dataset info unavailable"
        errorTitle="Could not load dataset info"
      />
      {data && (
        <dl className="space-y-0">
          <Field label="Name">{data.name}</Field>
          <Field label="Sensor">{data.sensor_type ?? NO_VALUE}</Field>
          <Field label="Format">{data.original_format ?? NO_VALUE}</Field>
          <Field label="Source">{data.source ?? NO_VALUE}</Field>
          <Field label="Licence">{data.license ?? NO_VALUE}</Field>
          <Field label="Records">{formatCount(data.record_count)}</Field>
          <Field label="Quality">
            {data.quality_score === null
              ? NO_VALUE
              : formatPercent(data.quality_score)}
          </Field>
          <Field label="Ground truth">
            <GroundTruthStatus hasGroundTruth={data.has_ground_truth} />
          </Field>
          <Field label="CRS">
            <code className="font-mono text-[11px]">
              {Array.isArray(data.coordinate_system)
                ? data.coordinate_system.join(', ') || NO_VALUE
                : data.coordinate_system}
            </code>
          </Field>
          <Field label="Positioned">
            {/*
              How many records actually carry a geographic position. Zero is
              a real and common answer here, and is stated rather than
              hidden -- it is what makes the map empty.
            */}
            <span
              className={
                data.geographic_record_count === 0
                  ? 'text-muted-foreground'
                  : 'text-foreground'
              }
            >
              {formatCount(data.geographic_record_count)} of{' '}
              {formatCount(data.record_count)}
            </span>
          </Field>
          <Field label="Survey area">
            {data.survey_area_m ? (
              <span className="tabular">
                {formatMetres(data.survey_area_m.lat_span)} &times;{' '}
                {formatMetres(data.survey_area_m.lon_span)}
              </span>
            ) : (
              <span className="text-muted-foreground">
                {NO_VALUE} — no positioned records to take an extent from
              </span>
            )}
          </Field>
          <Field label="Grid res.">
            {data.grid_resolution_m === null ? (
              <span className="text-muted-foreground">{NO_VALUE}</span>
            ) : (
              formatMetres(data.grid_resolution_m, 3)
            )}
          </Field>
          <Field label="Depth layers">
            {data.depth_layers && data.depth_layers.length > 0 ? (
              formatCount(data.depth_layers.length)
            ) : (
              <span className="text-muted-foreground">none</span>
            )}
          </Field>
          <Field label="Position src">
            <span className="font-mono text-[11px]">
              {Object.entries(data.position_sources ?? {})
                .map(([kind, n]) => `${kind}: ${formatCount(n)}`)
                .join(', ') || NO_VALUE}
            </span>
          </Field>
        </dl>
      )}
    </>
  )
}
