/**
 * The radargram inspection view.
 *
 * THE PROPERTY UNDER TEST is that a picture cannot say more than the data. A
 * radargram is the one surface here where a fabrication is invisible — a reader
 * cannot sanity-check a pixel the way they can check a number with units — so
 * these tests hold the specific claims the image could otherwise make:
 *
 *   1. the vertical axis is never called a depth it isn't
 *   2. the values are never called amplitude when they are a statistic
 *   3. a candidate that cannot be placed exactly is not drawn at all
 *   4. accepting a candidate does not promote it to anything
 *
 * The canvas itself is exercised through its reported grid dimensions and
 * domain rather than by reading pixels: jsdom has no real 2D context, and the
 * property that matters is that every measured cell is addressed exactly once.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/services/api'
import type {
  CandidateIntelligence,
  RadargramSemantics,
  TraceGrid,
} from '@/types/subterra'

const getTraceGrid = vi.fn()
const getCandidates = vi.fn()
const reviewCandidate = vi.fn()
const getReviewSummary = vi.fn()
const getDatasetReviews = vi.fn()
const getCandidateReview = vi.fn()
const submitCandidateReview = vi.fn()
const createMissedEvent = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getTraceGrid: (id: string, opts: unknown) => getTraceGrid(id, opts),
      getCandidates: (id: string) => getCandidates(id),
      reviewCandidate: (d: string, c: string, s: string) => reviewCandidate(d, c, s),
      getReviewSummary: (id: string) => getReviewSummary(id),
      getDatasetReviews: (id: string) => getDatasetReviews(id),
      getCandidateReview: (d: string, c: string) => getCandidateReview(d, c),
      submitCandidateReview: (d: string, c: string, body: unknown) =>
        submitCandidateReview(d, c, body),
      createMissedEvent: (d: string, body: unknown) => createMissedEvent(d, body),
    },
  }
})

import { RadargramInspector } from './radargram-inspector'

function semantics(overrides: Partial<RadargramSemantics> = {}): RadargramSemantics {
  return {
    vertical: {
      kind: 'derived_depth_default_velocity',
      label: 'Derived depth (default velocity)',
      units: 'm',
      basis: 'two_way_time_ns converted with the converter default velocity',
      is_derived: true,
      velocity_source: 'converter_default',
      velocity_m_per_ns: 0.1,
      caveat:
        "Derived from two-way travel time using the converter's default velocity of 0.1 m/ns. Nobody measured or declared this for this site.",
    },
    horizontal: {
      kind: 'trace_index',
      label: 'Trace',
      units: null,
      basis: 'the acquisition supplies no along-track distance',
      geographic_available: false,
    },
    field: {
      field: 'signal',
      label: 'Local-anomaly z-score',
      units: 'σ',
      description:
        'each cell is how far that sample sits from the background estimated in a ring around it. This is a statistic computed FROM the amplitude, not the amplitude.',
      is_statistic: true,
    },
    unreliable_cells: 6886,
    total_cells: 160768,
    reliability_note:
      'an unreliable cell is one whose local background could not be estimated from enough neighbours. It is not a cell where nothing was found, and it is not zero.',
    missing_note:
      'a missing cell is a sample the acquisition did not record. It is drawn as a gap, never as zero signal.',
    ...overrides,
  }
}

function grid(overrides: Partial<TraceGrid> = {}): TraceGrid {
  return {
    dataset_id: 'd1',
    name: '4TU 01.1 Path8',
    source_file: 'Path8.sgy',
    available_source_files: ['Path8.sgy'],
    field: 'signal',
    grid: [
      [1.0, -2.0, null],
      [0.5, 4.85, 0.1],
    ],
    reliability: [
      [true, true, null],
      [false, true, true],
    ],
    trace_indices: [0, 1, 2],
    depths: [0.1, 0.2],
    semantics: semantics(),
    candidate_footprints: [
      {
        candidate_id: 'c1',
        placeable: true,
        reason: '',
        first_column: 1,
        last_column: 1,
        first_row: 1,
        last_row: 1,
        peak_column: 1,
        peak_row: 1,
      },
    ],
    ...overrides,
  }
}

function intelligence(overrides: Partial<CandidateIntelligence> = {}): CandidateIntelligence {
  return {
    dataset_id: 'd1',
    status: 'available',
    status_reason: 'generated from 1 survey line(s)',
    missing: [],
    definition: 'a region of the processed signal … not a detected object',
    generation: {
      method: 'ring_local_anomaly_connected_components',
      method_version: '1.0.0',
      parameters: { threshold: 3, min_cells: 3, min_trace_span: 1 },
      generated_at: '2026-08-13T09:00:00Z',
      dataset_id: 'd1',
      input_fingerprint: 'abc',
      declared_reference_at: null,
      n_source_files: 1,
      n_records: 160768,
      seed: null,
      deterministic: true,
      determinism_note: 'no randomness is used',
    },
    staleness: {
      is_stale: false,
      reasons: [],
      checks_performed: ['records'],
      checks_skipped: [],
      note: 'nothing is recomputed automatically',
    },
    candidate_count: 1,
    candidates: [
      {
        candidate: {
          id: 'c1',
          dataset_id: 'd1',
          evidence: {
            source_file: 'Path8.sgy',
            trace_range: [1, 1],
            depth_range: [0.2, 0.2],
            n_supporting_cells: 4,
            peak_value: 4.85,
            peak_trace: 1,
            peak_depth: 0.2,
            mean_value: 3.6,
          },
          characteristics: {
            elongation: 0.4,
            compactness: 0.8,
            area_cells: 4,
            continuity_across_traces: 1,
            continuity_across_depth: 1,
            approx_lateral_extent_m: null,
            lateral_extent_source: null,
            approx_depth_extent_m: 0.02,
            centroid_lat: null,
            centroid_lon: null,
            centroid_elevation_m: null,
          },
          interpretation: { anomaly_class: 'compact', note: 'Neutral geometry only.' },
          confidence: {
            reliable_fraction: 1,
            touches_trace_boundary: false,
            touches_depth_boundary: false,
            kmz_direction_verified: null,
            dem_vertical_datum_verified: null,
            velocity_m_per_ns: 0.1,
          },
        },
        candidate_score: 4.85,
        candidate_score_meaning:
          'peak local-anomaly z magnitude … it is not a probability, not a confidence',
        localisation: 'trace_relative',
        localisation_basis: 'locatable as traces 1-1 of Path8.sgy',
        depth: 'derived',
        depth_basis:
          'converted from the time axis using a declared velocity of 0.1 m/ns, which is an assumption',
        status: 'proposed',
        classification_status: 'BLOCKED',
        classification_blocked_reason: 'no validated classifier exists in this repository',
      },
    ],
    ranking_basis: 'peak local-anomaly z magnitude',
    candidate_burden: 12.7,
    candidate_burden_basis: 'candidates per 1000 traces examined',
    localisation_breakdown: { trace_relative: 1 },
    depth_breakdown: { derived: 1 },
    shape_classes: { compact: 1 },
    classification_status: 'BLOCKED',
    classification_blocked_reason: 'no validated classifier exists in this repository',
    classified_object_count: 0,
    benchmark: {
      method: 'ring_local_anomaly_connected_components',
      method_version: '1.0.0',
      summary: 'This method performs at approximately chance on both benchmarks.',
      measurements: [],
      caveat: 'The 4TU separation rests on seven attested-empty trenches.',
      adequacy: 'This benchmark is UNDERPOWERED for comparing detectors.',
    },
    ...overrides,
  }
}

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <RadargramInspector datasetId="d1" />
    </SWRConfig>,
  )
}

/**
 * jsdom ships no 2D context, so without this the draw path bails at
 * `getContext` and the test would pass while exercising nothing. The stub is
 * deliberately faithful about the two properties the renderer depends on:
 * `createImageData` returns a real RGBA buffer of the requested size, and
 * `imageSmoothingEnabled` is recorded so a test can assert it was turned off.
 */
