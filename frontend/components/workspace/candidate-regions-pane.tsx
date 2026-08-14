'use client'

import Link from 'next/link'
import { Field, SectionLabel } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { useCandidates } from '@/hooks/use-subterra'
import { formatCount } from '@/lib/format'

/**
 * The Phase 6 candidate-region summary, from the same
 * `GET /api/candidates/{id}` payload `/datasets/{id}/candidates` already
 * uses, through the same `useCandidates` hook -- no second call, no second
 * derivation of the count or the definition.
 *
 * CANDIDATE IS NOT DETECTION, and this pane cannot make it read as one:
 * it prints `data.definition` verbatim (the platform's own words for the
 * distinction), the region count, and `classification_status` -- which is
 * structurally `BLOCKED` -- with its stored reason. It never touches
 * `candidate_score`, a per-candidate localisation/depth certainty, or any
 * shape class: those stay on the candidates page, along with the generate
 * / regenerate control. This pane only says whether a candidate region
 * summary exists, not what is in it.
 *
 * `status: 'blocked'` (no candidate set has ever been generated, or cannot
 * be) renders as an explicit absence, in the platform's own `status_reason`
 * -- not an error, and not a synthetic "0 findings" that would look like a
 * completed, empty search.
 *
 * READ-ONLY. No generate button here; `/datasets/{id}/candidates` remains
 * the only place that control lives.
 */
export function CandidateRegionsPane({ datasetId }: { datasetId: string }) {
  const { data, error, isLoading } = useCandidates(datasetId)

  return (
    <>
      <SectionLabel>Candidate regions</SectionLabel>
      <QueryState
        isLoading={isLoading}
        error={error}
        absenceTitle="Candidate regions unavailable"
        errorTitle="Could not load candidate regions"
      />

      {data && (
        <div data-candidate-regions={data.status} className="space-y-2">
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            {data.definition}
          </p>

          {data.status === 'blocked' ? (
            <StateBox kind="empty" title="No candidate set" detail={data.status_reason} />
          ) : (
            <dl className="space-y-0">
              <Field label="Regions">{formatCount(data.candidate_count)}</Field>
              <Field label="Classification">
                <span data-classification-status className="text-foreground">
                  {data.classification_status}
                </span>
              </Field>
              <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                {data.classification_blocked_reason}
              </p>
            </dl>
          )}

          <Link
            href={`/datasets/${encodeURIComponent(datasetId)}/candidates`}
            className="mt-1 inline-flex text-xs text-primary underline-offset-4 hover:underline"
          >
            Candidate intelligence
          </Link>
        </div>
      )}
    </>
  )
}
