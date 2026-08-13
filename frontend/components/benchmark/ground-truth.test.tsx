/**
 * The ground-truth panel.
 *
 * THE PROPERTY UNDER TEST is that the page cannot make an underpowered
 * benchmark look adequate. Three specific ways it could:
 *
 *   1. rendering UNKNOWN units among the negatives — the cheapest way to
 *      inflate the population every false-alarm claim rests on
 *   2. hiding that two units share the same bytes with opposite labels
 *   3. summarising fitness as a single badge, when fitness is per-question
 *
 * Fixtures are trimmed from the real artifact and keep its exact shape and
 * values, so a change in the backend's vocabulary fails here.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { BenchmarkDefinition } from '@/types/subterra'

const getBenchmarkArtifact = vi.fn()
vi.mock('@/hooks/use-subterra', async () => {
  const actual = await vi.importActual<typeof import('@/hooks/use-subterra')>(
    '@/hooks/use-subterra',
  )
  return {
    ...actual,
    useBenchmarkArtifact: (name?: string) => ({
      data: name ? getBenchmarkArtifact(name) : undefined,
      error: undefined,
      isLoading: false,
    }),
  }
})

import { GroundTruthPanel } from './ground-truth-panel'

function definition(overrides: Partial<BenchmarkDefinition> = {}): BenchmarkDefinition {
  return {
    benchmark: '4tu-nl-utility',
    version: '1.a5669dcdc9d8e9d2',
    schema_version: '1',
    content_hash: 'a5669dcdc9d8e9d2',
    counts: {
      units: 125,
      by_label: { negative: 7, positive: 112, unknown: 6 },
      by_duplicate_status: { contaminated: 2, duplicate_of: 4, independent: 119 },
      independent_positives: 107,
      independent_negatives: 6,
    },
    policies: {
      duplicate: 'compared by checksum',
      exclusion: 'a blank field is not an absence',
      metric: 'activity-level density separation only',
      threshold: 'Detector thresholds are NOT part of this benchmark',
    },
    power: {
      benchmark: '4tu-nl-utility',
      n_positive: 107,
      n_negative: 6,
      alpha: 0.05,
      power: 0.8,
      smallest_detectable_auc: 0.7415408839078994,
      negatives_required: { '0.6': 161, '0.65': 30, '0.7': 12, '0.75': 6 },
      se_at_chance: 0.1216,
      adequate_for_a_useful_detector: false,
      adequacy_anchor: 'AUC 0.70',
      method: 'Hanley & McNeil (1982)',
      caveat: 'An approximation, and a sample-size recommendation is not a guarantee.',
    },
    readiness: [
      {
        name: 'negative evidence',
        readiness: 'partial',
        reason: '6 independent attested-empty unit(s); 6 unit(s) are UNKNOWN and are not counted as absences',
        missing: ['more independently attested-empty units — 6 further would allow AUC 0.70'],
      },
      {
        name: 'depth truth',
        readiness: 'blocked',
        reason: 'no unit publishes a usable depth',
        missing: ['an unambiguous depth reference surface from the publisher'],
      },
    ],
    open_questions: [
      {
        id: 'attested-zero-population-is-small',
        statement: 'Only a handful of activities report a trench count of zero.',
        blocks: 'a false-alarm RATE on real-world ground',
        resolution_route: 'more zero-utility trenches, or another real-world corpus',
        status: 'BLOCKED',
        request_status: 'OUTSTANDING -- no request recorded in this repository',
      },
    ],
    units: [],
    ...overrides,
  }
}

function artifact(defn = definition()) {
  return {
    generated_by: 'scripts/build_benchmark_definition.py',
    reads_detector_output: false,
    corpus_unmodified: true,
    benchmarks: { '4tu-nl-utility': defn },
    bootstrap_cross_check: {},
  }
}

beforeEach(() => {
  getBenchmarkArtifact.mockReset()
})
afterEach(cleanup)

describe('unknown is never rendered as negative', () => {
  it('shows unknown units in their own row, marked as not counted', () => {
    getBenchmarkArtifact.mockReturnValue(artifact())
    const { container } = render(<GroundTruthPanel name="benchmark/definition" />)

    expect(container.querySelector('[data-unknown-units]')?.textContent).toBe('6')
    expect(container.querySelector('[data-independent-negatives]')?.textContent).toBe('6')
    expect(container.textContent).toMatch(/not counted as absences/i)
  })

  it('never adds unknown units into the negative count', () => {
    getBenchmarkArtifact.mockReturnValue(artifact())
    const { container } = render(<GroundTruthPanel name="benchmark/definition" />)
    // 6 negatives + 6 unknown must never be shown as 12 of anything.
    expect(container.querySelector('[data-independent-negatives]')?.textContent).not.toBe('12')
  })
})

describe('contamination is visible', () => {
  it('warns that units share data with the opposite label', () => {
    getBenchmarkArtifact.mockReturnValue(artifact())
    const { container } = render(<GroundTruthPanel name="benchmark/definition" />)

    expect(container.querySelector('[data-contaminated-units]')?.textContent).toBe('2')
    expect(container.querySelector('[data-contamination-warning]')?.textContent).toMatch(
      /cannot be evidence both that something is present and that nothing is/i,
    )
  })

  it('omits the warning when nothing is contaminated', () => {
    const clean = definition({
      counts: { ...definition().counts, by_duplicate_status: { independent: 125 } },
    })
    getBenchmarkArtifact.mockReturnValue(artifact(clean))
    const { container } = render(<GroundTruthPanel name="benchmark/definition" />)
    expect(container.querySelector('[data-contamination-warning]')).toBeNull()
  })
})

describe('the power finding is stated plainly', () => {
  it('says the smallest improvement the corpus could recognise', () => {
    getBenchmarkArtifact.mockReturnValue(artifact())
    const { container } = render(<GroundTruthPanel name="benchmark/definition" />)

    expect(container.querySelector('[data-smallest-detectable]')?.textContent).toBe('0.742')
    expect(container.textContent).toMatch(/would not be recognisable/i)
  })

  it('lists how many negatives each target improvement needs', () => {
    getBenchmarkArtifact.mockReturnValue(artifact())
    const { container } = render(<GroundTruthPanel name="benchmark/definition" />)

    const rows = Array.from(container.querySelectorAll('[data-negatives-required]'))
      .map((n) => n.textContent)
      .join(' ')
    expect(rows).toMatch(/AUC 0\.7 — 12/)
    expect(rows).toMatch(/holding 6/)
  })

  it('renders an absent estimate as absent, never as zero', () => {
    const noEstimate = definition({
      power: { ...definition().power!, smallest_detectable_auc: null,
               negatives_required: { '0.7': null } },
    })
    getBenchmarkArtifact.mockReturnValue(artifact(noEstimate))
    const { container } = render(<GroundTruthPanel name="benchmark/definition" />)

    expect(container.querySelector('[data-smallest-detectable]')).toBeNull()
    expect(container.textContent).toMatch(/no estimate is possible/i)
    expect(container.textContent).not.toMatch(/AUC 0\.000/)
  })
})

describe('readiness is per dimension, not a badge', () => {
  it('renders each dimension with its own state and what it needs', () => {
    getBenchmarkArtifact.mockReturnValue(artifact())
    const { container } = render(<GroundTruthPanel name="benchmark/definition" />)

    expect(container.querySelectorAll('[data-readiness]').length).toBe(2)
    expect(container.querySelector('[data-readiness="blocked"]')?.textContent).toMatch(
      /depth truth/i,
    )
    expect(container.querySelectorAll('[data-readiness-missing]').length).toBe(2)
  })

  it('shows no aggregate benchmark score or pass/fail verdict', () => {
    getBenchmarkArtifact.mockReturnValue(artifact())
    const { container } = render(<GroundTruthPanel name="benchmark/definition" />)
    const text = container.textContent ?? ''

    expect(text).not.toMatch(/overall score|benchmark score|\bpass\b|\bfail\b|grade/i)
    expect(text).not.toMatch(/\d+\s*\/\s*100/)
  })
})

describe('external evidence is recorded, not claimed', () => {
  it('shows what is blocked and that no request has been made', () => {
    getBenchmarkArtifact.mockReturnValue(artifact())
    const { container } = render(<GroundTruthPanel name="benchmark/definition" />)

    const question = container.querySelector('[data-open-question]')
    expect(question?.textContent).toMatch(/more zero-utility trenches/i)
    expect(container.querySelector('[data-request-status]')?.textContent).toMatch(
      /OUTSTANDING/,
    )
  })

  it('never implies a reply was received', () => {
    getBenchmarkArtifact.mockReturnValue(artifact())
    const { container } = render(<GroundTruthPanel name="benchmark/definition" />)
    expect(container.textContent).not.toMatch(/replied|response received|awaiting reply/i)
  })
})

describe('absence of the artifact', () => {
  it('says the definition has not been generated rather than showing nothing', () => {
    render(<GroundTruthPanel name={null} />)
    expect(screen.getByText(/No ground-truth benchmark definition/i)).toBeTruthy()
  })

  it('reports an unavailable benchmark with its reason', () => {
    getBenchmarkArtifact.mockReturnValue({
      generated_by: 's', reads_detector_output: false, corpus_unmodified: true,
      benchmarks: { 'bam-concrete-gpr': { unavailable: true, reason: 'archive absent' } },
      bootstrap_cross_check: {},
    })
    const { container } = render(<GroundTruthPanel name="benchmark/definition" />)
    expect(container.textContent).toMatch(/archive absent/)
  })
})

describe('the version is shown', () => {
  it('renders the definition version so a score can be tied to its truth', () => {
    getBenchmarkArtifact.mockReturnValue(artifact())
    const { container } = render(<GroundTruthPanel name="benchmark/definition" />)
    expect(container.textContent).toMatch(/definition version 1\.a5669dcdc9d8e9d2/)
  })
})
