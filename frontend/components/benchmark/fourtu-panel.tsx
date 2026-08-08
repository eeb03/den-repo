'use client'

import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import {
  BlockedGate,
  OpenQuestions,
  ScopeStatement,
} from '@/components/subterra/gate-status'
import { Interpretation, Metric } from './metric'
import { useBenchmarkArtifact } from '@/hooks/use-subterra'

/**
 * 4TU — real-world utility surveys, activity level.
 *
 * The headline is a null result, and it is presented as one. Nothing here
 * is recomputed; the artifact's own `interpretation` and `caveat` strings
 * are rendered verbatim next to the figures they qualify.
 *
 * Language matters in this panel specifically: the detector produces
 * CANDIDATES, and a candidate is not a detected utility. No candidate is
 * matched to a utility on this corpus -- object-level scoring is blocked --
 * so the word "detection" is not used for them.
 */
export function FourTuPanel({ name }: { name: string | null }) {
  const { data, error, isLoading } = useBenchmarkArtifact(name ?? undefined)

  if (!name) {
    return (
      <Panel>
        <PanelHeader title="4TU — real-world utility surveys" />
        <PanelBody>
          <StateBox
            kind="empty"
            title="No 4TU benchmark artifact has been generated"
            detail="Produce one with scripts/score_4tu_benchmark.py. Nothing is shown here in the meantime."
          />
        </PanelBody>
      </Panel>
    )
  }

  const score = (data?.score ?? {}) as Record<string, unknown>
  const separation = (score.density_separation ?? {}) as Record<string, unknown>
  const agreement = (score.count_agreement ?? {}) as Record<string, unknown>
  const positive = (score.positive_group ?? {}) as Record<string, unknown>
  const zero = (score.attested_zero_group ?? {}) as Record<string, unknown>

  return (
    <Panel className="min-h-0">
      <PanelHeader
        title="4TU — real-world utility surveys"
        action={
          <span className="font-mono text-[11px] text-muted-foreground">{name}</span>
        }
      />
      <PanelBody className="space-y-3">
        <QueryState
          isLoading={isLoading}
          error={error}
          absenceTitle="4TU artifact unavailable"
          errorTitle="Could not load the 4TU artifact"
          skeletonRows={5}
        />

        {data && (
          <>
            {typeof data.scope === 'string' && <ScopeStatement scope={data.scope} />}

            <BlockedGate
              label="Object-level scoring"
              status={data.object_level_status ?? 'BLOCKED'}
              reason={data.object_level_blocked_reason}
            />
            {data.activity_level_status && (
              <BlockedGate
                label="Activity-level scoring"
                status={data.activity_level_status}
                reason="Counting candidates per activity needs no coordinates and is legitimately available."
              />
            )}

            {/* ------------------------------ truth ------------------------- */}
            <div>
              <h3 className="pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                Ground truth
              </h3>
              <dl>
                <Metric label="Resolution" value={data.resolution as string} />
                <Metric label="Activities" value={data.truth_activities as number} />
                <Metric
                  label="Trench found ≥1 utility"
                  value={data.truth_positive as number}
                />
                <Metric
                  label="Trench found 0 (attested empty)"
                  value={data.truth_attested_zero as number}
                />
                <Metric
                  label="Field blank (unrecorded, not zero)"
                  value={data.truth_unrecorded as number}
                  note="A blank is not a zero. Only an attested zero can serve as a negative."
                />
                <Metric label="Join complete" value={String(data.join_complete)} />
              </dl>
            </div>

            {/* ------------------------------ candidates -------------------- */}
            <div>
              <h3 className="pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                Candidate density, per 1,000 traces
              </h3>
              <p className="pb-1.5 text-[11px] leading-relaxed text-muted-foreground">
                These are detector <span className="text-foreground">candidates</span>,
                not detected utilities. No candidate is matched to a utility on
                this corpus.
              </p>
              <dl>
                <Metric
                  label="Utility-bearing — median"
                  value={positive.median_per_1k as number}
                  emphasis
                />
                <Metric
                  label="Trench-empty — median"
                  value={zero.median_per_1k as number}
                  emphasis
                />
                <Metric
                  label="Utility-bearing — activities"
                  value={positive.n_activities as number}
                />
                <Metric
                  label="Trench-empty — activities"
                  value={zero.n_activities as number}
                />
                <Metric
                  label="Activities with zero candidates"
                  value={`${String(positive.activities_with_zero_candidates)} / ${String(
                    zero.activities_with_zero_candidates,
                  )}`}
                  note="Utility-bearing / trench-empty. The detector is never silent, in either group."
                />
              </dl>
            </div>

            {/* ------------------------------ separation -------------------- */}
            <div>
              <h3 className="pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                Discrimination
              </h3>
              <dl>
                <Metric
                  label="Separation (AUC)"
                  value={separation.auc as number}
                  emphasis
                  note={separation.interpretation as string}
                />
                <Metric
                  label="Count agreement (Spearman ρ)"
                  value={agreement.spearman_rho as number}
                  emphasis
                  note={agreement.interpretation as string}
                />
                <Metric label="ρ — pairs" value={agreement.n_pairs as number} />
                <Metric
                  label="Activity-level response rate"
                  value={score.activity_level_response_rate as number}
                  note={score.activity_level_note as string}
                />
                <Metric
                  label="Unexplained response rate"
                  value={score.unexplained_response_rate as number | null}
                  note={score.unexplained_response_basis as string}
                />
              </dl>
              {typeof agreement.caveat === 'string' && (
                <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                  <span className="text-foreground">Caveat.</span> {agreement.caveat}
                </p>
              )}
            </div>

            {/* -------------------- what was NOT scored --------------------- */}
            <div>
              <h3 className="pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                Not scored
              </h3>
              <dl>
                <Metric
                  label="Object-level"
                  value={String(score.object_level_scored)}
                />
                <Metric
                  label="Positional accuracy"
                  value={String(score.positional_accuracy_scored)}
                />
                <Metric
                  label="Depth accuracy"
                  value={String(score.depth_accuracy_scored)}
                />
              </dl>
            </div>

            {/* ---------------------------- interpretation ------------------ */}
            <Interpretation
              title="The headline is a null result"
              source="docs/4tu-utility-benchmark.md §3"
            >
              <p>
                The detector&rsquo;s candidate density carries no usable
                information about whether a trench found utilities, or how many.
                An AUC of 0.5 means no separation; 0.445 is no separation, very
                slightly reversed. A ρ of −0.062 over 112 activities is no
                monotonic relationship.
              </p>
              <p>
                The two measures point slightly different ways — the medians
                favour the expected direction, the rank-based AUC does not. With
                only 7 activities in the zero group, that inconsistency is
                exactly what &ldquo;no reliable separation&rdquo; looks like, and
                neither figure is quoted without the other.
              </p>
            </Interpretation>

            <Interpretation
              title="Two readings, and the data does not separate them"
              source="docs/4tu-utility-benchmark.md §4"
              uncertain
            >
              <p>
                <span className="text-foreground">1. The detector does not
                discriminate.</span> Consistent with the BAM benchmark and with
                the ring z-score&rsquo;s measured width saturation: a buried
                utility is a broad, laterally coherent target, which is the case
                the statistic is structurally weakest on.
              </p>
              <p>
                <span className="text-foreground">2. The truth is incomplete in
                a way that erases the signal.</span> If trench-empty activities
                routinely contain utilities outside the trench, the
                &ldquo;negative&rdquo; group is not negative and no method could
                separate the groups.
              </p>
              <p>
                Both are plausible. Reading 1 is better supported, because the
                same detector also scored poorly on BAM where the truth is
                complete for the specimen — but that is a controlled concrete
                specimen, and the inference across corpora is weak.
              </p>
            </Interpretation>

            <Interpretation
              title="Why an unmatched candidate is not a false alarm"
              source="artifact: score.trench_scope_caveat"
            >
              <p>
                {(score.trench_scope_caveat as string) ??
                  'A trial trench is a small excavation inside a much larger surveyed area, so a utility under a survey line but outside the trench is absent from the truth and present in the ground.'}
              </p>
              <p>
                Nothing here should be reported as a measured false-alarm rate on
                real-world ground.
              </p>
            </Interpretation>

            {Array.isArray(data.open_questions) && data.open_questions.length > 0 && (
              <div>
                <h3 className="pb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                  Open questions ({data.open_questions.length})
                </h3>
                <OpenQuestions questions={data.open_questions} />
              </div>
            )}
          </>
        )}
      </PanelBody>
    </Panel>
  )
}
