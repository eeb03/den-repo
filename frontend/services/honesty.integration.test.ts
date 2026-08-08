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
import { provenanceMeta } from '@/lib/provenance'
import { asProvenanceClass } from '@/lib/provenance'

let live = false

beforeAll(async () => {
  try {
    live = (await fetch(`${API_BASE}/api/health`)).ok
  } catch {
    live = false
  }
  if (!live) console.warn(`[skip] Subterra API not reachable at ${API_BASE}`)
})

const liveIt = (name: string, fn: () => Promise<void>, timeout = 30_000) =>
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
