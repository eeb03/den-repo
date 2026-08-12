/**
 * Dataset management: rename, delete, status, duplicate awareness.
 *
 * The risk here is not that a button fails to work — it is that a button works
 * too easily. Deletion is irreversible and operates on data somebody may have
 * spent a day acquiring, so most of what follows checks that it is hard to do
 * by accident, that it says what survives, and that the two datasets in this
 * corpus which share a name cannot be confused for one another.
 */
import { render, fireEvent, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import type { DatasetSummary } from '@/types/subterra'

const renameDataset = vi.fn()
const deleteDataset = vi.fn()
const rescoreDataset = vi.fn()
vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      renameDataset: (...a: unknown[]) => renameDataset(...a),
      deleteDataset: (...a: unknown[]) => deleteDataset(...a),
      rescoreDataset: (...a: unknown[]) => rescoreDataset(...a),
    },
  }
})

import { DatasetActions } from './dataset-actions'
import { DatasetStatusBadge } from './dataset-status'

function dataset(overrides: Partial<DatasetSummary> = {}): DatasetSummary {
  return {
    id: 'd1',
    name: 'Site 01 GPR',
    source: null,
    sensor_type: 'gpr',
    original_format: 'segy',
    quality_score: 0.8,
    record_count: 10727,
    has_ground_truth: false,
    center_lat: null,
    center_lon: null,
    version: 1,
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-02T00:00:00',
    source_file: 'line1.sgy',
    checksum: 'abc123',
    is_system_dataset: false,
    status: 'ready',
    status_reason: '10,727 record(s) are stored and readable',
    job_state: 'SUCCEEDED',
    job_id: 'j1',
    shares_source_with: [],
    ...overrides,
  }
}

function renderActions(data: DatasetSummary = dataset()) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <DatasetActions dataset={data} />
    </SWRConfig>,
  )
}

beforeEach(() => {
  renameDataset.mockReset()
  deleteDataset.mockReset()
  rescoreDataset.mockReset()
})

describe('rename', () => {
  it('offers a rename action', () => {
    const { container } = renderActions()
    expect(container.querySelector('[data-action="rename"]')).toBeTruthy()
  })

  it('sends the new name and nothing else', async () => {
    renameDataset.mockResolvedValue(dataset({ name: 'Renamed' }))
    const { container } = renderActions()

    fireEvent.click(container.querySelector('[data-action="rename"]')!)
    const input = container.querySelector('#rename-d1') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'Renamed survey' } })
    fireEvent.submit(container.querySelector('form')!)

    await waitFor(() => expect(renameDataset).toHaveBeenCalledWith('d1', 'Renamed survey'))
    expect(renameDataset).toHaveBeenCalledTimes(1)
  })

  it('says what a rename does not change', () => {
    const { container } = renderActions()
    fireEvent.click(container.querySelector('[data-action="rename"]')!)
    const text = container.textContent ?? ''
    expect(text).toContain('Only the display name changes')
    expect(text).toContain('line1.sgy')
    expect(text.toLowerCase()).toContain('provenance')
  })

  it('shows the backend refusal verbatim', async () => {
    const { ApiError } = await import('@/services/api')
    renameDataset.mockRejectedValue(new ApiError(422, 'a dataset name cannot be empty'))
    const { container } = renderActions()

    fireEvent.click(container.querySelector('[data-action="rename"]')!)
    fireEvent.submit(container.querySelector('form')!)

    await waitFor(() =>
      expect(container.querySelector('[data-action-error]')?.textContent).toBe(
        'a dataset name cannot be empty',
      ),
    )
  })
})

