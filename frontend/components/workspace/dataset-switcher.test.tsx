/**
 * The dataset switcher.
 *
 * Phase 7, slice 30 -- the switcher's option suffix printed the ingest
 * claim, `sensor_type`, as if it were the recorded instrument. This pins
 * that the suffix now reads "declared {sensor_type}", same wording as the
 * datasets list badge and DatasetSummaryPane's "Declared sensor" (slice 25),
 * that a null sensor_type prints no synthetic sensor value, and that the
 * unrelated "no geographic centre" suffix is untouched.
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

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

import { DatasetSwitcher } from './dataset-switcher'

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
      <DatasetSwitcher datasetId="d1" />
    </SWRConfig>,
  )
}

beforeEach(() => listDatasets.mockReset())
afterEach(cleanup)

describe('DatasetSwitcher', () => {
  it('prefixes a declared sensor_type as "declared", not the bare sensor value', async () => {
    view([dataset({ sensor_type: 'gpr' })])
    const option = await screen.findByRole('option', { name: /Site A/ })
    expect(option.textContent).toContain('declared gpr')
    expect(option.textContent).not.toMatch(/·\s*gpr(?!\s*·)/)
  })

  it('shows no sensor suffix, declared or synthetic, when sensor_type is null', async () => {
    view([dataset({ sensor_type: null })])
    const option = await screen.findByRole('option', { name: /Site A/ })
    expect(option.textContent).not.toContain('declared')
    expect(option.textContent).not.toContain('gpr')
  })

  it('still shows "no geographic centre" when center_lat is null', async () => {
    view([dataset({ center_lat: null, center_lon: null })])
    const option = await screen.findByRole('option', { name: /Site A/ })
    expect(option.textContent).toContain('no geographic centre')
  })

  it('never uses fusion, composition, or recorded-instrument vocabulary', async () => {
    view([dataset({ sensor_type: 'gpr' })])
    const option = await screen.findByRole('option', { name: /Site A/ })
    for (const forbidden of [
      'fused',
      'aligned',
      'ready for fusion',
      'recorded',
      'modality composition',
      'multi-modal',
    ]) {
      expect(option.textContent?.toLowerCase()).not.toContain(forbidden.toLowerCase())
    }
  })
})
