/**
 * The spatial reference workflow.
 *
 * This screen is the one place a guess could enter the platform: it takes
 * numbers from a person and records them as the dataset's relationship to the
 * physical world. So the tests are about what the form must refuse and what the
 * screen must not imply — no prefilled scientific values, no submission without
 * an author, no rendering of a derived depth as a measured one, and no drawing
 * of an unresolved dimension as a fault.
 */
import { render, fireEvent, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import type { DimensionState, SpatialReference } from '@/types/subterra'

const getSpatialReference = vi.fn()
const declareSpatialReference = vi.fn()
vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getSpatialReference: (id: string) => getSpatialReference(id),
      declareSpatialReference: (...a: unknown[]) => declareSpatialReference(...a),
    },
  }
})

import { SpatialReferenceView } from './spatial-reference'
import { DeclarationForm } from './declaration-form'

function dimension(overrides: Partial<DimensionState> = {}): DimensionState {
  return {
    dimension: 'vertical_reference',
    state: 'missing',
    reason: 'no frame declares a vertical datum',
    missing: ['a declared vertical datum for the acquisition elevations'],
    action: 'vertical_datum',
    provenance: 'unavailable',
    detail: {},
    ...overrides,
  }
}

function reference(overrides: Partial<SpatialReference> = {}): SpatialReference {
  return {
    contract_version: '1.0',
    dataset_id: 'd1',
    dimensions: [
      dimension({
        dimension: 'horizontal_position',
        state: 'available',
        reason: 'every one of 4 record(s) carries a geographic position',
        missing: [],
        action: null,
        provenance: 'measured',
      }),
      dimension({
        dimension: 'crs',
        state: 'declared',
        reason: 'EPSG:4326, stated by the source itself',
        missing: [],
        action: null,
        provenance: 'declared_by_source',
        detail: { validated: false },
      }),
      dimension(),
      dimension({
        dimension: 'depth_conversion',
        state: 'unavailable',
        reason:
          '1 frame(s) carry a MEASURED time axis and no depth: radar time zero is when the instrument fired, not the ground surface',
        missing: ['a propagation velocity'],
        action: 'depth_conversion',
      }),
      dimension({
        dimension: 'surface_reference',
        state: 'unavailable',
        reason: 'no surface elevation model is linked to this survey',
        missing: ['a DEM or LiDAR surface covering the survey'],
        action: 'surface_reference',
      }),
      dimension({
        dimension: 'orientation',
        state: 'missing',
        reason:
          'no frame declares an orientation, and none is inferred: a track bearing says where the acquisition went, not how the sensor was oriented',
        missing: ['an IMU record, or a declared antenna orientation'],
        action: null,
      }),
      dimension({
        dimension: 'survey_geometry',
        state: 'available',
        reason: '1 frame(s), each reporting its own position count',
        missing: [],
        action: null,
      }),
    ],
    declarations: [],
    has_stale_products: false,
    stale_products: [],
    ...overrides,
  }
}

async function renderView(data: SpatialReference = reference()) {
  getSpatialReference.mockResolvedValue(data)
  const result = render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <SpatialReferenceView datasetId="d1" />
    </SWRConfig>,
  )
  await new Promise((resolve) => setTimeout(resolve, 0))
  return result
}

beforeEach(() => {
  getSpatialReference.mockReset()
  declareSpatialReference.mockReset()
})

describe('the seven dimensions', () => {
  it('renders every dimension the backend reported', async () => {
    const { container } = await renderView()
    expect(container.querySelectorAll('[data-dimension]').length).toBe(7)
  })

  it('keeps the backend reason verbatim', async () => {
    const { container } = await renderView()
    expect(container.textContent).toContain(
      'radar time zero is when the instrument fired, not the ground surface',
    )
    expect(container.textContent).toContain(
      'a track bearing says where the acquisition went, not how the sensor was oriented',
    )
  })

  it('marks resolved and unresolved distinctly in the markup', async () => {
    const { container } = await renderView()
    expect(
      container.querySelector('[data-dimension="horizontal_position"]')?.getAttribute('data-resolved'),
    ).toBe('true')
    expect(
      container.querySelector('[data-dimension="vertical_reference"]')?.getAttribute('data-resolved'),
    ).toBe('false')
  })

  it('shows what each unresolved dimension requires', async () => {
    const { container } = await renderView()
    const vertical = container.querySelector('[data-dimension="vertical_reference"]')
    expect(vertical?.querySelectorAll('[data-missing]').length).toBeGreaterThan(0)
  })

  it('offers an action only where a declaration can resolve it', async () => {
    const { container } = await renderView()
    // Orientation is unresolved but no declaration fixes it — it needs an IMU.
    expect(container.querySelector('[data-action="resolve-orientation"]')).toBeNull()
    expect(container.querySelector('[data-action="resolve-vertical_reference"]')).toBeTruthy()
  })
})