describe('delete', () => {
  it('does not delete on a single click', () => {
    const { container } = renderActions()
    fireEvent.click(container.querySelector('[data-action="delete"]')!)
    expect(deleteDataset).not.toHaveBeenCalled()
    expect(container.querySelector('[data-delete-confirm]')).toBeTruthy()
  })

  it('stays disabled until the dataset name is typed exactly', () => {
    const { container } = renderActions()
    fireEvent.click(container.querySelector('[data-action="delete"]')!)
    const confirm = container.querySelector('[data-action="confirm-delete"]') as HTMLButtonElement

    expect(confirm.disabled).toBe(true)
    fireEvent.change(container.querySelector('#confirm-d1')!, {
      target: { value: 'Site 01' },
    })
    expect(confirm.disabled).toBe(true) // a prefix is not the name
    fireEvent.change(container.querySelector('#confirm-d1')!, {
      target: { value: 'Site 01 GPR' },
    })
    expect(confirm.disabled).toBe(false)
  })

  it('states what survives before the user commits', () => {
    const { container } = renderActions()
    fireEvent.click(container.querySelector('[data-action="delete"]')!)
    const text = container.textContent ?? ''
    expect(text).toContain('cannot be recovered')
    expect(text).toContain('original source file')
    expect(text).toContain('line1.sgy')
  })

  it('reports what was removed and what was kept', async () => {
    deleteDataset.mockResolvedValue({
      deleted: 'd1',
      removed: { artifacts: ['d1.jsonl', 'd1.frames.json'], fusion_samples: 1, versions: 0 },
      retained: { raw_source: '/data/raw/line1.sgy', import_jobs: 1, why: '…' },
    })
    const { container } = renderActions()

    fireEvent.click(container.querySelector('[data-action="delete"]')!)
    fireEvent.change(container.querySelector('#confirm-d1')!, {
      target: { value: 'Site 01 GPR' },
    })
    fireEvent.click(container.querySelector('[data-action="confirm-delete"]')!)

    await waitFor(() => expect(container.querySelector('[data-deleted]')).toBeTruthy())
    const text = container.textContent ?? ''
    expect(text).toContain('2 derived artifacts removed')
    expect(container.querySelector('[data-retained]')?.textContent).toContain(
      '/data/raw/line1.sgy',
    )
  })

  it('keeps the outcome on screen until it is dismissed', async () => {
    // Browser verification caught this: refreshing the list on success unmounts
    // the row this component lives in, so the outcome flashed and vanished.
    deleteDataset.mockResolvedValue({
      deleted: 'd1',
      removed: { artifacts: ['d1.jsonl'], fusion_samples: 0, versions: 0 },
      retained: { raw_source: '/data/raw/line1.sgy', import_jobs: 1, why: '…' },
    })
    const onDeleted = vi.fn()
    const { container } = render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <DatasetActions dataset={dataset()} onDeleted={onDeleted} />
      </SWRConfig>,
    )

    fireEvent.click(container.querySelector('[data-action="delete"]')!)
    fireEvent.change(container.querySelector('#confirm-d1')!, {
      target: { value: 'Site 01 GPR' },
    })
    fireEvent.click(container.querySelector('[data-action="confirm-delete"]')!)

    await waitFor(() => expect(container.querySelector('[data-deleted]')).toBeTruthy())
    // The list is not told to refresh until the user has read the outcome.
    expect(onDeleted).not.toHaveBeenCalled()

    fireEvent.click(container.querySelector('[data-action="dismiss-deleted"]')!)
    await waitFor(() => expect(onDeleted).toHaveBeenCalled())
  })

  it('surfaces a refusal to delete a dataset that is importing', async () => {
    const { ApiError } = await import('@/services/api')
    deleteDataset.mockRejectedValue(
      new ApiError(409, 'an import for this dataset is running; wait for it to finish'),
    )
    const { container } = renderActions()

    fireEvent.click(container.querySelector('[data-action="delete"]')!)
    fireEvent.change(container.querySelector('#confirm-d1')!, {
      target: { value: 'Site 01 GPR' },
    })
    fireEvent.click(container.querySelector('[data-action="confirm-delete"]')!)

    await waitFor(() =>
      expect(container.querySelector('[data-action-error]')?.textContent).toContain(
        'wait for it to finish',
      ),
    )
    expect(container.querySelector('[data-deleted]')).toBeNull()
  })
})

describe('system reference data', () => {
  it('offers neither rename nor delete', () => {
    const { container } = renderActions(dataset({ is_system_dataset: true }))
    expect(container.querySelector('[data-action="rename"]')).toBeNull()
    expect(container.querySelector('[data-action="delete"]')).toBeNull()
    expect(container.querySelector('[data-system-dataset]')?.textContent).toContain(
      'modifiable by no one',
    )
  })
})

describe('status', () => {
  it.each([
    ['ready', 'Ready'],
    ['importing', 'Importing'],
    ['empty', 'Empty'],
    ['failed', 'Failed'],
  ] as const)('renders %s distinctly', (status, label) => {
    const { container } = render(<DatasetStatusBadge dataset={dataset({ status })} />)
    expect(container.querySelector(`[data-status="${status}"]`)?.textContent).toContain(label)
  })

  it('carries the backend reason rather than inventing one', () => {
    const { container } = render(
      <DatasetStatusBadge
        dataset={dataset({ status: 'failed', status_reason: 'conversion failed: bad header' })}
      />,
    )
    expect(container.querySelector('[data-status]')?.getAttribute('title')).toBe(
      'conversion failed: bad header',
    )
  })

  it('computes nothing about status itself', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    const source = readFileSync(join(__dirname, 'dataset-status.tsx'), 'utf8')
    // No local re-derivation from record counts or job states.
    expect(source).not.toContain('record_count')
    expect(source).not.toContain('QUEUED')
  })
})
