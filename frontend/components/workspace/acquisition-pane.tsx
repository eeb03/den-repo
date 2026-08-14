'use client'

import Link from 'next/link'
import { Field, SectionLabel } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { useDatasetAcquisition } from '@/hooks/use-subterra'
import { NO_VALUE, formatDateTime } from '@/lib/format'

/**
 * Where this dataset came from, from `GET /api/datasets/{id}/acquisition`.
 *
 * THREE STATES, EACH READ STRAIGHT FROM THE PAYLOAD, NONE INFERRED. The
 * backend already tells the whole story -- device -> session -> acquisition
 * -> dataset -- and this pane's only job is to stop it from staying
 * invisible. Before this, opening a dataset that came from a recorded
 * device session looked identical to opening an unattributed drop.
 *
 * A dataset that predates the acquisition boundary is not an error: it is
 * every published reference corpus, and the backend's own `reason` renders
 * as an absence. A FileDrop dataset says so explicitly -- a file is a
 * source in its own right, not a session with a missing device. Neither
 * state is reconstructed here; both are exactly what the endpoint returned.
 *
 * `survey_area` and `coordinate_system` are the operator's own words, not
 * measurements. Neither settles Stage 8's spatial assessment -- a session
 * can claim "EPSG:32633" and the dataset's `crs` dimension stays exactly
 * what the frames and declarations actually say.
 */
export function AcquisitionPane({ datasetId }: { datasetId: string }) {
  const { data, error, isLoading } = useDatasetAcquisition(datasetId)

  return (
    <>
      <SectionLabel>Acquisition</SectionLabel>
      <QueryState
        isLoading={isLoading}
        error={error}
        absenceTitle="Acquisition unavailable"
        errorTitle="Could not load acquisition"
      />

      {data && !data.acquisition && (
        <StateBox kind="empty" title="No acquisition record" detail={data.reason} />
      )}

      {data && data.acquisition && !data.session && (
        <p
          data-acquisition-kind="file_drop"
          className="text-xs leading-relaxed text-muted-foreground"
        >
          This dataset arrived as a dropped file — a source in its own right,
          not through a recorded device session.
        </p>
      )}

      {data && data.session && (
        <dl className="space-y-0" data-acquisition-kind="session">
          <Field label="Device">
            {[data.device?.manufacturer, data.device?.model]
              .filter(Boolean)
              .join(' ') ||
              data.device?.device_type ||
              NO_VALUE}
            {data.device?.is_simulated && (
              <span
                data-simulated
                className="ml-2 rounded border border-border px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-muted-foreground"
              >
                Simulated — not real hardware
              </span>
            )}
          </Field>
          <Field label="Session">{data.session.state}</Field>
          {data.session.operator && (
            <Field label="Operator">{data.session.operator}</Field>
          )}
          {data.session.survey_area && (
            <Field label="Survey area">{data.session.survey_area}</Field>
          )}
          {data.session.coordinate_system && (
            // A declared claim, not a Stage 8 registration -- see the
            // module docstring. Rendered as the operator's own words, with
            // no EPSG validation and no resolve control.
            <Field label="Coordinate system (declared)">
              {data.session.coordinate_system}
            </Field>
          )}
          <Field label="Acquired">
            {formatDateTime(data.acquisition?.created_at)}
          </Field>
          <Link
            href="/devices"
            className="mt-2 inline-flex text-xs text-primary underline-offset-4 hover:underline"
          >
            Devices &amp; sessions
          </Link>
        </dl>
      )}
    </>
  )
}
