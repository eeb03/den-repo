/**
 * The Candidate Intelligence screen.
 *
 * THE PROPERTY UNDER TEST IS THAT A LIST CANNOT READ AS A FINDING. The detector
 * behind this screen is at approximately chance on both benchmarks. Rendering
 * its output as "12 candidates" and nothing else would be a page that says we
 * found twelve things, which is false. So these tests hold four lines:
 *
 *   1. the measured performance is on the page, and above the candidates
 *   2. no score is rendered as a percentage, a confidence or a probability
 *   3. depth is never printed as a number when no velocity was declared
 *   4. no word on the page claims an object was detected
 *
 * Each corresponds to a specific false claim the screen would otherwise make.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/services/api'
import type { CandidateIntelligence, InspectableCandidate } from '@/types/subterra'

const getCandidates = vi.fn()
const generateCandidates = vi.fn()
const getExportFormats = vi.fn()
const exportDatasetObjects = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getCandidates: (id: string) => getCandidates(id),
      generateCandidates: (id: string) => generateCandidates(id),
      getExportFormats: () => getExportFormats(),
      exportDatasetObjects: (id: string, format: string) => exportDatasetObjects(id, format),
    },
  }
})

import { CandidateIntelligenceView } from './candidate-intelligence'

function candidate(overrides: Partial<InspectableCandidate> = {}): InspectableCandidate {
  return {
    candidate: {
      id: 'c1',
      dataset_id: 'd1',
      evidence: {
        source_file: 'Line1.sgy',
        trace_range: [120, 124],
        depth_range: [0.4, 0.9],
        n_supporting_cells: 14,
        peak_value: 7.42,
        peak_trace: 122,
        peak_depth: 0.6,
        mean_value: 4.1,
      },
      characteristics: {
        elongation: 0.4,
        compactness: 0.8,
        area_cells: 14,
        continuity_across_traces: 0.8,
        continuity_across_depth: 0.6,
        approx_lateral_extent_m: null,
        lateral_extent_source: null,
        approx_depth_extent_m: 0.5,
        centroid_lat: null,
        centroid_lon: null,
        centroid_elevation_m: null,
      },
      interpretation: {
        anomaly_class: 'compact',
        note: 'Neutral geometric description only.',
      },
      confidence: {
        reliable_fraction: 0.9,
        touches_trace_boundary: false,
        touches_depth_boundary: false,
        kmz_direction_verified: null,
        dem_vertical_datum_verified: null,
        velocity_m_per_ns: null,
      },
    },
    candidate_score: 7.42,
    candidate_score_meaning:
      'peak local-anomaly z magnitude for the region. It orders candidates WITHIN one dataset under one parameter set and nothing more: it is not a probability, not a confidence, not calibrated against any ground truth, and not comparable between datasets.',
    localisation: 'trace_relative',
    localisation_basis: 'locatable as traces 120-124 of Line1.sgy',
    depth: 'unavailable',
    depth_basis:
      'no propagation velocity has been declared for this dataset, so the candidate position on the instrument axis is not a physical depth',
    status: 'proposed',
    classification_status: 'BLOCKED',
    classification_blocked_reason:
      'no validated classifier exists in this repository, and no benchmark here supports mapping a candidate to an object identity',
    ...overrides,
  }
}

function intelligence(
  overrides: Partial<CandidateIntelligence> = {},
): CandidateIntelligence {
  return {
    dataset_id: 'd1',
    status: 'available',
    status_reason: 'generated from 1 survey line(s)',
    missing: [],
    definition:
      'a region of the processed signal whose measured characteristics satisfy a candidate-generation rule. It is not a detected object, not a validated detection, and not evidence that anything is buried at this location.',
    generation: {
      method: 'ring_local_anomaly_connected_components',
      method_version: '1.0.0',
      parameters: { threshold: 3.0, min_cells: 3, min_trace_span: 1 },
      generated_at: '2026-08-13T09:00:00Z',
      dataset_id: 'd1',
      input_fingerprint: 'abc123',
      declared_reference_at: null,
      n_source_files: 1,
      n_records: 24000,
      seed: null,
      deterministic: true,
      determinism_note: 'no randomness is used',
    },
    staleness: {
      is_stale: false,
      reasons: [],
      checks_performed: ['method version', 'records'],
      checks_skipped: [],
      note: 'nothing is recomputed automatically',
    },
    candidate_count: 1,
    candidates: [candidate()],
    ranking_basis: 'peak local-anomaly z magnitude; it is not a probability',
    candidate_burden: 12.5,
    candidate_burden_basis: 'candidates per 1000 traces examined',
    localisation_breakdown: { trace_relative: 1 },
    depth_breakdown: { unavailable: 1 },
    shape_classes: { compact: 1 },
    classification_status: 'BLOCKED',
    classification_blocked_reason:
      'no validated classifier exists in this repository, and no benchmark here supports mapping a candidate to an object identity',
    classified_object_count: 0,
    benchmark: {
      method: 'ring_local_anomaly_connected_components',
      method_version: '1.0.0',
      summary:
        'This method performs at approximately chance on both benchmarks it has been scored against.',
      measurements: [
        {
          benchmark: 'bam-concrete-gpr',
          arm: '1.5 GHz',
          precision: 0.1351,
          recall: 0.0652,
          f1: 0.088,
          chance_precision: 0.1297,
          times_chance: 1.04,
          source: 'artifacts/bam/score_1_5_GHz_Rot00.json',
        },
        {
          benchmark: '4tu-nl-utility',
          arm: 'activity-level separation',
          auc: 0.4452,
          ci95: [0.2219, 0.6607],
          contains_chance: true,
          n_negative: 7,
          source: 'artifacts/4tu/leakage.json',
        },
      ],
      caveat: 'The 4TU separation rests on seven attested-empty trenches.',
    },
    ...overrides,
  }
}

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <CandidateIntelligenceView datasetId="d1" />
    </SWRConfig>,
  )
}

beforeEach(() => {
  getCandidates.mockReset()
  generateCandidates.mockReset()
  getExportFormats.mockReset()
  exportDatasetObjects.mockReset()
  getExportFormats.mockResolvedValue({
    formats: [
      { value: 'json', requires: 'identifiers only', carries_full_provenance: true },
      { value: 'csv', requires: 'identifiers only', carries_full_provenance: true },
      {
        value: 'geojson',
        requires: 'a geographic position per feature',
        carries_full_provenance: false,
        note: 'unplaceable features are skipped with their reason',
      },
    ],
    rule: 'nothing is silently dropped: every export reports what it skipped',
  })
  // jsdom does not implement the Blob-download primitives; stubbed here
  // rather than asserting a real download happened, which no DOM test can do.
  vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:mock'), revokeObjectURL: vi.fn() })
  // jsdom also tries to actually navigate a clicked <a href="blob:...">,
  // which it does not implement and logs as an error -- stubbed so the
  // component's real download trigger doesn't need a fake mechanism of
  // its own just to be testable.
  HTMLAnchorElement.prototype.click = vi.fn()
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('the measured performance is unavoidable', () => {
  it('renders the benchmark numbers on the page', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()

    await screen.findByText(/approximately chance/i)
    const context = container.querySelector('[data-benchmark-context]')
    expect(context).toBeTruthy()
    expect(context?.textContent).toMatch(/0\.1351/)
    expect(context?.textContent).toMatch(/1\.04×/)
  })

  it('places the benchmark context before the candidate list', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/approximately chance/i)

    const context = container.querySelector('[data-benchmark-context]')!
    const firstCandidate = container.querySelector('[data-candidate]')!
    // Node.DOCUMENT_POSITION_FOLLOWING === 4
    expect(context.compareDocumentPosition(firstCandidate) & 4).toBeTruthy()
  })

  it('reports the 4TU interval as spanning chance', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/approximately chance/i)

    expect(container.querySelector('[data-benchmark-context]')?.textContent).toMatch(
      /spans chance/i,
    )
  })
})

describe('a score is never dressed up as a probability', () => {
  it('renders the score as a bare magnitude with no percentage', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText('7.42')

    // Scoped to the candidate list: the benchmark block legitimately prints a
    // "95% interval", which is a confidence interval on a measured metric and
    // not a claim about any candidate.
    const list = container.querySelector('[data-candidate]')!
    expect(list.textContent).not.toMatch(/\d+(\.\d+)?\s*%/)
    expect(list.textContent).toMatch(/7\.42/)
  })

  it('states what the score means when a candidate is inspected', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()

    fireEvent.click(await screen.findByRole('button', { name: /Line1\.sgy/ }))
    const detail = container.querySelector('[data-candidate-detail]')
    expect(detail?.textContent).toMatch(/not a probability/i)
    expect(detail?.textContent).toMatch(/not comparable between datasets/i)
  })

  it('offers no ranking control that implies likelihood', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText('7.42')

    // The word "probability" DOES appear — inside "it is not a probability".
    // The guard is therefore against ASSERTIONS of likelihood, not the word.
    expect(container.textContent).not.toMatch(
      /most likely|sort by (probability|confidence|likelihood)|(\d)\s*% (likely|confident|probable)/i,
    )
    expect(container.textContent).toMatch(/not a probability/i)
  })
})

describe('depth is not invented', () => {
  it('says unavailable and prints no depth number when no velocity was declared', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()

    fireEvent.click(await screen.findByRole('button', { name: /Line1\.sgy/ }))
    const detail = container.querySelector('[data-candidate-detail]')!
    expect(detail.querySelector('[data-depth-basis]')?.textContent).toMatch(
      /not a physical depth/i,
    )
    expect(detail.querySelector('[data-depth-interval]')).toBeNull()
  })

  it('labels a velocity-derived depth as derived, never measured', async () => {
    const derived = candidate({
      depth: 'derived',
      depth_basis:
        'converted from the time axis using a declared velocity of 0.1 m/ns, which is an assumption about this ground and not a measurement',
    })
    getCandidates.mockResolvedValue(
      intelligence({ candidates: [derived], depth_breakdown: { derived: 1 } }),
    )
    const { container } = view()

    fireEvent.click(await screen.findByRole('button', { name: /Line1\.sgy/ }))
    const detail = container.querySelector('[data-candidate-detail]')!
    expect(detail.querySelector('[data-depth-interval]')?.textContent).toMatch(
      /derived — not measured/i,
    )
    expect(detail.textContent).not.toMatch(/measured depth/i)
  })
})

describe('position is not invented', () => {
  it('reports a trace-relative candidate as such, with no coordinates', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()

    fireEvent.click(await screen.findByRole('button', { name: /Line1\.sgy/ }))
    const detail = container.querySelector('[data-candidate-detail]')!
    expect(detail.querySelector('[data-localisation-basis]')?.textContent).toMatch(
      /traces 120-124/,
    )
    // No latitude/longitude pair anywhere.
    expect(detail.textContent).not.toMatch(/-?\d{1,3}\.\d{4,},\s*-?\d{1,3}\.\d{4,}/)
  })
})

describe('candidate is not detection', () => {
  it('shows object classification as BLOCKED', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText('7.42')

    expect(container.querySelector('[data-classification-status]')?.textContent).toBe(
      'BLOCKED',
    )
  })

  it('uses no language claiming something was found', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText('7.42')

    fireEvent.click(screen.getByRole('button', { name: /Line1\.sgy/ }))
    expect(container.textContent).not.toMatch(
      /object found|target detected|buried pipe|confirmed anomaly|object detected/i,
    )
  })

  it('states the definition of a candidate on the page', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText('7.42')

    expect(container.querySelector('[data-candidate-definition]')?.textContent).toMatch(
      /not a detected object/i,
    )
  })
})

describe('blocked and stale states', () => {
  it('names what a blocked dataset needs', async () => {
    getCandidates.mockResolvedValue(
      intelligence({
        status: 'blocked',
        status_reason: 'trace-local anomaly preprocessing has not been run',
        missing: ["reprocessing with preprocessing_mode='gpr_local_anomaly'"],
        candidates: [],
        candidate_count: 0,
        generation: null,
      }),
    )
    const { container } = view()

    await screen.findByText(/preprocessing has not been run/i)
    expect(container.querySelectorAll('[data-candidates-missing]').length).toBe(1)
  })

  it('says why a stale set no longer applies', async () => {
    getCandidates.mockResolvedValue(
      intelligence({
        status: 'limited',
        staleness: {
          is_stale: true,
          reasons: ['the dataset records have changed since generation'],
          checks_performed: ['records'],
          checks_skipped: [],
          note: 'nothing is recomputed automatically',
        },
      }),
    )
    const { container } = view()

    await screen.findByText(/no longer matches the dataset/i)
    expect(container.querySelector('[data-stale-reason]')?.textContent).toMatch(
      /records have changed/i,
    )
  })

  it('reports an empty result as a result, not a failure', async () => {
    getCandidates.mockResolvedValue(
      intelligence({ candidates: [], candidate_count: 0 }),
    )
    const { container } = view()

    await screen.findByText(/produced no candidates/i)
    expect(container.querySelector('[data-no-candidates]')?.textContent).toMatch(
      /a result, not a failure/i,
    )
  })
})

describe('Phase 7, tenth slice: no GPR action is invited when analysis does not apply', () => {
  it('off-gpr blocked: no generate button, no radargram link, reason and missing shown verbatim', async () => {
    getCandidates.mockResolvedValue(
      intelligence({
        status: 'blocked',
        status_reason:
          "this dataset's recorded modality composition is lidar; candidate analysis is a "
          + 'GPR-trace capability and does not apply to it',
        missing: ['a GPR acquisition, or frames recording GPR traces'],
        candidates: [],
        candidate_count: 0,
        generation: null,
      }),
    )
    const { container } = view()

    await screen.findByText(/does not apply to it/i)
    expect(container.textContent).toContain('lidar')
    expect(container.querySelectorAll('[data-candidates-missing]').length).toBe(1)
    expect(screen.queryByRole('button', { name: /generate candidates/i })).toBeNull()
    expect(container.querySelector('[data-radargram-link]')).toBeNull()
    // Phase 7, eleventh slice: the GPR method's own vocabulary and score
    // must not frame a reason that says the method does not apply.
    expect(container.querySelector('[data-candidate-definition]')).toBeNull()
    expect(container.querySelector('[data-benchmark-context]')).toBeNull()
    expect(container.textContent).not.toContain('Measured performance of this method')
  })

  it('"has not been run" blocked: generate button, radargram link, definition and benchmark all stay', async () => {
    getCandidates.mockResolvedValue(
      intelligence({
        status: 'blocked',
        status_reason: 'candidate generation has not been run for this dataset',
        missing: ['a candidate generation run'],
        candidates: [],
        candidate_count: 0,
        generation: null,
      }),
    )
    const { container } = view()

    await screen.findByText(/has not been run/i)
    expect(screen.queryByRole('button', { name: /generate candidates/i })).toBeTruthy()
    expect(container.querySelector('[data-radargram-link]')).toBeTruthy()
    expect(container.querySelector('[data-candidate-definition]')).toBeTruthy()
    expect(container.querySelector('[data-benchmark-context]')).toBeTruthy()
  })

  it('available gpr set: radargram link, regenerate, definition and benchmark all stay', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()

    await screen.findByText('7.42')
    expect(screen.queryByRole('button', { name: /regenerate candidates/i })).toBeTruthy()
    expect(container.querySelector('[data-radargram-link]')).toBeTruthy()
    expect(container.querySelector('[data-candidate-definition]')).toBeTruthy()
    expect(container.querySelector('[data-benchmark-context]')).toBeTruthy()
  })
})

describe('generation is an explicit action', () => {
  it('runs generation on request and shows the new set', async () => {
    getCandidates.mockResolvedValue(
      intelligence({ status: 'blocked', missing: ['a candidate generation run'],
        candidates: [], candidate_count: 0, generation: null }),
    )
    generateCandidates.mockResolvedValue(intelligence())
    view()

    fireEvent.click(await screen.findByRole('button', { name: /generate candidates/i }))
    await waitFor(() => expect(generateCandidates).toHaveBeenCalledWith('d1'))
    await screen.findByText('7.42')
  })

  it('reports a generation failure without inventing a result', async () => {
    getCandidates.mockResolvedValue(
      intelligence({ status: 'blocked', missing: ['a candidate generation run'],
        candidates: [], candidate_count: 0, generation: null }),
    )
    generateCandidates.mockRejectedValue(new Error('boom'))
    const { container } = view()

    fireEvent.click(await screen.findByRole('button', { name: /generate candidates/i }))
    await waitFor(() =>
      expect(container.querySelector('[data-candidate-error]')).toBeTruthy(),
    )
    expect(container.querySelector('[data-candidate]')).toBeNull()
  })
})

describe('the benchmark says whether it could recognise an improvement', () => {
  const withAdequacy = () =>
    intelligence({
      benchmark: {
        ...intelligence().benchmark,
        definition_version: '1.a5669dcdc9d8e9d2',
        adequacy:
          'This benchmark is UNDERPOWERED for comparing detectors. After removing duplicated and contaminated units it holds 107 independent positives and 6 independent negatives, which could only distinguish a detector of AUC 0.74 or better from chance.',
        evaluated: ['detection: does candidate density separate occupied from empty ground'],
        not_evaluated: [
          'localisation: the publisher withholds trench coordinates',
          'depth: no unit publishes a usable depth',
          'classification: no validated classifier and no class-level truth exist',
        ],
      },
    })

  it('states that an unchanged score is not evidence of failure', async () => {
    getCandidates.mockResolvedValue(withAdequacy())
    const { container } = view()
    await screen.findByText('7.42')

    expect(container.querySelector('[data-benchmark-adequacy]')?.textContent).toMatch(
      /UNDERPOWERED/,
    )
  })

  it('names what is not evaluated, so an absence does not read as a pass', async () => {
    getCandidates.mockResolvedValue(withAdequacy())
    const { container } = view()
    await screen.findByText('7.42')

    const notEvaluated = Array.from(
      container.querySelectorAll('[data-benchmark-not-evaluated]'),
    ).map((n) => n.textContent ?? '')
    expect(notEvaluated.length).toBe(3)
    expect(notEvaluated.join(' ')).toMatch(/localisation/i)
    expect(notEvaluated.join(' ')).toMatch(/classification/i)
  })

  it('ties the numbers to a versioned ground-truth definition', async () => {
    getCandidates.mockResolvedValue(withAdequacy())
    const { container } = view()
    await screen.findByText('7.42')
    expect(container.textContent).toMatch(/ground-truth definition 1\.a5669dcdc9d8e9d2/)
  })

  it('renders without them when the backend sends none', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText('7.42')
    expect(container.querySelector('[data-benchmark-adequacy]')).toBeNull()
  })
})

describe('provenance is shown', () => {
  it('names the method, its version and its parameters', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText('7.42')

    expect(container.textContent).toMatch(/ring_local_anomaly_connected_components v1\.0\.0/)
    expect(container.textContent).toMatch(/\|z\| > 3, min 3 cells, min 1 trace/)
  })

  it('reports the run as reproducible when no randomness is used', async () => {
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText('7.42')
    expect(container.textContent).toMatch(/no randomness is used/i)
  })
})

describe('export', () => {
  it('shows no export panel when there are no classified objects', async () => {
    getCandidates.mockResolvedValue(intelligence({ classified_object_count: 0 }))
    const { container } = view()
    await screen.findByText('7.42')
    expect(container.querySelector('[data-export-panel]')).toBeNull()
  })

  it('shows the export panel and object count when classified objects exist', async () => {
    getCandidates.mockResolvedValue(intelligence({ classified_object_count: 3 }))
    const { container } = view()
    await screen.findByText('7.42')
    const panel = container.querySelector('[data-export-panel]')
    expect(panel).not.toBeNull()
    expect(panel?.textContent).toMatch(/3 classified objects available/)
  })

  it('offers the formats the backend reports, not a hardcoded list', async () => {
    getCandidates.mockResolvedValue(intelligence({ classified_object_count: 1 }))
    view()
    await screen.findByText('7.42')
    const select = await screen.findByDisplayValue('json')
    const options = Array.from(select.querySelectorAll('option')).map((o) => o.value)
    expect(options).toEqual(['json', 'csv', 'geojson'])
  })

  it('exports the selected format and reports what was written and skipped', async () => {
    exportDatasetObjects.mockResolvedValue({
      format: 'geojson',
      payload: { type: 'FeatureCollection', features: [] },
      report: {
        written: 2,
        skipped: [{ id: 'o1', reason: 'no geographic position' }],
        transformed: 2,
      },
    })
    getCandidates.mockResolvedValue(intelligence({ classified_object_count: 3 }))
    const { container } = view()
    await screen.findByText('7.42')

    const select = await screen.findByDisplayValue('json')
    fireEvent.change(select, { target: { value: 'geojson' } })
    fireEvent.click(screen.getByRole('button', { name: 'Export' }))

    await waitFor(() => expect(exportDatasetObjects).toHaveBeenCalledWith('d1', 'geojson'))
    const report = await screen.findByText(/Wrote 2, skipped 1/)
    expect(report).toBeTruthy()
    expect(container.querySelector('[data-export-report]')?.textContent).toMatch(
      /see the file for why each was skipped/,
    )
  })

  it('downloads a csv export without asserting a report it cannot see', async () => {
    exportDatasetObjects.mockResolvedValue('id,status\no1,proposed\n')
    getCandidates.mockResolvedValue(intelligence({ classified_object_count: 1 }))
    const { container } = view()
    await screen.findByText('7.42')

    fireEvent.change(await screen.findByDisplayValue('json'), { target: { value: 'csv' } })
    fireEvent.click(screen.getByRole('button', { name: 'Export' }))
    await waitFor(() => expect(exportDatasetObjects).toHaveBeenCalledWith('d1', 'csv'))
    // no crash, and no report node rendered -- the backend puts csv's counts in
    // response headers, which the export panel deliberately does not fabricate
    expect(container.querySelector('[data-export-report]')).toBeNull()
  })

  it('shows the backend refusal verbatim when export is refused', async () => {
    exportDatasetObjects.mockRejectedValue(
      new ApiError(409, 'this format needs an absolute elevation per feature; none is established'),
    )
    getCandidates.mockResolvedValue(intelligence({ classified_object_count: 1 }))
    view()
    await screen.findByText('7.42')

    fireEvent.click(screen.getByRole('button', { name: 'Export' }))
    await screen.findByText(
      'this format needs an absolute elevation per feature; none is established',
    )
  })
})
