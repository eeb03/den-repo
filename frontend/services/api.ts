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
  AuthUser,
  ImportFormats,
  ImportJob,
  BenchmarkArtifact,
  BenchmarkArtifactsResponse,
  BenchmarkRun,
  CandidateIntelligence,
  ScenePayload,
  CandidateReviewStatus,
  Composition,
  DatasetAcquisition,
  DatasetInfo,
  DatasetReport,
  AcquisitionSession,
  DatasetSummary,
  DeclarationKind,
  Device,
  DeletionResult,
  ExportFormatsResponse,
  ExportResult,
  FrameProvenanceResponse,
  FusionRunResult,
  FusionSample,
  LabelsResponse,
  LayersResponse,
  ObjectsResponse,
  RescoreResult,
  Selection,
  SelectionResolution,
  SessionPayload,
  SessionState,
  SignalProcessingChain,
  SpatialDeclaration,
  SpatialReference,
  InspectableCandidate,
  RadargramField,
  TraceGrid,
} from '@/types/subterra'

/**
 * Base URL of the FastAPI backend. The single place this is decided.
 *
 * THE DEFAULT IS THE PORT `docker-compose.yml` PUBLISHES, which is 8001 and not
 * 8000: Subterra Core's own API already holds 8000 on this machine, so the
 * compose file maps `8001:8000`. The default pointed at 8000 for long enough
 * that `NEXT_PUBLIC_SUBTERRA_API=http://localhost:8001` had become a documented
 * ritual — a workaround for a default that was simply wrong about its own
 * deployment. `frontend/services/api-base.test.ts` now reads the compose file
 * and fails if the two drift apart again.
 *
 * Still overridable with NEXT_PUBLIC_SUBTERRA_API, which is what a
 * reverse-proxied or same-origin deployment sets.
 */
export const API_BASE =
  process.env.NEXT_PUBLIC_SUBTERRA_API ?? 'http://localhost:8001'

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

/**
 * FastAPI's `detail`, rendered as one string.
 *
 * A route-level `HTTPException` gives `detail` as a plain string -- the
 * common case, handled below unchanged. But a 422 from FastAPI's own
 * request validation (a bad enum member, a missing field) gives `detail`
 * as an ARRAY of Pydantic error objects (`{loc, msg, type, ...}`), and
 * `String()` on an array of plain objects joins their
 * `Object.prototype.toString()` -- literally "[object Object]", not an
 * explanation. This was found and fixed for one caller (the sensor-type
 * picker, slice 33); it applies to every 422 this module can receive, not
 * just that one, so the fix belongs here, not as another special case.
 */
