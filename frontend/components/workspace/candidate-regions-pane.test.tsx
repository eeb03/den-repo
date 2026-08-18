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

  it('prints benchmark.summary verbatim, from the payload', async () => {
    getCandidates.mockResolvedValue(
      available({
        benchmark: {
          method: 'ring_local_anomaly_connected_components', method_version: '1.0.0',
          summary: 'This method performs at approximately chance on both benchmarks it '
            + 'has been scored against.',
          measurements: [], caveat: '',
        },
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    const summary = container.querySelector('[data-benchmark-summary]')
    expect(summary?.textContent).toBe(
      'This method performs at approximately chance on both benchmarks it has '
      + 'been scored against.',
    )
  })

  it('never renders benchmark.measurements or any performance number', async () => {
    getCandidates.mockResolvedValue(
      available({
        benchmark: {
          method: 'ring_local_anomaly_connected_components', method_version: '1.0.0',
          summary: 'This method performs at approximately chance.',
          measurements: [
            {
              benchmark: 'bam-concrete-gpr', arm: '1.5 GHz', precision: 0.1351, recall: 0.0652,
              source: 'artifacts/bam/score_1_5_GHz_Rot00.json',
            },
          ],
          caveat: 'The 4TU separation rests on seven attested-empty trenches.',
        },
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.textContent).not.toContain('0.1351')
    expect(container.textContent).not.toContain('bam-concrete-gpr')
    expect(container.textContent).not.toContain('attested-empty trenches')
  })
})

describe('generation identity', () => {
  it('prints method and version from the payload when generation is recorded', async () => {
    getCandidates.mockResolvedValue(
      available({
        generation: {
          method: 'ring_local_anomaly_connected_components', method_version: '2.3.1',
          parameters: { threshold: 3.0, min_cells: 3, min_trace_span: 1 },
          generated_at: '2026-08-13T09:00:00Z', dataset_id: 'd1',
          input_fingerprint: 'abc123', declared_reference_at: null,
          n_source_files: 1, n_records: 24000, seed: null,
          deterministic: true, determinism_note: 'no randomness is used',
        },
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    const generation = container.querySelector('[data-generation]')
    expect(generation?.textContent).toBe('ring_local_anomaly_connected_components v2.3.1')
  })

  it('prints "unrecorded" when generation is null', async () => {
    getCandidates.mockResolvedValue(available({ generation: null }))
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    const generation = container.querySelector('[data-generation]')
    expect(generation?.textContent).toBe('unrecorded')
  })

  it('never renders generation parameters, fingerprint, seed, or record counts', async () => {
    getCandidates.mockResolvedValue(
      available({
        generation: {
          method: 'ring_local_anomaly_connected_components', method_version: '1.0.0',
          parameters: { threshold: 3.0, min_cells: 3, min_trace_span: 1 },
          generated_at: '2026-08-13T09:00:00Z', dataset_id: 'd1',
          input_fingerprint: 'fingerprint-xyz-999', declared_reference_at: null,
          n_source_files: 1, n_records: 24000, seed: 42,
          deterministic: true, determinism_note: 'no randomness is used',
        },
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.textContent).not.toContain('fingerprint-xyz-999')
    expect(container.textContent).not.toContain('24000')
    expect(container.textContent).not.toContain('threshold')
  })
})

describe('staleness', () => {
  it('prints a banner with the stored reasons and note, verbatim, when stale', async () => {
    getCandidates.mockResolvedValue(
      available({
        staleness: {
          is_stale: true,
          reasons: ['3 records were added after this set was generated'],
          checks_performed: ['method version', 'records'],
          checks_skipped: [],
          note: 'nothing is recomputed automatically',
        },
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    const stale = container.querySelector('[data-stale]')
    expect(stale).toBeTruthy()
    expect(stale?.textContent).toContain('no longer matches the dataset')
    expect(stale?.textContent).toContain('3 records were added after this set was generated')
    expect(stale?.textContent).toContain('nothing is recomputed automatically')
  })

  it('does not hide the count or the benchmark summary when the set is stale', async () => {
    getCandidates.mockResolvedValue(
      available({
        staleness: {
          is_stale: true, reasons: ['records changed'], checks_performed: [],
          checks_skipped: [], note: 'nothing is recomputed automatically',
        },
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.textContent).toContain('7')
    expect(container.querySelector('[data-benchmark-summary]')).toBeTruthy()
  })

  it('prints no stale banner and no "fresh"/"current" badge when not stale', async () => {
    getCandidates.mockResolvedValue(available())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.querySelector('[data-stale]')).toBeNull()
    const text = container.textContent?.toLowerCase() ?? ''
    expect(text).not.toContain('fresh')
    expect(text).not.toContain('up to date')
    expect(text).not.toMatch(/\bcurrent\b/)
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
    // Phase 7, twelfth slice: this is "has not been run", not "does not
    // apply" -- the method's definition still belongs on the page.
    expect(container.textContent).toContain(DEFINITION)
  })

  it('does not print a benchmark sentence over a set that does not exist', async () => {
    getCandidates.mockResolvedValue(blocked())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.querySelector('[data-benchmark-summary]')).toBeNull()
  })

  it('shows no generation identity, no stale banner, even when the fixture carries them', async () => {
    getCandidates.mockResolvedValue(
      blocked({
        generation: {
          method: 'ring_local_anomaly_connected_components', method_version: '1.0.0',
          parameters: { threshold: 3.0, min_cells: 3, min_trace_span: 1 },
          generated_at: '2026-08-13T09:00:00Z', dataset_id: 'd1',
          input_fingerprint: 'abc123', declared_reference_at: null,
          n_source_files: 1, n_records: 24000, seed: null,
          deterministic: true, determinism_note: 'no randomness is used',
        },
        staleness: {
          is_stale: true, reasons: ['records changed'], checks_performed: [],
          checks_skipped: [], note: 'nothing is recomputed automatically',
        },
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.querySelector('[data-generation]')).toBeNull()
    expect(container.querySelector('[data-stale]')).toBeNull()
    expect(container.textContent).not.toContain('unrecorded')
    expect(container.textContent).not.toContain('no longer matches the dataset')
  })
})

describe('Phase 7, twelfth and twenty-fourth slices: does not open under the method\'s vocabulary, and does not invite the workflow, when analysis does not apply', () => {
  it('hides the definition and the workflow link, but keeps the reason and the absence box', async () => {
    getCandidates.mockResolvedValue(
      blocked({
        status_reason:
          "this dataset's recorded modality composition is lidar; candidate analysis is a "
          + 'GPR-trace capability and does not apply to it',
        missing: ['a GPR acquisition, or frames recording GPR traces'],
      }),
    )
    const { container, getByText } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.textContent).not.toContain(DEFINITION)
    expect(getByText('No candidate set')).toBeTruthy()
    expect(container.textContent).toContain('lidar')
    expect(container.textContent).toContain('does not apply to it')
    expect(container.querySelector('[data-benchmark-summary]')).toBeNull()
    expect(container.querySelector('a[href="/datasets/d1/candidates"]')).toBeNull()
    // still no generate control, same as every other blocked reason
    expect(container.textContent?.toLowerCase()).not.toContain('generate')
  })

  it('"has not been run" is not the off-gpr reason: the workflow link stays', async () => {
    getCandidates.mockResolvedValue(blocked())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.querySelector('a[href="/datasets/d1/candidates"]')).toBeTruthy()
  })

  it('fails closed: blocked without the phrase keeps the workflow link', async () => {
    getCandidates.mockResolvedValue(
      blocked({ status_reason: 'trace-local anomaly preprocessing has not been run' }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-candidate-regions]')).toBeTruthy())
    expect(container.querySelector('a[href="/datasets/d1/candidates"]')).toBeTruthy()
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