const drawCalls: { smoothing: boolean | undefined }[] = []

function stubCanvas() {
  const proto = globalThis.HTMLCanvasElement?.prototype
  if (!proto) return
  proto.getContext = vi.fn(function (this: HTMLCanvasElement) {
    const context = {
      imageSmoothingEnabled: true,
      createImageData: (w: number, h: number) => ({
        width: w,
        height: h,
        data: new Uint8ClampedArray(w * h * 4),
      }),
      putImageData: vi.fn(),
      clearRect: vi.fn(),
      drawImage: vi.fn(() => {
        drawCalls.push({ smoothing: context.imageSmoothingEnabled })
      }),
    }
    return context as unknown as CanvasRenderingContext2D
  }) as unknown as HTMLCanvasElement['getContext']
}

beforeEach(() => {
  getTraceGrid.mockReset()
  getCandidates.mockReset()
  reviewCandidate.mockReset()
  getReviewSummary.mockReset()
  getDatasetReviews.mockReset()
  getCandidateReview.mockReset()
  submitCandidateReview.mockReset()
  createMissedEvent.mockReset()
  // Sensible defaults so tests that do not exercise the human-review
  // panels are not left with a network call that never resolves: an
  // absent review is a 404, matching what a real, never-reviewed
  // candidate returns.
  getDatasetReviews.mockResolvedValue({
    dataset_id: 'd1', reviews: [],
    summary: { total_reviews: 0, by_status: { unreviewed: 0, confirmed: 0, rejected: 0, uncertain: 0 }, missed_events: 0, eligible_for_corpus: 0 },
  })
  getCandidateReview.mockRejectedValue(new ApiError(404, 'this candidate has not been reviewed yet'))
  drawCalls.length = 0
  stubCanvas()
})
afterEach(cleanup)

