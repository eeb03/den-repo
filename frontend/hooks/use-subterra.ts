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
