/**
 * The spatial-view embed gate.
 *
 * `GET /api/datasets/{id}/points` reports `lat: 0.0, lon: 0.0` for a record
 * whose `position_kind` is `"none"`, and `visualization/viewer.html` plots
 * coordinates as given without filtering on that field. Embedding the
 * viewer for an unpositioned dataset would therefore draw every record at
 * null island and label it as a measured location.
 *
 * These tests pin the guard that prevents that. They are the reason the
 * embed reads `geographic_record_count` before rendering an iframe.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { DatasetInfo } from '@/types/subterra'

const mockUseDatasetInfo = vi.fn()

vi.mock('@/hooks/use-subterra', () => ({
  useDatasetInfo: (...args: unknown[]) => mockUseDatasetInfo(...args),
}))

const { EmbeddedViewer } = await import('./embedded-viewer')

afterEach(() => {
  cleanup()
  mockUseDatasetInfo.mockReset()
})

/** Shaped from a real /info response. */
function info(overrides: Partial<DatasetInfo>): DatasetInfo {
  return {
    dataset_id: 'ds',
    name: 'INGV-UNISA Site 1 GPR',
    sensor_type: 'gpr',
    original_format: 'zip(100 files)',
    source: 'zenodo',
    license: 'cc-by-4.0',
    record_count: 10727,
    quality_score: 0.3,
    has_ground_truth: false,
    coordinate_system: 'unknown',
    position_sources: { none: 10727 },
    survey_frames: [],
    survey_area_m: null,
    geographic_record_count: 0,
    grid_resolution_m: null,
    depth_layers: [],
    processing_applied: null,
    dem_aligned: false,
    last_preprocessing_mode: null,
    ...overrides,
  }
}

function setInfo(value: DatasetInfo) {
  mockUseDatasetInfo.mockReturnValue({
    data: value,
    error: null,
    isLoading: false,
  })
}

describe('a dataset with no positioned records is never embedded', () => {
  it('renders no iframe at all', () => {
    setInfo(info({ geographic_record_count: 0 }))
    const { container } = render(<EmbeddedViewer datasetId="ds" />)
    expect(container.querySelector('iframe')).toBeNull()
  })

  it('explains why, naming null island as the thing being avoided', () => {
    setInfo(info({ geographic_record_count: 0 }))
    const { container } = render(<EmbeddedViewer datasetId="ds" />)
    expect(screen.getByText(/no positioned records/i)).toBeTruthy()
    expect(container.textContent).toMatch(/null island/i)
    expect(container.textContent).toMatch(/position sources: none 10,727/i)
  })

  it('states what is missing rather than implying a bug', () => {
    setInfo(info({ geographic_record_count: 0 }))
    render(<EmbeddedViewer datasetId="ds" />)
    expect(
      screen.getByText(/a geographic position on the records, or a GeoTie/i),
    ).toBeTruthy()
  })

  it('shows the unpositioned state, not the empty or error state', () => {
    setInfo(info({ geographic_record_count: 0 }))
    const { container } = render(<EmbeddedViewer datasetId="ds" />)
    expect(container.querySelector('[data-state-kind="unpositioned"]')).toBeTruthy()
    expect(container.querySelector('[data-state-kind="error"]')).toBeNull()
  })
})

describe('a dataset with positioned records is embedded', () => {
  it('renders the viewer iframe scoped to that dataset', () => {
    setInfo(
      info({
        dataset_id: 'd3dca710',
        name: 'Lazaresti GPR depth slice 0-0.5m',
        geographic_record_count: 157040,
        record_count: 157040,
        position_sources: { geographic: 157040 },
      }),
    )
    const { container } = render(<EmbeddedViewer datasetId="d3dca710" />)
    const iframe = container.querySelector('iframe')
    expect(iframe).toBeTruthy()
    expect(iframe!.getAttribute('src')).toContain('/viewer?datasets=d3dca710')
  })

  it('sandboxes the embed to only what it needs', () => {
    setInfo(info({ geographic_record_count: 100 }))
    const iframe = render(<EmbeddedViewer datasetId="ds" />).container.querySelector(
      'iframe',
    )!
    const sandbox = iframe.getAttribute('sandbox') ?? ''
    expect(sandbox).toContain('allow-scripts')
    // withheld on purpose
    expect(sandbox).not.toContain('allow-forms')
    expect(sandbox).not.toContain('allow-popups')
    expect(sandbox).not.toContain('allow-top-navigation')
  })
})

describe('the gate reads the backend, not a local guess', () => {
  it('a partially positioned dataset is still embedded', () => {
    // The backend decides; the UI does not invent a coverage threshold.
    setInfo(
      info({ geographic_record_count: 1, record_count: 10727, position_sources: { geographic: 1, none: 10726 } }),
    )
    expect(
      render(<EmbeddedViewer datasetId="ds" />).container.querySelector('iframe'),
    ).toBeTruthy()
  })

  it('withholds the embed while the answer is still loading', () => {
    mockUseDatasetInfo.mockReturnValue({ data: null, error: null, isLoading: true })
    const { container } = render(<EmbeddedViewer datasetId="ds" />)
    expect(container.querySelector('iframe')).toBeNull()
  })

  it('withholds the embed when the answer could not be fetched', () => {
    mockUseDatasetInfo.mockReturnValue({
      data: null,
      error: new Error('boom'),
      isLoading: false,
    })
    const { container } = render(<EmbeddedViewer datasetId="ds" />)
    expect(container.querySelector('iframe')).toBeNull()
    expect(container.textContent).toMatch(/could not determine/i)
  })
})
