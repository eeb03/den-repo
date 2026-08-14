/**
 * The Dataset Report screen.
 *
 * The property under test is not "does it render" — it is that the screen
 * cannot quietly improve on what the backend said. A UI that rewords a
 * scientific limitation eventually softens it: "no frame declares a vertical
 * datum" becomes "some metadata missing", and the softened version is what
 * people remember. So these tests check that reasons appear verbatim, that a
 * blocked capability keeps its "requires" list, that an unmeasured quality
 * dimension never renders as 0 %, and that nothing on the page turns a
 * candidate into a detection.
 */
import { render } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import type { DatasetReport } from '@/types/subterra'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/datasets/d/report',
  useSearchParams: () => new URLSearchParams(''),
}))

const getDatasetReport = vi.fn()
vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    api: { ...actual.api, getDatasetReport: (id: string) => getDatasetReport(id) },
  }
})

import { DatasetReportView } from './dataset-report'

/** A dataset in the state every one currently held is in. */
function report(overrides: Partial<DatasetReport> = {}): DatasetReport {
  return {
    report_version: '1.0',
    generated_at: '2026-08-11T10:00:00',
    identity: {
      dataset_id: 'd1',
      name: 'Site 01 GPR',
      source: null,
      source_url: null,
      license: null,
      modality: 'gpr',
      recorded_modalities: ['gpr'],
      declared_sensor_type: 'gpr',
      original_format: 'segy',
      source_files: ['line1.sgy'],
      manufacturer: null,
      device_model: null,
      collection_date: null,
      imported_at: '2026-01-01T00:00:00',
      updated_at: '2026-01-01T00:00:00',
      checksum: null,
      version: 1,
      owner_id: null,
      is_system_dataset: true,
      has_ground_truth: false,
      undeclared: ['source', 'licence', 'manufacturer', 'device model'],
    },
    volume: {
      record_count: 10727,
      frame_count: 1,
      positions_per_frame: { 'd1:line1': 10727 },
      samples_per_trace: [512],
      sample_interval: [0.4],
      sample_interval_units: 'ns',
      records_with_signal: 10727,
      records_with_timestamp: 0,
      records_with_depth: 0,
      records_with_position: 0,
      invalid_signal_count: 0,
      position_kinds: { none: 10727 },
    },
    spatial: {
      horizontal: {
        coordinates_present: false,
        earth_referenced: false,
        declared_refs: [],
        crs_kinds: ['unknown'],
        crs_provenance: ['none'],
        positioned_record_count: 0,
        total_record_count: 10727,
        geo_tie_frames: [],
        reasons: ['no record carries a horizontal position'],
        missing: ['positions from the acquisition, or a GeoTie supplying them'],
      },
      vertical: {
        axis_kinds: ['two_way_time_ns'],
        axis_units: ['ns'],
        axis_origins: ['instrument time zero'],
        vertical_datum_declared: false,
        vertical_datums: [],
        depth_axis_available: false,
        depth_basis: 'unavailable',
        time_to_depth_justified: false,
        surface_model_held: false,
        surface_frame_ids: [],
        relationship_kind: null,
        absolute_elevation_available: false,
        reasons: ['no frame declares a vertical datum'],
        missing: ['a declared vertical datum for the acquisition elevations'],
      },
      geometry: {
        frame_count: 1,
        bounds: null,
        lat_span_m: null,
        lon_span_m: null,
        along_track_extent_m: {},
        reasons: ['survey bounds need geographic positions; this dataset has none'],
      },
    },
    processing: [
      { stage: 'format_identification', status: 'completed', detail: 'segy', parameters: {}, at: null },
      { stage: 'preprocessing', status: 'not_run', detail: 'no record carries a processing_applied entry', parameters: {}, at: null },
    ],
    signal_chain: {
      recorded: false,
      reason: 'no record carries a processing_applied entry -- preprocessing was not recorded for this dataset',
      steps: [],
    },
    quality: {
      stored_score: 0.8,
      computed_score: 0.8,
      dimensions: [
        {
          name: 'coordinate_integrity',
          value: 1.0,
          weight: 0.5,
          basis: 'records that declare a geographic position and carry valid coordinates',
          counts: { records: 10727 },
        },
        {
          name: 'signal_quality',
          value: null,
          weight: 0,
          basis: 'not measured: no noise floor, calibration target or repeat survey is held',
          counts: {},
        },
      ],
      issues: [],
      score_is_stale: false,
    },
    candidates: {
      candidate_count: 0,
      analysed: false,
      frames_with_candidates: [],
      shape_classes: {},
      evidence_available: false,
      classified_object_count: 0,
      note: 'Candidates are anomalous regions, not detected objects. No object classification has been performed.',
      status: 'blocked',
      status_reason: 'candidate generation has not been run for this dataset',
      missing: ['a candidate generation run'],
      method: null,
      method_version: null,
      generated_at: null,
      is_stale: false,
      stale_reasons: [],
      localisation_breakdown: {},
      depth_breakdown: {},
      classification_status: 'BLOCKED',
    },
    readiness: [
      {
        capability: 'ingestion',
        readiness: 'ready',
        reason: '10,727 record(s) across 1 frame(s) were converted and stored',
        missing: [],
        depends_on: [],
      },
      {
        capability: 'vertical_registration',
        readiness: 'blocked',
        reason: 'no frame declares a vertical datum',
        missing: ['a declared vertical datum for the acquisition elevations'],
        depends_on: [],
      },
      {
        capability: 'object_classification',
        readiness: 'blocked',
        reason: 'Subterra has no validated object classifier',
        missing: ['a classifier validated against ground truth on a benchmark site'],
        depends_on: ['candidate_analysis'],
      },
      {
        capability: 'reconstruction_3d',
        readiness: 'blocked',
        reason:
          'a 3D reconstruction needs every sample placed in one frame with X, Y and Z; horizontal registration and vertical registration are not available for this dataset',
        missing: ['a declared vertical datum for the acquisition elevations'],
        depends_on: ['horizontal_registration', 'vertical_registration'],
      },
    ],
    provenance: [],
    ...overrides,
  }
}

