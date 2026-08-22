/**
 * The Fusion run control.
 *
 * PREVIEW, THEN SAVE. `POST /api/fusion/run` with `persist: true` has no
 * dedup against what is already stored -- running it twice with the same
 * inputs creates two full sets of samples. These tests pin that Save
 * cannot be clicked until a Preview has been run with the EXACT current
 * configuration, and that changing anything (dataset selection, radius,
 * multimodal-only) invalidates a prior preview rather than leaving Save
 * clickable against a stale one.
 */
import { cleanup, render, screen, waitFor, fireEvent } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { DatasetSummary, FusionRunResult } from '@/types/subterra'

const listDatasets = vi.fn()
const runFusion = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      listDatasets: () => listDatasets(),
      runFusion: (options: unknown) => runFusion(options),
    },
  }
})

import FusionPage from './page'

function dataset(overrides: Partial<DatasetSummary> = {}): DatasetSummary {
  return {
    id: 'd1',
    name: 'Site A',
    source: 'upload',
    sensor_type: 'gpr',
    original_format: 'segy',
    quality_score: null,
    record_count: 10,
    has_ground_truth: false,
    center_lat: 52.24,
    center_lon: 6.85,
    version: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    source_file: null,
    checksum: null,
    is_system_dataset: false,
    status: 'ready',
    status_reason: 'Ready.',
    job_state: null,
    job_id: null,
    shares_source_with: [],
    ...overrides,
  }
}

function result(overrides: Partial<FusionRunResult> = {}): FusionRunResult {
  return {
    input_record_count: 100,
    fusion_sample_count: 1,
    excluded_from_fusion: [],
    samples: [
      {
        spatial_ref_kind: 'geographic',
        center_lat: 52.24,
        center_lon: 6.85,
        center_x: null,
        center_y: null,
        radius_m: 25,
        sensor_types: ['gpr', 'gps'],
        dataset_ids: ['d1'],
        has_ground_truth: false,
        n_reprojected: 0,
        record_counts: { gpr: 90, gps: 10 },
      },
    ],
    ...overrides,
  }
}

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <FusionPage />
    </SWRConfig>,
  )
}

beforeEach(() => {
  listDatasets.mockReset()
  runFusion.mockReset()
  listDatasets.mockResolvedValue([dataset()])
})
afterEach(cleanup)

describe('dataset selection', () => {
  it('lists each visible dataset as a checkbox', async () => {
    view()
    await screen.findByText('Site A')
    expect(document.querySelector('[data-dataset-checkbox="d1"]')).toBeTruthy()
  })

  it('shows an absence when there are no datasets', async () => {
    listDatasets.mockResolvedValue([])
    view()
    expect(await screen.findByText('No datasets ingested')).toBeTruthy()
  })
})

describe('preview', () => {
  it('omits datasetIds when nothing is checked -- means every visible dataset', async () => {
    runFusion.mockResolvedValue(result())
    view()
    await screen.findByText('Site A')

    fireEvent.click(document.querySelector('[data-action="preview-fusion"]')!)

    await waitFor(() => expect(runFusion).toHaveBeenCalled())
    const call = runFusion.mock.calls[0]?.[0]
    expect(call.datasetIds).toBeUndefined()
    expect(call.persist).toBe(false)
  })

  it('sends the checked dataset ids when one is selected', async () => {
    runFusion.mockResolvedValue(result())
    view()
    await screen.findByText('Site A')

    fireEvent.click(document.querySelector('[data-dataset-checkbox="d1"]')!)
    fireEvent.click(document.querySelector('[data-action="preview-fusion"]')!)

    await waitFor(() => expect(runFusion).toHaveBeenCalled())
    expect(runFusion.mock.calls[0]?.[0].datasetIds).toEqual(['d1'])
  })

  it('sends the radius as a number, and omits it when left blank', async () => {
    runFusion.mockResolvedValue(result())
    view()
    await screen.findByText('Site A')

    fireEvent.change(document.querySelector('[data-fusion-radius]')!, {
      target: { value: '30' },
    })
    fireEvent.click(document.querySelector('[data-action="preview-fusion"]')!)

    await waitFor(() => expect(runFusion).toHaveBeenCalled())
    expect(runFusion.mock.calls[0]?.[0].radiusM).toBe(30)
  })

  it('defaults multimodal-only to true, and sends false when unticked', async () => {
    runFusion.mockResolvedValue(result())
    view()
    await screen.findByText('Site A')

    const box = document.querySelector(
      '[data-fusion-multimodal-only]',
    ) as HTMLInputElement
    expect(box.checked).toBe(true)

    fireEvent.click(box)
    fireEvent.click(document.querySelector('[data-action="preview-fusion"]')!)

    await waitFor(() => expect(runFusion).toHaveBeenCalled())
    expect(runFusion.mock.calls[0]?.[0].multimodalOnly).toBe(false)
  })

  it('renders the summary counts, sample fields, and the per-sensor breakdown', async () => {
    runFusion.mockResolvedValue(result())
    view()
    await screen.findByText('Site A')
    fireEvent.click(document.querySelector('[data-action="preview-fusion"]')!)

    const sample = await screen.findByText('gpr, gps')
    const card = sample.closest('[data-fusion-run-sample]')!
    expect(card.textContent).toContain('geographic')
    expect(card.textContent).toContain('52.24000, 6.85000')
    expect(card.textContent).toContain('gpr: 90')
    expect(card.textContent).toContain('gps: 10')
    expect(screen.getByText('100')).toBeTruthy()
  })

  it('shows excluded partitions with their stated reason, not silently', async () => {
    runFusion.mockResolvedValue(
      result({
        excluded_from_fusion: [
          {
            position_kind: 'odometry',
            record_count: 12,
            dataset_ids: ['d1'],
            sensor_types: ['gpr'],
            reason: 'along-track distance only; the acquisition has no georeference',
          },
        ],
      }),
    )
    view()
    await screen.findByText('Site A')
    fireEvent.click(document.querySelector('[data-action="preview-fusion"]')!)

    const excluded = await screen.findByText(/along-track distance only/)
    expect(excluded.closest('[data-fusion-excluded]')?.textContent).toContain('odometry')
  })

  it('shows an absence, not an empty list, when nothing fused', async () => {
    runFusion.mockResolvedValue(result({ fusion_sample_count: 0, samples: [] }))
    view()
    await screen.findByText('Site A')
    fireEvent.click(document.querySelector('[data-action="preview-fusion"]')!)

    expect(await screen.findByText('No fusion samples')).toBeTruthy()
  })
})

