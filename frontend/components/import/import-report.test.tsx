/**
 * The Dataset ready screen.
 *
 * Pins the two things the controller flagged as unguarded after the Phase 1
 * §3 commit: the heading reads "Dataset ready", not the old "Dataset
 * imported", and the vertical-datum / survey-frame / candidate rows are read
 * from the dataset rather than hardcoded to NOT DECLARED / BLOCKED for every
 * import. Without this file, a regression back to the hardcoded lines would
 * pass every existing test.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { CandidateIntelligence, DatasetInfo, ImportJob } from '@/types/subterra'

const getDatasetInfo = vi.fn()
const getCandidates = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getDatasetInfo: (id: string) => getDatasetInfo(id),
      getCandidates: (id: string) => getCandidates(id),
    },
  }
})

import { ImportReport } from './import-report'

function info(overrides: Partial<DatasetInfo> = {}): DatasetInfo {
  return {
    dataset_id: 'd1',
    name: 'Line1',
    sensor_type: 'gpr',
    original_format: 'segy',
    source: null,
    license: null,
    record_count: 400,
    quality_score: 0.8,
    has_ground_truth: false,
    coordinate_system: 'unknown',
    position_sources: {},
    survey_frames: [],
    survey_area_m: null,
    geographic_record_count: 0,
    grid_resolution_m: null,
    depth_layers: null,
    processing_applied: null,
    dem_aligned: false,
    last_preprocessing_mode: 'trace',
    ...overrides,
  }
}

function candidates(overrides: Partial<CandidateIntelligence> = {}): CandidateIntelligence {
  return {
    dataset_id: 'd1',
    status: 'blocked',
    status_reason: 'Candidate generation has not been run for this dataset.',
    missing: [],
    definition: 'x',
    generation: null,
    staleness: {
      is_stale: false,
      reasons: [],
      checks_performed: [],
      checks_skipped: [],
      note: '',
    },
    candidate_count: 0,
    candidates: [],
    ranking_basis: 'x',
    candidate_burden: null,
    candidate_burden_basis: 'x',
    localisation_breakdown: {},
    depth_breakdown: {},
    shape_classes: {},
    classification_status: 'blocked',
    classification_blocked_reason: 'x',
    classified_object_count: 0,
    benchmark: {} as CandidateIntelligence['benchmark'],
    ...overrides,
  }
}

function job(overrides: Partial<ImportJob> = {}): ImportJob {
  return {
    id: 'job-1',
    job_type: 'dataset_import',
    state: 'SUCCEEDED',
    stage: 'complete',
    original_filename: 'line1.sgy',
    stored_filename: 'line1.sgy',
    size_bytes: 1024,
    sensor_type: 'gpr',
    detected_format: 'segy',
    format_status: 'supported',
    dataset_id: 'd1',
    error_stage: null,
    error_message: null,
    owner_id: null,
    created_at: '2026-08-08T10:00:00',
    started_at: null,
    completed_at: null,
    ...overrides,
  }
}

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <ImportReport job={job()} onReset={vi.fn()} />
    </SWRConfig>,
  )
}

beforeEach(() => {
  getDatasetInfo.mockReset()
  getCandidates.mockReset()
})
afterEach(cleanup)

describe('the heading is a product result, not a generic success', () => {
  it('leads with "Dataset ready"', async () => {
    getDatasetInfo.mockResolvedValue(info())
    getCandidates.mockResolvedValue(candidates())
    view()

    await screen.findByText(/dataset ready/i)
    expect(screen.queryByText(/dataset imported/i)).toBeNull()
  })
})

describe('vertical datum is read, not asserted', () => {
  it('reports NOT DECLARED when no stored frame declares one', async () => {
    getDatasetInfo.mockResolvedValue(
      info({
        survey_frames: [
          {
            frame_id: 'f1',
            source_file: 'line1.sgy',
            source_format: 'segy',
            modality: 'gpr',
            modality_source: 'declared',
            n_positions: 400,
            position_index_name: null,
            spatial_ref: { kind: 'unknown' },
            vertical_axis: { kind: 'two_way_time_ns', vertical_datum: null },
            assumptions: [],
          },
        ],
      }),
    )
    getCandidates.mockResolvedValue(candidates())
    const { container } = view()

    await screen.findByText(/dataset ready/i)
    const row = container.querySelector('[data-report-row="Vertical datum"]')
    expect(row?.querySelector('[data-status]')?.textContent).toBe('NOT DECLARED')
  })

  it('reports the declared code -- not [object Object] -- when a frame has one', async () => {
    getDatasetInfo.mockResolvedValue(
      info({
        survey_frames: [
          {
            frame_id: 'f1',
            source_file: 'line1.sgy',
            source_format: 'segy',
            modality: 'gpr',
            modality_source: 'declared',
            n_positions: 400,
            position_index_name: null,
            spatial_ref: { kind: 'unknown' },
            vertical_axis: {
              kind: 'depth_m',
              vertical_datum: { code: 'NAP', provenance: 'declared_by_source', name: 'NAP' },
            },
            assumptions: [],
          },
        ],
      }),
    )
    getCandidates.mockResolvedValue(candidates())
    const { container } = view()

    await screen.findByText(/dataset ready/i)
    const row = container.querySelector('[data-report-row="Vertical datum"]')
    expect(row?.textContent).toContain('NAP')
    expect(row?.textContent).not.toContain('[object Object]')
    expect(row?.querySelector('[data-status]')?.textContent).toBe('AVAILABLE')
  })
})

describe('survey frame availability is reported, not assumed', () => {
  it('reports MISSING when the dataset has no stored frame', async () => {
    getDatasetInfo.mockResolvedValue(info({ survey_frames: [] }))
    getCandidates.mockResolvedValue(candidates())
    const { container } = view()

    await screen.findByText(/dataset ready/i)
    const row = container.querySelector('[data-report-row="Survey frame"]')
    expect(row?.querySelector('[data-status]')?.textContent).toBe('MISSING')
  })
})

describe('candidate-region count is read from the candidates API, not invented', () => {
  it('states the absence when generation has not been run', async () => {
    getDatasetInfo.mockResolvedValue(info())
    getCandidates.mockResolvedValue(candidates({ generation: null }))
    const { container } = view()

    await screen.findByText(/dataset ready/i)
    const row = container.querySelector('[data-report-row="Candidates"]')
    expect(row?.querySelector('[data-status]')?.textContent).toBe('MISSING')
    expect(row?.textContent).toMatch(/has not been run/i)
  })

  it('reports the stored count when generation has run', async () => {
    getDatasetInfo.mockResolvedValue(info())
    getCandidates.mockResolvedValue(
      candidates({
        status: 'available',
        candidate_count: 7,
        generation: {
          method: 'threshold',
          method_version: '1',
          parameters: { threshold: 3, min_cells: 4, min_trace_span: 1 },
          generated_at: '2026-08-14T00:00:00',
          dataset_id: 'd1',
          input_fingerprint: 'x',
          declared_reference_at: null,
          n_source_files: 1,
          n_records: 400,
          seed: null,
          deterministic: true,
          determinism_note: 'x',
        },
      }),
    )
    const { container } = view()

    await screen.findByText(/dataset ready/i)
    const row = container.querySelector('[data-report-row="Candidates"]')
    expect(row?.textContent).toContain('7')
    expect(row?.querySelector('[data-status]')?.textContent).toBe('AVAILABLE')
  })
})

describe('no hardcoded platform-wide blocker rides along with every import', () => {
  it('never renders a Localisation row', async () => {
    getDatasetInfo.mockResolvedValue(info())
    getCandidates.mockResolvedValue(candidates())
    const { container } = view()

    await screen.findByText(/dataset ready/i)
    expect(container.querySelector('[data-report-row="Localisation"]')).toBeNull()
  })
})
