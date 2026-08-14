'use client'

import { SectionLabel } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { useSignalChain } from '@/hooks/use-subterra'
import { cn } from '@/lib/utils'

const STEP_LABEL: Record<string, string> = {
  background_removal: 'Background removal',
  dewow: 'Dewow',
  gain: 'Gain',
}

/**
 * The Phase 5 recorded signal-processing chain, from
 * `GET /api/datasets/{id}/signal-chain`.
 *
 * READ, NOT RE-RUN. `background_removal` / `dewow` / `gain`, in the order
 * `process_gpr_traces` actually applies them -- never a client-side default
 * chain. `ran` and `parameters` are read verbatim from the stored
 * `processing_applied` entry; a step this dataset's records never carried
 * is not invented, and a step that ran with no recorded parameter (the
 * boolean-only `background_removal`) shows none rather than a guess.
 *
 * DELIBERATELY A SEPARATE, THIN CALL FROM THE DATASET REPORT. The report is
 * slow to build on a dataset of any size; this pane loads on every dataset
 * open, the same way `AcquisitionPane` and `SpatialAssessmentPane` do, and
 * both the report and this route derive from the same `build_signal_chain`
 * so they cannot disagree about what ran.
 *
 * NO REPROCESS CONTROL, no parameter editor, no quality score. Raw and
 * processed amplitude stay distinguishable elsewhere (provenance); this
 * pane only names what already happened.
 */
export function SignalChainPane({ datasetId }: { datasetId: string }) {
  const { data, error, isLoading } = useSignalChain(datasetId)

  return (
    <>
      <SectionLabel count={data?.recorded ? data.steps.length : undefined}>
        Signal chain
      </SectionLabel>
      <QueryState
        isLoading={isLoading}
        error={error}
        absenceTitle="Signal chain unavailable"
        errorTitle="Could not load the signal chain"
      />

      {data && !data.recorded && (
        <StateBox kind="empty" title="Preprocessing not recorded" detail={data.reason} />
      )}

      {data && data.recorded && (
        <div data-signal-chain className="space-y-2.5">
          {data.steps.map((step) => {
            const parameterEntries = Object.entries(step.parameters)
            return (
              <div key={step.step} data-step={step.step} data-ran={String(step.ran)}>
                <div className="flex items-baseline justify-between gap-3">
                  <span
                    className={cn(
                      'text-xs',
                      step.ran ? 'text-foreground' : 'text-muted-foreground',
                    )}
                  >
                    {STEP_LABEL[step.step] ?? step.step}
                  </span>
                  <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                    {step.ran ? 'ran' : 'not_run'}
                  </span>
                </div>
                {step.ran && parameterEntries.length > 0 && (
                  <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                    {parameterEntries
                      .map(([key, value]) => `${key}: ${String(value)}`)
                      .join(', ')}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </>
  )
}
