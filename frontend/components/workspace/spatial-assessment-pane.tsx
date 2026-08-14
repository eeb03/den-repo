'use client'

import Link from 'next/link'
import { SectionLabel } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import {
  DIMENSION_LABEL,
  RESOLVED_SPATIAL_STATES,
} from '@/components/spatial/spatial-reference'
import { useSpatialReference } from '@/hooks/use-subterra'
import { cn } from '@/lib/utils'

/**
 * The Stage 8 spatial assessment, made visible where a dataset is opened.
 *
 * READ-ONLY. Before this, the only way to see "where is this in the world,
 * and what is still unknown" was to leave the workspace for `/spatial`. This
 * pane answers Phase 4's five questions -- horizontal position, vertical
 * reference, orientation, surface, coordinate reference system -- from the
 * SAME `GET /api/spatial/{id}` call `/spatial` makes, through the same
 * `useSpatialReference` hook. It renders every dimension the endpoint
 * returns; nothing here recomputes a state, a reason or a missing list.
 *
 * AN UNRESOLVED DIMENSION IS A RESULT, drawn at the same weight as a settled
 * one -- not as a warning, not as an error. That is the same rule `/spatial`
 * follows, and this pane reuses its label map and its resolved-state set
 * (`DIMENSION_LABEL`, `RESOLVED_SPATIAL_STATES`) rather than keeping a
 * second copy that could drift.
 *
 * NO DECLARATION CONTROL. `/datasets/{id}/spatial` remains the only place a
 * declaration is made; this pane only links there.
 *
 * A session's declared `coordinate_system` / `vertical_reference` (see
 * `AcquisitionPane`) are the operator's own words and never appear here --
 * this pane is the Stage 8 assessment, not a session claim.
 *
 * `common_frame` is printed the same way: `state` and `reason` verbatim, at
 * the same weight as a dimension. It is a COMPOSITION of the seven
 * dimensions above, not an eighth one -- `inputs_present` says only that
 * every Phase 4 input is itself resolved, never that a frame has been
 * computed. No control here changes it; it is derived, not declared.
 */
export function SpatialAssessmentPane({ datasetId }: { datasetId: string }) {
  const { data, error, isLoading } = useSpatialReference(datasetId)

  return (
    <>
      <SectionLabel count={data?.dimensions.length}>Spatial assessment</SectionLabel>
      <QueryState
        isLoading={isLoading}
        error={error}
        absenceTitle="Spatial assessment unavailable"
        errorTitle="Could not load the spatial assessment"
      />

      {data && (
        <div data-spatial-assessment className="space-y-2.5">
          {data.dimensions.map((dimension) => {
            const resolved = RESOLVED_SPATIAL_STATES.has(dimension.state)
            return (
              <div
                key={dimension.dimension}
                data-dimension={dimension.dimension}
                data-state={dimension.state}
                data-resolved={String(resolved)}
              >
                <div className="flex items-baseline justify-between gap-3">
                  <span
                    className={cn(
                      'text-xs',
                      resolved ? 'text-foreground' : 'text-muted-foreground',
                    )}
                  >
                    {DIMENSION_LABEL[dimension.dimension]}
                  </span>
                  <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                    {dimension.state}
                  </span>
                </div>
                <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                  {dimension.reason}
                </p>
              </div>
            )
          })}

          {/*
            THE COMPOSITION, NOT AN EIGHTH DIMENSION. `common_frame.state` is
            `incomplete` or `inputs_present` -- never a word that could be
            read as "a frame exists", because none does: this states only
            whether the six Phase 4 inputs are each individually resolved.
            Same weight as a dimension row, same rule for unresolved-as-result.
          */}
          <div
            data-common-frame
            data-state={data.common_frame.state}
            className="border-t border-border/60 pt-2"
          >
            <div className="flex items-baseline justify-between gap-3">
              <span
                className={cn(
                  'text-xs',
                  data.common_frame.state === 'inputs_present'
                    ? 'text-foreground'
                    : 'text-muted-foreground',
                )}
              >
                Common spatial frame
              </span>
              <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                {data.common_frame.state}
              </span>
            </div>
            <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
              {data.common_frame.reason}
            </p>
          </div>

          <Link
            href={`/datasets/${encodeURIComponent(datasetId)}/spatial`}
            className="mt-1 inline-flex text-xs text-primary underline-offset-4 hover:underline"
          >
            Spatial reference
          </Link>
        </div>
      )}
    </>
  )
}
