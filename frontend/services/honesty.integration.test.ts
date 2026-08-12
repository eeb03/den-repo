// @vitest-environment node
//
// NOT jsdom. These are API contract tests with no DOM, and jsdom follows the
// browser rule that `set-cookie` is a forbidden response header -- it strips it,
// so the session cookie the sign-in needs is invisible and every dataset call
// 401s. In a real browser the cookie jar handles this; in the test runner there
// is none, so the header has to be readable.
/**
 * Honesty guarantees that span the API/UI boundary.
 *
 * Two things the component tests cannot check, because they need the real
 * backend:
 *
 *   1. that the provenance vocabulary the UI knows is the vocabulary the
 *      backend actually publishes -- a class added server-side would
 *      otherwise reach the screen as an unstyled string nobody notices;
 *   2. that the two pre-existing UIs still work, since this project's whole
 *      premise is adding a layer beside them rather than replacing them.
 *
 * Skipped when the API is not running.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { API_BASE, ApiError, api } from './api'
import { signInForLiveTests } from './live-session'
import { provenanceMeta } from '@/lib/provenance'
import { asProvenanceClass } from '@/lib/provenance'

let live = false

beforeAll(async () => {
  try {
    live = (await fetch(`${API_BASE}/api/health`)).ok
  } catch {
    live = false
  }
  if (!live) {
    console.warn(`[skip] Subterra API not reachable at ${API_BASE}`)
    return
  }
  // Dataset routes require a session. See services/live-session.ts for why
  // this needs a shim rather than `credentials: 'include'`.
  live = await signInForLiveTests(API_BASE)
  if (!live) console.warn('[skip] Subterra API is up but a session could not be established')
})

// 120 s, not the 30 s default. EVERY live case here walks the whole corpus --
// several build a full dataset report for each of the six datasets held, and a
// report parses all of that dataset's records. Six full parses is about 28 s,
// which sits ON the default and makes these flaky rather than wrong. The cost is
// the single-entry record cache, not a regression; the timeout reflects what the
// tests actually do.
const liveIt = (name: string, fn: () => Promise<void>, timeout = 120_000) =>
  it(name, async () => {
    if (!live) return
    await fn()
  }, timeout)

/* ------------------- provenance survives API -> UI mapping ----------------- */

describe('the provenance vocabulary matches the backend', () => {
  liveIt('every class the backend publishes has UI presentation', async () => {
    const vocab = (await (
      await fetch(`${API_BASE}/api/provenance/vocabulary`)
    ).json()) as { classes: { value: string; meaning: string }[] }

    expect(vocab.classes.length).toBeGreaterThan(0)
    const missing = vocab.classes
      .map((c) => c.value)
      .filter((v) => asProvenanceClass(v) === null)
    expect(missing, `backend classes with no UI mapping: ${missing.join(', ')}`).toEqual(
      [],
    )
  })

  liveIt('the UI invents no class the backend does not publish', async () => {
    const vocab = (await (
      await fetch(`${API_BASE}/api/provenance/vocabulary`)
    ).json()) as { classes: { value: string }[] }
    const backend = new Set(vocab.classes.map((c) => c.value))
    const extra = Object.keys(provenanceMeta).filter((k) => !backend.has(k))
    expect(extra, `UI classes absent from the backend: ${extra.join(', ')}`).toEqual([])
  })

  liveIt('"unavailable" keeps its meaning: absent, not zero', async () => {
    const vocab = (await (
      await fetch(`${API_BASE}/api/provenance/vocabulary`)
    ).json()) as { classes: { value: string; meaning: string }[] }
    const unavailable = vocab.classes.find((c) => c.value === 'unavailable')
    expect(unavailable).toBeTruthy()
    // the backend states this explicitly; the UI must not soften it
    expect(unavailable!.meaning).toMatch(/not zero/i)
    expect(provenanceMeta.unavailable.meaning).toMatch(/no value exists/i)
  })

  liveIt('a real dataset\'s provenance classes all map to the UI', async () => {
    const datasets = await api.listDatasets()
    if (datasets.length === 0) return
    let checked = 0
    for (const d of datasets) {
      const body = await api.getFrameProvenance(d.id).catch((e) => {
        if (e instanceof ApiError && e.isAbsence) return null
        throw e
      })
      if (!body) continue
      for (const frame of body.frames) {
        for (const entry of frame.provenance) {
          expect(
            asProvenanceClass(entry.provenance),
            `unmapped provenance class ${entry.provenance!} on ${frame.frame_id}`,
          ).not.toBeNull()
          // the backend contract: a provenance label always carries a basis
          expect(entry.basis.length).toBeGreaterThan(0)
          checked += 1
        }
      }
    }
    expect(checked).toBeGreaterThan(0)
  })
})

/* --------------------- the pre-existing UIs still work --------------------- */

