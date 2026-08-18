'use client'

import { ExternalLink } from 'lucide-react'
import { API_BASE } from '@/services/api'
import { QueryState } from '@/components/subterra/query-state'
import { useCandidates, useDatasetInfo } from '@/hooks/use-subterra'
import { formatCount } from '@/lib/format'

/**
 * Embeds the existing Plotly viewer (`GET /viewer`).
 *
 * WHY EMBED RATHER THAN PORT. `visualization/viewer.html` is the platform's
 * proven spatial visualisation -- point cloud, top-down heatmap,
 * elevation-draped surface and B-scan, with depth filtering, focus ranges
 * and anomaly thresholding. Reimplementing that in React before parity is
 * demonstrated would duplicate spatial mathematics the backend and this
 * page already own, which is exactly the kind of divergence that produces
 * two different answers to the same question.
 *
 * ON UNPOSITIONED DATASETS. `GET /api/datasets/{id}/points` returns
 * `lat: 0.0, lon: 0.0` for records whose `position_kind` is `"none"` -- a
 * documented placeholder, not a location. The viewer now filters on that
 * field and reports how many records it excluded, so an unpositioned
 * dataset renders as an explained empty scene rather than a cloud of
 * points at null island.
 *
 * Because the viewer states that itself, this component does NOT gate the
 * embed. Two reasons: duplicating the judgement would give the same
 * question two answers that can drift apart, and gating would also hide
 * the B-scan, which is indexed by trace and depth and works perfectly well
 * for a dataset with no coordinates at all.
 *
 * What it does add is context the viewer has no way to know it should
 * give: a banner naming the position sources, so the empty scene is
 * expected rather than surprising.
 *
 * THE B-SCAN SENTENCE ITSELF IS A GPR CLAIM. "Indexed by trace and depth and
 * unaffected" is true of a GPR survey; for an off-GPR composition a B-scan
 * does not apply at all (slices 5-6, 15), so the same `doesNotApply` signal
 * used since slice 10 drops that one sentence here too -- reusing the
 * existing `['candidates', datasetId]` SWR key `CandidateRegionsPane` and
 * `import-report.tsx` already read, not a new contract.
 */
export function EmbeddedViewer({ datasetId }: { datasetId: string }) {
  const { data, error, isLoading } = useDatasetInfo(datasetId)
  const { data: candidates } = useCandidates(datasetId)
  const doesNotApply =
    candidates?.status === 'blocked' && candidates.status_reason.includes('does not apply')

  if (isLoading || error) {
    return (
      <div className="p-4">
        <QueryState
          isLoading={isLoading}
          error={error}
          absenceTitle="Spatial view unavailable"
          errorTitle="Could not determine whether this dataset can be plotted"
          skeletonRows={3}
        />
      </div>
    )
  }

  if (!data) return null

  const src = `${API_BASE}/viewer?datasets=${encodeURIComponent(datasetId)}`
  const unpositioned = data.geographic_record_count === 0

  return (
    <div className="flex h-full w-full flex-col">
      {unpositioned && (
        <div
          data-unpositioned-notice
          className="subterra-hatch shrink-0 border-b border-prov-unavailable/40 px-3.5 py-2"
        >
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            <span className="font-medium text-foreground">
              No positioned records.
            </span>{' '}
            None of this dataset&rsquo;s {formatCount(data.record_count)} records
            carries a geographic position (
            {Object.entries(data.position_sources ?? {})
              .map(([kind, n]) => `${kind}: ${formatCount(n)}`)
              .join(', ')}
            ), so the point cloud, heatmap and surface views have nothing to
            place and will report that.
            {!doesNotApply && (
              <> The B-scan is indexed by trace and depth and is unaffected.</>
            )}
          </p>
        </div>
      )}
      <div className="relative min-h-0 flex-1">
        <iframe
          key={datasetId}
          src={src}
          title={`Subterra 3D viewer — ${data.name}`}
          className="h-full w-full border-0 bg-background"
          /*
           * The viewer is first-party, served by the same FastAPI app, and
           * needs scripts to run. It is sandboxed to withhold everything it
           * does not need: no forms, no popups, no top-level navigation.
           */
          sandbox="allow-scripts allow-same-origin"
          loading="lazy"
        />
        <a
          href={src}
          target="_blank"
          rel="noreferrer"
          className="absolute right-2 top-2 inline-flex items-center gap-1.5 rounded-lg border border-border bg-card/90 px-2 py-1 text-[11px] text-muted-foreground backdrop-blur transition-colors hover:text-foreground"
        >
          Open full viewer
          <ExternalLink className="size-3" aria-hidden />
        </a>
      </div>
    </div>
  )
}

/**
 * Embeds the thin client (`GET /client`).
 *
 * Not gated: the thin client is the reference implementation of the
 * honesty model. It filters on position kind itself, lists unplaced items
 * separately with their reason, and delegates view availability to
 * /api/views/resolve. It can be shown for any dataset.
 *
 * It has no dataset URL parameter, so it opens on its own first dataset
 * rather than following this workspace's selection -- stated in the UI
 * rather than papered over.
 */
export function EmbeddedThinClient() {
  const src = `${API_BASE}/client`
  return (
    <div className="relative h-full w-full">
      <iframe
        src={src}
        title="Subterra thin client"
        className="h-full w-full border-0 bg-background"
        sandbox="allow-scripts allow-same-origin"
        loading="lazy"
      />
      <a
        href={src}
        target="_blank"
        rel="noreferrer"
        className="absolute right-2 top-2 inline-flex items-center gap-1.5 rounded-lg border border-border bg-card/90 px-2 py-1 text-[11px] text-muted-foreground backdrop-blur transition-colors hover:text-foreground"
      >
        Open full client
        <ExternalLink className="size-3" aria-hidden />
      </a>
    </div>
  )
}
