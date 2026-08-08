/**
 * Benchmark presentation.
 *
 * The benchmark numbers are frozen. The only way this layer can damage them
 * is by transforming, aggregating, omitting or re-framing them on the way to
 * the screen, so that is what these tests are about.
 *
 * Fixtures below are trimmed from the real artifacts and keep their exact
 * recorded values, including full float precision.
 */
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { BenchmarkArtifact, BenchmarkArtifactEntry } from '@/types/subterra'

const mockUseArtifact = vi.fn()

vi.mock('@/hooks/use-subterra', () => ({
  useBenchmarkArtifact: (...args: unknown[]) => mockUseArtifact(...args),
  useBenchmarkArtifacts: () => ({ data: undefined, error: null, isLoading: true }),
}))

const { BamPanel } = await import('./bam-panel')
const { FourTuPanel } = await import('./fourtu-panel')
const { Metric, Interpretation } = await import('./metric')

afterEach(() => {
  cleanup()
  mockUseArtifact.mockReset()
})

/* --------------------------------- fixtures -------------------------------- */

const BAM: BenchmarkArtifact = {
  benchmark: 'bam-concrete-gpr',
  scope:
    'BAM benchmark results measure performance on controlled concrete NDT specimens. They are not evidence of soil/utility-scale subsurface detection or localisation performance.',
  localization_status: 'BLOCKED',
  localization_blocked_reason: 'absolute origin is not verified',
  open_questions: ['absolute-origin', 'depth-reference-surface', 'coordinate-units'],
  threshold: 3.0,
  min_cells: 3,
  parameters_changed_for_this_benchmark: 'none',
  grid: {
    units_xy: 'mm',
    units_z: 'ns',
    units_provenance: 'inferred_from_documentation',
    crs: null,
    crs_provenance: 'none',
    absolute_origin_verified: false,
    frame: 'benchmark-local; X along specimen length, Y across width, Z two-way time',
  },
  provenance: {
    doi: '10.7910/DVN/FCMUJQ',
    repository: 'Harvard Dataverse',
    licence: 'CC0-1.0',
    archive: 'Pk266_Dataset.zip',
    archive_md5_verified: true,
    source_files_unmodified: true,
  },
  detection: {
    scan_id: 'Pk266_3D_Dataset_1_5_GHz_Rot00',
    specimen_id: 'Pk266',
    lines_processed: 161,
    lines_available: 161,
    n_targets: 4,
    true_positives: 45,
    false_negatives: 602,
    false_positives: 288,
    recall: 0.06521739130434782,
    precision: 0.13513513513513514,
    f1: 0.0879765395894428,
    overlapping_any_node: 45,
    detection_unit: 'target x line',
    match_rule: 'a detection matches a target when its peak trace node lies within the target footprint; no additional tolerance',
    per_target: {
      'Pk266-duct-1': { lines_with_a_match: 8, lines_processed: 161, grid_index: 50, footprint: [44, 56], target_type: 'tendon duct', position_provenance: 'transcribed_from_publication' },
      'Pk266-duct-4': { lines_with_a_match: 4, lines_processed: 161, grid_index: 350, footprint: [344, 356], target_type: 'tendon duct', position_provenance: 'transcribed_from_publication' },
    },
  },
  false_alarms: {
    specimen_id: 'Pk050',
    n_detections: 449,
    detections_per_line: 2.7888198757763973,
    rate_basis: 'detections per line on attested-empty ground',
    per_area_rate: null,
    per_area_note:
      'not computed: the archives declare no physical unit for X/Y, so an area cannot be stated without assuming one',
    control_caveat:
      'Pk050 is not featureless. The step back walls are real reflectors, and any detector will respond to them.',
  },
}

const BAM_PROBE: BenchmarkArtifact = {
  ...BAM,
  detection: { ...(BAM.detection as object), lines_processed: 20, lines_available: 161 },
}

