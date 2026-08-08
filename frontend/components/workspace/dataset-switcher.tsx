'use client'

import { useRouter } from 'next/navigation'
import { ChevronDown } from 'lucide-react'
import { useDatasets } from '@/hooks/use-subterra'

/**
 * Switches the workspace between ingested datasets.
 *
 * A plain native select: it is a short list, needs keyboard and screen
 * reader support for free, and nothing about choosing a dataset benefits
 * from a custom popup.
 *
 * Each option states whether the dataset has positioned records, because
 * that single fact determines whether the spatial view can show anything
 * — better to know before switching than to arrive at an empty panel.
 */
export function DatasetSwitcher({ datasetId }: { datasetId: string }) {
  const router = useRouter()
  const { data, isLoading } = useDatasets()

  if (isLoading || !data || data.length === 0) return null

  return (
    <div className="relative">
      <label htmlFor="dataset-switcher" className="sr-only">
        Dataset
      </label>
      <select
        id="dataset-switcher"
        value={datasetId}
        onChange={(event) =>
          router.push(`/datasets/${encodeURIComponent(event.target.value)}`)
        }
        className="h-8 max-w-[22rem] appearance-none truncate rounded-lg border border-border bg-card py-1 pl-2.5 pr-7 text-xs text-foreground outline-none transition-colors hover:border-primary/40 focus-visible:ring-2 focus-visible:ring-ring/50"
      >
        {data.map((dataset) => (
          <option key={dataset.id} value={dataset.id}>
            {dataset.name}
            {dataset.sensor_type ? ` · ${dataset.sensor_type}` : ''}
            {dataset.center_lat === null ? ' · no geographic centre' : ''}
          </option>
        ))}
      </select>
      <ChevronDown
        aria-hidden
        className="pointer-events-none absolute right-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
      />
    </div>
  )
}
