/**
 * The acquisition review.
 *
 * This screen exists to stop an ingestion happening before anybody has been
 * told what the file is. So the tests are about what it must state before it
 * offers to proceed — that the modality came from the uploader rather than the
 * file, that identical bytes are already held, that the spatial section is an
 * expectation about the FORMAT and not a claim about this file, and that
 * incomplete spatial reference blocks reconstruction rather than ingestion.
 */
import { render, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import type { ImportJob } from '@/types/subterra'

const acceptAcquisition = vi.fn()
vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      acceptAcquisition: (id: string, options?: unknown) =>
        acceptAcquisition(id, options),
    },
  }
})

import { AcquisitionReview } from './acquisition-review'

function job(overrides: Record<string, unknown> = {}): ImportJob {
  return {
    id: 'j1',
    job_type: 'dataset_import',
    state: 'NEEDS_INPUT',
    stage: null,
    original_filename: 'survey.csv',
    stored_filename: 'survey.csv',
    size_bytes: 2048,
    sensor_type: 'gpr',
    detected_format: 'csv',
    format_status: 'supported',
    dataset_id: null,
    error_stage: null,
    error_message: null,
    owner_id: 'u1',
    created_at: '2026-08-12T10:00:00',
    started_at: null,
    completed_at: null,
    checksum: 'a'.repeat(64),
    content_type: 'text/csv',
    identification: {
      original_filename: 'survey.csv',
      stored_filename: 'survey.csv',
      size_bytes: 2048,
      checksum: 'a'.repeat(64),
      content_type_claimed: 'text/csv',
      classification: 'supported',
      detected_format: 'csv',
      parser_available: true,
      declared_modality: 'gpr',
      modality_source: 'declared_by_uploader',
      ambiguous_format: true,
      ambiguity_note:
        'a csv file can hold several kinds of measurement, and Subterra cannot tell which from the file alone.',
      spatial_expectation: {
        horizontal: 'whatever columns the file happens to contain',
        vertical: 'whatever columns the file happens to contain',
        missing: ['a declared CRS, unless the file states one', 'a vertical datum'],
      },
      spatial_expectation_note:
        'what this FORMAT can carry, not what this file declares.',
      duplicates: { checked: true, is_duplicate: false, datasets: [], acquisitions: [] },
      ingestion_ready: true,
    },
    ...overrides,
  } as unknown as ImportJob
}

beforeEach(() => {
  // BLOCK BODY, NOT A CONCISE ARROW. `() => acceptAcquisition.mockReset()`
  // RETURNS the mock from the hook, which vitest then treats as a value to
  // settle -- shifting the timing enough that a rejected call was observed as
  // unhandled before React had attached the component's catch. The behaviour
  // under test never changed; the hook's return value did.
  acceptAcquisition.mockReset()
})

describe('what arrived', () => {
  it('shows the filename, format, declared modality and checksum', () => {
    const { container } = render(<AcquisitionReview job={job()} />)
    const text = container.textContent ?? ''
    expect(text).toContain('survey.csv')
    expect(text).toContain('csv')
    expect(text).toContain('gpr')
    expect(container.querySelector('[data-checksum]')?.textContent).toContain('aaaa')
  })

  it('says the modality came from the uploader, not the file', () => {
    const { container } = render(<AcquisitionReview job={job()} />)
    expect(container.querySelector('[data-ambiguous]')?.textContent).toContain(
      'cannot tell which from the file alone',
    )
  })
})

describe('spatial expectation', () => {
  it('is framed as what the format can carry, not what this file declares', () => {
    const { container } = render(<AcquisitionReview job={job()} />)
    const spatial = container.querySelector('[data-spatial-expectation]')?.textContent ?? ''
    expect(spatial).toContain('not what this file declares')
  })

  it('lists what is likely to need establishing later', () => {
    const { container } = render(<AcquisitionReview job={job()} />)
    expect(container.querySelectorAll('[data-expected-missing]').length).toBe(2)
  })

  it('says missing spatial information blocks reconstruction, not ingestion', () => {
    const { container } = render(<AcquisitionReview job={job()} />)
    const spatial = container.querySelector('[data-spatial-expectation]')?.textContent ?? ''
    expect(spatial).toContain('does not stop this file being read')
    expect(spatial).toContain('stops 3D reconstruction')
  })

  it('claims no CRS, datum or depth of its own', () => {
    const { container } = render(<AcquisitionReview job={job()} />)
    const text = (container.textContent ?? '').toLowerCase()
    for (const fabricated of ['epsg:', 'nap ', 'm/ns', 'metres below']) {
      expect(text).not.toContain(fabricated)
    }
  })
})

describe('duplicates', () => {
  it('says nothing when the bytes are new', () => {
    const { container } = render(<AcquisitionReview job={job()} />)
    expect(container.querySelector('[data-duplicate]')).toBeNull()
  })

  it('reports identical bytes without offering to merge them', () => {
    const duplicate = job()
    ;(duplicate.identification as unknown as Record<string, unknown>).duplicates = {
      checked: true,
      is_duplicate: true,
      datasets: [{ dataset_id: 'd9', name: 'Earlier survey' }],
      acquisitions: [],
      note: 'Separate arrivals are kept separate.',
    }
    const { container } = render(<AcquisitionReview job={duplicate} />)
    const panel = container.querySelector('[data-duplicate]')
    expect(panel?.textContent).toContain('already held')
    expect(panel?.textContent).toContain('Separate arrivals are kept separate')
    expect(container.textContent?.toLowerCase()).not.toContain('merge')
    // and it can still be imported: the user decides what identical bytes mean
    expect(container.querySelector('[data-action="accept-acquisition"]')).toBeTruthy()
  })
})