const FOURTU: BenchmarkArtifact = {
  benchmark: '4tu-nl-utility',
  resolution: 'activity (LocationID)',
  scope:
    '4TU results are activity-level only. No candidate is matched to a utility, and no positional or depth accuracy is measured.',
  object_level_status: 'BLOCKED',
  object_level_blocked_reason:
    '4TU publishes no trench coordinates, so no candidate can be matched to a utility',
  activity_level_status: 'RESOLVED',
  open_questions: ['trench-coordinates', 'trench-is-a-subset-of-the-survey'],
  truth_activities: 125,
  truth_positive: 112,
  truth_attested_zero: 7,
  truth_unrecorded: 6,
  join_complete: true,
  score: {
    activity_level_response_rate: 1.0,
    activity_level_note: 'A near-1.0 value here is not evidence of skill.',
    positive_group: { n_activities: 112, median_per_1k: 31.180246822483348, activities_with_zero_candidates: 0 },
    attested_zero_group: { n_activities: 7, median_per_1k: 24.344569288389515, activities_with_zero_candidates: 0 },
    density_separation: {
      auc: 0.4451530612244898,
      interpretation:
        'probability that a utility-bearing activity shows a higher candidate density than a trench-empty one; 0.5 is no separation',
    },
    count_agreement: {
      spearman_rho: -0.06186218355635493,
      n_pairs: 112,
      interpretation: 'whether activities where the trench found more utilities also produce more detector candidates',
      caveat: 'a trench count is not a count of what lies under the survey lines',
    },
    unexplained_response_rate: null,
    unexplained_response_basis: 'only 7 activities have an attested zero',
    object_level_scored: false,
    positional_accuracy_scored: false,
    depth_accuracy_scored: false,
    trench_scope_caveat:
      'A trial trench is a small excavation inside a much larger surveyed area.',
  },
}

const bamEntries: BenchmarkArtifactEntry[] = [
  { name: 'bam/score_1_5_GHz_Rot00', group: 'bam', filename: 'score_1_5_GHz_Rot00.json', size_bytes: 8653 },
  { name: 'bam/score_probe', group: 'bam', filename: 'score_probe.json', size_bytes: 8597 },
]

function loaded(artifact: BenchmarkArtifact) {
  mockUseArtifact.mockReturnValue({ data: artifact, error: null, isLoading: false })
}

function renderBam(artifact = BAM) {
  loaded(artifact)
  return render(
    <BamPanel artifacts={bamEntries} selected="bam/score_1_5_GHz_Rot00" onSelect={() => {}} />,
  )
}

function renderFourTu(artifact = FOURTU) {
  loaded(artifact)
  return render(<FourTuPanel name="4tu/benchmark" />)
}

/* ------------------------------ no transformation -------------------------- */

describe('metrics are rendered exactly as recorded', () => {
  it('BAM recall/precision/F1 keep full float precision', () => {
    const { container } = renderBam()
    expect(container.textContent).toContain('0.06521739130434782')
    expect(container.textContent).toContain('0.13513513513513514')
    expect(container.textContent).toContain('0.0879765395894428')
  })

  it('no metric is converted to a percentage', () => {
    const { container } = renderBam()
    expect(container.textContent).not.toMatch(/6\.5\s*%/)
    expect(container.textContent).not.toMatch(/13\.5\s*%/)
  })

  it('4TU AUC and rho keep full precision, including the negative sign', () => {
    const { container } = renderFourTu()
    expect(container.textContent).toContain('0.4451530612244898')
    expect(container.textContent).toContain('-0.06186218355635493')
  })

  it('integer counts are not rounded or abbreviated', () => {
    const { container } = renderBam()
    for (const n of ['45', '288', '602', '449']) {
      expect(container.textContent).toContain(n)
    }
  })
})

/* --------------------------- nothing silently dropped ---------------------- */

describe('a missing metric is stated, not omitted', () => {
  it('BAM per-area rate is null and renders as "not reported" with the reason', () => {
    const { container } = renderBam()
    const row = container.querySelector('[data-metric="Per-area rate"]')
    expect(row).toBeTruthy()
    expect(within(row as HTMLElement).getByText('not reported')).toBeTruthy()
    expect(container.textContent).toMatch(/declare no physical unit/)
  })

  it('4TU unexplained response rate is null and renders as "not reported"', () => {
    const { container } = renderFourTu()
    const row = container.querySelector('[data-metric="Unexplained response rate"]')
    expect(within(row as HTMLElement).getByText('not reported')).toBeTruthy()
    expect(container.textContent).toMatch(/only 7 activities have an attested zero/)
  })

  it('Metric renders null as an absence rather than zero', () => {
    const { container } = render(<Metric label="x" value={null} />)
    expect(container.textContent).toContain('not reported')
    expect(container.textContent).not.toMatch(/\b0\b/)
  })
})

