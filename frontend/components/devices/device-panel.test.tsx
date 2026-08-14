/**
 * Devices and acquisition sessions.
 *
 * The risk on this screen is not a broken button — it is an implication. A
 * device panel is exactly where an interface starts suggesting a connection
 * that does not exist, a serial number that was read rather than typed, or a
 * simulated instrument that looks like a real one. So these tests are mostly
 * about what the screen must NOT say.
 */
import { render, fireEvent, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import type { Device, SessionPayload } from '@/types/subterra'

const listDevices = vi.fn()
const registerDevice = vi.fn()
const createSession = vi.fn()
const getSession = vi.fn()
const moveSession = vi.fn()
const getImportFormats = vi.fn()
vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      listDevices: () => listDevices(),
      registerDevice: (b: unknown) => registerDevice(b),
      createSession: (id: string, b: unknown) => createSession(id, b),
      getSession: (id: string) => getSession(id),
      moveSession: (id: string, to: string) => moveSession(id, to),
      getImportFormats: () => getImportFormats(),
    },
  }
})

import { DevicePanel } from './device-panel'

function device(overrides: Partial<Device> = {}): Device {
  return {
    id: 'dev1',
    owner_id: 'u1',
    is_system_device: false,
    manufacturer: 'IDS',
    model: 'Stream C',
    device_type: 'gpr',
    serial_number: 'SN-9',
    firmware_version: null,
    capabilities: { modalities: ['gpr'], reports_position: true },
    adapter: null,
    identity_source: 'user_declared',
    kind: 'physical',
    is_simulated: false,
    label: null,
    created_at: '2026-08-12T10:00:00',
    ...overrides,
  }
}

function sessionPayload(overrides: Partial<SessionPayload> = {}): SessionPayload {
  return {
    session: {
      id: 's1',
      device_id: 'dev1',
      owner_id: 'u1',
      state: 'CREATED',
      label: null,
      operator: 'field team',
      notes: null,
      survey_area: null,
      evidence: { position_provided: false },
      failure_stage: null,
      failure_message: null,
      created_at: '2026-08-12T10:00:00',
      started_at: null,
      ended_at: null,
    },
    device: device(),
    capability_gap: [
      'a position: the device can report one and this session did not',
    ],
    acquisitions: [],
    datasets: [],
    ...overrides,
  }
}

async function renderPanel(devices: Device[] = [device()]) {
  listDevices.mockResolvedValue(devices)
  getImportFormats.mockResolvedValue({
    supported: ['.csv', '.sgy', '.dzt'],
    recognized_unsupported: [],
    max_upload_bytes: 2 * 1024 * 1024 * 1024,
    note: 'x',
  })
  const result = render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <DevicePanel />
    </SWRConfig>,
  )
  await new Promise((resolve) => setTimeout(resolve, 30))
  return result
}

beforeEach(() => {
  listDevices.mockReset()
  registerDevice.mockReset()
  createSession.mockReset()
  getSession.mockReset()
  moveSession.mockReset()
  getImportFormats.mockReset()
})

describe('no hardware is claimed', () => {
  it('says Subterra does not communicate with hardware', async () => {
    const { container } = await renderPanel()
    expect(container.textContent).toContain('does not communicate with hardware')
  })

  it('offers no connect, disconnect, or live acquisition control', async () => {
    const { container } = await renderPanel()
    const text = (container.textContent ?? '').toLowerCase()
    // The CLAIM is what is forbidden, not the word: the panel says "nothing
    // here connects to a device", which is the opposite of a claim.
    for (const claim of [
      'device connected',
      'connected to',
      'disconnect',
      'streaming',
      'acquiring live',
      'signal strength',
    ]) {
      expect(text).not.toContain(claim)
    }
    // And no control that would imply one.
    for (const action of ['connect-device', 'disconnect-device', 'start-streaming']) {
      expect(container.querySelector(`[data-action="${action}"]`)).toBeNull()
    }
  })

  it('renders no telemetry the platform cannot produce', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    const source = readFileSync(join(__dirname, 'device-panel.tsx'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, ' ')
      .replace(/\/\/[^\n]*/g, ' ')
    for (const forbidden of ['battery', 'signalStrength', 'WebSocket', 'EventSource']) {
      expect(source).not.toContain(forbidden)
    }
  })
})