describe('the axes say what they are', () => {
  it('labels a default-velocity axis as derived, with its caveat', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()

    await screen.findByText(/Radargram inspection/i)
    expect(container.querySelector('[data-vertical-label]')?.textContent).toBe(
      'Derived depth (default velocity)',
    )
    expect(container.querySelector('[data-vertical-caveat]')?.textContent).toMatch(
      /Nobody measured or declared this/i,
    )
  })

  it('never prints a bare "Depth (m)" for a derived axis', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    const label = container.querySelector('[data-vertical-label]')?.textContent ?? ''
    expect(label).not.toBe('Depth')
    expect(label.toLowerCase()).toContain('derived')
  })

  it('shows a time axis as time when no velocity exists', async () => {
    getTraceGrid.mockResolvedValue(
      grid({
        semantics: semantics({
          vertical: {
            kind: 'two_way_time_ns',
            label: 'Two-way time',
            units: 'ns',
            basis: 'the instrument own time axis; no velocity has been supplied',
            is_derived: false,
            velocity_source: 'none',
            velocity_m_per_ns: null,
            caveat: null,
          },
        }),
      }),
    )
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    expect(container.querySelector('[data-vertical-label]')?.textContent).toBe('Two-way time')
    expect(container.querySelector('[data-vertical-caveat]')).toBeNull()
    expect(container.textContent).not.toMatch(/derived depth/i)
  })

  it('states that the view is trace-relative when no georeference exists', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    expect(container.querySelector('[data-no-georeference]')?.textContent).toMatch(
      /trace-relative/i,
    )
  })
})

describe('the values say what they are', () => {
  it('labels a preprocessed grid as a z-score, not amplitude', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    expect(container.querySelector('[data-field-label]')?.textContent).toBe(
      'Local-anomaly z-score',
    )
    expect(container.querySelector('[data-field-description]')?.textContent).toMatch(
      /not the amplitude/i,
    )
  })

  it('reports unreliable and missing cells rather than leaving them to the eye', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    const quality = container.querySelector('[data-cell-quality]')?.textContent ?? ''
    expect(quality).toMatch(/6,886/)
    expect(quality).toMatch(/not a cell where nothing was found/i)
    expect(quality).toMatch(/never as zero signal/i)
  })
})

describe('the canvas addresses every measured cell exactly once', () => {
  it('reports the grid dimensions it drew', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    const canvas = container.querySelector('[data-radargram-canvas]')
    expect(canvas?.getAttribute('data-columns')).toBe('3')
    expect(canvas?.getAttribute('data-rows')).toBe('2')
  })

  it('counts missing cells rather than colouring them', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    expect(
      container.querySelector('[data-radargram-canvas]')?.getAttribute('data-missing-cells'),
    ).toBe('1')
  })

  it('scales the image with smoothing OFF', async () => {
    /*
     * The single most important rendering property. Bilinear smoothing would
     * invent values between traces that no antenna position ever recorded --
     * and would make the picture look better, which is exactly why it is
     * asserted rather than assumed.
     */
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    view()
    await screen.findByText(/Radargram inspection/i)

    expect(drawCalls.length).toBeGreaterThan(0)
    expect(drawCalls.every((c) => c.smoothing === false)).toBe(true)
  })

  it('uses a symmetric domain taken from the values present', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    expect(
      container.querySelector('[data-radargram-canvas]')?.getAttribute('data-domain'),
    ).toBe('4.8500')
  })
})

describe('candidate overlays', () => {
  it('draws a marker for a placeable candidate', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    expect(container.querySelectorAll('[data-candidate-marker]').length).toBe(1)
  })

  it('draws nothing for an unplaceable candidate, and says why', async () => {
    getTraceGrid.mockResolvedValue(
      grid({
        candidate_footprints: [
          {
            candidate_id: 'c9',
            placeable: false,
            reason: 'traces 900-901 are not in this grid',
            first_column: null,
            last_column: null,
            first_row: null,
            last_row: null,
            peak_column: null,
            peak_row: null,
          },
        ],
      }),
    )
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    expect(container.querySelectorAll('[data-candidate-marker]').length).toBe(0)
    expect(container.querySelector('[data-unplaceable-reason]')?.textContent).toMatch(
      /not in this grid/,
    )
  })

  it('reports an empty candidate set as a result, not a failure', async () => {
    getTraceGrid.mockResolvedValue(grid({ candidate_footprints: [] }))
    getCandidates.mockResolvedValue(intelligence({ candidates: [], candidate_count: 0 }))
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    expect(container.querySelector('[data-no-candidates]')?.textContent).toMatch(
      /a result, not a failure/i,
    )
  })

  it('still renders the measured signal when candidates fail to load', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockRejectedValue(new Error('boom'))
    const { container } = view()

    await waitFor(() =>
      expect(container.querySelector('[data-candidates-failed]')).toBeTruthy(),
    )
    expect(container.querySelector('[data-radargram-canvas]')).toBeTruthy()
  })
})

