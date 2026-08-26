'use client'

import { useState } from 'react'
import Link from 'next/link'
import { AppHeader } from '@/components/shell/app-header'
import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { buttonVariants } from '@/components/ui/button'
import { useOpenTopographyDemTypes } from '@/hooks/use-subterra'
import { ApiError, api } from '@/services/api'
import { formatCount } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DemFetchResult, SourceSearchResult } from '@/types/subterra'

/**
 * External sources: real public APIs Subterra can fetch supplementary data
 * from, to pair with a GPR survey already in the platform.
 *
 * TWO CONNECTORS, DELIBERATELY NARROW. `ingestion/sources.py` also has a
 * Zenodo full-text search, left off this page: its results are arbitrary
 * downloadable files of unknown format, not a typed bounding-box fetch this
 * page could act on directly the way it can for a DEM tile. This page
 * covers exactly what the roadmap named -- "external DEM/earthquake fetch"
 * -- not a general dataset-discovery UI.
 *
 * FETCHING IS NOT IMPORTING. `fetchOpenTopographyDem` only saves a file
 * server-side; nothing becomes a Subterra dataset until `ingestLocalFile`
 * is called explicitly, same as `/import`'s own review-before-ingest
 * discipline elsewhere in this workspace.
 *
 * EARTHQUAKES ARE NOT IMPORTABLE HERE. They are context for a site -- no
 * sensor_type exists for "seismic event catalog", and turning one into a
 * Subterra record would misrepresent it as a measurement this platform
 * took, rather than a public catalog entry it is displaying.
 */
export default function SourcesPage() {
  return (
    <>
      <AppHeader
        title="External sources"
        subtitle="Fetch a real DEM or search recent earthquakes from public APIs, to pair with a survey already in the platform."
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="mx-auto max-w-3xl space-y-4">
          <DemFetchPanel />
          <EarthquakeSearchPanel />
        </div>
      </div>
    </>
  )
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label className="block space-y-1">
      <span className="block text-[11px] text-muted-foreground">{label}</span>
      <input
        type="number"
        step="any"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
      />
    </label>
  )
}

function DemFetchPanel() {
  const { data: demTypes, error: demTypesError, isLoading: demTypesLoading } =
    useOpenTopographyDemTypes()
  const [demType, setDemType] = useState('')
  const [south, setSouth] = useState('')
  const [north, setNorth] = useState('')
  const [west, setWest] = useState('')
  const [east, setEast] = useState('')
  const [fetching, setFetching] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [fetched, setFetched] = useState<DemFetchResult | null>(null)
  const [ingesting, setIngesting] = useState(false)
  const [ingestError, setIngestError] = useState<string | null>(null)
  const [ingested, setIngested] = useState<{ dataset_id: string } | null>(null)

  const bboxValid = [south, north, west, east].every(
    (v) => v !== '' && Number.isFinite(Number(v)),
  )
  const isUsgsType = demTypes ? demType in demTypes.usgs : false
  const canFetch = demType !== '' && bboxValid && !fetching

  async function fetchDem() {
    setFetching(true)
    setFetchError(null)
    setFetched(null)
    setIngested(null)
    setIngestError(null)
    try {
      const result = await api.fetchOpenTopographyDem({
        demType,
        south: Number(south),
        north: Number(north),
        west: Number(west),
        east: Number(east),
        usgs: isUsgsType,
        // The only format any Subterra converter can actually read
        // (converters/geotiff_converter.py). AAIGrid/HFA are real options
        // the backend accepts but this page never offers, since choosing
        // one would produce a file nothing here can ingest.
        outputFormat: 'GTiff',
      })
      setFetched(result)
    } catch (err) {
      setFetchError(
        err instanceof ApiError ? err.detail : `could not reach the Subterra API: ${String(err)}`,
      )
    } finally {
      setFetching(false)
    }
  }

  async function ingestFetched() {
    if (!fetched) return
    setIngesting(true)
    setIngestError(null)
    try {
      const result = await api.ingestLocalFile({
        path: fetched.saved_to,
        sensorType: 'dem',
        source: 'opentopography',
        name: `${demType} DEM (${south},${west})–(${north},${east})`,
      })
      setIngested(result)
    } catch (err) {
      setIngestError(
        err instanceof ApiError ? err.detail : `could not reach the Subterra API: ${String(err)}`,
      )
    } finally {
      setIngesting(false)
    }
  }

  return (
    <Panel>
      <PanelHeader title="Fetch a DEM — OpenTopography" />
      <PanelBody className="space-y-3">
        <p className="text-xs leading-relaxed text-muted-foreground">
          Retrieves a real elevation raster for a bounding box you supply. This does not create a
          dataset by itself — fetch, then import it, same as any other file.
        </p>

        <QueryState
          isLoading={demTypesLoading}
          error={demTypesError}
          absenceTitle="DEM types unavailable"
          errorTitle="Could not load DEM types"
        />

        {demTypes && (
          <label className="block space-y-1">
            <span className="block text-[11px] text-muted-foreground">DEM type</span>
            <select
              data-dem-type
              value={demType}
              onChange={(e) => setDemType(e.target.value)}
              className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
            >
              <option value="">Select…</option>
              <optgroup label="Global">
                {Object.entries(demTypes.global).map(([code, label]) => (
                  <option key={code} value={code}>
                    {label} ({code})
                  </option>
                ))}
              </optgroup>
              <optgroup label="USGS 3DEP (United States only)">
                {Object.entries(demTypes.usgs).map(([code, label]) => (
                  <option key={code} value={code}>
                    {label} ({code})
                  </option>
                ))}
              </optgroup>
            </select>
          </label>
        )}

        <div className="grid grid-cols-2 gap-2">
          <NumberField label="South (min lat)" value={south} onChange={setSouth} />
          <NumberField label="North (max lat)" value={north} onChange={setNorth} />
          <NumberField label="West (min lon)" value={west} onChange={setWest} />
          <NumberField label="East (max lon)" value={east} onChange={setEast} />
        </div>

        {fetchError && (
          <p role="alert" data-fetch-error className="text-xs leading-relaxed text-destructive">
            {fetchError}
          </p>
        )}

        <button
          type="button"
          data-action="fetch-dem"
          disabled={!canFetch}
          onClick={fetchDem}
          className={cn(buttonVariants({ variant: 'default', size: 'sm' }))}
        >
          {fetching ? 'Fetching…' : 'Fetch DEM'}
        </button>

        {fetched && !ingested && (
          <div data-fetch-result className="rounded-lg border border-border p-3 text-xs">
            <p className="text-foreground">
              Saved {formatCount(fetched.size_bytes)} bytes on the server.
            </p>
            <p className="mt-1 break-all font-mono text-[11px] text-muted-foreground">
              {fetched.saved_to}
            </p>
            {ingestError && (
              <p role="alert" className="mt-1 text-destructive">
                {ingestError}
              </p>
            )}
            <button
              type="button"
              data-action="ingest-dem"
              disabled={ingesting}
              onClick={ingestFetched}
              className={cn(buttonVariants({ variant: 'default', size: 'sm' }), 'mt-2')}
            >
              {ingesting ? 'Importing…' : 'Import this DEM'}
            </button>
          </div>
        )}

        {ingested && (
          <p data-ingested className="text-xs leading-relaxed text-foreground">
            Imported as dataset{' '}
            <Link
              href={`/datasets/${encodeURIComponent(ingested.dataset_id)}/report`}
              className="text-primary underline-offset-4 hover:underline"
            >
              {ingested.dataset_id}
            </Link>
            .
          </p>
        )}
      </PanelBody>
    </Panel>
  )
}