async function renderReport(data: DatasetReport = report()) {
  getDatasetReport.mockResolvedValue(data)
  // A FRESH SWR CACHE PER RENDER. Without it the second case in a file gets
  // the first case's response back from cache and asserts against a report it
  // never supplied -- which passes or fails for reasons that have nothing to
  // do with the component.
  const result = render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <DatasetReportView datasetId="d1" />
    </SWRConfig>,
  )
  // SWR resolves on a microtask; flush before asserting.
  await new Promise((resolve) => setTimeout(resolve, 0))
  return result
}

beforeEach(() => {
  getDatasetReport.mockReset()
})

describe('readiness', () => {
  it('renders every capability the backend reported', async () => {
    const { container } = await renderReport()
    expect(container.querySelectorAll('[data-capability]').length).toBe(4)
  })

  it('keeps the backend reason verbatim rather than paraphrasing it', async () => {
    const { container } = await renderReport()
    expect(container.textContent).toContain(
      '10,727 record(s) across 1 frame(s) were converted and stored',
    )
    expect(container.textContent).toContain('Subterra has no validated object classifier')
  })

  it('shows what a blocked capability requires', async () => {
    const { container } = await renderReport()
    const blocked = container.querySelector('[data-capability="vertical_registration"]')
    expect(blocked?.getAttribute('data-readiness')).toBe('blocked')
    expect(blocked?.querySelectorAll('[data-missing]').length).toBeGreaterThan(0)
    expect(blocked?.textContent).toContain('a declared vertical datum')
  })

  it('never renders a blocked capability without a stated requirement', async () => {
    const { container } = await renderReport()
    for (const node of container.querySelectorAll('[data-readiness="blocked"][data-capability]')) {
      expect(node.querySelectorAll('[data-missing]').length).toBeGreaterThan(0)
    }
  })

  it('distinguishes the three states in the markup, not only in colour', async () => {
    const { container } = await renderReport()
    const states = new Set(
      Array.from(container.querySelectorAll('[data-capability]')).map((n) =>
        n.getAttribute('data-readiness'),
      ),
    )
    expect(states.has('ready')).toBe(true)
    expect(states.has('blocked')).toBe(true)
  })
})

describe('spatial limitations are visible', () => {
  it('states that coordinates are absent rather than showing an empty field', async () => {
    const { container } = await renderReport()
    const text = container.textContent ?? ''
    expect(text).toContain('no record carries a horizontal position')
    expect(container.querySelector('[data-earth-referenced="false"]')).toBeTruthy()
  })

  it('says the vertical datum is not declared', async () => {
    const { container } = await renderReport()
    expect(container.querySelector('[data-vertical-datum="false"]')?.textContent).toBe(
      'Not declared',
    )
  })

  it('reports depth as not validated when no time-to-depth relationship exists', async () => {
    const { container } = await renderReport()
    expect(container.querySelector('[data-time-to-depth="false"]')?.textContent).toBe(
      'Not validated',
    )
    expect(container.querySelector('[data-absolute-elevation="false"]')?.textContent).toBe(
      'Not available',
    )
  })

  it('shows no survey extent when nothing carries a position', async () => {
    const { container } = await renderReport()
    expect(container.textContent).toContain(
      'survey bounds need geographic positions; this dataset has none',
    )
    // and no fabricated zero-sized extent
    expect(container.textContent).not.toMatch(/0 m × 0 m/)
  })
})

