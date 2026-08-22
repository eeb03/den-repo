/**
 * The reconstructed scene.
 *
 * jsdom has no WebGL, so `THREE.WebGLRenderer` is mocked to a no-op stub
 * carrying a real `<canvas>` (so `mount.appendChild`/`removeChild` and
 * event listeners work); everything else is real `three`, since Scene,
 * geometry, materials and math need no GPU context.
 *
 * WHAT THESE TESTS PROTECT:
 *
 *   1. an unresolved dataset never renders a 3D canvas at all -- it gets
 *      the reason, what is missing, and links to the existing diagnostic
 *      views, same as every other unresolved view in this workspace
 *   2. every resolved scene shows `validation_status` verbatim
 *   3. a candidate missing a position or an elevation is listed as "not
 *      shown", never silently dropped and never drawn at a fallback point
 *   4. selecting a candidate (via the accessible list, not the 3D canvas
 *      raycast, which jsdom cannot exercise) opens its detail panel with
 *      its provenance
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ScenePayload, SceneCandidate } from '@/types/subterra'

vi.mock('three', async () => {
  const actual = await vi.importActual<typeof import('three')>('three')
  class FakeWebGLRenderer {
    domElement = document.createElement('canvas')
    setSize() {}
    setPixelRatio() {}
    render() {}
    dispose() {}
  }
  return { ...actual, WebGLRenderer: FakeWebGLRenderer }
})

const getScene = vi.fn()
const listDatasets = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getScene: (id: string, surfaceId?: string) => getScene(id, surfaceId),
      listDatasets: () => listDatasets(),
    },
  }
})

import { ReconstructedScene } from './reconstructed-scene'

function renderScene(datasetId = 'd1') {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <ReconstructedScene datasetId={datasetId} />
    </SWRConfig>,
  )
}

function unresolvedPayload(overrides: Partial<ScenePayload> = {}): ScenePayload {
  return {
    dataset_id: 'd1',
    resolved: false,
    resolution_reason: 'no dataset held has an established vertical relationship',
    missing: ['a declared vertical datum for the acquisition elevations'],
    vertical_relationship: null,
    surface: null,
    candidates: [],
    validation_status:
      'Positions and elevations in this scene are declared or derived from declared inputs. None of them is independently validated against physical ground truth.',
    diagnostic_views: { report: '/datasets/d1/report', radargram: '/datasets/d1/radargram' },
    ...overrides,
  }
}

function candidate(overrides: Partial<SceneCandidate> = {}): SceneCandidate {
  return {
    id: 'cand-1',
    position: { available: true, lat: 52.0, lon: 6.0, basis: 'spatially_registered', reason: '' },
    elevation: {
      available: true,
      elevation_m: 12.3,
      depth_m: 0.5,
      depth_certainty: 'derived',
      provenance: 'derived: surface elevation minus depth',
      reason: '',
    },
    score: 4.2,
    score_meaning: 'peak local-anomaly z magnitude, ordinal within this dataset only',
    anomaly_class: 'compact',
    note: 'Geometric descriptor only -- NOT a physical material or object identification.',
    source_file: 'line.SGY',
    trace_range: [10, 14],
    depth_range: [0.4, 0.6],
    evidence_reference: '/datasets/d1/radargram',
    ...overrides,
  }
}

function resolvedPayload(overrides: Partial<ScenePayload> = {}): ScenePayload {
  return {
    ...unresolvedPayload(),
    resolved: true,
    resolution_reason: null,
    missing: [],
    vertical_relationship: {
      kind: 'absolute_elevation',
      subsurface_frame_id: 'd1:line',
      surface_frame_id: 'd1:dem',
      reasons: ['both vertical datums are declared and equal'],
      missing: [],
    },
    surface: {
      frame_id: 'd1:dem',
      dataset_id: 'd1',
      modality: 'dem',
      vertical_datum_code: 'NAP',
      vertical_datum_provenance: 'supplied_by_caller',
      points: [{ lat: 52.0, lon: 6.0, elevation_m: 12.0 }],
      point_count_total: 1,
      downsampled: false,
    },
    candidates: [],
    ...overrides,
  }
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('unresolved scenes never render a 3D canvas', () => {
  it('shows the reason, what is missing, and the existing diagnostic views', async () => {
    getScene.mockResolvedValue(unresolvedPayload())
    listDatasets.mockResolvedValue([])
    const { container } = renderScene()

    await waitFor(() => screen.getByText('3D scene unavailable'))
    expect(container.textContent).toMatch(
      /no dataset held has an established vertical relationship/,
    )
    expect(container.textContent).toMatch(
      /a declared vertical datum for the acquisition elevations/,
    )
    const reportLink = screen.getByText('report').closest('a')
    expect(reportLink?.getAttribute('href')).toBe('/datasets/d1/report')

    // No canvas anywhere -- an unresolved dataset must not get an empty or
    // misleading 3D scene.
    expect(container.querySelector('canvas')).toBeNull()
  })
})

describe('resolved scenes', () => {
  it('always shows validation_status verbatim', async () => {
    getScene.mockResolvedValue(resolvedPayload())
    listDatasets.mockResolvedValue([])
    const { container } = renderScene()

    await waitFor(() =>
      expect(container.textContent).toMatch(
        /None of them is independently validated against physical ground truth/,
      ),
    )
  })

  it('renders the 3D canvas via the mocked renderer', async () => {
    getScene.mockResolvedValue(resolvedPayload())
    listDatasets.mockResolvedValue([])
    const { container } = renderScene()

    await waitFor(() => expect(container.querySelector('canvas')).not.toBeNull())
  })

  it('lists a candidate missing a position as "not shown", never fabricating one', async () => {
    const unplaced = candidate({
      id: 'cand-unpositioned',
      position: {
        available: false,
        lat: null,
        lon: null,
        basis: 'unknown',
        reason: "this candidate's supporting traces carry no geographic position",
      },
    })
    getScene.mockResolvedValue(resolvedPayload({ candidates: [unplaced] }))
    listDatasets.mockResolvedValue([])
    const { container } = renderScene()

    await waitFor(() => screen.getByText(/Not shown in this scene/))
    expect(container.textContent).toMatch(/carry no geographic position/)
    // It must not also appear in the placeable/candidates-in-scene list.
    expect(screen.queryByText(/Candidates in this scene/)).toBeNull()
  })

  it('lists a candidate missing elevation as "not shown", with the DEM-alignment reason', async () => {
    const noElevation = candidate({
      id: 'cand-no-elevation',
      elevation: {
        available: false,
        elevation_m: null,
        depth_m: 0.5,
        depth_certainty: 'derived',
        provenance: 'unavailable',
        reason:
          'this candidate’s records were never aligned with a DEM surface, so no surface elevation exists at its location',
      },
    })
    getScene.mockResolvedValue(resolvedPayload({ candidates: [noElevation] }))
    listDatasets.mockResolvedValue([])
    const { container } = renderScene()

    await waitFor(() => screen.getByText(/Not shown in this scene/))
    expect(container.textContent).toMatch(/never aligned with a DEM surface/)
  })

  it('selecting a placeable candidate opens its detail panel with provenance', async () => {
    const c = candidate()
    getScene.mockResolvedValue(resolvedPayload({ candidates: [c] }))
    listDatasets.mockResolvedValue([])
    const { container } = renderScene()

    await waitFor(() => screen.getByText(/Candidates in this scene/))
    fireEvent.click(screen.getByRole('button', { name: /compact/i }))

    await screen.findByText('Anomaly candidate')
    expect(container.textContent).toMatch(/derived: surface elevation minus depth/)
    expect(container.textContent).toMatch(/12\.30 m/)

    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByText('Anomaly candidate')).toBeNull()
  })

  it('never renders the word "validated" as a claim about this candidate’s own position', async () => {
    const c = candidate()
    getScene.mockResolvedValue(resolvedPayload({ candidates: [c] }))
    listDatasets.mockResolvedValue([])
    renderScene()

    await waitFor(() => screen.getByText(/Candidates in this scene/))
    fireEvent.click(screen.getByRole('button', { name: /compact/i }))
    await screen.findByText('Anomaly candidate')

    // The only place "validated" may appear is the standing disclaimer that
    // nothing here IS validated -- never a per-candidate claim otherwise.
    const matches = screen.getAllByText(/validated/i)
    for (const el of matches) {
      expect(el.textContent).toMatch(/not independently validated|is independently validated/)
    }
  })
})
