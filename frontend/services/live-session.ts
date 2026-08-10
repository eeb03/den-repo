/**
 * Signing the live-backend integration tests in.
 *
 * WHY THIS EXISTS. `api.integration.test.ts` and `honesty.integration.test.ts`
 * were written before Subterra had authentication. Once dataset routes started
 * requiring a session they answered 401 — but nobody saw it, because the
 * frontend's API_BASE still pointed at port 8000 while compose published 8001,
 * so `isLive()` always failed and every case skipped itself. Two suites'
 * worth of coverage had been quietly dead. Correcting the port default made
 * them reachable again and the 401s visible.
 *
 * WHY A FETCH SHIM. The session is an HTTP-only cookie and Node's `fetch` has
 * no cookie jar, so `credentials: 'include'` does nothing here — the browser
 * behaviour these tests rely on has no equivalent in the test runner. The
 * smallest honest fix is to attach the cookie to requests aimed at the API,
 * and only those. This is test-only: no production code changes, and the
 * adapter under test is exercised exactly as it ships.
 *
 * ONE ACCOUNT, NOT ONE PER RUN. Login is attempted first and registration only
 * happens if that fails, so a developer's database accumulates a single
 * integration user rather than one per test run. The datasets these tests read
 * are the system reference corpora, which any signed-in account may read.
 */
const EMAIL = 'integration@subterra.test'
const PASSWORD = 'integration-suite-password'

function cookieFrom(response: Response): string {
  const headers = response.headers as Headers & { getSetCookie?: () => string[] }
  const raw = headers.getSetCookie?.() ?? [response.headers.get('set-cookie') ?? '']
  return raw
    .filter(Boolean)
    .map((entry) => entry.split(';')[0])
    .join('; ')
}

async function post(apiBase: string, path: string): Promise<Response> {
  return fetch(`${apiBase}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  })
}

/**
 * Establishes a session and makes every later request carry it.
 *
 * Returns false when the backend is up but a session could not be established;
 * the caller then skips rather than reporting failures that are about the test
 * environment instead of about the API.
 */
export async function signInForLiveTests(apiBase: string): Promise<boolean> {
  let response = await post(apiBase, '/api/auth/login')
  if (!response.ok) {
    // First run against this database: create the account, which also signs in.
    response = await post(apiBase, '/api/auth/register')
  }
  if (!response.ok) return false

  const cookie = cookieFrom(response)
  if (!cookie) return false

  const original = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : (input as Request).url
    if (url.startsWith(apiBase)) {
      return original(input, { ...init, headers: { ...(init?.headers ?? {}), cookie } })
    }
    return original(input, init)
  }) as typeof globalThis.fetch

  return true
}
