/**
 * The Modality composition pane.
 *
 * Pins that the workspace names the recorded modality composition of a
 * dataset's survey frames -- distinct `survey_frames[].modality` values,
 * verbatim, from `GET /api/datasets/{id}/info` -- and that it follows the
 * FRAMES, not `dataset.sensor_type` (the ingest declaration, which
 * `DatasetSummaryPane` alone renders). Also pins the vocabulary rules: one
 * modality is a complete answer (never "only" / "incomplete" / "waiting"),
 * two or more are named without ever claiming fusion ("fused" /
 * "multi-modal" / "aligned" / "ready for fusion"), and no frames / no
 * recorded modality is an explicit absence, never a synthetic `gpr`.
 */
import { cleanup, render, waitFor } from '@testing-library/react'
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

import { ModalityCompositionPane } from './modality-composition-pane'

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
      <ModalityCompositionPane datasetId="d1" />
    </SWRConfig>,
  )
}

beforeEach(() => getDatasetInfo.mockReset())
afterEach(cleanup)

describe('a single recorded modality', () => {
  it('names it as a complete answer, never "only", "incomplete", or "waiting"', async () => {
    getDatasetInfo.mockResolvedValue(
      info({ survey_frames: [surveyFrame(), surveyFrame({ frame_id: 'd:line2' })] }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-modality-composition]')).toBeTruthy())
    const modalities = container.querySelectorAll('[data-modality]')
    expect(Array.from(modalities).map((m) => m.getAttribute('data-modality'))).toEqual(['gpr'])
    expect(modalities[0]?.textContent).toContain('gpr')
    expect(modalities[0]?.textContent).toContain('2')

    const text = container.textContent?.toLowerCase() ?? ''
    for (const forbidden of ['only', 'incomplete', 'waiting', 'not yet multi-modal']) {
      expect(text).not.toContain(forbidden)
    }
  })

  it('leaves the ingest-declared sensor_type alone (not rendered by this pane)', async () => {
    getDatasetInfo.mockResolvedValue(info({ sensor_type: 'gpr' }))
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-modality-composition]')).toBeTruthy())
    // This pane names frame modalities, not the ingest declaration -- no
    // "Sensor" field lives here.
    expect(container.textContent).not.toContain('Sensor')
  })
})

describe('two or more recorded modalities', () => {
  it('names each verbatim, never as fusion', async () => {
    getDatasetInfo.mockResolvedValue(
      info({
        survey_frames: [
          surveyFrame({ frame_id: 'd:line1', modality: 'gpr' }),
          surveyFrame({ frame_id: 'd:line2', modality: 'lidar' }),
        ],
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-modality-composition]')).toBeTruthy())
    const modalities = container.querySelectorAll('[data-modality]')
    expect(Array.from(modalities).map((m) => m.getAttribute('data-modality')).sort())
      .toEqual(['gpr', 'lidar'])

    const text = container.textContent?.toLowerCase() ?? ''
    for (const forbidden of ['fused', 'multi-modal', 'multimodal', 'aligned', 'ready for fusion']) {
      expect(text).not.toContain(forbidden)
    }
  })

  it('follows the frames even when sensor_type disagrees, and does not hide the extra modality', async () => {
    getDatasetInfo.mockResolvedValue(
      info({
        sensor_type: 'gpr',
        survey_frames: [
          surveyFrame({ frame_id: 'd:line1', modality: 'gpr' }),
          surveyFrame({ frame_id: 'd:line2', modality: 'lidar' }),
        ],
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-modality-composition]')).toBeTruthy())
    const modalities = container.querySelectorAll('[data-modality]')
    expect(Array.from(modalities).map((m) => m.getAttribute('data-modality')).sort())
      .toEqual(['gpr', 'lidar'])
  })
})

describe('no recorded modality', () => {
  it('shows an explicit absence when there are no survey frames, not a synthetic gpr', async () => {
    getDatasetInfo.mockResolvedValue(info({ survey_frames: [] }))
    const { container, getByText } = view()

    await waitFor(() => expect(container.querySelector('[data-state-kind]')).toBeTruthy())
    expect(container.querySelector('[data-state-kind]')?.getAttribute('data-state-kind')).toBe('empty')
    expect(getByText('No recorded modality')).toBeTruthy()
    expect(container.querySelector('[data-modality-composition]')).toBeNull()
    expect(container.textContent).not.toContain('gpr')
  })

  it('shows an explicit absence when frames exist but none records a modality', async () => {
    getDatasetInfo.mockResolvedValue(
      info({ survey_frames: [surveyFrame({ modality: '' as unknown as string })] }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-state-kind]')).toBeTruthy())
    expect(container.querySelector('[data-state-kind]')?.getAttribute('data-state-kind')).toBe('empty')
    expect(container.querySelector('[data-modality-composition]')).toBeNull()
  })
})

describe('what this pane never does', () => {
  it('offers no fusion or generate control', async () => {
    getDatasetInfo.mockResolvedValue(info())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-modality-composition]')).toBeTruthy())
    expect(container.querySelector('button')).toBeNull()
    expect(container.querySelector('form')).toBeNull()
  })

  it('never renders a percentage, a confidence, or object-class language', async () => {
    getDatasetInfo.mockResolvedValue(
      info({
        survey_frames: [
          surveyFrame({ frame_id: 'd:line1', modality: 'gpr' }),
          surveyFrame({ frame_id: 'd:line2', modality: 'lidar' }),
        ],
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-modality-composition]')).toBeTruthy())
    expect(container.textContent).not.toContain('%')
    const text = container.textContent?.toLowerCase() ?? ''
    expect(text).not.toContain('confidence')
    expect(text).not.toMatch(/\bpipe\b/)
  })
})
