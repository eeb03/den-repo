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
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/services/api'
import type { TraceGrid } from '@/types/subterra'

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

import { RadargramPane } from './spatial-panes'

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <RadargramPane datasetId="d1" selection={null} totalCount={5} loading={false} />
    </SWRConfig>,
  )
}

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
