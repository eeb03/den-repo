/**
 * The Acquisition pane.
 *
 * Pins the three states `GET /api/datasets/{id}/acquisition` can report, and
 * that none of them is reconstructed: a dataset produced through a device
 * session shows that device (and the simulated marker, when it is one); a
 * FileDrop dataset says explicitly that it has no session or device, rather
 * than looking identical to a session's dataset; a dataset that predates the
 * acquisition boundary shows the backend's own reason, not a fabricated one.
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { DatasetAcquisition } from '@/types/subterra'

const getDatasetAcquisition = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getDatasetAcquisition: (id: string) => getDatasetAcquisition(id),
    },
  }
})

import { AcquisitionPane } from './acquisition-pane'

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <AcquisitionPane datasetId="d1" />
    </SWRConfig>,
  )
}

beforeEach(() => getDatasetAcquisition.mockReset())
afterEach(cleanup)

describe('a dataset produced through a device session', () => {
  const payload: DatasetAcquisition = {
    dataset_id: 'd1',
    acquisition: {
      id: 'j1',
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
      owner_id: 'u1',
      created_at: '2026-08-14T10:00:00',
      started_at: null,
      completed_at: null,
    },
    session: {
      id: 's1',
      device_id: 'dev1',
      owner_id: 'u1',
      state: 'ACQUIRING',
      label: null,
      operator: 'field team',
      notes: null,
      survey_area: null,
      evidence: { position_provided: false },
      failure_stage: null,
      failure_message: null,
      created_at: '2026-08-14T09:00:00',
      started_at: '2026-08-14T09:05:00',
      ended_at: null,
    },
    device: {
      id: 'dev1',
      owner_id: 'u1',
      is_system_device: false,
      manufacturer: 'IDS',
      model: 'Stream C',
      device_type: 'gpr',
      serial_number: 'SN-9',
      firmware_version: null,
      capabilities: { modalities: ['gpr'] },
      adapter: { transport: 'file_drop' },
      identity_source: 'user_declared',
      kind: 'physical',
      is_simulated: false,
      label: null,
      created_at: '2026-08-13T09:00:00',
    },
  }

  it('shows the device, the session state and the operator', async () => {
    getDatasetAcquisition.mockResolvedValue(payload)
    const { container } = view()

    await screen.findByText('IDS Stream C')
    expect(container.querySelector('[data-acquisition-kind="session"]')).toBeTruthy()
    expect(container.textContent).toContain('ACQUIRING')
    expect(container.textContent).toContain('field team')
  })

  it('shows the simulated marker only for a simulated device', async () => {
    getDatasetAcquisition.mockResolvedValue({
      ...payload,
      device: { ...payload.device!, kind: 'simulated', is_simulated: true },
    })
    const { container } = view()

    await screen.findByText('IDS Stream C')
    expect(container.querySelector('[data-simulated]')?.textContent).toContain(
      'not real hardware',
    )
  })

  it('carries no simulated marker for a physical device', async () => {
    getDatasetAcquisition.mockResolvedValue(payload)
    const { container } = view()

    await screen.findByText('IDS Stream C')
    expect(container.querySelector('[data-simulated]')).toBeNull()
  })

  it('links back to devices and sessions', async () => {
    getDatasetAcquisition.mockResolvedValue(payload)
    const { container } = view()

    await screen.findByText('IDS Stream C')
    expect(container.querySelector('a[href="/devices"]')).toBeTruthy()
  })

  it('shows the declared survey area when the session has one', async () => {
    getDatasetAcquisition.mockResolvedValue({
      ...payload,
      session: { ...payload.session!, survey_area: 'North field, behind the barn' },
    })
    const { container } = view()

    await screen.findByText('IDS Stream C')
    expect(container.textContent).toContain('North field, behind the barn')
  })

  it('shows no survey area row when the session has none, never a fabricated one', async () => {
    getDatasetAcquisition.mockResolvedValue(payload) // survey_area: null
    const { container } = view()

    await screen.findByText('IDS Stream C')
    expect(container.textContent).not.toMatch(/survey area/i)
  })
})

describe('a FileDrop dataset', () => {
  it('says it has no session or device, rather than looking like a session dataset', async () => {
    getDatasetAcquisition.mockResolvedValue({
      dataset_id: 'd1',
      acquisition: {
        id: 'j1',
        job_type: 'dataset_import',
        state: 'SUCCEEDED',
        stage: 'complete',
        original_filename: 'a.csv',
        stored_filename: 'a.csv',
        size_bytes: 100,
        sensor_type: 'gpr',
        detected_format: 'csv',
        format_status: 'supported',
        dataset_id: 'd1',
        error_stage: null,
        error_message: null,
        owner_id: 'u1',
        created_at: '2026-08-14T10:00:00',
        started_at: null,
        completed_at: null,
      },
      session: null,
      device: null,
    } satisfies DatasetAcquisition)
    const { container } = view()

    await waitFor(() =>
      expect(container.querySelector('[data-acquisition-kind="file_drop"]')).toBeTruthy(),
    )
    expect(container.textContent).toMatch(/dropped file/i)
    expect(container.querySelector('[data-acquisition-kind="session"]')).toBeNull()
  })
})

describe('a dataset that predates the acquisition boundary', () => {
  it('shows the backend reason as an absence, not an error', async () => {
    getDatasetAcquisition.mockResolvedValue({
      dataset_id: 'd1',
      acquisition: null,
      session: null,
      device: null,
      reason: 'this dataset predates the acquisition boundary, so how its source file arrived was never recorded',
    } satisfies DatasetAcquisition)
    const { container } = view()

    await screen.findByText(/predates the acquisition boundary/i)
    expect(container.querySelector('[data-acquisition-kind]')).toBeNull()
  })
})
