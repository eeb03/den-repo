/**
 * The datasets list.
 *
 * Phase 7, slice 30 -- the sensor_type badge on each row printed the ingest
 * claim as if it were the recorded instrument. This pins that the badge now
 * reads "declared {sensor_type}", same wording as the switcher (this slice)
 * and DatasetSummaryPane's "Declared sensor" (slice 25), that a null
 * sensor_type renders no badge at all (never a synthetic sensor value), and
 * that the unrelated original_format badge is unchanged and unlabeled.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { DatasetSummary } from '@/types/subterra'

const listDatasets = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      listDatasets: () => listDatasets(),
    },
  }
})

import DatasetsPage from './page'

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

function view(datasets: DatasetSummary[]) {
  listDatasets.mockResolvedValue(datasets)
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <DatasetsPage />
    </SWRConfig>,
  )
}

beforeEach(() => listDatasets.mockReset())
afterEach(cleanup)

describe('DatasetsPage', () => {
  it('shows "declared gpr" on the sensor badge for a declared sensor_type', async () => {
    view([dataset({ sensor_type: 'gpr' })])
    const row = await screen.findByText('Site A')
    const li = row.closest('li')
    expect(li?.textContent).toContain('declared')
    expect(li?.textContent).toContain('gpr')
  })

  it('renders no declared-sensor badge, and no synthetic sensor value, when sensor_type is null', async () => {
    view([dataset({ sensor_type: null })])
    const row = await screen.findByText('Site A')
    const li = row.closest('li')
    expect(li?.textContent).not.toContain('declared')
    expect(li?.textContent).not.toContain('gpr')
  })

  it('still shows original_format as its own unlabeled badge, unchanged', async () => {
    view([dataset({ original_format: 'segy' })])
    const row = await screen.findByText('Site A')
    const li = row.closest('li')
    expect(li?.textContent).toContain('segy')
    expect(li?.textContent).not.toContain('declared segy')
  })

  it('never uses fusion, composition, or recorded-instrument vocabulary', async () => {
    view([dataset({ sensor_type: 'gpr' })])
    const row = await screen.findByText('Site A')
    const li = row.closest('li')
    for (const forbidden of [
      'fused',
      'aligned',
      'ready for fusion',
      'recorded sensor',
      'modality composition',
      'multi-modal',
    ]) {
      expect(li?.textContent?.toLowerCase()).not.toContain(forbidden.toLowerCase())
    }
  })
})
