/**
 * Where the frontend looks for the backend.
 *
 * This is one constant, and it was wrong for long enough that
 * `NEXT_PUBLIC_SUBTERRA_API=http://localhost:8001` turned into a documented
 * step people were expected to remember. A default that every developer has to
 * override is not a default. The interesting test is therefore not "does the
 * constant equal a string" but "does it still agree with the deployment it is
 * supposed to describe" -- so the second test reads `docker-compose.yml` and
 * derives the port, and will fail if either side moves again.
 *
 * ENVIRONMENT ISOLATION. `API_BASE` is evaluated once when the module is first
 * imported, so each case needs a fresh module registry (`vi.resetModules()`)
 * and its own value of the variable. Every case restores the variable to
 * whatever it was on entry -- including the case where it was absent, which
 * must be deleted rather than set to the string "undefined". Vitest gives each
 * test FILE its own module registry, so the resets here cannot reach the other
 * suites that import this module.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

const VARIABLE = 'NEXT_PUBLIC_SUBTERRA_API'
const ORIGINAL = process.env[VARIABLE]

/** Import `API_BASE` afresh with the variable set, or genuinely absent. */
async function apiBaseWith(value: string | undefined): Promise<string> {
  if (value === undefined) {
    delete process.env[VARIABLE]
  } else {
    process.env[VARIABLE] = value
  }
  vi.resetModules()
  const { API_BASE } = await import('./api')
  return API_BASE
}

afterEach(() => {
  if (ORIGINAL === undefined) {
    delete process.env[VARIABLE]
  } else {
    process.env[VARIABLE] = ORIGINAL
  }
  vi.resetModules()
})

describe('the default API base URL', () => {
  it('is the port docker compose publishes, with nothing configured', async () => {
    expect(await apiBaseWith(undefined)).toBe('http://localhost:8001')
  })

  it('matches the port docker-compose.yml actually publishes', async () => {
    // Derived, not repeated: this is the assertion that catches the drift
    // rather than restating one side of it.
    const compose = readFileSync(join(__dirname, '..', '..', 'docker-compose.yml'), 'utf8')
    const apiService = compose.split(/^\s{2}api:/m)[1] ?? ''
    const published = apiService.match(/"(\d+):(\d+)"/)

    expect(published, 'no published port found for the api service').not.toBeNull()
    const hostPort = published![1]

    expect(await apiBaseWith(undefined)).toBe(`http://localhost:${hostPort}`)
  })

  it('does not need an override to reach the backend', async () => {
    // The point of the change: the documented workaround is no longer needed,
    // and the configuration that gets verified is the one shipped by default.
    expect(await apiBaseWith(undefined)).not.toBe('http://localhost:8000')
  })
})

describe('an explicit NEXT_PUBLIC_SUBTERRA_API', () => {
  it('wins over the default', async () => {
    expect(await apiBaseWith('https://subterra.example.com')).toBe(
      'https://subterra.example.com',
    )
  })

  it('still supports the same-origin deployment, which sets an empty base', async () => {
    // A reverse-proxied deployment serves the API under the same origin and
    // wants relative URLs. An empty string is a deliberate configuration, so
    // `??` (not `||`) is what keeps it from being replaced by the default.
    expect(await apiBaseWith('')).toBe('')
  })

  it('is read at module load, not baked in at build time by this test', async () => {
    expect(await apiBaseWith('http://one.example')).toBe('http://one.example')
    expect(await apiBaseWith('http://two.example')).toBe('http://two.example')
  })
})

describe('environment isolation', () => {
  it('leaves the variable exactly as it found it', async () => {
    await apiBaseWith('http://scratch.example')
    // `afterEach` has not run yet, so restore by hand and check the invariant
    // the hook relies on: absent stays absent, rather than becoming a string.
    if (ORIGINAL === undefined) {
      delete process.env[VARIABLE]
      expect(VARIABLE in process.env).toBe(false)
    } else {
      process.env[VARIABLE] = ORIGINAL
      expect(process.env[VARIABLE]).toBe(ORIGINAL)
    }
  })
})
