'use client'

import Link from 'next/link'
import { ArrowRight, Database } from 'lucide-react'
import { AppHeader } from '@/components/shell/app-header'
import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { GroundTruthStatus } from '@/components/subterra/data-status'
import { DatasetActions } from '@/components/datasets/dataset-actions'
import { DatasetStatusBadge } from '@/components/datasets/dataset-status'
import { useDatasets } from '@/hooks/use-subterra'
import { NO_VALUE, formatCount, formatDateTime, formatPercent } from '@/lib/format'
import type { DatasetSummary } from '@/types/subterra'

export default function DatasetsPage() {
  const { data, error, isLoading } = useDatasets()

  return (
    <>
      <AppHeader
        title="Datasets"
        subtitle="Ingested surveys, their frames and their declared spatial references"
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="mx-auto max-w-5xl">
          <Panel>
            <PanelHeader title="Ingested datasets" count={data?.length} />
            <PanelBody>
              <QueryState
                isLoading={isLoading}
                error={error}
                absenceTitle="Datasets unavailable"
                errorTitle="Could not list datasets"
                skeletonRows={4}
              />
              {data && data.length === 0 && (
                <StateBox
                  kind="empty"
                  title="No datasets ingested"
                  detail="Nothing has been ingested into this registry yet. Import one to see it here."
                />
              )}
              {data && data.length > 0 && (
                <ul className="space-y-2">
                  {data.map((dataset) => (
                    <DatasetRow key={dataset.id} dataset={dataset} />
                  ))}
                </ul>
              )}
            </PanelBody>
          </Panel>
        </div>
      </div>
    </>
  )
}

function DatasetRow({ dataset }: { dataset: DatasetSummary }) {
  return (
    <li
      data-dataset-row={dataset.id}
      className="rounded-lg border border-border px-3.5 py-3 transition-colors hover:border-primary/40"
    >
      {/*
        The row is no longer one large link. Rename and delete are buttons, and
        an interactive control cannot live inside another one -- so the title
        links and the actions sit beside it.
      */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-2">
            <Database
              className="size-3.5 shrink-0 translate-y-0.5 text-muted-foreground"
              aria-hidden
            />
            <Link
              href={`/datasets/${encodeURIComponent(dataset.id)}`}
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              {dataset.name}
            </Link>
            {/*
              Phase 7, slice 30. sensor_type is what the dataset claimed at
              ingest, same fact DatasetSummaryPane calls "Declared sensor"
              (slice 25) -- "declared" in the badge text so this compact tag
              reads as the declaration it is, not the recorded instrument.
              The value is unchanged and unreconciled against frames.
            */}
            {dataset.sensor_type && (
              <span className="rounded border border-border px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                declared {dataset.sensor_type}
              </span>
            )}
            {dataset.original_format && (
              <span className="rounded border border-border px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                {dataset.original_format}
              </span>
            )}
          </div>
          {/*
            The ID and the source file are both shown. Two datasets in this
            corpus share a name, so the name alone does not identify one -- and
            the source file is what the name is NOT, which matters the moment
            somebody renames a dataset.
          */}
          <code className="mt-1 block truncate font-mono text-[11px] text-muted-foreground">
            {dataset.id}
          </code>
          {dataset.source_file && (
            <code
              data-source-file
              className="mt-0.5 block truncate font-mono text-[11px] text-muted-foreground"
            >
              from {dataset.source_file}
            </code>
          )}
        </div>
        <DatasetStatusBadge dataset={dataset} />
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-4">
        <Stat label="Records" value={formatCount(dataset.record_count)} />
        <Stat
          label="Quality"
          value={
            dataset.quality_score === null
              ? NO_VALUE
              : formatPercent(dataset.quality_score)
          }
        />
        <Stat label="Ingested" value={formatDateTime(dataset.created_at)} />
        <Stat label="Updated" value={formatDateTime(dataset.updated_at)} />
      </dl>

      <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <GroundTruthStatus hasGroundTruth={dataset.has_ground_truth} />
        <CentreStatus dataset={dataset} />
      </div>

      {/*
        Detection only. Identical source bytes are not the same dataset -- these
        are separate ingestion events, often under different converter
        behaviour -- so this states the relationship and offers no merge.
      */}
      {dataset.shares_source_with.length > 0 && (
        <p data-shares-source className="mt-2 text-xs leading-relaxed text-muted-foreground">
          Ingested from the same source file as {dataset.shares_source_with.length} other
          dataset{dataset.shares_source_with.length === 1 ? '' : 's'}. Separate ingestion
          events are kept separate; they may differ in how they were converted.
        </p>
      )}

      <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
        {dataset.status_reason}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <Link
          href={`/datasets/${encodeURIComponent(dataset.id)}/report`}
          className="text-xs text-primary underline-offset-4 hover:underline"
        >
          Open report
        </Link>
        <span aria-hidden className="text-muted-foreground">
          &middot;
        </span>
        <Link
          href={`/datasets/${encodeURIComponent(dataset.id)}`}
          className="inline-flex items-center gap-1 text-xs text-primary underline-offset-4 hover:underline"
        >
          Open workspace
          <ArrowRight className="size-3" aria-hidden />
        </Link>
      </div>

      <div className="mt-3">
        <DatasetActions dataset={dataset} />
      </div>
    </li>
  )
}


/**
 * The dataset's geographic centre, or a statement that it has none.
 *
 * `center_lat`/`center_lon` are null for a dataset whose records carry no
 * geographic position -- true of most of the corpus held today. That is
 * shown as an absence with its consequence spelled out, never as 0, 0.
 */
function CentreStatus({ dataset }: { dataset: DatasetSummary }) {
  const { center_lat: lat, center_lon: lon } = dataset
  if (lat === null || lon === null) {
    return (
      <span
        data-centre="none"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
      >
        <span
          aria-hidden
          className="size-1.5 rounded-full border border-dashed border-prov-unavailable"
        />
        no geographic centre — not placeable on a map
      </span>
    )
  }
  return (
    <code data-centre="geographic" className="tabular font-mono text-xs text-muted-foreground">
      {lat.toFixed(5)}, {lon.toFixed(5)}
    </code>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </dt>
      <dd className="tabular truncate text-xs text-foreground">{value}</dd>
    </div>
  )
}