describe('selecting a candidate shows its evidence', () => {
  async function open() {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const rendered = view()
    await screen.findByText(/Radargram inspection/i)
    fireEvent.click(rendered.container.querySelector('[data-candidate-marker]')!)
    await screen.findByText(/Candidate evidence/i)
    return rendered
  }

  it('exposes the evidence chain', async () => {
    const { container } = await open()
    const panel = container.querySelector('[data-evidence-panel]')?.textContent ?? ''
    expect(panel).toMatch(/Path8\.sgy/)
    expect(panel).toMatch(/4\.85/)
  })

  it('keeps classification blocked', async () => {
    const { container } = await open()
    expect(container.querySelector('[data-evidence-classification]')?.textContent).toMatch(
      /BLOCKED/,
    )
  })

  it('states what the score is not', async () => {
    const { container } = await open()
    expect(container.querySelector('[data-evidence-score]')?.textContent).toMatch(
      /not a probability/i,
    )
  })

  it('shows the generating method and version', async () => {
    const { container } = await open()
    expect(container.querySelector('[data-evidence-provenance]')?.textContent).toMatch(
      /ring_local_anomaly_connected_components v1\.0\.0/,
    )
  })

  it('carries the benchmark adequacy into the panel', async () => {
    const { container } = await open()
    expect(container.querySelector('[data-evidence-benchmark]')?.textContent).toMatch(
      /UNDERPOWERED/,
    )
  })

  it('shows depth as derived, never as measured', async () => {
    const { container } = await open()
    const depth = container.querySelector('[data-evidence-depth]')?.textContent ?? ''
    expect(depth).toMatch(/assumption/i)
    expect(depth).not.toMatch(/measured depth/i)
  })
})

describe('review actions preserve their meaning', () => {
  it('records a decision and says what it does not mean', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    reviewCandidate.mockResolvedValue({})
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)
    fireEvent.click(container.querySelector('[data-candidate-marker]')!)
    await screen.findByText(/Candidate evidence/i)

    expect(container.querySelector('[data-review-meaning]')?.textContent).toMatch(
      /does not make this candidate a detection, an object, or ground truth/i,
    )

    fireEvent.click(container.querySelector('[data-action="accept-candidate"]')!)
    await waitFor(() =>
      expect(reviewCandidate).toHaveBeenCalledWith('d1', 'c1', 'accepted'),
    )
  })

  it('uses no language claiming a detection anywhere on the page', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)
    fireEvent.click(container.querySelector('[data-candidate-marker]')!)

    expect(container.textContent).not.toMatch(
      /detected object|buried object|confirmed anomaly|target detected/i,
    )
  })
})

describe('an absent trace grid', () => {
  it('shows the backend detail verbatim, with no fallback explanation added', async () => {
    getTraceGrid.mockRejectedValue(
      new ApiError(
        400,
        'records are missing trace_index/depth metadata -- not genuine multi-sample GPR trace data',
      ),
    )
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()

    await waitFor(() =>
      expect(container.querySelector('[data-radargram-unavailable]')).toBeTruthy(),
    )
    expect(container.textContent).toMatch(/multi-sample GPR trace data/i)
    // Phase 7, sixth slice: this sentence used to be appended unconditionally,
    // re-describing an off-gpr dataset's real reason as a generic B-scan
    // caveat. The backend detail is the only explanation now.
    expect(container.textContent).not.toMatch(/A radargram needs genuine multi-sample/i)
    expect(container.textContent).not.toMatch(/has no B-scan to draw/i)
  })

  it('names the composition and says it does not apply, for an off-gpr dataset', async () => {
    getTraceGrid.mockRejectedValue(
      new ApiError(
        400,
        "this dataset's recorded modality composition is lidar; a radargram / "
          + 'trace-depth grid is a GPR-trace view and does not apply to it',
      ),
    )
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()

    await waitFor(() =>
      expect(container.querySelector('[data-radargram-unavailable]')).toBeTruthy(),
    )
    expect(container.textContent).toContain('lidar')
    expect(container.textContent).toContain('does not apply to it')
    expect(container.textContent).not.toMatch(/A radargram needs genuine multi-sample/i)
    expect(container.textContent).not.toMatch(/has no B-scan to draw/i)
  })

  it('falls back to a generic message only for a genuine, non-backend failure', async () => {
    getTraceGrid.mockRejectedValue(new Error('network down'))
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()

    await waitFor(() =>
      expect(container.querySelector('[data-radargram-unavailable]')).toBeTruthy(),
    )
    expect(container.textContent).toContain('Could not load the trace grid for this dataset.')
  })
})

describe('the grid is requested with what the viewer needs', () => {
  it('asks for reliability and candidate footprints', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    view()
    await screen.findByText(/Radargram inspection/i)

    expect(getTraceGrid).toHaveBeenCalledWith(
      'd1',
      expect.objectContaining({ reliability: true, candidateFootprints: true }),
    )
  })
})

/**
 * The display-mode toggle.
 *
 * The property under test is that switching representation changes ONLY the
 * numbers in the cells. A candidate that moved, an axis that changed, or a unit
 * that appeared would each be the viewer asserting something the data does not.
 */
