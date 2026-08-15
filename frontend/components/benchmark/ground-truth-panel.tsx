'use client'

import { Panel, PanelBody, PanelHeader } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { useBenchmarkArtifact } from '@/hooks/use-subterra'
import type {
  BenchmarkDefinition,
  BenchmarkDefinitionArtifact,
} from '@/types/subterra'

/**
 * The ground truth behind the scores, and what it can actually settle.
 *
 * WHY THIS PANEL EXISTS. The scoring panels answer "what did the detector
 * score". This answers the prior question: could that score have come out
 * differently? A corpus of 107 positives and 6 negatives could only
 * distinguish a detector of AUC 0.74 or better from chance, which means an
 * unchanged score is not evidence that a method failed. Without that stated,
 * every null result on this page is over-read.
 *
 * THERE IS NO GREEN/RED INDICATOR AND NO BENCHMARK SCORE. Fitness is
 * per-question, not a quantity: this corpus is fine for asking whether
 * candidates appear at all and unfit for asking whether one detector beats
 * another. A single badge would collapse exactly the distinction the panel
 * exists to make, so readiness is rendered as words per dimension, each with
 * the reason and what is missing.
 *
 * UNKNOWN IS RENDERED AS UNKNOWN. The six 4TU activities with a blank count
 * are shown in their own row and never folded into the negatives — which is
 * the single cheapest way a benchmark like this could be made to look
 * adequate, and the reason the label exists at all.
 */
export function GroundTruthPanel({ name }: { name: string | null }) {
  const { data, error, isLoading } = useBenchmarkArtifact(name ?? undefined)

  if (!name) {
    return (
      <Panel>
        <PanelHeader title="Ground truth" />
        <PanelBody>
          <StateBox
            kind="empty"
            title="No ground-truth benchmark definition has been generated"
            detail="Produce one with scripts/build_benchmark_definition.py. Nothing is shown here in the meantime."
          />
        </PanelBody>
      </Panel>
    )
  }

  const artifact = data as unknown as BenchmarkDefinitionArtifact | undefined
  const entries = Object.entries(artifact?.benchmarks ?? {})

  return (
    <Panel className="min-h-0">
      <PanelHeader
        title="Ground truth — what the benchmarks can settle"
        action={<span className="font-mono text-[11px] text-muted-foreground">{name}</span>}
      />
      <PanelBody className="space-y-4">
        <QueryState
          isLoading={isLoading}
          error={error}
          absenceTitle="No ground-truth definition available"
          errorTitle="Could not load the ground-truth definition"
        />

        {entries.map(([key, value]) =>
          'unavailable' in value ? (
            <div key={key} data-ground-truth-unavailable={key} className="text-xs text-muted-foreground">
              <p className="text-foreground">{key}</p>
              <p className="mt-1">Not available: {value.reason}</p>
            </div>
          ) : (
            <BenchmarkBlock key={key} definition={value as BenchmarkDefinition} />
          ),
        )}
      </PanelBody>
    </Panel>
  )
}

function BenchmarkBlock({ definition }: { definition: BenchmarkDefinition }) {
  const { counts, power } = definition
  const unknown = counts.by_label.unknown ?? 0
  const contaminated = counts.by_duplicate_status.contaminated ?? 0
  const duplicated = counts.by_duplicate_status.duplicate_of ?? 0

  return (
    <section data-ground-truth={definition.benchmark} className="space-y-3">
      <div>
        <h3 className="text-sm font-medium text-foreground">{definition.benchmark}</h3>
        <p className="font-mono text-[10px] text-muted-foreground">
          definition version {definition.version}
        </p>
      </div>

      {/* The population, stated so that unknown cannot hide among the negatives. */}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
        <Field label="Evaluation units">{counts.units}</Field>
        <Field label="Independent positives">{counts.independent_positives}</Field>
        <Field label="Independent negatives">
          <span data-independent-negatives>{counts.independent_negatives}</span>
        </Field>
        <Field label="Unknown">
          <span data-unknown-units>{unknown}</span>
          {unknown > 0 && (
            <span className="text-muted-foreground"> — not counted as absences</span>
          )}
        </Field>
        <Field label="Duplicated">{duplicated}</Field>
        <Field label="Contaminated">
          <span data-contaminated-units>{contaminated}</span>
        </Field>
      </dl>

      {contaminated > 0 && (
        <p data-contamination-warning className="text-xs leading-relaxed text-foreground">
          {contaminated} unit(s) share byte-identical measurements with a unit carrying
          the opposite label. The same data cannot be evidence both that something is
          present and that nothing is, so they are excluded from both populations.
        </p>
      )}

      {/* Power: the answer to "would we notice an improvement?" */}
      {power && (
        <div data-benchmark-power className="text-xs leading-relaxed text-muted-foreground">
          <p className="font-mono text-[10px] uppercase tracking-[0.14em]">
            Could this corpus recognise a better detector?
          </p>
          {power.smallest_detectable_auc === null ? (
            <p className="mt-1 text-foreground">
              No estimate is possible at this size — with fewer than two units in a
              group there is no variance to estimate from, so no improvement of any
              size could be shown to be real.
            </p>
          ) : (
            <p className="mt-1 text-foreground">
              Only a detector of AUC{' '}
              <span data-smallest-detectable>
                {power.smallest_detectable_auc.toFixed(3)}
              </span>{' '}
              or better could be distinguished from chance here, at{' '}
              {Math.round(power.power * 100)}% power and α {power.alpha}. A genuine but
              moderate improvement would not be recognisable.
            </p>
          )}
          {Object.entries(power.negatives_required).some(([, v]) => v !== null) && (
            <>
              <p className="mt-1.5">Independent negatives needed to detect:</p>
              <ul className="mt-1 space-y-0.5">
                {Object.entries(power.negatives_required).map(([auc, needed]) => (
                  <li key={auc} data-negatives-required>
                    AUC {auc} —{' '}
                    {needed === null
                      ? 'not reachable at any size this analysis considers'
                      : `${needed} (holding ${counts.independent_negatives})`}
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="mt-1.5">{power.caveat}</p>
        </div>
      )}

      {/* Readiness as words per dimension. No badge, no score. */}
      <div className="space-y-1">
        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
          What this benchmark supports
        </p>
        {definition.readiness.map((d) => (
          <div key={d.name} data-readiness={d.readiness} className="text-xs">
            <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              {d.readiness}
            </span>{' '}
            <span className="text-foreground">{d.name}</span>
            <p className="text-muted-foreground">{d.reason}</p>
            {d.missing.length > 0 && (
              <ul className="mt-0.5 space-y-0.5">
                {d.missing.map((m) => (
                  <li key={m} data-readiness-missing className="flex gap-2 text-muted-foreground">
                    <span aria-hidden className="select-none text-primary">
                      &middot;
                    </span>
                    <span>Needs: {m}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>

      {/* External dependencies, recorded as outstanding rather than as progress. */}
      {definition.open_questions.length > 0 && (
        <div className="space-y-1">
          <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
            Evidence that must come from outside Subterra
          </p>
          {definition.open_questions.map((q) => (
            <div key={q.id} data-open-question={q.id} className="text-xs">
              <span className="text-foreground">{q.id}</span>
              <p className="text-muted-foreground">Blocks: {q.blocks}</p>
              <p className="text-muted-foreground">Would be resolved by: {q.resolution_route}</p>
              <p data-request-status className="text-muted-foreground">
                {q.request_status}
              </p>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 text-foreground">{children}</dd>
    </div>
  )
}
