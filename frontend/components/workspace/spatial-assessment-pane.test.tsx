/**
 * The Spatial assessment pane.
 *
 * Pins that the workspace shows the Stage 8 seven-dimension assessment
 * verbatim -- states and reasons the backend actually returned, none
 * recomputed -- and that an unresolved dimension is visible at the same
 * weight as a settled one, never styled as an error. Also pins that this
 * pane offers no way to make a declaration: /spatial remains the only place
 * that happens.
 */
import { cleanup, render, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SpatialReference } from '@/types/subterra'

const getSpatialReference = vi.fn()

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getSpatialReference: (id: string) => getSpatialReference(id),
    },
  }
})

import { SpatialAssessmentPane } from './spatial-assessment-pane'

function reference(overrides: Partial<SpatialReference> = {}): SpatialReference {
  return {
    contract_version: '1',
    dataset_id: 'd1',
    dimensions: [
      {
        dimension: 'horizontal_position',
        state: 'available',
        reason: 'Records carry a WGS84 latitude/longitude pair.',
        missing: [],
        action: null,
        provenance: null,
        detail: {},
      },
      {
        dimension: 'crs',
        state: 'inferred',
        reason: 'No CRS was declared; WGS84 lat/lon was inferred from the coordinate range.',
        missing: [],
        action: 'crs',
        provenance: null,
        detail: {},
      },
      {
        dimension: 'vertical_reference',
        state: 'unresolved',
        reason: 'No survey frame declares what its vertical axis is measured from.',
        missing: ['a vertical_datum declaration'],
        action: 'vertical_datum',
        provenance: null,
        detail: {},
      },
      {
        dimension: 'orientation',
        state: 'unresolved',
        reason: 'No survey geometry establishes antenna heading.',
        missing: [],
        action: null,
        provenance: null,
        detail: {},
      },
      {
        dimension: 'surface_reference',
        state: 'unresolved',
        reason: 'No DEM or surface model is linked to this dataset.',
        missing: [],
        action: 'surface_reference',
        provenance: null,
        detail: {},
      },
    ],
    common_frame: {
      state: 'incomplete',
      reason: 'not every Phase 4 input is resolved yet -- crs: inferred; orientation: unresolved',
      inputs: [
        'horizontal_position', 'crs', 'vertical_reference', 'orientation',
        'surface_reference', 'survey_geometry',
      ],
      crs_codes: [],
      vertical_datum_codes: [],
      agreement: 'undetermined',
    },
    declarations: [],
    has_stale_products: false,
    stale_products: [],
    ...overrides,
  }
}

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <SpatialAssessmentPane datasetId="d1" />
    </SWRConfig>,
  )
}

beforeEach(() => getSpatialReference.mockReset())
afterEach(cleanup)

describe('the Stage 8 assessment, rendered verbatim', () => {
  it('shows each dimension the endpoint returned, with its own state and reason', async () => {
    getSpatialReference.mockResolvedValue(reference())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-spatial-assessment]')).toBeTruthy())

    const horizontal = container.querySelector('[data-dimension="horizontal_position"]')
    expect(horizontal?.getAttribute('data-state')).toBe('available')
    expect(horizontal?.textContent).toContain('WGS84 latitude/longitude')

    const crs = container.querySelector('[data-dimension="crs"]')
    expect(crs?.getAttribute('data-state')).toBe('inferred')
    expect(crs?.textContent).toContain('inferred from the coordinate range')
  })

  it('covers the five Phase 4 questions', async () => {
    getSpatialReference.mockResolvedValue(reference())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-spatial-assessment]')).toBeTruthy())
    for (const dimension of [
      'horizontal_position',
      'vertical_reference',
      'orientation',
      'surface_reference',
      'crs',
    ]) {
      expect(container.querySelector(`[data-dimension="${dimension}"]`)).toBeTruthy()
    }
  })
})

describe('an unresolved dimension is a result, not an error', () => {
  it('is visible, marked data-resolved=false, and carries the backend reason', async () => {
    getSpatialReference.mockResolvedValue(reference())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-spatial-assessment]')).toBeTruthy())
    const vertical = container.querySelector('[data-dimension="vertical_reference"]')
    expect(vertical?.getAttribute('data-resolved')).toBe('false')
    expect(vertical?.textContent).toContain('No survey frame declares')
  })

  it('renders no error/warning styling class or icon for an unresolved dimension', async () => {
    getSpatialReference.mockResolvedValue(reference())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-spatial-assessment]')).toBeTruthy())
    const vertical = container.querySelector('[data-dimension="vertical_reference"]')
    const classes = vertical?.innerHTML ?? ''
    expect(classes).not.toMatch(/destructive|error|warning/i)
  })
})

