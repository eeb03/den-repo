/**
 * The Candidate regions pane.
 *
 * Pins that the workspace shows the stored candidate-region summary --
 * verbatim definition, region count, `classification_status: BLOCKED` with
 * its stored reason -- from the SAME `GET /api/candidates/{id}` payload
 * `/datasets/{id}/candidates` uses. Also pins that a dataset with no
 * candidate set reads as an explicit absence (not an error, not a
 * synthetic "0 findings"), and that this pane offers no generate control
 * and never renders a score, a confidence, or an object class.
 */
import { cleanup, render, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { CandidateIntelligence } from '@/types/subterra'

const getCandidates = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getCandidates: (id: string) => getCandidates(id),
    },
  }
})

import { CandidateRegionsPane } from './candidate-regions-pane'

const DEFINITION =
  'a region of the processed signal whose measured characteristics satisfy a '
  + 'candidate-generation rule. It is not a detected object, not a validated '
  + 'detection, and not evidence that anything is buried at this location.'

function blocked(overrides: Partial<CandidateIntelligence> = {}): CandidateIntelligence {
  return {
    dataset_id: 'd1',
    status: 'blocked',
    status_reason: 'candidate generation has not been run for this dataset',
    missing: ['a candidate generation run'],
    definition: DEFINITION,
    generation: null,
    staleness: {
      is_stale: false, reasons: [], checks_performed: [], checks_skipped: [],
      note: 'nothing is recomputed automatically',
    },
    candidate_count: 0,
    candidates: [],
    ranking_basis: 'peak local-anomaly z magnitude; it is not a probability',
    candidate_burden: null,
    candidate_burden_basis: 'candidates per 1000 traces examined',
    localisation_breakdown: {},
    depth_breakdown: {},
    shape_classes: {},
    classification_status: 'BLOCKED',
    classification_blocked_reason:
      'no validated classifier exists in this repository, and no benchmark here '
      + 'supports mapping a candidate to an object identity',
    classified_object_count: 0,
    benchmark: {
      method: 'ring_local_anomaly_connected_components', method_version: '1.0.0',
      summary: 'This method performs at approximately chance.', measurements: [],
      caveat: '',
    },
    ...overrides,
  }
}

function available(overrides: Partial<CandidateIntelligence> = {}): CandidateIntelligence {
  return blocked({
    status: 'available',
    status_reason: 'generated from 1 survey line(s)',
    missing: [],
    candidate_count: 7,
    ...overrides,
  })
}

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <CandidateRegionsPane datasetId="d1" />
    </SWRConfig>,
  )
}

beforeEach(() => getCandidates.mockReset())
afterEach(cleanup)

describe('a dataset with a stored candidate set', () => {
  it('prints the region count, the verbatim definition, and classification_status: BLOCKED', async () => {
    getCandidates.mockResolvedValue(available())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.textContent).toContain(DEFINITION)
    expect(container.textContent).toContain('7')
    const status = container.querySelector('[data-classification-status]')
    expect(status?.textContent).toBe('BLOCKED')
    expect(container.textContent).toContain(
      'no validated classifier exists in this repository',
    )
  })

  it('links to the existing candidates page and nowhere else', async () => {
    getCandidates.mockResolvedValue(available())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    const link = container.querySelector('a')
    expect(link?.getAttribute('href')).toBe('/datasets/d1/candidates')
  })
})

describe('a dataset with no candidate set', () => {
  it('shows an explicit absence, not an error and not a synthetic empty finding', async () => {
    getCandidates.mockResolvedValue(blocked())
    const { container, getByText } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.querySelector('[data-candidate-regions]')?.getAttribute('data-candidate-regions'))
      .toBe('blocked')
    expect(container.querySelector('[data-state-kind]')?.getAttribute('data-state-kind')).toBe('empty')
    expect(getByText('No candidate set')).toBeTruthy()
    expect(container.textContent).toContain('candidate generation has not been run')
    // No count/classification block for the absent case.
    expect(container.querySelector('[data-classification-status]')).toBeNull()
  })
})

describe('what this pane never does', () => {
  it('offers no generate or regenerate control', async () => {
    getCandidates.mockResolvedValue(available())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.querySelector('button')).toBeNull()
    expect(container.querySelector('form')).toBeNull()
  })

  it('never renders a candidate score, a percentage, or a confidence value', async () => {
    getCandidates.mockResolvedValue(available())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.textContent).not.toContain('%')
    expect(container.textContent?.toLowerCase()).not.toContain('confidence')
    expect(container.textContent?.toLowerCase()).not.toMatch(/\bpipe\b/)
  })

  it('offers no generate control even when the set is blocked', async () => {
    getCandidates.mockResolvedValue(blocked())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.querySelector('button')).toBeNull()
  })
})
