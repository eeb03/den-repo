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
 *   5. the camera-framing math (`computeLocalBounds`/`fitDistance`) fits
 *      both a tight local survey and a widely-spread coarse-DEM scene --
 *      the exact case a browser audit found rendering nothing, because the
 *      old camera was a fixed `(30, 30, 30)` regardless of data extent
 *   6. "Fit to scene" and "Reset view" exist and are clickable recovery
 *      controls, and a resolved-but-empty scene (no surface, no
 *      candidates) gets an explicit empty-state message rather than a
 *      blank canvas
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ScenePayload, SceneCandidate } from '@/types/subterra'
import { clamp, computeLocalBounds, fitDistance } from './reconstructed-scene'

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

  it('shows an explicit empty state, no canvas, when neither surface nor candidates can be rendered', async () => {
    getScene.mockResolvedValue(resolvedPayload({ surface: null, candidates: [] }))
    listDatasets.mockResolvedValue([])
    const { container } = renderScene()

    await waitFor(() => screen.getByText('Nothing to render yet'))
    expect(container.textContent).toMatch(
      /no surface data and no candidates with sufficient position\/elevation information/,
    )
    // No fabricated geometry: this is a real empty state, not a canvas
    // rendering nothing.
    expect(container.querySelector('canvas')).toBeNull()
    // The recovery controls only make sense when there is something to
    // frame -- they must not appear over an empty state.
    expect(screen.queryByText('Fit to scene')).toBeNull()
    expect(screen.queryByText('Reset view')).toBeNull()
  })

  it('renders the surface and tells a non-expert plainly when it has zero candidates', async () => {
    getScene.mockResolvedValue(resolvedPayload({ candidates: [] }))
    listDatasets.mockResolvedValue([])
    const { container } = renderScene()

    await waitFor(() => expect(container.querySelector('canvas')).not.toBeNull())
    expect(container.textContent).toMatch(/No subsurface candidates to display yet/)
    expect(container.textContent).toMatch(
      /spatial scene is resolved, but no candidates with sufficient position\/elevation information/,
    )
  })

  it('offers "Fit to scene" and "Reset view" as recovery controls whenever something is rendered', async () => {
    const c = candidate()
    getScene.mockResolvedValue(resolvedPayload({ candidates: [c] }))
    listDatasets.mockResolvedValue([])
    renderScene()

    await waitFor(() => expect(screen.getByText('Fit to scene')).toBeTruthy())
    const fit = screen.getByRole('button', { name: 'Fit to scene' })
    const reset = screen.getByRole('button', { name: 'Reset view' })
    // Clicking must not throw -- this exercises the same camera-fit path
    // the initial mount already ran.
    expect(() => fireEvent.click(fit)).not.toThrow()
    expect(() => fireEvent.click(reset)).not.toThrow()
  })

  it('explains what "declared" positions mean for a non-expert, without weakening the validation line', async () => {
    getScene.mockResolvedValue(resolvedPayload())
    listDatasets.mockResolvedValue([])
    const { container } = renderScene()

    await waitFor(() =>
      expect(container.textContent).toMatch(
        /None of them is independently validated against physical ground truth/,
      ),
    )
    expect(container.textContent).toMatch(
      /does not mean an independent survey has confirmed these are the true absolute coordinates/,
    )
  })
})

describe('camera-framing math', () => {
  it('floors the bounding radius so a single point still gets a positive camera distance', () => {
    const bounds = computeLocalBounds([{ x: 5, y: 5, z: 5 }])
    expect(bounds).not.toBeNull()
    expect(bounds?.center).toEqual({ x: 5, y: 5, z: 5 })
    expect(bounds?.radius).toBeGreaterThan(0)
  })

  it('centres and sizes bounds from the real spread of the points, not a fixed constant', () => {
    // A widely-spread coarse-DEM-like tile: this is the exact shape of
    // scene that rendered nothing under the old fixed camera=(30,30,30),
    // because these points sit ~190 units from the origin while the old
    // camera was only ~52 units away, looking the wrong direction.
    const bounds = computeLocalBounds([
      { x: -107.5, y: 43.3, z: 153.6 },
      { x: 107.5, y: 33.8, z: 153.6 },
      { x: -107.5, y: -62.5, z: -153.6 },
      { x: 107.5, y: -14.7, z: -153.6 },
    ])
    expect(bounds).not.toBeNull()
    expect(bounds?.center.x).toBeCloseTo(0, 1)
    expect(bounds?.center.z).toBeCloseTo(0, 1)
    expect(bounds?.radius).toBeGreaterThan(150)
  })

  it('returns null for zero points, rather than a fabricated origin to centre on', () => {
    expect(computeLocalBounds([])).toBeNull()
  })

  it('fits a larger sphere at a proportionally larger distance, for both a tight survey and a coarse DEM', () => {
    const vFov = (50 * Math.PI) / 180
    const tightSurvey = fitDistance(5, vFov, 1.6)
    const coarseDem = fitDistance(190, vFov, 1.6)
    expect(coarseDem).toBeGreaterThan(tightSurvey)
    // Roughly proportional to radius -- the whole point of deriving the
    // camera from bounds instead of a fixed distance.
    expect(coarseDem / tightSurvey).toBeCloseTo(190 / 5, 0)
  })

  it('uses whichever field of view is tighter, so a narrow (portrait) canvas still fits the sphere', () => {
    const vFov = (50 * Math.PI) / 180
    const landscape = fitDistance(100, vFov, 2.0)
    const portrait = fitDistance(100, vFov, 0.5)
    // A narrower aspect has a narrower horizontal FOV, which needs more
    // distance to fit the same sphere.
    expect(portrait).toBeGreaterThan(landscape)
  })

  it('clamp keeps a rendering parameter inside its bounds without touching the value it clamps from', () => {
    expect(clamp(-5, 0.05, 4)).toBe(0.05)
    expect(clamp(500, 0.05, 4)).toBe(4)
    expect(clamp(1.2, 0.05, 4)).toBe(1.2)
  })
})
