'use client'

import { SectionLabel } from '@/components/subterra/panel'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { useSignalChain } from '@/hooks/use-subterra'
import { cn } from '@/lib/utils'

const STEP_LABEL: Record<string, string> = {
  time_zero: 'Time zero',
  background_removal: 'Background removal',
  dewow: 'Dewow',
  gain: 'Gain',
  local_anomaly: 'Local anomaly (z-score)',
}

function formatParameters(parameters: Record<string, unknown>): string | null {
  const entries = Object.entries(parameters)
  return entries.length > 0
    ? entries.map(([key, value]) => `${key}: ${String(value)}`).join(', ')
    : null
}

/**
 * The Phase 5 recorded signal-processing chain, from
 * `GET /api/datasets/{id}/signal-chain`.
 *
 * READ, NOT RE-RUN. `time_zero` / `background_removal` / `dewow` / `gain` /
 * `local_anomaly`, in that order -- never a client-side default chain.
 * `ran` and `parameters` are read verbatim from the stored
 * `processing_applied` entry, a converter's own recorded time-zero claim, or
 * the local-anomaly stamp; a step this dataset's records never carried is
 * not invented, and a step that ran with no recorded parameter (the
 * boolean-only `background_removal`) shows none rather than a guess.
 *
 * `time_zero` is always the first step once the chain is recorded, even
 * when nothing else is known -- it is a property of the acquisition, not of
 * whether `process_gpr_traces` ran. Its `reason` says whether a converter
 * recorded and withheld a time-zero offset, or nothing about one was
 * recorded at all; either way `ran` stays false, because Subterra applies
 * no time-zero correction.
 *
 * `local_anomaly` is the opposite: it is OMITTED entirely unless
 * `preprocess_trace_local_anomaly` actually ran (that step overwrites
 * `record.signal` with a ring-statistic z-score). When present it is
 * `ran: true` with a `reason` stating plainly that this is a derived
 * statistic, not a physical unit -- the same sentence the provenance
 * projection gives this quantity, so a chain that includes this step cannot
 * be mistaken for one still showing gained amplitude.
 *
 * DELIBERATELY A SEPARATE, THIN CALL FROM THE DATASET REPORT. The report is
 * slow to build on a dataset of any size; this pane loads on every dataset
 * open, the same way `AcquisitionPane` and `SpatialAssessmentPane` do, and
 * both the report and this route derive from the same `build_signal_chain`
 * so they cannot disagree about what ran.
 *
 * `recorded: false` HAS TWO DIFFERENT CAUSES, and the title here is
 * deliberately neutral between them rather than guessing which applies: a
 * GPR dataset Subterra was simply never told about, or a dataset whose
 * recorded modality composition has no `gpr` in it at all, for which the
 * chain does not apply. Titling this "Preprocessing not recorded" would be
 * wrong for the second case -- it would read as an unlogged GPR chain on a
 * LiDAR tile or a DEM. No second vocabulary is invented to distinguish the
 * two: `data.reason` (the backend's own words, printed verbatim as the
 * `StateBox` detail) already says which one it is.
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
        <StateBox kind="empty" title="No signal chain" detail={data.reason} />
      )}

      {data && data.recorded && (
        <div data-signal-chain className="space-y-2.5">
          {data.steps.map((step) => {
            const parameters = formatParameters(step.parameters)
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
                {/*
                  `reason` is only ever populated for `time_zero`: `ran=false`
                  alone cannot say whether a converter recorded and withheld
                  an offset, or nothing was recorded about one at all. When
                  present it takes priority; the bare parameter line below is
                  for the other three steps, which have no reason to show.
                */}
                {step.reason ? (
                  <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                    {step.reason}
                    {parameters && ` — ${parameters}`}
                  </p>
                ) : (
                  parameters && (
                    <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                      {parameters}
                    </p>
                  )
                )}
              </div>
            )
          })}
        </div>
      )}
    </>
  )
}
