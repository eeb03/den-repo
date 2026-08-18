/**
 * The Radargram pane.
 *
 * Phase 7, fifth slice. `GET .../trace_grid` answers 400 both when a dataset
 * genuinely lacks multi-sample GPR trace metadata AND, since this slice, when
 * a dataset's recorded modality composition simply has no gpr in it -- a
 * LiDAR/DEM dataset was never going to have a B-scan. Both are legitimate
 * absences (`ApiError.isAbsence`), not failures, and this pane must print the
 * backend's own reason verbatim rather than the generic "Could not load the
 * radargram" -- that title is reserved for a genuine failure (5xx / network),
 * which is pinned here too so the two states stay distinguishable.
 */
import { cleanup, render, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/services/api'
import type { CandidateIntelligence, TraceGrid } from '@/types/subterra'

const getTraceGrid = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getTraceGrid: (id: string, opts: unknown) => getTraceGrid(id, opts),
    },
  }
})

// Phase 7, twenty-first slice: SpatialPanes reads useCandidates to decide
// whether to mount RadargramPane at all. Partial-mocked so useTraceGrid
// stays the real hook -- the four existing RadargramPane cases below drive
// it through the mocked api.getTraceGrid above, unaffected by this mock.
const mockUseCandidates = vi.fn()

vi.mock('@/hooks/use-subterra', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/use-subterra')>(
    '@/hooks/use-subterra',
  )
  return {
    ...actual,
    useCandidates: (...args: unknown[]) => mockUseCandidates(...args),
  }
})

// The Spatial panel embeds the existing Plotly/thin-client iframes, which
// need their own hooks and DOM environment this file has no reason to
// exercise -- stubbed so the new SpatialPanes cases test the radargram
// gate, not the embed.
vi.mock('./embedded-viewer', () => ({
  EmbeddedViewer: () => null,
  EmbeddedThinClient: () => null,
}))

import { RadargramPane, SpatialPanes } from './spatial-panes'

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <RadargramPane datasetId="d1" selection={null} totalCount={5} loading={false} />
    </SWRConfig>,
  )
}

function spatialPanesView() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <SpatialPanes
        datasetId="d1"
        selection={null}
        placedCount={0}
        totalCount={5}
        loading={false}
      />
    </SWRConfig>,
  )
}

function offGprCandidates(overrides: Partial<CandidateIntelligence> = {}): CandidateIntelligence {
  return {
    dataset_id: 'd1',
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
    ...overrides,
  }
}

beforeEach(() => {
  // Fail closed: loading/missing candidates data must never hide the pane.
  mockUseCandidates.mockReturnValue({ data: undefined, error: null, isLoading: false })
  getTraceGrid.mockReset()
})

afterEach(cleanup)

describe('a dataset whose recorded composition has no gpr', () => {
  it('names the composition and says the grid does not apply, never "Could not load"', async () => {
    getTraceGrid.mockRejectedValue(
      new ApiError(
        400,
        "this dataset's recorded modality composition is lidar; a radargram / "
          + 'trace-depth grid is a GPR-trace view and does not apply to it',
      ),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-state-kind]')).toBeTruthy())
    expect(container.querySelector('[data-state-kind]')?.getAttribute('data-state-kind')).toBe(
      'unavailable',
    )
    expect(container.textContent).toContain('lidar')
    expect(container.textContent).toContain('does not apply to it')
    expect(container.textContent).not.toContain('Could not load the radargram')
    expect(container.textContent).not.toContain('not genuine multi-sample')
  })
})

describe('a dataset with no multi-sample trace metadata at all (empty composition)', () => {
  it('still renders the pre-slice-5 absence, verbatim', async () => {
    getTraceGrid.mockRejectedValue(
      new ApiError(
        400,
        'records are missing trace_index/depth metadata -- not genuine multi-sample GPR trace data',
      ),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-state-kind]')).toBeTruthy())
    expect(container.querySelector('[data-state-kind]')?.getAttribute('data-state-kind')).toBe(
      'unavailable',
    )
    expect(container.textContent).toContain('not genuine multi-sample GPR trace data')
  })
})

describe('a genuine failure, not an absence', () => {
  it('shows "Could not load the radargram", distinct from the absence states above', async () => {
    getTraceGrid.mockRejectedValue(new ApiError(500, 'internal server error'))
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-state-kind]')).toBeTruthy())
    expect(container.querySelector('[data-state-kind]')?.getAttribute('data-state-kind')).toBe(
      'error',
    )
    expect(container.textContent).toContain('Could not load the radargram')
  })
})

describe('a gpr dataset with a real grid', () => {
  it('renders the grid unchanged, with no fusion or multi-modal language', async () => {
    const grid: TraceGrid = {
      dataset_id: 'd1',
      name: 'd1',
      field: 'signal',
      semantics: null,
      reliability: null,
      candidate_footprints: null,
      source_file: 'Line1.sgy',
      available_source_files: ['Line1.sgy'],
      n_depths: 2,
      n_traces: 2,
      depths: [0, 1],
      trace_indices: [0, 1],
      grid: [
        [1, 2],
        [3, 4],
      ],
    } as unknown as TraceGrid
    getTraceGrid.mockResolvedValue(grid)
    const { container } = view()

    await waitFor(() => expect(container.textContent).toContain('Trace grid available'))
    for (const invented of ['fused', 'aligned', 'ready for fusion', 'multi-modal']) {
      expect(container.textContent?.toLowerCase()).not.toContain(invented)
    }
  })
})

describe('Phase 7, twenty-first slice: SpatialPanes does not mount the radargram pane when analysis does not apply', () => {
  it('off-gpr composition: no "Radargram" title, and useTraceGrid is never called', async () => {
    mockUseCandidates.mockReturnValue({ data: offGprCandidates(), error: null, isLoading: false })
    const { container } = spatialPanesView()

    await waitFor(() => expect(container.textContent).toContain('Spatial'))
    expect(container.textContent).not.toContain('Radargram')
    expect(getTraceGrid).not.toHaveBeenCalled()
  })

  it('"has not been run" is not the off-gpr reason: the pane still mounts', async () => {
    mockUseCandidates.mockReturnValue({
      data: offGprCandidates({
        status_reason: 'candidate generation has not been run for this dataset',
        missing: ['a candidate generation run'],
      }),
      error: null,
      isLoading: false,
    })
    getTraceGrid.mockRejectedValue(
      new ApiError(400, 'records are missing trace_index/depth metadata'),
    )
    const { container } = spatialPanesView()

    await waitFor(() => expect(container.textContent).toContain('Radargram'))
  })

  it('default/undefined candidates: fail closed, the pane still mounts', async () => {
    getTraceGrid.mockRejectedValue(
      new ApiError(400, 'records are missing trace_index/depth metadata'),
    )
    const { container } = spatialPanesView()

    await waitFor(() => expect(container.textContent).toContain('Radargram'))
  })
})
