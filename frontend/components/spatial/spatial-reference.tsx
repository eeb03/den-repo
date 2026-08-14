'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { buttonVariants } from '@/components/ui/button'
import { useSpatialReference } from '@/hooks/use-subterra'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DimensionState, SpatialDimensionName } from '@/types/subterra'
import { DeclarationForm } from './declaration-form'

/**
 * The spatial reference workflow.
 *
 * WHAT THIS SCREEN IS FOR: knowing, proving and communicating what spatial
 * relationship the data actually has to the physical world — and, where the
 * user holds evidence Subterra does not, letting them state it on the record.
 *
 * AN UNRESOLVED DIMENSION IS A RESULT, NOT AN ERROR. Six of the seven
 * dimensions are open for every dataset currently held, and that is the correct
 * answer: the evidence does not exist. So an open dimension is drawn in the
 * same weight as a settled one, with its reason and what would settle it. A
 * screen that rendered them as warnings would teach people to read a truthful
 * answer as a defect to be cleared, and clearing it is exactly what must not
 * happen without evidence.
 *
 * NOTHING IS COMPUTED HERE. Every state, reason and requirement is the
 * backend's own sentence. The component chooses which form to show and renders
 * what came back.
 */
/**
 * Exported so the read-only workspace summary (`AcquisitionPane`'s sibling,
 * `SpatialAssessmentPane`) uses the same seven words rather than keeping a
 * second copy that could drift.
 */
export const DIMENSION_LABEL: Record<SpatialDimensionName, string> = {
  horizontal_position: 'Horizontal position',
  crs: 'Coordinate reference system',
  vertical_reference: 'Vertical reference',
  depth_conversion: 'Depth',
  surface_reference: 'Surface',
  orientation: 'Orientation',
  survey_geometry: 'Survey geometry',
}

/** States that mean the question is settled. Mirrors the backend's own set. */
export const RESOLVED_SPATIAL_STATES = new Set([
  'available', 'declared', 'measured', 'derived',
])

export function SpatialReferenceView({ datasetId }: { datasetId: string }) {
  const { data, error, isLoading } = useSpatialReference(datasetId)
  const [open, setOpen] = useState<SpatialDimensionName | null>(null)

  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-10">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Spatial reference
          </p>
          <h1 className="mt-1 text-xl font-semibold tracking-tight text-foreground">
            {datasetId}
          </h1>
        </div>
        <Link
          href={`/datasets/${encodeURIComponent(datasetId)}/report`}
          className="shrink-0 text-xs text-primary underline-offset-4 hover:underline"
        >
          Back to report
        </Link>
      </div>

      <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
        What relationship this dataset has to the physical world, and where that
        relationship is not established. An unresolved dimension is a correct answer:
        Subterra will not supply spatial evidence it does not have.
      </p>

      <QueryState
        isLoading={isLoading}
        error={error}
        absenceTitle="No spatial reference available"
        errorTitle="Could not load the spatial reference"
        skeletonRows={5}
      />

      {data && (
        <div className="mt-6 space-y-5">
          {data.has_stale_products && (
            <Panel>
              <PanelHeader title="Downstream results are out of date" />
              <PanelBody>
                <p data-stale-products className="text-xs leading-relaxed text-muted-foreground">
                  A spatial declaration has been made since these were computed, so they
                  describe a different reference than the one now in force. Nothing has
                  been recomputed automatically — re-running them silently would hide the
                  change.
                </p>
                <ul className="mt-2 space-y-1">
                  {data.stale_products.map((product) => (
                    <li key={product} className="font-mono text-[11px] text-muted-foreground">
                      {product}
                    </li>
                  ))}
                </ul>
              </PanelBody>
            </Panel>
          )}

          <Panel>
            <PanelHeader title="Spatial dimensions" />
            <PanelBody>
              {data.dimensions.map((dimension) => (
                <DimensionRow
                  key={dimension.dimension}
                  datasetId={datasetId}
                  dimension={dimension}
                  open={open === dimension.dimension}
                  onToggle={() =>
                    setOpen(open === dimension.dimension ? null : dimension.dimension)
                  }
                />
              ))}
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader title="Declarations" count={data.declarations.length} />
            <PanelBody>
              {data.declarations.length === 0 ? (
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Nothing has been declared for this dataset. Everything above comes from
                  what the source itself stated.
                </p>
              ) : (
                <ul className="space-y-2.5">
                  {data.declarations.map((declaration) => (
                    <li key={declaration.id} data-declaration={declaration.kind}>
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="text-xs text-foreground">
                          {DIMENSION_LABEL[
                            declaration.kind as unknown as SpatialDimensionName
                          ] ?? declaration.kind.replace(/_/g, ' ')}
                        </span>
                        <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                          {formatDateTime(declaration.created_at)}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                        Established by {declaration.supplied_by}. Recorded as a declaration,
                        not a measurement.
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </PanelBody>
          </Panel>
        </div>
      )}
    </main>
  )
}

function DimensionRow({
  datasetId,
  dimension,
  open,
  onToggle,
}: {
  datasetId: string
  dimension: DimensionState
  open: boolean
  onToggle: () => void
}) {
  const resolved = RESOLVED_SPATIAL_STATES.has(dimension.state)
  return (
    <div
      data-dimension={dimension.dimension}
      data-state={dimension.state}
      data-resolved={String(resolved)}
      className="border-t border-border py-3 first:border-t-0"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h4 className={cn('text-sm font-medium', resolved ? 'text-foreground' : 'text-muted-foreground')}>
          {DIMENSION_LABEL[dimension.dimension]}
        </h4>
        <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          {dimension.state}
        </span>
      </div>

      <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{dimension.reason}</p>

      {dimension.missing.length > 0 && (
        <ul className="mt-2 space-y-1">
          {dimension.missing.map((item) => (
            <li
              key={item}
              data-missing
              className="flex gap-2 text-xs leading-relaxed text-muted-foreground"
            >
              <span aria-hidden className="select-none text-primary">
                &middot;
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}

      {dimension.action && (
        <div className="mt-2.5">
          <button
            type="button"
            data-action={`resolve-${dimension.dimension}`}
            onClick={onToggle}
            className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
          >
            {open ? 'Cancel' : 'Establish this'}
          </button>
          {open && (
            <DeclarationForm
              datasetId={datasetId}
              kind={dimension.action}
              onDone={onToggle}
              onCancel={onToggle}
            />
          )}
        </div>
      )}
    </div>
  )
}
