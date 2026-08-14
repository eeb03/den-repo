/**
 * The session-attributed import path.
 *
 * Stage 10 declared the architecture (a session's evidence arrives through
 * the same acquisition boundary a dropped file does) and it was tested at the
 * API layer -- but the product path never used it: the session's "Import"
 * link carried no session id, `api.createImport` never sent one, and a file
 * dropped after recording a device became an ordinary, unattributed FileDrop
 * acquisition. These tests pin the fix: the id travels from the URL into the
 * request, and bare /import (no id) is unchanged.
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, describe, expect, it, vi, beforeEach } from 'vitest'

import { ApiError } from '@/services/api'
import type { ImportFormats, SessionPayload } from '@/types/subterra'

let searchParams = new URLSearchParams('')
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/import',
  useSearchParams: () => searchParams,
}))

const getImportFormats = vi.fn()
const getSession = vi.fn()
const createImport = vi.fn()
vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      getImportFormats: () => getImportFormats(),
      getSession: (id: string) => getSession(id),
      createImport: (...a: unknown[]) => createImport(...a),
    },
  }
})

import ImportPage from './page'

function renderPage() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <ImportPage />
    </SWRConfig>,
  )
}

const FORMATS: ImportFormats = {
  supported: ['.csv', '.sgy'],
  recognized_unsupported: [],
  max_upload_bytes: 2 * 1024 * 1024 * 1024,
  note: 'x',
}

function sessionPayload(overrides: Partial<SessionPayload> = {}): SessionPayload {
  return {
    session: {
      id: 's1',
      device_id: 'dev1',
      owner_id: 'u1',
      state: 'READY',
      label: null,
      operator: null,
      notes: null,
      survey_area: null,
      coordinate_system: null,
      vertical_reference: null,
      evidence: { position_provided: false },
      failure_stage: null,
      failure_message: null,
      created_at: '2026-08-14T10:00:00',
      started_at: null,
      ended_at: null,
    },
    device: {
      id: 'dev1',
      owner_id: 'u1',
      is_system_device: false,
      manufacturer: 'IDS',
      model: 'Stream C',
      device_type: 'gpr',
      serial_number: null,
      firmware_version: null,
      capabilities: { modalities: ['gpr'] },
      adapter: { transport: 'file_drop' },
      identity_source: 'user_declared',
      kind: 'physical',
      is_simulated: false,
      label: null,
      created_at: '2026-08-14T09:00:00',
    },
    capability_gap: [],
    acquisitions: [],
    datasets: [],
    ...overrides,
  }
}

beforeEach(() => {
  searchParams = new URLSearchParams('')
  getImportFormats.mockReset().mockResolvedValue(FORMATS)
  getSession.mockReset()
  createImport.mockReset()
})
afterEach(cleanup)

describe('bare /import (no session)', () => {
  it('shows no attribution banner', async () => {
    const { container } = renderPage()
    await screen.findByText(/drop a dataset here/i)
    expect(container.querySelector('[data-session-attribution]')).toBeNull()
    expect(getSession).not.toHaveBeenCalled()
  })

  it('creates the import with no session id', async () => {
    createImport.mockResolvedValue({
      job: { id: 'j1', state: 'IDENTIFIED', dataset_id: null, session_id: null },
    })
    renderPage()
    await screen.findByText(/drop a dataset here/i)

    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['x'], 'line1.sgy')
    Object.defineProperty(input, 'files', { value: [file] })
    input.dispatchEvent(new Event('change', { bubbles: true }))

    const button = await screen.findByRole('button', { name: /import dataset/i })
    button.click()

    await waitFor(() => expect(createImport).toHaveBeenCalled())
    expect(createImport).toHaveBeenCalledWith(file, 'gpr', true, undefined)
  })
})

describe('/import?session=<id>', () => {
  beforeEach(() => {
    searchParams = new URLSearchParams('session=s1')
  })

  it('shows which session the drop will be attributed to', async () => {
    getSession.mockResolvedValue(sessionPayload())
    const { container } = renderPage()

    await waitFor(() =>
      expect(container.querySelector('[data-session-attribution]')).toBeTruthy(),
    )
    const banner = container.querySelector('[data-session-attribution]')
    expect(banner?.textContent).toContain('IDS Stream C')
    expect(banner?.textContent).toContain('READY')
  })

  it('offers a way back to the unattributed path', async () => {
    getSession.mockResolvedValue(sessionPayload())
    const { container } = renderPage()

    await waitFor(() =>
      expect(container.querySelector('[data-session-attribution]')).toBeTruthy(),
    )
    expect(container.querySelector('a[href="/import"]')).toBeTruthy()
  })

  it('sends the session id with the import', async () => {
    getSession.mockResolvedValue(sessionPayload())
    createImport.mockResolvedValue({
      job: { id: 'j1', state: 'IDENTIFIED', dataset_id: null, session_id: 's1' },
    })
    renderPage()
    await screen.findByText(/drop a dataset here/i)

    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['x'], 'line1.sgy')
    Object.defineProperty(input, 'files', { value: [file] })
    input.dispatchEvent(new Event('change', { bubbles: true }))

    const button = await screen.findByRole('button', { name: /import dataset/i })
    button.click()

    await waitFor(() => expect(createImport).toHaveBeenCalled())
    expect(createImport).toHaveBeenCalledWith(file, 'gpr', true, 's1')
  })

  it('surfaces the backend refusal of a closed session verbatim, inventing no new wording', async () => {
    getSession.mockResolvedValue(sessionPayload({ session: { ...sessionPayload().session, state: 'COMPLETED' } }))
    createImport.mockRejectedValue(
      new ApiError(409, 'this session is COMPLETED and cannot receive an acquisition'),
    )
    renderPage()
    await screen.findByText(/drop a dataset here/i)

    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['x'], 'line1.sgy')
    Object.defineProperty(input, 'files', { value: [file] })
    input.dispatchEvent(new Event('change', { bubbles: true }))

    const button = await screen.findByRole('button', { name: /import dataset/i })
    button.click()

    await waitFor(() =>
      expect(screen.getByText(/this session is COMPLETED and cannot receive/i)).toBeTruthy(),
    )
  })

  it('shows the absence when the session cannot be found or is not yours', async () => {
    getSession.mockRejectedValue(new ApiError(404, 'Session not found'))
    renderPage()

    await waitFor(() => expect(screen.getByText(/session unavailable/i)).toBeTruthy())
  })
})
