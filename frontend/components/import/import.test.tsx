/**
 * The import surface.
 *
 * What these pin is not that the upload works -- the backend tests cover that
 * -- but that the interface tells the truth about it: that the three format
 * verdicts stay distinct, that a stage track never becomes a percentage, that
 * a failure shows the backend's own words, and that a successful import
 * reports what is MISSING as prominently as what arrived.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { FormatVerdict, classify, extensionOf } from './format-check'
import { JobState, StageTrack } from './job-progress'
import { ImportFailure } from './import-report'
import type { ImportFormats, ImportJob } from '@/types/subterra'

const FORMATS: ImportFormats = {
  supported: ['.csv', '.sgy', '.dzt'],
  recognized_unsupported: [
    { extension: '.dzx', description: 'GSSI XML sidecar (read with its .dzt)' },
    { extension: '.sgd', description: 'Sensors & Software (proprietary GPR)' },
  ],
  max_upload_bytes: 2 * 1024 * 1024 * 1024,
  note: 'x',
}

function job(over: Partial<ImportJob> = {}): ImportJob {
  return {
    id: 'job-1',
    job_type: 'dataset_import',
    state: 'QUEUED',
    stage: 'queued',
    original_filename: 'line1.sgy',
    stored_filename: 'line1.sgy',
    size_bytes: 1024,
    sensor_type: 'gpr',
    detected_format: 'segy',
    format_status: 'supported',
    dataset_id: null,
    error_stage: null,
    error_message: null,
    owner_id: null,
    created_at: '2026-08-08T10:00:00',
    started_at: null,
    completed_at: null,
    ...over,
  }
}

describe('the three format verdicts stay distinct', () => {
  it('classifies a supported extension as readable', () => {
    const v = classify({ name: 'line1.sgy', size: 10 }, FORMATS)
    expect(v.kind).toBe('supported')
    render(<FormatVerdict verdict={v} />)
    expect(screen.getByText(/readable/i)).toBeTruthy()
  })

  it('distinguishes recognised-but-unreadable from unknown', () => {
    const known = classify({ name: 'survey.dzx', size: 10 }, FORMATS)
    const unknown = classify({ name: 'notes.bananas', size: 10 }, FORMATS)
    expect(known.kind).toBe('recognized_unsupported')
    expect(unknown.kind).toBe('unknown')

    const a = render(<FormatVerdict verdict={known} />)
    expect(a.container.textContent).toMatch(/recognised format — no adapter available/i)
    // it still NAMES the format, which is the point of the third state
    expect(a.container.textContent).toMatch(/GSSI XML sidecar/i)

    const b = render(<FormatVerdict verdict={unknown} />)
    expect(b.container.textContent).toMatch(/unknown format/i)
    expect(b.container.textContent).not.toMatch(/no adapter available/i)
  })

  it('refuses a file above the deployment limit', () => {
    const v = classify({ name: 'huge.sgy', size: FORMATS.max_upload_bytes + 1 }, FORMATS)
    expect(v.kind).toBe('too_large')
  })

  it('reads the extension case-insensitively so .SGY is not unknown', () => {
    expect(extensionOf('LINE1.SGY')).toBe('.sgy')
    expect(classify({ name: 'LINE1.SGY', size: 10 }, FORMATS).kind).toBe('supported')
  })

  it('keeps no format list of its own', async () => {
    // The verdicts must come from the backend registry passed in, never a
    // constant in the component. Passing an empty registry must make even a
    // .csv unknown.
    const empty: ImportFormats = { ...FORMATS, supported: [], recognized_unsupported: [] }
    expect(classify({ name: 'a.csv', size: 1 }, empty).kind).toBe('unknown')
  })
})

describe('progress is a stage, never a percentage', () => {
  it('renders the pipeline stages and marks the current one', () => {
    const { container } = render(<StageTrack job={job({ state: 'RUNNING', stage: 'validating' })} />)
    const active = container.querySelector('[data-stage-active="true"]')
    expect(active?.getAttribute('data-stage')).toBe('validating')
  })

  it('shows no percentage anywhere', () => {
    const { container } = render(<StageTrack job={job({ state: 'RUNNING', stage: 'persisting' })} />)
    expect(container.textContent ?? '').not.toMatch(/\d+\s*%/)
    expect(container.querySelector('progress')).toBeNull()
    expect(container.querySelector('[role="progressbar"]')).toBeNull()
  })

  it('renders each of the four job states explicitly', () => {
    for (const state of ['QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED'] as const) {
      const { container } = render(<JobState job={job({ state })} />)
      expect(container.querySelector(`[data-job-state="${state}"]`)).toBeTruthy()
      expect(container.textContent).toContain(state)
    }
  })
})

describe('a failure is useful', () => {
  it('shows the stage, the filename and the backend message verbatim', () => {
    const failed = job({
      state: 'FAILED',
      error_stage: 'converting',
      error_message: 'Conversion failed: trace length does not divide the body exactly',
      original_filename: 'broken.sgy',
    })
    const { container } = render(<ImportFailure job={failed} onReset={vi.fn()} />)

    expect(container.textContent).toMatch(/import failed/i)
    expect(container.textContent).toContain('converting')
    expect(container.textContent).toContain('broken.sgy')
    const message = container.querySelector('[data-error-message]')
    expect(message?.textContent).toBe(
      'Conversion failed: trace length does not divide the body exactly',
    )
  })

  it('never replaces a technical error with a generic apology', () => {
    const { container } = render(
      <ImportFailure
        job={job({ state: 'FAILED', error_message: 'segyio refused the file' })}
        onReset={vi.fn()}
      />,
    )
    const text = (container.textContent ?? '').toLowerCase()
    expect(text).not.toContain('something went wrong')
    expect(text).not.toContain('oops')
    expect(text).not.toContain('unexpected error')
  })

  it('offers a way to try another dataset', () => {
    const onReset = vi.fn()
    render(<ImportFailure job={job({ state: 'FAILED' })} onReset={onReset} />)
    const button = screen.getByRole('button', { name: /try another dataset/i })
    button.click()
    expect(onReset).toHaveBeenCalled()
  })
})

describe('the product vocabulary is not weakened', () => {
  it('the import surface never calls a candidate a detection', () => {
    const files = ['./format-check.tsx', './job-progress.tsx', './import-report.tsx']
    // read as source so copy changes are caught, not just rendered output
    return Promise.all(
      files.map(async (f) => {
        const { readFileSync } = await import('node:fs')
        const { join } = await import('node:path')
        const src = readFileSync(join(__dirname, f), 'utf8').toLowerCase()
        expect(src).not.toContain('ai interpretation')
        expect(src).not.toContain('ai confidence')
        expect(src).not.toMatch(/detected (utilities|objects|pipes)/)
      }),
    )
  })

  it('does not advertise hardware that does not exist', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    // Comments are stripped first -- as tests/no-synthetic-geometry.test.ts
    // does for its velocity check -- because the page's own docstring
    // legitimately EXPLAINS why it is not called "New Scan", and a raw source
    // scan would read that explanation as the offence.
    const page = readFileSync(
      join(__dirname, '..', '..', 'app', '(workspace)', 'import', 'page.tsx'),
      'utf8',
    )
      .replace(/\/\*[\s\S]*?\*\//g, ' ')
      .replace(/\/\/[^\n]*/g, ' ')
      .toLowerCase()

    expect(page).not.toContain('connect hardware')
    expect(page).not.toContain('coming soon')
    expect(page).not.toContain('new scan')
    expect(page).not.toContain('live trace')
  })
})