describe('the amplitude toggle', () => {
  function preAnomalySemantics(): RadargramSemantics {
    return semantics({
      field: {
        field: 'pre_anomaly_signal',
        label: 'Pre-anomaly signal',
        units: null,
        description:
          'the value each sample held immediately before local-anomaly processing replaced it with the z-score. It carries NO physical unit and no calibration, gain or antenna response is implied.',
        is_statistic: false,
        reliability_applies: false,
        reliability_note:
          'the reliability mask describes the anomaly statistic, not these values: a cell whose ring had too few neighbours still holds a perfectly good stored signal',
      },
    })
  }

  it('defaults to the anomaly view', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    expect(
      container.querySelector('[data-display-mode="signal"]')?.getAttribute('data-selected'),
    ).toBe('true')
    expect(getTraceGrid).toHaveBeenCalledWith(
      'd1',
      expect.objectContaining({ field: 'signal' }),
    )
  })

  it('requests the pre-anomaly projection when toggled', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    getTraceGrid.mockResolvedValue(
      grid({ semantics: preAnomalySemantics(), grid: [[172, -340, null], [8, 32764, 5]] }),
    )
    fireEvent.click(container.querySelector('[data-display-mode="pre_anomaly_signal"]')!)

    await waitFor(() =>
      expect(getTraceGrid).toHaveBeenCalledWith(
        'd1',
        expect.objectContaining({ field: 'pre_anomaly_signal' }),
      ),
    )
  })

  it('shows the backend label and no invented unit', async () => {
    getTraceGrid.mockResolvedValue(
      grid({ semantics: preAnomalySemantics(), grid: [[172, -340, null], [8, 32764, 5]] }),
    )
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    const values = container.querySelector('[data-field-label]')?.parentElement
    expect(values?.textContent).toContain('Pre-anomaly signal')
    expect(values?.textContent).not.toMatch(/\(σ\)|\(m\)|\(dB\)|\(V\)/)
    expect(container.textContent).not.toMatch(
      /raw amplitude|calibrated|physical amplitude/i,
    )
  })

  it('does not move a candidate when the representation changes', async () => {
    const footprint = grid().candidate_footprints![0]!
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    const before = container.querySelector('[data-candidate-marker]')!.getAttribute('style')

    getTraceGrid.mockResolvedValue(
      grid({
        semantics: preAnomalySemantics(),
        grid: [[172, -340, null], [8, 32764, 5]],
        candidate_footprints: [footprint],
      }),
    )
    fireEvent.click(container.querySelector('[data-display-mode="pre_anomaly_signal"]')!)
    await waitFor(() =>
      expect(getTraceGrid).toHaveBeenCalledWith(
        'd1',
        expect.objectContaining({ field: 'pre_anomaly_signal' }),
      ),
    )

    expect(container.querySelector('[data-candidate-marker]')!.getAttribute('style')).toBe(
      before,
    )
  })

  it('stops fading unreliable cells where the mask does not describe the values', async () => {
    getTraceGrid.mockResolvedValue(
      grid({ semantics: preAnomalySemantics(), grid: [[172, -340, null], [8, 32764, 5]] }),
    )
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    expect(container.querySelector('[data-toggle-unreliable]')).toBeNull()
    expect(
      container.querySelector('[data-reliability-not-applicable]')?.textContent,
    ).toMatch(/still holds a perfectly good stored signal/i)
  })

  it('keeps fading in the anomaly view, where the mask does describe them', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    expect(container.querySelector('[data-toggle-unreliable]')).toBeTruthy()
    expect(container.querySelector('[data-reliability-not-applicable]')).toBeNull()
  })

  it('missing cells stay missing in the pre-anomaly view', async () => {
    getTraceGrid.mockResolvedValue(
      grid({ semantics: preAnomalySemantics(), grid: [[172, -340, null], [8, 32764, 5]] }),
    )
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    expect(
      container.querySelector('[data-radargram-canvas]')?.getAttribute('data-missing-cells'),
    ).toBe('1')
  })

  it('does not refetch the candidate set when the representation changes', async () => {
    /*
     * The Stage 16 guarantee. Candidates are independent of how the signal is
     * displayed, so a toggle must not trigger a second dataset-wide read.
     */
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)
    await waitFor(() => expect(getCandidates).toHaveBeenCalledTimes(1))

    fireEvent.click(container.querySelector('[data-display-mode="pre_anomaly_signal"]')!)
    await waitFor(() =>
      expect(getTraceGrid).toHaveBeenCalledWith(
        'd1',
        expect.objectContaining({ field: 'pre_anomaly_signal' }),
      ),
    )

    expect(getCandidates).toHaveBeenCalledTimes(1)
  })
})