describe('user-declared identity', () => {
  it('labels a serial number as user supplied', async () => {
    const { container } = await renderPanel()
    expect(container.textContent).toContain('SN-9')
    expect(container.textContent).toContain('user supplied')
  })

  it('says on the form that nothing is read off the instrument', async () => {
    const { container } = await renderPanel([])
    fireEvent.click(container.querySelector('[data-action="register-device"]')!)
    expect(container.querySelector('[data-device-form]')?.textContent).toContain(
      'cannot read a serial number off an instrument',
    )
  })

  it('never asks the client to set identity_source', async () => {
    registerDevice.mockResolvedValue({ device: device() })
    const { container } = await renderPanel([])
    fireEvent.click(container.querySelector('[data-action="register-device"]')!)
    fireEvent.change(container.querySelector('#device-manufacturer')!, {
      target: { value: 'IDS' },
    })
    fireEvent.submit(container.querySelector('form')!)

    await waitFor(() => expect(registerDevice).toHaveBeenCalled())
    const sent = registerDevice.mock.calls[0]?.[0] as Record<string, unknown>
    expect(Object.keys(sent)).not.toContain('identity_source')
  })
})

describe('capability declaration', () => {
  it('lets a device declare what it can report, framed as capability', async () => {
    const { container } = await renderPanel([])
    fireEvent.click(container.querySelector('[data-action="register-device"]')!)
    const form = container.querySelector('[data-device-form]')!

    expect(form.querySelector('#device-reports_position')).toBeTruthy()
    expect(form.textContent).toContain('not what any session actually')
  })

  it('sends capabilities as capabilities, never as evidence', async () => {
    registerDevice.mockResolvedValue({ device: device() })
    const { container } = await renderPanel([])
    fireEvent.click(container.querySelector('[data-action="register-device"]')!)
    fireEvent.click(container.querySelector('#device-reports_position')!)
    fireEvent.submit(container.querySelector('form')!)

    await waitFor(() => expect(registerDevice).toHaveBeenCalled())
    const sent = registerDevice.mock.calls[0]?.[0] as {
      capabilities?: Record<string, unknown>
    }
    expect(sent.capabilities?.reports_position).toBe(true)
    // Nothing about what a session provided is sent when registering a device.
    expect(Object.keys(sent)).not.toContain('evidence')
  })
})

describe('simulated devices', () => {
  it('is labelled as not real hardware', async () => {
    const { container } = await renderPanel([device({ kind: 'simulated', is_simulated: true })])
    expect(container.querySelector('[data-simulated]')?.textContent).toContain(
      'not real hardware',
    )
  })

  it('a physical device carries no simulation marker', async () => {
    const { container } = await renderPanel()
    expect(container.querySelector('[data-simulated]')).toBeNull()
  })
})

describe('the device profile', () => {
  it('reports frequency, channels and export formats declared on the device', async () => {
    const { container } = await renderPanel([
      device({
        capabilities: {
          modalities: ['gpr'],
          frequency_mhz: 400,
          channels: 2,
          supported_export_formats: ['.sgy', '.dzt'],
        },
      }),
    ])
    expect(container.textContent).toContain('400 MHz')
    expect(container.textContent).toContain('.sgy, .dzt')
  })

  it('shows the absence, not zero, when the profile is undeclared', async () => {
    const { container } = await renderPanel([device({ capabilities: { modalities: ['gpr'] } })])
    const frequency = Array.from(container.querySelectorAll('dt')).find(
      (dt) => dt.textContent === 'Frequency',
    )?.nextElementSibling
    expect(frequency?.textContent).not.toContain('MHz')
  })

  it('offers export formats from the platform read registry, not a hardcoded list', async () => {
    const { container } = await renderPanel([])
    fireEvent.click(container.querySelector('[data-action="register-device"]')!)
    await waitFor(() => expect(getImportFormats).toHaveBeenCalled())
    const form = container.querySelector('[data-device-form]')!
    await waitFor(() => expect(form.textContent).toContain('.sgy'))
    expect(form.textContent).toContain('.dzt')
  })

  it('sends the declared profile fields as capabilities, and omits blank ones', async () => {
    registerDevice.mockResolvedValue({ device: device() })
    const { container } = await renderPanel([])
    fireEvent.click(container.querySelector('[data-action="register-device"]')!)
    await waitFor(() => expect(getImportFormats).toHaveBeenCalled())

    fireEvent.change(container.querySelector('#device-frequency_mhz')!, {
      target: { value: '400' },
    })
    fireEvent.change(container.querySelector('#device-channels')!, {
      target: { value: '2' },
    })
    const sgyBox = Array.from(container.querySelectorAll('label')).find(
      (l) => l.textContent === '.sgy',
    )?.querySelector('input')
    fireEvent.click(sgyBox!)
    fireEvent.submit(container.querySelector('form')!)

    await waitFor(() => expect(registerDevice).toHaveBeenCalled())
    const sent = registerDevice.mock.calls[0]?.[0] as {
      capabilities?: {
        frequency_mhz?: number
        channels?: number
        sampling_configuration?: Record<string, number>
        supported_export_formats?: string[]
      }
    }
    expect(sent.capabilities?.frequency_mhz).toBe(400)
    expect(sent.capabilities?.channels).toBe(2)
    expect(sent.capabilities?.supported_export_formats).toEqual(['.sgy'])
    // sample_interval_ns / samples_per_trace were left blank -- undeclared,
    // not sent as zero.
    expect(sent.capabilities?.sampling_configuration).toEqual({})
  })
})

