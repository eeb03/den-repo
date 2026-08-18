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
 * distinction) -- EXCEPT when `status_reason` already says candidate
 * analysis does not apply to this dataset's composition (Phase 7, slices
 * 10-12): opening under the method's own vocabulary before that reason
 * would be the same misdirection slices 10-11 removed from the candidates
 * page. `data.benchmark.summary` verbatim (the same "performs at
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

  // Slice 10-11's exact signal, reused verbatim: no second fetch, no
  // composition parsing, no new API field.
  const doesNotApply =
    !!data && data.status === 'blocked' && data.status_reason.includes('does not apply')

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
          {/*
            The definition is the vocabulary of a processed-signal /
            generation-rule capability. When status_reason already says that
            capability does not apply to this dataset, printing the
            definition first would open the pane under a method's own words
            before the reason it does not apply -- the same misdirection
            slice 11 removed from the candidates page.
          */}
          {!doesNotApply && (
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              {data.definition}
            </p>
          )}

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

          {/*
            Slice 24: sending a reader into the candidate workflow when the
            StateBox above already says the capability does not apply would
            be the same invitation slice 23 removed from the dataset
            report's Candidates section.
          */}
          {!doesNotApply && (
            <Link
              href={`/datasets/${encodeURIComponent(datasetId)}/candidates`}
              className="mt-1 inline-flex text-xs text-primary underline-offset-4 hover:underline"
            >
              Candidate intelligence
            </Link>
          )}
        </div>
      )}
    </>
  )
}