describe('no declaration control', () => {
  it('offers no button, form, or input to establish a dimension', async () => {
    getSpatialReference.mockResolvedValue(reference())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-spatial-assessment]')).toBeTruthy())
    expect(container.querySelector('button')).toBeNull()
    expect(container.querySelector('form')).toBeNull()
    expect(container.querySelector('input')).toBeNull()
    expect(container.querySelector('[data-action^="resolve-"]')).toBeNull()
  })

  it('links to the existing /spatial page rather than embedding the workflow', async () => {
    getSpatialReference.mockResolvedValue(reference())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-spatial-assessment]')).toBeTruthy())
    expect(container.querySelector('a[href="/datasets/d1/spatial"]')).toBeTruthy()
  })
})

describe('two different acquisition kinds show whatever the endpoint returned', () => {
  it('a fully resolved assessment renders as resolved, not as a special case', async () => {
    getSpatialReference.mockResolvedValue(
      reference({
        dimensions: reference().dimensions.map((d) => ({
          ...d,
          state: 'available',
        })),
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-spatial-assessment]')).toBeTruthy())
    expect(container.querySelector('[data-resolved="false"]')).toBeNull()
  })

  it('an all-unresolved assessment (e.g. a bare FileDrop CSV) renders every dimension unresolved', async () => {
    getSpatialReference.mockResolvedValue(
      reference({
        dimensions: reference().dimensions.map((d) => ({
          ...d,
          state: 'unresolved',
        })),
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-spatial-assessment]')).toBeTruthy())
    expect(container.querySelectorAll('[data-resolved="false"]').length).toBe(5)
  })
})

describe('a session-declared claim never appears here', () => {
  it('renders none of AcquisitionPane\'s "(declared)" session-claim labels', async () => {
    getSpatialReference.mockResolvedValue(reference())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-spatial-assessment]')).toBeTruthy())
    // This pane reads only GET /api/spatial/{id} -- it has no session prop
    // and cannot render a session's operator-declared coordinate_system /
    // vertical_reference / processing_version, which AcquisitionPane labels
    // with this exact "(declared)" suffix.
    for (const label of [
      'Coordinate system (declared)',
      'Vertical reference (declared)',
      'Processing version (declared)',
    ]) {
      expect(container.textContent).not.toContain(label)
    }
  })
})

describe('the common spatial frame composition', () => {
  it('is printed at the same weight as a dimension, verbatim', async () => {
    getSpatialReference.mockResolvedValue(reference())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-common-frame]')).toBeTruthy())
    const node = container.querySelector('[data-common-frame]')
    expect(node?.getAttribute('data-state')).toBe('incomplete')
    expect(node?.textContent).toContain('not every Phase 4 input is resolved yet')
  })

  it('is not rendered as one of the seven dimensions', async () => {
    getSpatialReference.mockResolvedValue(reference())
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-common-frame]')).toBeTruthy())
    expect(container.querySelector('[data-dimension="common_frame"]')).toBeNull()
  })

  it('never claims a frame has been computed when inputs are present', async () => {
    getSpatialReference.mockResolvedValue(
      reference({
        common_frame: {
          state: 'inputs_present',
          reason: 'every Phase 4 input is individually resolved, but no common spatial frame has been computed from them',
          inputs: ['horizontal_position', 'crs', 'vertical_reference', 'orientation', 'surface_reference', 'survey_geometry'],
          crs_codes: ['EPSG:4326'],
          vertical_datum_codes: ['NAP'],
          agreement: 'agree',
        },
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-common-frame]')).toBeTruthy())
    const node = container.querySelector('[data-common-frame]')
    expect(node?.getAttribute('data-state')).toBe('inputs_present')
    expect(node?.textContent).toContain('no common spatial frame has been computed')
  })

  it('prints the recorded CRS/vertical-datum identity and the agreement value verbatim', async () => {
    getSpatialReference.mockResolvedValue(
      reference({
        common_frame: {
          state: 'inputs_present',
          reason: 'every Phase 4 input is individually resolved, but they do not agree',
          inputs: ['horizontal_position', 'crs', 'vertical_reference', 'orientation', 'surface_reference', 'survey_geometry'],
          crs_codes: ['EPSG:28992', 'EPSG:4326'],
          vertical_datum_codes: ['MSL', 'NAP'],
          agreement: 'disagree',
        },
      }),
    )
    const { container } = view()

    await waitFor(() => expect(container.querySelector('[data-common-frame]')).toBeTruthy())
    const node = container.querySelector('[data-common-frame]')
    expect(node?.textContent).toContain('disagree')
    expect(node?.textContent).toContain('EPSG:28992')
    expect(node?.textContent).toContain('EPSG:4326')
    expect(node?.textContent).toContain('MSL')
    expect(node?.textContent).toContain('NAP')
  })
})
