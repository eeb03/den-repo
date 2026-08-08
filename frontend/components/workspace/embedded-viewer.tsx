'use client'

import { ExternalLink } from 'lucide-react'
import { API_BASE } from '@/services/api'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { useDatasetInfo } from '@/hooks/use-subterra'
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
 * WHY IT IS GATED. `GET /api/datasets/{id}/points` returns `lat: 0.0,
 * lon: 0.0` for records whose `position_kind` is `"none"`, and the viewer
 * plots what it is given without filtering on that field. For a dataset
 * whose records carry no position, embedding it unguarded would draw every
 * point at null island and label it `lat: 0.000000, lon: 0.000000` -- a
 * fabricated location, and precisely the failure the platform is built to
 * prevent.
 *
 * So the embed is shown only when the backend confirms the dataset has
 * geographically positioned records. Otherwise this renders the reason.
 * The guard reads `geographic_record_count`, which the backend computes;
 * it is not a judgement made here.
 */
export function EmbeddedViewer({ datasetId }: { datasetId: string }) {
  const { data, error, isLoading } = useDatasetInfo(datasetId)

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

  if (data.geographic_record_count === 0) {
    return (
      <div className="flex h-full w-full items-center justify-center p-5">
        <div className="w-full max-w-lg">
          <StateBox
            kind="unpositioned"
            title="No positioned records — nothing can be plotted"
            detail={
              `None of this dataset's ${formatCount(data.record_count)} records carries a geographic position ` +
              `(position sources: ${Object.entries(data.position_sources ?? {})
                .map(([k, n]) => `${k} ${formatCount(n)}`)
                .join(', ')}). ` +
              `The spatial viewer is not embedded here, because the points endpoint reports 0.0 / 0.0 for an ` +
              `absent position and the viewer plots coordinates as given — which would place every record at ` +
              `null island and label it as a measured location.`
            }
            missing={[
              'a geographic position on the records, or a GeoTie that supplies one',
            ]}
          />
        </div>
      </div>
    )
  }

  const src = `${API_BASE}/viewer?datasets=${encodeURIComponent(datasetId)}`

  return (
    <div className="relative h-full w-full">
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