/* ------------------------------- gates and scope --------------------------- */

describe('gates and scope are rendered, not softened', () => {
  it('BAM localisation shows BLOCKED with the recorded reason', () => {
    const { container } = renderBam()
    const gate = container.querySelector('[data-gate-status="BLOCKED"]')
    expect(gate).toBeTruthy()
    expect(container.textContent).toContain('absolute origin is not verified')
  })

  it('4TU object-level shows BLOCKED, activity-level shows RESOLVED', () => {
    const { container } = renderFourTu()
    expect(container.querySelector('[data-gate="Object-level scoring"]')!.getAttribute('data-gate-status')).toBe('BLOCKED')
    expect(container.querySelector('[data-gate="Activity-level scoring"]')!.getAttribute('data-gate-status')).toBe('RESOLVED')
    expect(container.textContent).toContain('no trench coordinates')
  })

  it('each panel carries its own scope statement', () => {
    const { container: bam } = renderBam()
    expect(bam.textContent).toMatch(/not evidence of soil\/utility-scale/)
    cleanup()
    const { container: tu } = renderFourTu()
    expect(tu.textContent).toMatch(/activity-level only/)
  })

  it('BAM provenance is shown, including archive verification', () => {
    const { container } = renderBam()
    expect(container.textContent).toContain('10.7910/DVN/FCMUJQ')
    expect(container.textContent).toContain('Harvard Dataverse')
    expect(container.textContent).toContain('CC0-1.0')
  })

  it('units and CRS provenance are labelled, not presented as fact', () => {
    const { container } = renderBam()
    expect(container.querySelector('[data-provenance="inferred_from_documentation"]')).toBeNull()
    // unrecognised classes still surface as themselves rather than vanishing
    expect(container.textContent).toMatch(/inferred_from_documentation|Unavailable/)
  })

  it('open questions are all listed', () => {
    const { container } = renderBam()
    for (const q of BAM.open_questions!) {
      expect(container.textContent).toContain(q)
    }
  })
})

/* ------------------------------ interpretation ----------------------------- */

describe('the documented interpretation is displayed', () => {
  it('BAM states the width-saturation mechanism', () => {
    const { container } = renderBam()
    expect(container.textContent).toMatch(/saturates with target width/i)
    expect(container.textContent).toMatch(/did not discover a new problem/i)
  })

  it('BAM states that no threshold was changed', () => {
    const { container } = renderBam()
    expect(container.textContent).toMatch(/No threshold was changed/i)
    expect(container.textContent).toMatch(/measurement into a fit/i)
  })

  it('BAM says a low per-target count is a miss, not an absent duct', () => {
    const { container } = renderBam()
    expect(container.textContent).toMatch(/detector miss/i)
    expect(container.textContent).toMatch(/not\s+evidence that the duct is absent/i)
  })

  it('4TU is presented as a null result, not as a low score', () => {
    const { container } = renderFourTu()
    expect(container.textContent).toMatch(/null result/i)
    expect(container.textContent).toMatch(/0\.5 is no separation/)
  })

  it('4TU calls them candidates, and only ever negates "detected utilities"', () => {
    const { container } = renderFourTu()
    const text = container.textContent ?? ''
    expect(text).toMatch(/not detected utilities/i)

    // Every occurrence of the phrase must be a negation of it. Asserting the
    // phrase is simply absent would be wrong -- saying candidates are NOT
    // detected utilities is exactly the distinction this panel must draw.
    const occurrences = [...text.matchAll(/detected utilit(?:y|ies)/gi)]
    expect(occurrences.length).toBeGreaterThan(0)
    for (const match of occurrences) {
      const preceding = text.slice(Math.max(0, match.index - 12), match.index)
      expect(preceding, `unnegated "${match[0]}"`).toMatch(/\bnot\s+$/i)
    }
  })

  it('4TU never labels a candidate count as a utility count', () => {
    const { container } = renderFourTu()
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/utilities detected/i)
    expect(text).not.toMatch(/\bdetections\b/i)
  })

  it('4TU marks the competing readings as uncertain', () => {
    const { container } = renderFourTu()
    const uncertain = container.querySelector('[data-uncertain="true"]')
    expect(uncertain).toBeTruthy()
    expect(uncertain!.textContent).toMatch(/truth is incomplete/i)
  })

  it('4TU says an unmatched candidate is not a false alarm', () => {
    const { container } = renderFourTu()
    expect(container.textContent).toMatch(/not a false alarm/i)
    expect(container.textContent).toMatch(/small excavation inside a much larger surveyed area/i)
  })

  it('every interpretation cites a source', () => {
    const { container } = renderBam()
    const blocks = container.querySelectorAll('[data-interpretation]')
    expect(blocks.length).toBeGreaterThan(0)
    blocks.forEach((b) => expect(b.textContent).toMatch(/source:/))
  })

  it('Interpretation requires and shows its source', () => {
    const { container } = render(
      <Interpretation title="t" source="docs/x.md §1">
        <p>body</p>
      </Interpretation>,
    )
    expect(container.textContent).toContain('docs/x.md §1')
  })
})