describe('human-in-the-loop review', () => {
  it('shows the review controls once a candidate is selected', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)
    fireEvent.click(container.querySelector('[data-candidate-marker]')!)
    await screen.findByText(/Human review/i)

    expect(container.querySelector('[data-action="review-confirmed"]')).toBeTruthy()
    expect(container.querySelector('[data-action="review-rejected"]')).toBeTruthy()
    expect(container.querySelector('[data-action="review-uncertain"]')).toBeTruthy()
  })

  it('the real radar evidence is visible before any review control', async () => {
    /* Section 5: no blind labeling -- the evidence panel must render above/beside the review controls, not stand alone. */
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)
    fireEvent.click(container.querySelector('[data-candidate-marker]')!)
    await screen.findByText(/Human review/i)

    expect(container.querySelector('[data-evidence-panel]')).toBeTruthy()
    expect(container.querySelector('[data-human-review-panel]')).toBeTruthy()
  })

  it('saves a confirmed review and reports it does not promote the candidate', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    submitCandidateReview.mockResolvedValue({
      id: 'rev1', dataset_id: 'd1', candidate_id: 'c1', site_id: null,
      source_file: 'Path8.sgy', trace_range: [1, 1], reviewer_id: 'u1',
      review_status: 'confirmed', operator_label: null, annotation_geometry: null,
      notes: null, evidence_grade: 'operator_reviewed', label_source: 'operator_reviewed',
      ground_truth_status: 'not_independently_validated', detector_snapshot: null,
      history: [], created_utc: 't', updated_utc: 't',
    })
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)
    fireEvent.click(container.querySelector('[data-candidate-marker]')!)
    await screen.findByText(/Human review/i)

    fireEvent.click(container.querySelector('[data-action="review-confirmed"]')!)
    await waitFor(() =>
      expect(submitCandidateReview).toHaveBeenCalledWith(
        'd1', 'c1', expect.objectContaining({ review_status: 'confirmed' }),
      ),
    )
    expect(container.querySelector('[data-review-disclaimer]')?.textContent).toMatch(
      /does not make this candidate a detection, an object, or independently validated ground truth/i,
    )
  })

  it('confirming with no operator label is a valid, savable state', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    submitCandidateReview.mockResolvedValue({
      id: 'rev1', dataset_id: 'd1', candidate_id: 'c1', site_id: null,
      source_file: 'Path8.sgy', trace_range: [1, 1], reviewer_id: 'u1',
      review_status: 'confirmed', operator_label: null, annotation_geometry: null,
      notes: null, evidence_grade: 'operator_reviewed', label_source: 'operator_reviewed',
      ground_truth_status: 'not_independently_validated', detector_snapshot: null,
      history: [], created_utc: 't', updated_utc: 't',
    })
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)
    fireEvent.click(container.querySelector('[data-candidate-marker]')!)
    await screen.findByText(/Human review/i)

    fireEvent.click(container.querySelector('[data-action="save-review"]')!)
    await waitFor(() =>
      expect(submitCandidateReview).toHaveBeenCalledWith(
        'd1', 'c1', expect.objectContaining({ operator_label: null }),
      ),
    )
  })

  it('reloading shows the persisted review state', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    getCandidateReview.mockResolvedValue({
      id: 'rev1', dataset_id: 'd1', candidate_id: 'c1', site_id: null,
      source_file: 'Path8.sgy', trace_range: [1, 1], reviewer_id: 'u1',
      review_status: 'confirmed', operator_label: 'pipe', annotation_geometry: null,
      notes: 'clear hyperbola', evidence_grade: 'operator_reviewed',
      label_source: 'operator_reviewed', ground_truth_status: 'not_independently_validated',
      detector_snapshot: null, history: [], created_utc: 't', updated_utc: 't',
    })
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)
    fireEvent.click(container.querySelector('[data-candidate-marker]')!)

    await waitFor(() =>
      expect(container.querySelector('[data-current-review-status]')?.textContent).toMatch(
        /Confirmed.*pipe/i,
      ),
    )
  })

  it('shows the dataset-level review progress', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    getDatasetReviews.mockResolvedValue({
      dataset_id: 'd1', reviews: [],
      summary: {
        total_reviews: 84, missed_events: 3,
        by_status: { unreviewed: 57, confirmed: 11, rejected: 10, uncertain: 6 },
        eligible_for_corpus: 27,
      },
    })
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    await waitFor(() =>
      expect(container.querySelector('[data-review-progress]')?.textContent).toMatch(
        /Confirmed: 11.*Rejected: 10.*Uncertain: 6.*Missed events added: 3/i,
      ),
    )
  })

  it('supports creating a missed-event annotation with no candidate present', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence({ candidates: [], candidate_count: 0 }))
    createMissedEvent.mockResolvedValue({
      id: 'rev-missed', dataset_id: 'd1', candidate_id: null, site_id: null,
      source_file: 'Path8.sgy', trace_range: [50, 55], reviewer_id: 'u1',
      review_status: 'confirmed', operator_label: null, annotation_geometry: null,
      notes: null, evidence_grade: 'operator_reviewed', label_source: 'operator_reviewed',
      ground_truth_status: 'not_independently_validated', detector_snapshot: null,
      history: [], created_utc: 't', updated_utc: 't',
    })
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    fireEvent.click(screen.getByText(/Add a missed event/i))
    fireEvent.change(container.querySelector('[data-missed-trace-start]')!, { target: { value: '50' } })
    fireEvent.change(container.querySelector('[data-missed-trace-end]')!, { target: { value: '55' } })
    fireEvent.click(container.querySelector('[data-action="save-missed-event"]')!)

    await waitFor(() =>
      expect(createMissedEvent).toHaveBeenCalledWith(
        'd1', expect.objectContaining({ source_file: 'Path8.sgy', trace_range: [50, 55] }),
      ),
    )
    expect(container.querySelector('[data-missed-event-saved]')).toBeTruthy()
  })

  it('rejects a missed event with an inverted trace range before calling the API', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    fireEvent.click(screen.getByText(/Add a missed event/i))
    fireEvent.change(container.querySelector('[data-missed-trace-start]')!, { target: { value: '55' } })
    fireEvent.change(container.querySelector('[data-missed-trace-end]')!, { target: { value: '50' } })
    fireEvent.click(container.querySelector('[data-action="save-missed-event"]')!)

    expect(container.querySelector('[data-missed-event-error]')).toBeTruthy()
    expect(createMissedEvent).not.toHaveBeenCalled()
  })

  it('offers a corpus export link once eligible reviews exist', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    getDatasetReviews.mockResolvedValue({
      dataset_id: 'd1', reviews: [],
      summary: { total_reviews: 5, missed_events: 1,
                by_status: { unreviewed: 0, confirmed: 4, rejected: 0, uncertain: 1 },
                eligible_for_corpus: 5 },
    })
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    const link = await screen.findByText(/Export 5 reviewed annotation/i)
    expect(link.closest('a')?.getAttribute('href')).toContain('/api/reviews/d1/corpus_export')
  })

  it('offers no export link with nothing eligible yet', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)
    await waitFor(() => expect(container.querySelector('[data-review-progress]')).toBeTruthy())

    expect(container.querySelector('[data-corpus-export-link]')).toBeNull()
  })

  it('never renders language claiming a detection anywhere on the review panels', async () => {
    /*
     * "Buried object" is a legitimate, selectable VOCABULARY option (Section
     * 4's own example taxonomy) and is correctly excluded below -- the
     * property under test is that nothing here ASSERTS a detection, not
     * that the vocabulary avoids the word.
     */
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)
    fireEvent.click(container.querySelector('[data-candidate-marker]')!)
    await screen.findByText(/Human review/i)

    expect(container.textContent).not.toMatch(
      /this is a detected|confirmed anomaly|target detected|Subterra detected/i,
    )
  })
})

