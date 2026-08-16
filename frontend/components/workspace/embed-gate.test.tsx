/**
 * The embedded spatial viewer.
 *
 * The honesty guarantee for unpositioned data lives in
 * `visualization/viewer.html`, which filters on `position_kind` and reports
 * how many records it excluded -- pinned by
 * `tests/test_viewer_positions.py`. This component therefore does NOT
 * re-decide whether the viewer may be shown; duplicating that judgement
 * would give one question two answers, and gating the embed would also
 * hide the B-scan, which works fine without coordinates.
 *
 * What these tests pin is the part this component does own: telling the
 * operator, before they wonder, that the scene will be empty and why.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { CandidateIntelligence, DatasetInfo } from '@/types/subterra'

const mockUseDatasetInfo = vi.fn()
const mockUseCandidates = vi.fn()

vi.mock('@/hooks/use-subterra', () => ({
  useDatasetInfo: (...args: unknown[]) => mockUseDatasetInfo(...args),
  useCandidates: (...args: unknown[]) => mockUseCandidates(...args),
}))

const { EmbeddedViewer } = await import('./embedded-viewer')

beforeEach(() => {
  // Every existing case stays on the GPR path unless a test overrides this
  // with setCandidates -- loading/missing candidates must never drop the
  // B-scan sentence.
  mockUseCandidates.mockReturnValue({ data: undefined, error: null, isLoading: false })
})

afterEach(() => {
  cleanup()
  mockUseDatasetInfo.mockReset()
  mockUseCandidates.mockReset()
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
  mockUseDatasetInfo.mockReturnValue({ data: value, error: null, isLoading: false })
}

function setCandidates(value: CandidateIntelligence) {
  mockUseCandidates.mockReturnValue({ data: value, error: null, isLoading: false })
}

function offGprCandidates(): CandidateIntelligence {
  return {
    dataset_id: 'ds',
    status: 'blocked',
    status_reason:
      "this dataset's recorded modality composition is lidar; candidate analysis is a "
      + 'GPR-trace capability and does not apply to it',
    missing: ['a GPR acquisition, or frames recording GPR traces'],
    definition: 'x',
    generation: null,
    staleness: {
      is_stale: false, reasons: [], checks_performed: [], checks_skipped: [], note: '',
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
  }
}

describe('an unpositioned dataset is embedded, with the reason stated up front', () => {
  it('warns that nothing can be placed, and names the position sources', () => {
    setInfo(info({ geographic_record_count: 0 }))
    const { container } = render(<EmbeddedViewer datasetId="ds" />)
    expect(container.querySelector('[data-unpositioned-notice]')).toBeTruthy()
    expect(screen.getByText(/No positioned records\./i)).toBeTruthy()
    expect(container.textContent).toMatch(/none: 10,727/)
  })

  it('says the B-scan still works, so a usable view is not written off', () => {
    setInfo(info({ geographic_record_count: 0 }))
    const { container } = render(<EmbeddedViewer datasetId="ds" />)
    expect(container.textContent).toMatch(/B-scan is indexed by trace and depth/i)
  })

  it('still embeds the viewer, which reports the exclusion itself', () => {
    setInfo(info({ geographic_record_count: 0 }))
    const { container } = render(<EmbeddedViewer datasetId="ds" />)
    expect(container.querySelector('iframe')).toBeTruthy()
  })

  it('Phase 7, sixteenth slice: drops the B-scan sentence when candidate analysis does not apply', () => {
    setInfo(info({ geographic_record_count: 0 }))
    setCandidates(offGprCandidates())
    const { container } = render(<EmbeddedViewer datasetId="ds" />)

    expect(container.textContent).toMatch(/No positioned records/i)
    expect(container.textContent).toMatch(/point cloud, heatmap and surface/i)
    expect(container.textContent).not.toMatch(/B-scan/i)
    expect(container.textContent).not.toMatch(/trace and depth/i)
    expect(container.querySelector('iframe')).toBeTruthy()
  })
})

describe('a positioned dataset shows no warning', () => {
  it('embeds without the notice', () => {
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
    expect(container.querySelector('[data-unpositioned-notice]')).toBeNull()
    expect(container.querySelector('iframe')!.getAttribute('src')).toContain(
      '/viewer?datasets=d3dca710',
    )
  })

  it('a partially positioned dataset is treated as positioned', () => {
    // The backend decides; the UI invents no coverage threshold.
    setInfo(
      info({
        geographic_record_count: 1,
        record_count: 10727,
        position_sources: { geographic: 1, none: 10726 },
      }),
    )
    const { container } = render(<EmbeddedViewer datasetId="ds" />)
    expect(container.querySelector('[data-unpositioned-notice]')).toBeNull()
    expect(container.querySelector('iframe')).toBeTruthy()
  })
})

describe('the embed is constrained and withheld until the answer is known', () => {
  it('sandboxes the iframe to only what it needs', () => {
    setInfo(info({ geographic_record_count: 100 }))
    const sandbox =
      render(<EmbeddedViewer datasetId="ds" />)
        .container.querySelector('iframe')!
        .getAttribute('sandbox') ?? ''
    expect(sandbox).toContain('allow-scripts')
    expect(sandbox).not.toContain('allow-forms')
    expect(sandbox).not.toContain('allow-popups')
    expect(sandbox).not.toContain('allow-top-navigation')
  })

  it('renders nothing embeddable while loading', () => {
    mockUseDatasetInfo.mockReturnValue({ data: null, error: null, isLoading: true })
    expect(
      render(<EmbeddedViewer datasetId="ds" />).container.querySelector('iframe'),
    ).toBeNull()
  })

  it('renders an error, not an embed, when the answer could not be fetched', () => {
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