describe('the existing UIs are unaffected', () => {
  liveIt('the thin client still serves, with its panels intact', async () => {
    const r = await fetch(`${API_BASE}/client`)
    expect(r.status).toBe(200)
    const html = await r.text()
    for (const marker of ['id="map"', 'id="radargram"', 'Not on the map', '/api/views/resolve']) {
      expect(html, `thin client lost ${marker}`).toContain(marker)
    }
  })

  liveIt('the 3D viewer still serves, with all four view modes', async () => {
    const r = await fetch(`${API_BASE}/viewer`)
    expect(r.status).toBe(200)
    const html = await r.text()
    for (const mode of ['Point cloud', 'Heatmap (top-down)', 'Surface (elevation-draped)', 'B-scan']) {
      expect(html, `viewer lost the ${mode} mode`).toContain(mode)
    }
  })

  liveIt('the viewer still filters unpositioned records', async () => {
    // the guard added in the viewer fix; pinned server-side too, but a
    // regression here would silently restore null-island plotting
    const html = await (await fetch(`${API_BASE}/viewer`)).text()
    expect(html).toContain('position_kind === "geographic"')
    expect(html).toContain('excludedNoPosition')
  })
})

/* ------------------- benchmark numbers cross the wire intact ---------------- */

describe('benchmark figures are not transformed in transit', () => {
  liveIt('the served artifact equals the artifact the UI parses', async () => {
    const listing = await api.listBenchmarkArtifacts()
    const bam = listing.artifacts.find((a) => a.group === 'bam')
    if (!bam) return

    // fetch raw text and compare against the parsed object the adapter returns
    const raw = await (
      await fetch(`${API_BASE}/api/benchmark/artifacts/${bam.name}`)
    ).text()
    const viaAdapter = await api.getBenchmarkArtifact(bam.name)
    expect(viaAdapter).toEqual(JSON.parse(raw))

    // and the gate survives
    expect(viaAdapter.localization_status).toBe('BLOCKED')
    expect(viaAdapter.parameters_changed_for_this_benchmark).toBe('none')
  })

  liveIt('a full-precision metric is not rounded by the transport', async () => {
    const listing = await api.listBenchmarkArtifacts()
    const bam = listing.artifacts.find(
      (a) => a.group === 'bam' && !a.filename.includes('probe'),
    )
    if (!bam) return
    const artifact = await api.getBenchmarkArtifact(bam.name)
    const detection = artifact.detection as Record<string, number>
    // a float that would lose information under toFixed(3)
    expect(String(detection.recall).length).toBeGreaterThan(5)
  })
})

// EACH of these builds a full report for EVERY dataset held. A report loads all
// of a dataset's records, and the record cache holds one dataset at a time, so
// six reports is six full parses -- about 28 s on this corpus, which sits right
// on the default 30 s timeout and makes them flaky rather than wrong. The cost
// is a known property of the single-entry cache, not a regression; the timeout
// is raised to reflect what the tests actually do.
describe('the dataset report tells the truth about real datasets', () => {
  liveIt('never claims an absolute elevation for any dataset held', async () => {
    const datasets = await api.listDatasets()
    if (datasets.length === 0) return

    for (const d of datasets) {
      const report = await api.getDatasetReport(d.id)

      // No dataset currently held has an established vertical relationship.
      // If this ever legitimately changes, it changes because a datum was
      // declared -- and this assertion is where that should be noticed.
      expect(report.spatial.vertical.absolute_elevation_available).toBe(false)

      const vertical = report.readiness.find(
        (c) => c.capability === 'vertical_registration',
      )!
      expect(vertical.readiness).not.toBe('ready')
      expect(vertical.missing.length).toBeGreaterThan(0)
    }
  })

  liveIt('never reports a classified object, and blocks classification', async () => {
    const datasets = await api.listDatasets()
    for (const d of datasets) {
      const report = await api.getDatasetReport(d.id)
      expect(report.candidates.classified_object_count).toBe(0)

      const classification = report.readiness.find(
        (c) => c.capability === 'object_classification',
      )!
      expect(classification.readiness).toBe('blocked')
    }
  })

  liveIt('blocks 3D reconstruction for every dataset, with a reason', async () => {
    const datasets = await api.listDatasets()
    for (const d of datasets) {
      const report = await api.getDatasetReport(d.id)
      const reconstruction = report.readiness.find(
        (c) => c.capability === 'reconstruction_3d',
      )!
      expect(reconstruction.readiness).toBe('blocked')
      expect(reconstruction.reason.length).toBeGreaterThan(0)
      expect(reconstruction.missing.length).toBeGreaterThan(0)
    }
  })

  liveIt('reports no survey extent where no record carries a position', async () => {
    const datasets = await api.listDatasets()
    for (const d of datasets) {
      const report = await api.getDatasetReport(d.id)
      if (report.spatial.horizontal.positioned_record_count === 0) {
        // The (0, 0) placeholder failure, guarded at the report level.
        expect(report.spatial.geometry.bounds).toBeNull()
        expect(report.spatial.geometry.lat_span_m).toBeNull()
      }
    }
  })
})
