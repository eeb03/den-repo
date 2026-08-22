/**
 * `ApiError.detail`, for every shape FastAPI can send it as.
 *
 * A route-level `HTTPException` sends `detail` as a plain string, always
 * handled correctly. FastAPI's own request validation (a 422 for a bad
 * enum member, a missing field) sends `detail` as an ARRAY of Pydantic
 * error objects instead -- and `String()` on an array of plain objects
 * renders "[object Object]", not an explanation. Found via the sensor-type
 * picker's `other` case (slice 33); fixed generically here so it holds for
 * every endpoint's validation refusal, not just that one.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from './api'

function mockErrorResponse(status: number, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { 'content-type': 'application/json' },
      }),
    ),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('a plain string detail', () => {
  it('is rendered verbatim, the existing behaviour', async () => {
    mockErrorResponse(404, { detail: 'Dataset not found' })
    await expect(api.listDatasets()).rejects.toMatchObject({
      detail: 'Dataset not found',
    } satisfies Partial<ApiError>)
  })
})

describe('a FastAPI validation-error array detail', () => {
  it('never renders as "[object Object]"', async () => {
    mockErrorResponse(422, {
      detail: [
        {
          type: 'enum',
          loc: ['body', 'sensor_type'],
          msg: "Input should be 'gpr', 'seismic', 'magnetometer'",
          input: 'other',
        },
      ],
    })
    let caught: ApiError | undefined
    try {
      await api.listDatasets()
    } catch (err) {
      caught = err as ApiError
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect(caught?.detail).not.toContain('[object Object]')
  })

  it('names the field and states the real message', async () => {
    mockErrorResponse(422, {
      detail: [
        {
          type: 'enum',
          loc: ['body', 'sensor_type'],
          msg: "Input should be 'gpr', 'seismic', 'magnetometer'",
          input: 'other',
        },
      ],
    })
    let caught: ApiError | undefined
    try {
      await api.listDatasets()
    } catch (err) {
      caught = err as ApiError
    }
    expect(caught?.detail).toBe(
      "sensor_type: Input should be 'gpr', 'seismic', 'magnetometer'",
    )
  })

  it('joins multiple validation errors, each legible on its own', async () => {
    mockErrorResponse(422, {
      detail: [
        { type: 'missing', loc: ['body', 'name'], msg: 'Field required' },
        { type: 'string_type', loc: ['body', 'source'], msg: 'Input should be a valid string' },
      ],
    })
    let caught: ApiError | undefined
    try {
      await api.listDatasets()
    } catch (err) {
      caught = err as ApiError
    }
    expect(caught?.detail).not.toContain('[object Object]')
    expect(caught?.detail).toContain('name: Field required')
    expect(caught?.detail).toContain('source: Input should be a valid string')
  })
})

describe('an absent or unparseable detail', () => {
  it('falls back to the HTTP status text, the existing behaviour', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('', { status: 500, statusText: 'Internal Server Error' }),
      ),
    )
    let caught: ApiError | undefined
    try {
      await api.listDatasets()
    } catch (err) {
      caught = err as ApiError
    }
    expect(caught?.detail).toBe('Internal Server Error')
  })
})