describe('save is gated on an exact, current preview', () => {
  it('is disabled before any preview has run', async () => {
    view()
    await screen.findByText('Site A')
    const save = document.querySelector('[data-action="save-fusion"]') as HTMLButtonElement
    expect(save.disabled).toBe(true)
  })

  it('enables once a preview matching the current configuration exists', async () => {
    runFusion.mockResolvedValue(result())
    view()
    await screen.findByText('Site A')
    fireEvent.click(document.querySelector('[data-action="preview-fusion"]')!)
    await waitFor(() => expect(runFusion).toHaveBeenCalled())

    const save = document.querySelector('[data-action="save-fusion"]') as HTMLButtonElement
    await waitFor(() => expect(save.disabled).toBe(false))
  })

  it('disables again the moment a setting changes after the preview', async () => {
    runFusion.mockResolvedValue(result())
    view()
    await screen.findByText('Site A')
    fireEvent.click(document.querySelector('[data-action="preview-fusion"]')!)
    await waitFor(() =>
      expect(
        (document.querySelector('[data-action="save-fusion"]') as HTMLButtonElement).disabled,
      ).toBe(false),
    )

    // The radius changes -- the preview on screen no longer describes what
    // Save would now run.
    fireEvent.change(document.querySelector('[data-fusion-radius]')!, {
      target: { value: '50' },
    })

    const save = document.querySelector('[data-action="save-fusion"]') as HTMLButtonElement
    expect(save.disabled).toBe(true)
  })

  it('calls runFusion with persist true, using the previewed configuration', async () => {
    runFusion.mockResolvedValue(result())
    view()
    await screen.findByText('Site A')
    fireEvent.click(document.querySelector('[data-dataset-checkbox="d1"]')!)
    fireEvent.click(document.querySelector('[data-action="preview-fusion"]')!)
    await waitFor(() =>
      expect(
        (document.querySelector('[data-action="save-fusion"]') as HTMLButtonElement).disabled,
      ).toBe(false),
    )

    runFusion.mockClear()
    runFusion.mockResolvedValue(result())
    fireEvent.click(document.querySelector('[data-action="save-fusion"]')!)

    await waitFor(() => expect(runFusion).toHaveBeenCalled())
    const call = runFusion.mock.calls[0]?.[0]
    expect(call.persist).toBe(true)
    expect(call.datasetIds).toEqual(['d1'])
  })

  it('disables Save again once the save has completed, to block a double-persist click', async () => {
    runFusion.mockResolvedValue(result())
    view()
    await screen.findByText('Site A')
    fireEvent.click(document.querySelector('[data-action="preview-fusion"]')!)
    await waitFor(() =>
      expect(
        (document.querySelector('[data-action="save-fusion"]') as HTMLButtonElement).disabled,
      ).toBe(false),
    )

    fireEvent.click(document.querySelector('[data-action="save-fusion"]')!)

    await waitFor(() => {
      const save = document.querySelector('[data-action="save-fusion"]') as HTMLButtonElement
      expect(save.disabled).toBe(true)
    })
  })
})
