'use client'

import Link from 'next/link'
import { ArrowRight, Database } from 'lucide-react'
import { AppHeader } from '@/components/shell/app-header'
import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { GroundTruthStatus } from '@/components/subterra/data-status'
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
                  detail="Nothing has been ingested into this registry yet. Ingest a dataset through /api/datasets/ingest to see it here."
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
    <li>
      <Link
        href={`/datasets/${encodeURIComponent(dataset.id)}`}
        className="group block rounded-lg border border-border px-3.5 py-3 transition-colors hover:border-primary/40 hover:bg-muted/40"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-2">
              <Database
                className="size-3.5 shrink-0 translate-y-0.5 text-muted-foreground"
                aria-hidden
              />
              <span className="font-medium text-foreground">{dataset.name}</span>
              {dataset.sensor_type && (
                <span className="rounded border border-border px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  {dataset.sensor_type}
                </span>
              )}
            </div>
            <code className="mt-1 block truncate font-mono text-[11px] text-muted-foreground">
              {dataset.id}
            </code>
          </div>
          <ArrowRight
            className="mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground"
            aria-hidden
          />
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
          <Stat label="Source" value={dataset.source ?? NO_VALUE} />
          <Stat label="Ingested" value={formatDateTime(dataset.created_at)} />
        </dl>

        <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <GroundTruthStatus hasGroundTruth={dataset.has_ground_truth} />
          <CentreStatus dataset={dataset} />
        </div>
      </Link>
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
