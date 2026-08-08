/**
 * The Subterra API adapter.
 *
 * This is the single seam between the UI and the backend. Every method here
 * maps onto an endpoint that actually exists; there are no mock bodies and
 * no invented endpoints. Where the v0 prototype had a service method with
 * no Subterra equivalent -- scans, sensors, system health, notifications,
 * operators, detection trends -- the method is simply absent rather than
 * faked, because the platform ingests files and has no telemetry, no job
 * lifecycle and no auth.
 *
 * TWO RULES THIS MODULE ENFORCES.
 *
 * 1. It does not interpret. Nothing here computes a coordinate, a depth, an
 *    elevation or a confidence, and nothing rescales or rounds a value. The
 *    backend owns every scientific judgement; this file moves JSON.
 *
 * 2. A refusal is data, not an exception to swallow. `ApiError` carries the
 *    HTTP status and the backend's own `detail` string so a caller can tell
 *    "no such dataset" (404) from "this dataset has no trace grid, and here
 *    is why" (400) from a genuine failure -- and render the backend's
 *    wording rather than substituting its own.
 */
import type {
  BenchmarkArtifact,
  BenchmarkArtifactsResponse,
  BenchmarkRun,
  Composition,
  DatasetInfo,
  DatasetSummary,
  FrameProvenanceResponse,
  LabelsResponse,
  LayersResponse,
  ObjectsResponse,
  Selection,
  SelectionResolution,
  TraceGrid,
} from '@/types/subterra'

/**
 * Base URL of the FastAPI backend.
 *
 * Same-origin by default so a reverse-proxied deployment needs no config;
 * override with NEXT_PUBLIC_SUBTERRA_API for the usual split dev setup
 * (Next on :3000, uvicorn on :8000).
 */
export const API_BASE =
  process.env.NEXT_PUBLIC_SUBTERRA_API ?? 'http://localhost:8000'

/** An HTTP-level refusal, carrying the backend's own explanation. */
export class ApiError extends Error {
  readonly status: number
  /** The backend's `detail`, verbatim. Render this, do not paraphrase it. */
  readonly detail: string

  constructor(status: number, detail: string) {
    super(`HTTP ${status}: ${detail}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }

  /**
   * True when the backend answered "this does not exist / this data cannot
   * support that", as opposed to failing. Both are legitimate states that
   * the UI renders as explained absences rather than as errors.
   */
  get isAbsence(): boolean {
    return this.status === 404 || this.status === 400 || this.status === 409
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { accept: 'application/json', ...(init?.headers ?? {}) },
    })
  } catch (cause) {
    // Network-level failure: the backend was not reachable at all.
    throw new ApiError(
      0,
      `could not reach the Subterra API at ${API_BASE}. ${String(cause)}`,
    )
  }

  const body = response.headers.get('content-type')?.includes('json')
    ? await response.json().catch(() => null)
    : await response.text().catch(() => null)

  if (!response.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : typeof body === 'string' && body
          ? body
          : response.statusText
    throw new ApiError(response.status, detail)
  }

  return body as T
}

function postJson<T>(path: string, payload: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export const api = {
  /* ------------------------------ datasets ------------------------------ */

  listDatasets(): Promise<DatasetSummary[]> {
    return request('/api/datasets/')
  },

  getDataset(id: string): Promise<DatasetSummary> {
    return request(`/api/datasets/${encodeURIComponent(id)}`)
  },

  /**
   * The richer dataset card. 404s when the dataset has no stored records,
   * which is a real state and not an error.
   */
  getDatasetInfo(id: string): Promise<DatasetInfo> {
    return request(`/api/datasets/${encodeURIComponent(id)}/info`)
  },

  /* ------------------------- objects and labels ------------------------- */

  getObjects(datasetId: string): Promise<ObjectsResponse> {
    return request(`/api/objects/${encodeURIComponent(datasetId)}`)
  },

  getLabels(datasetId: string): Promise<LabelsResponse> {
    return request(`/api/labels/${encodeURIComponent(datasetId)}`)
  },

  /* ------------------------------ overlays ------------------------------ */

  getLayers(datasetId: string): Promise<LayersResponse> {
    return request(`/api/overlays/${encodeURIComponent(datasetId)}/layers`)
  },

  composeOverlays(datasetIds: string[]): Promise<Composition> {
    return postJson('/api/overlays/compose', { datasets: datasetIds })
  },

  /* -------------------------------- views ------------------------------- */

  /**
   * Asks the backend which views can show a selection.
   *
   * This is the authority on what may be displayed. The UI must never
   * decide locally that a view is available -- particularly `scene_3d`,
   * which is unresolved for every dataset currently held because no dataset
   * has an established vertical relationship.
   */
  resolveSelection(selection: Selection): Promise<SelectionResolution> {
    return postJson('/api/views/resolve', { selection })
  },

  /* ----------------------------- provenance ----------------------------- */

  getFrameProvenance(datasetId: string): Promise<FrameProvenanceResponse> {
    return request(`/api/provenance/${encodeURIComponent(datasetId)}/frames`)
  },

  /* ------------------------------ radargram ----------------------------- */

  /**
   * The trace grid backing the radargram.
   *
   * Throws `ApiError` with status 400 and an explanation when the dataset's
   * records carry no trace/depth metadata, and 404 when there is no grid at
   * all. Both are legitimate states: a dataset without multi-sample trace
   * data has no radargram, and that is a fact about the data rather than a
   * failure of the request.
   */
  getTraceGrid(
    datasetId: string,
    opts: { field?: string; sourceFile?: string | null } = {},
  ): Promise<TraceGrid> {
    const query = new URLSearchParams({ field: opts.field ?? 'signal' })
    if (opts.sourceFile) query.set('source_file', opts.sourceFile)
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/trace_grid?${query}`,
    )
  },

  /* ------------------------------ benchmark ----------------------------- */

  listBenchmarkArtifacts(): Promise<BenchmarkArtifactsResponse> {
    return request('/api/benchmark/artifacts')
  },

  /**
   * One scoring artifact, exactly as the scoring script wrote it.
   *
   * Returned unmodified. Nothing in the UI recomputes, rescales or
   * reinterprets a benchmark figure.
   */
  getBenchmarkArtifact(name: string): Promise<BenchmarkArtifact> {
    return request(`/api/benchmark/artifacts/${name}`)
  },

  listBenchmarkRuns(): Promise<BenchmarkRun[]> {
    return request('/api/benchmark/runs')
  },
}

/*
 * DELIBERATELY ABSENT, because the backend has no such capability:
 *
 *   getScans / getActiveScan   there is no scan entity, lifecycle or
 *                              progress; the platform registers Datasets
 *                              and SurveyFrames
 *   getSensors                 no telemetry ingestion exists; sensors are
 *                              not connected to this system
 *   getSystemHealth            no metrics subsystem
 *   getNotifications           no notification service
 *   getOperator                no auth
 *   getAnalytics / trends      no time-series store, and no historical
 *                              baseline to difference against
 *
 * Adding any of them would mean inventing an endpoint or fabricating a
 * value. If one of these is genuinely needed, the backend gains the
 * capability first.
 */