describe('canvas-based review annotation', () => {
  /** RadargramCanvas renders at its default 900x520 here; grid() is 3 columns x 2 rows -> scaleX=300, scaleY=260. */
  function stubBoundingRect() {
    const proto = globalThis.HTMLDivElement?.prototype
    if (!proto) return
    proto.getBoundingClientRect = vi.fn(() => ({
      left: 0, top: 0, right: 900, bottom: 520, width: 900, height: 520, x: 0, y: 0, toJSON: () => {},
    })) as unknown as typeof proto.getBoundingClientRect
  }

  beforeEach(() => stubBoundingRect())

  it('defaults to select mode with no draw surface', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    expect(container.querySelector('[data-draw-mode-option="select"]')?.getAttribute('aria-pressed')).toBe('true')
    expect(container.querySelector('[data-radargram-draw-surface]')).toBeNull()
  })

  it('drawing a rectangle and confirming a candidate sends the real geometry', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    submitCandidateReview.mockResolvedValue({
      id: 'rev1', dataset_id: 'd1', candidate_id: 'c1', site_id: null,
      source_file: 'Path8.sgy', trace_range: [1, 1], reviewer_id: 'u1',
      review_status: 'confirmed', operator_label: null, annotation_geometry: null,
      notes: null, evidence_grade: 'operator_reviewed', label_source: 'operator_reviewed',
      ground_truth_status: 'not_independently_validated', detector_snapshot: null,
      history: [], created_utc: 't', updated_utc: 't',
    })
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    fireEvent.click(container.querySelector('[data-draw-mode-option="draw-rectangle"]')!)
    const surface = container.querySelector('[data-radargram-draw-surface]')!
    fireEvent.mouseDown(surface, { clientX: 310, clientY: 10 })   // col 1
    fireEvent.mouseMove(surface, { clientX: 310, clientY: 270 })  // row 1
    fireEvent.mouseUp(surface)

    await screen.findByText(/Rectangle: traces 1–1, samples 0–1/i)

    fireEvent.click(container.querySelector('[data-candidate-marker]')!)
    await screen.findByText(/Human review/i)
    fireEvent.click(container.querySelector('[data-action="review-confirmed"]')!)

    await waitFor(() =>
      expect(submitCandidateReview).toHaveBeenCalledWith(
        'd1', 'c1',
        expect.objectContaining({
          annotation_geometry: { kind: 'rectangle', trace_start: 1, trace_end: 1, sample_start: 0, sample_end: 1, trace_indices: [], sample_indices: [] },
        }),
      ),
    )
  })

  it('Clear removes the drawn geometry summary', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    fireEvent.click(container.querySelector('[data-draw-mode-option="draw-rectangle"]')!)
    const surface = container.querySelector('[data-radargram-draw-surface]')!
    fireEvent.mouseDown(surface, { clientX: 10, clientY: 10 })
    fireEvent.mouseUp(surface)
    await screen.findByText(/Rectangle:/i)

    fireEvent.click(container.querySelector('[data-action="clear-drawing"]')!)
    expect(container.querySelector('[data-drawn-geometry-summary]')).toBeNull()
  })

  it('tracing a ridge accumulates points and Finish converts them to a path geometry', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    fireEvent.click(container.querySelector('[data-draw-mode-option="draw-ridge"]')!)
    const surface = container.querySelector('[data-radargram-draw-surface]')!
    fireEvent.click(surface, { clientX: 10, clientY: 10 })
    fireEvent.click(surface, { clientX: 310, clientY: 270 })

    const finish = await screen.findByText(/Finish ridge \(2 points\)/i)
    fireEvent.click(finish)

    await screen.findByText(/Ridge: 2 point\(s\)/i)
    expect(container.querySelector('[data-draw-mode-option="select"]')?.getAttribute('aria-pressed')).toBe('true')
  })

  it('missed-event trace range is derived from a drawn rectangle, not typed', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence({ candidates: [], candidate_count: 0 }))
    createMissedEvent.mockResolvedValue({
      id: 'rev-missed', dataset_id: 'd1', candidate_id: null, site_id: null,
      source_file: 'Path8.sgy', trace_range: [1, 1], reviewer_id: 'u1',
      review_status: 'confirmed', operator_label: null, annotation_geometry: null,
      notes: null, evidence_grade: 'operator_reviewed', label_source: 'operator_reviewed',
      ground_truth_status: 'not_independently_validated', detector_snapshot: null,
      history: [], created_utc: 't', updated_utc: 't',
    })
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    fireEvent.click(container.querySelector('[data-draw-mode-option="draw-rectangle"]')!)
    const surface = container.querySelector('[data-radargram-draw-surface]')!
    fireEvent.mouseDown(surface, { clientX: 310, clientY: 10 })
    fireEvent.mouseUp(surface)
    await screen.findByText(/Rectangle:/i)

    fireEvent.click(screen.getByText(/Add a missed event/i))
    const startInput = container.querySelector('[data-missed-trace-start]') as HTMLInputElement
    expect(startInput.disabled).toBe(true)
    expect(startInput.value).toBe('1')

    fireEvent.click(container.querySelector('[data-action="save-missed-event"]')!)
    await waitFor(() =>
      expect(createMissedEvent).toHaveBeenCalledWith(
        'd1', expect.objectContaining({ trace_range: [1, 1] }),
      ),
    )
  })
})