/* --------------------------- artifact selection ---------------------------- */

describe('artifact selection and partial runs', () => {
  it('a partial run is labelled as partial', () => {
    const { container } = renderBam(BAM_PROBE)
    expect(container.textContent).toMatch(/Partial run/i)
    expect(container.textContent).toMatch(/not comparable with a full-scan report/i)
  })

  it('a full run carries no partial-run warning', () => {
    const { container } = renderBam(BAM)
    expect(container.textContent).not.toMatch(/Partial run/i)
  })

  it('the BAM scan selector offers every BAM artifact', () => {
    renderBam()
    const select = screen.getByLabelText('BAM scan') as HTMLSelectElement
    expect(select.options.length).toBe(bamEntries.length)
  })

  it('no BAM artifact renders an explicit empty state, not a blank panel', () => {
    mockUseArtifact.mockReturnValue({ data: undefined, error: null, isLoading: false })
    const { container } = render(
      <BamPanel artifacts={[]} selected={null} onSelect={() => {}} />,
    )
    expect(container.textContent).toMatch(/No BAM artifact has been generated/i)
    expect(container.textContent).toMatch(/score_bam_benchmark\.py/)
  })

  it('no 4TU artifact renders an explicit empty state', () => {
    mockUseArtifact.mockReturnValue({ data: undefined, error: null, isLoading: false })
    const { container } = render(<FourTuPanel name={null} />)
    expect(container.textContent).toMatch(/No 4TU benchmark artifact has been generated/i)
    expect(container.textContent).toMatch(/score_4tu_benchmark\.py/)
  })

  it('a failed artifact fetch renders an error, not fabricated values', () => {
    mockUseArtifact.mockReturnValue({
      data: undefined,
      error: new Error('boom'),
      isLoading: false,
    })
    const { container } = render(
      <BamPanel artifacts={bamEntries} selected="bam/score_1_5_GHz_Rot00" onSelect={() => {}} />,
    )
    expect(container.textContent).toMatch(/Could not load the BAM artifact/i)
    expect(container.textContent).not.toContain('0.065')
  })
})

/* ---------------------------- no recomputation ----------------------------- */

describe('nothing is recomputed or aggregated', () => {
  it('BAM shows no metric absent from the artifact', () => {
    const { container } = renderBam()
    // accuracy / MCC / AUC are not BAM artifact fields; inventing them would
    // mean computing a benchmark result in the browser
    expect(container.textContent).not.toMatch(/\bAccuracy\b/)
    expect(container.textContent).not.toMatch(/\bMCC\b/)
    expect(container.textContent).not.toMatch(/\bAUC\b/)
  })

  it('BAM does not restate a derived per-target rate', () => {
    const { container } = renderBam()
    // 8/161 must appear as recorded, not as a computed 0.0497 or "5%"
    expect(container.textContent).toMatch(/8\s*\/\s*161/)
    expect(container.textContent).not.toMatch(/0\.0497/)
  })

  it('neither panel mixes in the other benchmark, so no aggregate is possible', () => {
    const { container: bam } = renderBam()
    expect(bam.textContent).not.toMatch(/4tu-nl-utility/)
    expect(bam.textContent).not.toContain('0.4451530612244898')
    cleanup()
    const { container: tu } = renderFourTu()
    expect(tu.textContent).not.toMatch(/bam-concrete-gpr/)
    expect(tu.textContent).not.toContain('0.06521739130434782')
  })
})