describe('missing metadata is named, not fabricated', () => {
  it('lists what the source did not declare', async () => {
    const { container } = await renderReport()
    const undeclared = container.querySelector('[data-undeclared]')
    expect(undeclared?.textContent).toContain('manufacturer')
    expect(undeclared?.textContent).toContain('Subterra does not infer these')
  })

  it('renders an absent field as an explained absence, never as a value', async () => {
    const { container } = await renderReport()
    // The em dash is the platform's NO_VALUE marker.
    expect(container.textContent).toContain('—')
    expect(container.textContent).not.toMatch(/Manufacturer\s*(unknown|n\/a|none)/i)
  })
})

describe('recorded modality composition vs. the ingest declaration', () => {
  it('names one recorded modality plainly, no "only"/"incomplete"/"waiting"', async () => {
    const { container } = await renderReport(
      report({ identity: { ...report().identity, recorded_modalities: ['gpr'], declared_sensor_type: 'gpr' } }),
    )
    const recorded = container.querySelector('[data-recorded-modalities]')
    expect(recorded?.textContent).toBe('gpr')
    const text = container.textContent?.toLowerCase() ?? ''
    for (const forbidden of ['only', 'incomplete', 'waiting']) {
      expect(text).not.toContain(forbidden)
    }
  })

  it('names two recorded modalities verbatim, never fused/multi-modal/aligned', async () => {
    const { container } = await renderReport(
      report({
        identity: {
          ...report().identity,
          modality: null,
          recorded_modalities: ['gpr', 'lidar'],
          declared_sensor_type: 'gpr',
        },
      }),
    )
    const recorded = container.querySelector('[data-recorded-modalities]')
    expect(recorded?.textContent).toBe('gpr, lidar')
    const text = container.textContent?.toLowerCase() ?? ''
    for (const forbidden of ['fused', 'multi-modal', 'multimodal', 'aligned', 'ready for fusion']) {
      expect(text).not.toContain(forbidden)
    }
  })

  it('shows an explicit absence for an empty composition, never a synthetic gpr, while the declaration still shows', async () => {
    const { container } = await renderReport(
      report({
        identity: {
          ...report().identity,
          modality: null,
          recorded_modalities: [],
          declared_sensor_type: 'gpr',
        },
      }),
    )
    expect(container.querySelector('[data-recorded-modalities]')).toBeNull()
    expect(container.textContent).toContain('no survey frame records a modality')
    // The declaration is a separate fact and is not withheld.
    const declaredField = Array.from(container.querySelectorAll('dt')).find(
      (dt) => dt.textContent === 'Declared sensor',
    )
    expect(declaredField?.nextElementSibling?.textContent).toBe('gpr')
  })

  it('follows the frames even when the declaration disagrees, without correcting it', async () => {
    const { container } = await renderReport(
      report({
        identity: {
          ...report().identity,
          modality: null,
          recorded_modalities: ['gpr', 'lidar'],
          declared_sensor_type: 'gpr',
        },
      }),
    )
    const declaredField = Array.from(container.querySelectorAll('dt')).find(
      (dt) => dt.textContent === 'Declared sensor',
    )
    expect(declaredField?.nextElementSibling?.textContent).toBe('gpr')
    expect(container.querySelector('[data-recorded-modalities]')?.textContent).toBe('gpr, lidar')
  })
})

describe('quality', () => {
  it('shows the dimensions behind the score', async () => {
    const { container } = await renderReport()
    expect(container.querySelector('[data-dimension="coordinate_integrity"]')).toBeTruthy()
  })

  it('renders an unmeasured dimension as not measured, never as zero', async () => {
    const { container } = await renderReport()
    const dimension = container.querySelector('[data-dimension="signal_quality"]')
    expect(dimension?.textContent).toContain('not measured')
    expect(dimension?.textContent).not.toContain('0%')
  })

  it('flags a stale stored score instead of hiding it', async () => {
    const stale = report()
    stale.quality = { ...stale.quality, computed_score: 0.8, stored_score: 0.3, score_is_stale: true }
    const { container } = await renderReport(stale)
    expect(container.querySelector('[data-stale-score]')?.textContent).toContain(
      'changed after it was last scored',
    )
  })
})

