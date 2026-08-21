/**
 * The Dataset summary pane.
 *
 * Pins that the workspace names `dataset.sensor_type` -- the ingest
 * declaration -- as "Declared sensor", not "Sensor" (Phase 7, slice 25):
 * the dataset report already calls this same fact "Declared sensor" and the
 * frames "Recorded modality", and the workspace already has a separate
 * Modality composition pane for the frames' own claim, so a bare "Sensor"
 * label here reads as the recorded instrument rather than what the dataset
 * declared at ingest.
 *
 * Also pins that this pane never substitutes, corrects, hides or merges the
 * declaration against `survey_frames[].modality`, and that composition
 * itself stays on `ModalityCompositionPane`.
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { DatasetInfo, SurveyFrameSummary } from '@/types/subterra'

const getDatasetInfo = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getDatasetInfo: (id: string) => getDatasetInfo(id),
    },
  }
})

import { DatasetSummaryPane } from './dataset-summary-pane'

function surveyFrame(overrides: Partial<SurveyFrameSummary> = {}): SurveyFrameSummary {
  return {
    frame_id: 'd:line1',
    source_file: 'line1.sgy',
    source_format: 'segy',
    modality: 'gpr',
    modality_source: 'source_format',
    n_positions: 10,
    position_index_name: null,
    spatial_ref: { kind: 'unknown' },
    vertical_axis: {},
    assumptions: [],
    ...overrides,
  }
}

function info(overrides: Partial<DatasetInfo> = {}): DatasetInfo {
  return {
    dataset_id: 'd1',
    name: 'Site 01 GPR',
    sensor_type: 'gpr',
    original_format: 'segy',
    source: null,
    license: null,
    record_count: 10727,
    quality_score: 0.8,
    has_ground_truth: false,
    coordinate_system: 'EPSG:4326',
    position_sources: {},
    survey_frames: [surveyFrame()],
    survey_area_m: null,
    geographic_record_count: 0,
    grid_resolution_m: null,
    depth_layers: null,
    processing_applied: null,
    dem_aligned: false,
    last_preprocessing_mode: null,
    ...overrides,
  }
}

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <DatasetSummaryPane datasetId="d1" />
    </SWRConfig>,
  )
}

function fieldValue(label: string): string | null | undefined {
  const dt = screen.getByText(label)
  return dt.parentElement?.querySelector('dd')?.textContent
}

beforeEach(() => getDatasetInfo.mockReset())
afterEach(cleanup)

describe('the ingest declaration is labelled "Declared sensor"', () => {
  it('renders "Declared sensor", never bare "Sensor"', async () => {
    getDatasetInfo.mockResolvedValue(info({ sensor_type: 'gpr' }))
    const { container } = view()

    await waitFor(() => expect(container.textContent).toContain('Declared sensor'))
    expect(screen.queryByText('Sensor', { exact: true })).toBeNull()
  })

  it('shows the value from GET /api/datasets/{id}/info, verbatim', async () => {
    getDatasetInfo.mockResolvedValue(info({ sensor_type: 'gpr' }))
    view()

    await waitFor(() => expect(screen.getByText('Declared sensor')).toBeTruthy())
    expect(fieldValue('Declared sensor')).toBe('gpr')
  })

  it('shows the declaration unchanged even when frames record a different modality', async () => {
    getDatasetInfo.mockResolvedValue(
      info({
        sensor_type: 'gpr',
        survey_frames: [surveyFrame({ modality: 'lidar' })],
      }),
    )
    view()

    await waitFor(() => expect(screen.getByText('Declared sensor')).toBeTruthy())
    // The declaration is not hidden, merged with, or corrected against the
    // frames' own recorded modality -- it still reads the ingest claim.
    expect(fieldValue('Declared sensor')).toBe('gpr')
  })

  it('renders an absent declaration as the explained absence, never a synthetic "gpr"', async () => {
    getDatasetInfo.mockResolvedValue(info({ sensor_type: null as unknown as string }))
    view()

    await waitFor(() => expect(screen.getByText('Declared sensor')).toBeTruthy())
    expect(fieldValue('Declared sensor')).toBe('—')
  })

  it('does not render the recorded-modality composition -- that stays on ModalityCompositionPane', async () => {
    getDatasetInfo.mockResolvedValue(
      info({
        survey_frames: [
          surveyFrame({ frame_id: 'd:line1', modality: 'gpr' }),
          surveyFrame({ frame_id: 'd:line2', modality: 'lidar' }),
        ],
      }),
    )
    const { container } = view()

    await waitFor(() => expect(screen.getByText('Declared sensor')).toBeTruthy())
    expect(container.querySelector('[data-modality-composition]')).toBeNull()
    expect(container.querySelector('[data-modality]')).toBeNull()
  })
})