describe('the device adapter', () => {
  it('shows the declared transport on the saved card', async () => {
    const { container } = await renderPanel([
      device({ adapter: { transport: 'file_drop' } }),
    ])
    expect(container.textContent).toContain('file_drop')
  })

  it('shows the absence, not file_drop, when no adapter is declared', async () => {
    const { container } = await renderPanel([device({ adapter: null })])
    const row = Array.from(container.querySelectorAll('dt')).find(
      (dt) => dt.textContent === 'Evidence arrives via',
    )?.nextElementSibling
    expect(row?.textContent).not.toContain('file_drop')
  })

  it('offers no selectable network or serial option', async () => {
    const { container } = await renderPanel([])
    fireEvent.click(container.querySelector('[data-action="register-device"]')!)
    const form = container.querySelector('[data-device-form]')!
    expect(form.querySelector('#device-network')).toBeNull()
    expect(form.querySelector('#device-serial')).toBeNull()
    // Named, so an operator knows the platform recognises them --
    expect(form.textContent).toMatch(/network/i)
    // -- but never as a claim that either one works, matching the same
    // phrase-not-word rule the "no hardware is claimed" tests use: "cannot
    // connect" is the disclaimer, not the claim it disclaims.
    const text = (form.textContent ?? '').toLowerCase()
    for (const claim of ['connected to', 'will connect', 'connects to', 'pair with']) {
      expect(text).not.toContain(claim)
    }
  })

  it('sends a file_drop adapter only when declared, and nothing otherwise', async () => {
    registerDevice.mockResolvedValue({ device: device() })
    const { container } = await renderPanel([])
    fireEvent.click(container.querySelector('[data-action="register-device"]')!)
    fireEvent.click(container.querySelector('#device-file_drop')!)
    fireEvent.submit(container.querySelector('form')!)

    await waitFor(() => expect(registerDevice).toHaveBeenCalled())
    const sent = registerDevice.mock.calls[0]?.[0] as { adapter?: { transport: string } }
    expect(sent.adapter).toEqual({ transport: 'file_drop' })
  })

  it('omits the adapter entirely when the operator leaves it undeclared', async () => {
    registerDevice.mockResolvedValue({ device: device() })
    const { container } = await renderPanel([])
    fireEvent.click(container.querySelector('[data-action="register-device"]')!)
    fireEvent.submit(container.querySelector('form')!)

    await waitFor(() => expect(registerDevice).toHaveBeenCalled())
    const sent = registerDevice.mock.calls[0]?.[0] as { adapter?: unknown }
    expect(sent.adapter).toBeUndefined()
  })
})

describe('the declared survey area', () => {
  it('sends the survey area typed for that device when starting a session', async () => {
    createSession.mockResolvedValue({ session: sessionPayload().session, device: device() })
    getSession.mockResolvedValue(sessionPayload())
    const { container } = await renderPanel()

    fireEvent.change(container.querySelector('[data-survey-area-draft]')!, {
      target: { value: 'North field, behind the barn' },
    })
    fireEvent.click(container.querySelector('[data-action="start-session"]')!)

    await waitFor(() => expect(createSession).toHaveBeenCalled())
    expect(createSession).toHaveBeenCalledWith('dev1', {
      survey_area: 'North field, behind the barn',
    })
  })

  it('omits the field entirely when left blank, never an empty string', async () => {
    createSession.mockResolvedValue({ session: sessionPayload().session, device: device() })
    getSession.mockResolvedValue(sessionPayload())
    const { container } = await renderPanel()

    fireEvent.click(container.querySelector('[data-action="start-session"]')!)

    await waitFor(() => expect(createSession).toHaveBeenCalled())
    expect(createSession).toHaveBeenCalledWith('dev1', { survey_area: undefined })
  })
})

