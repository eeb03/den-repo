/**
 * Render-level guards for the scientific honesty rules.
 *
 * The adapter tests prove the backend's answers arrive intact. These prove
 * the answers survive the last step -- being turned into pixels. That step
 * is where a null quietly becomes "0%", an unmappable position acquires a
 * coordinate, or a BLOCKED gate is rendered as a footnote.
 *
 * Payloads here are the real shapes captured from a running instance.
 */
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ConfidenceValue } from './confidence-value'
import { CoordinateStatus, GroundTruthStatus } from './data-status'
import { BlockedGate, ScopeStatement } from './gate-status'
import { NotOnMap } from './not-on-map'
import { ProvenanceTag } from './provenance-tag'
import { StateBox } from './state-box'
import { UnavailableView } from './unavailable-view'
import type { Position, ViewResolution } from '@/types/subterra'

afterEach(cleanup)

describe('unknown confidence is never zero', () => {
  it('renders null as an explicit absence, with no bar', () => {
    const { container } = render(<ConfidenceValue value={null} />)
    expect(screen.getByText(/no confidence stated/i)).toBeTruthy()
    expect(container.textContent).not.toMatch(/0(\.0)?%/)
    expect(container.querySelector('[data-confidence="unstated"]')).toBeTruthy()
  })

  it('distinguishes null from a genuine zero measurement', () => {
    const { container: nullish } = render(<ConfidenceValue value={null} />)
    const nullText = nullish.textContent
    cleanup()
    const { container: zero } = render(<ConfidenceValue value={0} />)
    expect(zero.textContent).toMatch(/0\.0%/)
    expect(zero.textContent).not.toBe(nullText)
    expect(zero.querySelector('[data-confidence="stated"]')).toBeTruthy()
  })

  it('renders a real confidence at full stated precision', () => {
    const { container } = render(<ConfidenceValue value={0.8734} />)
    expect(container.textContent).toContain('87.3%')
  })
})

describe('an unplaceable position never becomes a coordinate', () => {
  const unplaceable: Position[] = [
    { kind: 'none', reason: 'the selection carries no position' },
    { kind: 'odometry', along_track_m: 3.5, path_id: 'line-1' },
    { kind: 'local_cartesian', x: 250, y: 80 },
    { kind: 'projected', easting: 655000, northing: 4544705 },
  ]

  it.each(unplaceable)('$kind is shown as not mappable, with a reason', (position) => {
    const { container } = render(<CoordinateStatus position={position} />)
    expect(container.textContent).toMatch(/not mappable/i)
    // no lat/lon pair is ever printed for a non-geographic position
    expect(container.textContent).not.toMatch(/-?\d+\.\d{4,},\s*-?\d+\.\d{4,}/)
    expect(container.textContent).not.toMatch(/\b0\.000000,\s*0\.000000\b/)
  })

  it('a geographic position does print its coordinates', () => {
    const { container } = render(
      <CoordinateStatus position={{ kind: 'geographic', lat: 45.96625, lon: 25.8718 }} />,
    )
    expect(container.textContent).toContain('45.966250')
    expect(container.querySelector('[data-position-kind="geographic"]')).toBeTruthy()
  })

  it('the unplaced list keeps items reachable and states why each is unplaced', () => {
    const { container } = render(
      <NotOnMap
        items={[
          {
            id: 'obj_1',
            itemType: 'object',
            position: { kind: 'none', reason: 'association gave no coordinate' },
          },
          { id: 'obj_2', itemType: 'object', position: { kind: 'odometry', along_track_m: 9 } },
        ]}
      />,
    )
    expect(screen.getByText('obj_1')).toBeTruthy()
    expect(screen.getByText(/association gave no coordinate/)).toBeTruthy()
    expect(screen.getByText(/along-track distance only/)).toBeTruthy()
    expect(container.querySelectorAll('[data-unplaced]')).toHaveLength(2)
  })
})

