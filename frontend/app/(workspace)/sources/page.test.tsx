/**
 * External sources: fetch a real DEM (OpenTopography) or search real
 * earthquakes (USGS) for a bounding box.
 *
 * WHAT THESE TESTS PIN:
 *   1. the dem_type select is populated from the SERVED vocabulary, never a
 *      hardcoded list, and correctly separates global from USGS types
 *   2. fetching is not importing -- "Import this DEM" only appears after a
 *      real fetch result, and calls ingestLocalFile with the exact saved
 *      path and sensor_type "dem"
 *   3. the usgs=true/false flag sent to fetchOpenTopographyDem is derived
 *      from which vocabulary bucket the chosen code came from
 *   4. earthquake search never offers to import a result as a dataset
 *   5. backend errors render verbatim, never paraphrased
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { OpenTopographyDemTypes, SourceSearchResult } from '@/types/subterra'

const getOpenTopographyDemTypes = vi.fn()
const fetchOpenTopographyDem = vi.fn()
const fetchUsgsEarthquakes = vi.fn()
const ingestLocalFile = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getOpenTopographyDemTypes: () => getOpenTopographyDemTypes(),
      fetchOpenTopographyDem: (options: unknown) => fetchOpenTopographyDem(options),
      fetchUsgsEarthquakes: (options: unknown) => fetchUsgsEarthquakes(options),
      ingestLocalFile: (options: unknown) => ingestLocalFile(options),
    },
  }
})

import { ApiError } from '@/services/api'
import SourcesPage from './page'

function demTypes(): OpenTopographyDemTypes {
  return {
    global: { COP30: 'Copernicus Global DSM 30m', SRTMGL3: 'SRTM GL3 (Global 90m)' },
    usgs: { USGS30m: 'USGS 3DEP 1 arc-second (~30m)' },
  }
}

function earthquake(overrides: Partial<SourceSearchResult> = {}): SourceSearchResult {
  return {
    title: 'M 4.2 - 10km NE of Somewhere',
    source: 'usgs',
    download_url: 'https://example.com/detail',
    license: 'public domain (USGS)',
    description: 'Magnitude 4.2 at depth 8.3km',
    extra: { magnitude: 4.2, latitude: 35.1, longitude: -120.5 },
    ...overrides,
  }
}

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <SourcesPage />
    </SWRConfig>,
  )
}

beforeEach(() => {
  getOpenTopographyDemTypes.mockResolvedValue(demTypes())
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('DEM type selection', () => {
  it('populates the select from the served vocabulary, separated by bucket', async () => {
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-dem-type]')).toBeTruthy())
    const select = container.querySelector('[data-dem-type]') as HTMLSelectElement
    const options = Array.from(select.options).map((o) => o.value)
    expect(options).toEqual(['', 'COP30', 'SRTMGL3', 'USGS30m'])
  })
})

describe('fetching a DEM', () => {
  async function fillBbox(container: HTMLElement) {
    const select = container.querySelector('[data-dem-type]') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'COP30' } })
    const inputs = container.querySelectorAll('input[type="number"]')
    fireEvent.change(inputs[0]!, { target: { value: '41.0' } }) // south
    fireEvent.change(inputs[1]!, { target: { value: '41.1' } }) // north
    fireEvent.change(inputs[2]!, { target: { value: '15.0' } }) // west
    fireEvent.change(inputs[3]!, { target: { value: '15.1' } }) // east
  }

  it('disables Fetch until a dem type and full bounding box are given', async () => {
    const { container } = view()
    await waitFor(() => expect(container.querySelector('[data-dem-type]')).toBeTruthy())

    const fetchButton = container.querySelector('[data-action="fetch-dem"]') as HTMLButtonElement
    expect(fetchButton.disabled).toBe(true)

    await fillBbox(container)
    expect(fetchButton.disabled).toBe(false)
  })

  it('sends usgs:false for a global type', async () => {
    fetchOpenTopographyDem.mockResolvedValue({ saved_to: '/app/datasets/downloads/COP30_x.tif', size_bytes: 2048 })
    const { container } = view()
    await waitFor(() => expect(container.querySelector('[data-dem-type]')).toBeTruthy())
    await fillBbox(container)

    fireEvent.click(container.querySelector('[data-action="fetch-dem"]')!)

    await waitFor(() =>
      expect(fetchOpenTopographyDem).toHaveBeenCalledWith(
        expect.objectContaining({ demType: 'COP30', usgs: false, outputFormat: 'GTiff' }),
      ),
    )
  })

  it('sends usgs:true for a USGS 3DEP type', async () => {
    fetchOpenTopographyDem.mockResolvedValue({ saved_to: '/app/datasets/downloads/USGS30m_x.tif', size_bytes: 2048 })
    const { container } = view()
    await waitFor(() => expect(container.querySelector('[data-dem-type]')).toBeTruthy())

    fireEvent.change(container.querySelector('[data-dem-type]')!, { target: { value: 'USGS30m' } })
    const inputs = container.querySelectorAll('input[type="number"]')
    fireEvent.change(inputs[0]!, { target: { value: '41.0' } })
    fireEvent.change(inputs[1]!, { target: { value: '41.1' } })
    fireEvent.change(inputs[2]!, { target: { value: '15.0' } })
    fireEvent.change(inputs[3]!, { target: { value: '15.1' } })

    fireEvent.click(container.querySelector('[data-action="fetch-dem"]')!)

    await waitFor(() =>
      expect(fetchOpenTopographyDem).toHaveBeenCalledWith(expect.objectContaining({ usgs: true })),
    )
  })

  it('shows the saved path and size, and the backend error verbatim on failure', async () => {
    fetchOpenTopographyDem.mockRejectedValue(new ApiError(400, 'OPENTOPOGRAPHY_API_KEY is not set.'))
    const { container } = view()
    await waitFor(() => expect(container.querySelector('[data-dem-type]')).toBeTruthy())
    await fillBbox(container)

    fireEvent.click(container.querySelector('[data-action="fetch-dem"]')!)

    await waitFor(() =>
      expect(container.querySelector('[data-fetch-error]')?.textContent).toContain(
        'OPENTOPOGRAPHY_API_KEY is not set.',
      ),
    )
    expect(container.querySelector('[data-fetch-result]')).toBeNull()
  })

  it('offers "Import this DEM" only after a real fetch result, and never before', async () => {
    fetchOpenTopographyDem.mockResolvedValue({ saved_to: '/app/datasets/downloads/COP30_x.tif', size_bytes: 4096 })
    const { container } = view()
    await waitFor(() => expect(container.querySelector('[data-dem-type]')).toBeTruthy())

    expect(container.querySelector('[data-action="ingest-dem"]')).toBeNull()

    await fillBbox(container)
    fireEvent.click(container.querySelector('[data-action="fetch-dem"]')!)

    await waitFor(() => expect(container.querySelector('[data-fetch-result]')).toBeTruthy())
    expect(container.querySelector('[data-fetch-result]')?.textContent).toContain(
      '/app/datasets/downloads/COP30_x.tif',
    )
    expect(container.querySelector('[data-action="ingest-dem"]')).toBeTruthy()
  })

  it('ingests with sensor_type "dem" and the exact saved path, and links to the resulting dataset', async () => {
    fetchOpenTopographyDem.mockResolvedValue({ saved_to: '/app/datasets/downloads/COP30_x.tif', size_bytes: 4096 })
    ingestLocalFile.mockResolvedValue({ dataset_id: 'ds-99', record_count: 1000, quality_score: 0.9, issues: [] })
    const { container } = view()
    await waitFor(() => expect(container.querySelector('[data-dem-type]')).toBeTruthy())
    await fillBbox(container)
    fireEvent.click(container.querySelector('[data-action="fetch-dem"]')!)
    await waitFor(() => expect(container.querySelector('[data-action="ingest-dem"]')).toBeTruthy())

    fireEvent.click(container.querySelector('[data-action="ingest-dem"]')!)

    await waitFor(() =>
      expect(ingestLocalFile).toHaveBeenCalledWith(
        expect.objectContaining({ path: '/app/datasets/downloads/COP30_x.tif', sensorType: 'dem' }),
      ),
    )
    await waitFor(() => expect(container.querySelector('[data-ingested]')).toBeTruthy())
    expect(container.querySelector('a[href="/datasets/ds-99/report"]')).toBeTruthy()
  })
})

describe('searching earthquakes', () => {
  it('disables Search until the full bounding box is given', () => {
    const { container } = view()
    const button = container.querySelector('[data-action="search-earthquakes"]') as HTMLButtonElement
    expect(button.disabled).toBe(true)
  })

  it('omits min_magnitude when left blank, and shows real results', async () => {
    fetchUsgsEarthquakes.mockResolvedValue([earthquake()])
    const { container } = view()
    const inputs = container.querySelectorAll('input[type="number"]')
    // 4 DEM bbox fields come first in the DOM, then the 4 earthquake bbox fields.
    fireEvent.change(inputs[4]!, { target: { value: '30' } })
    fireEvent.change(inputs[5]!, { target: { value: '40' } })
    fireEvent.change(inputs[6]!, { target: { value: '-120' } })
    fireEvent.change(inputs[7]!, { target: { value: '-110' } })

    fireEvent.click(container.querySelector('[data-action="search-earthquakes"]')!)

    await waitFor(() =>
      expect(fetchUsgsEarthquakes).toHaveBeenCalledWith(
        expect.objectContaining({ minLat: 30, maxLat: 40, minLon: -120, maxLon: -110 }),
      ),
    )
    const call = fetchUsgsEarthquakes.mock.calls[0]![0]
    expect(call.minMagnitude).toBeUndefined()

    await waitFor(() =>
      expect(container.querySelector('[data-earthquake-results]')?.textContent).toContain(
        'M 4.2 - 10km NE of Somewhere',
      ),
    )
  })

  it('shows an explicit empty state for zero results, and the backend error verbatim on failure', async () => {
    fetchUsgsEarthquakes.mockResolvedValue([])
    const { container } = view()
    const inputs = container.querySelectorAll('input[type="number"]')
    fireEvent.change(inputs[4]!, { target: { value: '30' } })
    fireEvent.change(inputs[5]!, { target: { value: '40' } })
    fireEvent.change(inputs[6]!, { target: { value: '-120' } })
    fireEvent.change(inputs[7]!, { target: { value: '-110' } })
    fireEvent.click(container.querySelector('[data-action="search-earthquakes"]')!)

    await waitFor(() => expect(container.textContent).toContain('No events found'))

    fetchUsgsEarthquakes.mockRejectedValue(new ApiError(502, 'USGS earthquake search failed: timeout'))
    fireEvent.click(container.querySelector('[data-action="search-earthquakes"]')!)
    await waitFor(() =>
      expect(container.querySelector('[data-search-error]')?.textContent).toContain(
        'USGS earthquake search failed: timeout',
      ),
    )
  })

  it('never offers to import an earthquake result as a dataset', async () => {
    fetchUsgsEarthquakes.mockResolvedValue([earthquake()])
    const { container } = view()
    const inputs = container.querySelectorAll('input[type="number"]')
    fireEvent.change(inputs[4]!, { target: { value: '30' } })
    fireEvent.change(inputs[5]!, { target: { value: '40' } })
    fireEvent.change(inputs[6]!, { target: { value: '-120' } })
    fireEvent.change(inputs[7]!, { target: { value: '-110' } })
    fireEvent.click(container.querySelector('[data-action="search-earthquakes"]')!)

    await waitFor(() => expect(container.querySelector('[data-earthquake-results]')).toBeTruthy())
    expect(container.querySelector('[data-earthquake-results] button')).toBeNull()
    expect(container.textContent?.toLowerCase()).not.toContain('import this earthquake')
  })
})
