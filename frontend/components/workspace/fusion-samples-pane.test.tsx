/**
 * The Fusion samples pane.
 *
 * Phase 7, slice 26 -- the first workspace surface for stored
 * `GET /api/fusion/samples`. Pins that this pane is read-only (no run /
 * generate control, nothing posts `/api/fusion/run`), that it filters the
 * global sample list to this dataset client-side, that zero matching
 * samples reads as a plain stored absence rather than "has not been run" or
 * "ready for fusion", and that stored fields print verbatim -- never
 * upgraded into a fusion or validation claim.
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { FusionSample } from '@/types/subterra'

const listFusionSamples = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      listFusionSamples: () => listFusionSamples(),
    },
  }
})

import { FusionSamplesPane } from './fusion-samples-pane'

function sample(overrides: Partial<FusionSample> = {}): FusionSample {
  return {
    id: 'fs-1',
    spatial_ref_kind: 'geographic',
    center_lat: 52.24,
    center_lon: 6.85,
    center_x: null,
    center_y: null,
    sensor_types: ['gpr'],
    dataset_ids: ['d1'],
    has_ground_truth: false,
    ...overrides,
  }
}

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <FusionSamplesPane datasetId="d1" />
    </SWRConfig>,
  )
}

beforeEach(() => listFusionSamples.mockReset())
afterEach(cleanup)

describe('label', () => {
  it('is "Fusion samples"', async () => {
    listFusionSamples.mockResolvedValue([])
    view()
    await waitFor(() => expect(screen.getByText('Fusion samples')).toBeTruthy())
  })
})

describe('no stored samples at all', () => {
  it('shows "No fusion samples", never a GPR-only or not-yet-run wording', async () => {
    listFusionSamples.mockResolvedValue([])
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-state-kind]')).toBeTruthy())
    expect(screen.getByText('No fusion samples')).toBeTruthy()
    const text = container.textContent?.toLowerCase() ?? ''
    for (const forbidden of [
      'fused', 'aligned', 'ready for fusion', 'has not been run',
      'incomplete', 'waiting', 'gpr-only', 'not yet multi-modal',
    ]) {
      expect(text).not.toContain(forbidden)
    }
  })
})

describe('stored samples exist, but none include this dataset', () => {
  it('shows the same plain absence', async () => {
    listFusionSamples.mockResolvedValue([
      sample({ id: 'fs-other', dataset_ids: ['d2', 'd3'] }),
    ])
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-state-kind]')).toBeTruthy())
    expect(screen.getByText('No fusion samples')).toBeTruthy()
    expect(container.querySelector('[data-fusion-samples]')).toBeNull()
  })
})

describe('one stored sample includes this dataset', () => {
  it('prints sensor_types, spatial_ref_kind and dataset_ids verbatim', async () => {
    listFusionSamples.mockResolvedValue([
      sample({
        id: 'fs-1',
        sensor_types: ['gpr', 'lidar'],
        dataset_ids: ['d1', 'd9'],
        spatial_ref_kind: 'geographic',
      }),
    ])
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-fusion-samples]')).toBeTruthy())
    const row = container.querySelector('[data-fusion-sample="fs-1"]')
    expect(row?.textContent).toContain('gpr, lidar')
    expect(row?.textContent).toContain('geographic')
    expect(row?.textContent).toContain('d1, d9')
  })

  it('never upgrades sensor_types into a "multi-modal" or fusion claim', async () => {
    listFusionSamples.mockResolvedValue([
      sample({ sensor_types: ['gpr', 'lidar'] }),
    ])
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-fusion-samples]')).toBeTruthy())
    const text = container.textContent?.toLowerCase() ?? ''
    for (const forbidden of ['fused', 'aligned', 'ready for fusion', 'multi-modal']) {
      expect(text).not.toContain(forbidden)
    }
  })
})

describe('a mixed-modality dataset with zero stored samples', () => {
  it('still shows the plain absence -- composition is not fusion', async () => {
    listFusionSamples.mockResolvedValue([])
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-state-kind]')).toBeTruthy())
    expect(screen.getByText('No fusion samples')).toBeTruthy()
    expect(container.textContent?.toLowerCase()).not.toContain('ready for fusion')
  })
})

describe('centre depends on spatial_ref_kind', () => {
  it('a geographic sample prints lat/lon', async () => {
    listFusionSamples.mockResolvedValue([
      sample({ spatial_ref_kind: 'geographic', center_lat: 52.24, center_lon: 6.85 }),
    ])
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-fusion-samples]')).toBeTruthy())
    const row = container.querySelector('[data-fusion-sample="fs-1"]')
    expect(row?.textContent).toContain('52.240000')
    expect(row?.textContent).toContain('6.850000')
  })

  it('a non-geographic sample with null lat/lon does not invent a geographic centre', async () => {
    listFusionSamples.mockResolvedValue([
      sample({
        spatial_ref_kind: 'projected',
        center_lat: null,
        center_lon: null,
        center_x: 501134.2,
        center_y: 4544705.8,
      }),
    ])
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-fusion-samples]')).toBeTruthy())
    const row = container.querySelector('[data-fusion-sample="fs-1"]')
    expect(row?.textContent).toContain('501134.20')
    expect(row?.textContent).toContain('4544705.80')
    // A real centre was supplied, so nothing here should fall back to
    // NO_VALUE -- confirms the wrong pair (lat/lon) was not read instead.
    expect(row?.textContent).not.toContain('—')
  })

  it('a non-geographic sample with a null centre renders the explained absence, not zero', async () => {
    listFusionSamples.mockResolvedValue([
      sample({
        spatial_ref_kind: 'local_cartesian',
        center_lat: null,
        center_lon: null,
        center_x: null,
        center_y: null,
      }),
    ])
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-fusion-samples]')).toBeTruthy())
    const row = container.querySelector('[data-fusion-sample="fs-1"]')
    expect(row?.textContent).toContain('—')
    expect(row?.textContent).not.toContain('0.00')
  })
})

describe('has_ground_truth is printed as the stored boolean', () => {
  it('never upgraded to "validated" or "confirmed targets"', async () => {
    listFusionSamples.mockResolvedValue([sample({ has_ground_truth: true })])
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-fusion-samples]')).toBeTruthy())
    const row = container.querySelector('[data-fusion-sample="fs-1"]')
    expect(row?.textContent).toContain('true')
    const text = container.textContent?.toLowerCase() ?? ''
    expect(text).not.toContain('validated')
    expect(text).not.toContain('confirmed target')
  })
})

describe('read-only', () => {
  it('offers no run or generate control, and never mentions fusion/run', async () => {
    listFusionSamples.mockResolvedValue([sample()])
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-fusion-samples]')).toBeTruthy())
    expect(container.querySelector('button')).toBeNull()
    expect(container.querySelector('[data-action]')).toBeNull()
    expect(container.textContent).not.toContain('fusion/run')
  })
})