describe('an unresolved view shows the backend reason, never a drawing', () => {
  const scene3d: ViewResolution = {
    view: 'scene_3d',
    resolved: false,
    coordinates: {},
    reason:
      'a 3D scene needs an absolute elevation for the selection, and no dataset held has an established vertical relationship',
    missing: ['an established vertical relationship (absolute elevation)'],
  }

  it('renders the reason and missing list verbatim', () => {
    const { container } = render(<UnavailableView resolution={scene3d} />)
    expect(screen.getByText(new RegExp(scene3d.reason!.slice(0, 40)))).toBeTruthy()
    expect(
      screen.getByText('an established vertical relationship (absolute elevation)'),
    ).toBeTruthy()
    expect(container.querySelector('[data-resolved="false"]')).toBeTruthy()
  })

  it('does not substitute its own explanation when the backend gave none', () => {
    render(
      <UnavailableView
        resolution={{ view: 'map', resolved: false, coordinates: {}, missing: [] }}
      />,
    )
    expect(screen.getByText(/supplied no reason/i)).toBeTruthy()
  })
})

describe('the five states stay visually distinct', () => {
  it('each state renders with its own marker', () => {
    const kinds = ['empty', 'unpositioned', 'unavailable', 'unassociated', 'error'] as const
    const seen = new Set<string>()
    for (const kind of kinds) {
      const { container } = render(<StateBox kind={kind} title={`t-${kind}`} />)
      const node = container.querySelector(`[data-state-kind="${kind}"]`)
      expect(node, `${kind} did not render`).toBeTruthy()
      seen.add(node!.className)
      cleanup()
    }
    // "empty" and "unavailable" in particular must not look alike
    expect(seen.size).toBe(kinds.length)
  })
})

describe('provenance survives the mapping to the UI', () => {
  const classes = [
    'measured',
    'declared_by_source',
    'supplied_by_caller',
    'derived',
    'inferred',
    'assumed',
    'unavailable',
  ] as const

  it.each(classes)('%s renders its own label and never colour alone', (provenance) => {
    const { container } = render(<ProvenanceTag provenance={provenance} />)
    const node = container.querySelector(`[data-provenance="${provenance}"]`)
    expect(node).toBeTruthy()
    // the text label is always present, so the encoding survives greyscale
    expect(node!.textContent!.trim().length).toBeGreaterThan(0)
  })

  it('an unrecognised class is shown as itself, not absorbed into a known one', () => {
    const { container } = render(<ProvenanceTag provenance="brand_new_class" />)
    expect(container.querySelector('[data-provenance="unrecognised"]')).toBeTruthy()
    expect(container.textContent).toContain('brand_new_class')
    expect(container.querySelector('[data-provenance="unavailable"]')).toBeNull()
  })

  it('ground truth has three states, and unknown is not "no"', () => {
    const { container: unknown } = render(<GroundTruthStatus hasGroundTruth={null} />)
    expect(unknown.textContent).toMatch(/not recorded/i)
    expect(unknown.textContent).not.toMatch(/^No ground truth$/)
    cleanup()
    const { container: absent } = render(<GroundTruthStatus hasGroundTruth={false} />)
    expect(absent.textContent).toMatch(/no ground truth/i)
  })
})

describe('a blocked gate stays blocked', () => {
  it('renders BLOCKED prominently with the backend reason', () => {
    const { container } = render(
      <BlockedGate
        label="Localisation scoring"
        status="BLOCKED"
        reason="absolute origin is not verified"
      />,
    )
    const gate = container.querySelector('[data-gate-status="BLOCKED"]')
    expect(gate).toBeTruthy()
    expect(within(gate as HTMLElement).getByText('BLOCKED')).toBeTruthy()
    expect(container.textContent).toContain('absolute origin is not verified')
  })

  it('does not present a blocked gate as resolved', () => {
    const { container } = render(<BlockedGate label="Localisation" status="BLOCKED" />)
    expect(container.textContent).not.toMatch(/RESOLVED/)
  })

  it('a scope statement is rendered verbatim', () => {
    const scope =
      'BAM benchmark results measure performance on controlled concrete NDT specimens. They are not evidence of soil/utility-scale subsurface detection or localisation performance.'
    const { container } = render(<ScopeStatement scope={scope} />)
    expect(container.textContent).toContain(scope)
  })
})
