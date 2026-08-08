'use client'

import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { useTraceGrid } from '@/hooks/use-subterra'
import type { Selection } from '@/types/subterra'

/**
 * The centre column: map over radargram.
 *
 * These panes are wired to real data but do not yet DRAW anything -- the
 * existing Plotly implementation in `visualization/` remains authoritative
 * for spatial rendering and is integrated in the next step, rather than
 * being reimplemented in React alongside it. What is real here is the
 * decision about whether there is anything to draw at all, which comes
 * from the backend.
 */
export function SpatialPanes({
  datasetId,
  selection,
  placedCount,
  totalCount,
  loading,
}: {
  datasetId: string
  selection: Selection | null
  /** Objects + labels carrying a geographic position. */
  placedCount: number
  totalCount: number
  loading: boolean
}) {
  return (
    <div className="grid min-h-0 grid-rows-2 gap-3">
      <Panel>
        <PanelHeader
          title="Map"
          count={placedCount}
          action={
            <span className="text-[11px] text-muted-foreground">
              marker shape encodes position provenance
            </span>
          }
        />
        <PanelBody className="subterra-grid flex items-center justify-center">
          <div className="w-full max-w-md">
            {loading ? (
              <QueryState isLoading error={null} skeletonRows={2} />
            ) : placedCount > 0 ? (
              <StateBox
                kind="empty"
                title={`${placedCount} item${placedCount === 1 ? '' : 's'} ready to plot`}
                detail="Rendering is handled by the existing Plotly map, integrated in the next step. Until then the count is shown rather than an approximate drawing."
              />
            ) : (
              <StateBox
                kind="unpositioned"
                title="Nothing to plot"
                detail={
                  totalCount > 0
                    ? `None of the ${totalCount} object(s) and label(s) in this dataset has a geographic position. They are listed under "Not on the map" and remain available through the API.`
                    : 'This dataset has no objects or labels with a geographic position. Nothing is drawn at a default coordinate.'
                }
              />
            )}
          </div>
        </PanelBody>
      </Panel>

      <RadargramPane datasetId={datasetId} selection={selection} />
    </div>
  )
}

function RadargramPane({
  datasetId,
  selection,
}: {
  datasetId: string
  selection: Selection | null
}) {
  const { data, error, isLoading } = useTraceGrid(
    datasetId,
    selection?.source_file ?? null,
  )

  /*
   * The vertical axis is a DEPTH only when the backend returned depths --
   * which happens only when a propagation velocity was supplied at ingest.
   * Otherwise it is a sample index and is labelled as one. The client never
   * converts between the two; doing so would mean assuming a velocity.
   */
  const verticalAxis = data?.depths
    ? 'depth (m, derived from an assumed velocity)'
    : 'sample index'

  return (
    <Panel>
      <PanelHeader
        title="Radargram"
        action={
          data ? (
            <span className="text-[11px] text-muted-foreground">
              y = {verticalAxis}
            </span>
          ) : undefined
        }
      />
      <PanelBody className="subterra-grid flex items-center justify-center">
        <div className="w-full max-w-md">
          <QueryState
            isLoading={isLoading}
            error={error}
            absenceTitle="No radar data"
            errorTitle="Could not load the radargram"
            skeletonRows={2}
          />
          {data && (
            <StateBox
              kind="empty"
              title={
                data.grid?.length
                  ? `Trace grid loaded — ${data.grid.length} rows x ${data.trace_indices?.length ?? 0} traces`
                  : 'Empty radargram'
              }
              detail={
                data.grid?.length
                  ? 'Rendering is handled by the existing Plotly heatmap, integrated in the next step.'
                  : 'The line returned no samples.'
              }
            />
          )}
        </div>
      </PanelBody>
    </Panel>
  )
}
