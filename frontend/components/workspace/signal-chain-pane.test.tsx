/**
 * The Signal chain pane.
 *
 * Pins that the workspace shows the recorded Phase 5 signal-processing chain
 * verbatim -- ordered steps, `ran`, and parameters exactly as the backend
 * returned them -- and that a dataset with no `processing_applied` entry
 * reads as an explicit absence, never a synthetic default chain and never an
 * error. Also pins that this pane offers no way to reprocess or edit a
 * parameter: it is read-only.
 */
import { cleanup, render, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SignalProcessingChain } from '@/types/subterra'

const getSignalChain = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getSignalChain: (id: string) => getSignalChain(id),
    },
  }
})

import { SignalChainPane } from './signal-chain-pane'

function notRecorded(overrides: Partial<SignalProcessingChain> = {}): SignalProcessingChain {
  return {
    recorded: false,
    reason: 'no record carries a processing_applied entry -- preprocessing was not recorded for this dataset',
    steps: [],
    ...overrides,
  }
}

function recorded(overrides: Partial<SignalProcessingChain> = {}): SignalProcessingChain {
  return {
    recorded: true,
    reason: 'read from the processing_applied entry recorded on this dataset\'s records',
    steps: [
      {
        step: 'time_zero', ran: false, parameters: {},
        reason: 'process_gpr_traces does not apply a time-zero correction, and no '
          + 'time-zero claim was recorded for this dataset\'s frames',
      },
      { step: 'background_removal', ran: true, parameters: {}, reason: null },
      { step: 'dewow', ran: true, parameters: { dewow_window: 15 }, reason: null },
      { step: 'gain', ran: true, parameters: { gain_type: 'linear', gain_power: 1.0 }, reason: null },
    ],
    ...overrides,
  }
}

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <SignalChainPane datasetId="d1" />
    </SWRConfig>,
  )
}

beforeEach(() => getSignalChain.mockReset())
afterEach(cleanup)

describe('a dataset with no recorded processing', () => {
  it('states that preprocessing was not recorded, not an error and not a default chain', async () => {
    getSignalChain.mockResolvedValue(notRecorded())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-state-kind]')).toBeTruthy())
    expect(container.querySelector('[data-state-kind]')?.getAttribute('data-state-kind')).toBe('empty')
    expect(container.textContent).toContain(
      'no record carries a processing_applied entry',
    )
    expect(container.querySelector('[data-signal-chain]')).toBeNull()
  })
})

describe('a dataset whose recorded composition has no gpr', () => {
  it('uses a neutral title, never "not recorded", and prints the backend reason verbatim', async () => {
    getSignalChain.mockResolvedValue(
      notRecorded({
        reason: "this dataset's recorded modality composition is lidar; the GPR "
          + 'signal-processing chain (time-zero, background removal, dewow, gain) '
          + 'does not apply to it',
      }),
    )
    const { container, getByText } = view()

    await waitFor(() => expect(container.querySelector('[data-state-kind]')).toBeTruthy())
    expect(container.querySelector('[data-state-kind]')?.getAttribute('data-state-kind')).toBe('empty')
    expect(getByText('No signal chain')).toBeTruthy()
    expect(container.textContent).not.toContain('Preprocessing not recorded')
    expect(container.textContent).toContain('does not apply to it')
    expect(container.textContent).toContain('lidar')
  })
})

