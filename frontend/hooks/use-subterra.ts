'use client'

import useSWR from 'swr'
import { ApiError, api } from '@/services/api'
import type { Selection } from '@/types/subterra'

/**
 * SWR hooks over the API adapter.
 *
 * NO POLLING. The v0 prototype refreshed sensors and system health every
 * five seconds because it was simulating a live rig. Nothing Subterra
 * serves is live: datasets, frames, objects, labels and benchmark
 * artifacts change only when someone ingests, scores or labels something.
 * A refresh interval here would produce constant motion that implies
 * incoming measurements, which would be a lie about the system.
 *
 * Retry is likewise suppressed for a 4xx. A 400 saying "this dataset has
 * no trace grid" is a settled answer about the data; retrying it five
 * times just delays showing the user that answer.
 */

const options = {
  revalidateOnFocus: false,
  shouldRetryOnError: (error: unknown) =>
    !(error instanceof ApiError && error.isAbsence),
}

export function useDatasets() {
  return useSWR('datasets', () => api.listDatasets(), options)
}

export function useDatasetInfo(datasetId: string | undefined) {
  return useSWR(
    datasetId ? ['dataset-info', datasetId] : null,
    () => api.getDatasetInfo(datasetId as string),
    options,
  )
}

export function useDatasetReport(datasetId: string | undefined) {
  return useSWR(
    datasetId ? ['dataset-report', datasetId] : null,
    () => api.getDatasetReport(datasetId as string),
    options,
  )
}

export function useDatasetAcquisition(datasetId: string | undefined) {
  return useSWR(
    datasetId ? ['dataset-acquisition', datasetId] : null,
    () => api.getDatasetAcquisition(datasetId as string),
    options,
  )
}

export function useSignalChain(datasetId: string | undefined) {
  return useSWR(
    datasetId ? ['signal-chain', datasetId] : null,
    () => api.getSignalChain(datasetId as string),
    options,
  )
}

export function useSpatialReference(datasetId: string | undefined) {
  return useSWR(
    datasetId ? ['spatial-reference', datasetId] : null,
    () => api.getSpatialReference(datasetId as string),
    options,
  )
}

export function useCandidates(datasetId: string | undefined) {
  return useSWR(
    datasetId ? ['candidates', datasetId] : null,
    () => api.getCandidates(datasetId as string),
    options,
  )
}

export function useSession(sessionId: string | undefined) {
  return useSWR(
    sessionId ? ['session', sessionId] : null,
    () => api.getSession(sessionId as string),
    options,
  )
}

export function useDevices() {
  return useSWR('devices', () => api.listDevices(), options)
}

export function useObjects(datasetId: string | undefined) {
  return useSWR(
    datasetId ? ['objects', datasetId] : null,
    () => api.getObjects(datasetId as string),
    options,
  )
}

export function useLabels(datasetId: string | undefined) {
  return useSWR(
    datasetId ? ['labels', datasetId] : null,
    () => api.getLabels(datasetId as string),
    options,
  )
}

export function useLayers(datasetId: string | undefined) {
  return useSWR(
    datasetId ? ['layers', datasetId] : null,
    () => api.getLayers(datasetId as string),
    options,
  )
}

export function useComposition(datasetId: string | undefined) {
  return useSWR(
    datasetId ? ['composition', datasetId] : null,
    () => api.composeOverlays([datasetId as string]),
    options,
  )
}

export function useFrameProvenance(datasetId: string | undefined) {
  return useSWR(
    datasetId ? ['provenance-frames', datasetId] : null,
    () => api.getFrameProvenance(datasetId as string),
    options,
  )
}

export function useTraceGrid(
  datasetId: string | undefined,
  sourceFile?: string | null,
) {
  return useSWR(
    datasetId ? ['trace-grid', datasetId, sourceFile ?? null] : null,
    () => api.getTraceGrid(datasetId as string, { sourceFile }),
    options,
  )
}

/**
 * Resolves a selection across every view.
 *
 * Keyed on the selection's identity so switching selections refetches, and
 * null-keyed when nothing is selected so no request is made.
 */
export function useViewResolution(selection: Selection | null) {
  return useSWR(
    selection
      ? ['views-resolve', selection.dataset_id, selection.kind, selection.selection_id]
      : null,
    () => api.resolveSelection(selection as Selection),
    options,
  )
}

export function useBenchmarkArtifacts() {
  return useSWR('benchmark-artifacts', () => api.listBenchmarkArtifacts(), options)
}

export function useBenchmarkArtifact(name: string | undefined) {
  return useSWR(
    name ? ['benchmark-artifact', name] : null,
    () => api.getBenchmarkArtifact(name as string),
    options,
  )
}

/* ------------------------------ dataset import ----------------------------- */

/**
 * The registry's answer about format support. Static for the life of a
 * deployment, so it is fetched once and never revalidated.
 */
export function useImportFormats() {
  return useSWR('import-formats', () => api.getImportFormats(), {
    ...options,
    revalidateIfStale: false,
    revalidateOnReconnect: false,
  })
}

/**
 * An import job, polled until it finishes.
 *
 * THIS IS THE ONE LEGITIMATE EXCEPTION to the no-polling rule at the top of
 * this file, and it is worth being precise about why. That rule exists because
 * the v0 prototype refreshed sensors on a timer to imply a live rig, and
 * nothing Subterra serves is live. An import job genuinely is: the server is
 * doing work right now and its state really does change without anyone acting.
 * Polling here reports a change that is actually happening rather than
 * simulating one that is not.
 *
 * Polling STOPS the moment the job reaches a terminal state, so a finished
 * import produces no further traffic and no illusion of ongoing activity.
 */
export function useImportJob(jobId: string | undefined) {
  return useSWR(
    jobId ? ['import-job', jobId] : null,
    () => api.getImportJob(jobId as string).then((r) => r.job),
    {
      ...options,
      refreshInterval: (latest) =>
        latest && (latest.state === 'SUCCEEDED' || latest.state === 'FAILED')
          ? 0
          : 1200,
    },
  )
}

/* --------------------------------- accounts -------------------------------- */

/**
 * Who is signed in, according to the server.
 *
 * A 401 is a legitimate ANSWER here, not a failure: it means "nobody". The
 * hook therefore resolves to null rather than surfacing an error, and does not
 * retry -- retrying a settled "you are not signed in" would only delay the
 * login screen.
 */
export function useCurrentUser() {
  return useSWR(
    'current-user',
    () =>
      api
        .me()
        .then((r) => r.user)
        .catch((error) => {
          if (error instanceof ApiError && error.status === 401) return null
          throw error
        }),
    { ...options, shouldRetryOnError: false },
  )
}
