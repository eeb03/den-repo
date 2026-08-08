'use client'

import { Check } from 'lucide-react'
import {
  Panel,
  PanelBody,
  PanelHeader,
  SectionLabel,
} from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { CoordinateStatus } from '@/components/subterra/data-status'
import { useComposition, useViewResolution } from '@/hooks/use-subterra'
import { viewMeta } from '@/lib/format'
import type { Selection, ViewResolution } from '@/types/subterra'

/**
 * Selection details and, critically, view resolution.
 *
 * Every statement about what can be shown comes from
 * `POST /api/views/resolve`. This component renders `resolved`, `reason`
 * and `missing` exactly as returned and adds no judgement of its own --
 * notably it does not special-case `scene_3d`, even though that view is
 * currently unresolved for every dataset held. If a vertical registration
 * is ever supplied, the view starts resolving with no change here.
 */
export function SelectionPane({
  datasetId,
  selection,
}: {
  datasetId: string
  selection: Selection | null
}) {
  const views = useViewResolution(selection)
  const composition = useComposition(datasetId)

  return (
    <Panel className="min-h-0">
      <PanelHeader title="Selection" />
      <PanelBody className="pt-0">
        <SectionLabel>Selected</SectionLabel>
        {selection ? (
          <div className="rounded-lg border border-primary/40 bg-primary/5 px-2.5 py-2">
            <div className="flex items-baseline gap-2">
              <span className="rounded border border-primary/40 px-1.5 py-px text-[10px] uppercase tracking-wider text-primary">
                {selection.kind}
              </span>
            </div>
            <code className="mt-1 block break-all font-mono text-[11px] text-foreground">
              {selection.selection_id}
            </code>
            <dl className="mt-2 space-y-1 text-[11px] text-muted-foreground">
              <div>
                frame:{' '}
                <code className="font-mono">{selection.frame_id ?? '—'}</code>
              </div>
              <div>
                trace:{' '}
                <code className="font-mono">
                  {selection.trace_index ?? '—'}
                </code>
              </div>
            </dl>
            {selection.position && (
              <div className="mt-2">
                <CoordinateStatus position={selection.position} />
              </div>
            )}
          </div>
        ) : (
          <StateBox
            kind="empty"
            title="Nothing selected"
            detail="Select a layer, object or label to see which views can show it."
          />
        )}

        <SectionLabel>Views</SectionLabel>
        {!selection ? (
          <StateBox
            kind="empty"
            title="No selection to resolve"
            detail="View availability is answered by the backend for a specific selection."
          />
        ) : (
          <>
            <QueryState
              isLoading={views.isLoading}
              error={views.error}
              absenceTitle="Selection could not be resolved"
              errorTitle="Could not resolve the selection"
              skeletonRows={3}
            />
            {views.data && (
              <ul className="space-y-1.5">
                {views.data.views.map((view) => (
                  <li key={view.view}>
                    <ViewRow resolution={view} />
                  </li>
                ))}
              </ul>
            )}
          </>
        )}

        <SectionLabel>Overlay composition</SectionLabel>
        <QueryState
          isLoading={composition.isLoading}
          error={composition.error}
          absenceTitle="No layers to compose"
          errorTitle="Composition failed"
        />
        {composition.data && (
          <div className="space-y-2">
            <StateBox
              kind={
                composition.data.spatial_relationship === 'not_relatable'
                  ? 'unassociated'
                  : 'empty'
              }
              title={composition.data.spatial_relationship}
              detail={composition.data.spatial_basis}
            />
            {composition.data.vertical_relationship && (
              <StateBox
                kind="unavailable"
                title={`vertical: ${composition.data.vertical_relationship.kind}`}
                detail={
                  composition.data.vertical_relationship
                    .absolute_elevation_available
                    ? 'absolute elevation available'
                    : 'absolute elevation NOT available'
                }
                missing={composition.data.vertical_relationship.missing}
              />
            )}
            {(composition.data.notes ?? []).map((note) => (
              <p
                key={note}
                className="text-[11px] leading-relaxed text-muted-foreground"
              >
                &bull; {note}
              </p>
            ))}
          </div>
        )}
      </PanelBody>
    </Panel>
  )
}

function ViewRow({ resolution }: { resolution: ViewResolution }) {
  const meta = viewMeta[resolution.view]
  const label = meta?.label ?? resolution.view

  if (resolution.resolved) {
    return (
      <div
        data-view={resolution.view}
        data-resolved="true"
        className="rounded-lg border border-success/35 bg-success/5 px-2.5 py-2"
      >
        <div className="flex items-center gap-2">
          <Check className="size-3.5 shrink-0 text-success" aria-hidden />
          <span className="text-xs font-medium text-foreground">{label}</span>
          <span className="ml-auto text-[10px] uppercase tracking-wider text-success">
            resolved
          </span>
        </div>
        {Object.keys(resolution.coordinates ?? {}).length > 0 && (
          <code className="mt-1.5 block break-all font-mono text-[10px] text-muted-foreground">
            {JSON.stringify(resolution.coordinates)}
          </code>
        )}
      </div>
    )
  }

  return (
    <StateBox
      kind="unavailable"
      title={`${label} — unavailable`}
      detail={
        resolution.reason ??
        'The backend reported this view as unresolved and supplied no reason.'
      }
      missing={resolution.missing}
    />
  )
}