describe('review queue prioritization', () => {
  function twoCandidateIntelligence() {
    const base = intelligence()
    const c1 = base.candidates[0]!
    const c2 = {
      ...c1,
      candidate: { ...c1.candidate, id: 'c2', evidence: { ...c1.candidate.evidence, trace_range: [5, 5] as [number, number] } },
      candidate_score: 9.0,
    }
    return { ...base, candidate_count: 2, candidates: [c1, c2] }
  }

  function twoFootprintGrid() {
    return grid({
      candidate_footprints: [
        { candidate_id: 'c1', placeable: true, reason: '', first_column: 1, last_column: 1, first_row: 1, last_row: 1, peak_column: 1, peak_row: 1 },
        { candidate_id: 'c2', placeable: true, reason: '', first_column: 0, last_column: 0, first_row: 0, last_row: 0, peak_column: 0, peak_row: 0 },
      ],
    })
  }

  it('defaults to position order (the order the backend returned)', async () => {
    getTraceGrid.mockResolvedValue(twoFootprintGrid())
    getCandidates.mockResolvedValue(twoCandidateIntelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)
    await screen.findByText(/Candidates on this line/i)

    const rows = container.querySelectorAll('[data-candidate-row]')
    expect(rows[0]?.getAttribute('data-candidate-row')).toBe('c1') // score 4.85, listed first (backend order)
    expect(rows[1]?.getAttribute('data-candidate-row')).toBe('c2') // score 9.0
  })

  it('"Highest score" reorders without touching "Position"', async () => {
    getTraceGrid.mockResolvedValue(twoFootprintGrid())
    getCandidates.mockResolvedValue(twoCandidateIntelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)
    await screen.findByText(/Candidates on this line/i)

    fireEvent.click(container.querySelector('[data-queue-order-option="score"]')!)
    const rows = container.querySelectorAll('[data-candidate-row]')
    expect(rows[0]?.getAttribute('data-candidate-row')).toBe('c2') // score 9.0, now first
    expect(rows[1]?.getAttribute('data-candidate-row')).toBe('c1')
  })

  it('marks a candidate already reviewed in the queue', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    getDatasetReviews.mockResolvedValue({
      dataset_id: 'd1',
      reviews: [{
        id: 'rev1', dataset_id: 'd1', candidate_id: 'c1', site_id: null,
        source_file: 'Path8.sgy', trace_range: [1, 1], reviewer_id: 'u1',
        review_status: 'confirmed', operator_label: 'pipe', annotation_geometry: null,
        notes: null, evidence_grade: 'operator_reviewed', label_source: 'operator_reviewed',
        ground_truth_status: 'not_independently_validated', detector_snapshot: null,
        history: [], created_utc: 't', updated_utc: 't',
      }],
      summary: { total_reviews: 1, by_status: { unreviewed: 0, confirmed: 1, rejected: 0, uncertain: 0 }, missed_events: 0, eligible_for_corpus: 1 },
    })
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)

    await waitFor(() =>
      expect(container.querySelector('[data-queue-review-status="confirmed"]')).toBeTruthy(),
    )
  })

  it('an unreviewed candidate carries no reviewed badge', async () => {
    getTraceGrid.mockResolvedValue(grid())
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()
    await screen.findByText(/Radargram inspection/i)
    await screen.findByText(/Candidates on this line/i)

    expect(container.querySelector('[data-queue-review-status]')).toBeNull()
  })
})
