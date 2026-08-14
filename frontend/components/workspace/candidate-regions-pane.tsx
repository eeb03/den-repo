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
 * derivation of the count, the definition, or the generation identity.
 *
 * CANDIDATE IS NOT DETECTION, and this pane cannot make it read as one:
 * it prints `data.definition` verbatim (the platform's own words for the
 * distinction), `data.benchmark.summary` verbatim (the same "performs at
 * approximately chance" sentence the candidates page puts above its own
 * list, from the payload -- not a paraphrase, not a number typed here that
 * could drift from what the benchmark actually produced), the region
 * count, `classification_status` -- which is structurally `BLOCKED` -- with
 * its stored reason, and who produced the set (`method vversion`, or
 * `unrecorded`). It never touches `candidate_score`, `benchmark.measurements`,
 * generation parameters/fingerprint/seed, a per-candidate localisation/depth
 * certainty, or any shape class: those stay on the candidates page, along
 * with the generate / regenerate control. This pane only says whether a
 * candidate region summary exists and whether it is current, not what is
 * in it or how to reproduce it.
 *
 * A COUNT CANNOT BE READ AS CURRENT IF IT IS NOT. When `staleness.is_stale`,
 * a banner outside the `<dl>` states that the set no longer matches the
 * dataset, with the stored `reasons` and `note` verbatim -- the set is NOT
 * hidden, because a stale set is still a set, and hiding it would conceal
 * the very thing that is stale. When not stale, nothing is printed: silence
 * is the honest state here, the same as on the candidates page (no "fresh" /
 * "current" / "up to date" badge, which would assert a check this pane does
 * not itself perform).
 *
 * `status: 'blocked'` (no candidate set has ever been generated, or cannot
 * be) renders as an explicit absence, in the platform's own `status_reason`
 * -- not an error, and not a synthetic "0 findings" that would look like a
 * completed, empty search. Nothing else in this component -- not identity,
 * not staleness, not the benchmark sentence -- renders in that branch.
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
            <>
              {/*
                Above the count, deliberately -- the candidates page puts
                this same sentence above its own list, because it is the
                context that decides how the count below should be read.
              */}
              <p data-benchmark-summary className="text-[11px] leading-relaxed text-foreground">
                {data.benchmark.summary}
              </p>

              {data.staleness.is_stale && (
                <div
                  data-stale
                  className="rounded border border-border px-2 py-1.5 text-[11px] leading-relaxed text-muted-foreground"
                >
                  <p className="text-foreground">
                    This candidate set no longer matches the dataset.
                  </p>
                  <ul className="mt-1 space-y-0.5">
                    {data.staleness.reasons.map((reason) => (
                      <li key={reason} data-stale-reason>
                        {reason}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-1">{data.staleness.note}</p>
                </div>
              )}

              <dl className="space-y-0">
                <Field label="Regions">{formatCount(data.candidate_count)}</Field>
                <Field label="Classification">
                  <span data-classification-status className="text-foreground">
                    {data.classification_status}
                  </span>
                </Field>
                <Field label="Generation">
                  <span data-generation>
                    {data.generation
                      ? `${data.generation.method} v${data.generation.method_version}`
                      : 'unrecorded'}
                  </span>
                </Field>
                <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                  {data.classification_blocked_reason}
                </p>
              </dl>
            </>
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