describe('sessions', () => {
  it('creates a session and shows its state', async () => {
    createSession.mockResolvedValue({ session: sessionPayload().session, device: device() })
    getSession.mockResolvedValue(sessionPayload())
    const { container } = await renderPanel()

    fireEvent.click(container.querySelector('[data-action="start-session"]')!)
    await waitFor(() => expect(container.querySelector('[data-session]')).toBeTruthy())
    expect(container.querySelector('[data-session-state]')?.getAttribute('data-session-state'))
      .toBe('CREATED')
  })

  it('shows what the device could provide and this session did not', async () => {
    createSession.mockResolvedValue({ session: sessionPayload().session, device: device() })
    getSession.mockResolvedValue(sessionPayload())
    const { container } = await renderPanel()
    fireEvent.click(container.querySelector('[data-action="start-session"]')!)

    await waitFor(() => expect(container.querySelector('[data-capability-gap]')).toBeTruthy())
    expect(container.querySelector('[data-gap]')?.textContent).toContain(
      'the device can report one and this session did not',
    )
  })

  it('offers only the transitions legal from the current state', async () => {
    createSession.mockResolvedValue({ session: sessionPayload().session, device: device() })
    getSession.mockResolvedValue(sessionPayload())
    const { container } = await renderPanel()
    fireEvent.click(container.querySelector('[data-action="start-session"]')!)

    await waitFor(() => expect(container.querySelector('[data-session]')).toBeTruthy())
    expect(container.querySelector('[data-action="session-ready"]')).toBeTruthy()
    // CREATED cannot jump straight to acquiring or completed.
    expect(container.querySelector('[data-action="session-acquiring"]')).toBeNull()
    expect(container.querySelector('[data-action="session-completed"]')).toBeNull()
  })

  it('offers nothing from a terminal state', async () => {
    const done = sessionPayload()
    done.session.state = 'COMPLETED'
    createSession.mockResolvedValue({ session: done.session, device: device() })
    getSession.mockResolvedValue(done)
    const { container } = await renderPanel()
    fireEvent.click(container.querySelector('[data-action="start-session"]')!)

    await waitFor(() => expect(container.querySelector('[data-session]')).toBeTruthy())
    for (const state of ['ready', 'acquiring', 'completed', 'cancelled']) {
      expect(container.querySelector(`[data-action="session-${state}"]`)).toBeNull()
    }
  })

  it('points acquisitions at the same import boundary a dropped file uses, attributed to this session', async () => {
    const open = sessionPayload()
    open.session.state = 'READY'
    createSession.mockResolvedValue({ session: open.session, device: device() })
    getSession.mockResolvedValue(open)
    const { container } = await renderPanel()
    fireEvent.click(container.querySelector('[data-action="start-session"]')!)

    await waitFor(() => expect(container.querySelector('[data-session]')).toBeTruthy())
    const text = container.textContent ?? ''
    expect(text).toContain('the same acquisition boundary')
    expect(container.querySelector(`a[href="/import?session=${open.session.id}"]`)).toBeTruthy()
  })

  it('shows a session failure with its stage', async () => {
    const failed = sessionPayload()
    failed.session.state = 'FAILED'
    failed.session.failure_stage = 'transport'
    failed.session.failure_message = 'the link dropped mid-line'
    createSession.mockResolvedValue({ session: failed.session, device: device() })
    getSession.mockResolvedValue(failed)
    const { container } = await renderPanel()
    fireEvent.click(container.querySelector('[data-action="start-session"]')!)

    await waitFor(() =>
      expect(container.querySelector('[data-session-failure]')?.textContent).toContain(
        'Failed at transport',
      ),
    )
  })

  it('links a produced dataset to its report', async () => {
    const withData = sessionPayload()
    withData.acquisitions = [
      { acquisition_id: 'j1', state: 'SUCCEEDED', original_filename: 'line1.csv',
        dataset_id: 'd9' },
    ]
    createSession.mockResolvedValue({ session: withData.session, device: device() })
    getSession.mockResolvedValue(withData)
    const { container } = await renderPanel()
    fireEvent.click(container.querySelector('[data-action="start-session"]')!)

    await waitFor(() =>
      expect(container.querySelector('[data-session-acquisition]')).toBeTruthy(),
    )
    expect(container.querySelector('a[href="/datasets/d9/report"]')).toBeTruthy()
  })

  it('shows the backend refusal of an illegal transition', async () => {
    const { ApiError } = await import('@/services/api')
    createSession.mockResolvedValue({ session: sessionPayload().session, device: device() })
    getSession.mockResolvedValue(sessionPayload())
    moveSession.mockRejectedValue(
      new ApiError(409, 'a session cannot go from CREATED to COMPLETED'),
    )
    const { container } = await renderPanel()
    fireEvent.click(container.querySelector('[data-action="start-session"]')!)
    await waitFor(() => expect(container.querySelector('[data-session]')).toBeTruthy())

    fireEvent.click(container.querySelector('[data-action="session-ready"]')!)
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(container.querySelector('[data-device-error]')?.textContent).toContain(
      'cannot go from CREATED',
    )
  })
})
