/**
 * The backend decides what can be shown; the UI renders that decision.
 *
 * The failure this guards against is subtle and tempting: hard-coding what
 * the UI "knows" to be true. `scene_3d` is unresolved for every dataset the
 * platform currently holds, so a shortcut that special-cases it would look
 * correct today and silently keep the view dark forever -- including on the
 * day a vertical registration finally makes it resolvable.
 *
 * So the strongest test here is the inverted one: feed the panel a RESOLVED
 * scene_3d and assert it renders as resolved. That can only pass if the
 * component is genuinely reading the backend's answer.
 */
import { cleanup, render, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { SelectionResolution, ViewResolution } from '@/types/subterra'

const mockUseViewResolution = vi.fn()
const mockUseComposition = vi.fn()

vi.mock('@/hooks/use-subterra', () => ({
  useViewResolution: (...a: unknown[]) => mockUseViewResolution(...a),
  useComposition: (...a: unknown[]) => mockUseComposition(...a),
}))

const { SelectionPane } = await import('./selection-pane')

afterEach(() => {
  cleanup()
  mockUseViewResolution.mockReset()
  mockUseComposition.mockReset()
})

const SELECTION = {
  kind: 'frame' as const,
  dataset_id: 'ds',
  selection_id: 'ds:line-1',
  frame_id: 'ds:line-1',
  trace_index: 5,
}

/** The real shape returned by POST /api/views/resolve. */
function resolution(views: ViewResolution[]): SelectionResolution {
  return {
    selection: SELECTION,
    views,
    resolvable_views: views.filter((v) => v.resolved).map((v) => v.view),
    unresolvable_views: views.filter((v) => !v.resolved).map((v) => v.view),
  }
}

function setViews(views: ViewResolution[]) {
  mockUseViewResolution.mockReturnValue({
    data: resolution(views),
    error: null,
    isLoading: false,
  })
  mockUseComposition.mockReturnValue({ data: undefined, error: null, isLoading: false })
}

const SCENE_3D_BLOCKED: ViewResolution = {
  view: 'scene_3d',
  resolved: false,
  coordinates: {},
  reason:
    'a 3D scene needs an absolute elevation for the selection, and no dataset held has an established vertical relationship',
  missing: ['an established vertical relationship (absolute elevation)'],
}

describe('an unresolved view is rendered with the backend reason', () => {
  it('shows the reason and the missing list verbatim', () => {
    setViews([SCENE_3D_BLOCKED])
    const { container } = render(
      <SelectionPane datasetId="ds" selection={SELECTION} />,
    )
    expect(container.textContent).toContain(
      'an established vertical relationship (absolute elevation)',
    )
    expect(container.textContent).toMatch(/needs an absolute elevation/)
    expect(container.querySelector('[data-state-kind="unavailable"]')).toBeTruthy()
  })

  it('offers no coordinates for an unresolved view', () => {
    setViews([SCENE_3D_BLOCKED])
    const { container } = render(
      <SelectionPane datasetId="ds" selection={SELECTION} />,
    )
    // nothing that could be read as a location
    expect(container.textContent).not.toMatch(/\blat\b/)
    expect(container.textContent).not.toMatch(/\{\s*\}/)
  })
})

describe('Phase 7, sixth slice: an off-gpr radargram reason is shown verbatim', () => {
  const OFF_GPR_RADARGRAM: ViewResolution = {
    view: 'radargram',
    resolved: false,
    coordinates: {},
    reason:
      "this dataset's recorded modality composition is lidar; a radargram view is a "
      + 'GPR-trace view and does not apply to it',
    missing: ['a GPR acquisition, or frames recording GPR traces'],
  }

  it('shows the composition reason, never "names no frame" or "needs a trace index"', () => {
    setViews([OFF_GPR_RADARGRAM])
    const { container } = render(
      <SelectionPane datasetId="ds" selection={SELECTION} />,
    )
    expect(container.textContent).toContain('lidar')
    expect(container.textContent).toContain('does not apply to it')
    expect(container.textContent).not.toContain('names no frame')
    expect(container.textContent).not.toContain('needs a trace index')
    expect(container.querySelector('[data-state-kind="unavailable"]')).toBeTruthy()
  })
})

describe('the UI does not hard-code what is unavailable', () => {
  it('renders scene_3d as RESOLVED when the backend says so', () => {
    /*
     * The inverted case. Today the backend never returns this. If a
     * vertical registration is ever supplied it will, and the view must
     * start working with no change here.
     */
    setViews([
      {
        view: 'scene_3d',
        resolved: true,
        coordinates: { frame_id: 'ds:line-1', x: 12, y: 4, z: -1.5 },
        missing: [],
      },
    ])
    const { container } = render(
      <SelectionPane datasetId="ds" selection={SELECTION} />,
    )
    const row = container.querySelector('[data-view="scene_3d"]')
    expect(row).toBeTruthy()
    expect(row!.getAttribute('data-resolved')).toBe('true')
    expect(within(row as HTMLElement).getByText(/resolved/i)).toBeTruthy()
    expect(container.querySelector('[data-state-kind="unavailable"]')).toBeNull()
  })

  it('renders map as UNAVAILABLE when the backend says so, despite map being ordinary', () => {
    setViews([
      {
        view: 'map',
        resolved: false,
        coordinates: {},
        reason: 'the selection carries no position',
        missing: ['a geographic position, or a GeoTie that supplies one'],
      },
    ])
    const { container } = render(
      <SelectionPane datasetId="ds" selection={SELECTION} />,
    )
    expect(container.textContent).toContain('the selection carries no position')
    expect(container.querySelector('[data-state-kind="unavailable"]')).toBeTruthy()
  })

  it('renders exactly the views the backend returned, no more and no fewer', () => {
    setViews([
      { view: 'radargram', resolved: true, coordinates: { trace_index: 5 }, missing: [] },
      SCENE_3D_BLOCKED,
    ])
    const { container } = render(
      <SelectionPane datasetId="ds" selection={SELECTION} />,
    )
    expect(container.querySelectorAll('[data-view]')).toHaveLength(1) // one resolved
    // the unresolved one renders as a state box, so two rows total
    const text = container.textContent ?? ''
    expect(text).toMatch(/Radargram/i)
    expect(text).toMatch(/3D scene/i)
    // views the backend did not mention are not invented
    expect(text).not.toMatch(/Depth slice/i)
    expect(text).not.toMatch(/Metadata/i)
  })

  it('a view with neither reason nor missing is not given one', () => {
    setViews([{ view: 'depth_slice', resolved: false, coordinates: {}, missing: [] }])
    const { container } = render(
      <SelectionPane datasetId="ds" selection={SELECTION} />,
    )
    expect(container.textContent).toMatch(/supplied no reason/i)
  })
})

describe('composition states are not collapsed', () => {
  it('not_relatable renders as unassociated, distinct from empty', () => {
    mockUseViewResolution.mockReturnValue({
      data: undefined,
      error: null,
      isLoading: false,
    })
    mockUseComposition.mockReturnValue({
      data: {
        layers: [],
        spatial_relationship: 'not_relatable',
        spatial_basis:
          '1 of 1 layer(s) cannot be placed on Earth. This needs a declared CRS or a GeoTie -- no amount of processing resolves it.',
        notes: ['layers that cannot be placed must not be drawn at a default coordinate'],
      },
      error: null,
      isLoading: false,
    })
    const { container } = render(<SelectionPane datasetId="ds" selection={null} />)
    expect(container.querySelector('[data-state-kind="unassociated"]')).toBeTruthy()
    expect(container.textContent).toMatch(/no amount of processing resolves it/)
    expect(container.textContent).toMatch(
      /must not be drawn at a default coordinate/,
    )
  })

  it('a vertical relationship without absolute elevation says so', () => {
    mockUseViewResolution.mockReturnValue({
      data: undefined,
      error: null,
      isLoading: false,
    })
    mockUseComposition.mockReturnValue({
      data: {
        layers: [],
        spatial_relationship: 'relatable',
        spatial_basis: 'both layers declare EPSG:4326',
        vertical_relationship: {
          kind: 'registration_required',
          absolute_elevation_available: false,
          missing: ['a vertical datum on at least one frame'],
        },
      },
      error: null,
      isLoading: false,
    })
    const { container } = render(<SelectionPane datasetId="ds" selection={null} />)
    expect(container.textContent).toMatch(/absolute elevation NOT available/)
    expect(container.textContent).toContain('a vertical datum on at least one frame')
  })
})