describe('rejection', () => {
  it('explains why and what would work, and offers no import', () => {
    const rejected = job({ state: 'REJECTED' })
    Object.assign(rejected.identification as unknown as Record<string, unknown>, {
      parser_available: false,
      rejection_reason: "Unrecognised file type '.docx'.",
      supported_formats: ['.csv', '.sgy'],
    })
    const { container } = render(<AcquisitionReview job={rejected} />)

    expect(container.querySelector('[data-rejected]')?.textContent).toContain(
      "Unrecognised file type '.docx'",
    )
    expect(container.textContent).toContain('.sgy')
    expect(container.querySelector('[data-action="accept-acquisition"]')).toBeNull()
  })
})

describe('handing off', () => {
  it('accepts only when the user says so', async () => {
    acceptAcquisition.mockResolvedValue({ job: job({ state: 'QUEUED' }) })
    const onAccepted = vi.fn()
    const { container } = render(<AcquisitionReview job={job()} onAccepted={onAccepted} />)

    expect(acceptAcquisition).not.toHaveBeenCalled()
    fireEvent.click(container.querySelector('[data-action="accept-acquisition"]')!)

    await waitFor(() => expect(acceptAcquisition).toHaveBeenCalledWith('j1', {}))
    await waitFor(() => expect(onAccepted).toHaveBeenCalled())
  })

  it('shows the backend refusal verbatim', async () => {
    const { ApiError } = await import('@/services/api')
    acceptAcquisition.mockRejectedValue(new ApiError(409, 'this acquisition is REJECTED'))

    const { container } = render(<AcquisitionReview job={job()} />)
    fireEvent.click(container.querySelector('[data-action="accept-acquisition"]')!)
    await new Promise((resolve) => setTimeout(resolve, 50))

    expect(container.querySelector('[data-acquisition-error]')?.textContent).toContain(
      'this acquisition is REJECTED',
    )
  })
})

describe('the component computes nothing', () => {
  it('derives no format, modality or spatial claim of its own', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    const source = readFileSync(join(__dirname, 'acquisition-review.tsx'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, ' ')
      .replace(/\/\/[^\n]*/g, ' ')
    // No local guessing from the filename or extension.
    for (const forbidden of ['endsWith(', 'split(\'.\')', 'EPSG', 'Math.']) {
      expect(source).not.toContain(forbidden)
    }
  })
})

describe('the surface anchor declaration', () => {
  function geotiff() {
    const raster = job()
    Object.assign(raster.identification as unknown as Record<string, unknown>, {
      detected_format: 'geotiff',
      ambiguous_format: false,
      ambiguity_note: null,
    })
    return raster
  }

  it('is offered for a raster and not for other formats', () => {
    const { container: csv } = render(<AcquisitionReview job={job()} />)
    expect(csv.querySelector('[data-band-declaration]')).toBeNull()

    const { container } = render(<AcquisitionReview job={geotiff()} />)
    expect(container.querySelector('[data-band-declaration]')).toBeTruthy()
  })

  it('is undeclared by default', () => {
    const { container } = render(<AcquisitionReview job={geotiff()} />)
    expect((container.querySelector('#band-is-elevation') as HTMLInputElement).checked)
      .toBe(false)
  })

  it('says the file does not state what its band measures', () => {
    const { container } = render(<AcquisitionReview job={geotiff()} />)
    const text = container.querySelector('[data-band-declaration]')?.textContent ?? ''
    expect(text).toContain('does not say what its band measures')
    expect(text).toContain('recorded as your claim')
    expect(text).toContain('undeclared band is a correct answer')
  })

  it('says a surface still needs a datum before it can anchor anything', () => {
    const { container } = render(<AcquisitionReview job={geotiff()} />)
    expect(container.querySelector('[data-band-declaration]')?.textContent).toContain(
      'declared vertical datum before it can anchor anything',
    )
  })

  it('sends the declaration only when the format can use it', async () => {
    acceptAcquisition.mockResolvedValue({ job: job() })

    const { container } = render(<AcquisitionReview job={geotiff()} />)
    fireEvent.click(container.querySelector('#band-is-elevation')!)
    fireEvent.click(container.querySelector('[data-action="accept-acquisition"]')!)
    await waitFor(() =>
      expect(acceptAcquisition).toHaveBeenCalledWith('j1', { band_is_elevation: true }),
    )

    acceptAcquisition.mockClear()
    const { container: csv } = render(<AcquisitionReview job={job()} />)
    fireEvent.click(csv.querySelector('[data-action="accept-acquisition"]')!)
    await waitFor(() => expect(acceptAcquisition).toHaveBeenCalledWith('j1', {}))
  })
})
