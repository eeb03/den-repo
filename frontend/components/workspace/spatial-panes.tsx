'use client'

import { useState } from 'react'
import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { EmbeddedThinClient, EmbeddedViewer } from './embedded-viewer'
import { useTraceGrid } from '@/hooks/use-subterra'
import type { Selection } from '@/types/subterra'

type SpatialTab = 'viewer' | 'client'

/**
 * The centre column: the spatial view above, the radargram below.
 *
 * The spatial view is the EXISTING implementation, embedded rather than
 * reimplemented -- see `embedded-viewer.tsx` for why, and for the guard
 * that keeps an unpositioned dataset out of a viewer that would plot it at
 * null island.
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
  placedCount: number
  totalCount: number
  loading: boolean
}) {
  const [tab, setTab] = useState<SpatialTab>('viewer')

  return (
    <div className="grid min-h-0 grid-rows-[1.35fr_1fr] gap-3">
      <Panel>
        <PanelHeader
          title="Spatial"
          count={placedCount || undefined}
          action={
            <div className="flex items-center gap-0.5 rounded-lg bg-muted p-0.5">
              <TabButton active={tab === 'viewer'} onClick={() => setTab('viewer')}>
                3D viewer
              </TabButton>
              <TabButton active={tab === 'client'} onClick={() => setTab('client')}>
                Thin client
              </TabButton>
            </div>
          }
        />
        <div className="min-h-0 flex-1">
          {tab === 'viewer' ? (
            <EmbeddedViewer datasetId={datasetId} />
          ) : (
            <div className="flex h-full flex-col">
              <p className="border-b border-border px-3.5 py-1.5 text-[11px] leading-relaxed text-muted-foreground">
                The thin client opens on its own first dataset — it takes no
                dataset parameter, so it does not follow the selection above.
              </p>
              <div className="min-h-0 flex-1">
                <EmbeddedThinClient />
              </div>
            </div>
          )}
        </div>
      </Panel>

      <RadargramPane
        datasetId={datasetId}
        selection={selection}
        totalCount={totalCount}
        loading={loading}
      />
    </div>
  )
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-md px-2 py-0.5 text-[11px] transition-colors ${
        active
          ? 'bg-background text-foreground shadow-sm'
          : 'text-muted-foreground hover:text-foreground'
      }`}
    >
      {children}
    </button>
  )
}

/**
 * The radargram.
 *
 * Backed by `GET /api/datasets/{id}/trace_grid`. Every dataset currently
 * held returns 400 with "records are missing trace_index/depth metadata --
 * not genuine multi-sample GPR trace data", which is a statement about the
 * data rather than a failure, and is rendered as the backend worded it.
 *
 * When a grid does arrive, the vertical axis is a DEPTH only if the
 * backend returned depths -- which happens only when a propagation
 * velocity was supplied at ingest. Otherwise it is a sample index and is
 * labelled as one. No conversion is performed here; doing so would mean
 * assuming a velocity.
 */
function RadargramPane({
  datasetId,
  selection,
  totalCount,
  loading,
}: {
  datasetId: string
  selection: Selection | null
  totalCount: number
  loading: boolean
}) {
  const { data, error, isLoading } = useTraceGrid(
    datasetId,
    selection?.source_file ?? null,
  )

  const verticalAxis = data?.depths
    ? 'depth (m, derived from an assumed velocity)'
    : 'sample index'

  return (
    <Panel>
      <PanelHeader
        title="Radargram"
        action={
          data?.grid?.length ? (
            <span className="text-[11px] text-muted-foreground">
              y = {verticalAxis}
            </span>
          ) : undefined
        }
      />
      <PanelBody className="subterra-grid flex items-center justify-center">
        <div className="w-full max-w-lg">
          <QueryState
            isLoading={isLoading || loading}
            error={error}
            absenceTitle="No radar data for this dataset"
            errorTitle="Could not load the radargram"
            skeletonRows={2}
          />
          {data &&
            (data.grid?.length ? (
              <StateBox
                kind="empty"
                title={`Trace grid available — ${data.grid.length} samples x ${data.trace_indices?.length ?? 0} traces`}
                detail={
                  `The vertical axis is ${verticalAxis}. Use the 3D viewer's B-scan mode above to ` +
                  `render it; the heatmap is drawn by the existing Plotly implementation rather than ` +
                  `redrawn here.`
                }
              />
            ) : (
              <StateBox
                kind="empty"
                title="Empty radargram"
                detail="The line returned no samples."
              />
            ))}
          {!data && !error && !isLoading && totalCount === 0 && null}
        </div>
      </PanelBody>
    </Panel>
  )
}
