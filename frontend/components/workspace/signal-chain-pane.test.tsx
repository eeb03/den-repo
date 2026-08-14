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
      { step: 'background_removal', ran: true, parameters: {} },
      { step: 'dewow', ran: true, parameters: { dewow_window: 15 } },
      { step: 'gain', ran: true, parameters: { gain_type: 'linear', gain_power: 1.0 } },
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
    const { container, getByText } = view()

    await waitFor(() => expect(container.querySelector('[data-state-kind]')).toBeTruthy())
    expect(container.querySelector('[data-state-kind]')?.getAttribute('data-state-kind')).toBe('empty')
    expect(getByText('Preprocessing not recorded')).toBeTruthy()
    expect(container.querySelector('[data-signal-chain]')).toBeNull()
  })
})

describe('the recorded chain, rendered verbatim', () => {
  it('shows every step in the order the backend returned, with its own ran state', async () => {
    getSignalChain.mockResolvedValue(recorded())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-signal-chain]')).toBeTruthy())
    const steps = container.querySelectorAll('[data-step]')
    expect(Array.from(steps).map((s) => s.getAttribute('data-step'))).toEqual([
      'background_removal', 'dewow', 'gain',
    ])
    for (const step of steps) {
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
          { step: 'background_removal', ran: true, parameters: {} },
          { step: 'dewow', ran: false, parameters: {} },
          { step: 'gain', ran: false, parameters: {} },
        ],
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-signal-chain]')).toBeTruthy())
    const dewow = container.querySelector('[data-step="dewow"]')
    expect(dewow?.getAttribute('data-ran')).toBe('false')
    expect(dewow?.textContent).not.toContain('dewow_window')
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
