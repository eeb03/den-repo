import type { ProvenanceClass } from '@/types/subterra'

/**
 * Presentation metadata for `ProvenanceClass`.
 *
 * The `label` and `meaning` strings paraphrase `schemas/provenance.py` and
 * `docs/provenance.md`. They explain the vocabulary to a reader; they never
 * substitute for a `basis` the backend supplied, which is always rendered
 * verbatim alongside.
 *
 * There is deliberately no numeric rank here. The backend keeps a
 * CLASS_STRENGTH map for sorting, with an explicit warning that it must
 * never be used "to collapse classes into a score". Mirroring it in the UI
 * would invite exactly that.
 */
export interface ProvenanceMeta {
  label: string
  /** CSS custom property carrying this class's hue. */
  color: string
  meaning: string
}

export const provenanceMeta: Record<ProvenanceClass, ProvenanceMeta> = {
  measured: {
    label: 'Measured',
    color: 'var(--prov-measured)',
    meaning: 'Recorded by an instrument.',
  },
  declared_by_source: {
    label: 'Declared by source',
    color: 'var(--prov-declared)',
    meaning: 'Stated by the publisher of the data, and taken at its word.',
  },
  supplied_by_caller: {
    label: 'Supplied by caller',
    color: 'var(--prov-supplied)',
    meaning: 'Provided to the platform at ingest or through the API.',
  },
  derived: {
    label: 'Derived',
    color: 'var(--prov-derived)',
    meaning: 'Computed from other values that are themselves attested.',
  },
  inferred: {
    label: 'Inferred',
    color: 'var(--prov-inferred)',
    meaning: 'Concluded from indirect evidence, not stated anywhere.',
  },
  assumed: {
    label: 'Assumed',
    color: 'var(--prov-assumed)',
    meaning: 'Taken as true without evidence, because something was needed.',
  },
  unavailable: {
    label: 'Unavailable',
    color: 'var(--prov-unavailable)',
    meaning: 'No value exists, and none has been substituted.',
  },
}

/** The seven classes, in the order the vocabulary documents them. */
export const provenanceOrder: ProvenanceClass[] = [
  'measured',
  'declared_by_source',
  'supplied_by_caller',
  'derived',
  'inferred',
  'assumed',
  'unavailable',
]

/**
 * Resolves an arbitrary string from the API to a known provenance class.
 *
 * Returns null rather than guessing when the value is unrecognised, so a
 * new backend class shows up as unstyled text that someone notices, rather
 * than being silently absorbed into `unavailable` -- which would read as a
 * claim about the data that nobody made.
 */
export function asProvenanceClass(value: unknown): ProvenanceClass | null {
  return typeof value === 'string' && value in provenanceMeta
    ? (value as ProvenanceClass)
    : null
}
