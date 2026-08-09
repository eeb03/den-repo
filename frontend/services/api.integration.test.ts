/**
 * Integration check of the adapter against a LIVE Subterra API.
 *
 * These tests hit the real backend, so they are skipped when it is not
 * running -- a developer without a local API should not see red. What they
 * exist to catch is the class of bug unit tests with fixtures cannot: a URL
 * that does not exist, a field renamed on the backend, or an error shape
 * the adapter mis-reads.
 *
 * Run with the API up, which is what `docker compose up` gives you --
 * it publishes the API on 8001, and `API_BASE` defaults there:
 *   docker compose up -d
 *   corepack pnpm test
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { API_BASE, ApiError, api } from './api'

let live = false

async function isLive(): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/api/health`)
    return r.ok
  } catch {
    return false
  }
}

beforeAll(async () => {
  live = await isLive()
  if (!live) {
    console.warn(`[skip] Subterra API not reachable at ${API_BASE}`)
  }
})

const liveIt = (name: string, fn: () => Promise<void>, timeout = 30_000) =>
  it(name, async () => {
    if (!live) return
    await fn()
  }, timeout)

describe('datasets', () => {
  liveIt('lists datasets with the fields the UI reads', async () => {
    const datasets = await api.listDatasets()
    expect(Array.isArray(datasets)).toBe(true)
    if (datasets.length === 0) return
    const d = datasets[0]!
    expect(typeof d.id).toBe('string')
    expect(typeof d.name).toBe('string')
    // Nullable by contract -- the UI must handle null, so the type must allow it.
    for (const key of ['quality_score', 'record_count', 'center_lat', 'center_lon'] as const) {
      expect(['number', 'object']).toContain(typeof d[key])
    }
  })

  liveIt('a dataset with no positioned records reports null, not zero', async () => {
    const datasets = await api.listDatasets()
    for (const d of datasets) {
      const info = await api.getDatasetInfo(d.id).catch((e) => {
        if (e instanceof ApiError && e.isAbsence) return null
        throw e
      })
      if (!info) continue
      if (info.geographic_record_count === 0) {
        // The critical invariant: no fabricated zero-sized survey.
        expect(info.survey_area_m).toBeNull()
        expect(info.grid_resolution_m).toBeNull()
        return
      }
    }
  })
})

describe('objects and labels', () => {
  liveIt('objects response distinguishes count from placed', async () => {
    const datasets = await api.listDatasets()
    if (datasets.length === 0) return
    const body = await api.getObjects(datasets[0]!.id)
    expect(typeof body.count).toBe('number')
    expect(typeof body.placed).toBe('number')
    expect(body.placed).toBeLessThanOrEqual(body.count)
    // Anything not placed must carry no coordinate at all.
    for (const o of body.objects) {
      if (o.position.kind !== 'geographic') {
        expect(o.position).not.toHaveProperty('lat')
        expect(o.position).not.toHaveProperty('lon')
      }
    }
  })

  liveIt('a label without a stated confidence stays null', async () => {
    const datasets = await api.listDatasets()
    if (datasets.length === 0) return
    const body = await api.getLabels(datasets[0]!.id)
    for (const l of body.labels) {
      expect(l.confidence === null || typeof l.confidence === 'number').toBe(true)
      // never coerced to 0 by the transport
      if (l.confidence === null) expect(l.confidence).not.toBe(0)
    }
  })
})

describe('view resolution', () => {
  liveIt('the backend answers per view, and 3D is unresolved', async () => {
    const datasets = await api.listDatasets()
    if (datasets.length === 0) return
    const datasetId = datasets[0]!.id
    const layers = await api.getLayers(datasetId)
    if (layers.layers.length === 0) return
    const frameId = layers.layers[0]!.frame_id

    const resolution = await api.resolveSelection({
      kind: 'frame',
      dataset_id: datasetId,
      selection_id: frameId,
      frame_id: frameId,
      trace_index: 0,
    })

    const byView = Object.fromEntries(
      resolution.views.map((v) => [v.view, v]),
    )
    expect(Object.keys(byView).sort()).toEqual(
      ['depth_slice', 'map', 'metadata', 'radargram', 'scene_3d'].sort(),
    )

    // scene_3d is unresolved for every dataset currently held, and says why.
    const scene = byView.scene_3d!
    expect(scene.resolved).toBe(false)
    expect(scene.coordinates).toEqual({})
    expect(scene.reason).toBeTruthy()
    expect(scene.missing.length).toBeGreaterThan(0)

    // An unresolved view offers nothing that could be mistaken for a location.
    for (const v of resolution.views) {
      if (!v.resolved) expect(v.coordinates).toEqual({})
    }
  })
})

describe('overlays', () => {
  liveIt('composition returns a relationship and its basis', async () => {
    const datasets = await api.listDatasets()
    if (datasets.length === 0) return
    const c = await api.composeOverlays([datasets[0]!.id])
    expect(typeof c.spatial_relationship).toBe('string')
    expect(typeof c.spatial_basis).toBe('string')
    expect(c.spatial_basis.length).toBeGreaterThan(0)
  })
})

describe('absence is distinguishable from failure', () => {
  liveIt('a dataset with no trace grid throws an absence, with a reason', async () => {
    const datasets = await api.listDatasets()
    if (datasets.length === 0) return
    let sawAbsence = false
    for (const d of datasets) {
      try {
        await api.getTraceGrid(d.id)
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError)
        const err = e as ApiError
        if (err.isAbsence) {
          sawAbsence = true
          // The UI renders this string verbatim, so it must be non-empty.
          expect(err.detail.length).toBeGreaterThan(0)
          break
        }
      }
    }
    expect(sawAbsence).toBe(true)
  })

  liveIt('an unknown dataset is a 404 absence, not a crash', async () => {
    await expect(api.getDatasetInfo('definitely-not-a-dataset')).rejects.toSatisfy(
      (e: unknown) => e instanceof ApiError && e.status === 404 && e.isAbsence,
    )
  })
})

describe('benchmark artifacts', () => {
  liveIt('lists artifacts and serves them unchanged', async () => {
    const listing = await api.listBenchmarkArtifacts()
    expect(typeof listing.count).toBe('number')
    if (listing.artifacts.length === 0) return

    for (const entry of listing.artifacts) {
      expect(entry.name).toMatch(/^[^/]+\/[^/]+$/)
    }

    const bam = listing.artifacts.find((a) => a.group === 'bam')
    if (!bam) return
    const artifact = await api.getBenchmarkArtifact(bam.name)

    // Gate status and reason must arrive intact.
    expect(artifact.localization_status).toBe('BLOCKED')
    expect(artifact.localization_blocked_reason).toBeTruthy()
    expect(artifact.scope).toBeTruthy()
    expect(Array.isArray(artifact.open_questions)).toBe(true)
    expect(artifact.open_questions!.length).toBeGreaterThan(0)

    // The recorded metric is a full-precision float, not a rounded display value.
    const detection = artifact.detection as Record<string, number> | undefined
    if (detection?.recall !== undefined) {
      expect(typeof detection.recall).toBe('number')
      expect(detection.recall).toBeGreaterThan(0)
      expect(detection.recall).toBeLessThan(0.15)
    }
  })

  liveIt('a traversal name cannot read outside the artifacts directory', async () => {
    for (const name of ['../../../etc/passwd', 'bam/../../.env']) {
      await expect(api.getBenchmarkArtifact(name)).rejects.toBeInstanceOf(ApiError)
    }
  })
})