describe('candidates are never detections', () => {
  it('says no analysis has been run when none has, in the backend’s words', async () => {
    const { container } = await renderReport()
    // The wording is the backend's `status_reason`, not this component's: the
    // report must not paraphrase a limitation it did not decide.
    expect(container.textContent).toContain(
      'candidate generation has not been run for this dataset',
    )
    expect(container.textContent).toContain('a candidate generation run')
  })

  it('describes candidates as candidate regions and carries the note', async () => {
    const analysed = report()
    analysed.candidates = {
      ...analysed.candidates,
      candidate_count: 12,
      analysed: true,
      frames_with_candidates: ['line1.sgy'],
      shape_classes: { compact: 8, elongated: 4 },
      evidence_available: true,
      status: 'available',
      status_reason: 'generated from 1 survey line(s)',
      missing: [],
      method: 'ring_local_anomaly_connected_components',
      method_version: '1.0.0',
      localisation_breakdown: { trace_relative: 12 },
      depth_breakdown: { unavailable: 12 },
    }
    const { container } = await renderReport(analysed)
    expect(container.textContent).toContain('Candidate regions')
    expect(container.querySelector('[data-candidate-note]')?.textContent).toContain(
      'not detected objects',
    )
    expect(container.querySelector('[data-classification-status]')?.textContent).toBe(
      'BLOCKED',
    )
  })

  it('survives a report payload stored before candidate provenance existed', async () => {
    // A stored report from an earlier version carries none of the Stage 13
    // fields. The page must degrade to "not stated", never crash.
    const old = report()
    old.candidates = {
      candidate_count: 12,
      analysed: true,
      frames_with_candidates: ['line1.sgy'],
      shape_classes: { compact: 12 },
      evidence_available: true,
      classified_object_count: 0,
      note: 'Candidates are anomalous regions, not detected objects.',
    } as unknown as typeof old.candidates

    const { container } = await renderReport(old)
    expect(container.textContent).toContain('Candidate regions')
    expect(container.querySelector('[data-classification-status]')?.textContent).toBe(
      'BLOCKED',
    )
  })

  it('never uses detection language anywhere on the page', async () => {
    const analysed = report()
    analysed.candidates = { ...analysed.candidates, analysed: true, candidate_count: 12 }
    const { container } = await renderReport(analysed)
    const text = (container.textContent ?? '').toLowerCase()
    for (const claim of [
      'pipe detected',
      'object detected',
      'objects found',
      'confirmed',
      'identified as',
    ]) {
      expect(text).not.toContain(claim)
    }
  })
})

describe('the component computes nothing', () => {
  it('derives no score, coordinate or depth of its own', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    const source = readFileSync(join(__dirname, 'dataset-report.tsx'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, ' ')
      .replace(/\/\/[^\n]*/g, ' ')

    // No arithmetic on scientific quantities: the backend owns every one.
    for (const forbidden of ['Math.', 'velocity', 'toFixed(', '* 0.', '/ 2']) {
      expect(source).not.toContain(forbidden)
    }
  })

  it('imports no 3D engine', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    for (const file of ['dataset-report.tsx', 'readiness.tsx']) {
      const source = readFileSync(join(__dirname, file), 'utf8')
      expect(source).not.toMatch(/from ['"]three|@react-three/)
    }
  })
})

describe('recomputing a stale score', () => {
  it('offers the action only when the score is stale', async () => {
    const fresh = await renderReport()
    expect(fresh.container.querySelector('[data-action="rescore"]')).toBeNull()

    const stale = report()
    stale.quality = { ...stale.quality, stored_score: 0.3, computed_score: 0.8, score_is_stale: true }
    const { container } = await renderReport(stale)
    expect(container.querySelector('[data-action="rescore"]')).toBeTruthy()
  })

  it('says it is not reprocessing', async () => {
    const stale = report()
    stale.quality = { ...stale.quality, stored_score: 0.3, computed_score: 0.8, score_is_stale: true }
    const { container } = await renderReport(stale)
    const text = container.textContent ?? ''
    // The distinction that makes this safe to offer as a button at all.
    expect(text).toContain('Only the derived score is recomputed')
    expect(text).toContain('this is not reprocessing')
  })
})
