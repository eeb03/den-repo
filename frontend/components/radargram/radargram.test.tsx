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

import type {
  CandidateIntelligence,
  RadargramSemantics,
  TraceGrid,
} from '@/types/subterra'

const getTraceGrid = vi.fn()
const getCandidates = vi.fn()
const reviewCandidate = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getTraceGrid: (id: string, opts: unknown) => getTraceGrid(id, opts),
      getCandidates: (id: string) => getCandidates(id),
      reviewCandidate: (d: string, c: string, s: string) => reviewCandidate(d, c, s),
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
  it('explains why rather than showing an empty frame', async () => {
    getTraceGrid.mockRejectedValue(new Error('nope'))
    getCandidates.mockResolvedValue(intelligence())
    const { container } = view()

    await waitFor(() =>
      expect(container.querySelector('[data-radargram-unavailable]')).toBeTruthy(),
    )
    expect(container.textContent).toMatch(/multi-sample trace data/i)
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
