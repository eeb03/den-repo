'use client'

import { useState } from 'react'
import Link from 'next/link'
import { AppHeader } from '@/components/shell/app-header'
import {
  Panel,
  PanelBody,
  PanelHeader,
  SectionLabel,
} from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { NotOnMap, type UnplacedItem } from '@/components/subterra/not-on-map'
import { ProvenanceTag } from '@/components/subterra/provenance-tag'
import { ConfidenceValue } from '@/components/subterra/confidence-value'
import { SpatialRefStatus } from '@/components/subterra/data-status'
import { SelectionPane } from './selection-pane'
import { SpatialPanes } from './spatial-panes'
import { AcquisitionPane } from './acquisition-pane'
import { SpatialAssessmentPane } from './spatial-assessment-pane'
import { SignalChainPane } from './signal-chain-pane'
import { CandidateRegionsPane } from './candidate-regions-pane'
import { DatasetSummaryPane } from './dataset-summary-pane'
import { ModalityCompositionPane } from './modality-composition-pane'
import { FusionSamplesPane } from './fusion-samples-pane'
import { DatasetSwitcher } from './dataset-switcher'
import { ProvenancePane } from './provenance-pane'
import {
  useLabels,
  useDatasets,
  useLayers,
  useObjects,
} from '@/hooks/use-subterra'
import { isGeographic, type Selection } from '@/types/subterra'

/**
 * The dataset workspace.
 *
 * Three panes mirroring `visualization/thin_client.html`, because that page
 * is the platform's reference for how this data may honestly be shown:
 * placed things on the map, unplaced things listed with their reason, and
 * every view's availability answered by the backend.
 *
 * Selection identity is built ONLY from identifiers the API already
 * returned, then POSTed to /api/views/resolve. This component decides
 * nothing about what can be displayed.
 */