describe('declaring', () => {
  function renderForm(kind: Parameters<typeof DeclarationForm>[0]['kind']) {
    return render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <DeclarationForm datasetId="d1" kind={kind} />
      </SWRConfig>,
    )
  }

  it('prefills no scientific value anywhere', () => {
    // A default velocity or antenna height would be a fabricated measurement
    // wearing a placeholder's clothes.
    for (const kind of ['depth_conversion', 'antenna_offset', 'crs', 'vertical_datum'] as const) {
      const { container } = renderForm(kind)
      for (const input of container.querySelectorAll('input, textarea')) {
        expect((input as HTMLInputElement).value).toBe('')
      }
    }
  })

  it('cannot be submitted without an attribution', () => {
    const { container } = renderForm('vertical_datum')
    const submit = container.querySelector('[data-action="submit-declaration"]') as HTMLButtonElement
    fireEvent.change(container.querySelector('#vertical_datum-code')!, {
      target: { value: 'NAP' },
    })
    expect(submit.disabled).toBe(true)

    fireEvent.change(container.querySelector('#vertical_datum-supplied-by')!, {
      target: { value: 'the site surveyor' },
    })
    expect(submit.disabled).toBe(false)
  })

  it('sends the attribution with the declaration', async () => {
    declareSpatialReference.mockResolvedValue({
      declaration: {},
      applied: { frames_changed: [] },
      spatial_reference: reference(),
    })
    const { container } = renderForm('vertical_datum')
    fireEvent.change(container.querySelector('#vertical_datum-code')!, {
      target: { value: 'NAP' },
    })
    fireEvent.change(container.querySelector('#vertical_datum-supplied-by')!, {
      target: { value: 'PDOK documentation' },
    })
    fireEvent.submit(container.querySelector('form')!)

    await waitFor(() =>
      expect(declareSpatialReference).toHaveBeenCalledWith(
        'd1',
        'vertical_datum',
        { code: 'NAP' },
        'PDOK documentation',
      ),
    )
  })

  it('says a velocity produces derived depth, not measured depth', () => {
    const { container } = renderForm('depth_conversion')
    const consequence = container.querySelector('[data-consequence]')?.textContent ?? ''
    expect(consequence).toContain('DERIVED, not measured')
    expect(consequence).toContain('assumption')
  })

  it('says a tie registers without overwriting the acquisition', () => {
    const { container } = renderForm('geo_tie')
    const consequence = container.querySelector('[data-consequence]')?.textContent ?? ''
    expect(consequence).toContain('Registration, not estimation')
    expect(consequence).toContain('without destroying the measurement')
  })

  it('says linking a surface model is not validating it', () => {
    const { container } = renderForm('surface_reference')
    expect(container.querySelector('[data-consequence]')?.textContent).toContain(
      'Linking is not validating',
    )
  })

  it('says an antenna offset has no default', () => {
    const { container } = renderForm('antenna_offset')
    expect(container.querySelector('[data-consequence]')?.textContent).toContain(
      'no default',
    )
  })

  it('says a declared CRS is not a validated one', () => {
    const { container } = renderForm('crs')
    const consequence = container.querySelector('[data-consequence]')?.textContent ?? ''
    expect(consequence).toContain('does not verify a CRS against the coordinate values')
  })

  it('shows the backend refusal verbatim', async () => {
    const { ApiError } = await import('@/services/api')
    declareSpatialReference.mockRejectedValue(
      new ApiError(422, 'velocity 3.0 m/ns is outside the physically plausible range'),
    )
    const { container } = renderForm('depth_conversion')
    fireEvent.change(container.querySelector('#depth_conversion-velocity_m_per_ns')!, {
      target: { value: '3.0' },
    })
    fireEvent.change(container.querySelector('#depth_conversion-supplied-by')!, {
      target: { value: 'me' },
    })
    fireEvent.submit(container.querySelector('form')!)

    await waitFor(() =>
      expect(container.querySelector('[data-declaration-error]')?.textContent).toContain(
        'outside the physically plausible range',
      ),
    )
  })
})

describe('declarations and staleness', () => {
  it('shows who established each declaration', async () => {
    const { container } = await renderView(
      reference({
        declarations: [
          {
            id: 'x1',
            dataset_id: 'd1',
            frame_id: null,
            kind: 'vertical_datum',
            value: { code: 'NAP' },
            supplied_by: 'PDOK documentation for AHN',
            note: null,
            created_at: '2026-08-11T10:00:00',
            superseded_at: null,
            superseded_by: null,
            active: true,
          },
        ],
      }),
    )
    const declaration = container.querySelector('[data-declaration="vertical_datum"]')
    expect(declaration?.textContent).toContain('PDOK documentation for AHN')
    expect(declaration?.textContent).toContain('not a measurement')
  })

  it('warns that downstream results are out of date, and that nothing was rerun', async () => {
    const { container } = await renderView(
      reference({ has_stale_products: true, stale_products: ['fusion sample f1'] }),
    )
    const stale = container.querySelector('[data-stale-products]')?.textContent ?? ''
    expect(stale).toContain('describe a different reference')
    expect(stale).toContain('Nothing has been recomputed automatically')
  })
})

describe('the component computes nothing', () => {
  it('derives no coordinate, depth or velocity of its own', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    const source = readFileSync(join(__dirname, 'spatial-reference.tsx'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, ' ')
      .replace(/\/\/[^\n]*/g, ' ')
    for (const forbidden of ['Math.', 'toFixed(', '* 0.', 'haversine']) {
      expect(source).not.toContain(forbidden)
    }
  })

  it('imports no 3D engine', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    for (const file of ['spatial-reference.tsx', 'declaration-form.tsx']) {
      const source = readFileSync(join(__dirname, file), 'utf8')
      expect(source).not.toMatch(/from ['"]three|@react-three/)
    }
  })
})