describe('the recorded chain, rendered verbatim', () => {
  it('shows every step in the order the backend returned, with its own ran state', async () => {
    getSignalChain.mockResolvedValue(recorded())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-signal-chain]')).toBeTruthy())
    const steps = container.querySelectorAll('[data-step]')
    expect(Array.from(steps).map((s) => s.getAttribute('data-step'))).toEqual([
      'time_zero', 'background_removal', 'dewow', 'gain',
    ])
    expect(container.querySelector('[data-step="time_zero"]')?.getAttribute('data-ran')).toBe('false')
    for (const step of container.querySelectorAll('[data-step]:not([data-step="time_zero"])')) {
      expect(step.getAttribute('data-ran')).toBe('true')
    }
  })

  it('prints parameters verbatim when present', async () => {
    getSignalChain.mockResolvedValue(recorded())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-signal-chain]')).toBeTruthy())
    const dewow = container.querySelector('[data-step="dewow"]')
    expect(dewow?.textContent).toContain('dewow_window: 15')
    const gain = container.querySelector('[data-step="gain"]')
    expect(gain?.textContent).toContain('gain_type: linear')
    expect(gain?.textContent).toContain('gain_power: 1')
  })

  it('shows a step that did not run, with no parameters invented', async () => {
    getSignalChain.mockResolvedValue(
      recorded({
        steps: [
          { step: 'background_removal', ran: true, parameters: {}, reason: null },
          { step: 'dewow', ran: false, parameters: {}, reason: null },
          { step: 'gain', ran: false, parameters: {}, reason: null },
        ],
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-signal-chain]')).toBeTruthy())
    const dewow = container.querySelector('[data-step="dewow"]')
    expect(dewow?.getAttribute('data-ran')).toBe('false')
    expect(dewow?.textContent).not.toContain('dewow_window')
  })

  it('prints the time_zero reason, and the recorded value when a converter claim exists', async () => {
    getSignalChain.mockResolvedValue(
      recorded({
        steps: [
          {
            step: 'time_zero', ran: false,
            parameters: { time_zero_offset_not_applied: 99.04 },
            reason: 'the header\'s rhf_position is 99.04 ns, but it is NOT applied.',
          },
          { step: 'background_removal', ran: true, parameters: {}, reason: null },
          { step: 'dewow', ran: true, parameters: { dewow_window: 15 }, reason: null },
          { step: 'gain', ran: true, parameters: { gain_type: 'linear', gain_power: 1.0 }, reason: null },
        ],
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-signal-chain]')).toBeTruthy())
    const timeZero = container.querySelector('[data-step="time_zero"]')
    expect(timeZero?.getAttribute('data-ran')).toBe('false')
    expect(timeZero?.textContent).toContain('NOT applied')
    expect(timeZero?.textContent).toContain('time_zero_offset_not_applied: 99.04')
  })

  it('offers no reprocess or edit control', async () => {
    getSignalChain.mockResolvedValue(recorded())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-signal-chain]')).toBeTruthy())
    expect(container.querySelector('button')).toBeNull()
    expect(container.querySelector('form')).toBeNull()
    expect(container.querySelector('input')).toBeNull()
  })
})

describe('the local_anomaly step', () => {
  it('is appended last, ran, and never presents the z-score as amplitude', async () => {
    getSignalChain.mockResolvedValue(
      recorded({
        steps: [
          ...recorded().steps,
          {
            step: 'local_anomaly', ran: true,
            parameters: { trace_depth_grid_shape: [482, 72] },
            reason: 'ring-based local anomaly z-score, a statistic derived from the '
              + 'processed amplitude -- not a physical unit',
          },
        ],
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-signal-chain]')).toBeTruthy())
    const steps = container.querySelectorAll('[data-step]')
    expect(Array.from(steps).map((s) => s.getAttribute('data-step'))).toEqual([
      'time_zero', 'background_removal', 'dewow', 'gain', 'local_anomaly',
    ])
    const localAnomaly = container.querySelector('[data-step="local_anomaly"]')
    expect(localAnomaly?.getAttribute('data-ran')).toBe('true')
    expect(localAnomaly?.textContent).toContain('not a physical unit')
    expect(localAnomaly?.textContent).toContain('trace_depth_grid_shape')
  })

  it('is omitted entirely when no anomaly_reliable stamp exists', async () => {
    getSignalChain.mockResolvedValue(recorded())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-signal-chain]')).toBeTruthy())
    expect(container.querySelector('[data-step="local_anomaly"]')).toBeNull()
    const steps = container.querySelectorAll('[data-step]')
    expect(Array.from(steps).map((s) => s.getAttribute('data-step'))).toEqual([
      'time_zero', 'background_removal', 'dewow', 'gain',
    ])
  })

  it('still offers no reprocess or edit control when local_anomaly is present', async () => {
    getSignalChain.mockResolvedValue(
      recorded({
        steps: [
          ...recorded().steps,
          { step: 'local_anomaly', ran: true, parameters: {}, reason: 'not a physical unit' },
        ],
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-signal-chain]')).toBeTruthy())
    expect(container.querySelector('button')).toBeNull()
    expect(container.querySelector('form')).toBeNull()
    expect(container.querySelector('input')).toBeNull()
  })
})

describe('the topographic_correction step', () => {
  it('renders with its own label, ran state, and parameters when derived', async () => {
    getSignalChain.mockResolvedValue(
      recorded({
        steps: [
          ...recorded().steps,
          {
            step: 'topographic_correction', ran: true,
            parameters: { topographic_correction_status: 'derived', topographic_correction_max_abs_ns: 0.48 },
            reason: null,
          },
        ],
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-signal-chain]')).toBeTruthy())
    const step = container.querySelector('[data-step="topographic_correction"]')
    expect(step?.getAttribute('data-ran')).toBe('true')
    expect(step?.textContent).toContain('Topographic / air-gap correction')
    expect(step?.textContent).toContain('derived')
  })

  it('is omitted entirely when no topographic_correction stamp exists', async () => {
    getSignalChain.mockResolvedValue(recorded())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-signal-chain]')).toBeTruthy())
    expect(container.querySelector('[data-step="topographic_correction"]')).toBeNull()
  })

  it('appears after local_anomaly when both are present', async () => {
    getSignalChain.mockResolvedValue(
      recorded({
        steps: [
          ...recorded().steps,
          { step: 'local_anomaly', ran: true, parameters: {}, reason: 'not a physical unit' },
          { step: 'topographic_correction', ran: false, parameters: { topographic_correction_status: 'not_material' }, reason: null },
        ],
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-signal-chain]')).toBeTruthy())
    const steps = container.querySelectorAll('[data-step]')
    expect(Array.from(steps).map((s) => s.getAttribute('data-step'))).toEqual([
      'time_zero', 'background_removal', 'dewow', 'gain', 'local_anomaly', 'topographic_correction',
    ])
  })
})