function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          const msg = String((item as { msg: unknown }).msg)
          const loc = (item as { loc?: unknown }).loc
          // `loc` is typically ["body", "<field>"]; "body" itself names
          // nothing a reader would recognise, so it is dropped.
          const field = Array.isArray(loc)
            ? loc.filter((part) => part !== 'body').join('.')
            : ''
          return field ? `${field}: ${msg}` : msg
        }
        return typeof item === 'string' ? item : JSON.stringify(item)
      })
      .join('; ')
  }
  return String(detail)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      // The session lives in an HTTP-only cookie, so every call must carry
      // credentials. Without this the browser silently omits it cross-origin
      // (Next on :3000, API on :8001) and every request looks unauthenticated.
      credentials: 'include',
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
        ? formatDetail((body as { detail: unknown }).detail)
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

  /* --------------------------------- devices -------------------------------- */

  /**
   * Record an instrument. Everything supplied here is user-declared and the
   * backend marks it so permanently — `identity_source` is not a field a client
   * can set, because asserting that hardware reported its own serial number
   * would be a forgery.
   */
  registerDevice(body: {
    device_type: string
    manufacturer?: string
    model?: string
    serial_number?: string
    label?: string
    kind?: 'physical' | 'simulated'
    capabilities?: Device['capabilities']
    adapter?: Device['adapter']
  }): Promise<{ device: Device }> {
    return postJson('/api/devices', body)
  },

  listDevices(): Promise<Device[]> {
    return request('/api/devices')
  },

  createSession(
    deviceId: string,
    body: {
      label?: string
      operator?: string
      notes?: string
      survey_area?: string
      coordinate_system?: string
      vertical_reference?: string
      processing_version?: string
    },
  ): Promise<{ session: AcquisitionSession; device: Device }> {
    return postJson(`/api/devices/${encodeURIComponent(deviceId)}/sessions`, body)
  },

  getSession(sessionId: string): Promise<SessionPayload> {
    return request(`/api/sessions/${encodeURIComponent(sessionId)}`)
  },

  /** Move a session along its lifecycle. Illegal transitions are refused 409. */
  moveSession(sessionId: string, to: SessionState): Promise<SessionPayload> {
    return postJson(
      `/api/sessions/${encodeURIComponent(sessionId)}/state?to=${encodeURIComponent(to)}`,
      {},
    )
  },

  /* -------------------------- dataset management ------------------------- */

  /**
   * Change a dataset's human-facing name. The id, the source file, the
   * checksum and every provenance entry are untouched by construction — the
   * backend writes one column.
   */
  renameDataset(id: string, name: string): Promise<DatasetSummary> {
    return request(`/api/datasets/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name }),
    })
  },

  /**
   * Delete a dataset and the data derived from it.
   *
   * The raw source file and the import job survive: the first is the original
   * measurement and cannot be regenerated, the second records an event that
   * happened. The response enumerates both, and the UI shows it — "deleted"
   * alone is not an adequate answer for an irreversible operation.
   */
  deleteDataset(id: string): Promise<DeletionResult> {
    return request(`/api/datasets/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },

  /**
   * Recompute the stored quality score from the records as they are now.
   *
   * NOT `reprocess`, which runs the preprocessing pipeline and saves the result
   * back. This reads, validates, and writes one derived scalar.
   */
  rescoreDataset(id: string): Promise<RescoreResult> {
    return postJson(`/api/datasets/${encodeURIComponent(id)}/rescore`, {})
  },

  /**
   * The richer dataset card. 404s when the dataset has no stored records,
   * which is a real state and not an error.
   */
  getDatasetInfo(id: string): Promise<DatasetInfo> {
    return request(`/api/datasets/${encodeURIComponent(id)}/info`)
  },

  /**
   * The Dataset Report: identity, volume, spatial reference, processing,
   * quality, candidates and downstream readiness, in one call.
   *
   * Deliberately ONE call. The alternative — assembling it in the browser
   * from `/info`, `/provenance/{id}/frames` and `/labels/{id}` — would put
   * the readiness judgement in the client, where it cannot be tested and
   * where the next consumer would reimplement it slightly differently.
   *
   * Unlike `/info`, this does NOT 404 on a dataset with no records: "this
   * produced nothing" is one of the most useful things a report can say.
   */
  getDatasetReport(id: string): Promise<DatasetReport> {
    return request(`/api/datasets/${encodeURIComponent(id)}/report`)
  },

  /**
   * Where this dataset came from: device -> session -> acquisition ->
   * dataset, or the reason no acquisition record exists.
   */
  getDatasetAcquisition(id: string): Promise<DatasetAcquisition> {
    return request(`/api/datasets/${encodeURIComponent(id)}/acquisition`)
  },

  /**
   * The recorded Phase 5 signal-processing chain, read from
   * `processing_applied` on this dataset's records -- never re-run.
   *
   * Deliberately separate from `getDatasetReport`: the full report is known
   * to take tens of seconds to build, and this is called on every dataset
   * open, the same way acquisition and spatial readiness are.
   */
  getSignalChain(id: string): Promise<SignalProcessingChain> {
    return request(`/api/datasets/${encodeURIComponent(id)}/signal-chain`)
  },

  /* --------------------------- spatial reference -------------------------- */

  /**
   * What spatial relationship this dataset has to the physical world.
   *
   * Seven dimensions, each with its state, its reason, what is missing and
   * which declaration would resolve it. An unresolved dimension is a correct
   * answer, not a gap to be filled by the client.
   */
  getSpatialReference(datasetId: string): Promise<SpatialReference> {
    return request(`/api/spatial/${encodeURIComponent(datasetId)}`)
  },

  /** Every claim ever made, superseded ones included. */
  listSpatialDeclarations(
    datasetId: string,
  ): Promise<{ dataset_id: string; count: number; declarations: SpatialDeclaration[] }> {
    return request(`/api/spatial/${encodeURIComponent(datasetId)}/declarations`)
  },

  /**
   * Assert something about how this dataset relates to the world.
   *
   * `suppliedBy` names the AUTHORITY — a surveyor, a document, an operator —
   * and is distinct from the signed-in account, which the backend records
   * separately: the person typing may be relaying somebody else's measurement.
   *
   * Returns the recalculated spatial reference, so inspect → resolve →
   * recalculate is one round trip rather than three.
   */
  declareSpatialReference(
    datasetId: string,
    kind: DeclarationKind,
    value: Record<string, unknown>,
    suppliedBy: string,
    note?: string,
  ): Promise<{
    declaration: SpatialDeclaration
    applied: { frames_changed: string[] }
    spatial_reference: SpatialReference
  }> {
    return postJson(`/api/spatial/${encodeURIComponent(datasetId)}/declarations`, {
      kind,
      value,
      supplied_by: suppliedBy,
      note,
    })
  },

  /* ------------------------- objects and labels ------------------------- */

  getObjects(datasetId: string): Promise<ObjectsResponse> {
    return request(`/api/objects/${encodeURIComponent(datasetId)}`)
  },

  /* -------------------------------- exports -------------------------------- */

  getExportFormats(): Promise<ExportFormatsResponse> {
    return request('/api/exports/formats')
  },

  /**
   * `format: 'csv'` resolves to a plain string (the backend serves it as
   * `text/csv`, which `request()` returns as text, not JSON) — every other
   * format resolves to `ExportResult`. The caller must discriminate on the
   * `format` it passed, not on the shape of what came back.
   */
  exportDatasetObjects(datasetId: string, format: string): Promise<ExportResult | string> {
    return request(
      `/api/exports/${encodeURIComponent(datasetId)}/objects?format=${encodeURIComponent(format)}`,
    )
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
  /**
   * One survey line as a (depth x trace) grid.
   *
   * `reliability` and `candidateFootprints` are opt-in because each adds
   * materially to the payload and no earlier caller needs them. The footprints
   * are computed server-side so the candidate-to-grid mapping has one tested
   * implementation rather than a second copy in TypeScript.
   */
  getTraceGrid(
    datasetId: string,
    opts: {
      field?: RadargramField | string
      sourceFile?: string | null
      reliability?: boolean
      candidateFootprints?: boolean
    } = {},
  ): Promise<TraceGrid> {
    const query = new URLSearchParams({ field: opts.field ?? 'signal' })
    if (opts.sourceFile) query.set('source_file', opts.sourceFile)
    if (opts.reliability) query.set('include_reliability', 'true')
    if (opts.candidateFootprints) query.set('include_candidates', 'true')
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

  /* ------------------------------- imports ------------------------------ */

  /**
   * What the platform can actually read, asked of the backend every time.
   *
   * The UI deliberately keeps NO list of its own: `converters/registry.py` is
   * the single source of truth for format support, and a second copy here
   * would eventually promise a format nobody can read.
   */
  getImportFormats(): Promise<ImportFormats> {
    return request('/api/imports/formats')
  },

  /** Uploads a file and returns the created job. 202: no dataset exists yet. */
  /**
   * Hand a reviewed acquisition to the existing ingestion pipeline.
   *
   * Only a held acquisition can be accepted; the backend refuses a rejected,
   * running or finished one with 409 rather than ingesting the same bytes
   * twice under one record.
   */
  acceptAcquisition(
    jobId: string,
    options: { band_is_elevation?: boolean } = {},
  ): Promise<{ job: ImportJob }> {
    // `options` are declarations about HOW to read the file — currently only
    // whether a raster band is elevation. The backend refuses any the detected
    // format cannot use, rather than recording a claim that had no effect.
    return postJson(`/api/imports/jobs/${encodeURIComponent(jobId)}/accept`, options)
  },

  createImport(
    file: File,
    sensorType: string,
    review = false,
    sessionId?: string,
  ): Promise<{ job: ImportJob }> {
    const form = new FormData()
    form.append('file', file)
    form.append('sensor_type', sensorType)
    // `review` holds the acquisition at the boundary so the user sees what
    // arrived before anything is ingested. Defaulting to false keeps the
    // original immediate behaviour for callers that never asked for a review.
    form.append('review', String(review))
    // Attributes this acquisition to a device session -- Stage 10's
    // convergence with FileDrop. Omitted entirely (not sent as an empty
    // string) when there is no session, so an ordinary drop still produces
    // session_id: null on the backend rather than an empty-string claim.
    if (sessionId) form.append('session_id', sessionId)
    // No content-type header: the browser must set the multipart boundary.
    return request('/api/imports', { method: 'POST', body: form })
  },

  /* -------------------------------- auth -------------------------------- */

  /**
   * The signed-in account, or an ApiError with status 401.
   *
   * There is no token to read here and none is stored: the cookie is
   * HTTP-only, so script cannot see it, and the only way to learn who you are
   * is to ask the server.
   */
  me(): Promise<{ user: AuthUser }> {
    return request('/api/auth/me')
  },

  register(email: string, password: string, displayName?: string): Promise<{ user: AuthUser }> {
    return postJson('/api/auth/register', {
      email,
      password,
      display_name: displayName || null,
    })
  },

  login(email: string, password: string): Promise<{ user: AuthUser }> {
    return postJson('/api/auth/login', { email, password })
  },

  /**
   * Request a reset link. The response is deliberately identical whether or not
   * the address has an account, and carries no token, url or identifier.
   */
  forgotPassword(email: string): Promise<{ message: string }> {
    return postJson('/api/auth/forgot-password', { email })
  },

  resetPassword(
    token: string,
    password: string,
    passwordConfirmation: string,
  ): Promise<{ message: string }> {
    return postJson('/api/auth/reset-password', {
      token,
      password,
      password_confirmation: passwordConfirmation,
    })
  },

  logout(): Promise<{ ok: boolean }> {
    return request('/api/auth/logout', { method: 'POST' })
  },

  getImportJob(jobId: string): Promise<{ job: ImportJob }> {
    return request(`/api/imports/jobs/${encodeURIComponent(jobId)}`)
  },

  listImportJobs(): Promise<{ jobs: ImportJob[] }> {
    return request('/api/imports/jobs')
  },

  /* ----------------------------- candidates ----------------------------- */

  /**
   * The stored candidate set, with staleness assessed at read time.
   *
   * A `blocked` status here is a real answer, not an error: it means candidate
   * generation has not been run, or cannot be, and `missing` says what would
   * change that.
   */
  getCandidates(datasetId: string): Promise<CandidateIntelligence> {
    return request(`/api/candidates/${encodeURIComponent(datasetId)}`)
  },

  /* -------------------------------- scene -------------------------------- */

  /**
   * The reconstructed-scene payload: what a 3D renderer needs to draw an
   * elevation-anchored scene for this dataset, or exactly why it cannot yet.
   *
   * `resolved: false` is the correct, common answer — it means
   * `fusion.vertical_reference.assess` has not been satisfied for this
   * dataset (see `resolution_reason`/`missing`), not that the request
   * failed. `surfaceDatasetId` names a SEPARATE dataset holding the surface
   * (DEM/LiDAR) frame, the same cross-dataset relationship `/api/fusion/*`
   * already reads.
   */
  getScene(datasetId: string, surfaceDatasetId?: string): Promise<ScenePayload> {
    const params = new URLSearchParams()
    if (surfaceDatasetId) params.set('surface_dataset_id', surfaceDatasetId)
    const qs = params.toString()
    return request(`/api/scene/${encodeURIComponent(datasetId)}${qs ? `?${qs}` : ''}`)
  },

  /**
   * Run candidate generation. An explicit action, never a side effect of
   * opening a report — it reads every record in the dataset.
   */
  generateCandidates(
    datasetId: string,
    parameters?: { threshold?: number; min_cells?: number; min_trace_span?: number },
  ): Promise<CandidateIntelligence> {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(parameters ?? {})) {
      if (value !== undefined) query.set(key, String(value))
    }
    const suffix = query.toString() ? `?${query}` : ''
    return request(`/api/candidates/${encodeURIComponent(datasetId)}/generate${suffix}`, {
      method: 'POST',
    })
  },

  /**
   * Record a reviewer's decision. Acceptance means "worth retaining" — it does
   * not promote a candidate to a detection, an object, or ground truth.
   */
  reviewCandidate(
    datasetId: string,
    candidateId: string,
    status: CandidateReviewStatus,
  ): Promise<InspectableCandidate & { note: string }> {
    return request(
      `/api/candidates/${encodeURIComponent(datasetId)}/${encodeURIComponent(candidateId)}` +
        `/status?status=${encodeURIComponent(status)}`,
      { method: 'POST' },
    )
  },

  /* -------------------------------- fusion -------------------------------- */

  /**
   * Every stored fusion sample, visible to this caller -- the endpoint
   * takes no parameters and is not scoped to one dataset; a caller filters
   * `dataset_ids` itself. Deliberately 1:1 with what
   * `GET /api/fusion/samples` returns: `radius_m` and `n_reprojected` are
   * both now part of that response, so both are typed.
   */
  listFusionSamples(): Promise<FusionSample[]> {
    return request('/api/fusion/samples')
  },

  /**
   * Run spatial fusion, and optionally persist the result.
   *
   * `datasetIds` omitted (not an empty array) means every dataset visible
   * to this caller -- the backend's own distinction between "say nothing"
   * and "say none", and `URLSearchParams.append` per id is what produces
   * FastAPI's expected repeated `dataset_ids=` query keys for a `list[str]`
   * parameter.
   *
   * `persist` defaults to `false`: this is a run control that writes new
   * `FusionSample` rows with no dedup against what is already stored, so
   * every caller must say `persist: true` on purpose. There is no
   * "preview" flag on the backend -- `persist: false` already IS the
   * preview, run as many times as wanted with nothing written.
   */
  runFusion(options?: {
    datasetIds?: string[]
    radiusM?: number
    multimodalOnly?: boolean
    persist?: boolean
  }): Promise<FusionRunResult> {
    const params = new URLSearchParams()
    for (const id of options?.datasetIds ?? []) params.append('dataset_ids', id)
    if (options?.radiusM !== undefined) params.set('radius_m', String(options.radiusM))
    if (options?.multimodalOnly !== undefined) {
      params.set('multimodal_only_flag', String(options.multimodalOnly))
    }
    params.set('persist', String(options?.persist ?? false))
    return request(`/api/fusion/run?${params.toString()}`, { method: 'POST' })
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