function EarthquakeSearchPanel() {
  const [minLat, setMinLat] = useState('')
  const [maxLat, setMaxLat] = useState('')
  const [minLon, setMinLon] = useState('')
  const [maxLon, setMaxLon] = useState('')
  const [minMagnitude, setMinMagnitude] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [results, setResults] = useState<SourceSearchResult[] | null>(null)

  const bboxValid = [minLat, maxLat, minLon, maxLon].every(
    (v) => v !== '' && Number.isFinite(Number(v)),
  )

  async function search() {
    setSearching(true)
    setSearchError(null)
    try {
      const found = await api.fetchUsgsEarthquakes({
        minLat: Number(minLat),
        maxLat: Number(maxLat),
        minLon: Number(minLon),
        maxLon: Number(maxLon),
        minMagnitude: minMagnitude !== '' ? Number(minMagnitude) : undefined,
      })
      setResults(found)
    } catch (err) {
      setSearchError(
        err instanceof ApiError ? err.detail : `could not reach the Subterra API: ${String(err)}`,
      )
    } finally {
      setSearching(false)
    }
  }

  return (
    <Panel>
      <PanelHeader title="Search earthquakes — USGS" count={results?.length ?? null} />
      <PanelBody className="space-y-3">
        <p className="text-xs leading-relaxed text-muted-foreground">
          Real events from the USGS earthquake catalog for a bounding box — context for a survey
          site, not itself a sensor reading or something this page can import as a dataset.
        </p>

        <div className="grid grid-cols-2 gap-2">
          <NumberField label="Min lat" value={minLat} onChange={setMinLat} />
          <NumberField label="Max lat" value={maxLat} onChange={setMaxLat} />
          <NumberField label="Min lon" value={minLon} onChange={setMinLon} />
          <NumberField label="Max lon" value={maxLon} onChange={setMaxLon} />
        </div>
        <NumberField label="Min magnitude (optional)" value={minMagnitude} onChange={setMinMagnitude} />

        {searchError && (
          <p role="alert" data-search-error className="text-xs leading-relaxed text-destructive">
            {searchError}
          </p>
        )}

        <button
          type="button"
          data-action="search-earthquakes"
          disabled={!bboxValid || searching}
          onClick={search}
          className={cn(buttonVariants({ variant: 'default', size: 'sm' }))}
        >
          {searching ? 'Searching…' : 'Search'}
        </button>

        {results && results.length === 0 && (
          <StateBox
            kind="empty"
            title="No events found"
            detail="No earthquakes matched this bounding box and magnitude filter."
          />
        )}

        {results && results.length > 0 && (
          <ul data-earthquake-results className="space-y-1.5">
            {results.map((r, i) => (
              <li key={i} className="rounded-lg border border-border p-2 text-xs">
                <p className="text-foreground">{r.title}</p>
                {r.description && (
                  <p className="mt-0.5 text-muted-foreground">{r.description}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </PanelBody>
    </Panel>
  )
}