export function DatasetWorkspace({ datasetId }: { datasetId: string }) {
  const [selection, setSelection] = useState<Selection | null>(null)

  // The switcher already lists every dataset, so the name costs no request.
  const dataset = useDatasets().data?.find((d) => d.id === datasetId)
  const layers = useLayers(datasetId)
  const objects = useObjects(datasetId)
  const labels = useLabels(datasetId)

  const placedObjects = (objects.data?.objects ?? []).filter((o) =>
    isGeographic(o.position),
  )
  const placedLabels = (labels.data?.labels ?? []).filter((l) =>
    isGeographic(l.position),
  )

  const unplaced: UnplacedItem[] = [
    ...(objects.data?.objects ?? [])
      .filter((o) => !isGeographic(o.position))
      .map((o) => ({ id: o.id, itemType: 'object', position: o.position })),
    ...(labels.data?.labels ?? [])
      .filter((l) => !isGeographic(l.position))
      .map((l) => ({ id: l.id, itemType: 'label', position: l.position })),
  ]

  return (
    <>
      {/*
        The NAME leads and the id follows. A rename has to be visible here or
        the user cannot tell which dataset they renamed -- the list and the
        report already show it. Falling back to the id rather than to a
        placeholder means the header never claims a name the platform does not
        have yet, which is the same rule the rest of the workspace follows.
      */}
      <AppHeader
        title={dataset?.name ?? 'Dataset workspace'}
        subtitle={datasetId}
        actions={<DatasetSwitcher datasetId={datasetId} />}
      />

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 lg:grid-cols-[18rem_minmax(0,1fr)] xl:grid-cols-[18rem_minmax(0,1fr)_21rem]">
        {/* ------------------------------ left ------------------------------ */}
        <Panel className="min-h-0">
          <PanelHeader title="Dataset" />
          <PanelBody className="pt-0">
            <DatasetSummaryPane datasetId={datasetId} />

            <ModalityCompositionPane datasetId={datasetId} />

            <FusionSamplesPane datasetId={datasetId} />

            <AcquisitionPane datasetId={datasetId} />

            <SpatialAssessmentPane datasetId={datasetId} />

            <SignalChainPane datasetId={datasetId} />

            <CandidateRegionsPane datasetId={datasetId} />

            {/*
              The report answers what this workspace cannot: how far the
              dataset can be trusted and what Subterra may legitimately do
              with it. Linked rather than embedded -- it is a page-length
              answer, and burying it in a sidebar is how a limitation goes
              unread.
            */}
            <Link
              href={`/datasets/${encodeURIComponent(datasetId)}/report`}
              className="mt-3 inline-flex text-xs text-primary underline-offset-4 hover:underline"
            >
              View dataset report
            </Link>

            <SectionLabel count={layers.data?.layer_count}>Layers</SectionLabel>
            <QueryState
              isLoading={layers.isLoading}
              error={layers.error}
              absenceTitle="Layers unavailable"
              errorTitle="Could not load layers"
            />
            {layers.data &&
              (layers.data.layers.length === 0 ? (
                <StateBox
                  kind="empty"
                  title="No layers"
                  detail="This dataset has no survey frames."
                />
              ) : (
                <ul className="space-y-1.5">
                  {layers.data.layers.map((layer) => {
                    const active =
                      selection?.kind === 'frame' &&
                      selection.selection_id === layer.frame_id
                    return (
                      <li key={layer.layer_id}>
                        <button
                          type="button"
                          aria-pressed={active}
                          onClick={() =>
                            setSelection({
                              kind: 'frame',
                              dataset_id: datasetId,
                              selection_id: layer.frame_id,
                              frame_id: layer.frame_id,
                              source_file: layer.source_format
                                ? undefined
                                : undefined,
                            })
                          }
                          className={`w-full rounded-lg border px-2.5 py-2 text-left transition-colors ${
                            active
                              ? 'border-primary/50 bg-primary/10'
                              : 'border-border hover:border-primary/30 hover:bg-muted/40'
                          }`}
                        >
                          <div className="flex items-baseline justify-between gap-2">
                            <span className="text-xs font-medium text-foreground">
                              {layer.modality}
                            </span>
                            <span className="font-mono text-[10px] text-muted-foreground">
                              {layer.source_format ?? 'unknown format'}
                            </span>
                          </div>
                          <div className="mt-1.5">
                            <SpatialRefStatus spatialRef={layer.spatial_ref} />
                          </div>
                          {layer.extent?.wgs84_basis && (
                            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                              {layer.extent.wgs84_basis}
                            </p>
                          )}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              ))}

            <SectionLabel count={objects.data?.count}>Objects</SectionLabel>
            <QueryState
              isLoading={objects.isLoading}
              error={objects.error}
              absenceTitle="Objects unavailable"
              errorTitle="Could not load objects"
            />
            {objects.data &&
              (placedObjects.length === 0 ? (
                <StateBox
                  kind={objects.data.count > 0 ? 'unpositioned' : 'empty'}
                  title={
                    objects.data.count > 0
                      ? 'No placed objects'
                      : 'No objects resolved'
                  }
                  detail={
                    objects.data.count > 0
                      ? 'Every object in this dataset lacks a geographic position — see "Not on the map".'
                      : 'No objects have been resolved for this dataset.'
                  }
                />
              ) : (
                <ul className="space-y-1.5">
                  {placedObjects.map((object) => (
                    <li key={object.id}>
                      <button
                        type="button"
                        aria-pressed={selection?.selection_id === object.id}
                        onClick={() =>
                          setSelection({
                            kind: 'object',
                            dataset_id: datasetId,
                            selection_id: object.id,
                            frame_id: object.members?.[0]?.frame_id ?? null,
                            source_file: object.members?.[0]?.source_file ?? null,
                            trace_index: object.members?.[0]?.trace_index ?? null,
                            position: object.position,
                          })
                        }
                        className={`w-full rounded-lg border px-2.5 py-2 text-left transition-colors ${
                          selection?.selection_id === object.id
                            ? 'border-primary/50 bg-primary/10'
                            : 'border-border hover:border-primary/30 hover:bg-muted/40'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <ProvenanceTag
                            provenance={object.position_provenance}
                            basis={object.position_basis}
                            size="sm"
                          />
                          <span className="text-[11px] text-muted-foreground">
                            {object.status}
                          </span>
                        </div>
                        <code className="mt-1 block truncate font-mono text-[11px] text-foreground">
                          {object.id}
                        </code>
                      </button>
                    </li>
                  ))}
                </ul>
              ))}

            <SectionLabel count={labels.data?.labels.length}>Labels</SectionLabel>
            <QueryState
              isLoading={labels.isLoading}
              error={labels.error}
              absenceTitle="Labels unavailable"
              errorTitle="Could not load labels"
            />
            {labels.data &&
              (placedLabels.length === 0 ? (
                <StateBox
                  kind={labels.data.labels.length > 0 ? 'unpositioned' : 'empty'}
                  title={
                    labels.data.labels.length > 0
                      ? 'No placed labels'
                      : 'No labels'
                  }
                  detail={
                    labels.data.labels.length > 0
                      ? 'All labels are attached to targets rather than to coordinates.'
                      : 'No labels have been written for this dataset.'
                  }
                />
              ) : (
                <ul className="space-y-1.5">
                  {placedLabels.map((label) => (
                    <li
                      key={label.id}
                      className="rounded-lg border border-border px-2.5 py-2"
                    >
                      <div className="flex items-center gap-2">
                        <ProvenanceTag provenance={label.provenance} size="sm" />
                        <span className="truncate text-xs text-foreground">
                          {label.value}
                        </span>
                      </div>
                      <div className="mt-1.5">
                        <ConfidenceValue value={label.confidence} showBar={false} />
                      </div>
                    </li>
                  ))}
                </ul>
              ))}

            <SectionLabel count={unplaced.length}>Not on the map</SectionLabel>
            {(objects.data || labels.data) && <NotOnMap items={unplaced} />}

            <ProvenancePane datasetId={datasetId} />
          </PanelBody>
        </Panel>

        {/* ----------------------------- centre ----------------------------- */}
        <SpatialPanes
          datasetId={datasetId}
          selection={selection}
          placedCount={placedObjects.length + placedLabels.length}
          totalCount={
            (objects.data?.count ?? 0) + (labels.data?.labels.length ?? 0)
          }
          loading={objects.isLoading || labels.isLoading}
        />

        {/* ------------------------------ right ----------------------------- */}
        <div className="min-h-0 xl:contents">
          <SelectionPane datasetId={datasetId} selection={selection} />
        </div>
      </div>
    </>
  )
}
